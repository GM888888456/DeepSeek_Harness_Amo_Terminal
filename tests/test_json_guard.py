# -*- coding: utf-8 -*-
"""模型输出 JSON 校验的测试（规范 5.6）。"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load():
    spec = importlib.util.spec_from_file_location("amo_json_guard",
                                                  os.path.join(ROOT, "amo_core/json_guard.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


JG = load()
SPEC = {"city": "str", "hobbies": "list", "daily_life": "str", "world_rules": "str?"}


class ValidateTest(unittest.TestCase):
    def test_good_payload(self):
        ok, problems = JG.validate({"city": "贵阳", "hobbies": ["喝茶"], "daily_life": "上班"},
                                   SPEC)
        self.assertTrue(ok)
        self.assertEqual(problems, [])

    def test_missing_required(self):
        ok, problems = JG.validate({"city": "贵阳", "hobbies": []}, SPEC)
        self.assertFalse(ok)
        self.assertTrue(any("daily_life" in item for item in problems))

    def test_optional_field_may_be_missing(self):
        ok, _problems = JG.validate({"city": "贵阳", "hobbies": ["a"], "daily_life": "x"}, SPEC)
        self.assertTrue(ok)

    def test_wrong_type(self):
        ok, problems = JG.validate({"city": 1, "hobbies": "x", "daily_life": "d"}, SPEC)
        self.assertFalse(ok)
        self.assertEqual(len(problems), 2)

    def test_not_an_object(self):
        ok, problems = JG.validate(["nope"], SPEC)
        self.assertFalse(ok)
        self.assertIn("不是 JSON 对象", " ".join(problems))

    def test_bool_is_not_a_number(self):
        ok, problems = JG.validate({"n": True}, {"n": "int"})
        self.assertFalse(ok)
        self.assertTrue(any("布尔" in item for item in problems))


class CleanTest(unittest.TestCase):
    def test_drops_bad_and_truncates(self):
        data = {"city": "  贵阳  ", "hobbies": ["a", "b"], "daily_life": "x" * 5000,
                "world_rules": 123}
        out = JG.clean(data, SPEC, max_len=100)
        self.assertEqual(out["city"], "贵阳")
        self.assertEqual(out["hobbies"], ["a", "b"])
        self.assertEqual(len(out["daily_life"]), 100)
        self.assertNotIn("world_rules", out)      # 类型不对就丢，不猜

    def test_non_dict(self):
        self.assertEqual(JG.clean("x", SPEC), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)
