# -*- coding: utf-8 -*-
"""模型结构化输出的校验（规范 5.6）。

模型给的 JSON 只是**候选**：字段齐不齐、类型对不对、长度有没有超，都要本地判。
不合格就丢，绝不把没校验的东西写进记忆或世界观。
"""

from __future__ import annotations

#: 支持的期望类型
_TYPES = {
    "str": str,
    "int": int,
    "float": (int, float),
    "list": list,
    "dict": dict,
    "bool": bool,
}


def validate(data, spec: dict) -> tuple:
    """按 spec 校验；返回 (是否合格, 问题列表)。

    spec 形如 {"city": "str", "hobbies": "list", "age": "int"}；
    值写 `"str?"` 表示可选（缺了不算错，但给了就必须是 str）。
    """
    problems = []
    if not isinstance(data, dict):
        return False, ["不是 JSON 对象"]
    for key, want in (spec or {}).items():
        optional = str(want).endswith("?")
        kind = str(want).rstrip("?")
        if key not in data or data.get(key) in (None, ""):
            if not optional:
                problems.append("缺字段 %s" % key)
            continue
        expected = _TYPES.get(kind)
        if expected is None:
            continue
        if kind in ("int", "float") and isinstance(data.get(key), bool):
            problems.append("%s 应是数字，给了布尔" % key)
            continue
        if not isinstance(data.get(key), expected):
            problems.append("%s 应为 %s，实际 %s" % (key, kind, type(data.get(key)).__name__))
    return (not problems), problems


def clean(data, spec: dict, max_len: int = 2000) -> dict:
    """把合格的部分留下来，超长截断；不合格的字段直接丢掉（不猜内容）。"""
    out = {}
    if not isinstance(data, dict):
        return out
    for key, want in (spec or {}).items():
        kind = str(want).rstrip("?")
        value = data.get(key)
        if value in (None, ""):
            continue
        expected = _TYPES.get(kind)
        if expected is not None and not isinstance(value, expected):
            continue
        if isinstance(value, str):
            value = value.strip()[:max_len]
        elif isinstance(value, list):
            value = [str(item)[:40] for item in value[:8]]
        out[key] = value
    return out


__all__ = ["validate", "clean"]
