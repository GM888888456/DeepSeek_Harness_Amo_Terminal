# -*- coding: utf-8 -*-
"""出口润色：书面腔 → 口语；林黛玉腔 → 贵州姑娘。

用户口径（2026-11-24）：
  「一点都不如贵州女孩豪爽活泼，感觉像林黛玉」
  「多学学正常人怎么说话的」

只做**保守替换**，不改语义、不删信息、幂等；任何异常都返回原文。
"""
import re

# ---------- 1. 书面词 → 口语 ----------
_WORDS = [
    ("是否", "是不是"),
    ("能否", "能不能"),
    ("如何", "怎么"),
    ("何时", "什么时候"),
    ("为何", "为啥"),
    ("因此", "所以"),
    ("因而", "所以"),
    ("然而", "不过"),
    ("并且", "而且"),
    ("以及", "和"),
    ("十分", "挺"),
    ("较为", "有点"),
    ("略微", "有点"),
    ("于是", "然后"),
    ("目前", "现在"),
    ("即刻", "马上"),
    ("或许", "可能"),
    ("大约", "大概"),
    ("极为", "特别"),
    ("即便", "就算"),
    ("即使", "就算"),
    ("尽管", "虽然"),
    ("从而", "这样"),
    ("予以", "给"),
    ("诸多", "好多"),
    ("些许", "一点"),
]

_BOUNDARY = r"(?:(?<=^)|(?<=[，。！？、\s：；]))"
_RULES = [(re.compile(_BOUNDARY + re.escape(old)), new) for old, new in _WORDS]
_SURE = re.compile(_BOUNDARY + r"确实")
_VERY = re.compile(_BOUNDARY + r"非常(?!规|时|手)")

# ---------- 2. 林黛玉腔 → 爽利 ----------
# 只换词，不改句意；这些都是「柔弱/哀怨/文言」的标志词
_LIN = [
    (re.compile(r"我又何曾"), "我哪有"),
    (re.compile(r"何曾"), "哪有"),
    (re.compile(r"终究还是"), "还是"),
    (re.compile(r"终究"), "到底"),
    (re.compile(r"不过如此"), "也就这样"),
    (re.compile(r"有缘无分"), "没缘分"),
    (re.compile(r"命里注定"), "就是命"),
    (re.compile(r"罢了(?=[，。！？\s]|$)"), ""),
    (re.compile(r"又何苦"), "何必"),
    (re.compile(r"岂不是"), "不就"),
    (re.compile(r"莫不是"), "是不是"),
    (re.compile(r"甚是"), "特别"),
    (re.compile(r"方才"), "刚"),
    (re.compile(r"已然"), "已经"),
]


def _dedupe(text: str) -> str:
    return re.sub(r"(而且|所以|不过|然后)\1+", r"\1", text)


def humanize(text: str) -> str:
    """书面腔 / 林黛玉腔 → 口语。幂等、保守、出错返回原文。"""
    raw = str(text or "")
    if not raw.strip():
        return raw
    try:
        out = raw
        for pattern, new in _RULES:
            out = pattern.sub(new, out)
        out = _SURE.sub("还真", out)
        out = _VERY.sub("挺", out)
        for pattern, new in _LIN:
            out = pattern.sub(new, out)
        # 书面连接词后面紧跟逗号时，口语里常不留
        out = re.sub(r"(所以|不过|而且|然后)，", r"\1", out)
        out = _dedupe(out)
        out = re.sub(r"[，]{2,}", "，", out).strip("，")
        return out if out.strip() else raw
    except Exception:
        return raw


__all__ = ["humanize"]
