# -*- coding: utf-8 -*-
"""Amo 终端 · text

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

from .deps import *  # noqa: F401,F403  用到：json, re, strip_pseudo_tags
__all__ = [
    "POS_WORDS",
    "NEG_WORDS",
    "ANGRY_WORDS",
    "SAD_WORDS",
    "AFFECTION_WORDS",
    "INSULT_WORDS",
    "truncate",
    "has_question",
    "sentiment",
    "_WORD_RE",
    "_CJK_RE",
    "tokens",
    "overlap",
    "json_extract_list",
    "json_extract",
    "CHAT_FORMAT_NOISE",
    "strip_chat_format",
    "clean_reply",
]

POS_WORDS = ("开心", "高兴", "哈哈", "笑死", "好耶", "喜欢", "爱你", "可爱", "棒", "不错",
             "太好了", "谢谢", "嘿嘿", "嘻嘻", "么么", "抱抱", "亲亲", "好吃", "好看")
NEG_WORDS = ("难过", "伤心", "哭", "烦", "累", "讨厌", "滚", "闭嘴", "无语", "失望",
             "委屈", "孤单", "想死", "崩溃", "气死", "不开心")
ANGRY_WORDS = ("滚", "闭嘴", "傻", "废物", "烦死", "气死", "去死", "恶心", "别烦", "有病")
SAD_WORDS = ("难过", "伤心", "想哭", "委屈", "孤单", "没人", "算了", "失望", "哭")
AFFECTION_WORDS = ("喜欢", "爱你", "想你", "抱抱", "亲亲", "贴贴", "宝贝", "老婆", "宝宝", "么么")
INSULT_WORDS = ("傻逼", "智障", "废物", "垃圾", "去死", "恶心", "滚")
def truncate(text, limit=120):
    text = str(text or "").replace("\n", " ").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + "…"
def has_question(text):
    if "?" in text or "？" in text:
        return True
    return any(word in text for word in (
        "吗", "呢", "怎么", "为什么", "啥", "什么", "哪", "多少", "几",
        "是不是", "能不能", "可不可以", "如何", "几点", "谁",
    ))
def sentiment(text):
    text = text or ""
    pos = sum(1 for word in POS_WORDS if word in text)
    neg = sum(1 for word in NEG_WORDS if word in text)
    angry = sum(1 for word in ANGRY_WORDS if word in text)
    sad = sum(1 for word in SAD_WORDS if word in text)
    aff = sum(1 for word in AFFECTION_WORDS if word in text)
    total = pos + neg
    score = 0.0 if total == 0 else (pos - neg) / float(total)
    return {
        "pos": pos, "neg": neg, "angry": angry, "sad": sad,
        "aff": aff, "insult": any(w in text for w in INSULT_WORDS),
        "score": score,
    }
_WORD_RE = re.compile(r"[a-zA-Z0-9_]{2,}")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]+")
def tokens(text):
    text = (text or "").lower()
    out = set()
    for word in _WORD_RE.findall(text):
        out.add(word)
    for run in _CJK_RE.findall(text):
        if len(run) == 1:
            out.add(run)
        for i in range(len(run) - 1):
            out.add(run[i:i + 2])
        for i in range(len(run) - 2):
            out.add(run[i:i + 3])
    return out
def overlap(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / float(max(1, min(len(a), len(b))))
def json_extract_list(text):
    """给“要一个数组”的场景用：json_extract 会先匹配 "{"，
    遇到 `[{...},{...}]` 只返回第一个对象，导致 extract_facts 永远拿到 dict → 返回 []。
    """
    if not text:
        return []
    raw = str(text).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    start, end = raw.find("["), raw.rfind("]")
    if start >= 0 and end > start:
        chunk = re.sub(r",\s*([}\]])", r"\1", raw[start:end + 1])
        try:
            data = json.loads(chunk)
            if isinstance(data, list):
                return data
        except Exception:
            pass
    data = json_extract(text)
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        return [data]
    return []
def json_extract(text):
    if not text:
        return None
    raw = str(text).strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    for opener, closer in (("{", "}"), ("[", "]")):
        start = raw.find(opener)
        if start < 0:
            continue
        depth = 0
        in_string = False
        escaped = False
        for index in range(start, len(raw)):
            char = raw[index]
            if in_string:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    in_string = False
                continue
            if char == '"':
                in_string = True
            elif char == opener:
                depth += 1
            elif char == closer:
                depth -= 1
                if depth == 0:
                    chunk = raw[start:index + 1]
                    chunk = re.sub(r",\s*([}\]])", r"\1", chunk)
                    try:
                        return json.loads(chunk)
                    except Exception:
                        break
    return None
CHAT_FORMAT_NOISE = re.compile(
    r"@\s*([^\s（(]+)\s*[（(]\s*QQ\s*[:：]?\s*\d+\s*[）)]"
    r"|[（(]\s*QQ\s*[:：]?\s*\d+\s*[）)]"
    r"|\bQQ\s*[:：]?\s*\d{4,}\b"
    r"|@\s*([^\s，。！？!?、；;：:]+)",
    re.I,
)
def strip_chat_format(text):
    """去掉模型复述的 @昵称(QQ号)、QQ号等后台格式，保留自然称呼。"""
    value = str(text or "")
    value = CHAT_FORMAT_NOISE.sub(lambda m: (m.group(1) or m.group(2) or "").strip(), value)
    value = re.sub(r"[（(]\s*[）)]", "", value)
    value = re.sub(r"[ \t]{2,}", " ", value)
    return value.strip()
def clean_reply(text, limit=300):
    if not text:
        return ""
    text = strip_chat_format(str(text).strip())
    text = strip_pseudo_tags(text)
    text = re.sub(r"^(?:Amo|amo|核心|我|助手|assistant|AI|机器人)\s*[:：]\s*", "", text)
    if len(text) >= 2 and text[0] in "\"'“‘" and text[-1] in "\"'”’":
        text = text[1:-1]
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:limit]
