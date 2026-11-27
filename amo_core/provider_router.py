# -*- coding: utf-8 -*-
"""辅助模型路由与错误分类（规范 5.2~5.5）。

规矩：

- **不写死任何 provider id/模型名**：候选只来自配置（`aux_provider_<kind>`），留空就走主模型；
- 失败要分得清：不是所有异常都变成空字符串；
- 选谁、为什么不选另一个、为什么降级，都要能说出来（`reason`）。

健康状态只在内存里记，重启就清空——不落盘、不猜远端额度。
"""

from __future__ import annotations

import asyncio
import time

#: 规范 5.3 的错误分类
ERROR_KINDS = (
    "provider_unavailable",
    "timeout",
    "quota_exceeded",
    "capability_not_supported",
    "invalid_output",
    "parse_error",
    "unknown",
)

#: 关键词 → 分类（按顺序匹配，越具体越靠前）
_ERROR_PATTERNS = (
    ("quota_exceeded", ("quota", "insufficient", "余额", "额度", "402", "payment")),
    ("timeout", ("timeout", "timed out", "超时", "deadline")),
    ("capability_not_supported", ("not support", "unsupported", "vision", "image", "不支持", "400")),
    ("provider_unavailable", ("not found", "unavailable", "connection", "connect", "refused",
                              "dns", "ssl", "403", "404", "500", "502", "503", "504")),
    ("invalid_output", ("invalid", "empty", "schema", "格式", "无法解析")),
    ("parse_error", ("json", "decode", "parse")),
)

#: 健康缓存有效期（秒）：同一次故障不反复探
HEALTH_TTL = 120


def classify_error(exc) -> str:
    """把异常归到 ERROR_KINDS 里的一类。"""
    text = ("%s %s" % (type(exc).__name__, exc)).lower()
    for kind, words in _ERROR_PATTERNS:
        if any(word.lower() in text for word in words):
            return kind
    return "unknown"


class ProviderRouter:
    """辅助用途的候选链路：配置 → 健康缓存 → 主模型兜底。"""

    def __init__(self):
        self._health = {}       # provider_id -> (ok, ts, error_kind)
        self._calls = {}        # kind -> 次数（观测用，不落盘）

    # ---------------------------------------------------------------- 候选
    @staticmethod
    def candidates(plugin, kind):
        """某个用途配置了哪些候选（逗号分隔）；没配置返回空元组。"""
        try:
            conf = str(plugin.cfg_str("aux_provider_" + str(kind), "") or "").strip()
        except Exception:
            return ()
        return tuple(item.strip() for item in conf.replace("，", ",").split(",") if item.strip())

    # ---------------------------------------------------------------- 健康
    def healthy(self, provider_id) -> bool:
        ok, stamp, _kind = self._health.get(str(provider_id), (True, 0, ""))
        if time.time() - stamp > HEALTH_TTL:
            return True
        return ok

    def note(self, provider_id, ok, exc=None):
        self._health[str(provider_id)] = (bool(ok), time.time(),
                                          "" if ok else classify_error(exc))

    def health(self) -> dict:
        return {pid: {"ok": ok, "kind": kind} for pid, (ok, _ts, kind) in self._health.items()}

    # ---------------------------------------------------------------- 选择
    async def pick(self, plugin, kind, getter):
        """返回 (provider, reason)。getter(provider_id) 是异步取 provider 的函数。"""
        self._calls[kind] = self._calls.get(kind, 0) + 1
        tried = []
        for pid in self.candidates(plugin, kind):
            if not self.healthy(pid):
                tried.append("%s(近期失败已跳过)" % pid)
                continue
            provider = await getter(pid)
            if provider is None:
                self.note(pid, False, RuntimeError("not found"))
                tried.append("%s(取不到)" % pid)
                continue
            self.note(pid, True)
            # 规范 5.4：要能说清「为什么选它、为什么没选别的」
            skipped = ("（先跳过了：%s）" % "；".join(tried)) if tried else ""
            return provider, "用配置的 %s%s" % (pid, skipped)
        if not tried:
            return None, "未配置 aux_provider_%s，走主模型" % kind
        return None, "候选都不可用（%s），走主模型" % "；".join(tried)

    def stats(self) -> dict:
        return {"calls": dict(self._calls), "health": self.health()}


__all__ = ["ERROR_KINDS", "classify_error", "ProviderRouter", "HEALTH_TTL"]
