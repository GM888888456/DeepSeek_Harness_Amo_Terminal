# -*- coding: utf-8 -*-
"""Amo 终端 · util

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

from .deps import *  # noqa: F401,F403  用到：hashlib
from .consts import *  # noqa: F401,F403  用到：USAGE_DEFAULT_PRICES
__all__ = [
    "clamp",
    "to_int",
    "to_float",
    "md5_int",
    "_CATEGORY_FEEL_CACHE",
    "schedule_category_feel",
    "other_platform_bot_lines",
    "usage_cost",
    "uniq",
]

def clamp(value, low=0.0, high=100.0):
    try:
        value = float(value)
    except Exception:
        return float(low)
    return max(float(low), min(float(high), value))
def to_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default
def to_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default
def md5_int(text):
    return int(hashlib.md5(str(text).encode("utf-8")).hexdigest()[:8], 16)
_CATEGORY_FEEL_CACHE = None
def schedule_category_feel():
    """日程类别 → 每小时七情六欲增量（复用 schedule_engine.CATEGORY_FEEL）。"""
    global _CATEGORY_FEEL_CACHE
    if _CATEGORY_FEEL_CACHE is not None:
        return _CATEGORY_FEEL_CACHE
    table = {}
    try:
        from .schedule_engine import CATEGORY_FEEL as table
    except Exception:
        try:
            from schedule_engine import CATEGORY_FEEL as table
        except Exception:
            table = {}
    _CATEGORY_FEEL_CACHE = dict(table or {})
    return _CATEGORY_FEEL_CACHE
def other_platform_bot_lines(rows, umo, limit=3, platform=""):
    """从跨平台近聊里挑出「她自己说的、且不是当前会话」的几句话。

    主动消息以前只看当前会话的最近 12 句：QQ 上 08:48 说「等散会了跟你说」，
    之后一直没人说话，12:00 的主动消息就接着那场会往下说；与此同时飞书那边
    早就是「在便利店买饭」了。把她在别的平台刚说的话也放进去，两边才不会
    各讲各的故事（内容冲突时以当前状态为准，见 gen_proactive 的规则）。

    数据插件有的行没有 `umo`，所以再按 `platform` 兜一层，避免把本平台的
    话当成「另一边说过」。
    """
    umo = str(umo or "")
    platform = str(platform or "")
    out = []
    for row in rows or []:
        if str(row.get("role") or "") != "bot":
            continue
        if str(row.get("umo") or "") == umo:
            continue
        row_platform = str(row.get("platform") or "")
        if row_platform and platform and row_platform == platform:
            continue
        text = str(row.get("content") or "").strip().replace("\n", " ")
        if text:
            out.append(text)
    size = max(1, int(limit or 1))
    return out[-size:]
def usage_cost(usage, prices=None):
    """按空闲/高峰两档单价（元/百万 token）估算花费。"""
    table = dict(USAGE_DEFAULT_PRICES)
    if isinstance(prices, dict):
        for key, value in prices.items():
            try:
                table[key] = float(value)
            except (TypeError, ValueError):
                continue
    cost = 0.0
    for bucket, prefix in ((usage.get("peak") or {}, "peak"), (usage.get("idle") or {}, "idle")):
        cost += float(bucket.get("input_cached") or 0) * table["hit_" + prefix] / 1e6
        cost += float(bucket.get("input_miss") or 0) * table["miss_" + prefix] / 1e6
        cost += float(bucket.get("output") or 0) * table["out_" + prefix] / 1e6
    return round(cost, 6)

def uniq(items):
    out = []
    seen = set()
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out
