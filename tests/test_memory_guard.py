# -*- coding: utf-8 -*-
"""记忆地点冲突提示的测试（误报回归）。"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


MG = load("amo_memory_guard", "memory_guard.py")


class FakeDB:
    def __init__(self):
        self.store = {}

    def kv_get(self, key, default=None):
        return self.store.get(key, default)

    def kv_set(self, key, value):
        self.store[key] = value


class CanonicalPlaceTest(unittest.TestCase):
    def test_same_place_normalized(self):
        self.assertEqual(MG.canonical_place("家里"), MG.canonical_place("家"))
        self.assertEqual(MG.canonical_place("公司里"), MG.canonical_place("公司"))
        self.assertEqual(MG.canonical_place("公司"), MG.canonical_place("公司"))

    def test_unknown_kept(self):
        self.assertEqual(MG.canonical_place("火星"), "火星")


class ConflictHintTest(unittest.TestCase):
    NOW = datetime(2026, 11, 28, 6, 4)

    def test_home_and_jia_li_are_the_same(self):
        db = FakeDB()
        MG.commit(db, "u1", "他回到家了，家里灯还亮着", self.NOW, 1.0)
        hint = MG.commit(db, "u1", "她坐在家里发信息", self.NOW, 2.0)
        self.assertEqual(hint, "")          # 家 / 家里 不再算两个地点

    def test_real_conflict_still_reported(self):
        db = FakeDB()
        MG.commit(db, "u1", "他在公司开会", self.NOW, 1.0)
        hint = MG.commit(db, "u1", "她回到家了", self.NOW, 2.0)
        self.assertIn("不一致", hint)
        self.assertIn("公司", hint)

    def test_no_place_no_hint(self):
        db = FakeDB()
        hint = MG.commit(db, "u1", "今天有点困", self.NOW, 1.0)
        self.assertEqual(hint, "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
