# -*- coding: utf-8 -*-
"""待补发队列的测试（纯逻辑，不依赖 AstrBot）。"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load():
    spec = importlib.util.spec_from_file_location("amo_undelivered",
                                                  os.path.join(ROOT, "amo_core/undelivered.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


UD = load()


class FakeDB:
    def __init__(self):
        self.store = {}

    def kv_get(self, key, default=None):
        return self.store.get(key, default)

    def kv_set(self, key, value):
        self.store[key] = value


class QueueTest(unittest.TestCase):
    def test_enqueue_and_pop(self):
        db = FakeDB()
        self.assertTrue(UD.enqueue(db, "umo-a", "想跟你说句话", ts=1000))
        taken = UD.pop_for(db, "umo-a", now=1100)
        self.assertEqual(len(taken), 1)
        self.assertEqual(taken[0]["text"], "想跟你说句话")
        self.assertEqual(UD.all_items(db, now=1100), [])      # 取走就没了

    def test_only_matching_session(self):
        db = FakeDB()
        UD.enqueue(db, "umo-a", "给 A 的", ts=1000)
        UD.enqueue(db, "umo-b", "给 B 的", ts=1000)
        self.assertEqual([item["text"] for item in UD.pop_for(db, "umo-b", now=1100)], ["给 B 的"])
        self.assertEqual([item["text"] for item in UD.pop_for(db, "umo-a", now=1100)], ["给 A 的"])

    def test_expired_are_dropped(self):
        db = FakeDB()
        UD.enqueue(db, "umo-a", "昨天的情绪", ts=1000)
        self.assertEqual(UD.pop_for(db, "umo-a", now=1000 + UD.TTL + 10), [])

    def test_capped(self):
        db = FakeDB()
        for index in range(6):
            UD.enqueue(db, "umo-a", "第%d条" % index, ts=1000 + index)
        items = UD.all_items(db, now=1010)
        self.assertEqual(len(items), UD.MAX_ITEMS)
        self.assertEqual(items[-1]["text"], "第5条")

    def test_blank_text_ignored(self):
        db = FakeDB()
        self.assertFalse(UD.enqueue(db, "umo-a", "   ", ts=1000))
        self.assertEqual(UD.all_items(db, now=1010), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
