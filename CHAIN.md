# 链式排查手册（CHAIN）

> 2026-11-15 ｜ 适用八仓库：终端 / 记忆 / 生图 / 语音 / 医疗 / 金融 / 市场 / 守护

八个插件是一个整体：Amo 是大脑，其余是挂载的执行器。每次业务动作都在插件**内部**
按固定步骤走一遍，每一步写一行日志。出问题时不用猜，先看这条链断在哪一步。

## 1 日志长什么样

```
[chain] medical.treat#12 quote ok cost=200 total=280 reimbursed=80 (0ms)
[chain] medical.treat#12 approve ok (1ms)
[chain] medical.treat#12 pay ok:扣款成功 balance=5292.75 payee=医院 (13ms)
[chain] medical.treat#12 execute ok:恢复中 hours=12 medicines=3 (14ms)
[chain] medical.treat#12 done ok executed=True self_pay=200.0 (14ms)
```

一行四段：`[chain]` 标记 → trace 号 → 步骤名 → `ok` 或 `FAIL:原因` → 字段 → 耗时。
失败打 **warning**，成功打 info；字段为空的直接不显示（不会出现 `umo=` 空值）。

## 2 trace 号怎么来

- 有幂等号的业务（就医、扣费、记忆写入）：trace 就是幂等号，**重试也是同一条链**，
  一眼看出「这是同一笔的第几次」。
- 没有幂等号的（出图、出声、发送、行情）：自动编号 `链名#序号`。
- 同一个 trace 号跨插件能对上：医疗的 `med-…` → 终端的 `terminal.charge` 用同一个
  event_id → 金融的 `finance.charge` 也用它。

## 3 各插件链与步骤词表

| 插件 | 链名 | 步骤 |
|---|---|---|
| 终端 | `terminal.charge` | `propose` → `approve` → `charge` → `receipt` → `done`／`FAIL` |
| 记忆 | `data.remember` ／ `data.recall` | `request` → `write`/`recall` → `done` |
| 生图 | `image.draw` | `request` → `boundary` → `quota` → `prompt` → `generate` → `receipt` → `done` |
| 语音 | `speech.speak` | `request` → `decide` → `split` → `synth` → `send` → `done` |
| 医疗 | `medical.treat` | `quote` → `approve` → `pay` → `execute` → `done` |
| 金融 | `finance.charge` | `idempotent` → `apply` → `ledger` → `done` |
| 市场 | `market.price` | `tick`（只在刷新失败时留痕，避免每分钟刷屏） |
| 守护 | `guard.deliver` | `request` → `gate` → `process` → `send` → `done` |

步骤名是**固定词表**，不要临时造词——不然 grep 不出来。新增步骤要同时更新本表和
该仓库的 `tests/test_chain_wiring.py`。

## 4 排查常用命令

```bash
# 最近一条链的全部步骤
docker logs --since 30m AstrBot-Amo 2>&1 | grep '\[chain\]' | tail -20

# 某一笔（用幂等号）
docker logs --since 24h AstrBot-Amo 2>&1 | grep '\[chain\] med-20261115'

# 只看失败：钱扣了没、图出没出、话发没发
docker logs --since 24h AstrBot-Amo 2>&1 | grep '\[chain\]' | grep FAIL

# 按插件分开看
docker logs --since 24h AstrBot-Amo 2>&1 | grep '\[chain\] finance.charge'
docker logs --since 24h AstrBot-Amo 2>&1 | grep '\[chain\] image.draw'
```

## 5 约定（改代码前先看这五条）

1. **只记事实**：金额、状态、幂等号、余额、字数、条数。不记提示词、密钥、完整聊天内容。
2. **失败不抛异常**：链只是记录，`ch.step(..., ok=False, detail=原因)` 后照原逻辑返回。
3. **一条业务一条链**：不要在一次请求里反复 new Chain，也不要把无关步骤塞进同一条。
4. **重试复用 trace**：传幂等号（`event_id=` / `trace_id=`），别每次新编号。
5. **删方法先扫调用点**：链的接线测试（`tests/test_chain_wiring.py`）会拦住「步骤无声消失」，
   但「方法删了调用点还在」要靠 `tests/test_service_contract.py` 的类内调用契约。

## 6 和其他约定的关系

- **不替代各插件自身的日志**：`[amo_med]`、`[amo_fin]`、`[amo_image]` 那些是业务细节，
  `[chain]` 是流程骨架，两者都要看。
- **不碰心流判定**：链只记录，不参与打分、不改变是否开口。
- **守护缺席时**：终端直接原文直发，链停在 `terminal` 侧，不产生 `guard.deliver` 行，
  这是正常的，不是丢消息。
