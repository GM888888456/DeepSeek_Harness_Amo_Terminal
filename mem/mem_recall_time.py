# -*- coding: utf-8 -*-
"""时间路召回：和「枚举/关键词」那一路并行的第二条检索通道。

为什么要有这一路
----------------
原来的 recall 只有一条路：关键词（BM25/trigram）+ 语义向量，再乘一个很弱的
新鲜度。这带来两个真实病象：

1. **kind 枚举只能管「能不能进池」**。`photo_record`、`daily_digest` 这些种类
   决定生命周期（7 天降权 / 14 天删除），但同类里「今天下午那张」和「十天前那张」
   权重几乎一样；
2. **用户问「刚才」「昨天下午」「你还记得早上吗」时，关键词根本命中不了**。
   「昨天」不在记忆正文里，「刚拍的照片」也不一定有「刚」这个字，于是候选池里
   全是旧事，模型就拿旧事回答现在。

所以这里做第二路：**只看时间戳，不看关键词**，按「此刻前后两小时 / 近三天 /
近一周 / 更早」几个时间桶取候选，带上桶权重交给上层合并。两路结果按 id 去重，
同一段记忆被两路都选中时权重相加（既是这段时间的事、又对得上话，最该被想起来）。

设计取舍
--------
- **不改表结构**：`created_at` 本来就在 `memories` 表里，加列只会让老库迁移变复杂。
  时间信息在召回时算，喂给模型的正文里只补一个人能读懂的相对时间。
- **不碰生命周期**：这里只是「多取几条候选」，淘汰仍然走 lifecycle。
- **可关**：`recall_time_enabled` 设 false 就完全退回原来的单路召回。
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

try:  # 业务时区（默认 Asia/Shanghai），容器系统时区常是 UTC，两者不能混用
    from . import clock as _clock
except ImportError:  # pragma: no cover - 按文件直接加载时
    try:
        import clock as _clock  # type: ignore
    except ImportError:
        _clock = None  # type: ignore

#: 时间桶：(名字, 上界秒数偏移, 桶权重)。偏移相对「现在」，越小越贴近此刻。
TIME_BUCKETS: Tuple[Tuple[str, float, float], ...] = (
    ("now", 7200.0, 1.00),            # 此刻前后两小时
    ("recent", 3 * 86400.0, 0.70),    # 近三天
    ("week", 7 * 86400.0, 0.45),      # 近一周
    ("old", 0.0, 0.20),               # 更早的：只做兜底，权重压到最低
)

#: 「此刻前后」这个桶的宽度（秒）。聊天里「刚才」指的是半小时到几小时，
#: 两小时足够覆盖一次连续对话，又不至于把上午的事算成刚刚。
NEAR_WINDOW = 2 * 3600.0

#: 问句里出现这些说法时，时间路才真正参与排序：这时候「什么时候」比「说了什么」重要。
TIME_WORD_HINTS = (
    "刚才", "刚刚", "刚说", "刚发", "刚拍", "刚聊",
    "今天", "今日", "今早", "今天早上", "今天中午", "今天下午", "今天晚上", "今晚",
    "昨天", "昨日", "昨晚", "昨天晚上", "昨天下午", "昨天中午",
    "前天", "大前天", "上周", "上个星期", "上礼拜", "这周", "这个星期",
    "上次", "那次", "之前", "以前", "最早", "第一次", "最后一次",
    "最近", "这几天", "这两天", "那会儿", "那时候", "当年", "去年",
)

#: 这些词说明问的是「刚刚发生的事」，此时 near 权重压过一切。
NEAR_WORD_HINTS = ("刚才", "刚刚", "刚说", "刚发", "刚拍", "这会儿", "现在", "眼下")

#: 能**单独**当命中证据的时间说法：只有「刚刚发生的」这一档。
#:
#: 为什么只有这一档：
#: - 「今天」「最近」是纯语境词（「你今天心情怎么样」毫无指向），拿它当证据会把旧事全捞出来；
#: - 「上次」「那次」「以前」是相对指代，没有绝对时间位置，必须靠内容去配对，
#:   否则「上次说的小挂件」会把库里任何一条刚写的记忆都捞上来；
#: - 「昨天 / 前天 / 上周 / 某月某日」有确定位置，由 recall 里的 span + date_hit 单独处理，
#:   不需要走这条。
#: 所以这里只认「刚刚」：时间本身就能证明「他问的就是这条」。
EVIDENCE_TIME_WORDS = (
    "刚才", "刚刚", "刚说", "刚发", "刚拍", "刚聊", "这会儿",
)


def has_time_word(text: str) -> bool:
    """这句里有没有时间说法。没有的话时间路只做轻量补位，不抢相关性。"""
    body = str(text or "")
    return any(word in body for word in TIME_WORD_HINTS)


def has_evidence_time_word(text: str) -> bool:
    """这句里的时间说法能不能当「命中证据」。

    和 `has_time_word` 的区别：`has_time_word` 只用来决定「要不要启动时间路」，
    泛指词（今天/最近）也算；这里是决定「能不能只凭时间就把一条记忆捞出来」，
    只认指着具体某件事的说法。
    """
    body = str(text or "")
    return any(word in body for word in EVIDENCE_TIME_WORDS)


def wants_near(text: str) -> bool:
    """是不是在问「刚刚」——这种问句只该看最近两小时。"""
    body = str(text or "")
    return any(word in body for word in NEAR_WORD_HINTS)


def bucket_weight(name: str) -> float:
    for key, _span, weight in TIME_BUCKETS:
        if key == name:
            return weight
    return 0.2


def humanize_age(created_at: Any, now: Optional[float] = None) -> str:
    """把时间戳说成人话：「刚刚」「23 分钟前」「今天早上」「昨天下午」「3 天前」。

    比直接给「11-17 09:15」有用：模型对相对时间的理解远好于绝对时间，
    而写进记忆正文的又必须是相对说法（绝对时间会让它算错日子）。
    """
    try:
        stamp = float(created_at or 0)
    except (TypeError, ValueError):
        return ""
    if stamp <= 0:
        return ""
    now = float(now if now is not None else time.time())
    delta = now - stamp
    if delta < 90:
        return "刚刚"
    if delta < 3600:
        return "%d 分钟前" % max(1, int(delta // 60))
    # 一定按业务时区算，不能用系统时区：容器里 system 是 UTC，
    # 北京时间 09:15 会被算成凌晨 01:15，「今天早上」就成了「今天凌晨」，
    # 「今天/昨天」的分界也会整体错 8 小时。
    try:
        if _clock is not None:
            when = _clock.from_timestamp(stamp)
            today = _clock.from_timestamp(now).date()
        else:
            when = datetime.fromtimestamp(stamp)
            today = datetime.fromtimestamp(now).date()
    except (ValueError, OSError, OverflowError):
        return "%d 小时前" % max(1, int(delta // 3600))
    days = (today - when.date()).days
    hour = when.hour
    if hour < 5:
        part = "凌晨"
    elif hour < 8:
        part = "早上"
    elif hour < 11:
        part = "上午"
    elif hour < 13:
        part = "中午"
    elif hour < 18:
        part = "下午"
    elif hour < 23:
        part = "晚上"
    else:
        part = "深夜"
    if days <= 0:
        return "今天" + part
    if days == 1:
        return "昨天" + part
    if days == 2:
        return "前天" + part
    if days < 7:
        return "%d 天前" % days
    if days < 30:
        return "%d 周前" % max(1, int(days // 7))
    if days < 365:
        return "%d 个月前" % max(1, int(days // 30))
    return "%d 年前" % max(1, int(days // 365))


def time_bucket_of(created_at: Any, now: Optional[float] = None) -> str:
    """这条记忆落在哪个时间桶。和 TIME_BUCKETS 的优先级一致。"""
    try:
        stamp = float(created_at or 0)
    except (TypeError, ValueError):
        return "old"
    if stamp <= 0:
        return "old"
    now = float(now if now is not None else time.time())
    delta = now - stamp
    if delta <= NEAR_WINDOW:
        return "now"
    if delta <= 3 * 86400.0:
        return "recent"
    if delta <= 7 * 86400.0:
        return "week"
    return "old"


def time_score(created_at: Any, now: Optional[float] = None,
               near: bool = False) -> float:
    """时间路的原始分（0～1）。

    - `near=True`（他在问「刚刚」）：只有 NEAR_WINDOW 内得高分，其余迅速衰减，
      避免「他刚说完难受，她去翻一周前的旧事」；
    - 否则按桶权重给分，桶内再按距离线性衰减，保证同桶里近的排前面。
    """
    bucket = time_bucket_of(created_at, now)
    base = bucket_weight(bucket)
    try:
        stamp = float(created_at or 0)
    except (TypeError, ValueError):
        return 0.0
    if stamp <= 0:
        return 0.0
    now = float(now if now is not None else time.time())
    age = max(0.0, now - stamp)
    if near:
        if age <= NEAR_WINDOW:
            # 越近越高：0 秒→1.0，两小时→0.6
            return 1.0 - 0.4 * (age / NEAR_WINDOW)
        # 超过两小时：按「多久以前」快速衰减，一天以外基本出局
        return max(0.0, 0.55 * (1.0 - min(1.0, (age - NEAR_WINDOW) / (86400.0 - NEAR_WINDOW))))
    if bucket == "now":
        return base * (1.0 - 0.25 * (age / max(1.0, 86400.0)))
    return base


def merge_two_ways(keyword_rows: List[Dict[str, Any]],
                   time_rows: List[Dict[str, Any]],
                   now: Optional[float] = None,
                   near: bool = False,
                   bonus: float = 0.35) -> List[Dict[str, Any]]:
    """把「关键词路」和「时间路」的候选合并去重。

    - 只在一路出现的：拿那一路的分；
    - 两路都出现的：`kw + time * bonus`，封顶 1.0——两路都说相关的记忆
      应该排在只有一路支持的记忆前面。
    """
    merged: Dict[Any, Dict[str, Any]] = {}
    for row in keyword_rows or []:
        key = row.get("id")
        if key is None:
            continue
        item = dict(row)
        item["kw_score"] = float(item.get("kw_score") or 1.0)
        item["time_score"] = 0.0
        item["engines"] = ["keyword"]
        merged[key] = item
    for row in time_rows or []:
        key = row.get("id")
        if key is None:
            continue
        score = time_score(row.get("created_at"), now, near=near)
        if key in merged:
            merged[key]["time_score"] = score
            if "time" not in merged[key]["engines"]:
                merged[key]["engines"].append("time")
        else:
            item = dict(row)
            item["kw_score"] = 0.0
            item["time_score"] = score
            item["engines"] = ["time"]
            merged[key] = item
    out = []
    for item in merged.values():
        item["dual_score"] = min(1.0, item["kw_score"] + item["time_score"] * float(bonus))
        out.append(item)
    out.sort(key=lambda x: x["dual_score"], reverse=True)
    return out
