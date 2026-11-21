# -*- coding: utf-8 -*-
"""Amo 终端 · consts

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

from .deps import *  # noqa: F401,F403  用到：re
__all__ = [
    "PLUGIN_NAME",
    "SCHEDULE_VERSION",
    "OUTFIT_VERSION",
    "DIARY_WARM_VERSION",
    "SICK_STATUSES",
    "USAGE_DEFAULT_PRICES",
    "FRAGMENT_TAIL_RE",
    "DIALECT_SAMPLES",
]

PLUGIN_NAME = "Astrbot_Amo_forever"
SCHEDULE_VERSION = "backbone-v6"
OUTFIT_VERSION = "outfit-v11"  # 穿搭规则变了就改这里，旧日程会自动重配
DIARY_WARM_VERSION = "diary-v3"  # 小日记规则变了就改这里，会重新预生成
SICK_STATUSES = ("轻微不适", "感冒", "低烧", "发烧", "不舒服", "生病", "拉肚子")
USAGE_DEFAULT_PRICES = {
    "hit_peak": 0.04, "hit_idle": 0.02,
    "miss_peak": 2.0, "miss_idle": 1.0,
    "out_peak": 8.0, "out_idle": 4.0,
}
FRAGMENT_TAIL_RE = re.compile(
    r"(跟|和|与|对|给|被|让|冲|朝|向)[^，。、~\s]{0,2}"
    r"(闲聊|聊|说|讲话|说话|待着|待|一起|走|吃|喝)"
    r"(两句|几句|一会儿|一下|一会|半天|会儿)?$")

DIALECT_SAMPLES = {
    "贵州话": "晓得、咋个、要得、安逸",
    "东北话": "咋整、唠嗑、得瑟、麻溜",
    "四川话": "啥子、莫得、巴适、搞快些",
    "广东话": "唔该、点解、得闲、搞掂",
    "台湾腔": "酱紫、蛮、超赞、拍谢",
    "天津话": "嘛呢、倍儿、哏儿、得嘞",
    "河南话": "弄啥嘞、中、得劲、木有",
    "上海话": "阿拉、侬、哪能、老灵",
}
