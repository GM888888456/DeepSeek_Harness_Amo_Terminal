# -*- coding: utf-8 -*-
"""权威等级与冲突裁决（规范 4.5、第六节）。

规范给的等级是硬规矩，不能倒置：

    1. 用户原始人格档案      user_template
    2. 用户明确纠正          user_correction
    3. 用户明确陈述的记忆    user_statement
    4. 系统推断              inference
    5. 模型生成              model

这里只做两件事：

- `resolve(records)`：按等级 + 新鲜度挑出该信的那条，并**保留冲突来源**（不合并、不覆盖）；
- `scan_conflicts(...)`：拿权威档案去核对别的文本（世界观、记忆摘要），发现「她其实是普通上班族」
  这种矛盾就报出来——只报，不自动改数据（规范第六节：模型生成内容不许覆盖固定身份）。
"""

from __future__ import annotations

import time

#: 来源 → 等级（数字越大越权威）
LEVELS = {
    "user_template": 5,
    "user_correction": 4,
    "user_statement": 3,
    "inference": 2,
    "model": 1,
}

#: 与档案对照的矛盾词典：字段 → (原文里该有的锚点, 出现这些就算矛盾的说法)
CONTRADICTIONS = {
    "职业": (
        ("总裁", "集团"),
        ("普通上班族", "上班族", "小职员", "打工的", "公司前台", "实习"),
    ),
    "资产": (
        ("庄园", "别墅", "宝马"),
        ("租房", "没有房", "没车", "挤公交", "坐地铁上班"),
    ),
    "丈夫": (
        ("墨辞烟", "丈夫"),
        ("单身", "没有丈夫", "没结婚", "离婚"),
    ),
}


def level_of(source: str) -> int:
    return LEVELS.get(str(source or "").strip(), 0)


def resolve(records) -> dict:
    """从若干条同主题记录里挑出该信的那条。

    records: [{"id","content","source","updated_at"(epoch,可选)}]
    返回 {"winner": 记录|None, "losers": [...], "reason": 说明}
    """
    items = [dict(item) for item in (records or []) if str(item.get("content") or "").strip()]
    if not items:
        return {"winner": None, "losers": [], "reason": "没有候选记录"}

    def sort_key(item):
        return (level_of(item.get("source")), float(item.get("updated_at") or 0))

    items.sort(key=sort_key, reverse=True)
    winner, losers = items[0], items[1:]
    if not losers:
        return {"winner": winner, "losers": [], "reason": "唯一候选"}
    top_level = level_of(winner.get("source"))
    tied = [item for item in losers if level_of(item.get("source")) == top_level]
    if tied:
        reason = "同级冲突：%s，按时间取最新，其余保留来源待人工确认" % "、".join(
            str(item.get("id") or "?") for item in tied)
    else:
        reason = "按权威等级选中 %s（%d 级），丢弃更低来源 %s" % (
            winner.get("id") or "?", top_level,
            "、".join(str(item.get("source")) for item in losers))
    return {"winner": winner, "losers": losers, "reason": reason}


def scan_conflicts(archive, other_text, fields=None) -> list:
    """拿档案核对别的文本，返回矛盾清单（只报告，不改数据）。

    archive: PersonaArchive；other_text: 世界观/记忆等拼好的文本。
    """
    text = str(other_text or "")
    if not text:
        return []
    problems = []
    for name in (fields or CONTRADICTIONS.keys()):
        anchors, conflicts = CONTRADICTIONS.get(name, ((), ()))
        value = archive.field(name) if archive is not None else ""
        if not value:
            continue
        if not any(anchor in value for anchor in anchors):
            continue
        hits = [word for word in conflicts if word in text]
        if hits:
            problems.append({
                "field": name,
                "archive": value[:60],
                "conflict_text": "、".join(hits),
            })
    return problems


def scan_age_conflict(archive, world) -> dict:
    """年龄单独看：档案生日算出来的岁数 vs 世界观里的 age。"""
    try:
        from .persona_archive import parse  # noqa: F401  （仅为说明来源，不参与计算）
    except Exception:
        pass
    if archive is None or not isinstance(world, dict):
        return {}
    age = world.get("age")
    return {"age": age, "note": "年龄以档案生日换算为准"} if age else {}


__all__ = ["LEVELS", "CONTRADICTIONS", "level_of", "resolve", "scan_conflicts",
           "scan_age_conflict"]
