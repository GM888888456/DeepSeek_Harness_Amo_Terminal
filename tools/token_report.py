#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Amo 的 Token / 调用量基线报表（只读，不改任何数据）。

口径（固定在这一份里，别在别处再算一套）：

1. `provider_stats`（`$DATA/data_v4.db`）：AstrBot 记的每次模型调用，
   有 token_input_other / token_input_cached / token_output、start_time / end_time（epoch）、
   status、provider_id、umo。
2. `token_usage`（`plugin_data/Astrbot_Amo_forever/amo_forever.db`）：插件自记账，
   专门记 `provider_stats` 不收的内部调用（judge / polish / diary / digest / other）。
3. `platform_stats`（同 `data_v4.db`）：每小时收到的消息数，**时间是 +08:00**，
   这里统一减 8 小时，按 UTC 日归并，好和另外两张表（epoch / UTC）对齐。

窗口：默认取「最后一次调用」往前 `--days` 天（UTC），保证同一批数据每次算出来一样。

调用率 = 调用次数 / 消息数；本地处理近似率 = 1 - 调用率。
注意这是**近似值**：一条消息可能触发 0 次或多次调用（点名、追问、判分各算一次），
所以它衡量的是「模型被叫醒的频率」，不是精确的命中率。

成本不在这里估：价格会变，没有价目表就宁可不算，也不编一个数字。

用法：

    python3 tools/token_report.py                    # 最近 7 天，打印表格
    python3 tools/token_report.py --days 3 --json    # 机器可读
    python3 tools/token_report.py --out tools/baselines/token-baseline.json
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import sqlite3
import sys

DATA = os.environ.get("AMO_DATA", "/data/astrbot")
PLUGIN_DATA = os.environ.get("AMO_PLUGIN_DATA", os.path.join(DATA, "plugin_data"))
FOREVER_DB = os.path.join(PLUGIN_DATA, "Astrbot_Amo_forever", "amo_forever.db")
ASTRBOT_DB = os.path.join(DATA, "data_v4.db")


def _connect(path):
    if not os.path.isfile(path):
        return None
    return sqlite3.connect("file:%s?mode=ro" % path, uri=True)


def _rows(conn, sql, args=()):
    if conn is None:
        return []
    try:
        return conn.execute(sql, args).fetchall()
    except sqlite3.Error:
        return []


def _percentile(values, ratio):
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round(ratio * (len(ordered) - 1)))))
    return round(ordered[index], 3)


def _day(epoch):
    return datetime.datetime.utcfromtimestamp(float(epoch)).strftime("%Y-%m-%d")


def collect(days=7):
    """采一次样本：返回 dict（全部数字，不带结论）。"""
    astro = _connect(ASTRBOT_DB)
    forever = _connect(FOREVER_DB)

    last = _rows(astro, "SELECT MAX(start_time) FROM provider_stats")
    last_ts = float(last[0][0]) if last and last[0][0] else 0.0
    if not last_ts:
        last2 = _rows(forever, "SELECT MAX(ts) FROM token_usage")
        last_ts = float(last2[0][0]) if last2 and last2[0][0] else 0.0
    since = last_ts - days * 86400 if last_ts else 0.0

    calls = _rows(astro,
                  "SELECT start_time, end_time, status, provider_id, provider_model, "
                  "token_input_other, token_input_cached, token_output, umo "
                  "FROM provider_stats WHERE start_time >= ?", (since,))
    inner = _rows(forever,
                  "SELECT ts, kind, model, input_other, input_cached, output "
                  "FROM token_usage WHERE ts >= ?", (since,))
    # platform_stats 是 +08:00 本地时间：减 8 小时再按 UTC 日归并
    platform = _rows(astro,
                     "SELECT timestamp, count FROM platform_stats WHERE timestamp >= ?",
                     (datetime.datetime.utcfromtimestamp(since - 8 * 3600)
                      .strftime("%Y-%m-%d %H:%M:%S"),))

    summary = {
        "window": {"since_utc": _day(since) if since else "",
                   "until_utc": _day(last_ts) if last_ts else "",
                   "days": days},
        "messages": 0,
        "calls": {"total": len(calls), "tokens_in_other": 0, "tokens_in_cached": 0,
                  "tokens_out": 0, "errors": 0, "aborted": 0},
        "inner": {"total": len(inner), "tokens_in_other": 0, "tokens_in_cached": 0,
                  "tokens_out": 0},
        "latency_s": {}, "by_day": {}, "by_provider": {}, "by_kind": {},
    }

    for row in platform:
        summary["messages"] += int(row[1] or 0)

    latencies = []
    for (start, end, status, provider_id, model, inp, cached, out, _umo) in calls:
        summary["calls"]["tokens_in_other"] += int(inp or 0)
        summary["calls"]["tokens_in_cached"] += int(cached or 0)
        summary["calls"]["tokens_out"] += int(out or 0)
        if status == "error":
            summary["calls"]["errors"] += 1
        elif status == "aborted":
            summary["calls"]["aborted"] += 1
        if start and end:
            latencies.append(float(end) - float(start))
        day = summary["by_day"].setdefault(_day(start), {"messages": 0, "calls": 0,
                                                         "inner": 0, "tokens_in": 0,
                                                         "tokens_out": 0})
        day["calls"] += 1
        day["tokens_in"] += int(inp or 0) + int(cached or 0)
        day["tokens_out"] += int(out or 0)
        bucket = summary["by_provider"].setdefault(
            provider_id or "?", {"calls": 0, "tokens_in": 0, "tokens_out": 0})
        bucket["calls"] += 1
        bucket["tokens_in"] += int(inp or 0) + int(cached or 0)
        bucket["tokens_out"] += int(out or 0)

    for (ts, kind, model, inp, cached, out) in inner:
        summary["inner"]["tokens_in_other"] += int(inp or 0)
        summary["inner"]["tokens_in_cached"] += int(cached or 0)
        summary["inner"]["tokens_out"] += int(out or 0)
        day = summary["by_day"].setdefault(_day(ts), {"messages": 0, "calls": 0, "inner": 0,
                                                       "tokens_in": 0, "tokens_out": 0})
        day["inner"] += 1
        key = kind or "other"
        bucket = summary["by_kind"].setdefault(key, {"calls": 0, "tokens_in": 0,
                                                     "tokens_out": 0, "models": {}})
        bucket["calls"] += 1
        bucket["tokens_in"] += int(inp or 0) + int(cached or 0)
        bucket["tokens_out"] += int(out or 0)
        bucket["models"][model or "?"] = bucket["models"].get(model or "?", 0) + 1

    # 消息按 UTC 日归并
    for stamp, count in platform:
        try:
            utc = (datetime.datetime.strptime(stamp, "%Y-%m-%d %H:%M:%S")
                   - datetime.timedelta(hours=8))
        except (TypeError, ValueError):
            continue
        day = summary["by_day"].setdefault(utc.strftime("%Y-%m-%d"),
                                           {"messages": 0, "calls": 0, "inner": 0,
                                            "tokens_in": 0, "tokens_out": 0})
        day["messages"] += int(count or 0)

    summary["latency_s"] = {"p50": _percentile(latencies, 0.5),
                            "p95": _percentile(latencies, 0.95),
                            "max": round(max(latencies), 3) if latencies else 0.0,
                            "n": len(latencies)}
    total_calls = summary["calls"]["total"]
    total_inner = summary["inner"]["total"]
    summary["rates"] = {
        "messages": summary["messages"],
        "main_calls_per_message": round(total_calls / summary["messages"], 3)
        if summary["messages"] else 0.0,
        "all_calls_per_message": round((total_calls + total_inner) / summary["messages"], 3)
        if summary["messages"] else 0.0,
        "main_tokens_in_per_message": round(summary["calls"]["tokens_in_other"] / summary["messages"], 1)
        if summary["messages"] else 0.0,
        "main_tokens_out_per_message": round(summary["calls"]["tokens_out"] / summary["messages"], 1)
        if summary["messages"] else 0.0,
    }
    if astro is not None:
        astro.close()
    if forever is not None:
        forever.close()
    return summary


def render(summary):
    out = []
    out.append("窗口：%s ~ %s（UTC，%d 天）" % (summary["window"]["since_utc"],
                                          summary["window"]["until_utc"],
                                          summary["window"]["days"]))
    rates = summary["rates"]
    out.append("消息 %d 条 / 主回复调用 %d 次 / 内部调用 %d 次"
               % (rates["messages"], summary["calls"]["total"], summary["inner"]["total"]))
    out.append("主回复调用率 %.3f 次/消息（内部调用算上 %.3f 次/消息）"
               % (rates["main_calls_per_message"], rates["all_calls_per_message"]))
    out.append("主回复 token：输入 %d（含缓存 %d）/ 输出 %d；每条消息 输入 %.1f / 输出 %.1f"
               % (summary["calls"]["tokens_in_other"], summary["calls"]["tokens_in_cached"],
                  summary["calls"]["tokens_out"], rates["main_tokens_in_per_message"],
                  rates["main_tokens_out_per_message"]))
    out.append("内部 token：输入 %d（含缓存 %d）/ 输出 %d"
               % (summary["inner"]["tokens_in_other"], summary["inner"]["tokens_in_cached"],
                  summary["inner"]["tokens_out"]))
    lat = summary["latency_s"]
    out.append("延迟 p50 %.2fs / p95 %.2fs / max %.2fs（n=%d）；失败 %d，中断 %d"
               % (lat["p50"], lat["p95"], lat["max"], lat["n"],
                  summary["calls"]["errors"], summary["calls"]["aborted"]))
    out.append("")
    out.append("%-12s %8s %7s %7s %10s %9s" % ("日期(UTC)", "消息", "主调用", "内部", "输入tok", "输出tok"))
    for day in sorted(summary["by_day"]):
        item = summary["by_day"][day]
        out.append("%-12s %8d %7d %7d %10d %9d"
                   % (day, item["messages"], item["calls"], item["inner"],
                      item["tokens_in"], item["tokens_out"]))
    out.append("")
    out.append("%-34s %7s %10s %9s" % ("provider", "调用", "输入tok", "输出tok"))
    for name, item in sorted(summary["by_provider"].items(), key=lambda kv: -kv[1]["calls"]):
        out.append("%-34s %7d %10d %9d" % (name, item["calls"], item["tokens_in"],
                                           item["tokens_out"]))
    out.append("")
    out.append("%-10s %7s %10s %9s  %s" % ("内部kind", "次数", "输入tok", "输出tok", "模型"))
    for name, item in sorted(summary["by_kind"].items(), key=lambda kv: -kv[1]["calls"]):
        models = ",".join("%s×%d" % (k, v) for k, v in
                          sorted(item["models"].items(), key=lambda kv: -kv[1])[:3])
        out.append("%-10s %7d %10d %9d  %s" % (name, item["calls"], item["tokens_in"],
                                               item["tokens_out"], models))
    return "\n".join(out)


def main(argv):
    parser = argparse.ArgumentParser(description="Amo token / 调用量基线报表（只读）")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    parser.add_argument("--out", default="", help="把 JSON 另存到这个路径")
    args = parser.parse_args(argv)

    summary = collect(args.days)
    payload = json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        folder = os.path.dirname(os.path.abspath(args.out))
        if folder and not os.path.isdir(folder):
            os.makedirs(folder)
        with open(args.out, "w", encoding="utf-8") as handle:
            handle.write(payload + "\n")
    print(payload if args.json else render(summary))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
