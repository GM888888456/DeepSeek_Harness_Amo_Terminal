# -*- coding: utf-8 -*-
"""颜文字：按她此刻的七情六欲挑，不是随机贴。

两个克制：
  · 概率低（默认 18%）、且上一句带过就跳过 —— 每条都带是最不像人的地方；
  · 只在句尾追加，前面空一格；已经带括号表情的句子不重复加。
"""

from __future__ import annotations

import random
import re
from typing import Optional

# 类别 → (七情维度, 颜文字池)
POOLS: dict[str, tuple[str, tuple[str, ...]]] = {
    "开心": ("joy", ("(*^▽^*)", "(≧▽≦)", "(￣▽￣)~*", "(๑•̀ㅂ•́)و✧", "٩(๑❛ᴗ❛๑)۶", "(・∀・)")),
    "撒娇": ("love", ("(｡･ω･｡)ﾉ♡", "(๑´ㅂ`๑)", "(´･ω･`)", "(⁄ ⁄•⁄ω⁄•⁄ ⁄)", "(๑•́ ₃ •̀๑)")),
    "无语": ("disgust", ("(￣_￣)", "(・_・;)", "(￣ω￣)")),
    "生气": ("anger", ("(｀へ´)", "ヽ(`Д´)ﾉ", "(￣^￣)")),
    "委屈": ("sadness", ("(｡•́︿•̀｡)", "(´；ω；`)", "(＞﹏＜)")),
    "惊讶": ("surprise", ("(⊙_⊙)", "(ﾟДﾟ)", "(๑°ㅁ°๑)")),
    "困": ("energy", ("(－_－) zzZ", "(´-ω-)zzz", "(￣o￣) zzZ")),
}

# 只看这几个维度；六欲和饥饿不参与
_WATCH = ("joy", "love", "disgust", "anger", "sadness", "surprise")

# 句子末尾已经有这类括号表情/颜文字 → 不再加
_HAS_KAO = re.compile(r"[（(][^（）()]{1,12}[）)]\s*$|[\U0001F300-\U0001FAFF]")

# 太短的回复（「嗯」「哦」「？」）不加，否则像表情机器人
_MIN_LEN = 3


def _top(feel: dict) -> str:
    """取此刻最突出的那一维；都在常态（<50）就不加情绪色。"""
    best, best_val = "", -1.0
    for dim in _WATCH:
        try:
            val = float((feel or {}).get(dim) or 0)
        except (TypeError, ValueError):
            continue
        if val > best_val:
            best, best_val = dim, val
    return best if best_val >= 55 else ""


def pick(feel: dict, rng: Optional[random.Random] = None) -> str:
    """按情绪挑一个颜文字；没有明显情绪时从「开心 + 撒娇」里挑。"""
    r = rng or random
    top = _top(feel)
    names = [name for name, (dim, _) in POOLS.items() if dim == top]
    if not names:
        names = ["开心", "撒娇"]
    # 能量低优先判困；但 energy 没传时不能当成 0（那会把所有情绪都判成困）
    _energy = (feel or {}).get("energy")
    if _energy is not None:
        try:
            if float(_energy) <= 12:
                names = ["困"]
        except (TypeError, ValueError):
            pass
    return r.choice(POOLS[names[0]][1])


def maybe_append(
    text: str,
    feel: Optional[dict] = None,
    rng: Optional[random.Random] = None,
    prob: float = 0.18,
    last_had: bool = False,
) -> str:
    """按概率在句尾补一个颜文字。

    ``last_had`` 为真（上一条刚带过）就不再带，避免连着两条都是表情。
    """
    raw = str(text or "")
    body = raw.strip()
    if not body or len(re.sub(r"\s", "", body)) < _MIN_LEN:
        return raw
    if _HAS_KAO.search(body):
        return raw
    if last_had:
        return raw
    r = rng or random
    if r.random() >= max(0.0, min(float(prob), 1.0)):
        return raw
    return body + " " + pick(feel, rng=r)


__all__ = ["POOLS", "pick", "maybe_append"]
