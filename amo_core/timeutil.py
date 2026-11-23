# -*- coding: utf-8 -*-
"""Amo 终端 · timeutil

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

from .deps import *  # noqa: F401,F403  用到：date, time, timedelta
__all__ = [
    "_now",
    "_clock_now",
    "_clock_configure",
    "_clock_name",
    "now_ts",
    "CN_HOLIDAYS",
    "SOLAR_TERMS",
    "day_meta",
    "today_str",
    "weekday_cn",
    "parse_hhmm",
    "minutes_now",
    "in_minute_range",
    "quiet_now",
]

# ---- 统一时区（原文同步）----
# 容器/服务器常在 UTC 跑，直接取服务器本地时间会把北京时间 10 点算成凌晨 2 点。
# 这里是全插件唯一一处解析 clock 模块；main.py 的 _clock_configure / _clock_name
# 也从这里出去，保证配置与读取用的是同一个模块对象。
try:
    from .. import clock as _clock_mod
except Exception:
    try:
        import clock as _clock_mod
    except Exception:
        _clock_mod = None

if _clock_mod is not None:
    _clock_now = _clock_mod.now
    _clock_configure = _clock_mod.configure
    _clock_name = _clock_mod.current_name
else:
    def _clock_now(*args, **kwargs):
        return datetime.now()

    def _clock_configure(*args, **kwargs):
        return ""

    def _clock_name(*args, **kwargs):
        return ""


def _now():
    """目标时区下的「现在」（naive，便于和原代码里 datetime 运算混用）。"""
    return _clock_now()

def now_ts():
    return time.time()
CN_HOLIDAYS = {
    "2025-01-01": "元旦",
    "2025-01-28": "除夕", "2025-01-29": "春节", "2025-01-30": "春节", "2025-01-31": "春节", "2025-02-01": "春节", "2025-02-02": "春节", "2025-02-03": "春节", "2025-02-04": "春节",
    "2025-04-04": "清明",
    "2025-05-01": "劳动节",
    "2025-05-31": "端午",
    "2025-10-01": "国庆", "2025-10-02": "国庆", "2025-10-03": "国庆", "2025-10-04": "国庆", "2025-10-05": "国庆", "2025-10-07": "国庆", "2025-10-08": "国庆",
    "2025-10-06": "国庆中秋",
    "2026-01-01": "元旦",
    "2026-02-16": "除夕", "2026-02-17": "春节", "2026-02-18": "春节", "2026-02-19": "春节", "2026-02-20": "春节", "2026-02-21": "春节", "2026-02-22": "春节", "2026-02-23": "春节",
    "2026-04-05": "清明",
    "2026-05-01": "劳动节",
    "2026-06-19": "端午",
    "2026-09-25": "中秋",
    "2026-10-01": "国庆", "2026-10-02": "国庆", "2026-10-03": "国庆", "2026-10-04": "国庆", "2026-10-05": "国庆", "2026-10-06": "国庆", "2026-10-07": "国庆",
    "2027-01-01": "元旦",
    "2027-02-05": "除夕", "2027-02-06": "春节", "2027-02-07": "春节", "2027-02-08": "春节", "2027-02-09": "春节", "2027-02-10": "春节", "2027-02-11": "春节",
    "2027-04-05": "清明",
    "2027-05-01": "劳动节",
    "2027-06-09": "端午",
    "2027-09-15": "中秋",
    "2027-10-01": "国庆", "2027-10-02": "国庆", "2027-10-03": "国庆", "2027-10-04": "国庆", "2027-10-05": "国庆", "2027-10-06": "国庆", "2027-10-07": "国庆",
}
SOLAR_TERMS = {
    "2025-01-05": "小寒", "2025-01-20": "大寒", "2025-02-03": "立春", "2025-02-18": "雨水", "2025-03-05": "惊蛰", "2025-03-20": "春分", "2025-04-04": "清明", "2025-04-20": "谷雨", "2025-05-05": "立夏", "2025-05-21": "小满", "2025-06-05": "芒种", "2025-06-21": "夏至", "2025-07-07": "小暑", "2025-07-22": "大暑", "2025-08-07": "立秋", "2025-08-23": "处暑", "2025-09-07": "白露", "2025-09-23": "秋分", "2025-10-08": "寒露", "2025-10-23": "霜降", "2025-11-07": "立冬", "2025-11-22": "小雪", "2025-12-07": "大雪", "2025-12-21": "冬至",
    "2026-01-05": "小寒", "2026-01-20": "大寒", "2026-02-04": "立春", "2026-02-18": "雨水", "2026-03-05": "惊蛰", "2026-03-20": "春分", "2026-04-05": "清明", "2026-04-20": "谷雨", "2026-05-05": "立夏", "2026-05-21": "小满", "2026-06-05": "芒种", "2026-06-21": "夏至", "2026-07-07": "小暑", "2026-07-23": "大暑", "2026-08-07": "立秋", "2026-08-23": "处暑", "2026-09-07": "白露", "2026-09-23": "秋分", "2026-10-08": "寒露", "2026-10-23": "霜降", "2026-11-07": "立冬", "2026-11-22": "小雪", "2026-12-07": "大雪", "2026-12-21": "冬至",
    "2027-01-05": "小寒", "2027-01-20": "大寒", "2027-02-04": "立春", "2027-02-19": "雨水", "2027-03-06": "惊蛰", "2027-03-21": "春分", "2027-04-05": "清明", "2027-04-20": "谷雨", "2027-05-06": "立夏", "2027-05-21": "小满", "2027-06-06": "芒种", "2027-06-21": "夏至", "2027-07-07": "小暑", "2027-07-23": "大暑", "2027-08-08": "立秋", "2027-08-23": "处暑", "2027-09-08": "白露", "2027-09-23": "秋分", "2027-10-08": "寒露", "2027-10-24": "霜降", "2027-11-08": "立冬", "2027-11-22": "小雪", "2027-12-07": "大雪", "2027-12-22": "冬至",
}
#: holiday_calendar.json 覆盖层：{日期: {name, rest}}；rest=false 是调休补班。
#: 缓存按 mtime 失效，改日历文件不用重启进程。
_CALENDAR_OVERLAY = {"mtime": None, "rest": {}, "work": {}}


def _calendar_overlay():
    """读插件目录下的 holiday_calendar.json；读不到就用空表，内置表照旧。"""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "holiday_calendar.json")
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}, {}
    if _CALENDAR_OVERLAY.get("mtime") == mtime:
        return _CALENDAR_OVERLAY["rest"], _CALENDAR_OVERLAY["work"]
    rest, work = {}, {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = json.load(handle) or {}
    except Exception:
        raw = {}
    for key, value in (raw or {}).items():
        day = str(key or "").strip()[:10]
        if len(day) != 10:
            continue
        if isinstance(value, dict):
            name = str(value.get("name") or "").strip()
            flag = value.get("rest", True)
        else:
            name, flag = str(value or "").strip(), True
        if flag is False:
            work[day] = name or "调休"
        else:
            rest[day] = name or "假日"
    _CALENDAR_OVERLAY.update({"mtime": mtime, "rest": rest, "work": work})
    return rest, work


def day_meta(day=None):
    """返回某天的节日、节气和上不上班：日历是唯一口径。

    ``rest`` 为真 = 休息日，``work`` 为真 = 工作日。周末、法定节假日、
    以及 holiday_calendar.json 里的调休补班（``rest: false``）都在这里判定；
    日程骨架、日子类型、文案都只认这一份结果，不许再各自按星期猜
    （2026-11-23：周一抽到宅家日，骨架全天在家、文案写在公司，照片就成了家里的自拍）。
    """
    try:
        target = date.fromisoformat(str(day)) if day else _now().date()
    except Exception:
        target = _now().date()
    key = target.isoformat()
    extra_rest, forced_work = _calendar_overlay()
    holiday = CN_HOLIDAYS.get(key, "") or extra_rest.get(key, "")
    term = SOLAR_TERMS.get(key, "")
    weekend = target.weekday() >= 5
    forced = key in forced_work
    rest = False if forced else bool(weekend or holiday)
    holiday_days = 0
    if holiday:
        cursor = target
        while CN_HOLIDAYS.get(cursor.isoformat()) == holiday:
            holiday_days += 1
            cursor -= timedelta(days=1)
        cursor = target + timedelta(days=1)
        while CN_HOLIDAYS.get(cursor.isoformat()) == holiday:
            holiday_days += 1
            cursor += timedelta(days=1)
    label = "、".join(item for item in (holiday, term) if item)
    if holiday_days >= 2:
        label += (" · " if label else "") + "%d天假期" % holiday_days
    if not label and weekend and not forced:
        label = "周末"
    return {
        "date": key,
        "weekday": "一二三四五六日"[target.weekday()],
        "weekend": weekend,
        "holiday": holiday,
        "solar_term": term,
        "holiday_days": holiday_days,
        "rest": rest,
        "work": not rest,
        "label": label,
    }
def today_str():
    return _now().date().isoformat()
def weekday_cn():
    return "一二三四五六日"[_now().date().weekday()]
def parse_hhmm(value, default=0):
    try:
        parts = str(value).strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception:
        return default
def minutes_now():
    dt = _now()
    return dt.hour * 60 + dt.minute
def in_minute_range(cur, start, end):
    if start == end:
        return True
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end
def quiet_now(spec):
    try:
        start, end = str(spec).split("-", 1)
        return in_minute_range(minutes_now(), parse_hhmm(start), parse_hhmm(end))
    except Exception:
        return False
