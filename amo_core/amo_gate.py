# -*- coding: utf-8 -*-
"""回复闸门：多路判定之后决定「这条回不回、什么时候回」。

用户口径（2026-11-23）：
- 同时对 A、B 两条消息判定，按判定结果先后回话；
- 异群：后到那个群的回复加延迟，别两个群同时刷；
- 同群：只回最新一条，旧的作废；
- 点名：判定通过就回，不管是不是最新，也不排长队。

注意：本模块名故意不叫 reply_gate —— amo_core/reply_gate.py 是既有的
ReplyGate 评分类，main.py/shared.py 都在 import *，别混用。
"""

from __future__ import annotations

import time
from typing import Dict, Tuple

CROSS_GROUP_DELAY = 3.0
SAME_GROUP_DELAY = 0.0
MENTION_MAX_WAIT = 1.0

_latest: Dict[str, Tuple[str, float]] = {}
_last_sent: Dict[str, float] = {}
_last_any = 0.0
_last_umo = ""


def note_message(umo: str, token: str) -> None:
    if not umo or not token:
        return
    _latest[str(umo)] = (str(token), time.time())


def is_latest(umo: str, token: str) -> bool:
    cur = _latest.get(str(umo))
    return bool(cur and cur[0] == str(token))


def decide(umo: str, token: str, mention: bool = False) -> Tuple[str, float]:
    """返回 (动作, 待等秒数)。动作是 send 或 drop。"""
    global _last_any, _last_umo
    umo = str(umo or "")
    if not mention and token and not is_latest(umo, token):
        return "drop", 0.0
    wait = 0.0
    if _last_any > 0:
        gap = time.time() - _last_any
        need = CROSS_GROUP_DELAY if (_last_umo and _last_umo != umo) else SAME_GROUP_DELAY
        if gap < need:
            wait = need - gap
    if mention:
        wait = min(wait, MENTION_MAX_WAIT)
    return "send", max(0.0, wait)


def mark_sent(umo: str) -> None:
    global _last_any, _last_umo
    _last_any = time.time()
    _last_umo = str(umo or "")
    if umo:
        _last_sent[str(umo)] = _last_any


def reset() -> None:
    global _last_any, _last_umo
    _latest.clear()
    _last_sent.clear()
    _last_any = 0.0
    _last_umo = ""
