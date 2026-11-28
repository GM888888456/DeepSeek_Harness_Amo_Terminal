# -*- coding: utf-8 -*-
"""生图姿势/道具约束的单元测试（不依赖 AstrBot）。

    cd /data/astrbot/plugins/DeepSeek_Harness_Amo_Terminal
    python3 tests/test_pose.py

**这里只验提示词文本，不等于图片质量通过。** 视觉验收必须真机出一张图再看得见的东西
（日志里 `image_caption` 那行最准），见 README 的「生图验收」一节。

约束来源是 2026-11-23/24 用户口径，本测试只做护栏，不改文案：
- 自拍：一只手在画面外举手机（前置摄像头物理事实），另一只手做姿态动作；
  手机本身不入镜，画面里只有她本人和她所在的地方；
- 他拍：拍摄者在镜头后方、站在画面外；
- 参考图只定长相/身高比例/发长，姿势与头部朝向每次重新摆（歪头就是被母图带出来的）；
- 只有提示词明确写了在吃喝，才让她手里拿东西。
"""

from __future__ import annotations

import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def load():
    name = "amo_image_consistency_under_test"
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "amo_core", "media_image", "consistency.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


C = load()

#: 不该无缘无故出现的道具（用户口径：自拍默认不安排这些东西）
UNWANTED_PROPS = ("花束", "咖啡", "饮料", "奶茶", "包", "雨伞", "书", "玩偶", "气球")


class ReferenceImageTest(unittest.TestCase):
    def test_reference_only_fixes_identity(self):
        clause = C.REF_ONLY_CLAUSE
        self.assertIn("长相", clause)
        self.assertIn("身高比例", clause)
        self.assertIn("发长", clause)
        # 姿势/头部朝向/手的位置必须写「重新摆」，否则图生图会照抄母图姿态
        self.assertIn("重新摆", clause)
        for word in ("姿势", "头部朝向", "手放哪里"):
            self.assertIn(word, clause)

    def test_clause_is_appended_every_way(self):
        for selfie in (True, False):
            for seed in ("", "a", "b", "c", "d", "e", "f", "g"):
                self.assertIn(C.REF_ONLY_CLAUSE, C.pose_clause(selfie, seed=seed))


class SelfiePoseTest(unittest.TestCase):
    def test_phone_stays_out_of_frame(self):
        for seed in ("", "s1", "s2", "s3", "s4", "s5", "s6", "s7", "s8", "s9"):
            clause = C.pose_clause(True, seed=seed)
            self.assertIn("自拍", clause)
            self.assertTrue("画面外" in clause or "不入镜" in clause, clause)

    def test_head_pose_always_present(self):
        for seed in ("", "x1", "x2", "x3"):
            self.assertIn("头部朝向", C.pose_clause(True, seed=seed))

    def test_no_unrequested_props(self):
        for seed in ("", "p1", "p2", "p3", "p4", "p5", "p6", "p7", "p8", "p9"):
            clause = C.pose_clause(True, seed=seed)
            for prop in UNWANTED_PROPS:
                self.assertNotIn(prop, clause, "自拍默认不该出现道具：%s" % prop)

    def test_prop_only_when_asked(self):
        with_prop = C.pose_clause(True, with_prop=True, seed="带道具")
        plain = C.pose_clause(True, with_prop=False, seed="带道具")
        self.assertNotEqual(with_prop, plain)
        self.assertIn("吃", with_prop)
        # 手机在镜头外的说法两种写法都行：「画面外」或「不入镜」
        self.assertTrue("画面外" in with_prop or "不入镜" in with_prop, with_prop)

    def test_body_pose_varies_with_seed(self):
        seen = {C.pose_clause(True, seed="seed-%d" % i) for i in range(12)}
        self.assertGreater(len(seen), 3, "姿势池应该随种子换，别每次一个样")


class OtherPersonPoseTest(unittest.TestCase):
    def test_shooter_stays_out_of_frame(self):
        clause = C.pose_clause(False)
        self.assertIn("拍摄者", clause)
        self.assertIn("画面外", clause)
        self.assertIn(C.REF_ONLY_CLAUSE, clause)

    def test_no_unrequested_props(self):
        clause = C.pose_clause(False)
        for prop in UNWANTED_PROPS:
            self.assertNotIn(prop, clause)


class NegativeListTest(unittest.TestCase):
    def test_phone_in_frame_is_forbidden(self):
        text = C.POSE_NEGATIVE
        self.assertIn("手机出现在画面里", text)
        self.assertIn("断手", text)          # 手部畸形的兜底
        self.assertIn("多只手", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
