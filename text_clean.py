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

# ---------------------------------------------------------------------------
# 元话语 / 思维外泄
# ---------------------------------------------------------------------------
# 2026-11-23 15:27:38，群里她连发两条：
#   叔问“你有尾巴吗？”——直接半句怼回去。
#   “我又不是猴，哪来尾巴”11字，冲，短
# 没有标签、没有 DSML：前面两道闸门（strip_pseudo_tags / voice_guard）都拦不住，
# 因为它们看着就是人话。这里按「形态」认，全部是整行判定，
# 宁可不拦，也不吞掉正常的一句话。

#: 内心独白（2026-11-26 19:04 群里实发）：
#:   等一下，先别把酒桌上的照片当成他发回来的照片——他刚问的是“少喝点”
#:   我该接他这句
#: 模型把自己的推演当正文写出来。按「旁白口吻」认，整行丢弃；判不准就放行。
_META_SELF_TALK_RE = re.compile(
    r"^(?:等一下|等等|先等一下|慢着)[，,]\s*(?:先|别|这|那)"
    r"|^(?:先)?别把[^。！？\n]{0,16}(?:当成|当作|算成)"
    r"|^(?:我该|我得|我要|我还是|我应该)(?:先)?(?:接|回|答|说|想|看)"
    r"|^(?:他|她|对方|群友|他们)(?:刚|刚才)(?:问|说|讲|要)(?:的)?是\s*[“\"「『]"
    r"|^(?:这轮|这次|这条|这句)\s*(?:我|得|该|要|先)"
    r"|(?:这句|那句话)\s*(?:我|该)(?:接|回|答)"
    r"|我该接(?:他|她|这句)"
    r"|^(?:先)?(?:想一下|我想想|让我想想|分析一下|判断一下)"
)

_META_REHEARSAL_RE = re.compile(
    r"^[^\s，。！？]{1,6}(?:问|说|讲)[：:]?\s*[“\"「『][^”\"」』]{0,80}[”\"」』]\s*"
    r"(?:——|—{2,3}|--)\s*(?:直接|干脆|就)?\s*"
    r"(?:半句|一句|怼|答|回他|回她|接他|接她|应他)"
    r"[^。！？!?\n]{0,10}[。！？!?]?$"
)
_META_BARE_RE = re.compile(
    r"^(?:直接|干脆|就|先)?(?:半句|一句)(?:怼|回|答|接|应)"
    r"[^。！？!?\n]{0,10}[。！？!?]?$"
)
_META_COUNT_RE = re.compile(
    r"^(?:\d{1,3}\s*字|半句|一句|短句)\s*(?:[，,、]\s*"
    r"(?:冲|短|软|硬|冷|狠|稳|暖|凶|平|长|干|直)){0,4}\s*[。！？!?]?$"
)
#: 引号台词后面挂的字数标注：`“…”11字，冲，短`
_META_QUOTE_COUNT_RE = re.compile(
    r"([”\"」』])\s*\d{1,3}\s*字\s*(?:[，,、][^。！？!?\n]{0,20})?$")
#: 句尾括号标注：`（1-2句，短，冲）`
_META_BRACKET_TAIL_RE = re.compile(r"[（(]\s*([^（）()]{1,20})[）)]\s*[。！？!?]?\s*$")
#: 清理后只剩一句被引号包着的台词 → 把引号也摘掉，真人说话不带引号
_QUOTE_WRAP_RE = re.compile(r"^[“\"「『]([^”\"」』\n]{1,60})[”\"」』]$")

#: 演算句里带引号台词（2026-11-26 21:09 实发）：
#:   他说的故障我只能回一句「我这边正常」，至于我问谁，就不关他的事
#: 只保留引号里那句，其余全是她自己的推演。
_META_PLAN_QUOTE_RE = re.compile(
    r"(?:我只能|我就|只能|就该|应该|可以|只会|就|想|我)(?:回|说|答)(?:他|她)?"
    r"(?:一?句)?[：:，,\s]*[「“\"]([^」”\"\n]{1,120})[」”\"]")
#: 整行都是演算、又没写引号（「他说的故障我只能回一句我这边正常」）→ 整行丢
_META_PLAN_ONLY_RE = re.compile(
    r"^(?:他|她|对方|群友|他们|这人|那人)[^。！？\n]{0,40}?"
    r"(?:我只能|我就|只能|就该|应该|只会)(?:回|说|答)")
#: 句尾推理尾巴：至于我问谁，就不关他的事 / 反正与我无关
_META_REASON_TAIL_RE = re.compile(
    r"[，,；;、]?\s*(?:至于|反正|不过)[^。！？\n]{0,40}?"
    r"(?:不关[^。！？\n]{0,8}事|与我无关|跟我没关系|和我没关系)[。]?\s*$")


def _bracket_is_meta(inner):
    core = str(inner or "").strip()
    if not core:
        return False
    if re.search(r"\d\s*[-–~]?\s*\d{0,2}\s*[句字]", core):
        return True
    return core in ("半句", "一句", "短句", "字数")


def strip_meta_monologue(text):
    """切掉「模型把自己的推演当正文」的句子。

    返回 (清理后文本, 命中的标签列表)；没命中时原样返回。
    """
    raw = str(text or "")
    if not raw.strip():
        return raw, []
    hits = []
    out = []
    for line in raw.split("\n"):
        s = line.strip()
        if not s:
            out.append("")
            continue
        if _META_SELF_TALK_RE.search(s):
            hits.append("内心独白")
            continue
        # 2026-11-26：演算句「我只能回一句「…」」→ 只留台词
        _plan = _META_PLAN_QUOTE_RE.search(s)
        if _plan:
            hits.append("演算台词")
            s = _plan.group(1).strip()
            if not s:
                continue
        elif _META_PLAN_ONLY_RE.match(s):
            hits.append("演算句")
            continue
        # 句尾推理尾巴：「至于我问谁，就不关他的事」
        _tail = _META_REASON_TAIL_RE.sub("", s).strip()
        if _tail != s:
            hits.append("推理尾巴")
            s = _tail
            if not s:
                continue
        if _META_REHEARSAL_RE.match(s):
            hits.append("排练句")
            continue
        if _META_BARE_RE.match(s) or _META_COUNT_RE.match(s):
            hits.append("字数标注")
            continue
        if _META_QUOTE_COUNT_RE.search(s):
            hits.append("字数标注")
            s = _META_QUOTE_COUNT_RE.sub(r"\1", s).strip()
            if not s:
                continue
        m = _META_BRACKET_TAIL_RE.search(s)
        if m and _bracket_is_meta(m.group(1)):
            hits.append("括号标注")
            s = s[: m.start()].rstrip()
            if not s:
                continue
        out.append(s)
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip()
    if hits:
        m = _QUOTE_WRAP_RE.match(body)
        if m:
            body = m.group(1).strip()
    return body, hits

#: SPEAK 协议行：单独一行、或「SPEAK 1 正文」连写，允许 ** 与引号
_SPEAK_LINE_RE = re.compile(
    r"""^[\s>*_`"'\u300c\u300d]*SPEAK[\s*_]*[:\uff1a]?[\s*_]*([01])[\s*_]*"""
    r"""[\u300c\u300d>*_`"'\s:：,，]*"""
    r"""(.*)$""",
    re.I,
)


#: 第三人称旁白：她把自己写成「她换掉一身烟味…」
#: 只在整条只有一个「她」、且没提到「他」时才改（避免把别的女生的话改成她自己）
_THIRD_SELF_RE = re.compile(
    r'(^|[。！？!?…\n]\s*)她(?=(?:换|洗|卸|穿|脱|坐|躺|站|靠|走|进|出|看|笑|说|把|'
    r'已经|才|刚|不|没|又|还|正|伸手|低头|抬头|慢慢|懒懒))'
)


def fix_first_person(text):
    """把「她＋动作」的旁白改成「我」，别让第三人称叙述流出去。"""
    raw = str(text or "")
    if not raw.strip() or "她" not in raw:
        return raw
    if "他" in raw or raw.count("她") != 1:
        return raw
    return _THIRD_SELF_RE.sub(lambda m: m.group(1) + "我", raw, count=1)


def strip_speak_protocol(text):
    """剥掉模型写的 SPEAK 1 / SPEAK 0 协议行。

    返回 (正文, 决定)：决定是 "0" / "1" / ""（没写协议）。
    "0" 时正文为空串，调用方按空串处理即可（不发）。
    """
    raw = str(text or "")
    if not raw.strip() or "speak" not in raw.lower():
        return raw, ""
    decision = ""
    kept = []
    for line in raw.split("\n"):
        m = _SPEAK_LINE_RE.match(line.strip())
        if m:
            decision = decision or m.group(1)
            rest = (m.group(2) or "").strip()
            if rest:
                kept.append(rest)
            continue
        kept.append(line)
    body = "\n".join(kept).strip()
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    if decision == "0":
        return "", "0"
    return body, decision
