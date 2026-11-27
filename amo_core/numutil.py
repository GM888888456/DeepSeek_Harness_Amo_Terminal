# -*- coding: utf-8 -*-
"""三个纯数值工具：`clamp` / `to_int` / `to_float`。

原来长在 `amo_core/util.py` 里，但 util 会顺着 deps 把 astrbot 拖进来——一个纯算术函数
不该依赖框架，否则连单元测试都要先造假 astrbot 包。2026-11-28 搬到这里：

- 函数体逐行照抄，行为不变；
- `amo_core/util.py` 改成从这里 re-export，老的 `from ...util import to_int` 照旧可用
  （`schedule_engine.py` 里那份自己的 clamp 以后也可以换成这里实现，本次不动它）。
"""

from __future__ import annotations

__all__ = ["clamp", "to_int", "to_float"]


def clamp(value, low=0.0, high=100.0):
    try:
        value = float(value)
    except Exception:
        return float(low)
    return max(float(low), min(float(high), value))

def to_int(value, default=0):
    try:
        return int(float(value))
    except Exception:
        return default

def to_float(value, default=0.0):
    try:
        return float(value)
    except Exception:
        return default
