# -*- coding: utf-8 -*-
"""软活动层（候选池 + 连续性约束）的测试。"""

from __future__ import annotations

import importlib.util
import os
import random
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load():
    spec = importlib.util.spec_from_file_location("amo_activity_pool",
                                                  os.path.join(ROOT, "amo_core/activity_pool.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


AP = load()


class PoolTest(unittest.TestCase):
    def test_pools_exist(self):
        self.assertTrue(AP.candidates("home", "rest"))
        self.assertTrue(AP.candidates("company", "work"))
        self.assertEqual(AP.candidates("home", "unknown"), ())

    def test_never_repeat_previous(self):
        rng = random.Random(1)
        prev = AP.candidates("home", "rest")[0]
        for _ in range(20):
            picked = AP.pick("home", "rest", prev=prev, rng=rng)
            self.assertNotEqual(picked, prev)

    def test_never_repeat_last_two(self):
        rng = random.Random(2)
        recent = list(AP.candidates("home", "rest")[:2])
        for _ in range(20):
            picked = AP.pick("home", "rest", prev=recent[-1], recent=recent, rng=rng)
            self.assertNotIn(picked, recent)

    def test_daily_cap_degrades_gracefully(self):
        pool = AP.candidates("home", "rest")
        counts = {text: AP.CAP for text in pool}       # 全部打满
        picked = AP.pick("home", "rest", counts=counts, rng=random.Random(3))
        self.assertTrue(picked)                        # 不会返回空

    def test_idle_gets_looser_cap(self):
        idle = [text for text in AP.candidates("home", "rest")
                if any(word in text for word in AP.IDLE_WORDS)][0]
        self.assertEqual(AP._cap_of(idle), AP.CAP_LOOSE)

    def test_cross_day_same_slot_avoided(self):
        pool = AP.candidates("home", "rest")
        history = [{20: pool[0]}]
        for _ in range(30):
            picked = AP.pick("home", "rest", hour=20, history=history, rng=random.Random(4))
            self.assertNotEqual(picked, pool[0])

    def test_mood_weighting(self):
        picked = AP.pick("home", "rest", mood="tired", rng=random.Random(5))
        self.assertTrue(any(word in picked for word in AP.STATE_BONUS["tired"]), picked)

    def test_note_counts(self):
        counts = {}
        AP.note(counts, "刷手机")
        AP.note(counts, "刷手机")
        self.assertEqual(counts["刷手机"], 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)


class NoHallucinatedCarTest(unittest.TestCase):
    """2026-11-28 用户口径：资产里没车就不许自己造一辆。"""

    def test_schedule_engine_has_no_random_car_fallback(self):
        import io
        src = io.open(os.path.join(ROOT, "schedule_engine.py"), encoding="utf-8").read()
        self.assertNotIn("car = CAR_POOL", src)
        self.assertNotIn("CAR_POOL", src)      # 连常量都删了，免得以后又被拿来兜底
        self.assertIn('car = car or ""', src)
        self.assertIn("CAR_BRANDS", src)       # 但「从人格里读车品牌」要留着


class SoftActivityInScheduleTest(unittest.TestCase):
    """日程要真的用上软活动层，而不是又回到 BANK 随机。"""

    def test_schedule_engine_calls_activity_pool(self):
        import io
        src = io.open(os.path.join(ROOT, "schedule_engine.py"), encoding="utf-8").read()
        self.assertIn("activity_pool import pick", src)
        self.assertIn("_save_activity_history", src)
        self.assertIn("_mood_of", src)
