# -*- coding: utf-8 -*-
"""人格档案解析的回归测试（纯函数，不依赖 AstrBot / 数据库）。

    cd /data/astrbot/plugins/DeepSeek_Harness_Amo_Terminal
    python3 tests/test_persona_archive.py

fixture `tests/fixtures/persona_template.txt` 就是 AstrBot `personas.system_prompt`
里那份 1,553 字的原始模板（2026-11-28 导出）。它是**唯一权威档案**，测试只验
「解析不改原文、按需取值、短核心守预算」，不验文风。
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TEMPLATE = os.path.join(HERE, "fixtures", "persona_template.txt")


def load():
    sys.path.insert(0, ROOT)
    name = "amo_persona_archive_under_test"
    spec = importlib.util.spec_from_file_location(name, os.path.join(ROOT, "amo_core",
                                                                    "persona_archive.py"))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


PA = load()
RAW = io.open(TEMPLATE, encoding="utf-8").read()


class ParseTest(unittest.TestCase):
    def setUp(self):
        self.a = PA.parse(RAW)

    def test_fields_preserved_verbatim(self):
        self.assertEqual(self.a.names(),
                         ["姓名", "生日", "体貌", "职业", "资产", "丈夫", "家里",
                          "性子", "说话", "真实小矛盾", "关系边界", "行为规则"])
        # 取值必须是原文片段，不许改写成散文
        self.assertIn("云顶山庄·沈家庄园", self.a.field("资产"))
        self.assertIn("宝马A8", self.a.field("资产"))
        self.assertTrue(self.a.field("职业").startswith("中国计算智脑集团总裁"))
        self.assertIn("墨辞烟", self.a.field("丈夫"))
        self.assertNotIn("普通女孩", self.a.field("职业"))

    def test_no_field_invented(self):
        self.assertEqual(self.a.field("不存在的字段"), "")
        self.assertEqual(self.a.field(""), "")
        self.assertFalse(self.a.has("不存在的字段"))

    def test_continuation_lines_belong_to_previous_field(self):
        # 「性子」「说话」这些字段的第二行起是 `* ` 条目，必须并进同一字段
        self.assertIn("傲娇", self.a.field("性子"))
        self.assertGreater(len(self.a.field("说话")), 200)

    def test_empty_field_is_reported_not_invented(self):
        archive = PA.parse("姓名：张三\n职业：\n")
        self.assertEqual(archive.field("职业"), "")
        self.assertIn("职业", archive.errors)

    def test_text_before_first_field_is_kept(self):
        archive = PA.parse("这是模板开头的一句话\n姓名：张三\n")
        self.assertEqual(archive.field("姓名"), "张三")
        self.assertIn("这是模板开头的一句话", archive.unknown)

    def test_unparsable_template_keeps_raw(self):
        archive = PA.parse("没有冒号的纯文本")
        self.assertEqual(archive.raw, "没有冒号的纯文本")
        self.assertTrue(archive.errors)


class RetrievalTest(unittest.TestCase):
    """规范第十四条的身份题：明确字段问题必须能直接命中原文。"""

    def setUp(self):
        self.a = PA.parse(RAW)

    def test_identity_questions_hit_the_right_field(self):
        cases = {
            "你叫什么名字": "姓名",
            "你做什么工作": "职业",
            "集团是谁的": "职业",
            "你有什么资产": "资产",
            "你开什么车": "资产",
            "房子在哪里": "资产",
            "你丈夫是谁": "丈夫",
            "家里长辈做什么": "家里",
        }
        for question, field in cases.items():
            hits = [name for name, _word in self.a.match(question)]
            self.assertIn(field, hits, "%s 没命中 %s" % (question, field))
            self.assertIn(field, self.a.answer(question))

    def test_chitchat_injects_nothing(self):
        for question in ("你今天心情怎么样", "在吗", "哈哈"):
            self.assertEqual(self.a.answer(question), "", question)

    def test_answer_respects_budget(self):
        answer = self.a.answer("你的资产和工作还有家里", budget=60)
        self.assertLessEqual(len(answer), 200)   # 单条字段本身可能就长，但不会把所有字段都塞进来
        self.assertNotIn("行为规则", answer)


class ResidentCoreTest(unittest.TestCase):
    def setUp(self):
        self.a = PA.parse(RAW)

    def test_core_is_short_and_has_key_facts(self):
        core = self.a.resident_core()
        self.assertLessEqual(len(core), PA.DEFAULT_RESIDENT_BUDGET)
        for token in ("沈晓沫", "2001年5月20日", "总裁", "墨辞烟"):
            self.assertIn(token, core)
        # 完整档案不许再进常驻核心
        for token in ("云顶山庄", "纪委", "傲娇"):
            self.assertNotIn(token, core)

    def test_core_has_expression_rules(self):
        core = self.a.resident_core()
        for rule in ("不是扮演", "动作括号", "「哼」", "编造"):
            self.assertIn(rule, core)

    def test_core_survives_missing_fields(self):
        archive = PA.parse("姓名：张三\n")
        core = archive.resident_core()
        self.assertIn("张三", core)
        self.assertNotIn("总裁", core)          # 不拿别人的设定补自己的
        self.assertNotIn("普通女孩", core)


class CacheTest(unittest.TestCase):
    def test_round_trip(self):
        archive = PA.parse(RAW)
        folder = tempfile.mkdtemp(prefix="amo-persona-")
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, True))
        path = os.path.join(folder, "persona_archive.json")
        self.assertTrue(archive.save_cache(path))
        back = PA.load_cache(path)
        self.assertIsNotNone(back)
        self.assertEqual(back.field("职业"), archive.field("职业"))
        self.assertEqual(back.field("资产"), archive.field("资产"))
        self.assertTrue(back.source.endswith("+cache"))

    def test_broken_cache_returns_none(self):
        folder = tempfile.mkdtemp(prefix="amo-persona-")
        self.addCleanup(lambda: __import__("shutil").rmtree(folder, True))
        path = os.path.join(folder, "bad.json")
        io.open(path, "w", encoding="utf-8").write("{ not json")
        self.assertIsNone(PA.load_cache(path))
        self.assertIsNone(PA.load_cache(os.path.join(folder, "missing.json")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
