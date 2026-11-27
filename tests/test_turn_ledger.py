# -*- coding: utf-8 -*-
"""每轮注入账本的回归测试（纯本地）。"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load():
    name = "amo_turn_ledger_under_test"
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "amo_core", "turn_ledger.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TL = load()

PARTS = [
    "姓名：沈晓沫\n生日：2001年5月20日",            # 第一段 → 人格核心
    "【档案原文】资产：云顶山庄·沈家庄园",           # → archive
    "【世界观】\n城市：贵阳\n日常：去公司开会",       # → world
    "【此刻状态】\n在办公室",                        # → state
    "【关于对方的记忆】\n他喜欢喝茶",                 # → memory
    "【关系网】\n二婶：催婚",                        # → relation
    "【语气】短句",                                  # → other
]


class ClassifyTest(unittest.TestCase):
    def test_sections_by_prefix(self):
        self.assertEqual(TL.classify(PARTS[0], 0), "persona")
        self.assertEqual(TL.classify(PARTS[1], 1), "archive")
        self.assertEqual(TL.classify(PARTS[2], 2), "world")
        self.assertEqual(TL.classify(PARTS[3], 3), "state")
        self.assertEqual(TL.classify(PARTS[4], 4), "memory")
        self.assertEqual(TL.classify(PARTS[5], 5), "relation")
        self.assertEqual(TL.classify(PARTS[6], 6), "other")


class LedgerTest(unittest.TestCase):
    def test_counts_and_total(self):
        ledger = TL.TurnLedger()
        ledger.add_from_parts(PARTS)
        sections = ledger.sections
        self.assertEqual(sections["persona"], len(PARTS[0]))
        self.assertEqual(sections["archive"], len(PARTS[1]))
        self.assertEqual(ledger.total(), sum(len(part) for part in PARTS))

    def test_payload_marks_unit_chars(self):
        ledger = TL.TurnLedger()
        ledger.add_from_parts(PARTS)
        payload = ledger.as_dict("umo-x", extra={"archive_fields": 2})
        self.assertEqual(payload["unit"], "chars")      # 不许冒充 token
        self.assertEqual(payload["umo"], "umo-x")
        self.assertEqual(payload["archive_fields"], 2)
        self.assertNotIn("tokens", payload)

    def test_appends_jsonl(self):
        folder = tempfile.mkdtemp(prefix="amo-ledger-")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "turn_ledger.jsonl")
        ledger = TL.TurnLedger(path)
        ledger.add_from_parts(PARTS)
        ledger.log(None, umo="u1")
        ledger.log(None, umo="u1")
        lines = [json.loads(line) for line in io.open(path, encoding="utf-8")]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["chars_total"], ledger.total())

    def test_missing_path_is_silent(self):
        ledger = TL.TurnLedger("")
        ledger.add("persona", "x")
        self.assertFalse(ledger.append({"a": 1}))


if __name__ == "__main__":
    unittest.main(verbosity=2)
