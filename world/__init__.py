# -*- coding: utf-8 -*-
"""世界观词条库（lorebook）：按关键词把设定注入上下文，不进人格、不占常驻 token。

做法照行业标准（SillyTavern 的 World Info / Lorebook）：
- 每条词条有 **keys（触发词）**，消息里出现才激活；``always: true`` 的常驻；
- **priority** 决定抢占预算的顺序，``order`` 决定同优先级内的插入顺序；
- 支持 **regex key**（形如 ``/卡数|算力/``）与 **递归引用**（内容里写 ``[[其他id]]``，
  预算够就把被引用的词条一起展开，只展开一层）；
- **预算按字符算**（token 的粗略代理），默认 1100 字符——宁可少说两条，
  也不要每轮多花几千 token。

数据放在同目录 ``entries/*.json``，改词条**只改 JSON**，不用碰代码，改完不用重启
（按文件 mtime 热加载）。
"""

from __future__ import annotations

import json
import os
import re
import threading

_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "entries")
_LOCK = threading.Lock()
_CACHE = {"mtime": 0.0, "entries": []}

DEFAULT_BUDGET = 1100


def _load():
    try:
        stamp = max(
            [os.path.getmtime(os.path.join(_DIR, name))
             for name in os.listdir(_DIR) if name.endswith(".json")] or [0.0]
        )
    except Exception:
        stamp = 0.0
    with _LOCK:
        if stamp and stamp == _CACHE["mtime"]:
            return _CACHE["entries"]
        entries = []
        try:
            names = sorted(n for n in os.listdir(_DIR) if n.endswith(".json"))
        except Exception:
            names = []
        for name in names:
            try:
                data = json.load(open(os.path.join(_DIR, name), encoding="utf-8"))
            except Exception:
                continue
            rows = data.get("entries") if isinstance(data, dict) else data
            for row in rows or []:
                if not isinstance(row, dict):
                    continue
                entry = dict(row)
                entry.setdefault("id", "")
                entry.setdefault("keys", [])
                entry.setdefault("content", "")
                entry.setdefault("priority", 50)
                entry.setdefault("order", 100)
                entry.setdefault("always", False)
                entry.setdefault("type", "term")
                entry["_source"] = name
                if entry["id"] and entry["content"]:
                    entries.append(entry)
        entries.sort(key=lambda e: (-int(e.get("priority") or 0), int(e.get("order") or 0)))
        _CACHE["mtime"] = stamp
        _CACHE["entries"] = entries
        return entries


def _key_hits(key, text):
    key = str(key or "").strip()
    if not key:
        return False
    if len(key) > 2 and key.startswith("/") and key.endswith("/"):
        try:
            return re.search(key[1:-1], text) is not None
        except Exception:
            return False
    return key.lower() in text.lower()


def match(text, limit=8):
    """只返回命中的词条（不拼文本），方便调试与测试。"""
    body = str(text or "")
    hits = []
    for entry in _load():
        if entry.get("always"):
            hits.append(entry)
            continue
        if any(_key_hits(k, body) for k in entry.get("keys") or []):
            hits.append(entry)
        if len(hits) >= limit * 2:
            break
    return hits


def _expand(entry, by_id, seen, depth=0):
    """把 [[其他id]] 展开一层（预算由调用方控制）。"""
    content = str(entry.get("content") or "")
    if depth >= 1:
        return content

    def repl(m):
        ref = by_id.get(m.group(1))
        if not ref or ref["id"] in seen:
            return ""
        seen.add(ref["id"])
        return _expand(ref, by_id, seen, depth + 1)

    return re.sub(r"\[\[([\w\-]+)\]\]", repl, content)


def scan(text, budget=DEFAULT_BUDGET, limit=6):
    """把命中的词条拼成一段可注入文本；没命中返回空串。"""
    entries = match(text, limit=limit)
    if not entries:
        return ""
    by_id = {e["id"]: e for e in _load()}
    seen = set()
    lines = []
    used = 0
    for entry in entries[:limit]:
        if entry["id"] in seen:
            continue
        seen.add(entry["id"])
        kind = entry.get("type")
        head = "" if kind == "rule" else ("◇ " if kind == "event" else "· ")
        piece = head + _expand(entry, by_id, seen)
        if used + len(piece) > budget:
            break
        used += len(piece)
        lines.append(piece)
    if not lines:
        return ""
    return "【世界设定】（后台资料，只照着做，不许念出来）\n" + "\n".join(lines)


def dump():
    """调试用：打印全部词条 id、类型、优先级与触发词。"""
    for entry in _load():
        print("%-24s %-6s %-4s %s" % (
            entry["id"], entry.get("type"), entry.get("priority"),
            ",".join(str(k) for k in (entry.get("keys") or [])[:6])))
