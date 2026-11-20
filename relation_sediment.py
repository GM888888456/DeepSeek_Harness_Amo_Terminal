# -*- coding: utf-8 -*-
"""关系网自动沉淀：把「聊得多」「通过你认识」算成该写哪些边。

纯函数，不做任何 IO；落库、同步到数据终端由 main.py 负责。

分档（全部历史累计）：
- 0 条但有人物档案 / 1 条以上          → 陌生人（关系网的底，保证每个人都进图）
- ≥15 条且跨度 ≥2 天                  → 熟人
- ≥60 条且跨度 ≥7 天                  → 朋友
只升不降；管理员手设、家人/恋人/仇人不覆盖。
"""

from __future__ import annotations

import re

KEEP_RELATIONS = ("家人", "恋人", "仇人")
CLOSE_RELATIONS = ("熟人", "朋友")
HUMAN_TIER = {"陌生人": 0, "熟人": 1, "朋友": 2}


def note_kind(note):
    """note 来源：''=没边，auto=自动，infer=两跳推断，manual=管理员手设。"""
    text = str(note or "")
    if not text:
        return ""
    if text.startswith("自动："):
        return "auto"
    if text.startswith("推断："):
        return "infer"
    return "manual"


def auto_relation_for(count, span_days):
    """互动量 → 关系档位。

    2026-11-20 用户口径：聊过之后就该「认识」，靠聊天自己长关系网。
    原来要 15 条 + 跨 2 天才算熟人、60 条 + 跨 7 天才算朋友，群里永远一片
    「陌生人」（实测 190 条），两跳推断也就永远起不来。
    现在：聊过 3 句就当认识（熟人）；20 句且跨 2 天算朋友；60 句且跨 7 天维持朋友。
    """
    if count >= 20 or (count >= 60 and span_days >= 7):
        if count >= 20 and span_days >= 2:
            return "朋友"
        if count >= 60:
            return "朋友"
    if count >= 3:
        return "熟人"
    return "陌生人"


def _tier(relation):
    return HUMAN_TIER.get(str(relation or ""), 0)


def _pair(uid):
    return tuple(sorted(["bot", str(uid)]))


def _span_days(row):
    try:
        return (float(row.get("l") or 0) - float(row.get("f") or 0)) / 86400.0
    except (TypeError, ValueError):
        return 0.0


def _auto_note(count):
    if count <= 0:
        return "自动：在列表里"
    return "自动：累计 %d 条" % count


def plan_edges(stats, existing=None, names=None, infer_limit=5):
    """算出这一轮要写的关系边，返回 ``[(a_uid, b_uid, relation, note)]``。

    - ``stats``：[{"uid", "c", "f", "l"}]，来自本地 messages 表；
      只出现在人物列表、没聊过天的人用 ``c=0`` 传进来，也会记成「陌生人」；
    - ``existing``：{(a_uid, b_uid): (relation, note)}，已排序的边；
    - ``names``：{uid: 名字}，只用来写推断边的 note。
    """
    existing = dict(existing or {})
    names = dict(names or {})
    writes = {}
    bot_edges = {pair: value for pair, value in existing.items() if "bot" in pair}
    close = []
    for row in stats or []:
        uid = str(row.get("uid") or "")
        if not uid or uid == "bot":
            continue
        try:
            count = int(row.get("c") or 0)
        except (TypeError, ValueError):
            count = 0
        relation = auto_relation_for(count, _span_days(row))
        if relation in CLOSE_RELATIONS:
            close.append((uid, count))
        pair = _pair(uid)
        old_relation, old_note = existing.get(pair, ("", ""))
        if note_kind(old_note) == "manual" or old_relation in KEEP_RELATIONS:
            continue
        # 自动边只升不降：这阵子聊得少了，也不把「朋友」打回「熟人/陌生人」
        if old_relation == relation or _tier(old_relation) > _tier(relation):
            continue
        note = _auto_note(count)
        writes[pair] = (relation, note)
        bot_edges[pair] = (relation, note)

    # 两跳推断：只从「人和人之间的显式边」出发，bot 自己的边不参与；
    # 且只有已经处成熟人/朋友的用户，才把 TA 的朋友介绍给 bot
    human_edges = []
    for pair, (relation, note) in existing.items():
        if "bot" in pair or note_kind(note) == "infer":
            continue
        if relation in ("仇人", "陌生人"):
            continue
        human_edges.append((pair[0], pair[1]))

    limit = max(1, int(infer_limit or 1))
    for uid, _count in close:
        made = 0
        for a, b in human_edges:
            if made >= limit:
                break
            other = b if a == uid else (a if b == uid else "")
            if not other or other == "bot" or other == uid:
                continue
            pair = _pair(other)
            old_relation, old_note = bot_edges.get(pair, ("", ""))
            if old_relation or note_kind(old_note) == "manual":
                continue
            name = names.get(uid) or str(uid)
            note = "推断：经" + name + "认识"
            writes[pair] = ("朋友", note)
            bot_edges[pair] = ("朋友", note)
            made += 1

    return [(a, b, relation, note) for (a, b), (relation, note) in writes.items()]

#: 群聊里 @ 别人的写法（aiocqhttp 把 @ 渲染进正文）
_AT_RE = re.compile(r"\[At:(\d+)\]")


def guess_person_edges(rows, existing=None, min_hits=5, limit=20, name_map=None):
    """从群聊里「谁经常 @ 谁」推测人和人的边（低置信度）。

    - 只做人↔人，不碰 bot 自己；
    - 已经有的边（不管是手设还是自动）一律不覆盖；
    - note 一律带「推测：」，面板里能一眼看出是猜的、也能删；
    - 每次最多写 limit 条，避免一次刷爆关系图。

    ``rows``：[{uid, content, ...}]，一条消息一行。
    ``existing``：{(a_uid, b_uid)} 已经存在的边。
    """
    have = set()
    for pair in existing or ():
        try:
            a, b = pair
        except Exception:
            continue
        if a and b:
            have.add(tuple(sorted([str(a), str(b)])))
    # 名字 → uid：用于「这条消息提到了谁」的推测（存下来的正文没有 @ 标记）
    names = {}
    for name, target in (name_map or {}).items():
        name = str(name or "").strip()
        target = str(target or "").strip()
        if len(name) >= 2 and target and target != "bot":
            names[name] = target
    counter = {}
    for row in rows or []:
        uid = str(row.get("uid") or "")
        text = str(row.get("content") or "")
        if not uid or uid == "bot" or not text:
            continue
        targets = set(_AT_RE.findall(text))
        # 按名字提及：一条消息里出现谁的名字，就算跟谁互动一次
        for name, target in names.items():
            if target != uid and name in text:
                targets.add(target)
        for target in targets:
            target = str(target)
            if not target or target == uid or target == "bot":
                continue
            key = tuple(sorted([uid, target]))
            counter[key] = counter.get(key, 0) + 1
    writes = []
    for pair, hits in sorted(counter.items(), key=lambda kv: -kv[1]):
        if hits < max(1, int(min_hits or 1)):
            continue
        if pair in have:
            continue
        writes.append((pair[0], pair[1], "熟人", "推测：群里常互相提到 %d 次" % hits))
        if len(writes) >= max(1, int(limit or 1)):
            break
    return writes
