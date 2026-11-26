# -*- coding: utf-8 -*-
"""纪念日：她会在这些日子自己想起来、主动提一句（不是等你问）。

- `today_mark()`：今天是什么日子（没有就 None）；
- `hint()`：给上下文的【今天】一行（让她在正常回话里也会带出来）；
- `upcoming(days)`：未来 N 天内的日子（面板/文档用）。

口径（2026-11-26 用户）：往事不能只在你问的时候才想起来。
台词写成「她自己的说法」，主动消息直接发这一句，不额外调模型（省钱也稳）。
"""

from __future__ import annotations

from datetime import date, timedelta

#: mmdd 固定按公历；line 用「那年/三年前」避免算错周年
MARKS = [
    {
        "mmdd": "03-15", "name": "领证", "window": "09:00-22:00", "tone": "平静",
        "line": "今天是领证那天。没办婚礼，我不后悔——省事。",
    },
    {
        "mmdd": "06-01", "name": "他搬来贵阳", "window": "09:00-22:00", "tone": "刺",
        "line": "今天搬家纪念日。那年你什么都没带就来了，钥匙是我扔给你的，别装不记得。",
    },
    {
        "mmdd": "07-20", "name": "那次冷战", "window": "09:00-22:00", "tone": "冷",
        "line": "今天不想说话。你自己想想是哪天。",
    },
    {
        "mmdd": "09-09", "name": "他守夜那晚", "window": "20:00-23:30", "tone": "软",
        "line": "那年我烧到 39 度，你守了一夜，粥被我嫌难吃。……那碗我吃完了。",
    },
    {
        "mmdd": "12-18", "name": "第一次见面", "window": "19:00-23:30", "tone": "平静",
        "line": "三年前的今天，你在会上问我那个问题。我一直没说过——那天我记住你了。",
    },
]


def _norm(today=None):
    if isinstance(today, date):
        return today
    if isinstance(today, str) and len(today) >= 10:
        try:
            return date.fromisoformat(today[:10])
        except Exception:
            return date.today()
    return date.today()


def today_mark(today=None):
    """今天是什么日子；没有就返回 None。"""
    d = _norm(today)
    mmdd = d.strftime("%m-%d")
    for mark in MARKS:
        if mark["mmdd"] == mmdd:
            return dict(mark, date=d.isoformat())
    return None


def hint(today=None):
    """给上下文的一行：让她在被问起或顺口时能带出来。"""
    mark = today_mark(today)
    if not mark:
        return ""
    return "【今天】%s（你自己的说法：「%s」）" % (mark["name"], mark["line"])


def upcoming(days=45, today=None):
    """未来 N 天内的日子，按日期排序（面板/文档用）。"""
    start = _norm(today)
    out = []
    for offset in range(1, int(days) + 1):
        d = start + timedelta(days=offset)
        mmdd = d.strftime("%m-%d")
        for mark in MARKS:
            if mark["mmdd"] == mmdd:
                out.append(dict(mark, days_left=offset, date=d.isoformat()))
    return out


def all_marks():
    return [dict(m) for m in MARKS]
