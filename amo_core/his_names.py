# -*- coding: utf-8 -*-
"""「他」在文字里怎么被称呼 —— 可变表，**不写死任何账号或人名**。

日程和日记里不许出现「他」（那是她一个人的日子）。要判断一句话有没有提到他，
原来是在两个引擎里把「阿墨 / 老公 / 主人」写死的：换号、换恋人、人格改名之后，
「阿墨」这两个字就再也拦不住了，而新恋人叫「哥哥」又拦不住。

现在：通用称呼只有「老公 / 主人 / 他」，具体人名由插件启动时用 `set_names()`
从 profiles 里 `relation=相恋` 的人灌进来——爱人叫什么，就拦什么。

用法：
    from amo_core import his_names
    his_names.set_names(["阿墨", "墨辞烟"])   # 插件启动/认人后调用
    his_names.mentions("阿墨回家了")          # True
    his_names.text_re().sub("", text)        # 删掉称呼
"""
from __future__ import annotations

import re

#: 通用称呼：跟账号无关，永远拦
BASE_NAMES: tuple[str, ...] = ("老公", "主人")

#: 「他」的排除：其他人、其他时候、他们、他乡…
_TAIL = r"(?<![其吉])他(?!们|人|处|时|乡|俩)"

_NAMES: tuple[str, ...] = BASE_NAMES
_RE = re.compile(r"老公|主人|" + _TAIL)


def set_names(names) -> None:
    """把恋人的人名灌进来（单字不认：太容易误伤正常句子）。"""
    global _NAMES, _RE
    extra, clean = [], []
    for name in names or ():
        text = str(name or "").strip()
        if not text:
            continue
        if len(text) >= 2 and text not in BASE_NAMES:
            extra.append(re.escape(text))
            clean.append(text)
    _NAMES = tuple(dict.fromkeys(list(clean) + list(BASE_NAMES)))
    parts = list(dict.fromkeys(extra))
    if parts:
        try:
            _RE = re.compile("|".join(parts) + "|" + _TAIL + "|老公|主人")
            return
        except re.error:
            pass
    _RE = re.compile(r"老公|主人|" + _TAIL)


def names() -> tuple[str, ...]:
    return _NAMES


def text_re():
    return _RE


def mentions(text) -> bool:
    try:
        return bool(_RE.search(str(text or "")))
    except Exception:
        return False


__all__ = ["BASE_NAMES", "set_names", "names", "text_re", "mentions"]
