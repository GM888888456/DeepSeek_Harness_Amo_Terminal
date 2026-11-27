# -*- coding: utf-8 -*-
"""配置同步：AstrBot 原生设置页改完，插件内存里的 config 也立刻跟上。

为什么需要：面板和原生设置页改的是**同一个配置文件**，但插件进程里握着的
是启动时那份 ``config`` 对象。不重新读，就会出现「设置页显示开、面板显示关」
这种两边不同步的怪象。这里按 mtime 判断，变了才重新并进去，开销可以忽略。
**这份是五个插件共用的唯一实现**（2026-11-27 收敛，原来四份一模一样）。
各插件根目录的 `config_watch.py` 只是加载入口，实现改动请改这一份。
"""

from __future__ import annotations

#: 公共实现版本，入口文件用它判断实现是否过旧
SHIM_VERSION = 1

import json
import os

#: (id(config), path) -> 上次同步时的 mtime
_SEEN: dict = {}


def reload_if_changed(config, logger=None) -> bool:
    """配置文件 mtime 变了就把新值并进 config；返回是否真的更新了。"""
    if config is None:
        return False
    path = str(getattr(config, "config_path", "") or "")
    if not path:
        return False
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        return False
    key = (id(config), path)
    if _SEEN.get(key, 0) >= mtime:
        return False
    try:
        with open(path, encoding="utf-8-sig") as handle:
            data = json.load(handle)
    except Exception:
        return False
    if not isinstance(data, dict):
        return False
    changed = False
    try:
        for name, value in data.items():
            if config.get(name) != value:
                config[name] = value
                changed = True
    except Exception:
        return False
    _SEEN[key] = mtime
    if changed and logger is not None:
        try:
            logger.debug("[config] 已把配置文件的新值同步进内存")
        except Exception:
            pass
    return changed


def reset() -> None:
    """测试用：清掉记住的 mtime。"""
    _SEEN.clear()
