#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""人格/检索/注入的自检工具（只读，不调模型）。

规范第十四条的验收项，能本地查的都放在这里，一条命令看完：

    python3 tools/persona_check.py

会打印：

1. 人格档案：解析出哪些字段、各多少字、有没有空字段/未识别内容；
2. 常驻核心：多少字、有没有把完整档案塞进去；
3. 身份题：规范列的那几问，能不能命中档案原文（命中/注入字数）；
4. 注入账本：最近若干轮每轮的区块字符数（来自 plugin_data/.../turn_ledger.jsonl）；
5. 现状开关：方言是否关闭、辅助模型是否配了模型（都应「未配置→主模型」）。
"""

from __future__ import annotations

import ast
import io
import json
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)

from amo_core import persona_archive as PA  # noqa: E402

DATA = os.environ.get("AMO_PLUGIN_DATA", os.path.join(
    os.environ.get("AMO_DATA", "/data/astrbot"), "plugin_data"))
PLUGIN_DATA = os.path.join(DATA, "DeepSeek_Harness_Amo_Terminal")
ARCHIVE_JSON = os.path.join(PLUGIN_DATA, "persona_archive.json")
LEDGER = os.path.join(PLUGIN_DATA, "turn_ledger.jsonl")
TEMPLATE = os.path.join(HERE, "..", "tests", "fixtures", "persona_template.txt")

#: 规范第十四条的身份题
QUESTIONS = (
    ("你叫什么", ("姓名", "沈晓沫")),
    ("你做什么工作", ("职业", "总裁")),
    ("集团是谁的", ("职业", "总裁")),
    ("你有什么资产", ("资产", "云顶山庄")),
    ("你丈夫是谁", ("丈夫", "墨辞烟")),
    ("家里长辈做什么", ("家里", "长辈")),
)


def load_archive():
    """优先用线上解析缓存；没有就用仓库里的模板快照。"""
    cached = PA.load_cache(ARCHIVE_JSON)
    if cached is not None:
        return cached, ARCHIVE_JSON
    if os.path.isfile(TEMPLATE):
        return PA.parse(io.open(TEMPLATE, encoding="utf-8").read(), source="repo_fixture"), TEMPLATE
    return None, ""


def print_archive(archive, source):
    print("== 人格档案 ==")
    print("  来源：%s" % source)
    print("  字段 %d 个：%s" % (len(archive.names()),
                              "、".join("%s(%d字)" % (n, len(archive.field(n))) for n in archive.names())))
    if archive.errors:
        print("  ⚠️ 空字段：%s" % "、".join(archive.errors))
    if archive.unknown:
        print("  ⚠️ 未识别内容（已原文保留）：%s" % " / ".join(archive.unknown)[:120])


def print_core(archive):
    core = archive.resident_core()
    print()
    print("== 常驻核心 ==")
    print("  %d 字（预算 %d）" % (len(core), PA.DEFAULT_RESIDENT_BUDGET))
    leaks = [w for w in ("云顶山庄", "纪委", "傲娇", "宝马A8") if w in core]
    if leaks:
        print("  ⚠️ 完整档案泄漏进核心：%s" % "、".join(leaks))
    print("  ---")
    for line in core.splitlines():
        print("  " + line)


def print_questions(archive):
    print()
    print("== 身份题（是否命中档案原文）==")
    bad = 0
    for question, (field, expect) in QUESTIONS:
        answer = archive.answer(question)
        ok = field in [name for name, _w, _s in archive.match_scored(question)] and expect in answer
        bad += 0 if ok else 1
        print("  %-4s %-12s → %3d 字  %s" % ("OK" if ok else "MISS", question, len(answer),
                                            answer.replace("\n", " / ")[:60]))
    print("  未命中 %d 条" % bad)
    return bad


def print_ledger(limit=8):
    print()
    print("== 每轮注入账本（字符数，不是 token）==")
    if not os.path.isfile(LEDGER):
        print("  还没有账本：重启后发一条消息就会生成 %s" % LEDGER)
        return
    rows = []
    with io.open(LEDGER, encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    if not rows:
        print("  账本为空")
        return
    totals = [row.get("chars_total", 0) for row in rows]
    print("  共 %d 轮；字数 p50=%d p95=%d max=%d"
          % (len(rows), int(statistics.median(totals)),
             int(statistics.quantiles(totals, n=20)[-1]) if len(totals) > 2 else max(totals),
             max(totals)))
    sections = {}
    for row in rows[-200:]:
        for key, value in (row.get("chars") or {}).items():
            sections.setdefault(key, []).append(value)
    for key, values in sorted(sections.items(), key=lambda kv: -statistics.mean(kv[1])):
        print("    %-8s 平均 %5d 字" % (key, int(statistics.mean(values))))
    print("  最近 %d 轮：" % min(limit, len(rows)))
    for row in rows[-limit:]:
        detail = " ".join("%s=%d" % (k, v) for k, v in sorted((row.get("chars") or {}).items()))
        print("    %s %s 共 %d 字" % (row.get("umo", "")[-12:] or "-", detail,
                                     row.get("chars_total", 0)))


def _world_text():
    """从 kv 里拼出世界观正文（只读）；没有就返回空串。"""
    db = os.path.join(DATA, "Astrbot_Amo_forever", "amo_forever.db")
    if not os.path.isfile(db):
        return ""
    try:
        import sqlite3
        conn = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
        row = conn.execute("SELECT value FROM kv WHERE key='worldview'").fetchone()
        conn.close()
        world = json.loads(row[0]) if row and row[0] else {}
    except Exception:
        return ""
    return " ".join(str(world.get(k) or "") for k in ("name", "city", "daily_life",
                                                    "world_rules", "summary", "occupation"))


def print_conflicts(archive):
    print()
    print("== 冲突检查（档案 vs 世界观，只报告不改数据）==")
    text = _world_text()
    if not text:
        print("  读不到 kv.worldview，跳过")
        return 0
    try:
        from amo_core.authority import scan_conflicts
    except Exception as exc:
        print("  冲突检查不可用：%s" % exc)
        return 0
    problems = scan_conflicts(archive, text)
    if not problems:
        print("  没有发现冲突")
        return 0
    for item in problems:
        print("  ⚠️ %s：档案「%s」/ 文本里出现「%s」（以档案为准）"
              % (item["field"], item["archive"][:30], item["conflict_text"]))
    return len(problems)


def print_query(archive, queries):
    print()
    print("== 检索诊断 ==")
    for query in queries:
        hits = archive.match_scored(query)
        answer = archive.answer(query)
        print("  %-18s 命中 %-22s 注入 %3d 字"
              % (query, ", ".join("%s(%d)" % (n, s) for n, _w, s in hits) or "（无）", len(answer)))
        if answer:
            print("      %s" % answer.replace("\n", " / ")[:100])


def print_switches():
    print()
    print("== 开关现状 ==")
    # 方言：不 import（会拖 astrbot），用 AST 看那个开关是不是「只有一句 return False」
    try:
        src = io.open(os.path.join(ROOT, "amo_core", "persona.py"), encoding="utf-8").read()
        hard_off = False
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.FunctionDef) and node.name == "_dialect_active":
                body = [stmt for stmt in node.body if not isinstance(stmt, ast.Expr)]
                hard_off = (len(body) == 1 and isinstance(body[0], ast.Return)
                            and isinstance(getattr(body[0], "value", None), ast.Constant)
                            and body[0].value.value is False)
                break
        print("  方言：_dialect_active() %s" % ("恒 False（已下线）" if hard_off
                                              else "⚠️ 不是恒 False，检查一下"))
    except Exception as exc:
        print("  方言：源码检查失败（%s）" % exc)
    for key in ("aux_provider_polish", "aux_provider_judge", "aux_provider_extract"):
        cfg = os.path.join(os.environ.get("AMO_DATA", "/data/astrbot"), "config",
                           "DeepSeek_Harness_Amo_Terminal_config.json")
        value = ""
        try:
            data = json.loads(io.open(cfg, encoding="utf-8-sig").read())
            value = str(data.get(key) or "")
        except Exception:
            pass
        print("  %-22s %s" % (key, value or "未配置 → 走主模型"))


def main():
    queries = [arg.split("=", 1)[1] for arg in sys.argv[1:] if arg.startswith("--query=")]
    archive, source = load_archive()
    if archive is None:
        print("找不到人格档案，也找不到模板快照：%s" % ARCHIVE_JSON)
        return 2
    print_archive(archive, source)
    print_core(archive)
    bad = print_questions(archive)
    print_conflicts(archive)
    if queries:
        print_query(archive, queries)
    print_ledger()
    print_switches()
    print()
    print("结论：%s" % ("身份题全部命中" if bad == 0 else "有 %d 条身份题没命中，见上" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
