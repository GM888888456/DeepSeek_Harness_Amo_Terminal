# -*- coding: utf-8 -*-
"""Amo 终端 · 主动说话与仪式（ProactiveMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., ProactiveMixin, Star) 混入，self.* 照旧可用。

注意：常量/工具只在这里或 amo_core 里有一份，不要在 main.py 再定义一份。
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import inspect
import json
import math
import os
import random
import re
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone

try:
    from astrbot.api import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("amo_terminal")

from .shared import *



class ProactiveMixin:

    def _ritual_in_window(self, spec):
        try:
            start, end = str(spec).split("-", 1)
            return in_minute_range(minutes_now(), parse_hhmm(start), parse_hhmm(end))
        except Exception:
            return False

    def _ritual_umos(self, profile):
        """她能给你发问候的会话：QQ、飞书…按最近说过话排序。"""
        uid = str(profile.get("uid") or "")
        items = []
        try:
            data = self.db.kv_get("channels:%s" % uid, {}) or {}
        except Exception:
            data = {}
        if isinstance(data, dict):
            entries = [value for value in data.values() if isinstance(value, dict) and value.get("umo")]
            entries.sort(key=lambda value: -to_float(value.get("ts"), 0))
            for value in entries:
                umo = str(value.get("umo") or "")
                if umo and umo not in items:
                    items.append(umo)
        private_umo = str(profile.get("private_umo") or "")
        if private_umo and private_umo not in items:
            items.append(private_umo)
        return items

    def _recent_greeting(self, uid, minutes):
        """最近一次每日问候发在哪个平台、隔了多久（QQ/飞书算同一个人）。"""
        if not uid:
            return False
        try:
            data = self.db.kv_get("greeting_last:%s" % uid, {}) or {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            return False
        return _within_minutes(data.get("ts"), now_ts(), minutes)

    def _mark_greeting(self, uid, kind, umo):
        try:
            self.db.kv_set("greeting_last:%s" % str(uid), {
                "kind": str(kind),
                "umo": str(umo or ""),
                "ts": now_ts(),
            })
        except Exception:
            pass

    def _ritual_lookback_start(self, kind):
        """「今天这个时段已经聊过」的判定起点。

        不能只看最后 10 条 / 45 分钟：06:52 他说「早上好」、07:10 收尾，
        到 08:00 两道闸都过期，于是又问一遍「你醒了没」。所以按当天时段判。
        """
        now = now_ts()
        hours = getattr(self, "RITUAL_FROM_HOURS", None) or {"morning": 5, "lunch": 11, "goodnight": 21}
        hour = hours.get(str(kind))
        if hour is None:
            return now - max(5, self.cfg_int("ritual_skip_recent_minutes", 45)) * 60
        try:
            base = datetime.fromtimestamp(now).replace(
                hour=int(hour), minute=0, second=0, microsecond=0)
            start = base.timestamp()
            if start > now:
                # 凌晨 0-2 点的晚安算「昨天 21:00 起」；其他时段还没到点就从现在算
                start = start - 24 * 3600 if str(kind) == "goodnight" else now
            return start
        except Exception:
            return now - max(5, self.cfg_int("ritual_skip_recent_minutes", 45)) * 60

    def _ritual_judge_rows(self, rows, kind, since):
        """按已经取到的消息判断今天这个问候还发不发；QQ/飞书一起算。"""
        rows = [row for row in (rows or []) if to_float(row.get("created_at"), 0) >= since]
        rows.sort(key=lambda row: to_float(row.get("created_at"), 0))
        now = now_ts()
        recent_gap = max(5, self.cfg_int("ritual_skip_recent_minutes", 45)) * 60
        if rows:
            last_at = to_float(rows[-1].get("created_at"), 0)
            if last_at and now - last_at < recent_gap:
                return False
        if not self.cfg_bool("ritual_skip_if_greeted", True):
            return True
        # 只认「他」问候过：她自己那句「吃了没 / 晚安」多半是主动消息或追问，
        # 算进来会把当天的问候整段吃掉（午饭问候时有时无就是这么来的）。
        texts = [str(row.get("content") or "") for row in rows if str(row.get("role") or "") == "user"]
        # 不再只看最后 10 条：早上聊了几十句之后，最早那句「早」会被挤出去。
        joined = "\n".join(texts)
        if kind == "morning":
            return not bool(re.search(r"(?:^|\s)早(?:\s|$|[，,、!！。~～])|早安|早上好|早上好呀|我醒了|起床了|还没起来吗|醒了没", joined))
        if kind == "goodnight":
            return not bool(re.search(r"晚安|睡了|睡觉|先睡|去睡|早点休息", joined))
        if kind == "lunch":
            return not bool(re.search(r"午饭|中午吃|吃啥|吃什么|吃饭|吃了没|吃了吗", joined))
        return True

    def _ritual_he_is_around(self, rows, kind, since):
        """他今天露过面，就不再发「醒了没 / 还没起来吗」这种问候。

        2026-11-18：她 07:35 在私聊说「早，刚起来」、11:05 还在群里连着说话，
        11:00 的问候还是问了「醒没醒」。原因就是判定只看私聊、而且只认吃饭词。
        """
        mine = [row for row in (rows or []) if str(row.get("role") or "") == "user"]
        if not mine:
            return False
        now = now_ts()
        gap = max(5, self.cfg_int("ritual_skip_recent_minutes", 45)) * 60
        last_at = max(to_float(row.get("created_at"), 0) for row in mine)
        if str(kind) in ("morning", "lunch") and last_at and (now - last_at) < gap:
            # 他刚在群里/私聊说过话 = 他醒着、人还在，这时候问「醒了没」最伤人。
            return True
        if str(kind) == "morning":
            joined = "\n".join(str(row.get("content") or "") for row in mine)
            if self.RITUAL_MORNING_WORDS.search(joined):
                return True
        return False

    def _ritual_should_send(self, umos, kind):
        """同步版：只读本地缓存表/内存缓冲（拿不到记忆库时的兜底）。"""
        umos = list(umos) if isinstance(umos, (list, tuple, set)) else [umos]
        since = self._ritual_lookback_start(kind)
        rows = []
        for item in umos:
            try:
                rows.extend(self.db.messages_since_umo(item, since, 200))
            except Exception:
                try:
                    rows.extend(self._recent(item, 10))
                except Exception:
                    pass
        return self._ritual_judge_rows(rows, kind, since)

    async def _ritual_should_send_async(self, umos, kind, uid=""):
        """真正发送前用这个：消息真相在记忆库。

        插件本地的 messages 表最后一条停在 11-09（容量/迁移后不再写入），
        只看它会永远判成「今天还没聊过」，于是 8 点又问一遍「醒了没」。
        """
        since = self._ritual_lookback_start(kind)
        uid = str(uid or "")
        if uid:
            try:
                rows = await self._data_call(
                    "messages_since", self._data_bot_id(), uid, int(since), 400)
            except Exception as exc:
                logger.debug("[amo] 问候判定取聊天失败: %s" % exc)
                rows = []
            if rows:
                # 群聊内容不进私聊的话题判定（和里程碑同一口径），
                # 但「他在不在场」必须看全部会话：上一秒还在群里说话，
                # 就不能再问「醒了没」（2026-11-18 病象）。
                if not self._ritual_judge_rows(_private_rows(rows), kind, since):
                    return False
                return not self._ritual_he_is_around(rows, kind, since)
        return self._ritual_should_send(umos, kind)

    def _choose_proactive_kind(self, profile, snap, category=""):
        relation = profile.get("relation", "普通")
        rel = snap.get("feel_rel") or {}
        painful = (
            snap["health"]["sick"]
            or snap["period"]["pain"] >= 6
            or rel.get("sadness", 50.0) >= 62
            or rel.get("fatigue", 40.0) >= 72
        )
        if relation == "相恋" and painful and self.cfg_bool("proactive_comfort", True):
            return "comfort"
        activity = str((snap.get("activity") or {}).get("activity") or "")
        if category == "play" and ("游戏" in activity or "打游戏" in activity):
            return "game"
        if category == "meal":
            return "meal"
        if category in ("rest", "play"):
            return "slack"
        if category == "commute":
            return "offwork" if _now().hour >= 16 else "commute"
        if relation in ("熟识", "相恋") and random.random() < self.cfg_float("proactive_share_prob", 0.35):
            return "share"
        return "greet"

    def _proactive_user_just_talked(self, profile, now):
        """对方刚说过话就别主动插话。0 表示关闭这项检查。"""
        minutes = max(0, self.cfg_int("proactive_user_idle_minutes", 10))
        if not minutes:
            return False
        last_user_at = to_float(profile.get("last_seen"), 0)
        return bool(last_user_at) and (now - last_user_at) < minutes * 60

    def _proactive_forced_allowed(self, profile, now):
        """「日常关心」也要跟上次主动拉开间隔，避免重启后立刻又发。"""
        gap = max(1, self.cfg_int("proactive_forced_gap_minutes", 30)) * 60
        return (now - to_float(profile.get("last_proactive", 0))) >= gap

    def _forced_hour_key(self, uid):
        return "proactive_forced_hour_" + str(uid or "")

    def _forced_sent_this_hour(self, uid):
        """「日常关心」每小时只强制一次；存数据库，热重载/重启都不清空。"""
        mark = today_str() + ":" + str(_now().hour)
        try:
            return str(self.db.kv_get(self._forced_hour_key(uid), "")) == mark
        except Exception:
            return self._last_proactive_activity.get(str(uid)) == mark

    def _mark_forced_hour(self, uid):
        mark = today_str() + ":" + str(_now().hour)
        self._last_proactive_activity[str(uid)] = mark
        try:
            self.db.kv_set(self._forced_hour_key(uid), mark)
        except Exception:
            pass

    def _record_channel(self, uid, umo, platform):
        """记下这个人各平台的会话地址，供主动消息选边。"""
        if not uid or not umo:
            return
        try:
            key = "channels:%s" % uid
            data = self.db.kv_get(key, {}) or {}
            if not isinstance(data, dict):
                data = {}
            data[str(platform or "?")] = {"umo": str(umo), "ts": now_ts()}
            self.db.kv_set(key, data)
        except Exception as exc:
            logger.debug("[amo] 记录通道失败: %s" % exc)

    def _proactive_owner_ids(self, profiles=None):
        """主动私聊的对象：配了 proactive_owner_ids 只认名单；留空 = 管理员 + 相恋。"""
        raw = str(self.cfg_str("proactive_owner_ids", "") or "").replace("，", ",")
        ids = {item.strip() for item in raw.split(",") if item.strip()}
        if ids:
            return ids
        ids = {str(uid).strip() for uid in (self.admin_uids or set()) if str(uid).strip()}
        rows = profiles
        if rows is None:
            try:
                rows = self.db.proactive_profiles(limit=200)
            except Exception:
                rows = []
        for profile in rows or []:
            try:
                if str(profile.get("relation") or "") != "相恋":
                    continue
                uid = str(profile.get("uid") or "").strip()
            except Exception:
                continue
            if uid:
                ids.add(uid)
        return ids

    def _is_proactive_friend(self, profile):
        return str(profile.get("relation") or "普通") in ("熟识", "相恋")

    def _pending_key(self, uid):
        return "proactive_pending_" + str(uid)

    def _set_proactive_pending(self, uid, kind, text, umo=""):
        self.db.kv_set(self._pending_key(uid), {
            "sent_at": now_ts(), "kind": kind, "text": str(text or ""),
            # 记下真正发出去的会话：追问要回同一个平台，否则会「飞书问完、QQ 追」。
            "umo": str(umo or ""),
            "followup": False, "mood": False,
        })

    def _clear_proactive_pending(self, uid):
        pending = self.db.kv_get(self._pending_key(uid), None)
        if pending:
            self.db.kv_set(self._pending_key(uid), {})
            self.db.kv_set("proactive_ignored_" + str(uid), 0)

    def _pending_still_blocking(self, uid, profile, now) -> bool:
        pending = self.db.kv_get(self._pending_key(uid), None)
        if not isinstance(pending, dict) or not pending.get("sent_at"):
            return False
        sent_at = to_float(pending.get("sent_at"), 0)
        if not sent_at:
            return False
        # 他在这之后说过话（不管在哪个平台），就当她「已经看见她」了，不用再等
        try:
            if to_float(profile.get("last_seen"), 0) > sent_at + 60:
                self.db.kv_set(self._pending_key(uid), {})
                return False
        except Exception:
            pass
        if now - sent_at >= proactive_pending_block_seconds(self.cfg_int):
            return False
        return True

    def _depressed_active(self, uid):
        return to_float(self.db.kv_get("proactive_depressed_until_" + str(uid), 0), 0) > now_ts()

    def _set_depressed(self, uid):
        hours = max(1, self.cfg_int("proactive_depressed_hours", 24))
        self.db.kv_set("proactive_depressed_until_" + str(uid), now_ts() + hours * 3600)

    def _try_soothe(self, uid, text):
        if not self._depressed_active(uid):
            return
        words = ("抱抱", "亲亲", "哄", "对不起", "别难过", "喜欢你", "爱你", "怎么啦", "我在", "在呢", "乖")
        if any(word in str(text or "") for word in words):
            self.db.kv_set("proactive_depressed_until_" + str(uid), 0)
            self.db.kv_set("proactive_ignored_" + str(uid), 0)
            self.state.feel_bump({"sadness": -6, "joy": 4, "love": 3},
                                 weight=self.state.relation_feel_weight(uid))
            logger.debug("[amo] 抑郁状态被哄好: %s" % uid)

    def _followup_text(self, uid, kind, previous_text=""):
        """追问换着说法：同一句不连着出现，也别把刚问的问题再问一遍。"""
        templates = [t for t in (self.FOLLOWUP_TEMPLATES.get(str(kind)) or self.FOLLOWUP_TEMPLATES["greet"]) if t]
        if not templates:
            return "？怎么不理我了？"
        key = "proactive_followup_last_%s" % uid
        try:
            last = str(self.db.kv_get(key, "") or "")
        except Exception:
            last = ""
        pool = [t for t in templates if t != last]
        topics = self._followup_topics(previous_text)
        if topics:
            fresh = [t for t in pool if not (self._followup_topics(t) & topics)]
            pool = fresh
        if not pool:
            # 同一类话题的问句都问过了，就换成「怎么不理我」的催回，别再问一遍。
            pool = [t for t in self.FOLLOWUP_TEMPLATES["greet"] if t != last] or list(self.FOLLOWUP_TEMPLATES["greet"])
        text = random.choice(pool)
        try:
            self.db.kv_set(key, text)
        except Exception:
            pass
        return text


__all__ = [
    "ProactiveMixin",
]
