# Token / 调用量基线

## 怎么复现

    cd /data/astrbot/plugins/DeepSeek_Harness_Amo_Terminal
    python3 tools/token_report.py --days 7              # 打印
    python3 tools/token_report.py --days 7 --json       # 机器可读
    python3 tools/token_report.py --days 7 --out tools/baselines/xxx.json

脚本只读（sqlite `mode=ro`），不写任何数据。

## 口径

- `provider_stats`（`/data/astrbot/data_v4.db`）：AstrBot 记的模型调用，含 token 与起止时间（epoch）。
- `token_usage`（`plugin_data/Astrbot_Amo_forever/amo_forever.db`）：插件自记账，记 `provider_stats` 不收的内部调用（judge/polish/diary/digest/other）。
- `platform_stats`（同 `data_v4.db`）：每小时消息数，**+08:00**，这里减 8 小时按 UTC 日归并。
- 窗口：以最后一次调用为终点往前 N 天（UTC）。同一批数据每次算出来一样。
- 调用率 = 调用 / 消息；这是「模型被叫醒的频率」，不是精确命中率（一条消息可能 0 次或多次调用）。
- 成本不估：没有价目表就算不出来，不编。

## 改造前基线（2026-11-28 采，窗口 2026-11-20 ~ 2026-11-27 UTC）

| 指标 | 值 |
| --- | --- |
| 消息 | 2,628 条 |
| 主回复调用 | 3,025 次（1.151 次/消息） |
| 内部调用 | 6,285 次（合计 3.543 次/消息） |
| 主回复输入 token | 13,268,822（另有缓存 18,678,791） |
| 主回复输出 token | 268,562（102.2/消息） |
| 每条消息平均输入 | 5,049 token |
| 内部输入/输出 token | 12,781,851 / 1,151,503 |
| 延迟 | p50 1.54s / p95 9.15s / max 377.06s |
| 失败 / 中断 | 22 / 1 |
| 内部调用构成 | judge 5,775（GLM-4-flash）、other 334、diary 101、polish 69、digest 6 |

要点：

1. **judge（判分/预筛）是调用量第一大户**，次数是主回复的 1.9 倍，输入 token 接近主回复量级；
   优化 token 的第一目标在它，不在 Context Builder。
2. 主回复每条消息平均吃 5,049 输入 token，p95 延迟 9 秒，max 377 秒（有一次卡了 6 分钟）。
3. 缓存 token（18.7M）已经大于新增输入（13.3M），说明前缀缓存已经在起作用，别乱改 prompt 前缀顺序。

详细数字见同目录 `token-baseline-20261128-7d.json`。
