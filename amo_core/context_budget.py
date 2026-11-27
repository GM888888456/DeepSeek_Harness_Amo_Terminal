# -*- coding: utf-8 -*-
"""轻量上下文预算器：事实源查询结果优先，LLM 只拿本轮需要的数据。"""
from __future__ import annotations
import re

_DYNAMIC_PREFIXES = (
    "【正在】","【天气】","【身体】","【生理期】","【心情】",
    "【关于对方的记忆】","【最近对话】","【今日世界】","【世界",
    "【景区参考】","【天气查询】","【手边的事】","【关系网】",
    "【跨平台】","【时间回看】","【在路上】","【今天的路】",
    "【他在】","【他在外地】",
)
_LOW_VALUE_MARKERS = (
    "以上全是后台给你看的设定","不要主动报日程","一句都不许念出来",
    "别写旁白","一条只讲一件事",
)

def _norm(text):
    return re.sub(r"\s+","",str(text or "")).strip()

def compact_parts(parts, max_chars=9000):
    """去重、优先动态事实、硬预算；不调用模型、不生成事实。"""
    if not parts:
        return []
    seen=set(); dynamic=[]; normal=[]; low=[]
    for raw in parts:
        value=str(raw or "").strip()
        if not value: continue
        key=_norm(value)
        if not key or key in seen: continue
        seen.add(key)
        if any(value.startswith(p) for p in _DYNAMIC_PREFIXES):
            dynamic.append(value)
        elif any(m in value for m in _LOW_VALUE_MARKERS):
            low.append(value)
        else:
            normal.append(value)
    out=[]; used=0
    for value in dynamic+normal+low:
        cost=len(value)
        if used+cost<=max_chars:
            out.append(value); used+=cost; continue
        remain=max_chars-used
        if remain>=120:
            out.append(value[:remain].rstrip()+"…")
        break
    return out

__all__=["compact_parts"]
