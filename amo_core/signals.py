# -*- coding: utf-8 -*-
"""他此刻的状态信号：在不在岗、睡没睡、在不在家。

为什么单独一个文件：这些词表以前散在 `presence.py`（睡/不在本地）和
`misc.py`（怎么告诉她）两处，各打各的补丁。2026-11-21 那天他说
「在宿舍没上班」，她照样问「下班没、到家没」——因为 away 只认「不上班」，
不认「没上班」，也不认「宿舍」，而这两个词表根本不在同一个地方。

规则分两层：
  1. 认词（这里）——高置信、零成本、毫秒级；词穷就直接加词，不用改逻辑。
  2. 判语义（调用方）——词表判不出来时才值得花一次模型调用，别在词表里堆正则。

`scan()` 返回结构化结果，`render_lines()` 决定怎么讲给她听。
"""

from __future__ import annotations

import re
import time

# ---- 词表（按语义分组，加说法只改这里）----

SLEEP_WORDS = (
    "要睡", "去睡", "睡觉", "睡了", "想睡", "困了", "困死",
    "眯一会", "眯一会儿", "躺一会", "躺一会儿", "晚安", "闭眼",
)

AWAY_WORDS = (
    "在外地", "出差", "不在家", "回不去", "放假", "休假", "年假", "请假",
    "不上班", "没上班", "没有上班", "不用上班", "今天休息", "休息一天", "在家休息",
    "在宿舍", "在寝室", "宿舍待着", "不出门",
)

AWAY_REGEX = (
    re.compile(r"明天.{0,6}早起"),
)

BUSY_WORDS = ("在忙", "忙着", "开会", "上课", "考试", "赶工")

# 时效：他说的话按「当天」有效，不能昨天说一句就永远不问
SLEEP_TTL_HOURS = 10
AWAY_TTL_SECONDS = 18 * 3600


def _hit(text: str, words, regex=()) -> bool:
    s = str(text or "")
    if not s:
        return False
    if any(w in s for w in words):
        return True
    return any(p.search(s) for p in regex)


def hit_sleep(text: str) -> bool:
    return _hit(text, SLEEP_WORDS)


def hit_away(text: str) -> bool:
    return _hit(text, AWAY_WORDS, AWAY_REGEX)


def hit_busy(text: str) -> bool:
    return _hit(text, BUSY_WORDS)


def scan(rows, now: float = 0.0, sleep_hours: int = SLEEP_TTL_HOURS,
         away_ttl: int = AWAY_TTL_SECONDS) -> dict:
    """从最近聊天里读他的状态。

    ``rows`` 只要 ``role`` / ``content`` / ``created_at`` 三个字段（多给不管）。
    返回 ``asleep / away / busy`` 与命中的原话、时间，供提示词引用。
    """
    now = float(now or time.time())
    flags = {
        "asleep": False, "sleep_text": "", "clock": "",
        "away": False, "away_text": "",
        "busy": False, "busy_text": "",
    }
    sleep_at = sleep_text = ""
    sleep_ts = away_ts = busy_ts = 0.0
    away_text = busy_text = ""

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("role") or "") != "user":
            continue
        content = str(row.get("content") or "").strip()
        if not content:
            continue
        try:
            when = float(row.get("created_at") or 0)
        except (TypeError, ValueError):
            when = 0.0
        if hit_sleep(content) and when >= sleep_ts:
            sleep_ts, sleep_text = when, content
        if hit_away(content) and when >= away_ts:
            away_ts, away_text = when, content
        if hit_busy(content) and when >= busy_ts:
            busy_ts, busy_text = when, content

    if sleep_text and (now - sleep_ts) <= max(1, int(sleep_hours)) * 3600:
        flags["asleep"] = True
        flags["sleep_text"] = sleep_text
        try:
            flags["clock"] = time.strftime("%H:%M", time.localtime(sleep_ts))
        except Exception:
            flags["clock"] = ""

    if away_text and (now - away_ts) <= int(away_ttl):
        flags["away"] = True
        flags["away_text"] = away_text

    if busy_text and (now - busy_ts) <= 6 * 3600:
        flags["busy"] = True
        flags["busy_text"] = busy_text

    return flags


def render_lines(flags: dict, clip: int = 30) -> list:
    """把状态讲成给模型的短提示（只有真命中才出，避免白占 token）。"""
    lines = []
    flags = flags or {}
    if flags.get("asleep"):
        text = str(flags.get("sleep_text") or "")[:clip]
        lines.append(
            "【他说要睡】%s 他说「%s」——他这会儿在睡或准备睡；别再问他下班、到家、吃没吃，"
            "也别催照片和正事，等他自己醒。" % (flags.get("clock") or "刚才", text)
        )
    if flags.get("away"):
        text = str(flags.get("away_text") or "")[:clip]
        lines.append(
            "【他今天不在岗】他说「%s」——今天不是照常上班的日子，别问下班没、到家没，"
            "也别把「你下班了吗」当开场。" % text
        )
    if flags.get("busy") and not flags.get("asleep"):
        text = str(flags.get("busy_text") or "")[:clip]
        lines.append("【他说在忙】他说「%s」——别连发、别催，等他说完。" % text)
    return lines


__all__ = [
    "AWAY_REGEX", "AWAY_WORDS", "SLEEP_WORDS", "BUSY_WORDS",
    "hit_away", "hit_busy", "hit_sleep", "render_lines", "scan",
]
