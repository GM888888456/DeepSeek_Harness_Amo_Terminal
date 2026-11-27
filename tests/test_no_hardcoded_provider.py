# -*- coding: utf-8 -*-
"""守护：代码里不许再写死 provider id / 模型名（2026-11-28 用户口径）。

    python3 tests/test_no_hardcoded_provider.py

起因：11-27 一天里三个 provider 被删、11-28 主模型也换了，而 `amo_core/llm_service.py`
里写死的辅助模型链（`智谱网站/GLM-4-flash`、`硅基流动/Qwen/Qwen3-8B`）让日志天天刷
"provider not found"，辅助调用悄悄退化成主模型。

规矩：模型 id 只许出现在**配置**里（`aux_provider_<kind>`、`cmd_config.json`），
代码里出现就是回归。
"""

from __future__ import annotations

import io
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

#: 历史上真实出现过、后来被删掉的 provider id 前缀 —— 出现即回归。
BANNED = ("智谱网站", "官方网站/", "星桥网站/", "星渊站点", "星渊网站")
#: 这些是画图后端的品牌名（不是对话 provider），允许出现在 Image 插件里
ALLOWED_FILES = {os.path.join("DeepSeek_Harness_Amo_Image", "main.py"),
                 os.path.join("DeepSeek_Harness_Amo_Image", "providers.py")}


def iter_sources():
    root = os.path.dirname(ROOT)
    for plugin in sorted(os.listdir(root)):
        if not plugin.startswith("DeepSeek_Harness_Amo_"):
            continue
        for folder, _dirs, files in os.walk(os.path.join(root, plugin)):
            if ".git" in folder or "__pycache__" in folder:
                continue
            for name in files:
                if name.endswith(".py") and name != os.path.basename(__file__):
                    yield os.path.join(folder, name)


class NoHardcodedProviderTest(unittest.TestCase):
    def test_no_known_dead_provider_ids_in_code(self):
        offenders = []
        for path in iter_sources():
            text = io.open(path, encoding="utf-8", errors="replace").read()
            for token in BANNED:
                if token in text:
                    offenders.append("%s: %s" % (os.path.relpath(path, os.path.dirname(ROOT)), token))
        self.assertEqual(offenders, [], "代码里还写死着 provider id：\n" + "\n".join(offenders))

    def test_aux_models_come_from_config_only(self):
        text = io.open(os.path.join(ROOT, "amo_core", "llm_service.py"), encoding="utf-8").read()
        self.assertIn("AUX_KINDS", text)
        self.assertNotIn("AUX_ROUTES", text, "AUX_ROUTES 又回来了：辅助模型不该有内置默认链")
        self.assertIn("aux_provider_", text)
        # 留空必须能走主模型，而不是报错或返回空
        self.assertIn("await self.provider(umo)", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
