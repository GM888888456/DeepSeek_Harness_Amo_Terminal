# -*- coding: utf-8 -*-
"""全项目共用的枚举：日程分类、场景区域、一级时段、穿搭场景、风格。

（心情不在这里：2026-11-18 十维心情已删除，情绪只剩七情六欲 heartflow。）

为什么要有这个文件：这些值以前是散落各处的裸字符串（`"生气"`、`"sleep"`、
`"scenic"`…），拼错一个字母不会报错，只会**静默走错分支**——日程写成
`"Sleep"` 就永远不睡、生图拿到 `"景区"` 就找不到场景，表现出来就像"她失忆/"
"她幻视"。枚举把这类错误变成当场报错。

三条铁律：

1. **值必须和旧字符串完全一致**（`ActivityCategory.WORK.value == "work"`），
   数据库和配置里的老数据不用迁移；
2. 一律用 `str` 子类，并且 `__str__` 返回中文值——拼提示词、写日志时不会出现
   `MoodKey.ANGRY` 这种鬼东西；
3. 认不出的旧值**不抛异常**：`coerce()` 会退回给定的默认值，历史脏数据仍能读。

日程回固定骨架（12.7.0）后新增三组：`DayPart`（一级时段）、`OutfitScene`
（穿搭场景）、`StyleCamp`（汉服 / JK / 其他），并把 `SceneZone` 补全到骨架里
真实用到的取值（`city` / `station` / `bedroom`）。
"""

from __future__ import annotations

from enum import Enum


class _StrEnum(str, Enum):
    """值就是字符串，`str()` / f-string 也输出值本身。"""

    def __str__(self) -> str:  # pragma: no cover - 一行，行为由测试锁住
        return str(self.value)

    def __repr__(self) -> str:  # pragma: no cover
        return "<%s.%s: %r>" % (type(self).__name__, self.name, self.value)


class ActivityCategory(_StrEnum):
    SLEEP = "sleep"
    MEAL = "meal"
    LIFE = "life"
    WORK = "work"
    REST = "rest"
    PLAY = "play"
    COMMUTE = "commute"
    EXERCISE = "exercise"
    SOCIAL = "social"
    OTHER = "other"


class SceneZone(_StrEnum):
    """日程那一格在地图上属于什么场景（生图按它锁环境）。"""

    HOME = "home"
    BEDROOM = "bedroom"
    HOTEL = "hotel"
    SCENIC = "scenic"
    PARK = "park"
    STREET = "street"
    ROAD = "road"
    STATION = "station"
    CITY = "city"
    CAFE = "cafe"
    RESTAURANT = "restaurant"
    MALL = "mall"
    OFFICE = "office"
    WORK = "work"
    COMMUTE = "commute"


class TransitMode(_StrEnum):
    """出行方式（空串表示这一格不在路上，用 `coerce(..., default="")` 读）。"""

    DRIVE = "drive"
    TAXI = "taxi"
    TRAIN = "train"
    FLIGHT = "flight"
    BUS = "bus"
    WALK = "walk"


class DayPart(_StrEnum):
    """日程第一级的四个时段，标题就是这四个词（顺序即一天顺序）。"""

    LATE_NIGHT = "深夜"
    MORNING = "上午"
    NOON = "中午"
    EVENING = "晚上"


#: 一级时段的固定区间（左闭右开，单位分钟）。改顺序就改这一份，别在页面里写死。
DAY_PART_SPANS = (
    (DayPart.LATE_NIGHT, 0, 6 * 60),
    (DayPart.MORNING, 6 * 60, 12 * 60),
    (DayPart.NOON, 12 * 60, 18 * 60),
    (DayPart.EVENING, 18 * 60, 24 * 60),
)


class OutfitScene(_StrEnum):
    """穿搭引擎判定的场景（`outfit_engine.scene_of()` 的返回值）。"""

    SLEEP = "sleep"
    HOME = "home"
    WORK = "work"
    FORMAL = "formal"
    COMMUTE = "commute"
    OUT = "out"
    SPORT = "sport"
    BEACH = "beach"
    CASUAL = "casual"


class StyleCamp(_StrEnum):
    """衣柜里的风格阵营（市场也是按这三类上架的）。"""

    HANFU = "汉服"
    JK = "JK"
    OTHER = "其他"


def coerce(enum_cls, value, default=None):
    """把老字符串/新枚举都变成枚举成员；认不出就返回 default。

    读历史数据时用它，别让一个脏值把整条链路打挂。
    """
    if isinstance(value, enum_cls):
        return value
    text = str(value or "").strip()
    for item in enum_cls:
        if item.value == text:
            return item
    # 大小写不一致也算认出来（历史脏数据里常有 "Sleep" / "SCENIC"）
    lowered = text.lower()
    if lowered and text == text.strip():
        for item in enum_cls:
            if item.value.lower() == lowered:
                return item
    if default is not None:
        try:
            return enum_cls(default)
        except Exception:
            return None
    return None


def value_of(enum_cls, value, default=""):
    """取字符串值（写库、拼提示词用）。认不出就用 default 原文。"""
    item = coerce(enum_cls, value)
    return item.value if item is not None else str(default or "")


def day_part(minutes, default=None):
    """这一刻属于哪一段（0–1439 分钟）。越界按最近的一端算。"""
    try:
        minutes = int(minutes)
    except (TypeError, ValueError):
        return coerce(DayPart, default) if default is not None else None
    minutes = max(0, min(24 * 60 - 1, minutes))
    for part, start, end in DAY_PART_SPANS:
        if start <= minutes < end:
            return part
    return coerce(DayPart, default) if default is not None else None


#: 日程一格里允许出现的键（写库前用它收口，多余的旧键一律丢掉）
SCHEDULE_ITEM_KEYS = (
    "start", "end", "activity", "place", "zone", "category", "transit",
    "vehicle", "detail", "effects", "event", "spot", "soothe", "mood", "outfit",
)


def normalize_schedule_item(item, strict=False):
    """把日程一格收拾干净：分类/区域/出行方式归一到枚举值，去掉认不出的。

    `strict=True` 时，认不出的分类/区域**直接报错**——生成侧用它，能在写出
    「sleep 写成 Sleep 就永远不睡」之前就炸掉；读取侧用 `strict=False`，
    历史脏数据安静地退回空串。
    """
    if not isinstance(item, dict):
        return item
    row = dict(item)
    for key, enum_cls in (("category", ActivityCategory), ("zone", SceneZone)):
        raw = str(row.get(key) or "").strip()
        if not raw:
            continue
        fixed = value_of(enum_cls, raw, default="")
        if not fixed and strict:
            raise ValueError("日程里的 %s=%r 不在 %s 里" % (key, raw, enum_cls.__name__))
        row[key] = fixed
    # 出行方式只是给人看的一行字（骨架里有「在路上」这种中文），认不出就原样留着
    raw_transit = str(row.get("transit") or "").strip()
    if raw_transit:
        row["transit"] = value_of(TransitMode, raw_transit, default=raw_transit)
    return row
