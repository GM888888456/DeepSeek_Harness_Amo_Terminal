# -*- coding: utf-8 -*-
"""群聊认人：谁是机器人、谁是谁、这句话是不是冲她说的。

移植自上游 `CAIHONHUPUP/Astrbot_amoupup_forever` 的 `amo_group_guard.py`
（2026-11-23）。只保留纯函数 + 一份内存名册，不碰 AstrBot 事件对象，方便单测。

三条原则（原作者的，和我们目标一致）：
1. 别的机器人发的话只当背景，不判定、不接话；
2. 群成员按 uid 记名字，认人时用名册里的名字当证据；
3. 没有「对她说」的证据（@ / 引用 / 叫名字 / 接着她的话）就不算点名。

注意：这里只判「这句是不是冲她说的」，**不判要不要说话**——说不说仍然交给她自己
（免费小模型 + 说话欲）。所以我们的 `addressing_verdict` 只用它给出的 reason
（addressed / hard_other / soft_continue / not_addressed），不启用上游
"没叫就不开口" 的策略。
"""

from __future__ import annotations

import re
import time
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

#: 像机器人的昵称关键词：英文按独立单词匹配，中文按包含匹配。
#: 刻意不收「小爱/小冰/小微/助手」这类像真人昵称的词——误伤真人比漏认机器人严重。
DEFAULT_BOT_KEYWORDS: Tuple[str, ...] = (
    "bot", "robot", "assistant", "agent", "gpt", "chatgpt", "claude", "llm",
    "机器人", "小助手", "智能助手", "小爱同学", "天猫精灵",
)

_SPLIT_RE = re.compile(r"[,，;；\s]+")


def normalize_name(name: Any) -> str:
    """昵称归一：去掉空白，让「墨辞烟」和「墨 辞 烟」算同一个人。"""
    return re.sub(r"\s+", "", str(name or "")).strip()


def parse_keywords(raw: Any) -> Tuple[str, ...]:
    if isinstance(raw, str):
        items = [item.strip() for item in _SPLIT_RE.split(raw) if item.strip()]
    elif isinstance(raw, (list, tuple, set)):
        items = [str(item).strip() for item in raw if str(item).strip()]
    else:
        items = []
    return tuple(items) or DEFAULT_BOT_KEYWORDS


def parse_ids(raw: Any) -> Set[str]:
    if isinstance(raw, str):
        return {item.strip() for item in _SPLIT_RE.split(raw) if item.strip()}
    if isinstance(raw, (list, tuple, set)):
        return {str(item).strip() for item in raw if str(item).strip()}
    return set()


def is_bot_name(name: Any, keywords: Sequence[str] = DEFAULT_BOT_KEYWORDS) -> bool:
    """昵称像不像机器人：英文按独立单词，中文按包含。"""
    raw = str(name or "").strip()
    if not raw:
        return False
    lowered = raw.lower()
    compact = normalize_name(lowered)
    for keyword in keywords:
        word = str(keyword or "").strip().lower()
        if not word:
            continue
        if word.isascii():
            pattern = re.compile(r"(?<![a-z0-9])" + re.escape(word) + r"(?![a-z0-9])")
            if pattern.search(lowered):
                return True
        elif word in compact:
            return True
    return False


def is_bot_sender(sender_name: Any, sender_id: Any,
                  keywords: Sequence[str] = DEFAULT_BOT_KEYWORDS,
                  bot_ids: Sequence[str] = ()) -> bool:
    """这个发言人是不是别的机器人：先看显式账号名单，再看昵称。"""
    uid = str(sender_id or "").strip()
    if uid:
        for item in bot_ids:
            if str(item).strip() == uid:
                return True
    return is_bot_name(sender_name, keywords)


class MemberBook:
    """群成员名册（内存）：谁是谁、谁在说话、谁是机器人。"""

    def __init__(self, max_members: int = 120, ttl_seconds: int = 7 * 24 * 3600):
        self.max_members = max(8, int(max_members))
        self.ttl_seconds = max(60, int(ttl_seconds))
        self._groups: Dict[str, Dict[str, Dict[str, Any]]] = {}

    def observe(self, umo: Any, uid: Any, name: Any, is_bot: bool = False,
                now: Optional[float] = None) -> Optional[Dict[str, Any]]:
        group_key = str(umo or "").strip()
        user_key = str(uid or "").strip()
        if not group_key or not user_key:
            return None
        stamp = float(now) if now is not None else time.time()
        group = self._groups.setdefault(group_key, {})
        row = group.get(user_key)
        if row is None:
            row = {"uid": user_key, "name": "", "is_bot": False,
                   "first_seen": stamp, "last_seen": stamp, "count": 0}
            group[user_key] = row
        cleaned = normalize_name(name)
        if cleaned:
            row["name"] = cleaned
        row["is_bot"] = bool(row["is_bot"] or is_bot)
        row["last_seen"] = stamp
        row["count"] = int(row.get("count", 0)) + 1
        self._trim(group, stamp)
        return row

    def get(self, umo: Any, uid: Any) -> Optional[Dict[str, Any]]:
        return self._groups.get(str(umo or ""), {}).get(str(uid or ""))

    def members(self, umo: Any) -> List[Dict[str, Any]]:
        return list(self._groups.get(str(umo or ""), {}).values())

    def is_known_bot(self, umo: Any, uid: Any) -> bool:
        row = self.get(umo, uid)
        return bool(row and row.get("is_bot"))

    def display_name(self, umo: Any, uid: Any, fallback: str = "") -> str:
        row = self.get(umo, uid)
        if row and row.get("name"):
            return str(row["name"])
        return fallback

    def names(self, umo: Any, include_bots: bool = True) -> List[str]:
        rows = self._sorted_rows(umo)
        return [str(r["name"]) for r in rows
                if r.get("name") and (include_bots or not r.get("is_bot"))]

    def describe(self, umo: Any, limit: int = 12) -> str:
        rows = [r for r in self._sorted_rows(umo) if r.get("name")][:max(1, int(limit))]
        return "、".join(str(r["name"]) + ("（机器人）" if r.get("is_bot") else "") for r in rows)

    def bots(self, umo: Any) -> Set[str]:
        return {str(r["uid"]) for r in self.members(umo) if r.get("is_bot")}

    def mentioned_member(self, umo: Any, text: Any,
                         exclude: Sequence[str] = (),
                         exclude_uids: Sequence[str] = ()) -> Optional[Dict[str, Any]]:
        """消息里是否点名了名册里的某个群友（长名字优先）。"""
        compact = normalize_name(text)
        if not compact:
            return None
        skip_names = {normalize_name(i) for i in exclude if normalize_name(i)}
        skip_uids = {str(i).strip() for i in exclude_uids if str(i).strip()}
        rows = [r for r in self.members(umo) if r.get("name")]
        rows.sort(key=lambda item: -len(str(item.get("name") or "")))
        for row in rows:
            name = normalize_name(row.get("name"))
            if len(name) < 2 or name in skip_names or str(row.get("uid")) in skip_uids:
                continue
            if name in compact:
                return row
        return None

    def clear(self, umo: Any = None) -> None:
        if umo is None:
            self._groups.clear()
        else:
            self._groups.pop(str(umo or ""), None)

    def _sorted_rows(self, umo: Any) -> List[Dict[str, Any]]:
        return sorted(self.members(umo), key=lambda item: -float(item.get("last_seen") or 0))

    def _trim(self, group: Dict[str, Dict[str, Any]], now: float) -> None:
        expired = [uid for uid, row in group.items()
                   if now - float(row.get("last_seen") or 0) > self.ttl_seconds]
        for uid in expired:
            group.pop(uid, None)
        if len(group) <= self.max_members:
            return
        ordered = sorted(group.values(), key=lambda item: float(item.get("last_seen") or 0))
        for row in ordered[: len(group) - self.max_members]:
            group.pop(str(row.get("uid")), None)


def addressing_verdict(*, target: str, mentioning_bot: bool, hard: bool, soft: bool,
                       only_when_addressed: bool, forced: bool = False) -> Tuple[bool, str]:
    """她这次该不该开口（只判「是不是冲她说的」）。

    返回 (allowed, reason)：
    - forced：被连续打扰强制回复；
    - addressed：模型判成对她说，或明确在叫她；
    - hard_other：硬证据显示在 @/回复别人；
    - soft_continue：她在接自己刚说的话；
    - not_addressed：对全群/看不出对象。
    - gate_off：关掉「只在被叫到时回复」，恢复主动插话。
    """
    if forced:
        return True, "forced"
    if not only_when_addressed:
        return True, "gate_off"
    if mentioning_bot or str(target or "") == "bot":
        return True, "addressed"
    if hard:
        return False, "hard_other"
    if soft and str(target or "") not in ("other", "all"):
        return True, "soft_continue"
    return False, "not_addressed"
