# -*- coding: utf-8 -*-
"""方言下线的护栏测试（2026-11-28 产品决定）。

    python3 tests/test_dialect_off.py

守的是四件事：

1. `_dialect_active()` 恒为 False —— 生成链路里所有方言注入都问它一个函数；
2. 面板和 schema 里不能再出现方言入口（不然「下线」只是说说）；
3. `dialects` 表、词表、`_dialect_rows()` 这些**数据**要留着（先解耦，不迁移、不删）；
4. `polish.py` 的出口校验词表不能被动到 —— 它自带口语时间词（「清早八晨」这类），
   跟方言开关无关；口语表达和原有语感靠它兜着。
"""

from __future__ import annotations

import ast
import io
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)


def read(*parts):
    return io.open(os.path.join(ROOT, *parts), encoding="utf-8").read()


class DialectOffTest(unittest.TestCase):
    def test_switch_is_hard_off(self):
        tree = ast.parse(read("amo_core", "persona.py"))
        method = None
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_dialect_active":
                method = node
        self.assertIsNotNone(method, "persona.py 里找不到 _dialect_active")
        body = [stmt for stmt in method.body
                if not (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant))]
        self.assertEqual(len(body), 1, "开关函数不该再有分支：%s" % ast.dump(body[0])[:80])
        self.assertIsInstance(body[0], ast.Return)
        self.assertIsInstance(body[0].value, ast.Constant)
        self.assertIs(body[0].value.value, False)

    def test_panel_and_schema_have_no_dialect_entry(self):
        schema = json.loads(read("_conf_schema.json"))
        for key in ("dialect_enabled", "create_dialect_kb", "dialect_kb_name"):
            self.assertNotIn(key, schema, "schema 里还应删掉：%s" % key)
        page = read("views", "dashboard", "index.html")
        for token in ("worldDialect", "btnKb", "dialectHint"):
            self.assertNotIn(token, page, "面板里还有方言入口：%s" % token)

    def test_word_bank_is_kept(self):
        db = read("amo_core", "amo_db.py")
        self.assertIn("CREATE TABLE IF NOT EXISTS dialects", db)
        self.assertIn("_seed_dialects", db)
        persona = read("amo_core", "persona.py")
        self.assertIn("DIALECT_FALLBACK_ROWS", persona)
        self.assertIn("def _dialect_rows", persona)

    def test_polish_word_list_untouched(self):
        polish = read("amo_core", "polish.py")
        for word in ("清早八晨", "今儿", "明儿", "礼拜"):
            self.assertIn(word, polish, "出口校验的口语时间词被动了：%s" % word)

    def test_web_api_rejects_dialect_style(self):
        api = read("amo_core", "web_api.py")
        self.assertNotIn('if key == "dialect_style"', api)
        self.assertIn("方言已下线", api)


if __name__ == "__main__":
    unittest.main(verbosity=2)
