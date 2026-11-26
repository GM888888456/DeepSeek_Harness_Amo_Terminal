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
