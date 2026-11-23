"""日子类型：每天先掷一个「今天是哪种日子」，再按它生成日程。

移植自 dsh-daily-schedule 的 DAY_TYPES 设计（上班日 / 休息日 / 外出日 /
宅家日 / 加班日 / 摸鱼日），按权重随机，工作日与周末各抽各的池子。
"""
from __future__ import annotations

import random

DAY_TYPES = [
    {
        "id": "workday",
        "name": "上班日",
        "enabled": True,
        "weight": 5,
        "scope": "weekday",
        "guide": "常规上班日，两点一线：起床洗漱、通勤去上班，白天在单位干活，"
                 "中午吃饭，傍晚下班通勤回家，晚上吃饭、有一点自己的时间，然后睡觉。",
    },
    {
        "id": "restday",
        "name": "休息日",
        "enabled": True,
        "weight": 4,
        "scope": "weekend",
        "guide": "不上班，以待在家里为主：睡个懒觉，在家收拾、看书看剧，"
                 "出门散散步，去附近餐馆好好吃一顿，晚上在家放松。",
    },
    {
        "id": "outing",
        "name": "外出日",
        "enabled": True,
        "weight": 3,
        "scope": "weekend",
        "guide": "出门玩一整天：逛街、看展、去公园或海边、找好吃的店，"
                 "傍晚或晚上才回家，回家时有点累但很满足。"
                 "这一天大部分时间都在外面，不在家也不在单位。",
    },
    {
        "id": "homebody",
        "name": "宅家日",
        "enabled": True,
        "weight": 1,
        "scope": "any",
        "guide": "哪儿也不想去，几乎一整天窝在家：睡到中午，点外卖，"
                 "追剧看书，作息有点乱，晚上反而精神。",
    },
    {
        "id": "overtime",
        "name": "加班日",
        "enabled": True,
        "weight": 1,
        "scope": "weekday",
        "guide": "活多的一天：照常上班，但一直忙到很晚，午饭晚饭都随便对付，"
                 "回家已经很累，倒头就睡。",
    },
    {
        "id": "slacking",
        "name": "摸鱼日",
        "enabled": True,
        "weight": 1,
        "scope": "weekday",
        "guide": "名义上在上班，实际上一直找机会摸鱼：开小差、刷手机、"
                 "去茶水间找零食，但下班前会把要紧的事赶完。",
    },
]


def normalize_day_types(raw) -> list[dict]:
    src = raw if isinstance(raw, list) and raw else DAY_TYPES
    out, seen = [], set()
    for item in src[:30]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()[:20]
        ident = str(item.get("id") or name).strip()[:32]
        if not name or ident in seen:
            continue
        seen.add(ident)
        try:
            weight = max(0.0, min(50.0, float(item.get("weight", 1) or 0)))
        except Exception:
            weight = 1.0
        scope = str(item.get("scope") or "any")
        if scope not in ("weekday", "weekend", "any"):
            scope = "any"
        out.append({
            "id": ident,
            "name": name,
            "enabled": bool(item.get("enabled", True)),
            "weight": weight,
            "scope": scope,
            "guide": str(item.get("guide") or "").strip()[:300],
        })
    return out or list(DAY_TYPES)


#: 这些职业不上班：周中也不排上班日，日程按休息/宅家/外出走
NON_WORK_OCCUPATIONS = ("家庭主妇", "全职太太", "主妇", "家庭煮夫", "退休", "无业",
                        "待业", "全职女儿", "全职妈妈")

#: 这些职业周末也可能上班/轮班（职业来自世界观，世界观由人格识别出来）
WEEKEND_WORK_WORDS = ("护士", "医生", "医师", "医护", "牙医", "药师", "店员", "服务员",
                      "厨师", "咖啡师", "收银", "销售", "客服", "司机", "保安", "警察",
                      "消防", "值班", "轮班", "倒班", "零售", "餐饮", "酒店", "前台",
                      "快递", "外卖", "主播", "空乘")


def _world_text(world) -> str:
    world = world or {}
    return (str(world.get("occupation") or "") + " " + str(world.get("workplace") or "")).lower()


def has_job(world) -> bool:
    """有没有要出门的营生；没有就按不上班排日程（不是所有 Amo 都要上班）。"""
    text = _world_text(world).strip()
    if not text:
        return True
    return not any(word in text for word in NON_WORK_OCCUPATIONS)


def works_on_weekend(world) -> bool:
    return any(word in _world_text(world) for word in WEEKEND_WORK_WORDS)


#: 日子类型分池：日历是工作日只抽上班类，是休息日只抽休息类。
WORK_DAY_IDS = frozenset({"workday", "overtime", "slacking"})
REST_DAY_IDS = frozenset({"restday", "outing", "homebody"})


def day_type_kind(item) -> str:
    """这个日子类型属于「work / rest / both」哪一池。

    先按 id 认（配置里存的 scope 可能还是旧的 "any"，例如宅家日），
    认不出来再看 scope：weekday=上班类、weekend=休息类、any=两池都行。
    """
    ident = str((item or {}).get("id") or "").strip().lower()
    if ident in WORK_DAY_IDS:
        return "work"
    if ident in REST_DAY_IDS:
        return "rest"
    scope = str((item or {}).get("scope") or "any").strip().lower()
    if scope == "weekday":
        return "work"
    if scope == "weekend":
        return "rest"
    return "both"


def pick_day_type(day_types: list[dict], is_weekend: bool, seed: str, world=None,
                  work_day=None) -> dict:
    """按日历 + 职业抽一个今天的类型；同一个种子结果稳定。

    2026-11-23 用户定：**日历说了算**——日历是工作日就排上班类（上班日/加班日/
    摸鱼日），日历是休息日就排休息类（休息日/外出日/宅家日），两边不许串台；
    「宅家日」这类休息型日子类型再也不能在工作日被抽到（那正是「日程在公司上班、
    照片却在家里」的来源）。

    2026-11-21 她说「并不是所有的 Amo 都需要上班，日程根据职业来定」：
    家庭主妇/退休/无业，日历再是工作日也不排上班日。

    ``work_day`` 由 day_meta() 给出；不传时按 ``is_weekend`` 兜底（老调用点不变）。
    """
    weekend = bool(is_weekend)
    working = has_job(world)
    work = bool(work_day if work_day is not None else (working and not weekend)) and working
    pool = []
    for item in day_types:
        if not item.get("enabled", True):
            continue
        if float(item.get("weight") or 0) <= 0:
            continue
        kind = day_type_kind(item)
        if kind != "both" and (kind == "work") != work:
            continue
        pool.append(item)
    if not pool:
        if work:
            return {"id": "workday", "name": "上班日", "guide": ""}
        return {"id": "restday", "name": "休息日", "guide": ""}
    total = sum(float(x["weight"]) for x in pool)
    rng = random.Random(seed)
    point = rng.random() * total
    acc = 0.0
    for item in pool:
        acc += float(item["weight"])
        if point <= acc:
            return item
    return pool[-1]
