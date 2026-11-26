# -*- coding: utf-8 -*-
"""世界状态与事件引擎：每天推进一次，事件影响势力关系，落盘可查。

- 有连续性：事件进 history，昨天的麻烦今天还能被提起；
- 有后果：每个事件对 省里/军方/金融/商界/媒体 五方有正负影响，声望跟着动；
- 有边界：事件只给「发生了什么」，怎么反应交给她（也交给你）；
- 可读：面板与上下文读同一份 state，不存在两份真相。

落盘：plugin_data/DeepSeek_Harness_Amo_Terminal/world_state.json
"""

from __future__ import annotations

import json
import os
import random

FACTIONS = ("省里", "军方", "金融", "商界", "媒体")

DEFAULT_STATE = {
    "day": "",
    "factions": {"省里": 52, "军方": 55, "金融": 60, "商界": 50, "媒体": 42},
    "reputation": 52,
    "today": [],
    "history": [],
    "log": [],
}

EVENT_POOL = [
    {"id": "rival_bid", "tag": "竞争", "weight": 9,
     "text": "京畿智算在省里那个智算中心的标上压了价，评审组里有他们的人。",
     "effects": {"商界": -3, "省里": -2}},
    {"id": "client_renew", "tag": "生意", "weight": 8,
     "text": "云平台最大的那个客户主动提了续约，还想加两千张卡的用量。",
     "effects": {"商界": +5, "金融": +2}},
    {"id": "price_war", "tag": "竞争", "weight": 7,
     "text": "海图科技把推理报价又砍了三成，市场部说有几家小客户在观望。",
     "effects": {"商界": -2, "媒体": +1}},
    {"id": "chip_shortage", "tag": "供应链", "weight": 6,
     "text": "卡的交期又拖了，供应链说三期的上架时间可能要往后挪两周。",
     "effects": {"商界": -2, "金融": -1}},
    {"id": "big_order", "tag": "生意", "weight": 6,
     "text": "一家做车机的厂商找上门，要包年买推理，量不小但压价狠。",
     "effects": {"商界": +3}},
    {"id": "credit_tight", "tag": "金融", "weight": 7,
     "text": "邮储那边风声说对公授信的额度在收，客户经理让她这周把材料补齐。",
     "effects": {"金融": -4}},
    {"id": "quant_drawdown", "tag": "量化", "weight": 6,
     "text": "幻方这周回撤超了线，资管那边有两个老客户在问要不要赎回。",
     "effects": {"金融": -3, "媒体": -1}},
    {"id": "quant_best", "tag": "量化", "weight": 5,
     "text": "幻方这个月的策略跑得很顺，净值曲线创了年内新高。",
     "effects": {"金融": +4, "商界": +2}},
    {"id": "dividend", "tag": "金融", "weight": 4,
     "text": "集团年度分红的方案报上来了，财务在等她签字。",
     "effects": {"金融": +1}},
    {"id": "gov_visit", "tag": "政商", "weight": 6,
     "text": "省里要来调研算力产业，名单上有她的集团，发改委那边在排时间。",
     "effects": {"省里": +4, "媒体": +1}},
    {"id": "gov_pressure", "tag": "政商", "weight": 5,
     "text": "有人递话过来，说智算中心那个标「最好别争得太难看」。",
     "effects": {"省里": -3, "商界": -2}},
    {"id": "audit", "tag": "合规", "weight": 4,
     "text": "审计组下个月进场，财务部连夜在清账。",
     "effects": {"金融": -1, "省里": -1}},
    {"id": "reporter_push", "tag": "媒体", "weight": 6,
     "text": "苏晚又递了采访函，这次是写「新一代算力玩家」的封面。",
     "effects": {"媒体": +3, "商界": +1}},
    {"id": "bad_press", "tag": "媒体", "weight": 4,
     "text": "有篇稿子在传，说她公司的算力是「堆卡堆出来的」，评论不太好听。",
     "effects": {"媒体": -4, "商界": -1}},
    {"id": "award", "tag": "媒体", "weight": 3,
     "text": "行业榜单把她列进了年度人物候选，公关部很想让她去。",
     "effects": {"媒体": +5, "省里": +1}},
    {"id": "grandpa_call", "tag": "家里", "weight": 5,
     "text": "老宅来了电话，爷爷问她这周回不回去吃饭。",
     "effects": {"军方": +2}},
    {"id": "aunt_tip", "tag": "家里", "weight": 4,
     "text": "姨妈在家族群里又提了一次她的体检，说这次别拖。",
     "effects": {"军方": +1}},
    {"id": "uncle_hint", "tag": "家里", "weight": 3,
     "text": "大伯打电话来，说振华那边有笔钱想跟着她进算力，问她带不带。",
     "effects": {"商界": +2, "军方": +1}},
    {"id": "dc_fault", "tag": "运维", "weight": 5,
     "text": "贵安机房半夜跳了一次电，运维压住了，但复盘报告要她签。",
     "effects": {"商界": -1}},
    {"id": "hire_wave", "tag": "人事", "weight": 4,
     "text": "研发院递上来一批招聘需求，说再不加人，三期的活干不完。",
     "effects": {"金融": -1}},
    {"id": "key_leave", "tag": "人事", "weight": 3,
     "text": "芯片部的负责人提了离职，理由是「想去做点更前面的事」。",
     "effects": {"商界": -2}},
    {"id": "model_win", "tag": "技术", "weight": 5,
     "text": "研发院的新模型在公开测试里跑进了第一梯队，推理成本还比对手低。",
     "effects": {"商界": +4, "媒体": +3, "金融": +1}},
]


# ---------------- 季度主线（每季第一天额外抽一条） ----------------
QUARTER_POOL = {
    1: [
        {"id": "q1_open", "tag": "季度·开局", "weight": 5,
         "text": "开年第一会：集团把今年的营收目标定在 11 亿，比去年翻一成半。",
         "effects": {"商界": +2, "金融": +1}},
        {"id": "q1_hiring", "tag": "季度·开局", "weight": 4,
         "text": "开年招人：研发院要扩 200 个编制，人力部说预算吃紧。",
         "effects": {"金融": -2, "商界": +1}},
    ],
    2: [
        {"id": "q2_chip", "tag": "季度·算力", "weight": 5,
         "text": "二季度卡荒：上游交期整体后移，她把三期上架计划压到下季。",
         "effects": {"商界": -3, "金融": -2}},
        {"id": "q2_customer", "tag": "季度·算力", "weight": 4,
         "text": "二季度大客户集体验收，推理单价被压了一轮，但用量涨了三成。",
         "effects": {"商界": +3, "金融": +1}},
    ],
    3: [
        {"id": "q3_reg", "tag": "季度·合规", "weight": 5,
         "text": "三季度监管加压：数据出境与算力出口管制同时收紧，法务部连开三天会。",
         "effects": {"省里": -3, "金融": -2}},
        {"id": "q3_market", "tag": "季度·合规", "weight": 4,
         "text": "三季度行业洗牌：两家小厂出局，客户往头部集中，她的单子反而多了。",
         "effects": {"商界": +4, "媒体": +1}},
    ],
    4: [
        {"id": "q4_close", "tag": "季度·收官", "weight": 5,
         "text": "四季度收官：集团全年营收差 3000 万没达标，她在年会上没提这件事。",
         "effects": {"商界": -2, "金融": -1}},
        {"id": "q4_bonus", "tag": "季度·收官", "weight": 4,
         "text": "四季度分红方案：她拍板给核心团队发三个月奖金，自己那份减半。",
         "effects": {"商界": +3, "军方": +1}},
    ],
}

HISTORY_KEEP = 80


def _data_path():
    for base in ("/AstrBot/data/plugin_data/DeepSeek_Harness_Amo_Terminal",
                 "/data/astrbot/plugin_data/DeepSeek_Harness_Amo_Terminal",
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), ".data")):
        try:
            os.makedirs(base, exist_ok=True)
            return os.path.join(base, "world_state.json")
        except Exception:
            continue
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "world_state.json")


_PATH = _data_path()


def load():
    try:
        with open(_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        data = {}
    state = json.loads(json.dumps(DEFAULT_STATE))
    if isinstance(data, dict):
        for key in DEFAULT_STATE:
            if key in data:
                state[key] = data[key]
    for name in FACTIONS:
        state["factions"][name] = int(state["factions"].get(name, 50) or 50)
    return state


def save(state):
    try:
        tmp = _PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, _PATH)
        return True
    except Exception:
        return False


def _clamp(value):
    return int(max(0, min(100, round(value))))


def apply_effects(state, effects):
    for name, delta in (effects or {}).items():
        if name in state["factions"]:
            state["factions"][name] = _clamp(state["factions"][name] + int(delta))
    if effects:
        total = sum(int(v) for v in effects.values())
        state["reputation"] = _clamp(state["reputation"] + total / 2.0)


def rollover(state, today, rng=None):
    """推进到新的一天：抽 1~2 个事件，应用影响，写历史。"""
    rng = rng or random
    pool = list(EVENT_POOL)
    count = 1 if rng.random() < 0.55 else 2
    picked = []
    for _ in range(count):
        if not pool:
            break
        weights = [max(1, int(e.get("weight") or 1)) for e in pool]
        choice = rng.choices(pool, weights=weights, k=1)[0]
        pool.remove(choice)
        picked.append(choice)
    # 季度主线：每季头三天额外推进一条（和日常事件叠加，不进日常池）
    try:
        month = int(str(today)[5:7])
        day = int(str(today)[8:10])
    except Exception:
        month, day = 0, 0
    quarter = (month - 1) // 3 + 1 if month else 0   # 1/4/7/10 月 = 第 1/2/3/4 季
    if quarter in QUARTER_POOL and 1 <= day <= 3:
        options = QUARTER_POOL[quarter]
        quarter_pick = rng.choices(options, weights=[max(1, int(e.get("weight") or 1))
                                                     for e in options], k=1)[0]
        picked.append(quarter_pick)

    state["day"] = today
    state["today"] = [{"id": e["id"], "text": e["text"], "tag": e.get("tag", ""),
                       "effects": e.get("effects") or {}} for e in picked]
    for event in picked:
        apply_effects(state, event.get("effects"))
        state["history"].append({"date": today, "id": event["id"],
                                 "text": event["text"], "tag": event.get("tag", "")})
    state["history"] = state["history"][-HISTORY_KEEP:]
    state["log"].append({"date": today, "events": [e["id"] for e in picked]})
    state["log"] = state["log"][-30:]
    return state


def ensure_today(today, rng=None):
    """读→必要时推进→存，返回 (state, changed)。"""
    state = load()
    if str(state.get("day") or "") == str(today):
        return state, False
    state = rollover(state, today, rng=rng)
    save(state)
    return state, True


def today_block(state, limit_chars=200):
    rows = state.get("today") or []
    if not rows:
        return ""
    return "；".join(str(r.get("text") or "") for r in rows[:2])[:limit_chars]


def faction_block(state, keys=None):
    items = []
    for name in FACTIONS:
        if keys and name not in keys:
            continue
        items.append("%s %d" % (name, int(state["factions"].get(name, 50))))
    return "、".join(items)


def weak_factions(state, below=38):
    return [n for n in FACTIONS if int(state["factions"].get(n, 50)) < below]


def recent(state, n=3):
    rows = (state.get("history") or [])[-n:]
    return ["%s：%s" % (r.get("date"), r.get("text")) for r in rows]
