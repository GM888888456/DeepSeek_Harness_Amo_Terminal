# -*- coding: utf-8 -*-
"""口癖/开场检查的回归测试（纯本地，不调模型）。"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, path))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


EG = load("amo_expression_guard", "amo_core/expression_guard.py")


class OpenerTest(unittest.TestCase):
    def test_detects_opener(self):
        self.assertEqual(EG.opener_of("哼，少来"), "哼")
        self.assertEqual(EG.opener_of("凭什么听你的"), "凭什么")
        self.assertEqual(EG.opener_of("我才不去"), "我才不")
        self.assertEqual(EG.opener_of("今天有点累"), "")

    def test_repeat_opener_removed_once(self):
        guard = EG.OpeningGuard()
        text, note = guard.check("u1", "哼，你先说")
        self.assertEqual(text, "哼，你先说")     # 第一次不管
        self.assertEqual(note, "")
        text, note = guard.check("u1", "哼，我不听")
        self.assertEqual(text, "我不听")          # 上一次也是「哼」→ 去掉
        self.assertIn("开场重复", note)

    def test_does_not_swap_to_another_filler(self):
        guard = EG.OpeningGuard()
        guard.check("u1", "哼，好吧")
        text, _note = guard.check("u1", "哼，随便")
        self.assertFalse(text.startswith("切"))   # 禁止用「切」顶替
        self.assertFalse(text.startswith("哼"))

    def test_other_sessions_independent(self):
        guard = EG.OpeningGuard()
        guard.check("u1", "哼，一个人")
        text, note = guard.check("u2", "哼，两个人")
        self.assertEqual(text, "哼，两个人")
        self.assertEqual(note, "")

    def test_never_returns_empty(self):
        guard = EG.OpeningGuard()
        guard.check("u1", "哼")
        text, _note = guard.check("u1", "哼")
        self.assertTrue(text.strip())


class DiagnoseTest(unittest.TestCase):
    def test_action_and_star(self):
        self.assertIn("动作括号", EG.diagnose("（笑了笑）你好呀"))
        self.assertIn("星号旁白", EG.diagnose("*轻轻叹气* 算了"))
        self.assertIn("波浪号过多", EG.diagnose("好呀~~真的~~"))

    def test_clean_text(self):
        self.assertEqual(EG.diagnose("今天在公司忙了一天"), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
