# -*- coding: utf-8 -*-
"""upup_schedule_bridge —— 终端自己的日程，用她的引擎产出的那一份。

她的日程引擎把结果落在 amo_forever.db 的 schedule 表：
    day / items(JSON 数组) / updated
items 每项：start、end、activity、place、zone、category、happened、event_id

这个桥只读不写：终端读它当「今天的日程事实」，读不到就用终端自己的骨架。
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

DB_PATH = os.environ.get(
    "AMO_UPUP_SCHEDULE_DB",
    "/AstrBot/data/plugin_data/Astrbot_amoupup_forever/amo_forever.db",
)


def _open() -> Optional[sqlite3.Connection]:
    if not os.path.exists(DB_PATH):
        return None
    try:
        return sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=3)
    except Exception:
        return None


def today_items(day: Optional[str] = None) -> List[Dict[str, Any]]:
    """今天（或指定日）的日程条目；读不到返回空表。"""
    day = day or datetime.now().strftime("%Y-%m-%d")
    con = _open()
    if con is None:
        return []
    try:
        row = con.execute("select items from schedule where day=?", (day,)).fetchone()
        if not row or not row[0]:
            return []
        items = json.loads(row[0])
        return items if isinstance(items, list) else []
    except Exception:
        return []
    finally:
        con.close()


def hour_slots(day: Optional[str] = None) -> Dict[int, str]:
    """折成 0–23 点每小时一句话，给事实注入用。"""
    slots: Dict[int, str] = {}
    for it in today_items(day):
        try:
            h = int(str(it.get("start", "0:00")).split(":")[0])
        except Exception:
            continue
        text = str(it.get("activity") or "").strip()
        place = str(it.get("place") or "").strip()
        if text:
            slots[h] = f"{text}（{place}）" if place else text
    return slots


def now_item(day: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """此刻落在哪一条。"""
    now = datetime.now().strftime("%H:%M")
    for it in today_items(day):
        if str(it.get("start", "")) <= now < str(it.get("end", "")):
            return it
    return None
