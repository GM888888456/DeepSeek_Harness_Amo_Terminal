# -*- coding: utf-8 -*-
"""config_watch.py —— 加载入口，不是实现。

真正的实现只有一份：`<终端插件>/amo_shared/config_watch.py`。

- 加载成功：本模块就是公共实现的转发，`from .config_watch import ...` / `import config_watch` 照旧可用；
- 加载不到 / 版本过旧 / 缺接口：降级成文件末尾的最小实现，导入不抛异常，
  插件照常启动，只是这条能力退化，日志里有一条 warning 说明原因；
- 本文件由 `amo_shared/gen_shims.py` 生成，手改会被下次生成覆盖。改行为请改公共实现。
"""

from __future__ import annotations

import importlib.util as _ilu
import logging as _logging
import os as _os
import sys as _sys
import time as _time

_LOG = _logging.getLogger(__name__)

#: 期望的公共实现版本：低于这个数就当「过旧」，降级
NEED = 1
#: 加载成功后必须存在的名字（公共实现缺了任何一个也降级）
PUBLIC = ('reload_if_changed', 'reset')
#: sys.modules 里的唯一名字，避免和别处同名模块打架
_SHARED_NAME = "amo_shared_config_watch"
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
    path = _os.path.join(root, "amo_shared", "config_watch.py")
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
    def reload_if_changed(config, logger=None):
        return False

    def reset():
        return None

    __all__ = ["reload_if_changed", "reset"]

