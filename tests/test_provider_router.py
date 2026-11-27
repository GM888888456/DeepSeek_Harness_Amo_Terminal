# -*- coding: utf-8 -*-
"""辅助模型路由与错误分类的测试（规范 5.3~5.5）。"""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load():
    spec = importlib.util.spec_from_file_location("amo_provider_router",
                                                  os.path.join(ROOT, "amo_core/provider_router.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


PR = load()


class ErrorClassTest(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(PR.classify_error(TimeoutError("Request timed out")), "timeout")
        self.assertEqual(PR.classify_error(RuntimeError("insufficient quota")), "quota_exceeded")
        self.assertEqual(PR.classify_error(RuntimeError("Provider xx was not found")),
                         "provider_unavailable")
        self.assertEqual(PR.classify_error(ValueError("json decode error")), "parse_error")
        self.assertEqual(PR.classify_error(KeyError("whatever")), "unknown")
        for kind in (PR.classify_error(RuntimeError("x")),):
            self.assertIn(kind, PR.ERROR_KINDS)


class StubPlugin:
    def __init__(self, conf=""):
        self.conf = conf

    def cfg_str(self, key, default=""):
        return self.conf if key.startswith("aux_provider_") else default


class PickTest(unittest.TestCase):
    def test_no_config_goes_main(self):
        router = PR.ProviderRouter()
        provider, reason = asyncio.run(router.pick(StubPlugin(""), "judge", lambda pid: None))
        self.assertIsNone(provider)
        self.assertIn("走主模型", reason)
        self.assertIn("未配置", reason)

    def test_uses_configured_first(self):
        router = PR.ProviderRouter()
        plugin = StubPlugin("cheap-a,cheap-b")

        async def getter(pid):
            return "provider:" + pid if pid == "cheap-a" else None

        provider, reason = asyncio.run(router.pick(plugin, "judge", getter))
        self.assertEqual(provider, "provider:cheap-a")
        self.assertIn("cheap-a", reason)

    def test_missing_candidate_falls_through(self):
        router = PR.ProviderRouter()
        plugin = StubPlugin("gone,ok-one")

        async def getter(pid):
            return "provider" if pid == "ok-one" else None

        provider, reason = asyncio.run(router.pick(plugin, "polish", getter))
        self.assertEqual(provider, "provider")
        self.assertIn("gone", reason)

    def test_unhealthy_is_skipped(self):
        router = PR.ProviderRouter()
        plugin = StubPlugin("bad,good")
        router.note("bad", False, TimeoutError("timed out"))
        seen = []

        async def getter(pid):
            seen.append(pid)
            return "provider:" + pid

        provider, reason = asyncio.run(router.pick(plugin, "extract", getter))
        self.assertNotIn("bad", seen)          # 近期失败的不再探
        self.assertEqual(provider, "provider:good")
        self.assertIn("bad", reason)
        self.assertEqual(router.health()["bad"]["kind"], "timeout")


if __name__ == "__main__":
    unittest.main(verbosity=2)
