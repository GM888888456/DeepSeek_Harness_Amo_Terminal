# -*- coding: utf-8 -*-
"""公共模块入口（shim）回归测试。

跑法：

    cd /data/astrbot/plugins/DeepSeek_Harness_Amo_Terminal/amo_shared
    python3 tests/test_shims.py          # 或 python3 -m unittest discover tests

覆盖：

1. 五个插件里的入口都能加载，并且拿到的是**同一份**公共实现（同一个类对象）；
2. `Chain` 行为不变：trace 号、steps、ok、summary、失败打 warning；
3. 记忆层的入口仍然是「成功步骤打 debug」；
4. 终端插件缺失 / 公共实现过旧 / 公共实现缺接口 → 降级成最小实现，导入不抛异常。
"""

from __future__ import annotations

import importlib.util
import io
import os
import shutil
import sys
import tempfile
import unittest

PLUGINS = os.environ.get("AMO_PLUGINS", "/data/astrbot/plugins")
TERMINAL = "DeepSeek_Harness_Amo_Terminal"
_LOADED = 0


def load(path, name=None):
    """按文件路径加载一个入口模块（模拟 AstrBot 的加载方式）。"""
    global _LOADED
    _LOADED += 1
    name = name or "shim_test_%d" % _LOADED
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    # 子包（Image/sp、Terminal/mem）在生产里是把这个目录插进 sys.path 再 import 的，
    # 所以 sp/link.py 这类「from sp_link import *」的兼容层，测试里也要同样给路径。
    folder = os.path.dirname(path)
    added = folder not in sys.path
    if added:
        sys.path.insert(0, folder)
    try:
        spec.loader.exec_module(module)
    finally:
        if added:
            try:
                sys.path.remove(folder)
            except ValueError:
                pass
    return module


class FakeLog:
    def __init__(self):
        self.lines = []

    def _record(self, level):
        def take(message, *args, **kwargs):
            self.lines.append((level, str(message)))
        return take

    def __getattr__(self, level):
        return self._record(level)


class SharedTest(unittest.TestCase):
    def setUp(self):
        self.terminal = load(os.path.join(PLUGINS, TERMINAL, "chain.py"))
        self.image = load(os.path.join(PLUGINS, "DeepSeek_Harness_Amo_Image", "chain.py"))
        self.finance = load(os.path.join(PLUGINS, "DeepSeek_Harness_Amo_Finance", "chain.py"))
        self.market = load(os.path.join(PLUGINS, "DeepSeek_Harness_Amo_Market", "chain.py"))
        self.medical = load(os.path.join(PLUGINS, "DeepSeek_Harness_Amo_Medical", "chain.py"))
        self.sp = load(os.path.join(PLUGINS, "DeepSeek_Harness_Amo_Image", "sp", "sp_chain.py"))
        self.mem = load(os.path.join(PLUGINS, TERMINAL, "mem", "mem_chain.py"))

    def test_all_use_shared_implementation(self):
        for name, module in (("terminal", self.terminal), ("image", self.image),
                             ("finance", self.finance), ("market", self.market),
                             ("medical", self.medical), ("sp", self.sp)):
            self.assertEqual(getattr(module, "SHIM_SOURCE", ""), "shared", name)
        # 同一个类对象：任何一处 isinstance 判断都不会因为「另一份拷贝」而失效
        self.assertIs(self.terminal.Chain, self.image.Chain)
        self.assertIs(self.image.Chain, self.finance.Chain)
        self.assertIs(self.finance.Chain, self.market.Chain)
        self.assertIs(self.market.Chain, self.medical.Chain)
        self.assertIs(self.medical.Chain, self.sp.Chain)

    def test_memory_layer_keeps_debug_level(self):
        self.assertTrue(issubclass(self.mem.Chain, self.image.Chain))
        self.assertIsNot(self.mem.Chain, self.image.Chain)
        log = FakeLog()
        self.mem.Chain("mem.test", logger=log).step("read")
        self.assertEqual([level for level, _ in log.lines], ["debug"])

    def test_chain_behaviour_unchanged(self):
        log = FakeLog()
        chain = self.image.Chain("medical.treat", event_id="abc123", logger=log)
        chain.step("quote", cost=200, plan="门诊")
        chain.step("pay", ok=False, detail="余额不足", balance=10)
        chain.done(executed=False)
        self.assertEqual(chain.trace, "abc123")
        self.assertEqual([item["stage"] for item in chain.steps], ["quote", "pay", "done"])
        self.assertFalse(chain.ok)
        self.assertIn("quote", chain.summary())
        self.assertIn("余额不足", chain.summary())
        self.assertEqual([level for level, _ in log.lines], ["info", "warning", "info"])
        self.assertIn("[chain] abc123 quote", log.lines[0][1])
        self.assertIn("cost=200", log.lines[0][1])
        self.assertIn(" FAIL:", log.lines[1][1])

    def test_class_reports_version(self):
        self.assertGreaterEqual(getattr(self.terminal.Chain.__module__ and
                                        sys.modules[self.terminal.Chain.__module__],
                                        "SHIM_VERSION", 0), 1)


class FallbackTest(unittest.TestCase):
    """终端插件缺失 / 公共实现过旧 / 缺接口：都要能降级，不能把插件带崩。"""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="amo-shim-")
        self.addCleanup(shutil.rmtree, self.root, True)
        os.makedirs(os.path.join(self.root, "DeepSeek_Harness_Amo_Image"))
        shutil.copy2(os.path.join(PLUGINS, "DeepSeek_Harness_Amo_Image", "chain.py"),
                     os.path.join(self.root, "DeepSeek_Harness_Amo_Image", "chain.py"))

    def _write_shared(self, body):
        folder = os.path.join(self.root, TERMINAL, "amo_shared")
        os.makedirs(folder)
        path = os.path.join(folder, "chain.py")
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(body)
        return path

    def _load_image(self):
        return load(os.path.join(self.root, "DeepSeek_Harness_Amo_Image", "chain.py"))

    def test_missing_terminal_falls_back(self):
        module = self._load_image()
        self.assertEqual(module.SHIM_SOURCE, "fallback")
        log = FakeLog()
        chain = module.Chain("x", logger=log).step("a", cost=1)
        self.assertEqual(chain.steps[0]["stage"], "a")
        self.assertEqual(chain.name, "x")
        self.assertEqual(chain.summary(), "a")
        self.assertEqual(log.lines, [])  # 降级实现不写链日志，但不报错

    def test_old_version_falls_back(self):
        self._write_shared("SHIM_VERSION = 0\nclass Chain:\n    pass\n")
        self.assertEqual(self._load_image().SHIM_SOURCE, "fallback")

    def test_missing_interface_falls_back(self):
        self._write_shared('SHIM_VERSION = 1\n"""没有 Chain"""\n')
        self.assertEqual(self._load_image().SHIM_SOURCE, "fallback")

    def test_broken_shared_falls_back(self):
        self._write_shared("SHIM_VERSION = 1\nraise RuntimeError('boom')\n")
        self.assertEqual(self._load_image().SHIM_SOURCE, "fallback")


class FakeConfig(dict):
    """模拟 AstrBot 的配置对象：dict + config_path。"""

    def __init__(self, path, **values):
        super().__init__(**values)
        self.config_path = path


class ConfigWatchTest(unittest.TestCase):
    """config_watch 的入口：同一份实现，行为照旧（mtime 变了才并进来）。"""

    def _module(self, plugin):
        return load(os.path.join(PLUGINS, plugin, "config_watch.py"))

    def test_all_use_shared_implementation(self):
        modules = [self._module(p) for p in (
            "DeepSeek_Harness_Amo_Image", "DeepSeek_Harness_Amo_Finance",
            "DeepSeek_Harness_Amo_Market", "DeepSeek_Harness_Amo_Medical")]
        for module in modules:
            self.assertEqual(module.SHIM_SOURCE, "shared")
        for module in modules[1:]:
            self.assertIs(module.reload_if_changed, modules[0].reload_if_changed)

    def test_reload_merges_new_values_once(self):
        module = self._module("DeepSeek_Harness_Amo_Finance")
        folder = tempfile.mkdtemp(prefix="amo-cfg-")
        self.addCleanup(shutil.rmtree, folder, True)
        path = os.path.join(folder, "x_config.json")
        with io.open(path, "w", encoding="utf-8") as handle:
            handle.write(u'{"a": 1, "b": "x"}')
        config = FakeConfig(path, a=0, b="")
        module.reset()
        self.assertTrue(module.reload_if_changed(config))
        self.assertEqual(config["a"], 1)
        self.assertEqual(config["b"], "x")
        # mtime 没变：第二次不再并、也不重复报「已更新」
        self.assertFalse(module.reload_if_changed(config))

    def test_missing_config_path_is_noop(self):
        module = self._module("DeepSeek_Harness_Amo_Medical")
        self.assertFalse(module.reload_if_changed({}))
        self.assertFalse(module.reload_if_changed(None))


class ConfigWatchFallbackTest(unittest.TestCase):
    def test_missing_terminal_falls_back(self):
        root = tempfile.mkdtemp(prefix="amo-cfg-fb-")
        self.addCleanup(shutil.rmtree, root, True)
        plugin = os.path.join(root, "DeepSeek_Harness_Amo_Image")
        os.makedirs(plugin)
        shutil.copy2(os.path.join(PLUGINS, "DeepSeek_Harness_Amo_Image", "config_watch.py"),
                     os.path.join(plugin, "config_watch.py"))
        module = load(os.path.join(plugin, "config_watch.py"))
        self.assertEqual(module.SHIM_SOURCE, "fallback")
        self.assertFalse(module.reload_if_changed(FakeConfig("/nonexistent")))
        self.assertIsNone(module.reset())


class FakeSavedConfig(dict):
    """模拟带 save_config 的配置对象。"""

    def __init__(self, path, **values):
        super().__init__(**values)
        self.config_path = path
        self.saves = 0

    def save_config(self):
        self.saves += 1
        return True


class ConfigGuardTest(unittest.TestCase):
    """config_guard：同一份实现 + 配置自愈行为不变。"""

    PLUGINS_WITH_GUARD = ("DeepSeek_Harness_Amo_Terminal", "DeepSeek_Harness_Amo_Image",
                          "DeepSeek_Harness_Amo_Finance", "DeepSeek_Harness_Amo_Market",
                          "DeepSeek_Harness_Amo_Medical")

    def _module(self, plugin):
        return load(os.path.join(PLUGINS, plugin, "config_guard.py"))

    def test_all_use_shared_implementation(self):
        modules = [self._module(p) for p in self.PLUGINS_WITH_GUARD]
        for module in modules:
            self.assertEqual(module.SHIM_SOURCE, "shared")
        for module in modules[1:]:
            self.assertIs(module.heal, modules[0].heal)
            self.assertIs(module.fallback_data_dir, modules[0].fallback_data_dir)

    def test_fallback_data_dir_matches_layout(self):
        module = self._module("DeepSeek_Harness_Amo_Market")
        root = tempfile.mkdtemp(prefix="amo-guard-")
        self.addCleanup(shutil.rmtree, root, True)
        plugins_root = os.path.join(root, "plugins")
        plugin_dir = os.path.join(plugins_root, "DeepSeek_Harness_Amo_Market")
        os.makedirs(plugin_dir)
        expected = os.path.join(root, "plugin_data", "DeepSeek_Harness_Amo_Market")
        self.assertEqual(module.fallback_data_dir(plugin_dir, "DeepSeek_Harness_Amo_Market"),
                         expected)

    def test_heal_restores_from_snapshot(self):
        module = self._module("DeepSeek_Harness_Amo_Finance")
        root = tempfile.mkdtemp(prefix="amo-heal-")
        self.addCleanup(shutil.rmtree, root, True)
        plugin_dir = os.path.join(root, "plugins", "X")
        data_dir = os.path.join(root, "plugin_data", "X")
        config_dir = os.path.join(root, "config")
        for folder in (plugin_dir, data_dir, config_dir):
            os.makedirs(folder)
        with io.open(os.path.join(plugin_dir, "_conf_schema.json"), "w", encoding="utf-8") as fh:
            fh.write(u'{"greeting": {}, "api_key": {}}')
        cfg_path = os.path.join(config_dir, "X_config.json")
        with io.open(cfg_path, "w", encoding="utf-8") as fh:
            fh.write(u'{"greeting": "hi", "api_key": "k1"}')

        first = FakeSavedConfig(cfg_path, greeting="hi", api_key="k1")
        report = module.heal(first, plugin_name="X", plugin_dir=plugin_dir, data_dir=data_dir)
        self.assertTrue(report["snapshot_written"])

        second = FakeSavedConfig(cfg_path, greeting="", api_key="")
        report2 = module.heal(second, plugin_name="X", plugin_dir=plugin_dir, data_dir=data_dir)
        self.assertEqual(second["api_key"], "k1")
        self.assertIn("api_key", report2["from_snapshot"])
        self.assertEqual(second.saves, 1)

    def test_bare_dict_config_is_noop(self):
        module = self._module("DeepSeek_Harness_Amo_Medical")
        report = module.heal({"a": ""}, plugin_name="X", plugin_dir="/tmp", data_dir="/tmp")
        self.assertEqual(report["restored"], [])
        self.assertFalse(report["snapshot_written"])


class ConfigGuardFallbackTest(unittest.TestCase):
    def test_missing_terminal_falls_back(self):
        root = tempfile.mkdtemp(prefix="amo-guard-fb-")
        self.addCleanup(shutil.rmtree, root, True)
        plugin = os.path.join(root, "DeepSeek_Harness_Amo_Finance")
        os.makedirs(plugin)
        shutil.copy2(os.path.join(PLUGINS, "DeepSeek_Harness_Amo_Finance", "config_guard.py"),
                     os.path.join(plugin, "config_guard.py"))
        module = load(os.path.join(plugin, "config_guard.py"))
        self.assertEqual(module.SHIM_SOURCE, "fallback")
        report = module.heal({}, plugin_name="X", plugin_dir="/tmp", data_dir="/tmp")
        self.assertEqual(report["restored"], [])
        # 降级时仍然算得出数据目录，插件不会因为没有公共实现而拿错路径
        self.assertTrue(module.fallback_data_dir("/a/plugins/X", "X").endswith("plugin_data/X"))
        # 认不出实现时按敏感处理，宁可不回填
        self.assertTrue(module.is_sensitive_key("api_key"))


class LinkTest(unittest.TestCase):
    """link：同一份实现 + 面板字段不变（终端不在时如实说没连上）。"""

    PANEL_KEYS = ("terminal_connected", "terminal_name", "terminal_version",
                  "data_connected", "bot_id", "last_heartbeat", "error")

    def _module(self, plugin, *extra):
        return load(os.path.join(PLUGINS, plugin, *extra, "link.py"))

    def test_all_use_shared_implementation(self):
        modules = [self._module("DeepSeek_Harness_Amo_Image"),
                   self._module("DeepSeek_Harness_Amo_Image", "sp"),
                   self._module("DeepSeek_Harness_Amo_Finance"),
                   self._module("DeepSeek_Harness_Amo_Market"),
                   self._module("DeepSeek_Harness_Amo_Medical"),
                   self._module("DeepSeek_Harness_Amo_Terminal", "mem")]
        for module in modules:
            self.assertEqual(module.SHIM_SOURCE, "shared")
        for module in modules[1:]:
            self.assertIs(module.probe, modules[0].probe)
            self.assertIs(module._find, modules[0]._find)

    def test_probe_without_context_reports_disconnected(self):
        module = self._module("DeepSeek_Harness_Amo_Market")

        class Bare:
            pass

        payload = module.probe(Bare())
        for key in self.PANEL_KEYS:
            self.assertIn(key, payload)
        self.assertFalse(payload["terminal_connected"])
        self.assertFalse(payload["data_connected"])
        self.assertTrue(payload["error"])
        self.assertIn("终端", module.summary(payload))

    def test_helpers_degrade_quietly(self):
        module = self._module("DeepSeek_Harness_Amo_Medical")
        self.assertIsNone(module._find(None, ("x",), ("y",)))
        self.assertEqual(module.version_of(None), "")
        self.assertEqual(module.bot_id_of(None, None), module.DEFAULT_BOT_ID)

    def test_market_import_style_still_works(self):
        """Market 是 `from .link import _find, TERMINAL_NAMES, TERMINAL_MARKERS`。"""
        module = self._module("DeepSeek_Harness_Amo_Market")
        for name in ("_find", "TERMINAL_NAMES", "TERMINAL_MARKERS", "probe", "summary"):
            self.assertTrue(hasattr(module, name), name)
            self.assertIn(name, module.__all__)


class LinkFallbackTest(unittest.TestCase):
    def test_missing_terminal_falls_back(self):
        root = tempfile.mkdtemp(prefix="amo-link-fb-")
        self.addCleanup(shutil.rmtree, root, True)
        plugin = os.path.join(root, "DeepSeek_Harness_Amo_Image")
        os.makedirs(plugin)
        shutil.copy2(os.path.join(PLUGINS, "DeepSeek_Harness_Amo_Image", "link.py"),
                     os.path.join(plugin, "link.py"))
        module = load(os.path.join(plugin, "link.py"))
        self.assertEqual(module.SHIM_SOURCE, "fallback")
        payload = module.probe(object())
        self.assertFalse(payload["terminal_connected"])
        self.assertIn("公共实现不可用", payload["error"])
        self.assertIsNone(module._find(None, (), ()))
        self.assertEqual(module.bot_id_of(None, None), "陪伴")
        self.assertIn("终端未连接", module.summary(payload))


if __name__ == "__main__":
    unittest.main(verbosity=2)
