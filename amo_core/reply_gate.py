# -*- coding: utf-8 -*-
"""Amo 终端 · reply_gate

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

from .deps import *  # noqa: F401,F403  用到：random, re
from .text import *  # noqa: F401,F403  用到：has_question, overlap, sentiment, tokens, truncate
from .timeutil import *  # noqa: F401,F403  用到：_now, now_ts, quiet_now
from .util import *  # noqa: F401,F403  用到：clamp
__all__ = [
    "ReplyGate",
]

class ReplyGate:
    def __init__(self, plugin):
        self.p = plugin

    def activity(self, group_id):
        if not group_id:
            return 0.0
        cutoff = now_ts() - 300
        times = [item for item in self.p._group_times.get(group_id, []) if item >= cutoff]
        self.p._group_times[group_id] = times
        return len(times) / 5.0

    def score_group(self, umo, group_id, text, recent, directed, profile, snap):
        rec = [m for m in recent if m.get("role") == "user"][-6:]
        rec_text = " ".join([m.get("content", "") for m in rec])
        relevance = overlap(tokens(text), tokens(rec_text)) * 100.0
        if has_question(text):
            relevance += 12
        if "你" in text or any(alias and alias in text for alias in self.p.bot_aliases):
            relevance += 10
        if directed:
            relevance += 28
        relevance = clamp(relevance)

        # 心情不再进「要不要说话」的分数（2026-11-20 用户口径：让她自己判断，
        # 心情只影响态度和语气）。以前这里七项加权，精力一低 willingness 直接掉一半，
        # 被点名的群消息也经常不回。语气照旧走 state.tone_text()。
        willingness = 50.0
        relation = profile.get("relation", "普通")
        willingness += {"相恋": 22, "熟识": 10, "抵触": -30, "仇恨": -55}.get(relation, 0)
        phase = snap["period"]["phase"]
        willingness += {"排卵期": 6, "卵泡期": 3, "黄体期": -6, "月经期": -10}.get(phase, 0)
        if snap["health"]["sick"]:
            willingness -= 15
        hour = _now().hour
        if hour < 6:
            willingness -= 25
        last_reply = self.p._last_reply_at.get(umo, 0)
        if last_reply and now_ts() - last_reply < 25:
            willingness -= 22
        willingness = clamp(willingness)

        social = 72.0
        if len(text) < 2:
            social -= 20
        if re.search(r"https?://|www\.", text):
            social -= 35
        if re.search(r"(加群|代购|广告|优惠|返利|扫码|兼职)", text):
            social -= 45
        senti = sentiment(text)
        if senti["insult"]:
            social -= 40
        blocked = [word.strip() for word in self.p.cfg_str("blocked_words", "").split(",") if word.strip()]
        if any(word in text for word in blocked):
            social -= 50
        if directed:
            social += 10
        if has_question(text):
            social += 5
        social = clamp(social)

        timing = 60.0
        dt = now_ts() - last_reply if last_reply else 99999
        if dt < 15:
            timing -= 40
        elif dt < 45:
            timing -= 20
        elif dt < 120:
            timing -= 5
        elif dt > 300:
            timing += 15
        category = snap["activity"].get("category")
        if category == "sleep":
            timing -= 55
        elif category in ("work", "study"):
            timing -= 18
        rate = self.activity(group_id)
        if 2.0 <= rate <= 12.0:
            timing += 10
        elif rate > 20.0:
            timing -= 12
        if quiet_now(self.p.cfg_str("quiet_hours", "23:30-07:30")):
            timing -= 25
        timing = clamp(timing)

        last_two = [m for m in recent if m.get("role") == "user"][-2:]
        coherence = overlap(
            tokens(text), tokens(" ".join([m.get("content", "") for m in last_two]))
        ) * 100.0
        if directed:
            coherence += 18
        if re.search(r"(这个|那个|刚才|刚刚|上面|你说|你刚才)", text):
            coherence += 10
        if len(text) < 4:
            coherence -= 10
        coherence = clamp(coherence)

        weights = [
            self.p.cfg_float("gate_w_relevance", 0.30),
            self.p.cfg_float("gate_w_willingness", 0.25),
            self.p.cfg_float("gate_w_social", 0.15),
            self.p.cfg_float("gate_w_timing", 0.15),
            self.p.cfg_float("gate_w_coherence", 0.15),
        ]
        total_weight = sum(weights) or 1.0
        total = (
            relevance * weights[0] + willingness * weights[1]
            + social * weights[2] + timing * weights[3] + coherence * weights[4]
        ) / total_weight
        return {
            "relevance": round(relevance, 1),
            "willingness": round(willingness, 1),
            "social": round(social, 1),
            "timing": round(timing, 1),
            "coherence": round(coherence, 1),
            "total": round(clamp(total), 1),
        }

    def dynamic_threshold(self, activity, snap, profile):
        base = self.p.cfg_float("reply_threshold", 0)
        if base <= 0:
            legacy = self.p.cfg_float("base_reply_threshold", 0.55)
            base = legacy * 100 if legacy <= 1 else legacy
        base = clamp(base, 0, 100)

        if activity < 1:
            activity_delta = -8
        elif activity < 4:
            activity_delta = -2
        elif activity < 9:
            activity_delta = 3
        elif activity < 18:
            activity_delta = 8
        else:
            activity_delta = 12

        # 心情不再推高/压低门槛（同上）：这里只留活跃度、关系、身体、时段、天气。
        mood_delta = 0.0

        relation = profile.get("relation", "普通")
        relation_delta = {"相恋": -10, "熟识": -5, "抵触": 16, "仇恨": 36}.get(relation, 0)
        health_delta = 8 if snap["health"]["sick"] else 0
        phase = snap["period"]["phase"]
        period_delta = {"月经期": 6, "黄体期": 4, "排卵期": -3, "卵泡期": -1}.get(phase, 0)
        time_delta = 10 if _now().hour in (23, 0, 1, 2, 3, 4, 5) else 0
        weather_delta = 3 if snap["weather"].get("tag") in ("rain", "storm", "snow") else 0

        value = clamp(
            base + activity_delta + mood_delta + relation_delta
            + health_delta + period_delta + time_delta + weather_delta,
            20, 92,
        )
        return {
            "value": round(value, 1),
            "base": round(base, 1),
            "activity_delta": activity_delta,
            "mood_delta": round(mood_delta, 1),
            "relation_delta": relation_delta,
            "health_delta": health_delta,
            "period_delta": period_delta,
            "time_delta": time_delta,
            "weather_delta": weather_delta,
        }

    async def should_reply_group(self, umo, group_id, text, recent, directed, profile, snap):
        scores = self.score_group(umo, group_id, text, recent, directed, profile, snap)
        activity = self.activity(group_id)
        threshold = self.dynamic_threshold(activity, snap, profile)
        diff = scores["total"] - threshold["value"]

        if diff >= 0:
            probability = 0.92
        elif diff > -8:
            probability = 0.55 + diff * 0.045
        elif diff > -20:
            probability = 0.18 + (diff + 20) * 0.046
        else:
            probability = 0.03
        probability = clamp(probability, 0.01, 0.98)
        reply = random.random() < probability

        bot_recent = [m for m in recent[-5:] if m.get("role") == "bot"]
        if not directed and len(bot_recent) >= 2 and diff < 20:
            reply = False

        used_llm = False
        band = self.p.cfg_float("llm_gate_band", 10)
        if self.p.cfg_bool("enable_llm_gate", True) and abs(diff) <= band:
            question = (
                "群聊里刚刚有人说『" + truncate(text, 80) + "』。"
                "角色现在的心情是" + self.p.state.feel_word() + "，正在" + snap["activity"].get("activity", "休息") + "，"
                "和说话人的关系是" + profile.get("relation", "普通") + "。"
                "角色应该自然地插话回复吗？"
            )
            verdict = await self.p.llm.decide(
                umo, question,
                {
                    "recent": [m.get("content", "") for m in recent[-6:]],
                    "feel": snap.get("feel") or {},
                    "activity": snap["activity"],
                },
            )
            used_llm = True
            if verdict is not None:
                reply = verdict

        return {
            "reply": reply,
            "probability": round(probability, 2),
            "diff": round(diff, 1),
            "scores": scores,
            "threshold": threshold,
            "activity": round(activity, 2),
            "used_llm": used_llm,
            "directed": directed,
        }

    def private_probability(self, snap, profile):
        probability = 0.95
        category = snap["activity"].get("category")
        probability *= {
            "sleep": 0.02, "work": 0.42, "study": 0.50,
            "commute": 0.60, "meal": 0.85,
        }.get(category, 1.0)
        probability *= {
            "感冒": 0.55, "低烧": 0.35, "轻微不适": 0.70, "疲惫": 0.70,
        }.get(snap["health"]["status"], 1.0)
        probability *= {
            "月经期": 0.80, "黄体期": 0.90, "排卵期": 1.05,
        }.get(snap["period"]["phase"], 1.0)
        # 情绪一律不参与「要不要回私聊」（2026-11-20 用户口径：任何情绪只影响态度和语气，
        # 不阻止她要不要说话）。以前怒 >62 打七折、哀 >62 打八折，等于她一难过就不理人。
        # 语气、句子长短、要不要闹别扭，都在 tone_text() 和提示词里体现。
        try:
            if profile.get("uid") and self.p._depressed_active(str(profile.get("uid"))):
                probability *= 0.35
        except Exception:
            pass
        relation = profile.get("relation", "普通")
        if relation == "相恋":
            probability = max(probability, 0.90)
        elif relation == "仇恨":
            probability *= 0.20
        elif relation == "抵触":
            probability *= 0.45
        return clamp(probability, 0.0, 1.0)
