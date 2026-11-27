# -*- coding: utf-8 -*-
"""`amo_core/text_split.py` 的回归测试（纯函数，不依赖 AstrBot）。

    cd /data/astrbot/plugins/DeepSeek_Harness_Amo_Terminal
    python3 tests/test_text_split.py

`golden_text_split.json` 的来源：拆模块**之前**从旧的 main.py 现算一遍，再和新模块
逐条比对（并做过 19 个单元的源码级逐字比对，19/19 一致）。之后它就是防回归的基线：
改了切分规则导致输出变化，这里会直接红。
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GOLDEN = os.path.join(HERE, "golden_text_split.json")


def load():
    path = os.path.join(ROOT, "amo_core", "text_split.py")
    if ROOT not in sys.path:  # text_clean / util 在插件根上
        sys.path.insert(0, ROOT)
    name = "amo_text_split_under_test"
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


TOOLS = load()
GOLD = json.load(io.open(GOLDEN, encoding="utf-8"))


class GoldenTest(unittest.TestCase):
    def test_segment_text_matches_golden(self):
        for case in GOLD["samples"]:
            self.assertEqual(TOOLS.segment_text(case["text"]), case["segment_text"], case["text"])
            self.assertEqual(TOOLS.segment_text(case["text"], keep_punc=False),
                             case["no_punc"], case["text"])
            self.assertEqual(TOOLS.segment_text(case["text"], min_len=2, max_len=12),
                             case["short"], case["text"])

    def test_voice_tag_helpers_match_golden(self):
        for text, expected in GOLD["split_voice_tag"].items():
            self.assertEqual(list(TOOLS.split_voice_tag(text)), expected, text)
        for text, expected in GOLD["strip_voice_tags"].items():
            self.assertEqual(TOOLS._strip_voice_tags(text), expected, text)

    def test_same_sentence_matches_golden(self):
        for a, b, expected in GOLD["same_sentence"]:
            self.assertEqual(TOOLS.same_sentence(a, b), expected, (a, b))

    def test_typing_delay_is_bounded(self):
        """typing_delay_ms 自带 ±15~20% 随机（模拟真人手速），只能验区间和上限。"""
        for text in ("你好呀", "", "a" * 200, "这是一句比较长的话，用来看看打字延迟会不会到上限"):
            clean = text.replace(" ", "")
            nominal = min(700 + len(clean) * 400, 20000)
            value = TOOLS.typing_delay_ms(text)
            self.assertGreaterEqual(value, int(max(200, nominal * 0.85)), text[:16])
            self.assertLessEqual(value, int(max(200, nominal * 1.2)) + 1, text[:16])
            self.assertGreaterEqual(value, 200)


class InvariantTest(unittest.TestCase):
    """不看金标准也要成立的硬约束。"""

    LINE = "今天在公司开了一上午会，下午去贵安机房看线缆，回来路上买了杯冰水，晚上想吃点辣的。" * 2

    def test_respects_limits(self):
        for kwargs in ({}, {"max_segments": 2}, {"max_len": 12}, {"min_len": 2, "max_len": 8}):
            segments = TOOLS.segment_text(self.LINE, **kwargs)
            self.assertLessEqual(len(segments), kwargs.get("max_segments", 4))
            for seg in segments:
                self.assertTrue(seg.strip())
                # 注意：max_len 只是切分时的**倾向**，遇到「一逗到底」的长句它守不住
                # 上限（宁可整句发出去，也不硬断在词中间）。这里只验不产出空段。

    def test_does_not_invent_text(self):
        text = "他说明天下午三点在观山湖公园门口等我，别迟到。"
        joined = "".join(TOOLS.segment_text(text)).replace("\u200b", "")
        for char in set(joined):
            self.assertIn(char, text, "切出来出现了原文没有的字符：%r" % char)

    def test_voice_tag_semantics(self):
        # 有开标签时只取标签里那句要念的话，标签外的话不混进去（原有语义）
        self.assertEqual(TOOLS._strip_voice_tags("<amo_speak>好</amo_speak>呀"), "好")
        self.assertEqual(TOOLS._strip_voice_tags("没有标签的句子"), "没有标签的句子")
        self.assertNotIn("amo_speak", TOOLS._strip_voice_tags("<amo_speak>x</amo_speak>ab"))
        self.assertEqual(TOOLS.split_voice_tag("plain")[1], "plain")

    def test_all_names_exported(self):
        for name in ("segment_text", "typing_delay_ms", "same_sentence",
                     "split_voice_tag", "_strip_voice_tags", "_protect_mask",
                     "_split_regex", "_mask_with_placeholders", "_cut",
                     "_norm_sentence", "_bigrams", "_cover_ratio",
                     "_VOICE_TAG_RE", "_VOICE_TAG_OPEN_RE", "_PAIRS",
                     "_STRONG", "_WEAK", "_TRIM"):
            self.assertIn(name, TOOLS.__all__, name)
            self.assertTrue(hasattr(TOOLS, name), name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
