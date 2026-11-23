# -*- coding: utf-8 -*-
"""Amo 终端 · llm_service

从 main.py 平移而来（阶段 1 拆分），函数体与原文逐行一致，不要在这里改行为。
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import inspect
import json
import math
import os
import random
import re
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone

try:
    from astrbot.api import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("amo_terminal")

from .deps import *  # noqa: F401,F403  用到：_pg_analyze_rows, _pg_compose_task, _pg_near_duplicate, logger
from .text import *  # noqa: F401,F403  用到：clean_reply, json_extract, json_extract_list, truncate
from .timeutil import *  # noqa: F401,F403  用到：now_ts, today_str
from .util import *  # noqa: F401,F403  用到：other_platform_bot_lines, to_int
__all__ = [
    "LLMService",
]

class LLMService:
    def __init__(self, plugin):
        self.p = plugin
        self.context = plugin.context
        self._persona_cache = {}

    async def persona(self, umo=""):
        key = umo or "default"
        cached = self._persona_cache.get(key)
        if cached and now_ts() - cached[0] < 300:
            return cached[1]
        prompt = ""
        manager = getattr(self.context, "persona_manager", None)
        if manager is not None:
            try:
                persona = await manager.get_default_persona_v3(umo or None)
                if isinstance(persona, dict):
                    prompt = persona.get("prompt") or ""
                else:
                    prompt = getattr(persona, "prompt", "") or ""
            except Exception as exc:
                logger.debug("[amo] 读取 AstrBot 人格失败: %s" % exc)
        if not prompt:
            try:
                cfg = self.context.get_config(umo or None)
                personas = cfg.get("persona", []) if cfg else []
                if isinstance(personas, list) and personas:
                    prompt = personas[0].get("prompt", "") or ""
            except Exception:
                pass
        if not prompt:
            prompt = "你是一个生活在中国城市的普通女孩，有工作、有情绪、有自己的生活，说话自然口语化。"
        extra = self.p.cfg_str("persona_extra", "")
        if extra:
            prompt += "\n" + extra
        try:
            name = await self.p._persona_name_for(umo)
            if name and name not in prompt[:240]:
                prompt = "你的名字是" + name + "。\n" + prompt
        except Exception:
            pass
        self._persona_cache[key] = (now_ts(), prompt)
        return prompt

    async def provider(self, umo=""):
        try:
            if hasattr(self.context, "get_using_provider_async"):
                return await self.context.get_using_provider_async(umo or None)
            return self.context.get_using_provider(umo or None)
        except Exception as exc:
            logger.warning("[amo] 获取对话模型失败: %s" % exc)
            return None

    async def chat_raw(self, umo, system, prompt, contexts=None, kind="other"):
        provider = await self.provider(umo)
        if provider is None:
            return ""
        try:
            response = await provider.text_chat(
                # AstrBot 4.29.4：不传就是 0，会被兜成 1 还打 WARN；这里显式给 2
                request_max_retries=2,
                prompt=prompt,
                system_prompt=system,
                contexts=contexts or [],
            )
        except Exception as exc:
            logger.error("[amo] LLM 调用失败: %s" % exc)
            return ""
        self.p._record_tokens(kind, provider, response)
        return str(getattr(response, "completion_text", "") or "").strip()

    async def chat(self, umo, system, prompt, contexts=None, limit=300, kind="other"):
        return clean_reply(await self.chat_raw(umo, system, prompt, contexts, kind=kind), limit)

    async def decide(self, umo, question, state):
        service = getattr(self.context, "decision", None)
        if service is not None:
            try:
                return bool(await service.yes_no(
                    question=question, state=state, threshold=0.5, default=None
                ))
            except Exception as exc:
                logger.debug("[amo] Decision 判断不可用: %s" % exc)
        answer = await self.chat(
            umo, "你是一个判断器，只输出 yes 或 no。",
            question + "\n只输出 yes 或 no。", limit=8,
        )
        if not answer:
            return None
        answer = answer.strip().lower()
        return answer.startswith("y") or answer.startswith("是") or answer.startswith("对")

    async def gen_worldview(self, umo, persona):
        system = "你是一个世界观设定师。只输出 JSON，不要输出其他文字。"
        prompt = (
            "根据下面的人格设定，为这个角色生成一个真实可信的现代生活世界观。\n"
            "人格设定：\n" + truncate(persona, 1500) + "\n\n"
            "输出 JSON 对象，字段：name(角色名), age(整数), city(城市), occupation(职业), "
            "workplace(工作或学习地点), personality(性格一句话), hobbies(字符串数组), "
            "daily_life(日常生活一段话), world_rules(这个世界和人设的规则一段话), "
            "summary(50字内总结)。"
        )
        raw = await self.chat_raw(umo, system, prompt)
        data = json_extract(raw)
        if not isinstance(data, dict):
            return None
        hobbies = data.get("hobbies")
        if not isinstance(hobbies, list):
            hobbies = [str(hobbies)] if hobbies else []
        return {
            "name": str(data.get("name") or self.p.bot_name),
            "age": to_int(data.get("age"), 22),
            "city": str(
                data.get("city")
                or self.p.cfg_str("weather_city_name", "")
                or self.p.cfg_str("weather_city", "贵阳")
            ),
            "occupation": str(data.get("occupation") or "普通上班族"),
            "workplace": str(data.get("workplace") or "公司"),
            "personality": str(data.get("personality") or "温柔敏感"),
            "hobbies": [str(item)[:20] for item in hobbies[:5]],
            "daily_life": str(data.get("daily_life") or ""),
            "world_rules": str(data.get("world_rules") or ""),
            "summary": str(data.get("summary") or ""),
        }

    async def gen_proactive(self, umo, profile, snap, kind):
        name = profile.get("alias") or profile.get("name") or "你"
        relation = profile.get("relation", "普通")
        system = (
            await self.persona(umo) + "\n\n"
            + self.p.state.prompt_text(snap, with_activity=True) + "\n"
            + self.p.state.tone_text(snap, relation) + "\n"
            "规则：你就是角色本人，只输出要发出去的消息。\n"
            "此刻在做什么以上面「你此刻在…」为准；和之前说的不一样就自然改口（「会开完了」）。"
        )
        try:
            rows = self.p._recent(umo, 12)
        except Exception:
            rows = []
        analysis = _pg_analyze_rows(rows, now=now_ts()) if _pg_analyze_rows else {
            "context_text": "",
            "unanswered_text": "",
            "unanswered_seconds": 0.0,
            "unanswered_at": 0.0,
            "recent_bot_texts": [],
        }
        # 她刚在另一个平台（QQ / 飞书）说过的话也带上：只看本会话的话，
        # 另一边早就改口了，这边还在接上一场开会。
        other_bot = []
        uid = str(profile.get("uid") or "")
        if uid:
            try:
                other_bot = other_platform_bot_lines(
                    await self.p._recent_by_uid(uid, 12, ""), umo,
                    platform=str(umo).split(":", 1)[0],
                )
            except Exception as exc:
                logger.debug("[amo] 取跨平台近聊失败: %s" % exc)
                other_bot = []
        if other_bot:
            analysis["recent_bot_texts"] = list(analysis.get("recent_bot_texts") or []) + list(other_bot)
            system = system + (
                "\n【你刚在别的平台说过】\n"
                + "\n".join("· " + str(item)[:120] for item in other_bot)
                + "\n（这些是你在另一个平台刚说的话，不是他说的，别复述、别重复；"
                "和此刻状态对不上就以此刻为准。）"
            )
        window = max(0, self.p.cfg_int("proactive_unanswered_window_minutes", 30)) * 60
        limit = self.p.cfg_int("max_reply_chars", 220)
        # 记忆只来自记忆库（Astr_Amo_data）；主动消息也带上，免得她说得像个陌生人
        memory_text = ""
        try:
            uid = str(profile.get("uid") or "")
            if uid:
                _, memory_text = await self.p._recall(uid, "", None)
        except Exception:
            memory_text = ""
        if memory_text:
            system = system + "\n【关于他的记忆】\n" + memory_text
        try:
            his_lines = self.p._his_state_lines(umo)
        except Exception:
            his_lines = []
        if his_lines:
            system = system + "\n" + "\n".join(his_lines)
        try:
            presence = self.p._his_presence_line(str(profile.get("uid") or ""), umo)
        except Exception:
            presence = ""
        if presence:
            system = system + "\n" + presence
        try:
            relation_network = self.p._relation_network_text(str(profile.get("uid") or ""))
        except Exception:
            relation_network = ""
        if relation_network:
            system = system + "\n【关系网】\n" + relation_network
        try:
            trip = self.p.db.kv_get("wander_trip", {}) or {}
            if (
                isinstance(trip, dict) and trip.get("city") and not trip.get("announced")
                and str(trip.get("day") or "") <= today_str() <= str(trip.get("return_day") or "")
            ):
                spots = trip.get("spots") or []
                spot = str(spots[0]) if spots else ""
                system = system + (
                    "\n【旅游中】你现在一个人在 " + str(trip["city"]) + " 旅游"
                    + ("，今天去了" + spot if spot else "")
                    + "。主动跟他分享今天看到的、吃到的、天气；别报公司/上班，也别编景点。"
                )
        except Exception:
            pass

        def build_task(duplicate_hint=""):
            if not _pg_compose_task:
                return "你突然想起" + name + "，想主动发一条消息。"
            event_text = ""
            if kind == "share":
                try:
                    event_text = self.p.state.interesting_event()
                except Exception:
                    event_text = ""
            try:
                dialect_enabled = bool(self.p._dialect_active())
            except Exception:
                dialect_enabled = False
            try:
                avoid_work = bool(self.p._his_state_flags(umo).get("away"))
            except Exception:
                avoid_work = False
            return _pg_compose_task(
                kind=kind,
                name=name,
                unanswered_text=analysis["unanswered_text"],
                unanswered_seconds=analysis["unanswered_seconds"],
                window_seconds=window,
                recent_bot_texts=analysis["recent_bot_texts"],
                interesting_event=event_text,
                duplicate_hint=duplicate_hint,
                dialect_style=self.p.cfg_str("dialect_style", ""),
                dialect_enabled=dialect_enabled,
                avoid_work_questions=avoid_work,
            )

        def build_prompt(task):
            prompt = "这是私聊。请以角色身份主动发一条消息，" + task + " 1 到 2 句，口语化。"
            if analysis["context_text"]:
                prompt = "最近私聊记录：\n" + analysis["context_text"] + "\n\n" + prompt
            if memory_text:
                prompt = "你记得关于他的事：\n" + memory_text + "\n\n" + prompt
            return prompt

        text = await self.chat(umo, system, build_prompt(build_task()), limit=limit)
        if not _pg_near_duplicate or not self.p.cfg_bool("proactive_dedupe_enabled", True):
            return text
        threshold = self.p.cfg_float("proactive_dedupe_threshold", 0.62)
        hit = _pg_near_duplicate(text, analysis["recent_bot_texts"], threshold)
        if not hit:
            return text
        retry = await self.chat(
            umo, system, build_prompt(build_task(duplicate_hint=hit[0])), limit=limit,
        )
        if retry and not _pg_near_duplicate(retry, analysis["recent_bot_texts"], threshold):
            return retry
        logger.debug("[amo] 主动消息和最近的发言重复，跳过本次：%s" % str(text or retry or "")[:60])
        return ""

    async def extract_facts(self, umo, name, lines):
        system = "你是记忆提取器。只输出 JSON 数组。"
        prompt = (
            "从下面的聊天里提取关于用户“" + name + "”的长期事实。\n"
            "每行带说话人：[他] 是用户说的，[我] 是角色自己说的。只从 [他] 的行提取。\n"
            "值得长期记的：名字、生日、喜好、厌恶、居住地、工作或学校、宠物、年龄、计划、经历。\n"
            "位置写「他现在在X」；他说了搬/住/定居才写「他住在X」。\n"
            "content 用「他」开头（写「他脸疼」，不写「我脸疼」），不省主语。\n"
            "输出 JSON 数组，每项 content / kind(name,birthday,preference,place,work,pet,age,event) / "
            "tier(0 普通,1 重要,2 珍贵)；没有就输出 []。\n\n"
            "聊天记录：\n" + "\n".join(lines[-20:])
        )
        raw = await self.chat_raw(umo, system, prompt)
        data = json_extract_list(raw)
        if not isinstance(data, list):
            return []
        result = []
        for item in data:
            if not isinstance(item, dict):
                continue
            content = str(item.get("content", "")).strip()
            if len(content) < 2:
                continue
            # 兜底：模型偶尔仍会写成「我脸疼」/「被扇了耳光」这种没有主语或第一人称的句子，
            # 这种记忆注入后会被当成角色自己的经历（就是"幻视"）。这里统一补成第三人称。
            if content.startswith(("我", "你")):
                content = "他" + content[1:]
            elif not content.startswith(("他", "她", "用户", name or "\u0000")):
                content = "他" + content
            result.append({
                "content": content[:80],
                "kind": str(item.get("kind", "fact"))[:20],
                "tier": to_int(item.get("tier"), 1),
            })
        return result[:8]
