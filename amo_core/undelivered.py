# -*- coding: utf-8 -*-
"""发不出去的主动消息先存着，等下一次有事件上下文时补发。

为什么需要：`aiocqhttp` 的 `call_action` 在没有事件上下文、又有多条 API 连接时
选不出该用哪个 bot，直接抛 `ApiNotAvailable`（2026-11-28 日志里那条）。
后台定时任务天生没有事件上下文，所以主动消息**不可能**保证发得出去——
但可以做到不丢：存起来，等他下次说话时用 `event.send()`（有连接、有 self_id）补发。

存储：kv 键 `amo_undelivered`，最多留 3 条、24 小时过期（过期就丢，别拿昨天的情绪今天发）。
"""

from __future__ import annotations

import time

KV_KEY = "amo_undelivered"
#: 最多留几条（多了就不像「刚才想说的一句」了）
MAX_ITEMS = 3
#: 多久之内的还算数（秒）
TTL = 24 * 3600


def _load(db):
    try:
        items = db.kv_get(KV_KEY, []) or []
    except Exception:
        return []
    return [item for item in items if isinstance(item, dict)]


def _save(db, items):
    try:
        db.kv_set(KV_KEY, list(items)[-MAX_ITEMS:])
        return True
    except Exception:
        return False


def enqueue(db, umo, text, ts=None) -> bool:
    """存一条待补发的消息。"""
    content = str(text or "").strip()
    if not content:
        return False
    items = _load(db)
    items.append({"umo": str(umo or ""), "text": content, "ts": float(ts or time.time())})
    return _save(db, items)


def pop_for(db, umo, now=None) -> list:
    """取出某个会话待补发的消息（过期的顺手清掉）。"""
    stamp = float(now or time.time())
    key = str(umo or "")
    items = _load(db)
    fresh = [item for item in items if stamp - float(item.get("ts") or 0) <= TTL]
    keep, taken = [], []
    for item in fresh:
        if str(item.get("umo") or "") == key:
            taken.append(item)
        else:
            keep.append(item)
    if len(keep) != len(items) or taken:
        _save(db, keep)
    return taken


def all_items(db, now=None) -> list:
    """只读：看现在积压了什么（诊断用）。"""
    stamp = float(now or time.time())
    return [item for item in _load(db) if stamp - float(item.get("ts") or 0) <= TTL]


def queue(plugin, umo, text, log=None) -> bool:
    """发不出去时存起来（plugin 上取 db）。"""
    db = getattr(plugin, "db", None)
    if db is None:
        return False
    ok = enqueue(db, umo, text)
    if ok and log is not None:
        try:
            log.info("[amo] 主动消息没发出去，先存着（等下次有事件上下文补发）：%s"
                     % str(text)[:30])
        except Exception:
            pass
    return ok


async def flush(plugin, event, log=None) -> int:
    """有事件上下文时补发（用 event.send，带 self_id，不会 ApiNotAvailable）。"""
    db = getattr(plugin, "db", None)
    umo = str(getattr(event, "unified_msg_origin", "") or "")
    if db is None or not umo:
        return 0
    items = pop_for(db, umo)
    if not items:
        return 0
    sent = 0
    for item in items:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        try:
            try:
                from astrbot.api.message_components import Plain
                from astrbot.core.message.message_event_result import MessageChain
                await event.send(MessageChain([Plain(text)]))
            except Exception:
                await event.send(text)
            sent += 1
            if log is not None:
                log.info("[amo] 补发主动消息：%s" % text[:40])
        except Exception as exc:
            if log is not None:
                log.warning("[amo] 补发失败: %s: %r" % (type(exc).__name__, exc))
    return sent


__all__ = ["KV_KEY", "MAX_ITEMS", "TTL", "enqueue", "pop_for", "all_items"]
