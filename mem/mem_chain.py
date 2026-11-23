# -*- coding: utf-8 -*-
"""插件内部的链式步骤：每一步一行日志，同一个 trace 号串起来，方便按链排查。

用法（八个插件一致）：

    from chain import Chain       # 包内加载用 from .chain import Chain
    ch = Chain("medical.treat", event_id=幂等号)
    ch.step("quote", cost=200, plan="门诊")
    ch.step("pay", ok=bool(result.get("ok")), detail=结果原因, balance=余额)
    ch.step("execute", ok=executed, detail=新状态)
    ch.done(executed=executed)

日志长这样（`docker logs … | grep '\[chain\]'` 就能把一条业务链捞全）：

    [chain] medical.treat#12 quote cost=200 plan=门诊 (0ms)
    [chain] medical.treat#12 pay ok:扣款成功 balance=7800.0 (12ms)
    [chain] medical.treat#12 execute ok:恢复中 (14ms)
    [chain] medical.treat#12 done executed=True (14ms)

约定：
- 步骤名用各插件固定的词表，别临时造词，否则筛不出来；
- 失败一律 `ch.step(..., ok=False, detail=原因)`，打 warning，不抛异常；
- 只记事实（金额、状态、幂等号、余额），不记提示词、密钥、完整聊天；
- 一个业务动作一条链；重试沿用同一个 trace 号（传 event_id），一眼看出是同一笔。
"""

from __future__ import annotations

import itertools
import time

_SEQ = itertools.count(1)
_MAX_DETAIL = 120


def _fmt(value, limit=_MAX_DETAIL):
    text = "" if value is None else str(value)
    text = text.replace("\n", " ")
    return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"


class Chain:
    """一条业务链：构造即开始计时，step 记一步，done 收尾。"""

    def __init__(self, name, trace_id="", logger=None, event_id="", **fields):
        """trace_id 与 event_id 等价：传幂等号就能把重试串成同一条链。"""
        self.name = str(name or "task")
        self.trace = str(trace_id or event_id or "") or "%s#%d" % (self.name, next(_SEQ))
        self._logger = logger
        self._t0 = time.monotonic()
        self.steps = []
        self.fields = dict(fields)

    # ---------------------------------------------------------------- 内部
    def _logger_obj(self):
        if self._logger is not None:
            return self._logger
        try:
            from astrbot.api import logger
            return logger
        except Exception:
            return None

    def _emit(self, line, ok):
        log = self._logger_obj()
        if log is None:
            return
        try:
            (log.debug if ok else log.warning)(line)
        except Exception:
            pass

    # ---------------------------------------------------------------- 记一步
    def step(self, stage, ok=True, detail="", **fields):
        elapsed = int((time.monotonic() - self._t0) * 1000)
        extra = " ".join(
            "%s=%s" % (key, _fmt(value))
            for key, value in fields.items()
            if value not in (None, "")
        )
        text = "[chain] %s %s %s" % (self.trace, stage, "ok" if ok else "FAIL")
        if detail:
            text += ":" + _fmt(detail)
        if extra:
            text += " " + extra
        text += " (%dms)" % elapsed
        self.steps.append({
            "stage": stage, "ok": bool(ok), "detail": _fmt(detail), "elapsed_ms": elapsed,
        })
        self._emit(text, ok)
        return self

    def done(self, **fields):
        return self.step("done", **fields)

    def fail(self, stage, reason="", **fields):
        return self.step(stage, ok=False, detail=reason, **fields)

    @property
    def ok(self):
        return all(item["ok"] for item in self.steps)

    def summary(self):
        return " → ".join(
            "%s%s" % (item["stage"], "" if item["ok"] else "(FAIL:%s)" % item["detail"])
            for item in self.steps
        )
