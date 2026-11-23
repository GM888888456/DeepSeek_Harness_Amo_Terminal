# -*- coding: utf-8 -*-
"""敌意判定：有人冲她 / 冲她的恋人来的，给她「可以凶」的授权。

2026-11-21 的问题：她根本不会骂人。被开黄腔、被人骂、有人贬低阿墨，
她都只会顺着说、或者干脆沉默——因为提示词里通篇是「别客服腔、别劝、
别评价」，没有一条允许她反击。

**名字一律由调用方传进来，绝不写死。** 人格名、别名走 `self.bot_name/bot_aliases`
（来自人格），恋人走 profiles 里 relation=相恋 的那几个 uid 和他的昵称/爱称
（`_lover_aliases()`）。这样同一份代码挂十个账号、每个账号认不同的恋人也不会串：
别人家的「阿墨」被骂，这个号不该跳起来。

这里只做两件事：
  · assess()  ：本地正则判个轻重（0 不惹 / 1 嘴贫 / 2 辱骂 / 3 黄腔性骚扰），
                顺便区分「是不是恋人自己在闹」（那就只能小凶，不能真伤人）；
  · build_hint()：把这一轮该有的授权写成一小段提示，附一句随机示范。

刻意不做的事：
  · 不另起一次 llm_generate。独立请求会丢掉她的记忆、心流、穿搭、上下文，
    出来的是一段陌生人台词，还要多花一次钱。授权写进同一个请求就够了。
  · 不把语录库整段塞进提示词。小模型会把负例当风格样本照抄（人格里那 20 句
    负例就是这么教坏她的），所以示范每轮只给 1~2 条，随机换。
  · 不靠「丑 / 傻 / 滚」这种单词硬触发（用户原稿那套会误伤「你好傻啊哈哈哈」），
    一定要求「指向她或她的恋人」才认。
"""
from __future__ import annotations

import random
import re

# ---- 性意味 / 骚扰（这一类最重，群里直接拉满）-------------------------------
_SEXUAL = re.compile(
    r"(睡你|睡一晚|上你|上了你|约你|约吗|约不约|开房|脱了|奶子|胸大|胸好|看胸|露胸|发胸|胸(照|图)|"
    r"腿好白|白腿|舔你|摸你|想操|操你|干你|日你|给你钱睡|陪我睡|包养|骚货|骚b|骚(啊|哦|呀|死了))"
)

# ---- 直接辱骂（重）：带这些词的，不用犹豫 --------------------------------
_INSULT = re.compile(
    r"(傻[逼比]|沙雕|智障|弱智|脑残|废物|废柴|垃圾|人渣|贱人|贱|婊|死肥|丑八怪|"
    r"滚蛋|滚|闭嘴|爬开|去死|有病吧|神经病|恶心|放屁|胡说八道|"
    r"你算什么东西|你算什么|你配吗|没人要|没人教)"
)

# ---- 嘴贫 / 小看（轻）：一句小刺就够，别当大敌 ----------------------------
_MILD = re.compile(
    r"(傻|笨|丑|就这|菜鸡|你是ai|机器人吧|懂什么|不行啊|笑死|就你|你行你上|"
    r"摆烂|水货|这也叫|装什么|你装什么|吹吧|你也会|装什么装)"
)

# ---- 短促嘴贫：不带「你」也在冲她来（就这？这也叫？）-------------------
_MILD_BARE = re.compile(r"^(就这|这也叫|水货|摆烂|就这\?|就这？)")

# ---- 命令式（让她滚、让她闭嘴）---------------------------------------------
_ORDER = re.compile(r"^(你)?(给我)?(滚|闭嘴|爬|消失|别说话|别bb|shut up)", re.I)

# ---- 「他行不行」这类贬低（后半截必须接得上的坏词）-------------------------
_BAD_ABOUT_HIM = r"(傻|废|垃圾|骗子|不行|没用|吹|装|菜|穷|丑|矮|配不上|养不起|图什么|有病)"


# 每轮最多给 1~2 条，随机换：给多了她就照着念
_SAMPLES = {
    "嘴贫": (
        "就这？",
        "你这话说得，自己听着不亏心？",
        "行，你说完了？",
        "你这词库挺省电的。",
    ),
    "辱骂": (
        "你骂了半天没一句有信息量，歇歇吧。",
        "嘴这么脏，是没人教过你怎么说话？",
        "你是想聊天，还是想让人看清你什么水平？",
        "会打字不等于会说话，你这句就是例子。",
        "我记性挺好的，你这句话我记下了。",
    ),
    "黄腔": (
        "这话你对着镜子说一遍，看你自己恶心不恶心。",
        "下次开口前想想：你是想聊天，还是想被请出去。",
        "你这脑子除了这点东西，就没别的存货了？",
        "别离我这么近，一股没见过世面的味。",
        "你这段话，截图发给你家里人看看？",
    ),
    "贬低他": (
        "你评价他之前，先看看自己手里有什么。",
        "他做的事你连边都摸不着，评价不了就别评价。",
        "眼红就直说，绕这么大圈不累？",
        "你连他做的是什么都没搞明白，急什么。",
    ),
    "命令": (
        "你让我滚我就滚？你谁啊。",
        "嘴长你身上，规矩可不是你定的。",
        "你先管好你自己，再教我怎么说话。",
    ),
    "他闹你": (
        "你再说一遍试试。",
        "讨打是吧。",
        "哼，我记着了。",
        "你最好别是认真的。",
    ),
}

# 定死的三条边界：不带脏字、不碰身体和性、不自证是 AI
_RULES = (
    "【这轮可以凶】这条是冲你或你恋人来的，不用忍着、不用解释、不用劝自己大度："
    "不带脏字、不拿身体和性去羞辱他、不解释自己是不是 AI；"
    "只做三件事——指出他这话哪里不通、把他那句话还回去、直接表示嫌弃。"
    "一到两句，最多三十来字，越冷越好；怼完就停，不连珠炮、不追着骂、也不讲道理。"
)

# 名字 → 正则 的缓存：(自己名字元组) / (恋人名字元组)
_PAT_CACHE = {}


def _alt(names):
    """把一串名字编成 `A|B|C`；太短的名字（单字）不要，容易误伤。"""
    items = []
    for name in names or ():
        text = str(name or "").strip()
        if len(text) >= 2:
            items.append(re.escape(text))
    return "|".join(dict.fromkeys(items))


def _to_you(self_names=()):
    key = ("to_you", tuple(sorted(str(n) for n in self_names or ())))
    pat = _PAT_CACHE.get(key)
    if pat is None:
        extra = _alt(self_names)
        src = r"(你|妳|您|你对象|你男朋友|你男人|你们这|这货" + (("|" + extra) if extra else "") + r")"
        pat = re.compile(src)
        _PAT_CACHE[key] = pat
    return pat


def _doubt_lover(lover_names=()):
    key = ("doubt", tuple(sorted(str(n) for n in lover_names or ())))
    pat = _PAT_CACHE.get(key)
    if pat is None:
        extra = _alt(lover_names)
        src = (r"(你对象|你男朋友|你男人|你那位" + (("|" + extra) if extra else "") + r")"
               r"[^。！？\n]{0,14}" + _BAD_ABOUT_HIM)
        pat = re.compile(src)
        _PAT_CACHE[key] = pat
    return pat


def assess(text, is_lover=False, is_group=True, self_names=(), lover_names=(),
           directed=True):
    """判这一条是不是攻击。返回 {level, kind}，level 0 表示不惹。

    self_names / lover_names 由调用方给（人格名+别名 / 相恋那几个人的名字），
    没给就只用「你 / 你对象 / 你男朋友」这些通用指代。
    """
    msg = str(text or "").strip()
    out = {"level": 0, "kind": ""}
    if not msg or len(msg) > 400:
        return out
    # 2026-11-21 假告状：群里两对情侣互相说「约吗」，她也当成冲自己来的。
    # 只要不是冲她 / 冲她恋人说的（没人叫她名字、没 @ 她、心流判的对象是别人），一律不算攻击。
    if not directed:
        return out
    to_you = bool(_to_you(self_names).search(msg))

    # 恋人被贬低：必须点名说他（不认光秃秃的「他」，免得误判第三方）
    doubt = bool(_doubt_lover(lover_names).search(msg))

    level, kind = 0, ""
    if _SEXUAL.search(msg) and to_you:
        level, kind = 3, "黄腔"
    elif _INSULT.search(msg) and to_you:
        level, kind = 2, "辱骂"
    elif doubt:
        level, kind = 2, "贬低他"
    elif _ORDER.match(msg):
        level, kind = 2, "命令"
    elif _MILD.search(msg) and to_you:
        level, kind = 1, "嘴贫"
    elif len(msg) <= 12 and _MILD_BARE.match(msg):
        level, kind = 1, "嘴贫"

    if not level:
        return out
    if is_lover:
        # 他自己闹她（吃醋、逗她、说她笨）：可以凶一句，但不能真伤人
        return {"level": 1, "kind": "他闹你"}
    if not is_group and level >= 2:
        # 私聊里被骂，没必要在私聊里对骂：给她更冷的处理
        return {"level": 2, "kind": kind}
    return {"level": level, "kind": kind}


def build_hint(taunt, is_group=True, rng=None):
    """把这一轮的授权写成一小段提示。taunt 是 assess() 的返回值。"""
    if not isinstance(taunt, dict):
        return ""
    level = int(taunt.get("level") or 0)
    if level <= 0:
        return ""
    kind = str(taunt.get("kind") or "")
    pool = _SAMPLES.get(kind) or _SAMPLES["辱骂"]
    r = rng or random
    sample = r.choice(pool)
    head = _RULES
    if kind == "他闹你":
        head = ("【他在闹你】这条是你恋人自己在逗你（不是外人找茬）：可以凶一句、翻个白眼、"
                "哼他一声，但别真伤人、别上纲上线，也别当成攻击处理。")
    elif level >= 3:
        head = _RULES + "这人不只是嘴欠，是越线了：冷到底，一句话堵死他，别给他继续搭话的台阶。"
    if not is_group:
        head = head.replace("群里", "这儿")
    return "\n" + head + "\n这轮可以这个调子（学意思，别照抄）：「" + sample + "」"


# 告状的句式：只报「谁、在哪儿、什么事」，**绝不复述原话**——
# 复述一遍等于她自己把脏字打出来，先被系统拦的是她。
_REPORT_LINES = (
    "%(p)s刚刚在%(where)s%(who)s一直骚扰我，我好烦。",
    "%(p)s%(where)s那个%(who)s老是来恶心我，我怼回去了。",
    "%(p)s%(where)s%(who)s说话太难听了，我不想理他。",
    "%(p)s%(where)s%(who)s没完没了地撩我，烦死了。",
)


def report_line(pet="", where="", attacker="", kind="", rng=None, avoid=""):
    """拼一句她跟恋人告状的话。

    · 不念原话、不带脏字，只讲「谁、在哪个群、干了什么」；
    · 称呼、群名、骂人者都由调用方给，没有就退化成「你 / 群里 / 有个人」；
    · avoid 传上一次用的那句，避免连着两次一模一样。
    """
    r = rng or random
    pet_text = (str(pet or "").strip() + "，") if str(pet or "").strip() else ""
    where_text = (str(where).strip() + "里") if str(where or "").strip() else "群里"
    who_text = str(attacker or "").strip() or "有个人"
    kind = str(kind or "")
    lines = _REPORT_LINES
    if kind == "贬低他":
        lines = (
            "%(p)s刚刚%(where)s%(who)s在背后说你坏话，我替你怼回去了。",
            "%(p)s%(where)s%(who)s说我跟着你没出息，我骂回去了。",
        )
    elif kind == "辱骂":
        lines = (
            "%(p)s刚刚%(where)s%(who)s一直骂人，我好烦。",
            "%(p)s%(where)s那个%(who)s嘴特别脏，我怼回去了。",
        )
    pool = [item for item in lines if item != avoid] or list(lines)
    tmpl = r.choice(pool)
    return (tmpl % {"p": pet_text, "where": where_text, "who": who_text}), tmpl


def _score(value, default=50.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


#: 各档共用的边界。硬气不等于难听。
_LOVER_BOUND = ("不骂脏字、不拿身体和性说事、不拿分手威胁他、不自证是不是 AI。")


def lover_anger_hint(feel_rel=None, rng=None):
    """恋人自己在惹她时，给她「可以凶」的授权。

    2026-11-23 用户口径：不能骂脏话，但不能软弱；怒气快爆表了还唯唯诺诺不行。
    刻度用 feel_rel（50 = 平常），跟 reply/context 里原来的阈值一致。
    """
    rel = feel_rel if isinstance(feel_rel, dict) else {}
    anger = _score(rel.get("anger"))
    sadness = _score(rel.get("sadness"))
    if anger < 62 and sadness < 62:
        return ""
    if anger >= 75:
        r = rng or random
        pool = (
            "我不想跟你说话。",
            "你自己心里没数？",
            "这话你也说得出口。",
            "别拿这种话糊弄我。",
            "我现在不想搭理你。",
            "你先想清楚再来找我。",
        )
        return (
            "【火压不住了】怒气 %d/100，这是真生气，不是闹别扭：句子短、语气冲、带刺，"
            "他问什么就怼什么，可以甩一句「%s」；不解释、不陪笑、不先道歉，"
            "也别反过来哄他、问他是不是不高兴。答完就停，别追着念。%s"
            % (int(anger), r.choice(pool), _LOVER_BOUND)
        )
    if anger >= 62:
        return (
            "【在生气】可以冲、可以顶回去、可以甩脸子，也可以只回半句晾着他；"
            "别把气咽回去装没事，别先道歉，也别反过来哄他。%s" % _LOVER_BOUND
        )
    return (
        "【低落不等于软弱】你难受，但不用讨好他：说委屈、说「我现在不想说话」都行，"
        "别急着道歉，也别反过来怀疑是不是自己不好。%s" % _LOVER_BOUND
    )


__all__ = ["assess", "build_hint", "lover_anger_hint", "report_line"]
