# -*- coding: utf-8 -*-
"""口癖/开场重复的本地检查（规范第八节）。

只做**本地、最小修改**：不调模型、不改事实、不改立场、不改情绪强度。

规矩（来自规范）：

1. 「哼」不是默认开场白；
2. 最近一轮以「哼」开头，下一轮不许再以「哼」开头；
3. 最近五轮同一语气词频繁出现，降低它的优先级；
4. 允许直接正常说话；**不许为了换掉「哼」就机械换成「切」**；
5. 只允许最小修改——删掉多余的开场词，别改写句子。
"""

from __future__ import annotations

import re

#: 会被当成「开场语气词」的前缀（长的在前，避免「我才不」被「我」吃掉）。
OPENERS = ("我才不", "凭什么", "哼", "切", "呵", "哟", "咦")

#: 记住最近几轮的开场白。
RECENT = 8

#: 开场词后面跟的标点，一起删掉，免得留下孤零零的逗号。
_TRAIL_PUNCT = "，,、。！!？?…~～ \t"

#: 动作括号 / 星号旁白 / 波浪号（规范：不写动作旁白、不堆波浪号）。
_ACTION_RE = re.compile(r"[（(][^）)]{0,20}(?:笑|叹气|皱眉|点头|摇头|挑眉|伸|抱|摸|看|坐|站)[^）)]{0,20}[）)]")
_STAR_RE = re.compile(r"[*＊][^*＊]{1,40}[*＊]")


def opener_of(text: str) -> str:
    """取这句话的开场语气词；没有就返回空串。"""
    value = str(text or "").strip()
    for word in OPENERS:
        if value.startswith(word):
            return word
    return ""


def _strip_opener(text: str, opener: str) -> str:
    value = str(text or "").lstrip()
    if opener and value.startswith(opener):
        value = value[len(opener):].lstrip(_TRAIL_PUNCT)
    return value or str(text or "")


def diagnose(text: str) -> list:
    """不做修改，只报告问题类别（写日志用）。"""
    issues = []
    if _ACTION_RE.search(str(text or "")):
        issues.append("动作括号")
    if _STAR_RE.search(str(text or "")):
        issues.append("星号旁白")
    if str(text or "").count("~") + str(text or "").count("～") >= 2:
        issues.append("波浪号过多")
    return issues


class OpeningGuard:
    """按会话记住最近几轮的开场白，重复就删掉这一次的开场词。"""

    def __init__(self, recent: int = RECENT):
        self.recent = recent
        self._history = {}   # umo -> [opener, ...]

    def history(self, umo):
        return list(self._history.get(umo or "", ()))

    def check(self, umo: str, text: str) -> tuple:
        """返回 (改后的文本, 说明)。说明为空表示没动。"""
        key = umo or ""
        history = self._history.setdefault(key, [])
        opener = opener_of(text)
        note = ""
        result = text
        # 规则 2/3：最近两轮用过同一个开场词，这一轮去掉，但**不换成别的语气词**
        if opener and opener in history[-2:]:
            stripped = _strip_opener(text, opener)
            if stripped and stripped != str(text or "").strip():
                result = stripped
                note = "开场重复（%s）已去掉" % opener
        if opener:
            history.append(opener)
        else:
            history.append("")
        del history[:-self.recent]
        return result, note

    def reset(self, umo: str = ""):
        if umo:
            self._history.pop(umo, None)
        else:
            self._history.clear()


__all__ = ["OPENERS", "RECENT", "opener_of", "diagnose", "OpeningGuard"]
