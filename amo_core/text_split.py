# -*- coding: utf-8 -*-
"""回复文本的切分与比较（原来散在 main.py 顶上，2026-11-28 拆出来）。

这些东西和插件状态无关，全是纯函数：

- 语音伪标签：`_strip_voice_tags` / `split_voice_tag`（模型偶尔直接吐 <astrbot_speak>）
- 句子比较：`_norm_sentence` / `_bigrams` / `_cover_ratio` / `same_sentence`（防复读）
- 分段：`segment_text` 及其掩码/切分工具（标点、括号、引用不能被切坏）
- 打字停顿：`typing_delay_ms`

拆出来的理由：main.py 的类已经 3200 行，这几十个纯函数塞在最前面，改切分规则要在
4000 行文件里翻。行为一个字都没改——回归用 `tests/test_text_split.py` 对着
`tests/golden_text_split.json`（重构前从旧 main.py 现算出来的输出）逐条比对。

注意：`__all__` 里带下划线的名字是给 `from .amo_core.text_split import *` 用的，
main.py 当年就是这么用的（`_strip_voice_tags` 等在模块里被直接引用），别删。
"""

from __future__ import annotations

import difflib
import random
import re

# 这两个是仓库里既有的纯函数，不复制一份：
# - strip_pseudo_tags：剥模型当正文吐出来的控制标签（text_clean.py，纯标准库）
# - to_int：`segment_text` 解析参数用（amo_core/util.py）
try:  # 包内加载（AstrBot 的正常方式）
    from ..text_clean import strip_pseudo_tags
except ImportError:  # 插件根在 sys.path 上时
    from text_clean import strip_pseudo_tags  # type: ignore
try:
    from .numutil import to_int
except ImportError:
    from amo_core.numutil import to_int  # type: ignore

__all__ = [
    "_PAIRS",
    "_STRONG",
    "_TRIM",
    "_VOICE_TAG_OPEN_RE",
    "_VOICE_TAG_RE",
    "_WEAK",
    "_bigrams",
    "_cover_ratio",
    "_cut",
    "_mask_with_placeholders",
    "_norm_sentence",
    "_protect_mask",
    "_protected_ranges",
    "_split_regex",
    "_strip_voice_tags",
    "same_sentence",
    "segment_text",
    "split_voice_tag",
    "typing_delay_ms",
]


_VOICE_TAG_OPEN_RE = re.compile(r"<(?:astrbot_speak|amo_speak)\b([^>]*)>", re.I)


_VOICE_TAG_RE = re.compile(r"</?(?:astrbot_speak|amo_speak)\b[^>]*>", re.I)


def _strip_voice_tags(text: str) -> str:
    """模型偶尔不调 amo_speak 工具，直接输出 <astrbot_speak text="..."> 这种伪标签。
    这里只取要念的那句话，别把标签念出来，也别让整条回复消失。"""
    body = str(text or "")
    m = _VOICE_TAG_OPEN_RE.search(body)
    if m:
        attr = m.group(1) or ""
        am = re.search(r'text\s*=\s*"([^"]*)"', attr) or re.search(r"text\s*=\s*'([^']*)'", attr)
        if am and am.group(1).strip():
            return strip_pseudo_tags(am.group(1).strip())
        tail = body[m.end():]
        close = re.search(r"</(?:astrbot_speak|amo_speak)>", tail, re.I)
        if close:
            return strip_pseudo_tags(tail[: close.start()].strip())
    return strip_pseudo_tags(_VOICE_TAG_RE.sub("", body))


def split_voice_tag(text: str) -> tuple[str, str]:
    """把模型写出来的 ``<astrbot_speak text="…">`` 伪标签拆成两半。

    返回 ``(要念的那句, 标签以外剩下的正文)``；没有标签时返回 ``("", 原文)``。
    模型偶尔不调 amo_speak 工具，直接把标签写进正文——标签绝不能进聊天
    （群里只会显示成一串代码），但整条回复也不能因此消失。
    """
    body = str(text or "")
    if not _VOICE_TAG_OPEN_RE.search(body):
        return "", body
    return _strip_voice_tags(body), strip_pseudo_tags(_VOICE_TAG_RE.sub("", body)).strip()


def _norm_sentence(value) -> str:
    """比较用：去掉标点、空白和表情，只留字。"""
    return re.sub(r"[\W_]+", "", str(value or ""))


def _bigrams(text: str) -> set:
    value = _norm_sentence(text)
    if len(value) < 2:
        return {value} if value else set()
    return {value[index:index + 2] for index in range(len(value) - 1)}


def _cover_ratio(short: str, longer: str) -> float:
    """短句的 bigram 有多少出现在长句里（0~1）。"""
    a, b = _bigrams(short), _bigrams(longer)
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a))


def same_sentence(a, b, threshold=0.8) -> bool:
    """两句是不是同一句。

    2026-11-18 16:00：她调 amo_speak 念了「还在跟同事扯接口…」，四秒后守护
    又把同一句当文字发了一遍，群里就是语音 + 同一条文字。语音插件念过的句子，
    正文不该再发；只做去重判断，不改变任何说话逻辑。
    """
    na, nb = _norm_sentence(a), _norm_sentence(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    # 太短的一句（「好」「嗯」）不做包含/相似判断，免得把真回复误吞
    if len(short) < 8:
        return False
    if short in longer:
        return True
    # 换了个说法的同一句：语音念「小k这名字叫着倒顺口，你俩是早就认识的呀」，
    # 正文写「小k这名字叫着倒挺顺口」—— difflib 只有 0.67，但短句几乎被完全覆盖。
    if len(short) >= 6 and _cover_ratio(short, longer) >= 0.75:
        return True
    try:
        return difflib.SequenceMatcher(None, na, nb).ratio() >= threshold
    except Exception:
        return False


_PAIRS = {
    "《": "》", "〈": "〉", "“": "”", "‘": "’", "「": "」", "『": "』",
    "（": "）", "(": ")", "【": "】", "〔": "〕", "[": "]", "{": "}",
}


# 2026-11-26（用户口径）：破折号也是断句点——「……再给你拍——也就你有这个面子」
# 该切成两条发，而不是憋在一个气泡里。
_STRONG = "。！？!?…\n—–"


_WEAK = "，,、；;：:~～"


_TRIM = " \t\r\n。！？!?…，,、；;：:~～"


def _protect_mask(text):
    length = len(text)
    mask = [False] * length

    def mark(start, end):
        for index in range(max(0, start), min(length, end)):
            mask[index] = True

    for match in re.finditer(r"```.*?```", text, re.S):
        mark(match.start(), match.end())
    for match in re.finditer(r"`[^`\n]+`", text):
        mark(match.start(), match.end())
    for match in re.finditer(r"https?://[^\s]+", text):
        mark(match.start(), match.end())

    index = 0
    while index < length:
        char = text[index]
        closer = _PAIRS.get(char)
        if closer:
            depth = 1
            scan = index + 1
            while scan < length:
                if text[scan] == char:
                    depth += 1
                elif text[scan] == closer:
                    depth -= 1
                    if depth == 0:
                        break
                scan += 1
            if scan < length:
                mark(index, scan + 1)
                index = scan + 1
                continue
            mark(index, length)
            break
        index += 1
    return mask


def _cut(text, mask, delimiters, min_keep=0):
    parts = []
    start = 0
    for index, char in enumerate(text):
        if mask[index]:
            continue
        if char in delimiters and (index + 1 - start) >= min_keep:
            parts.append(text[start:index + 1])
            start = index + 1
    parts.append(text[start:])
    return parts


def _protected_ranges(text):
    mask = _protect_mask(text)
    ranges = []
    start = None
    for index, flag in enumerate(mask):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            ranges.append((start, index))
            start = None
    if start is not None:
        ranges.append((start, len(mask)))
    return ranges


def _mask_with_placeholders(text):
    ranges = _protected_ranges(text)
    if not ranges:
        return text, {}
    pieces = []
    placeholders = {}
    last = 0
    for index, (start, end) in enumerate(ranges):
        pieces.append(text[last:start])
        token = "\x00%d\x00" % index
        placeholders[token] = text[start:end]
        pieces.append(token)
        last = end
    pieces.append(text[last:])
    return "".join(pieces), placeholders


def _split_regex(text, pattern, protect_pairs=True):
    if not pattern:
        return None
    masked, placeholders = _mask_with_placeholders(text) if protect_pairs else (text, {})
    try:
        compiled = re.compile(pattern)
    except re.error:
        return None
    pieces = []
    last = 0
    for match in compiled.finditer(masked):
        end = match.end()
        if end <= last:
            continue
        pieces.append(masked[last:end])
        last = end
    pieces.append(masked[last:])
    restored = []
    for piece in pieces:
        value = piece
        for token, original in placeholders.items():
            value = value.replace(token, original)
        value = value.strip()
        if value:
            restored.append(value)
    return restored


def segment_text(text, keep_punc=True, min_len=6, max_len=42, max_segments=4,
                 mode="punct", split_chars="", regex_pattern="", protect_pairs=True):
    """按标点符号或正则分段；成对符号、代码块、URL 内部不会被切开。

    mode="punct" 时按 segment_split_chars + 内置标点分段；
    mode="regex" 时按 segment_regex 分段，失败自动回退到标点模式。
    """
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    min_len = max(1, to_int(min_len, 6))
    max_len = max(min_len + 1, to_int(max_len, 42))
    max_segments = max(1, to_int(max_segments, 4))

    pieces = None
    if str(mode).lower() == "regex" and regex_pattern:
        pieces = _split_regex(text, regex_pattern, protect_pairs)
    if pieces is None:
        extra = "".join(char for char in str(split_chars or "") if char not in "\r\n")
        strong = "".join(dict.fromkeys(_STRONG + extra))
        mask = _protect_mask(text) if protect_pairs else [False] * len(text)
        pieces = []
        for part in _cut(text, mask, strong):
            part = part.strip()
            if not part:
                continue
            if len(part) > max_len:
                sub_mask = _protect_mask(part) if protect_pairs else [False] * len(part)
                pieces.extend(_cut(part, sub_mask, _WEAK, min_keep=max(4, max_len // 2)))
            else:
                pieces.append(part)

    normalized = []
    for part in pieces or []:
        part = str(part).strip()
        if not part:
            continue
        if len(part) > max_len:
            sub_mask = _protect_mask(part) if protect_pairs else [False] * len(part)
            normalized.extend(_cut(part, sub_mask, _WEAK, min_keep=max(4, max_len // 2)))
        else:
            normalized.append(part)
    pieces = normalized

    segments = []
    for part in pieces:
        seg = part.strip()
        # 破折号当断句点时，气泡首尾不该留着「——」
        seg = seg.strip("—–").strip()
        if not keep_punc:
            seg = seg.strip(_TRIM)
        if seg:
            segments.append(seg)
    if not segments:
        return []

    # 纯标点碎片（「真的？！」里被切出来的「！」）挂回上一句，别单独成条
    glued = []
    for seg in segments:
        if glued and all(char in _TRIM for char in seg):
            glued[-1] = glued[-1] + seg
        else:
            glued.append(seg)
    segments = glued

    index = 0
    while len(segments) > 1 and index < len(segments):
        if len(segments[index]) < min_len:
            if index + 1 < len(segments):
                segments[index + 1] = segments[index] + segments[index + 1]
                del segments[index]
                continue
            segments[index - 1] = segments[index - 1] + segments[index]
            del segments[index]
            break
        index += 1

    while len(segments) > max_segments:
        best = 0
        best_len = None
        for cursor in range(len(segments) - 1):
            total = len(segments[cursor]) + len(segments[cursor + 1])
            if best_len is None or total < best_len:
                best_len = total
                best = cursor
        segments[best] = segments[best] + segments[best + 1]
        del segments[best + 1]

    return [seg for seg in segments if seg][:max_segments]


def typing_delay_ms(text, base=700, per_char=400, cap=20000):
    """按回复字数模拟打字时间，越长的回复停顿越久；标点再补一点。"""
    clean = re.sub(r"\s+", "", str(text or ""))
    chars = len(clean)
    pauses = (
        clean.count("。") + clean.count("！") + clean.count("？")
        + clean.count("!") + clean.count("?") + clean.count("…")
    )
    commas = clean.count("，") + clean.count(",") + clean.count("、")
    value = base + chars * per_char + pauses * 70 + commas * 35
    value = min(value, cap)
    value = max(200, value * random.uniform(0.85, 1.2))
    return int(value)
