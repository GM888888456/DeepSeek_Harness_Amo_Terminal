# -*- coding: utf-8 -*-
"""宅内人事（司机/厨师/管家）与「在家吃、有人开车」的测试。"""

from __future__ import annotations

import importlib.util
import io
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)


def load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, rel))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


HH = load("amo_household", "amo_core/household.py")
PA = load("amo_persona_archive_h", "amo_core/persona_archive.py")


class StaffTest(unittest.TestCase):
    def test_titles_from_lineage(self):
        self.assertEqual(HH.driver_title(), "周师傅")
        self.assertEqual(HH.cook_title(), "郑师傅")
        self.assertEqual(HH.helper_title(), "李姐")
        self.assertEqual(HH.housekeeper_title(), "陈姨")

    def test_unknown_role_falls_back(self):
        self.assertEqual(HH.staff_title("宇航员", "没人"), "没人")


class HomeTest(unittest.TestCase):
    def test_home_detection(self):
        self.assertTrue(HH.is_home("云顶山庄·沈家庄园"))
        self.assertTrue(HH.is_home("家里"))
        self.assertFalse(HH.is_home("贵阳·酉阳桃花源旅游景区"))
        self.assertFalse(HH.is_home("路上"))

    def test_home_meal_banks_are_by_time(self):
        breakfast, home = HH.meal_bank(8, home=True)
        lunch, _ = HH.meal_bank(12, home=True)
        dinner, _ = HH.meal_bank(19, home=True)
        self.assertTrue(home)
        self.assertEqual(breakfast, HH.HOME_BREAKFAST)
        self.assertEqual(lunch, HH.HOME_LUNCH)
        self.assertEqual(dinner, HH.HOME_DINNER)

    def test_no_home_bank_outside(self):
        bank, home = HH.meal_bank(12, home=False)
        self.assertEqual(bank, ())
        self.assertFalse(home)

    def test_home_meals_never_say_downstairs_or_takeout(self):
        for bank in (HH.HOME_BREAKFAST, HH.HOME_LUNCH, HH.HOME_DINNER):
            for line in bank:
                for bad in ("下楼", "外卖", "便利店", "小馆子", "同事"):
                    self.assertNotIn(bad, line, line)

    def test_commute_never_self_driving(self):
        for line in HH.commute_bank():
            self.assertIn("老周", line)
            self.assertNotIn("我开车", line)


class CarTest(unittest.TestCase):
    def setUp(self):
        self.archive = PA.parse(io.open(os.path.join(HERE, "fixtures", "persona_template.txt"),
                                       encoding="utf-8").read())

    def test_car_from_archive(self):
        self.assertEqual(HH.car_label(self.archive), "宝马A8·贵A·00008")

    def test_car_absent_is_empty(self):
        self.assertEqual(HH.car_label(None), "")
        self.assertEqual(HH.car_label(PA.parse("姓名：张三")), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
