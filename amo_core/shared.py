# -*- coding: utf-8 -*-
"""Amo 终端 · 共享底座（shared）

所有 mixin 模块统一从这里 import，避免「某个方法用了 HumanState / RELATIONS
却忘了 import」这种只在运行时才炸的坑（2026-11-20 踩过一次）。
只导基础模块，不导 mixin，避免循环。
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

from .deps import *
from .consts import *
from .text import *
from .timeutil import *
from .util import *
from .amo_db import *
from .human_state import *
from .llm_service import *
from .reply_gate import *

_AUTO_NOTE_RE = re.compile(r"^(?:画像|记忆)\s*\d+\s*条", re.I)

def _looks_auto_note(text) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    if "memory companion" in value.lower():
        return True
    return bool(_AUTO_NOTE_RE.match(value))

FORCED_ON_CONFIG_KEYS = frozenset({
    "enable_group_reply", "enable_private_reply",
    "diary_enabled", "usage_stats_enabled",
})

RELATIONS = ("仇恨", "抵触", "普通", "熟识", "相恋")

DIALECT_REGIONS = {
    "贵州话": "贵州",
    "东北话": "东北",
    "四川话": "四川",
    "广东话": "广东",
    "台湾腔": "台湾",
    "天津话": "天津",
    "河南话": "河南",
    "上海话": "上海",
}

NETWORK_RELATIONS = ("家人", "恋人", "朋友", "同事", "同学", "熟人", "陌生人", "仇人")

INTERNAL_RELATION_NODES = ("bot", "self")

USAGE_PEAK_HOURS = ((9, 12), (14, 18))

def usage_clock(now=None, step: int = 15):
    """今天 24 小时的峰谷分段 + 此刻状态（面板画进度条用）。

    每 ``step`` 分钟取一次，跟着 ``usage_is_peak`` 走，以后改计价规则不用改前端。
    """
    now = now or _now()
    segments = []
    for minute in range(0, 24 * 60, step):
        sample = now.replace(hour=minute // 60, minute=minute % 60, second=0, microsecond=0)
        peak = bool(usage_is_peak(sample.timestamp()))
        if segments and segments[-1]["peak"] == peak:
            segments[-1]["to"] = minute + step
        else:
            segments.append({"from": minute, "to": minute + step, "peak": peak})
    return {
        "now_minute": now.hour * 60 + now.minute,
        "now_peak": bool(usage_is_peak(now.timestamp())),
        "segments": segments,
        "note": "高峰：工作日 9-12、14-18；其余按空闲价",
    }

def usage_is_peak(ts):
    """北京时间工作日 9-12、14-18 为高峰；周末全天算空闲（法定节假日未处理）。"""
    try:
        dt = datetime.fromtimestamp(float(ts), timezone.utc) + timedelta(hours=8)
    except Exception:
        return False
    if dt.weekday() >= 5:
        return False
    return any(start <= dt.hour < end for start, end in USAGE_PEAK_HOURS)

def _usage_row_ts(start_time, created_at):
    try:
        value = float(start_time or 0)
        if value > 0:
            return value
    except Exception:
        pass
    try:
        dt = datetime.fromisoformat(str(created_at or "").strip())
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except Exception:
        return 0.0

def _empty_bucket():
    return {"calls": 0, "input_miss": 0, "input_cached": 0, "output": 0}

def summarize_token_usage(db_path, start_ts=None, end_ts=None, model_filter=None):
    """按 provider_stats 汇总 token。start_ts/end_ts 为 epoch 秒，None 表示不限。"""
    usage = _empty_bucket()
    usage.update({"cache_rate": 0.0, "peak": _empty_bucket(), "idle": _empty_bucket(), "by_model": {}})
    if not db_path or not os.path.exists(db_path):
        usage["error"] = "找不到 AstrBot 数据库"
        return usage
    try:
        conn = sqlite3.connect("file:%s?mode=ro" % str(db_path).replace("\\", "/"), uri=True)
    except Exception as exc:
        usage["error"] = "打开数据库失败: %s" % exc
        return usage
    try:
        rows = conn.execute(
            "SELECT provider_model, token_input_other, token_input_cached, token_output, "
            "start_time, created_at FROM provider_stats"
        ).fetchall()
    except Exception as exc:
        usage["error"] = "读取 provider_stats 失败: %s" % exc
        conn.close()
        return usage
    conn.close()

    for model, miss, cached, out, start_time, created_at in rows:
        model = str(model or "")
        if model_filter and model_filter not in model:
            continue
        ts = _usage_row_ts(start_time, created_at)
        if start_ts is not None and ts and ts < float(start_ts):
            continue
        if end_ts is not None and ts and ts >= float(end_ts):
            continue
        miss = int(miss or 0)
        cached = int(cached or 0)
        out = int(out or 0)
        usage["calls"] += 1
        usage["input_miss"] += miss
        usage["input_cached"] += cached
        usage["output"] += out
        bucket = usage["peak"] if usage_is_peak(ts) else usage["idle"]
        bucket["calls"] += 1
        bucket["input_miss"] += miss
        bucket["input_cached"] += cached
        bucket["output"] += out
        item = usage["by_model"].setdefault(model or "unknown", _empty_bucket())
        item["calls"] += 1
        item["input_miss"] += miss
        item["input_cached"] += cached
        item["output"] += out

    total_in = usage["input_miss"] + usage["input_cached"]
    usage["cache_rate"] = (usage["input_cached"] / total_in) if total_in else 0.0
    usage["by_model"] = [
        dict(model=key, **value) for key, value in
        sorted(usage["by_model"].items(), key=lambda kv: -(kv[1]["input_miss"] + kv[1]["input_cached"]))
    ]
    return usage



# 导出 shared 里实际存在的所有名字（含 _ 开头的），否则 mixin 里 `from .shared import *` 会漏掉 KIND_PHOTO 之类
__all__ = [n for n in list(globals()) if not n.startswith("__")]
