# -*- coding: utf-8 -*-
"""正文清洗：把模型当正文吐出来的控制标签去掉。

从 main.py 抽出来的（19,225 行那种大文件，先把这种纯函数、零依赖的块搬走）。

处理的几类脏东西：

- `<astrbot_execute_python>…` 这类框架标签（整块剥掉）
- `<astrbot_speak>` / `<text>` 之类的包裹标签
- `<thought>` / `<thinking>`：模型把思考标签当正文发出去（48 小时漏了 50 次）
- `<｜｜DSML｜｜ calls>` / `<｜｜DSML｜｜ invoke …>` / `</｜｜DSML｜｜ parameter>`：
  工具调用的特殊标记（DeepSeek 系的），开标签、闭标签、带参数的都要剥掉
- 代码围栏

2026-11-16 群里爆过一整段 `<｜｜DSML｜｜ invoke name="amo_speak">`：
原来只删了「不带斜杠的开标签」，`</｜｜DSML｜｜ parameter>` 这种闭标签和裸参数
留了下来，发出去就是一串代码。

但**不能整块删**：那种块里 `parameter name="text"` 夹着的往往正是她想说的话，
整块删掉她这句就没了（第一次改就踩到这个）。顺序是：

1. 先把 `parameter name="text"` 里的正文抽出来（``salvage_text``）；
2. 再按「整块 → 所有标签 → 裸碎片」把标记剥干净；
3. 剥完如果只剩空白，才拿第 1 步抽出来的那句顶上。
"""

from __future__ import annotations

import re

#: 一堆同义词，模型写工具调用时 arg 名不一定叫 text。
_TEXT_ARG_RE = re.compile(
    r"<[｜|]{2}\s*DSML\s*[｜|]{2}\s*parameter\b[^>]*\bname\s*=\s*[\"']"
    r"(?:text|content|message|reply|say|sentence)[\"'][^>]*>(.*?)"
    r"</[｜|]{2}\s*DSML\s*[｜|]{2}\s*parameter\s*>",
    re.S | re.I)

_PSEUDO_BLOCK_RE = re.compile(r"<astrbot_execute_python>.*?</astrbot_execute_python>", re.S | re.I)
_PSEUDO_TAG_RE = re.compile(r"</?(?:astrbot|amo)_[a-z_]+[^>]*>|</?text\b[^>]*>", re.I)
_THOUGHT_BLOCK_RE = re.compile(
    r"<(thought|thinking|reasoning|analysis)\b[^>]*>.*?</\1>", re.S | re.I)
_THOUGHT_TAG_RE = re.compile(r"</?(?:thought|thinking|reasoning|analysis)\b[^>]*>", re.I)
_CODE_FENCE_RE = re.compile(r"```.*?```", re.S)

#: 整块：从 `<｜｜DSML｜｜ calls>` / `<｜｜DSML｜｜ invoke …>` 吃到最后一个闭标签。
#: 只在抽完正文之后用，用来把剩下的壳和参数一起清掉。
_DSML_BLOCK_RE = re.compile(
    r"<[｜|]{2}\s*DSML\s*[｜|]{2}\s*(?:calls?|invoke|tool|function)\b[^>]*>.*"
    r"(?:</[｜|]{2}\s*DSML\s*[｜|]{2}\s*(?:parameter|invoke|function|calls?)\s*>"
    r"|<[｜|]{2}\s*DSML\s*[｜|]{2}\s*calls?\s*>)",
    re.S | re.I)
#: 单个标签：开标签、闭标签、带不带参数都算。
_DSML_TAG_RE = re.compile(r"</?[｜|]{2}\s*DSML\s*[｜|]{2}[^<>]{0,200}>", re.I)
#: 残留的裸标记（没包在尖括号里、或标签被截断了一半）。
_DSML_BARE_RE = re.compile(r"</?[｜|]{2}\s*DSML\s*[｜|]{2}[^<>\n]{0,40}", re.I)
#: 别的框架也会漏：`<|tool_call|>`、`<|endoftext|>` 这种竖线包起来的东西。
_BARE_PIPE_TAG_RE = re.compile(r"<\|[^<>|\n]{1,40}\|>")


def has_tool_markup(text) -> bool:
    """这段话里有没有工具调用标记（只判断不修改）。"""
    body = str(text or "")
    if not body:
        return False
    return bool(_DSML_TAG_RE.search(body) or _DSML_BARE_RE.search(body)
                or _BARE_PIPE_TAG_RE.search(body))


def salvage_text(text) -> str:
    """从工具调用块里把「她本来想说的那句」捞出来。"""
    body = str(text or "")
    if not body:
        return ""
    parts = []
    for match in _TEXT_ARG_RE.finditer(body):
        piece = strip_tool_markup(match.group(1)).strip()
        if piece:
            parts.append(piece)
    return "\n".join(parts)


def strip_tool_markup(text) -> str:
    """只剥工具调用标记（DSML 家族），不碰正文里的普通尖括号。"""
    body = str(text or "")
    if not body:
        return ""
    body = _DSML_BLOCK_RE.sub("", body)
    body = _DSML_TAG_RE.sub("", body)
    body = _DSML_BARE_RE.sub("", body)
    body = _BARE_PIPE_TAG_RE.sub("", body)
    return body


def strip_pseudo_tags(text):
    """把框架控制标签从正文里剥掉；剥空了就用工具调用里那句正文顶上。

    模型偶尔把 `<astrbot_execute_python>` 这类标签当正文输出，直接发出去就是
    「群里爆代码」。整块剥干净，代码围栏也一起删。
    """
    raw = str(text or "")
    saved = salvage_text(raw)
    body = strip_tool_markup(raw)
    body = _THOUGHT_BLOCK_RE.sub("", body)
    body = _THOUGHT_TAG_RE.sub("", body)
    body = _PSEUDO_BLOCK_RE.sub("", body)
    body = _PSEUDO_TAG_RE.sub("", body)
    body = _CODE_FENCE_RE.sub("", body)
    body = body.strip()
    if body:
        return body
    return saved
