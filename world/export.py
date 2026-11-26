# -*- coding: utf-8 -*-
"""把世界观导出成一份可读的 Markdown（数据改了随时重生成）。

来源全部是「唯一真源」，不手写副本：
- world/entries/*.json   词条（规则/组织/地点/事件/术语/人物）
- world/events.py        事件池 + 五方势力初值
- story/lineage.py       族谱 44 口 + 宅邸 12 人

用法：
    python3 -m world.export           # 写到 world/WORLD.md
    python3 -m world.export out.md    # 指定输出
"""

from __future__ import annotations

import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

TYPE_TITLE = [
    ("rule", "规则与边界"),
    ("org", "组织与势力"),
    ("place", "地点"),
    ("event", "事件与时间线"),
    ("term", "行业与生活口径"),
    ("person", "人物"),
]


def _load_entries():
    import json
    rows = []
    entries_dir = os.path.join(HERE, "entries")
    for name in sorted(os.listdir(entries_dir)):
        if not name.endswith(".json"):
            continue
        try:
            data = json.load(open(os.path.join(entries_dir, name), encoding="utf-8"))
        except Exception:
            continue
        for row in (data.get("entries") if isinstance(data, dict) else data) or []:
            if isinstance(row, dict) and row.get("content"):
                rows.append(row)
    return rows


def build():
    out = io.StringIO()
    w = out.write

    w("# 沈晓沫 · 世界观总览\n\n")
    w("> 自动生成，别手工改这份文件——改 `world/entries/*.json`、`world/events.py`、`story/lineage.py` 后重跑 `python3 -m world.export`。\n\n")

    rows = _load_entries()

    # ---- 常驻规则 ----
    always = [e for e in rows if e.get("always")]
    if always:
        w("## 世界底座（每轮都在）\n\n")
        for e in always:
            w("- %s\n" % str(e["content"]).strip())
        w("\n")

    # ---- 分类 ----
    for kind, title in TYPE_TITLE:
        group = [e for e in rows if e.get("type") == kind and not e.get("always")]
        if not group:
            continue
        group.sort(key=lambda e: -int(e.get("priority") or 0))
        w("## %s\n\n" % title)
        for e in group:
            keys = "、".join(str(k) for k in (e.get("keys") or [])[:6])
            w("### %s\n\n" % (e.get("title") or e.get("id")))
            w("%s\n\n" % str(e["content"]).strip())
            if keys:
                w("<sub>触发词：%s</sub>\n\n" % keys)

    # ---- 势力 ----
    try:
        from . import events as ev
    except Exception:
        ev = None
    if ev is not None:
        w("## 五方势力（初值）\n\n")
        w("| 势力 | 初值 |\n|---|---|\n")
        for name, value in ev.DEFAULT_STATE["factions"].items():
            w("| %s | %d |\n" % (name, value))
        w("\n每天按权重抽 1~2 个事件，事件对势力做加减，声望跟着动；低于 38 算「吃紧」。\n\n")
        w("## 事件池（%d 个）\n\n" % len(ev.EVENT_POOL))
        w("| 标签 | 事件 | 影响 | 权重 |\n|---|---|---|---|\n")
        for e in sorted(ev.EVENT_POOL, key=lambda x: -int(x.get("weight") or 0)):
            eff = "、".join("%s %+d" % (k, v) for k, v in (e.get("effects") or {}).items()) or "—"
            w("| %s | %s | %s | %d |\n" % (e.get("tag", ""), e.get("text", ""), eff,
                                          int(e.get("weight") or 0)))
        w("\n")

        # 季度主线
        quarter = getattr(ev, "QUARTER_POOL", None) or {}
        if quarter:
            w("### 季度主线（每季头三天额外推进一条）\n\n")
            w("| 季度 | 事件 | 影响 |\n|---|---|---|\n")
            for q, items in sorted(quarter.items()):
                for e in items:
                    eff = "、".join("%s %+d" % (k, v) for k, v in (e.get("effects") or {}).items()) or "—"
                    w("| Q%d | %s | %s |\n" % (q, e.get("text", ""), eff))
            w("\n")

    # ---- 族谱与宅邸 ----
    try:
        try:
            from story import lineage as ln
        except Exception:
            sys.path.insert(0, ROOT)
            from story import lineage as ln
    except Exception:
        ln = None
    if ln is not None:
        w("## 沈家四代（%d 口）\n\n" % len(ln.FAMILY))
        w("家训：%s\n\n" % ln.MOTTO)
        cur = None
        for person in ln.FAMILY:
            gen = int(person.get("gen") or 0)
            if gen != cur:
                cur = gen
                w("### 第%s代\n\n" % {1: "一", 2: "二", 3: "三", 4: "四"}.get(gen, str(gen)))
                w("| 关系 | 姓名 | 身份 | 备注 |\n|---|---|---|---|\n")
            w("| %s | %s | %s | %s |\n" % (person.get("relation", ""), person.get("name", ""),
                                          person.get("title", ""), person.get("note", "")))
        w("\n产业：\n\n")
        for item in ln.ASSETS:
            w("- %s\n" % item)
        w("\n## 宅邸班组（%d 人）\n\n" % len(ln.STAFF))
        w("| 角色 | 称呼 | 姓名 | 职责 | 备注 |\n|---|---|---|---|---|\n")
        for s in ln.STAFF:
            w("| %s | %s | %s | %s | %s |\n" % (s.get("role", ""), s.get("title", ""),
                                              s.get("name", ""), s.get("duty", ""),
                                              s.get("note", "")))
        w("\n")

    w("---\n\n")
    w("规模：词条 %d 条（常驻 %d）、事件 %d 个、族谱 %d 口、宅邸 %d 人。\n" % (
        len(rows), len(always),
        len(ev.EVENT_POOL) if ev is not None else 0,
        len(ln.FAMILY) if ln is not None else 0,
        len(ln.STAFF) if ln is not None else 0,
    ))
    return out.getvalue()


def main():
    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "WORLD.md")
    text = build()
    with open(target, "w", encoding="utf-8") as fh:
        fh.write(text)
    print("已导出 %s（%d 字）" % (target, len(text)))
    return target


if __name__ == "__main__":
    main()
