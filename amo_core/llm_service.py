# -*- coding: utf-8 -*-
"""Amo 终端 · llm_service

从 main.py 平移而来（阶段 1 拆分），函数体与原文逐行一致，不要在这里改行为。
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import inspect
import io
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

#: 插件名：人格档案缓存落在 plugin_data/<这个名字>/ 下（和 amo_forever.db 同级）
PLUGIN_NAME = "DeepSeek_Harness_Amo_Terminal"
__all__ = [
    "LLMService",
]

# 辅助任务（机械活）**不写死任何 provider id**：一律看配置 `aux_provider_<kind>`。
#
# 2026-11-28（用户口径）：写死的那几条全删了。原因很实在——11-27 一天里三个 provider
# 被删、11-28 主模型也换了，写死的 id 只带来两个后果：日志里天天刷 "provider not found"，
# 辅助调用悄悄退化成主模型还不自知。
#
# 现在的规则：
# - 配置 `aux_provider_polish` / `aux_provider_judge` / `aux_provider_extract`
#   可以写逗号分隔的多个 id，按顺序取第一个可用的；
# - **留空就走主模型**（写作类本来就该走主模型：一天一两次，省不出钱还会写平）；
# - 换模型、删供应商都不用改代码。
AUX_KINDS = ("polish", "judge", "extract")

#: 只把「同一件事的不同叫法」归到上面三类，别把写作类也塞进来
AUX_ALIASES = {
    "rewrite": "polish", "humanize": "polish", "voice": "polish",
    "fact": "extract", "facts": "extract",
}

class LLMService:
    def __init__(self, plugin):
        self.p = plugin
        self.context = plugin.context
        self._persona_cache = {}
        #: 人格档案（原始模板的字段索引）：300 秒内复用，解析结果同时落盘一份
        self._archive_cache = {}

    # ------------------------------------------------------------ 人格档案
    def _archive_path(self):
        """档案缓存落在插件数据目录：`plugin_data/<插件名>/persona_archive.json`。"""
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            base = get_astrbot_data_path()
        except Exception:
            base = ""
        if base:
            return os.path.join(base, "plugin_data", PLUGIN_NAME, "persona_archive.json")
        try:  # 拿不到框架路径时按插件目录上跳两级算（和 config_guard 同一套算法）
            try:
                from ..config_guard import fallback_data_dir
            except ImportError:
                from config_guard import fallback_data_dir  # type: ignore
            return os.path.join(
                fallback_data_dir(getattr(self.p, "plugin_dir", ""), PLUGIN_NAME),
                "persona_archive.json")
        except Exception:
            return ""

    async def persona_template(self, umo=""):
        """权威模板原文：配置的模板文件 > AstrBot 人格 > 空。返回 (原文, 来源)。"""
        path = str(self.p.cfg_str("persona_template_path", "") or "").strip()
        if path:
            try:
                with io.open(path, encoding="utf-8") as handle:
                    text = handle.read()
                if text.strip():
                    return text, "user_template_file"
            except Exception as exc:
                logger.warning("[amo] 人格模板文件读不了（%s）：%s" % (path, exc))
        manager = getattr(self.context, "persona_manager", None)
        if manager is not None:
            try:
                persona = await manager.get_default_persona_v3(umo or None)
                text = (persona.get("prompt") or "") if isinstance(persona, dict) \
                    else (getattr(persona, "prompt", "") or "")
                if str(text).strip():
                    return str(text), "user_template"
            except Exception as exc:
                logger.debug("[amo] 读取 AstrBot 人格失败: %s" % exc)
        return "", ""

    async def persona_archive(self, umo=""):
        """把权威模板解析成字段档案（不是改写过的散文）。拿不到就退上次缓存，再不行返回 None。"""
        key = umo or "default"
        cached = self._archive_cache.get(key)
        if cached and now_ts() - cached[0] < 300:
            return cached[1]
        try:
            from .persona_archive import parse, load_cache
        except ImportError:
            from persona_archive import parse, load_cache  # type: ignore

        text, source = await self.persona_template(umo)
        if text:
            archive = parse(text, source=source)
            if archive.names():
                path = self._archive_path()
                if path:
                    archive.save_cache(path)
                if archive.errors:
                    logger.warning("[amo] 人格档案里的空字段：%s" % ",".join(archive.errors))
                self._archive_cache[key] = (now_ts(), archive)
                return archive
        path = self._archive_path()
        archive = load_cache(path) if path else None
        if archive is not None:
            logger.warning("[amo] 人格模板读不到，用上次的解析缓存（%d 个字段）" % len(archive.names()))
            self._archive_cache[key] = (now_ts(), archive)
            return archive
        logger.warning("[amo] 人格档案不可用：没有模板也没有缓存，只能用最小身份")
        return None

    async def persona_answer(self, umo, text, budget=700):
        """按需检索：这句话问到的档案字段原文；没问到就返回空（不注入、不占 token）。"""
        try:
            archive = await self.persona_archive(umo)
        except Exception:
            return ""
        if archive is None:
            return ""
        try:
            return archive.answer(text, budget=budget)
        except Exception:
            return ""

    async def persona(self, umo=""):
        """每轮常驻的短核心（约 200 字）+ 可选 persona_extra。

        2026-11-28 规范：完整档案不再每轮注入（原来每轮白烧 3k 字 prefill）。
        详细字段走 `persona_answer()` 按需检索；档案拿不到时才退回完整核心。
        """
        key = umo or "default"
        cached = self._persona_cache.get(key)
        if cached and now_ts() - cached[0] < 300:
            return cached[1]

        extra = ""
        try:
            extra = str(self.p.cfg_str("persona_extra", "") or "").strip()
        except Exception:
            pass

        archive = None
        try:
            archive = await self.persona_archive(umo)
        except Exception as exc:
            logger.debug("[amo] 取人格档案失败: %s" % exc)

        if archive is not None:
            prompt = archive.resident_core()
            if extra:
                prompt += "\n" + extra[:400]
        else:
            # 模板和缓存都没有：用完整核心保底，绝不退回「普通女孩」这类通用模板
            try:
                try:
                    from .persona_core import build_persona
                except ImportError:
                    from persona_core import build_persona  # type: ignore
                prompt = build_persona(extra)
            except Exception:
                prompt = (
                    "你叫沈晓沫。你是中国计算智脑集团总裁，墨辞烟是你的丈夫，"
                    "你有自己的生活、事业、情绪和判断。以第一人称自然交流，"
                    "不要把自己理解为AI助手或正在扮演角色；不知道的不编。"
                )
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

    async def _provider_by_id(self, provider_id):
        getter = getattr(self.context, "get_provider_by_id", None)
        if not callable(getter):
            return None
        try:
            result = getter(str(provider_id))
            if hasattr(result, "__await__"):
                result = await result
            return result
        except Exception as exc:
            logger.debug("[amo] 取模型 %s 失败: %s" % (provider_id, exc))
            return None

    def _aux_ids(self, kind):
        """某个用途在配置里指定了哪些候选模型；没配返回空元组（= 用主模型）。"""
        try:
            conf = str(self.p.cfg_str("aux_provider_" + str(kind), "") or "").strip()
        except Exception:
            return ()
        return tuple(x.strip() for x in conf.replace("，", ",").split(",") if x.strip())

    async def _aux_provider(self, kind):
        """按用途挑小模型：只看 `aux_provider_<kind>` 配置，没配就返回 None（调用方用主模型）。"""
        for pid in self._aux_ids(kind):
            provider = await self._provider_by_id(pid)
            if provider is not None:
                return provider
        return None

    async def probe_all(self):
        """启动时探一遍辅助模型配置（缺了就在日志里说，不用等触发）。"""
        results = {}
        for kind in AUX_KINDS:
            ids = self._aux_ids(kind)
            if not ids:
                logger.info("[amo] 辅助模型 %-8s 未配置 → 走主模型" % kind)
                continue
            for pid in ids:
                if pid in results:
                    continue
                results[pid] = (await self._provider_by_id(pid)) is not None
        for pid, ok in sorted(results.items()):
            logger.info("[amo] 模型可用性 %-30s %s" % (pid, "OK" if ok else "缺失"))
        return results

    async def _probe_aux_once(self, kind):
        """第一次用到某个辅助用途时，把候选模型逐个探一遍，日志里能立刻看出缺谁。"""
        if getattr(self, "_aux_probed", None) is None:
            self._aux_probed = set()
        if kind in self._aux_probed:
            return
        self._aux_probed.add(kind)
        ids = self._aux_ids(kind)
        if not ids:
            logger.info("[amo] 辅助模型 %s：未配置，走主模型" % kind)
            return
        for pid in ids:
            provider = await self._provider_by_id(pid)
            logger.info("[amo] 辅助模型 %s（%s）-> %s" % (
                pid, kind, "OK" if provider is not None else "缺失"))

    async def chat_raw(self, umo, system, prompt, contexts=None, kind="other"):
        route = AUX_ALIASES.get(str(kind), str(kind))
        if route in AUX_KINDS:
            try:
                await self._probe_aux_once(route)
            except Exception:
                pass
        provider = await self._aux_provider(route)
        using_aux = provider is not None
        if provider is None:
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
            if not using_aux:
                return ""
            fallback = await self.provider(umo)
            if fallback is None or fallback is provider:
                return ""
            try:
                response = await fallback.text_chat(
                    request_max_retries=2,
                    prompt=prompt,
                    system_prompt=system,
                    contexts=contexts or [],
                )
                logger.info("[amo] 小模型失败，回退主模型（kind=%s）" % kind)
                provider = fallback
            except Exception as exc2:
                logger.error("[amo] 回退主模型也失败: %s" % exc2)
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
            question + "\n只输出 yes 或 no。", limit=8, kind="judge",
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
