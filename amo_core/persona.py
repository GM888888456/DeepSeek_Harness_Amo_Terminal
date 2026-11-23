# -*- coding: utf-8 -*-
"""Amo 终端 · 人格·方言·景区知识库（PersonaMixin）

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

CITY_DIALECT_RULES = (
    (("贵阳", "贵州", "遵义", "安顺", "六盘水", "凯里"), "贵州话"),
    (("成都", "四川", "重庆", "绵阳", "德阳", "宜宾"), "四川话"),
    (("广州", "深圳", "东莞", "佛山", "珠海", "中山", "惠州", "江门", "汕头", "广东"), "广东话"),
    (("上海", "苏州", "无锡", "常州", "昆山"), "上海话"),
    (("天津",), "天津话"),
    (("郑州", "河南", "洛阳", "开封"), "河南话"),
    (("哈尔滨", "沈阳", "长春", "大连", "东北", "辽宁", "吉林", "黑龙江"), "东北话"),
    (("台北", "台湾", "高雄", "台中"), "台湾腔"),
)
def dialect_for_city(city):
    text = str(city or "")
    if not text:
        return ""
    for keys, style in CITY_DIALECT_RULES:
        if any(key in text for key in keys):
            return style
    return ""
DIALECT_FALLBACK_ROWS = {
    "东北话": [
        ("咋整", "怎么办", "咋整啊"), ("唠嗑", "聊天", "来唠嗑"), ("得瑟", "显摆", "别得瑟"),
        ("麻溜", "快点", "麻溜的"), ("贼拉", "非常", "贼拉冷"), ("嘎哈", "干什么", "你嘎哈呢"),
        ("老铁", "哥们", "老铁没毛病"),
    ],
    "四川话": [
        ("啥子", "什么", "你说啥子"), ("莫得", "没有", "莫得问题"), ("巴适", "舒服", "巴适得很"),
        ("搞快些", "快点", "搞快些"), ("瓜娃子", "傻孩子", "你个瓜娃子"), ("雄起", "加油", "雄起"),
        ("撇脱", "干脆", "撇脱点"),
    ],
    "广东话": [
        ("唔该", "谢谢、劳驾", "唔该晒"), ("点解", "为什么", "点解啊"), ("得闲", "有空", "得闲饮茶"),
        ("搞掂", "搞定", "搞掂啦"), ("靓仔", "帅哥", "靓仔"), ("靓女", "美女", "靓女"),
        ("冇", "没有", "冇问题"),
    ],
    "台湾腔": [
        ("酱紫", "这样", "酱紫啊"), ("蛮", "很", "蛮好的"), ("超赞", "非常棒", "超赞"),
        ("拍谢", "不好意思", "拍谢啦"), ("机车", "麻烦、烦人", "很机车"), ("阿嬷", "奶奶", "阿嬷"),
        ("龟毛", "挑剔", "别龟毛"),
    ],
    "天津话": [
        ("嘛呢", "干什么", "嘛呢"), ("倍儿", "非常", "倍儿好"), ("哏儿", "有趣", "真哏儿"),
        ("得嘞", "好的", "得嘞"), ("腻歪", "腻烦、黏人", "别腻歪"), ("幺蛾子", "麻烦", "出幺蛾子"),
        ("耐人", "招人喜欢", "真耐人"),
    ],
    "河南话": [
        ("弄啥嘞", "干什么", "你弄啥嘞"), ("中", "好", "中，就这么办"), ("得劲", "舒服", "真得劲"),
        ("木有", "没有", "木有事"), ("恁", "你", "恁吃饭没"), ("俺", "我", "俺知道了"),
        ("中不中", "行不行", "中不中"),
    ],
    "上海话": [
        ("阿拉", "我、我们", "阿拉晓得"), ("侬", "你", "侬好"), ("哪能", "怎么", "哪能办"),
        ("结棍", "厉害", "侬结棍"), ("老灵", "很好", "老灵额"), ("白相", "玩", "出去白相"),
        ("适意", "舒服", "适意"),
    ],
}
def extract_persona_name(persona):
    """从 AstrBot Personality 的 name / system prompt 中取角色名。"""
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

    def _dialect_rows(self):
        region = self._dialect_region()
        try:
            rows = [row for row in self.db.list_dialects() if region in str(row.get("region") or "")]
        except Exception:
            rows = []
        if rows:
            return rows
        style = self._dialect_style().strip()
        return [
            {"term": term, "meaning": meaning, "region": style, "example": example}
            for term, meaning, example in DIALECT_FALLBACK_ROWS.get(style, [])
        ]

    def _dialect_region(self):
        style = self._dialect_style().strip()
        return DIALECT_REGIONS.get(style, style)

    def _dialect_active(self):
        """方言是否生效：语种选「普通话」就等于关掉方言（连方言库都不查）。"""
        style = str(self.cfg_str("dialect_style", "") or "").strip()
        if style in ("普通话", "关闭", "off", "none"):
            return False
        return self.cfg_bool("dialect_enabled", True)

    def _dialect_style(self):
        """语种：配置里写了就用配置（面板可覆盖），没写就按世界观城市自动选。"""
        explicit = str(self.cfg_str("dialect_style", "") or "").strip()
        if explicit and explicit not in ("自动", "auto", "auto_city"):
            return explicit
        city = ""
        try:
            world = getattr(self.state, "worldview", None) or {}
            city = str(world.get("city") or "")
        except Exception:
            pass
        if not city:
            try:
                city = str(
                    self.cfg_str("weather_city_name", "")
                    or self.cfg_str("weather_city", "")
                    or ""
                )
            except Exception:
                pass
        return dialect_for_city(city)

    def _dialect_kb_name(self):
        base = self.cfg_str("dialect_kb_name", "陪伴方言库").strip() or "陪伴方言库"
        style = self._dialect_style().strip()
        return base + "-" + style if style else base

    async def _dialect_kb_context(self, query):
        # 关掉方言就别检索方言库：省一次 embedding 查询和一段提示词
        if not self._dialect_active():
            return ""
        try:
            manager = getattr(self.context, "kb_manager", None)
            if manager is None or not str(query or "").strip():
                return ""
            name = self._dialect_kb_name()
            kb = await manager.get_kb_by_name(name)
            names = [name]
            if kb is None:
                legacy = await manager.get_kb_by_name("核心方言库")
                if legacy is not None:
                    kb = legacy
                    names = ["核心方言库"]
            if kb is None:
                return ""
            result = await manager.retrieve(str(query)[:500], names, top_m_final=3)
            if not isinstance(result, dict):
                return ""
            return str(result.get("context_text") or "")
        except Exception as exc:
            logger.debug("[amo] 方言知识库检索失败: %s" % exc)
            return ""

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
    "CITY_DIALECT_RULES",
    "dialect_for_city",
    "DIALECT_FALLBACK_ROWS",
    "extract_persona_name",
    "extract_persona_aliases",
    "PersonaMixin",
]
