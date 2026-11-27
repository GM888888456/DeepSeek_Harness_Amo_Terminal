#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成五个插件里的公共模块加载入口（chain / config_guard / config_watch / link）。

用法：

    python3 gen_shims.py            # 列出可生成的模块
    python3 gen_shims.py chain      # 生成 chain 那一组
    python3 gen_shims.py all        # 全部
    python3 gen_shims.py check      # 只检查现有入口与模板是否一致（不改文件）

规则：

- 每个入口文件自包含（loader + 降级实现），不依赖 sys.path、不依赖包模式，
  所以 `from .chain import Chain` 和 `import chain` 两种加载方式都照旧可用；
- 覆盖前把旧文件备份成 `<file>.bak.shim.<时间戳>`（各仓库 .gitignore 已忽略 *.bak.*）；
- `check` 报出「和模板不一致」的入口文件，用来发现手改过的副本。
"""

from __future__ import annotations

import io
import os
import sys
import time

PLUGINS_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

TEMPLATE = '''# -*- coding: utf-8 -*-
@@DOC@@

from __future__ import annotations

import importlib.util as _ilu
import logging as _logging
import os as _os
import sys as _sys
import time as _time

_LOG = _logging.getLogger(__name__)

#: 期望的公共实现版本：低于这个数就当「过旧」，降级
NEED = @@NEED@@
#: 加载成功后必须存在的名字（公共实现缺了任何一个也降级）
PUBLIC = @@PUBLIC@@
#: sys.modules 里的唯一名字，避免和别处同名模块打架
_SHARED_NAME = "@@SHARED_NAME@@"
#: 终端插件的目录名（改名、多版本都认）
_TERMINAL_DIRS = (
    "DeepSeek_Harness_Amo_Terminal", "deepseek_harness_amo_terminal",
    "Astrbot_Amo_forever", "astrbot_plugin_amo_forever", "amo_forever",
)


def _terminal_dir():
    """找终端插件目录：从本文件往上跳，看哪一级的同级目录里有 amo_shared/ 标记。"""
    here = _os.path.dirname(_os.path.abspath(__file__))
    current = here
    for _ in range(4):
        parent = _os.path.dirname(current)
        if not parent or parent == current:
            break
        current = parent
        for name in _TERMINAL_DIRS:
            candidate = _os.path.join(current, name)
            if _os.path.isdir(_os.path.join(candidate, "amo_shared")):
                return candidate
    try:
        for entry in sorted(_os.listdir(current)):
            candidate = _os.path.join(current, entry)
            if _os.path.isdir(_os.path.join(candidate, "amo_shared")):
                return candidate
    except OSError:
        pass
    return None


def _load_shared():
    """按路径加载公共实现，返回 (模块, 失败原因)。任何异常都收敛成失败原因。"""
    root = _terminal_dir()
    if not root:
        return None, "没找到终端插件目录"
    path = _os.path.join(root, "amo_shared", "@@FILE@@")
    if not _os.path.isfile(path):
        return None, "公共实现文件不存在：" + path
    try:
        mtime = _os.path.getmtime(path)
    except OSError:
        mtime = 0
    cached = _sys.modules.get(_SHARED_NAME)
    if cached is not None and getattr(cached, "_SHIM_MTIME", None) == mtime:
        return cached, ""
    if cached is not None:  # 公共实现被改过（或插件热重载）：丢掉旧的重新读
        _sys.modules.pop(_SHARED_NAME, None)
    spec = _ilu.spec_from_file_location(_SHARED_NAME, path)
    if spec is None or spec.loader is None:
        return None, "无法为公共实现建立加载器"
    module = _ilu.module_from_spec(spec)
    _sys.modules[_SHARED_NAME] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # 公共实现自己炸了：降级，不带崩插件
        _sys.modules.pop(_SHARED_NAME, None)
        return None, "公共实现加载失败：%s: %s" % (type(exc).__name__, exc)
    module._SHIM_MTIME = mtime
    return module, ""


def _publish(shared):
    """转发公共实现的公开接口；下划线名字只转发 PUBLIC 里点名的那些。"""
    names = []
    for name in dir(shared):
        if name.startswith("__"):
            continue
        if name.startswith("_") and name not in PUBLIC:
            continue
        value = getattr(shared, name)
        if isinstance(value, type(_os)):  # 别把实现里的 os/json 之类转发出去
            continue
        globals()[name] = value
        names.append(name)
    globals()["SHIM_SOURCE"] = "shared"
    globals()["__all__"] = sorted(set(names) | set(PUBLIC))


_SHARED, _WHY = _load_shared()
if _SHARED is not None:
    _version = getattr(_SHARED, "SHIM_VERSION", 0)
    _missing = [name for name in PUBLIC if not hasattr(_SHARED, name)]
    if _version < NEED:
        _SHARED = None
        _WHY = "公共实现过旧（%s < %s）" % (_version, NEED)
    elif _missing:
        _SHARED = None
        _WHY = "公共实现缺接口：%s" % ",".join(_missing)

if _SHARED is not None:
    _publish(_SHARED)
else:
    _LOG.warning("[%s] 公共实现不可用，降级为本地最小实现：%s",
                 _os.path.basename(__file__), _WHY)
    SHIM_SOURCE = "fallback"
@@FALLBACK@@
@@ADAPT@@
'''

DOC_TEMPLATE = '''"""@@FILE@@ —— 加载入口，不是实现。

真正的实现只有一份：`<终端插件>/amo_shared/@@FILE@@`。

- 加载成功：本模块就是公共实现的转发，`from .@@MODULE@@ import ...` / `import @@MODULE@@` 照旧可用；
- 加载不到 / 版本过旧 / 缺接口：降级成文件末尾的最小实现，导入不抛异常，
  插件照常启动，只是这条能力退化，日志里有一条 warning 说明原因；
- 本文件由 `amo_shared/gen_shims.py` 生成，手改会被下次生成覆盖。改行为请改公共实现。
"""'''

# ---------------------------------------------------------------- 各模块的降级实现
# 只在「公共实现拿不到」时生效：接口对齐原有实现，行为明确退化（不静默假装成功），
# 目的只有一个——终端插件被删/搬走/降级时，其余插件照样能启动、面板照样说清楚状态。

CHAIN_FALLBACK = r'''
    def _fmt(value, limit=120):
        text = "" if value is None else str(value)
        text = text.replace("\n", " ")
        return text if len(text) <= limit else text[: max(0, limit - 1)] + "…"

    class Chain:  # 最小实现：接口一致，但不写 [chain] 日志
        def __init__(self, name, trace_id="", logger=None, event_id="",
                     ok_level="info", **fields):
            self.name = str(name or "task")
            self.trace = str(trace_id or event_id or "") or "%s#%d" % (self.name, 0)
            self.steps = []
            self.fields = dict(fields)
            self._ok_level = str(ok_level or "info").lower()

        def step(self, stage, ok=True, detail="", **fields):
            self.steps.append({"stage": stage, "ok": bool(ok),
                               "detail": _fmt(detail), "elapsed_ms": 0})
            return self

        def done(self, **fields):
            return self.step("done", **fields)

        def fail(self, stage, reason="", **fields):
            return self.step(stage, ok=False, detail=reason, **fields)

        @property
        def ok(self):
            return all(item["ok"] for item in self.steps)

        def summary(self):
            return " → ".join(
                "%s%s" % (item["stage"], "" if item["ok"] else "(FAIL:%s)" % item["detail"])
                for item in self.steps
            )

    __all__ = ["Chain"]
'''

CONFIG_WATCH_FALLBACK = r'''
    def reload_if_changed(config, logger=None):
        return False

    def reset():
        return None

    __all__ = ["reload_if_changed", "reset"]
'''

# 记忆层原来把成功步骤打成 debug（嫌 info 太吵），降级时保持同一口径
MEM_CHAIN_ADAPT = r'''
# 记忆层沿用原来的静默级别：成功步骤打 debug，不刷 info
class Chain(Chain):  # noqa: F811 —— 覆盖上面转发来的 Chain
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("ok_level", "debug")
        super().__init__(*args, **kwargs)
'''

MODULES = {
    "chain": {
        "file": "chain.py",
        "module": "chain",
        "need": 1,
        "public": ("Chain",),
        "shared_name": "amo_shared_chain",
        "fallback": CHAIN_FALLBACK,
        "targets": [
            ("DeepSeek_Harness_Amo_Terminal", "chain.py", ""),
            ("DeepSeek_Harness_Amo_Image", "chain.py", ""),
            ("DeepSeek_Harness_Amo_Image", "sp/sp_chain.py", ""),
            ("DeepSeek_Harness_Amo_Finance", "chain.py", ""),
            ("DeepSeek_Harness_Amo_Market", "chain.py", ""),
            ("DeepSeek_Harness_Amo_Medical", "chain.py", ""),
            ("DeepSeek_Harness_Amo_Terminal", "mem/mem_chain.py", MEM_CHAIN_ADAPT),
        ],
    },
    "config_watch": {
        "file": "config_watch.py",
        "module": "config_watch",
        "need": 1,
        "public": ("reload_if_changed", "reset"),
        "shared_name": "amo_shared_config_watch",
        "fallback": CONFIG_WATCH_FALLBACK,
        "targets": [
            ("DeepSeek_Harness_Amo_Image", "config_watch.py", ""),
            ("DeepSeek_Harness_Amo_Image", "sp/sp_config_watch.py", ""),
            ("DeepSeek_Harness_Amo_Finance", "config_watch.py", ""),
            ("DeepSeek_Harness_Amo_Market", "config_watch.py", ""),
            ("DeepSeek_Harness_Amo_Medical", "config_watch.py", ""),
            ("DeepSeek_Harness_Amo_Terminal", "mem/mem_config_watch.py", ""),
        ],
    },
}

CONFIG_GUARD_FALLBACK = r'''
    SNAPSHOT_NAME = "config_snapshot.json"
    EMPTY_VALUES = (None, "")
    SENSITIVE_KEY_HINTS = ("key", "token", "secret", "password", "passwd", "cookie",
                           "auth", "credential", "webhook", "proxy", "api_base",
                           "base_url", "endpoint")

    def snapshot_path(data_dir):
        return _os.path.join(str(data_dir or ""), SNAPSHOT_NAME)

    def load_snapshot(data_dir):
        return {}

    def save_snapshot(data_dir, values):
        return False

    def schema_keys(plugin_dir):
        return []

    def config_stem(name):
        return ""

    def is_sensitive_key(key):
        # 认不出实现时按「敏感」处理：宁可少回填，也不能把凭据搬错地方
        return True

    def orphan_values(config_path, keys, own_name="", legacy_names=()):
        return {}

    def heal(config, **kwargs):
        return {"restored": [], "from_snapshot": [], "from_orphan": [],
                "snapshot_written": False, "keys": 0}

    def remember(config, **kwargs):
        return False

    def fallback_data_dir(plugin_dir="", plugin_name=""):
        """算插件数据目录：<AstrBot 数据目录>/plugin_data/<插件名>（上跳两级）。"""
        path = _os.path.abspath(str(plugin_dir or ""))
        plugins_root = _os.path.dirname(path)
        data_root = _os.path.dirname(plugins_root)
        target = _os.path.join(data_root, "plugin_data", str(plugin_name or ""))
        if _os.path.isdir(target):
            return target
        legacy = _os.path.join(plugins_root, "plugin_data", str(plugin_name or ""))
        if _os.path.isdir(legacy):
            return legacy
        return target

    __all__ = ["SNAPSHOT_NAME", "EMPTY_VALUES", "SENSITIVE_KEY_HINTS", "snapshot_path",
               "load_snapshot", "save_snapshot", "schema_keys", "config_stem",
               "is_sensitive_key", "orphan_values", "heal", "remember", "fallback_data_dir"]
'''

LINK_FALLBACK = r'''
    TERMINAL_NAME = "DeepSeek_Harness_Amo_Terminal"
    DATA_NAME = "DeepSeek_Harness_Amo_Memory"
    TERMINAL_NAMES = ("DeepSeek_Harness_Amo_Terminal", "deepseek_harness_amo_terminal",
                      "Astrbot_Amo_forever", "astrbot_plugin_amo_forever", "amo_forever")
    DATA_NAMES = ("DeepSeek_Harness_Amo_Memory", "deepseek_harness_amo_memory",
                  "Astr_Amo_data", "astrbot_plugin_amo_data", "Astr_Amo_data_plugin")
    TERMINAL_MARKERS = ("amo_terminal", "amo_forever")
    DATA_MARKERS = ("amo_memory", "amo_data", "astr_amo_data")
    DEFAULT_BOT_ID = "陪伴"

    def _instance(meta, require_mem=False):
        return None

    def _find(context, names, markers, require_mem=False):
        return None

    def version_of(plugin):
        return ""

    def bot_id_of(terminal, data):
        return DEFAULT_BOT_ID

    def probe(plugin):
        # 公共实现都拿不到，就不可能有「已连接」：面板如实说没连上
        return {
            "terminal_connected": False, "terminal_name": TERMINAL_NAME, "terminal_version": "",
            "data_connected": False, "data_name": DATA_NAME, "data_version": "",
            "bot_id": DEFAULT_BOT_ID, "last_heartbeat": -1, "checked_at": int(_time.time()),
            "error": "公共实现不可用（终端插件的 amo_shared/link.py 没加载到）",
        }

    def summary(payload):
        if payload.get("terminal_connected"):
            text = "终端 %s 已连接" % (payload.get("terminal_version") or "?")
        else:
            text = "终端未连接"
        if payload.get("data_connected"):
            text += "，记忆库 %s 已连接" % (payload.get("data_version") or "?")
        else:
            text += "，记忆库未连接"
        text += "，bot_id %s" % (payload.get("bot_id") or DEFAULT_BOT_ID)
        if payload.get("error"):
            text += "（%s）" % payload["error"]
        return text

    __all__ = ["TERMINAL_NAME", "DATA_NAME", "TERMINAL_NAMES", "DATA_NAMES",
               "TERMINAL_MARKERS", "DATA_MARKERS", "DEFAULT_BOT_ID", "probe", "summary",
               "version_of", "bot_id_of", "_find", "_instance"]
'''

MODULES.update({
    "config_guard": {
        "file": "config_guard.py",
        "module": "config_guard",
        "need": 1,
        "public": ("heal", "remember", "fallback_data_dir", "snapshot_path", "load_snapshot",
                   "save_snapshot", "schema_keys", "config_stem", "is_sensitive_key",
                   "orphan_values", "SNAPSHOT_NAME", "SENSITIVE_KEY_HINTS", "EMPTY_VALUES"),
        "shared_name": "amo_shared_config_guard",
        "fallback": CONFIG_GUARD_FALLBACK,
        "targets": [
            ("DeepSeek_Harness_Amo_Terminal", "config_guard.py", ""),
            ("DeepSeek_Harness_Amo_Image", "config_guard.py", ""),
            ("DeepSeek_Harness_Amo_Image", "sp/sp_config_guard.py", ""),
            ("DeepSeek_Harness_Amo_Finance", "config_guard.py", ""),
            ("DeepSeek_Harness_Amo_Market", "config_guard.py", ""),
            ("DeepSeek_Harness_Amo_Medical", "config_guard.py", ""),
            ("DeepSeek_Harness_Amo_Terminal", "mem/mem_config_guard.py", ""),
        ],
    },
    "link": {
        "file": "link.py",
        "module": "link",
        "need": 1,
        "public": ("probe", "summary", "version_of", "bot_id_of", "_find", "_instance",
                   "TERMINAL_NAME", "DATA_NAME", "TERMINAL_NAMES", "DATA_NAMES",
                   "TERMINAL_MARKERS", "DATA_MARKERS", "DEFAULT_BOT_ID"),
        "shared_name": "amo_shared_link",
        "fallback": LINK_FALLBACK,
        "targets": [
            ("DeepSeek_Harness_Amo_Image", "link.py", ""),
            ("DeepSeek_Harness_Amo_Image", "sp/sp_link.py", ""),
            ("DeepSeek_Harness_Amo_Finance", "link.py", ""),
            ("DeepSeek_Harness_Amo_Market", "link.py", ""),
            ("DeepSeek_Harness_Amo_Medical", "link.py", ""),
            ("DeepSeek_Harness_Amo_Terminal", "mem/mem_link.py", ""),
        ],
    },
})


def render(name, adapt=""):
    """把模板渲染成入口文件内容；adapt 是追加在文件末尾的补充段（按目标可选）。"""
    spec = MODULES[name]
    doc = (DOC_TEMPLATE
           .replace("@@FILE@@", spec["file"])
           .replace("@@MODULE@@", spec["module"]))
    text = (TEMPLATE
            .replace("@@DOC@@", doc)
            .replace("@@NEED@@", str(spec["need"]))
            .replace("@@PUBLIC@@", repr(tuple(spec["public"])))
            .replace("@@SHARED_NAME@@", spec["shared_name"])
            .replace("@@FILE@@", spec["file"])
            .replace("@@FALLBACK@@", spec["fallback"].strip("\n"))
            .replace("@@ADAPT@@", adapt or ""))
    return text


def _targets(name):
    for plugin, rel, adapt_text in MODULES[name]["targets"]:
        yield plugin, rel, adapt_text, os.path.join(PLUGINS_ROOT, plugin, rel)


def _set_adapt(name, plugin, rel, adapt_text):
    """允许按目标覆盖 adapt 段（例如记忆层的 debug 级别）。"""
    targets = list(MODULES[name]["targets"])
    for index, (p, r, _a) in enumerate(targets):
        if p == plugin and r == rel:
            targets[index] = (p, r, adapt_text)
    MODULES[name]["targets"] = targets
    return render(name, adapt_text)


def main(argv):
    if not argv:
        print("可用模块：%s" % ", ".join(sorted(MODULES)))
        print("用法：gen_shims.py <模块> | all | check")
        return 0
    mode = argv[0]
    if mode == "check":
        names = [n for n in argv[1:] if n in MODULES] or sorted(MODULES)
        bad = 0
        for name in names:
            for plugin, rel, adapt_text, path in _targets(name):
                text = _set_adapt(name, plugin, rel, adapt_text)
                if not os.path.isfile(path):
                    print("缺少入口：%s/%s" % (plugin, rel))
                    bad += 1
                elif io.open(path, encoding="utf-8").read() != text:
                    print("与模板不一致：%s/%s" % (plugin, rel))
                    bad += 1
        print("check 完成：%d 处不一致" % bad)
        return 1 if bad else 0
    names = sorted(MODULES) if mode == "all" else [mode]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    for name in names:
        if name not in MODULES:
            print("没有这个模块：%s" % name)
            return 2
        for plugin, rel, adapt_text, path in _targets(name):
            text = _set_adapt(name, plugin, rel, adapt_text)
            folder = os.path.dirname(path)
            if not os.path.isdir(folder):
                print("跳过（目录不存在）：%s/%s" % (plugin, rel))
                continue
            old = ""
            if os.path.isfile(path):
                old = io.open(path, encoding="utf-8").read()
                if old == text:
                    print("已是最新：%s/%s" % (plugin, rel))
                    continue
                bak = "%s.bak.shim.%s" % (path, stamp)
                with io.open(bak, "w", encoding="utf-8") as fh:
                    fh.write(old)
            with io.open(path, "w", encoding="utf-8") as fh:
                fh.write(text)
            print("已生成：%s/%s%s" % (plugin, rel, "（旧文件已备份）" if old else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
