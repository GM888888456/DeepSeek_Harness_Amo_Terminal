# -*- coding: utf-8 -*-
"""Amo 出口润色校验（纯本地规则，不调用模型）。

2026-11-26 用户口径：「润色！我说了多少遍」。
这条链上以前只有「删」——删套话、删八股、删地点前缀；没有任何一层在管
「这句话像不像正常人说的」。这里补上，抓三类烂句：

  · 半截话 —— 从「所以就 / 而且 / 但是」这类连接词起头，或话没说完就断；
  · 复读   —— 把对方的话换个人称丢回去，绕一圈等于没说话；
  · 空转   —— 「X 就 X」，前后只差一个代词（「多我一个不多」→「多你一个就多一个」）。

命中不重写、不额外调模型：群里直接不发（沉默比烂话好），私聊换成一句极短的
追问。判不准一律放行——宁可漏掉一句，也不许把正常的话拦死。
"""

from __future__ import annotations

import re

#: 从这些词起头说明是接着上一句说的半截话。单字「就/也/还」不算（「就这？」很正常）。
_HEAD_WORDS = ("所以就", "而且", "但是", "可是", "所以", "然后", "于是", "不过",
               "并且", "再说了", "然后呢", "不过呢")

#: 话说到这些词上就断，等于没说完。
_TAIL_WORDS = ("就", "也", "又", "还", "却", "而", "而且", "但是", "所以", "因为",
               "如果", "要是", "虽然", "并且", "也不过")

#: 句末语气词，比较「空转」时先剥掉。
_TAIL_PARTICLES = "呗吧啊呀嘛哈哦喔咧咯啦嘛"

_SWAP = str.maketrans({"我": "你", "你": "我"})


def _core(text):
    """只留实字：去标点、空白、emoji。"""
    return re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text or "")


def _strip_pron(s):
    return re.sub(r"[我你他她它咱们]", "", s or "")


def _lcs_len(a, b):
    """最长公共子串长度（两句都很短，直接 DP）。"""
    if not a or not b:
        return 0
    best = 0
    prev = [0] * (len(b) + 1)
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        ai = a[i - 1]
        for j in range(1, len(b) + 1):
            if ai == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def _is_tautology(core):
    """「多你一个就多一个」：以「就」为界，两边去掉人称代词后是同一句。"""
    for pos in range(len(core)):
        if core[pos] != "就":
            continue
        left = _strip_pron(core[max(0, pos - 8):pos]).rstrip(_TAIL_PARTICLES)
        right = _strip_pron(core[pos + 1:pos + 9]).rstrip(_TAIL_PARTICLES)
        if len(left) >= 2 and len(right) >= 2:
            if left == right or left.endswith(right) or right.endswith(left):
                return True
    return False


def _is_echo(core, incoming):
    """把对方的话换个人称（或原样）丢回去。"""
    other = _core(incoming)
    if not other:
        return False
    for cand in (other, other.translate(_SWAP)):
        lcs = _lcs_len(core, cand)
        if lcs >= 5 and lcs >= 0.5 * len(core):
            return True
    return False


def check_broken(text, incoming=""):
    """返回拦截原因；放行返回空串。"""
    t = (text or "").strip()
    core = _core(t)
    if len(core) <= 4:            # 「嗯」「好嘞」「就这」这种没得挑
        return ""
    for word in _TAIL_WORDS:
        if core.endswith(word) and len(core) >= 8:
            return "半截话（说到「%s」就断了）" % word
    if _is_tautology(core):
        return "空转（前后同一句，只换了个代词）"
    if _is_echo(core, incoming):
        return "复读（把对方的话换个说法丢回去）"
    return ""


#: 评价词：出现它却没有任何具体东西，就是“空评价”。
_EVAL_WORDS = ("真", "挺", "够", "太", "怪", "倒是", "还行", "不错", "有意思",
               "绝了", "离谱", "服了", "没谁了", "也是", "可以啊")

#: 时间词：有它就算有指涉。
_TIME_WORDS = ("今天", "明天", "昨天", "早上", "上午", "中午", "下午", "晚上",
               "半夜", "刚才", "现在", "一会儿", "待会", "等会", "分钟", "小时",
               "今儿", "明儿", "周末",
               # 2026-11-27：方言/口语的说法没进表，害得「清早八晨的…」被判成零指涉
               "清早", "大清早", "清早八晨", "大早", "一早", "天亮", "天黑",
               "傍晚", "凌晨", "礼拜")

#: 虚字：不能当“具体东西”算。
_STOP_CHARS = set("的了是在就也都很我你他她它们这那个不没有和跟把被给让说吗呢吧啊呀嘛呗哦哈么啥一会能可就要")


def _bigrams(s):
    return {s[i:i + 2] for i in range(len(s) - 1)}


def is_vague(text, incoming=""):
    """空评价（八股）判定：没指到任何具体东西，只剩一个态度词。

    判据：没数字、没时间词、与对方的句子没有共用的实词，却带评价词。
    ≈4 实字一律放行（「嗯」「就这」这种没得挑）——判不准一律放行。
    """
    core = _core(text)
    if len(core) <= 5:
        return False
    if re.search(r"\d", core):
        return False
    if any(w in core for w in _TIME_WORDS):
        return False
    inc = _core(incoming)
    # 2026-11-27：对方只发了一个字（「早」「好」）时，共用实词无从谈起，
    # 这时候判「零指涉」就是误杀——实测把「你倒是醒得比我还早」判成了八股。
    if len(inc) < 2:
        return False
    # 句子里点了对方或第三人，本身就有指涉，不算空评价。
    if re.search(r"[你他]", core):
        return False
    # 2026-11-28（用户：「他好像不理解上下文」）：反问句本身就是在回应对方。
    # 「真会挑时候，大忙人还盯着我呢？」被判成空评价，重写成「吃着鲍鱼燕窝粥
    # 还要被你抓包」——跟他说的话毫无关系。
    if re.search(r"[？?]\s*$", str(text or "").strip()):
        return False
    if inc:
        shared = _bigrams(core) & _bigrams(inc)
        shared = {g for g in shared if not (set(g) & _STOP_CHARS)}
        if shared:
            return False
    return any(w in core for w in _EVAL_WORDS)


_FOOD_WORDS = ("吃", "喝", "早餐", "早饭", "午饭", "晚饭", "粥", "面", "饭", "咖啡", "茶", "杯")


def drifts(new, incoming="", activity=""):
    """改写后的这句是不是跑了题（2026-11-28）。

    事例：他 08:39 说「在上班啊」，她原本回「真会挑时候，大忙人还盯着我呢？」，
    被重写成「吃着鲍鱼燕窝粥还要被你抓包」——粥是她日程早餐里的，跟他那句话
    没关系。两个判据：跟对方原话一个实词都不共用；或者把日程里的吃喝搬来回话，
    而他压根没提过吃喝。
    """
    src = str(new or "").strip()
    if not src:
        return "空"
    inc = _core(incoming)
    if len(inc) >= 6:
        shared = _bigrams(_core(src)) & _bigrams(inc)
        shared = {g for g in shared if not (set(g) & _STOP_CHARS)}
        if not shared:
            return "跟对方说的没有共同话题"
    act = str(activity or "")
    if act and any(w in act for w in _FOOD_WORDS) and not any(w in inc for w in _FOOD_WORDS):
        if any(w in src for w in _FOOD_WORDS):
            return "拿日程里的吃喝当回话"
    return ""


if __name__ == "__main__":       # 离线自测
    bad = [
        ("你这句话，我可记着了，多你一个就多一个呗", "再说群里一百多号人，多我一个不多。"),
        ("我觉得这事儿就这么办", ""),
        ("群里一百多人呢，你嘴上没个把门的 (￣▽￣)~*", "看看腿"),
    ]
    for s, inc in bad:
        print("BAD? %-24s <- %s" % (check_broken(s, inc) or "放行", s))
    good = ["群里一百多人呢，你嘴上没个把门的 (￣▽￣)~*", "腿有啥好看的嘛", "我都投完了，你再催我币就没了",
            "嗯", "就这？", "要得，我记下了", "多你一个不多，少你一个不少", "我这就去贵安看机房，路上得半小时",
            "所以我就不去了", "不过你也别太当真", "然后呢"]
    for s in good:
        r = check_broken(s, "看看腿")
        print("OK?  %-24s <- %s" % (r or "放行", s))
