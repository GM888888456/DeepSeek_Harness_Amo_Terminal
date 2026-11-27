# -*- coding: utf-8 -*-
"""宅内人事与「她不该自己干」的那几件事（日程/文案用）。

数据来源只有两处，不许自己编：

- `story/lineage.py` 的 `STAFF`：司机老周（开宝马 A8·贵A·00008）、厨师郑师傅、帮厨李姐、
  管家陈姨（陈慧兰）、女仆小满/桐桐/小雅/小亦……
- 人格档案的「资产」字段：车型与车牌以档案原文为准。

为什么需要：日程的吃饭/通勤文案库是通用库（「下楼吃牛肉粉」「点外卖」），
放在她身上就是错的——庄园里有厨师和帮厨，出门有老周开车。
2026-11-28 用户口径：在家吃饭该是厨房做，不是下楼吃；出门该是老周开。
"""

from __future__ import annotations

import re

#: 家里/宅内的判定词（用于决定「在家吃」还是「在外面吃」）
HOME_WORDS = ("庄园", "别墅", "家里", "家中", "自家", "宅")

#: 家里吃饭：厨房做，不下楼、不点外卖。按钟点分早/午/晚。
HOME_BREAKFAST = (
    "郑师傅做了小锅米粉，配一碟糟辣椒",
    "在餐厅吃李姐现包的抄手",
    "陈姨让厨房熬了粥，配两样小菜",
    "桐桐把早茶端到露台上，她慢慢吃",
    "厨房蒸了糯米饭，配自家腌的酸菜",
)
HOME_LUNCH = (
    "回庄园吃，郑师傅做了三菜一汤",
    "让厨房做了酸汤鱼，配一碗米饭",
    "在家吃，李姐煮了豆米火锅",
    "陈姨安排好午饭，她在餐厅吃了半小时",
    "厨房做了折耳根炒腊肉，她吃了两碗饭",
)
HOME_DINNER = (
    "厨房炖了汤，她喝了半碗",
    "在家吃，郑师傅做了几个小菜",
    "让厨房煮了碗面，配一小碟咸菜",
    "在餐厅吃，桐桐温热了黄酒",
    "厨房做了酸菜豆米，她吃得很慢",
)

#: 通勤（有车且有人开）：她坐后排，不开车
COMMUTE_BY_DRIVER = (
    "老周开车送她去集团，她坐后排看文件",
    "老周绕开了最堵那条路",
    "老周把车停进地下车库，她直接从专梯上楼",
    "路上被加塞，老周按了两下喇叭",
    "她在后排改完一份邮件，老周正好把车停到楼下",
)


def _lineage():
    try:
        from ..story import lineage as _lin
    except Exception:
        try:
            from story import lineage as _lin  # type: ignore
        except Exception:
            return None
    return _lin


def staff_title(role, default=""):
    """按角色取宅内称呼（厨师 → 郑师傅）。"""
    lin = _lineage()
    if lin is None:
        return default
    for person in getattr(lin, "STAFF", ()) or ():
        if str(person.get("role") or "") == str(role or ""):
            return str(person.get("title") or person.get("name") or default)
    return default


def driver_title():
    return staff_title("司机", "老周")


def cook_title():
    return staff_title("厨师", "郑师傅")


def helper_title():
    return staff_title("帮厨", "李姐")


def housekeeper_title():
    return staff_title("管家", "陈姨")


def is_home(place) -> bool:
    """地点是不是家里/庄院内。"""
    text = str(place or "")
    return any(word in text for word in HOME_WORDS)


def car_label(archive=None) -> str:
    """从人格档案的资产里取车型+车牌（原文）；取不到返回空串，绝不编。"""
    text = ""
    try:
        text = archive.field("资产") if archive is not None else ""
    except Exception:
        text = ""
    if not text:
        return ""
    # 例：宝马A8·贵A·00008（全款）
    match = re.search(r"([\u4e00-\u9fa5A-Za-z0-9]{2,10})[·\-]?\s*(贵[A-Z]·[0-9A-Z]{4,6})", text)
    if match:
        return "%s·%s" % (match.group(1), match.group(2))
    match = re.search(r"([\u4e00-\u9fa5]{2,6}\s?[A-Z0-9]{1,4})（全款", text)
    return match.group(1) if match else ""


def meal_bank(hour: int, home: bool = False) -> tuple:
    """该用哪个吃饭库：(条目, 是否家里)。在家就只用厨房做的那些。"""
    if not home:
        return (), False
    if hour < 10:
        return HOME_BREAKFAST, True
    if 10 <= hour < 15:
        return HOME_LUNCH, True
    return HOME_DINNER, True


def commute_bank() -> tuple:
    """有人开车的通勤库（她坐后排）。"""
    return COMMUTE_BY_DRIVER


__all__ = ["HOME_WORDS", "HOME_BREAKFAST", "HOME_LUNCH", "HOME_DINNER", "COMMUTE_BY_DRIVER",
           "staff_title", "driver_title", "cook_title", "helper_title", "housekeeper_title",
           "is_home", "car_label", "meal_bank", "commute_bank"]
