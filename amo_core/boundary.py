# -*- coding: utf-8 -*-
"""亲密称呼的边界（2026-11-21）。

她的原话：「有人让他喊老公，他居然喊……让他知道，只有恋人才能喊老公这种亲密的啊？
其他人直接怼回去然后拉抵触。」

两件事：
1. `asks_intimate()`：这句是不是在要她喊亲密称呼（「喊我一声老公」「叫人家一声」）。
2. `scrub_intimate()`：非恋人的回复里出现「老公 / 老婆 / 亲爱的 …」时直接抹掉，
   换成「你」——不靠模型自觉，发送前硬拦。

注意：只在**非恋人**这条路上用。他（恋人）该怎么叫就怎么叫。
"""

from __future__ import annotations

import re

#: 只属于恋人的称呼。顺序有意义：长的先替换，免得「老婆子」被拆成「老婆」。
INTIMATE_WORDS = (
    "老公公", "老婆子", "媳妇儿", "亲爱的", "宝贝儿", "小宝贝",
    "老公", "老婆", "媳妇", "宝贝", "宝宝", "亲亲", "心肝", "臭宝",
)

#: 「喊我一声老公」「叫我一句亲爱的」这类直球
_ASK_RE = re.compile(
    r"(喊|叫|称呼|喊声|叫声|来声|说声|给我喊|给我叫)[^，,。.!！?？]{0,8}"
    r"(老公|老婆|亲爱的|宝贝|宝宝|亲亲|心肝|媳妇)"
)
#: 「也喊我一下」「叫我一声」——上次有人要她喊老公，后面跟风（允许前面带 @昵称）
_FOLLOW_RE = re.compile(
    r"(?:^|[\s，,。.!！?？、])[^\s，,。.!！?？、]{0,8}?"
    r"(?:也|再|那也|顺便)?\s*(喊|叫|称呼)(我|人家)\s*(一声|一句|一下|声)?\s*"
    r"(老公|老婆|亲爱的|宝贝|宝宝|亲亲|心肝|媳妇|听听|嘛|吧|哈|呗)?\s*$"
)

#: 只要句子里出现这些，就认为她在用昵称称呼对方
_WORD_RE = re.compile("(%s)" % "|".join(re.escape(w) for w in INTIMATE_WORDS))


def _strip_mentions(text: str) -> str:
    """去掉「@晓辞沫」这类点名，只留她要看的那句话。"""
    return re.sub(r"[@＠]\S+", " ", str(text or "")).strip()


def asks_intimate(text: str) -> bool:
    """这句是不是在要她喊亲密称呼（越界请求）。"""
    body = _strip_mentions(text)
    if not body:
        return False
    if _ASK_RE.search(body):
        return True
    if _FOLLOW_RE.search(body) and ("喊" in body or "叫" in body):
        return True
    return False


def mentions_intimate(text: str) -> bool:
    return bool(_WORD_RE.search(str(text or "")))


def scrub_intimate(text: str) -> tuple:
    """把非恋人回复里的亲密称呼换成「你」；返回 (新文本, 命中的词)。"""
    body = str(text or "")
    hits = []

    def _repl(match):
        word = match.group(0)
        if word not in hits:
            hits.append(word)
        return "你"

    fixed = _WORD_RE.sub(_repl, body)
    fixed = re.sub(r"你{2,}", "你", fixed)
    fixed = re.sub(r"你+(?=[，,。.!！?？、；;：:\s]|$)", "你", fixed)
    fixed = re.sub(r"^[，,。、\s]+", "", fixed)
    return fixed, hits


def boundary_notice(sender_name: str = "") -> str:
    """越界那一刻塞给模型的硬提示。"""
    who = (sender_name or "群里这个人").strip()
    return (
        "\n【有人越界】%s 刚刚要你喊他亲密称呼（老公/老婆/亲爱的这类）。"
        "这不是开玩笑的事：这些称呼只属于你的恋人。\n"
        "这一轮必须做到：\n"
        "1. 明确拒绝，口气不好，一句话顶回去（可以带点嫌弃、可以说“想得美”“少来”“你谁啊”）；\n"
        "2. 不许顺着他，不许撒娇、不许解释、不许半推半就当玩笑应下来；\n"
        "3. 之后对他明显冷下来：不主动搭理，他说话就短答或不答。\n"
        % who
    )


def cold_rule() -> str:
    """每轮都带上的一条底线（很短的常驻规则）。"""
    return (
        "\n【称呼底线】老公 / 老婆 / 亲爱的 / 宝贝 / 宝宝 / 亲亲 这些只对你恋人用。"
        "群里别人要你这么叫，直接拒绝并顶回去，别给他面子；不许当成玩笑应下来。"
    )
