# -*- coding: utf-8 -*-
"""Amo 终端 · 人格与景区知识库（PersonaMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., PersonaMixin, Star) 混入，self.* 照旧可用。

注意：常量/工具只在这里或 amo_core 里有一份，不要在 main.py 再定义一份。
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

from .shared import *

def extract_persona_name(persona):
    """Amo 终端 · 人格与景区知识库（PersonaMixin）"""
    if not persona:
        return ""
    name = ""
    prompt = ""
    try:
        name = str(persona.get("name") or "").strip()
        prompt = str(persona.get("prompt") or "")
    except Exception:
        name = str(getattr(persona, "name", "") or "").strip()
        prompt = str(getattr(persona, "prompt", "") or "")
    generic = {"default", "assistant", "系统默认", "默认", "bot", "ai"}
    if name and name.lower() not in generic and not re.fullmatch(r"[0-9a-fA-F-]{8,}", name):
        return name[:30]
    patterns = (
        r"你的名字(?:是|叫|为)\s*[「“\"']?([\u4e00-\u9fa5A-Za-z0-9_·]{1,16})",
        r"你叫(?:做)?\s*[「“\"']?([\u4e00-\u9fa5A-Za-z0-9_·]{1,16})",
        r"你名叫\s*[「“\"']?([\u4e00-\u9fa5A-Za-z0-9_·]{1,16})",
        r"名为\s*[「“\"']?([\u4e00-\u9fa5A-Za-z0-9_·]{1,16})",
        r"你是\s*[「“\"']?([\u4e00-\u9fa5A-Za-z0-9_·]{1,16})",
    )
    blocked = {"一个", "一名", "一位", "个人", "人", "你", "我", "他", "她", "这个", "那个"}
    for pattern in patterns:
        for match in re.finditer(pattern, prompt):
            candidate = str(match.group(1) or "").strip("「」“”\"' ")
            if (
                candidate and candidate not in blocked
                and not candidate.startswith(("一个", "一名", "一位", "个", "人"))
            ):
                return candidate[:30]
    return ""
def extract_persona_aliases(persona, name=""):
    """从人格文本里抠出「别名 / 昵称」那一行，返回能叫她的称呼列表。

    2026-11-20 用户口径：别名要用**人格里写的那一套**，不能只固定一个。
    人格里是这样写的：``别名：晓沫；沫沫；沫酱；沫子``
    """
    prompt = ""
    if persona:
        try:
            prompt = str(persona.get("prompt") or "")
        except Exception:
            prompt = str(getattr(persona, "prompt", "") or "")
    if not prompt:
        return []
    out = []
    pattern = re.compile(r"(?:别名|别称|昵称|小名|外号|称呼)\s*[:：]\s*([^\n]{1,140})")
    for match in pattern.finditer(prompt):
        for item in re.split(r"[；;、,，/|]+", match.group(1)):
            text = str(item).strip(" 「」“”\"'。.·-—")
            if not text or len(text) > 12 or text == name or text in out:
                continue
            out.append(text)
            if len(out) >= 12:
                return out
    return out


class PersonaMixin:

    async def _persona_name_for(self, umo=""):
        """读取当前会话的人格名；读不到时返回空字符串。"""
        if not self.cfg_bool("use_persona_name", True):
            return ""
        key = str(umo or "default")
        cached = self._persona_name_cache.get(key)
        if cached and now_ts() - cached[0] < 300:
            return cached[1]
        name = extract_persona_name(await self._resolve_persona(umo))
        self._persona_name_cache[key] = (now_ts(), name)
        return name

    async def _persona_names_for(self, umo=""):
        """返回 (名字, 别名列表)：别名取人格里「别名：…」那一行 + 配置里的 bot_aliases。"""
        use = self.cfg_bool("use_persona_name", True)
        persona = await self._resolve_persona(umo) if use else None
        name = extract_persona_name(persona) if use else ""
        aliases = extract_persona_aliases(persona, name) if use else []
        for item in self.cfg_str("bot_aliases", "").split(","):
            item = str(item or "").strip()
            if item and item not in aliases:
                aliases.append(item)
        return name, aliases


    def scenic_spots(self):
        if getattr(self, "_scenic_cache", None):
            return self._scenic_cache
        try:
            path = os.path.join(self.plugin_dir, "scenic_spots.json")
            with open(path, encoding="utf-8") as stream:
                data = json.load(stream)
            self._scenic_cache = data if isinstance(data, list) else []
        except Exception as exc:
            logger.warning("[amo] 读取景区数据失败: %s" % exc)
            self._scenic_cache = []
        return self._scenic_cache

    def _scenic_kb_name(self):
        name = self.cfg_str("scenic_kb_name", "旅游知识库-风景区").strip()
        if not name or name in ("中国景区知识库", "景区知识库"):
            return "旅游知识库-风景区"
        return name

    def _scenic_text_lines(self):
        lines = []
        for spot in self.scenic_spots():
            if not isinstance(spot, dict):
                continue
            projects = spot.get("projects") if isinstance(spot.get("projects"), list) else []
            lines.append(
                "景区：%s\n城市：%s·%s\n等级：%s\n游玩项目：%s\n建议时长：%s\n区域：%s" % (
                    spot.get("name", ""), spot.get("province", ""), spot.get("city", ""),
                    spot.get("level", ""), "、".join(str(item) for item in projects),
                    spot.get("duration", ""), spot.get("area", ""),
                )
            )
        return lines

    async def _ensure_scenic_kb(self):
        if not self.cfg_bool("create_scenic_kb", True):
            return None
        try:
            manager = getattr(self.context, "kb_manager", None)
            if manager is None:
                logger.warning("[amo] 当前 AstrBot 没有 kb_manager，景区知识库未创建")
                return None
            if callable(manager) and not hasattr(manager, "create_kb"):
                manager = manager()
            name = self._scenic_kb_name()
            kb = await manager.get_kb_by_name(name)
            if kb is None:
                providers = list(self.context.get_all_embedding_providers() or [])
                if not providers:
                    logger.warning("[amo] 没有 Embedding 供应商，景区知识库未创建")
                    return None
                provider_id = str(getattr(providers[0], "provider_config", {}).get("id", "") or "")
                if not provider_id:
                    try:
                        provider_id = str(providers[0].meta().id or "")
                    except Exception:
                        provider_id = ""
                if not provider_id:
                    logger.warning("[amo] Embedding 供应商没有有效 id，景区知识库未创建")
                    return None
                created = manager.create_kb(
                    name,
                    "中国 3A 级以上景区、所在城市与具体游玩项目",
                    emoji="🏞️",
                    embedding_provider_id=provider_id,
                )
                kb = await created if inspect.isawaitable(created) else created
            lines = self._scenic_text_lines()
            if lines:
                try:
                    docs = await kb.list_documents(search="amo_scenic")
                    for doc in docs or []:
                        doc_id = getattr(doc, "doc_id", "") or getattr(doc, "id", "")
                        if doc_id:
                            await kb.delete_document(doc_id)
                except Exception:
                    pass
                try:
                    await kb.upload_document(
                        "amo_scenic_spots.txt",
                        "\n\n".join(lines).encode("utf-8"),
                        "txt",
                    )
                except Exception as exc:
                    logger.warning("[amo] 景区知识库上传失败: %s" % exc)
            logger.debug("[amo] 景区知识库 %s 已同步，共 %d 个景区" % (name, len(lines)))
            return kb
        except Exception as exc:
            logger.warning("[amo] 景区知识库创建失败: %s" % exc)
            return None

    async def _scenic_kb_context(self, query):
        try:
            manager = getattr(self.context, "kb_manager", None)
            if manager is None or not str(query or "").strip():
                return ""
            name = self._scenic_kb_name()
            kb = await manager.get_kb_by_name(name)
            if kb is None:
                return ""
            result = await manager.retrieve(str(query)[:400], [name], top_m_final=4)
            return str(result.get("context_text") or "") if isinstance(result, dict) else ""
        except Exception as exc:
            logger.debug("[amo] 景区知识库检索失败: %s" % exc)
            return ""


__all__ = [
"extract_persona_name",
    "extract_persona_aliases",
    "PersonaMixin",
]
