# -*- coding: utf-8 -*-
"""拟人打字延迟（抄自 SIiOC/astrbot-plugin-humanizer 的 typing.py，去掉 astrbot 依赖）。

原来终端里的算法是 `base + 每字 400ms + 标点`，再乘一个 uniform(0.85,1.2)：
每条都一样长、没有犹豫、没有长尾，反而是最像机器的部分。这里换成：

    · 阅读耗时（按他这条多长）+ 犹豫（长消息多犹豫）+ 打字（按回复字数）
    · 整体乘对数正态抖动，偶发长尾（去倒水 / 被喊走）
    · 深夜变慢（23-24 点 ×1.3，3-7 点 ×1.6）
    · **目标总延迟**语义：算出的是「他发来到我发出」的总时长，
      实际 sleep = 目标 − 已经耗掉的链路时间（settle_delay），
      链路本身已经够慢时就不再额外等。

纯标准库，可在服务器上直接单测。
"""

from __future__ import annotations

import math
import random
from typing import Optional

# ===================== 参数表（秒） =====================

# 阅读耗时：每字区间与总上限
READ_PER_CHAR_RANGE = (0.10, 0.20)
READ_MAX = 4.0

# 反应犹豫：基线区间；对方消息越长基线越高
HESITATE_BASE_RANGE = (0.8, 3.0)
HESITATE_LONG_INBOUND = 60
HESITATE_LONG_BONUS = (1.0, 2.5)

# 打字速度：每字耗时（约 1.5~4 字/秒），加起手耗时
TYPE_PER_CHAR_RANGE = (0.25, 0.60)
TYPE_BASE = (0.3, 1.2)

# 干扰事件长尾
INTERRUPT_PROB = 0.08
INTERRUPT_EXTRA_RANGE = (5.0, 20.0)

# 抖动
LOGNORMAL_SIGMA = 0.45

# 时段系数（本地小时）
NIGHT_SLOWDOWN = [
    (23, 24, 1.3),
    (0, 3, 1.3),
    (3, 7, 1.6),
]
DAY_FACTOR = 1.0

# 单轮总延迟上限
TOTAL_DELAY_CAP = 90.0

# 分段发送：后续条目间隙
SEGMENT_GAP_RANGE = (0.5, 3.0)
SEGMENT_GAP_LONG_PROB = 0.2
SEGMENT_GAP_LONG_RANGE = (4.0, 8.0)


def _lnsample(mean: float, rng: Optional[random.Random] = None) -> float:
    """对数正态采样：中位数 = mean，sigma 控制散布。"""
    r = rng or random
    return math.exp(math.log(max(mean, 1e-6)) + r.gauss(0, LOGNORMAL_SIGMA))


def _uni(lo: float, hi: float, rng: Optional[random.Random] = None) -> float:
    r = rng or random
    return r.uniform(lo, hi)


def time_factor(hour: Optional[int]) -> float:
    """按本地小时返回打字速度系数；hour 为 None 时不加成。支持跨午夜区间。"""
    if hour is None:
        return DAY_FACTOR
    try:
        hour = int(hour) % 24
    except (TypeError, ValueError):
        return DAY_FACTOR
    for lo, hi, fac in NIGHT_SLOWDOWN:
        if lo <= hi:
            if lo <= hour < hi:
                return fac
        elif hour >= lo or hour < hi:
            return fac
    return DAY_FACTOR


def compute_delay(
    reply_text: str,
    inbound_len: int = 0,
    hour: Optional[int] = None,
    rng: Optional[random.Random] = None,
) -> float:
    """算「他消息到达 → 我发出」的目标总延迟（秒），结果在 [0, TOTAL_DELAY_CAP]。"""
    inbound = max(0, int(inbound_len or 0))
    read = min(inbound * _uni(*READ_PER_CHAR_RANGE, rng=rng), READ_MAX)
    hes = _uni(*HESITATE_BASE_RANGE, rng=rng)
    if inbound >= HESITATE_LONG_INBOUND:
        hes += _uni(*HESITATE_LONG_BONUS, rng=rng)
    n_chars = len([c for c in str(reply_text or "") if not c.isspace()])
    typing = _uni(*TYPE_BASE, rng=rng) + n_chars * _uni(*TYPE_PER_CHAR_RANGE, rng=rng)
    base = read + hes + typing
    total = _lnsample(max(base, 0.5), rng=rng) * time_factor(hour)
    r = rng or random
    if r.random() < INTERRUPT_PROB:
        total += _uni(*INTERRUPT_EXTRA_RANGE, rng=rng)
    return max(0.0, min(total, TOTAL_DELAY_CAP))


def settle_delay(target_delay: float, elapsed: float) -> float:
    """目标总延迟减去本轮已自然耗时，下限 0（NaN 也按 0 处理）。"""
    target = float(target_delay or 0.0)
    elapsed = float(elapsed or 0.0)
    if target != target:
        target = 0.0
    if elapsed != elapsed:
        elapsed = 0.0
    return max(0.0, target - max(0.0, elapsed))


def segment_gap(
    index: int,
    rng: Optional[random.Random] = None,
    gap_range=SEGMENT_GAP_RANGE,
    long_prob=SEGMENT_GAP_LONG_PROB,
    long_range=SEGMENT_GAP_LONG_RANGE,
) -> float:
    """分段发送中第 index 条（0 为首条，无间隙）之前的间隙秒数。

    小概率「边想边打」拉长到 4~8 秒，其余 0.5~3 秒。
    """
    if index <= 0:
        return 0.0
    r = rng or random

    def _win(w, fallback):
        try:
            lo, hi = float(w[0]), float(w[1])
        except (TypeError, ValueError, IndexError):
            return fallback
        if lo <= 0 or hi <= 0:
            return fallback
        if lo > hi:
            lo, hi = hi, lo
        return (lo, hi)

    gap = _win(gap_range, SEGMENT_GAP_RANGE)
    lng = _win(long_range, SEGMENT_GAP_LONG_RANGE)
    try:
        p = float(long_prob)
    except (TypeError, ValueError):
        p = SEGMENT_GAP_LONG_PROB
    p = max(0.0, min(p, 1.0))
    if r.random() < p:
        return _uni(*lng, rng=rng)
    return _uni(*gap, rng=rng)


def first_wait(
    reply_text: str,
    inbound_text: str = "",
    hour: Optional[int] = None,
    elapsed: float = 0.0,
    cap: float = 28.0,
) -> float:
    """首条回复该等多久（已扣掉链路自然耗时，并受本轮预算 cap 约束）。"""
    target = compute_delay(reply_text, len(str(inbound_text or "")), hour)
    wait = settle_delay(target, elapsed)
    return max(0.0, min(wait, float(cap)))


__all__ = [
    "compute_delay",
    "settle_delay",
    "segment_gap",
    "time_factor",
    "first_wait",
    "TOTAL_DELAY_CAP",
]
