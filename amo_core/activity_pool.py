# -*- coding: utf-8 -*-
"""软活动候选池 + 连续性约束（活动层）。

分工（2026-11-28 五仓库复审结论）：

- 时间/地点/硬事件由日程骨架决定（不动）；
- **这一小时具体做什么**，从这里挑，而不是从一句写死的 BANK 里随机抽；
- LLM 只负责把挑好的那件事说得像她本人。

约束（都是本地的、可测的）：

1. 不跟上一格重复；
2. 不跟最近两格重复（避免「刷手机、刷手机、刷手机」）；
3. 同一件事一天最多出现 CAP 次（发呆这类放宽到 CAP_LOOSE）；
4. 同一个 (小时, 活动) 如果前两天出现过，尽量避开（避免「每天 20:00 都在刷手机」）；
5. 今日状态影响权重：累 → 躺着/洗澡/什么都不想干；心情好 → 院子/茶室/看电影。

数据在这里，规则在这里；调用方只传上下文，不复制一份判断。
"""

from __future__ import annotations

#: 各类软活动候选。键是 (zone, category)，值是候选句子（可直接当 activity）。
POOLS = {
    ("home", "rest"): (
        "在客厅放着片子，人没怎么看", "窝在沙发上刷手机", "在露台上吹风，什么都没想",
        "去院子走了一圈", "在茶室坐了会儿，泡了壶茶", "泳池边坐着，脚垂在水里",
        "靠在床头看书，看到一半走神", "什么都不想干，就那么躺着",
    ),
    ("home", "life"): (
        "收拾衣帽间，把新到的裙子挂好", "洗了头，慢慢吹干",
        "在厨房看郑师傅备菜", "给自己敷了面膜", "整理明天要带的东西",
        "在书房把文件归了归类", "给花换了水",
    ),
    ("home", "play"): (
        "在影音室挑了部老片", "和院子里的狗玩了一会儿",
        "在泳池游了几圈", "在琴房弹了会儿（弹得一般）",
    ),
    ("home", "work"): (
        "在书房看集团报表", "跟何助理通了个电话，问了两件事",
        "在电脑前改方案，改到第三版", "把下周的会都定下来了",
    ),
    ("company", "work"): (
        "在会议室听部门汇报，只在关键处问一句", "在办公室看材料，圈了几处要改的",
        "把两个部门的方案并到一起看", "跟财务对了下季度预算",
        "签了几份文件，顺手把一版驳回", "在落地窗前站了会儿，想事情",
    ),
    ("company", "rest"): (
        "在办公室的沙发上歪着刷手机", "泡了杯咖啡，靠着窗站了会儿",
        "把鞋脱了一只，脚踩着地毯", "跟何助理说了句废话才回去开会",
    ),
}

#: 单日次数上限（同一句）
CAP = 2
#: 发呆/刷手机这类「空活动」单独放宽，但也别一天五次
CAP_LOOSE = 3

#: 空活动关键词（放宽上限，同时在「累」的时候加权）
IDLE_WORDS = ("刷手机", "发呆", "什么都没想", "躺着", "歪着", "站着")

#: 状态词 → 加权（出现就加分）
STATE_BONUS = {
    "tired": ("躺着", "什么都不想干", "洗了头", "歪着", "靠在床头"),
    "happy": ("院子", "茶室", "影碟", "挑了部老片", "泳池"),
    "sad": ("靠在床头", "什么都不想干", "在露台上吹风"),
    "busy": ("报表", "方案", "开会", "材料"),
}


def candidates(zone, category):
    """某个 (地点类型, 类别) 下的候选活动。"""
    return POOLS.get((str(zone or ""), str(category or "")), ())


def _cap_of(text):
    return CAP_LOOSE if any(word in text for word in IDLE_WORDS) else CAP


def pick(zone, category, *, hour=0, prev="", recent=(), counts=None, history=(),
         mood="", rng=None):
    """挑一条本小时的活动。

    prev / recent：今天前几格的活动（避免连着重）；
    counts：今天各句已出现次数；
    history：前两天的 {hour: activity}，用来避开「每天同一时刻同一件事」；
    mood：tired / happy / sad / busy（或能命中的中文词）。
    """
    pool = list(candidates(zone, category))
    if not pool:
        return ""
    counts = dict(counts or {})
    recent = tuple(recent or ())
    history = list(history or [])

    def allowed(text):
        if text == prev:
            return False
        if text in recent[-2:]:
            return False
        if counts.get(text, 0) >= _cap_of(text):
            return False
        return True

    kept = [text for text in pool if allowed(text)]
    if not kept:                      # 实在没有新的了，就退回「不跟上一格重复」
        kept = [text for text in pool if text != prev] or pool

    # 跨天：同一小时前两天做过的，排到最后
    same_slot = set()
    for day in history:
        if isinstance(day, dict):
            value = str(day.get(str(int(hour))) or day.get(int(hour)) or "")
            if value:
                same_slot.add(value)
    fresh = [text for text in kept if text not in same_slot]
    if fresh:
        kept = fresh

    # 状态加权：命中的排前面（但不是硬规则）
    bonus = ()
    for key, words in STATE_BONUS.items():
        if key in str(mood or "") or any(word in str(mood or "") for word in words):
            bonus = words
            break
    if bonus:
        preferred = [text for text in kept if any(word in text for word in bonus)]
        if preferred:
            # 状态命中就只在命中项里挑：不然「加成」等于没有
            kept = preferred

    if rng is None:
        return kept[0]
    return kept[rng.randrange(len(kept))]


def note(counts, text):
    """记一次出现（调用方维护当天计数）。"""
    if text:
        counts[text] = int((counts or {}).get(text, 0)) + 1
    return counts


__all__ = ["POOLS", "CAP", "CAP_LOOSE", "IDLE_WORDS", "STATE_BONUS", "candidates", "pick", "note"]
