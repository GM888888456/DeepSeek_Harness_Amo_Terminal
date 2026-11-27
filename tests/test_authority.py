# -*- coding: utf-8 -*-
"""权威等级与冲突裁决的测试（规范 4.5）。"""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


AU = load("amo_authority", "amo_core/authority.py")
PA = load("amo_persona_archive_a", "amo_core/persona_archive.py")


class LevelTest(unittest.TestCase):
    def test_order_is_not_inverted(self):
        self.assertGreater(AU.level_of("user_template"), AU.level_of("user_correction"))
        self.assertGreater(AU.level_of("user_correction"), AU.level_of("user_statement"))
        self.assertGreater(AU.level_of("user_statement"), AU.level_of("inference"))
        self.assertGreater(AU.level_of("inference"), AU.level_of("model"))
        self.assertEqual(AU.level_of("随便什么"), 0)


class ResolveTest(unittest.TestCase):
    def test_authority_beats_recency(self):
        result = AU.resolve([
            {"id": "old", "content": "她是总裁", "source": "user_template", "updated_at": 1},
            {"id": "new", "content": "她是普通上班族", "source": "model", "updated_at": 999},
        ])
        self.assertEqual(result["winner"]["id"], "old")
        self.assertIn("权威等级", result["reason"])
        self.assertEqual(len(result["losers"]), 1)      # 冲突来源保留，不合并

    def test_same_level_prefers_newer_and_warns(self):
        result = AU.resolve([
            {"id": "a", "content": "x", "source": "user_statement", "updated_at": 10},
            {"id": "b", "content": "y", "source": "user_statement", "updated_at": 20},
        ])
        self.assertEqual(result["winner"]["id"], "b")
        self.assertIn("同级冲突", result["reason"])

    def test_empty_records(self):
        self.assertIsNone(AU.resolve([])["winner"])
        self.assertIsNone(AU.resolve([{"id": "x", "content": "  "}])["winner"])


class ConflictTest(unittest.TestCase):
    def setUp(self):
        self.archive = PA.parse(io.open(os.path.join(HERE, "fixtures", "persona_template.txt"),
                                        encoding="utf-8").read())

    def test_detects_job_conflict(self):
        problems = AU.scan_conflicts(self.archive, "职业：普通上班族，每天挤地铁")
        fields = [item["field"] for item in problems]
        self.assertIn("职业", fields)
        self.assertIn("普通上班族", " ".join(item["conflict_text"] for item in problems))

    def test_detects_asset_conflict(self):
        problems = AU.scan_conflicts(self.archive, "她租房住，没车，平时坐地铁上班")
        self.assertIn("资产", [item["field"] for item in problems])

    def test_no_false_positive_on_consistent_text(self):
        text = "她是中国计算智脑集团总裁，住在云顶山庄，丈夫是墨辞烟。"
        self.assertEqual(AU.scan_conflicts(self.archive, text), [])

    def test_empty_text(self):
        self.assertEqual(AU.scan_conflicts(self.archive, ""), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
