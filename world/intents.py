# -*- coding: utf-8 -*-
"""意图层：驱动越线后，她自己决定做点什么。

用户口径：「不设配额，全套做完整」——所以这里**没有每日上限**，只保留：
- 每个意图自己的冷却（同一件事别连着做）；
- 安静时段由调用方（心跳）判断（睡着不闹）。

意图清单（drives 里哪个越线就只有哪几个候选）：
- go_outside    出门/在庄园走走   ← boredom
- talk_to_him   找他说话          ← social
- send_photo    发张自拍          ← social / valued
- push_company  催一下公司的事     ← control

打分 = 触发驱动的超出量 × 权重；多个同时越线时按权重随机抽，不会一次干三件事。
"""

from __future__ import annotations

import random
import time as _time

INTENTS = [
    {"id": "go_outside", "name": "出门走走", "drives": ("boredom",),
     "min": 58, "weight": 3.0, "cooldown": 1500},
    {"id": "talk_to_him", "name": "找他说话", "drives": ("social",),
     "min": 60, "weight": 5.0, "cooldown": 1200},
    {"id": "send_photo", "name": "发张照片", "drives": ("social", "valued"),
     "min": 55, "weight": 2.5, "cooldown": 2400},
    {"id": "push_company", "name": "催一下公司的事", "drives": ("control",),
     "min": 68, "weight": 2.0, "cooldown": 3000},
]

BY_ID = {item["id"]: item for item in INTENTS}


def candidates(state, now=None):
    """返回 [(intent, score)]，按 score 降序；已冷却的不在内。"""
    now = float(now or 0) or _time.time()
    values = (state or {}).get("values") or {}
    last = (state or {}).get("last") or {}
    out = []
    for item in INTENTS:
        ready_at = float(last.get(item["id"]) or 0)
        if now - ready_at < float(item.get("cooldown") or 0):
            continue
        score = 0.0
        for name in item.get("drives") or ():
            value = float(values.get(name) or 0)
            over = value - float(item.get("min") or 60)
            if over <= 0:
                score = 0.0
                break
            score += over
        if score > 0:
            out.append((item, score * float(item.get("weight") or 1)))
    out.sort(key=lambda row: -row[1])
    return out


def pick(state, now=None, rng=None):
    """按权重抽一个；没有候选就返回 None。"""
    rng = rng or random
    rows = candidates(state, now=now)
    if not rows:
        return None
    total = sum(score for _, score in rows)
    if total <= 0:
        return None
    point = rng.random() * total
    acc = 0.0
    for item, score in rows:
        acc += score
        if point <= acc:
            return item
    return rows[-1][0]


def mark(state, intent_id, now=None):
    """记下这次做过，冷却从这里开始算。"""
    now = float(now or 0) or _time.time()
    state.setdefault("last", {})[str(intent_id)] = now
    return state


def explain(intent, state):
    """一句人话，给日志/上下文用。"""
    if not intent:
        return ""
    values = (state or {}).get("values") or {}
    drivers = "、".join("%s %.0f" % (d, float(values.get(d) or 0))
                        for d in intent.get("drives") or ())
    return "%s（因为 %s）" % (intent.get("name"), drivers)
