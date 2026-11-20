# -*- coding: utf-8 -*-
"""Amo 终端 · 在场感与出行（PresenceMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., PresenceMixin, Star) 混入，self.* 照旧可用。

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

_HIS_SLEEP_RE = re.compile(r"要睡|去睡|睡觉|睡了|想睡|困了|困死|眯一会|眯一会儿|躺一会|躺一会儿|晚安|闭眼")
_HIS_AWAY_RE = re.compile(r"在外地|出差|不在家|回不去|放假|休假|年假|请假|不上班|不用上班|明天.{0,6}早起")
def proactive_pending_block_seconds(cfg_int) -> float:
    """发过主动消息后，多久之内不再发下一条。

    原来是写死 6 小时：他只要没在私聊回一句，她半天都不能再开口；
    实际上他在群里聊得火热也算「人在」，这条要跟着放宽。
    """
    try:
        minutes = max(0, int(cfg_int("proactive_pending_max_minutes", 120)))
    except Exception:
        minutes = 120
    return minutes * 60


class PresenceMixin:

    async def _start_solo_trip(self, uid, offer):
        """确认出发：>=22 点明天走，否则现在就走。"""
        city = str(offer.get("city") or "").strip()
        spots = [x for x in (offer.get("spot_rows") or []) if isinstance(x, dict)]
        if not city:
            self.db.kv_set("wander_offer", {})
            return ""
        tomorrow = _now().hour >= 22
        start = (_now().date() + timedelta(days=1)) if tomorrow else _now().date()
        days = max(1, min(3, _wander_trip_days(random)))
        if days == 1 and not tomorrow and _now().hour >= 17:
            days = 2  # 傍晚才走，别刚出门就回家
        return_day = start + timedelta(days=days - 1)
        return_hour = 21 if days == 1 else 12
        hit = self._city_lookup(city)
        trip = {
            "city": city,
            "id": str((hit or {}).get("id") or ""),
            "day": start.isoformat(),
            "days": days,
            "return_day": return_day.isoformat(),
            "return_hour": return_hour,
            "spots": [str(x.get("name") or "") for x in spots][:4],
            "phase": "planned",
        }
        self.db.kv_set("wander_trip", trip)
        self.db.kv_set("wander_offer", {})
        try:
            content = "她 %s 一个人去 %s 旅游（他同意了，玩 %d 天）" % (start.isoformat(), city, days)
            if not await self._write_memory_checked(uid, content, "event", 1):
                logger.warning("[amo] 旅游记忆没写进去")
        except Exception as exc:
            logger.warning("[amo] 旅游记忆写入失败: %s" % exc)
        try:
            log = self.db.kv_get("travel_log", []) or []
            if not isinstance(log, list):
                log = []
            log.append({
                "day": start.isoformat(), "hour": "%02d:00" % _now().hour,
                "city": city, "solo": True,
            })
            self.db.kv_set("travel_log", log[-10:])
        except Exception:
            pass
        if not tomorrow:
            if hit:
                try:
                    await self._switch_weather_city(hit)
                except Exception as exc:
                    logger.warning("[amo] 旅游天气切换失败: %s" % exc)
            try:
                self.state.apply_travel_overlay(city)
            except Exception as exc:
                logger.warning("[amo] 旅游日程失败: %s" % exc)
            trip["phase"] = "applied"
            self.db.kv_set("wander_trip", trip)
        agree = _wander_solo_agree_text(city, random)
        plan = _wander_plan_text(city, spots, tomorrow, random)
        when = "明天" if tomorrow else "现在"
        back_text = "第 %d 天中午回来" % days if days > 1 else "当晚回来"
        return (
            "【出发】他同意了：你" + when + "去 " + city + " 旅游（一个人），玩 %d 天，%s。"
            % (days, back_text) + "先照这个说一句：" + agree + " 再说安排：" + plan
            + " 别说成跟他一起；白天自己去景点，晚上住酒店。"
        )

    async def _end_solo_trip(self, uid, reason=""):
        """结束 solo 旅游：清状态、记回来、天气换回他在的城市、日程回家。"""
        trip = self.db.kv_get("wander_trip", {}) or {}
        if not isinstance(trip, dict) or not trip.get("city"):
            return
        city = str(trip["city"])
        self.db.kv_set("wander_trip", {})
        try:
            content = "她 %s 从 %s 旅游回来了" % (today_str(), city)
            if not await self._write_memory_checked(uid, content, "event", 1):
                logger.warning("[amo] 回来记忆没写进去")
        except Exception as exc:
            logger.warning("[amo] 回来记忆写入失败: %s" % exc)
        try:
            log = self.db.kv_get("travel_log", []) or []
            if not isinstance(log, list):
                log = []
            log.append({
                "day": today_str(), "hour": "%02d:00" % _now().hour,
                "city": city, "solo": True, "back": True,
            })
            self.db.kv_set("travel_log", log[-10:])
        except Exception:
            pass
        his = str(self.db.kv_get("his_city", "") or "").strip() or _CITY_DEFAULT
        hit = self._city_lookup(his)
        if hit:
            try:
                await self._switch_weather_city(hit)
            except Exception as exc:
                logger.warning("[amo] 回来天气切换失败: %s" % exc)
        try:
            self.state.apply_travel_overlay(his)
        except Exception as exc:
            logger.warning("[amo] 回来日程失败: %s" % exc)

    async def _start_follow_trip(self, uid, offer):
        """同意跟去：定出发日/出发时间，当天或次日先坐 2 小时车再玩。"""
        city = str(offer.get("city") or "").strip()
        if not city:
            self.db.kv_set("follow_offer", {})
            return ""
        tomorrow = bool(offer.get("tomorrow"))
        start = (_now().date() + timedelta(days=1)) if tomorrow else _now().date()
        start_hour = 9 if tomorrow else _now().hour
        spots = []
        try:
            spots = _city_pick_spots(self.scenic_spots(), city, start.isoformat())
        except Exception:
            spots = []
        trip = {
            "city": city,
            "id": str(offer.get("id") or ""),
            "from": str(self.db.kv_get("his_city", "") or ""),
            "start_day": start.isoformat(),
            "start_hour": start_hour,
            "spots": [dict(x) for x in spots][:4],
            "phase": "journey",
        }
        self.db.kv_set("travel", trip)
        self.db.kv_set("follow_offer", {})
        self.db.kv_set("follow_declined", {})
        try:
            content = "她 %s 坐车去 %s 陪他（路上约 2 小时）" % (start.isoformat(), city)
            if not await self._write_memory_checked(uid, content, "event", 1):
                logger.warning("[amo] 跟随记忆没写进去")
        except Exception as exc:
            logger.warning("[amo] 跟随记忆写入失败: %s" % exc)
        try:
            log = self.db.kv_get("travel_log", []) or []
            if not isinstance(log, list):
                log = []
            log.append({"day": start.isoformat(), "hour": "%02d:00" % start_hour,
                        "city": city, "journey": True})
            self.db.kv_set("travel_log", log[-10:])
        except Exception:
            pass
        if not tomorrow:
            self.db.kv_set("his_city", city)
            hit = self._city_lookup(city)
            if hit:
                try:
                    await self._switch_weather_city(hit)
                except Exception as exc:
                    logger.warning("[amo] 跟随天气切换失败: %s" % exc)
            try:
                self.state.apply_follow_start(city, start_hour, spots, keep_past=True)
            except Exception as exc:
                logger.warning("[amo] 跟随日程失败: %s" % exc)
            trip["phase"] = "touring"
            self.db.kv_set("travel", trip)
        plan = _wander_follow_agree_text(city, random)
        when = "明天一早" if tomorrow else "现在"
        return (
            "【出发】他同意了：你" + when + "出发去 " + city + " 陪他，路上约 2 小时，到了再找他。"
            "照这个意思说一句（别报公司/上班）：" + plan
        )

    async def _end_follow_trip(self, uid):
        """结束跟随：回家、恢复城市/天气/日程、写回来记忆。"""
        trip = self.db.kv_get("travel", {}) or {}
        city = str(trip.get("city") or "") if isinstance(trip, dict) else ""
        self.db.kv_set("travel", {})
        home = _CITY_DEFAULT
        self.db.kv_set("his_city", home)
        self.db.kv_set("he_city", home)
        hit = self._city_lookup(home)
        if hit:
            try:
                await self._switch_weather_city(hit)
            except Exception:
                pass
        try:
            self.state.apply_travel_overlay(home)
        except Exception:
            pass
        try:
            content = "她 %s 从 %s 回来了" % (today_str(), city)
            await self._write_memory_checked(uid, content, "event", 1)
        except Exception:
            pass
        try:
            log = self.db.kv_get("travel_log", []) or []
            if isinstance(log, list):
                log.append({
                    "day": today_str(), "hour": "%02d:00" % _now().hour,
                    "city": city, "back": True,
                })
                self.db.kv_set("travel_log", log[-10:])
        except Exception:
            pass

    def _track_his_place(self, text):
        """记住他人在哪：说了城市就记城市，只说「在外地/出差」就记「外地」。

        以前只有 `_city_detect`：他一句「我在外地」认不出城市，于是什么都不记，
        她那边就当他在家——然后说「你在家」「你慢点开」，全错。
        """
        body = str(text or "").strip()
        if not body:
            return
        if not any(word in body for word in
                   ("我在", "我到", "我回", "人还", "出差", "外地", "在温州", "在杭州")):
            return
        if any(word in body for word in self.HE_HOME_WORDS):
            self.db.kv_set("he_place", {"ts": now_ts(), "city": _CITY_DEFAULT, "away": False})
            return
        name = ""
        try:
            hit = _city_detect(body) if _city_detect is not None else None
            name = str((hit or {}).get("name") or "").strip()
        except Exception:
            name = ""
        if name:
            self.db.kv_set("he_place", {"ts": now_ts(), "city": name,
                                        "away": name != _CITY_DEFAULT})
            logger.info("[amo] 记住他在哪：%s（%s）" % (name, "外地" if name != _CITY_DEFAULT else "同城"))
            return
        if any(word in body for word in self.HE_AWAY_WORDS):
            self.db.kv_set("he_place", {"ts": now_ts(), "city": "", "away": True})
            logger.info("[amo] 记住他在哪：外地（没细说城市）")

    def _his_presence_line(self, uid, umo="") -> str:
        """他已经醒着/刚说过话时，把这件事当硬事实给她，堵住「醒了没」。

        返回空串表示「今天没证据他还醒着」，调用方据此决定要不要拦。
        """
        uid = str(uid or "")
        if not uid:
            return ""
        try:
            profile = self.db.get_profile(uid)
        except Exception:
            profile = {}
        last = to_float(profile.get("last_seen"), 0)
        if not last:
            return ""
        age = now_ts() - last
        if age < 0 or age > 12 * 3600:
            return ""
        stamp = (_now() - timedelta(seconds=age)).strftime("%H:%M")
        if age <= 90 * 60:
            return (
                "【他已经醒着】他 %s 刚说过话（%d 分钟前）。"
                "绝对不要问「醒了没 / 醒没醒 / 起来没 / 还没起来吗 / 在吗 / 在不在 / 人呢」，"
                "也不要问他是不是在忙；直接把你要说的那件事说出来。"
                % (stamp, max(1, int(age // 60)))
            )
        return (
            "【他已经醒着】他今天 %s 说过话。"
            "不要问「醒了没 / 起来没 / 在不在」，直接说事。" % stamp
        )

    def _his_state_flags(self, umo) -> dict:
        """从最近聊天里读他刚说的话：在睡？不在本地？（只给事实，不做判断）"""
        flags = {"asleep": False, "away": False, "sleep_text": "", "away_text": "", "clock": ""}
        try:
            rows = self._recent(umo, 24) or []
        except Exception:
            rows = []
        now = now_ts()
        sleep_at, sleep_text, away_text = 0.0, "", ""
        for row in rows:
            if str(row.get("role") or "") != "user":
                continue
            content = str(row.get("content") or "").strip()
            if not content:
                continue
            when = to_float(row.get("created_at"), 0)
            if _HIS_SLEEP_RE.search(content) and when >= sleep_at:
                sleep_at, sleep_text = when, content
            if _HIS_AWAY_RE.search(content):
                away_text = away_text or content
        hours = max(1, self.cfg_int("his_sleep_hours", 10))
        if sleep_at and (now - sleep_at) <= hours * 3600:
            flags["asleep"] = True
            flags["sleep_text"] = sleep_text
            try:
                flags["clock"] = time.strftime("%H:%M", time.localtime(sleep_at))
            except Exception:
                flags["clock"] = ""
        if away_text:
            flags["away"] = True
            flags["away_text"] = away_text
        return flags

    async def _check_proactive_pending(self):
        try:
            profiles = self.db.proactive_profiles(limit=100)
        except Exception:
            return
        now = now_ts()
        for profile in profiles:
            uid = str(profile.get("uid") or "")
            if not uid:
                continue
            pending = self.db.kv_get(self._pending_key(uid), None)
            if not isinstance(pending, dict) or not pending.get("sent_at"):
                continue
            # 追问要回真正发出这条主动消息的平台（飞书发的就在飞书追）；
            # 老数据没有 umo 时退回主页会话。
            umo = str(pending.get("umo") or "") or str(profile.get("private_umo") or "")
            if not umo:
                continue
            age = now - to_float(pending.get("sent_at"), 0)
            if age > proactive_pending_block_seconds(self.cfg_int):
                self.db.kv_set(self._pending_key(uid), {})
                continue
            followup_minutes = self.cfg_int("proactive_followup_minutes", 30)
            # 0 / 负数 = 关掉追问，只保留「心情变差」这一档
            followup_after = 10 ** 9 if followup_minutes <= 0 else max(5, followup_minutes) * 60
            # 0 / 负数 = 关掉「没回复就心情变差」；默认跟 schema 一致（30 分钟）
            mood_minutes = max(0, self.cfg_int("proactive_no_reply_minutes", 30))
            mood_after = mood_minutes * 60 if mood_minutes else 10 ** 9
            if not pending.get("followup") and age >= followup_after:
                if not quiet_now(self.cfg_str("quiet_hours", "23:30-07:30")):
                    kind = str(pending.get("kind") or "greet")
                    followup = self._followup_text(uid, kind, pending.get("text"))
                    if await self._send_to_umo(umo, followup):
                        pending["followup"] = True
                        pending["followup_at"] = now
                        self.db.kv_set(self._pending_key(uid), pending)
                        # 追问本身也是一句她说过的话，不记下来会引出下一轮「你怎么不理我」
                        self._remember_bot_message(umo, followup)
                        self._mark_bot_initiated(umo)
                        logger.debug("[amo] 主动私聊未回复，已追问: %s" % uid)
            if not pending.get("mood") and age >= mood_after:
                pending["mood"] = True
                self.db.kv_set(self._pending_key(uid), pending)
                ignored = to_int(self.db.kv_get("proactive_ignored_" + uid, 0), 0) + 1
                self.db.kv_set("proactive_ignored_" + uid, ignored)
                self.state.feel_bump({"sadness": 4, "anger": 2, "love": 2, "desire_mind": 3},
                                     weight=self.state.relation_feel_weight(uid))
                if ignored >= max(1, self.cfg_int("proactive_depressed_count", 3)):
                    self._set_depressed(uid)
                logger.debug("[amo] 主动私聊仍无回复，心情变差: %s (%d)" % (uid, ignored))

    def _proactive_candidates(self, profile, primary):
        """主动消息的候选平台：选中的优先，其次是其它通道，最后 private_umo。

        最近刚被主动联系过的平台会被跳过，避免兜底时连着骚扰同一处。
        """
        items = []

        def push(umo, force=False):
            umo = str(umo or "")
            if not umo or umo in items:
                return
            if not force and self._recent_bot_initiated(umo, 3600):
                return
            items.append(umo)

        push(primary, force=True)
        if self.cfg_bool("proactive_rotate_enabled", True):
            try:
                data = self.db.kv_get("channels:%s" % (profile.get("uid") or ""), {}) or {}
            except Exception:
                data = {}
            if isinstance(data, dict):
                entries = [v for v in data.values() if isinstance(v, dict) and v.get("umo")]
                entries.sort(key=lambda v: -float(v.get("ts") or 0))
                for value in entries:
                    push(value.get("umo"))
        push(profile.get("private_umo"))
        return items

    def _pick_proactive_umo(self, profile):
        """选这轮主动消息先发哪个平台；关掉开关就用 private_umo。"""
        fallback = str(profile.get("private_umo") or "")
        if not self.cfg_bool("proactive_rotate_enabled", True):
            return fallback
        uid = str(profile.get("uid") or "")
        try:
            data = self.db.kv_get("channels:%s" % uid, {}) or {}
        except Exception:
            return fallback
        if not isinstance(data, dict):
            return fallback
        items = []
        for value in data.values():
            if isinstance(value, dict) and value.get("umo"):
                items.append((float(value.get("ts") or 0), str(value.get("umo"))))
        if not items:
            return fallback
        items.sort(key=lambda pair: -pair[0])
        if len(items) == 1:
            return items[0][1]
        window = max(1, self.cfg_int("proactive_recent_minutes", 30)) * 60
        if now_ts() - items[0][0] <= window:
            return items[0][1]
        last = str(self.db.kv_get("last_channel:%s" % uid, "") or "")
        for _, umo in items:
            if umo != last:
                return umo
        return items[0][1]

    def _disturb_pressure(self, umo, uid, text="", group=False):
        """最近窗口内，同一个人连续发消息数 / 群里叫机器人的消息数。"""
        try:
            rows = self._recent(umo, 24)
        except Exception:
            return 0
        window = max(1, self.cfg_int("disturb_window_minutes", 10)) * 60
        cutoff = max(
            now_ts() - window,
            to_float(getattr(self, "_disturb_reset_at", {}).get(str(umo), 0), 0),
        )
        same_sender = 0
        mentions = 0
        names = [self.bot_name] + list(self.bot_aliases)
        for row in reversed(rows):
            if to_float(row.get("created_at"), 0) < cutoff:
                continue
            if row.get("role") == "bot":
                break
            if row.get("role") != "user":
                continue
            if group:
                if str(row.get("uid")) == str(uid):
                    same_sender += 1
                content = str(row.get("content") or "")
                if any(name and len(str(name)) >= 2 and str(name) in content for name in names):
                    mentions += 1
            else:
                same_sender += 1
        return max(same_sender, mentions) if group else same_sender

    async def _debounce_private(self, event, text):
        """私聊防抖：同一会话连发的几条合并成一句，只让最后一条继续回复。

        返回 True = 这条是这一批的最后一条（合并后的文本已写回 event.message_str）；
        返回 False = 已被合并，事件保持 stop 状态，调用方直接 return。
        """
        umo = event.unified_msg_origin
        delay = max(0.3, self.cfg_float("private_debounce_seconds", 6.0))
        max_wait = max(delay + 0.1, self.cfg_float("private_debounce_max_wait", 14.0))
        now = time.monotonic()
        buffer = self._private_buffers.get(umo)
        if buffer is None:
            buffer = {"seq": 0, "texts": [], "started": now, "updated": now}
            self._private_buffers[umo] = buffer
        buffer["seq"] += 1
        my_seq = buffer["seq"]
        buffer["texts"].append(str(text or ""))
        buffer["updated"] = now
        event.stop_event()
        deadline = buffer["started"] + max_wait
        while True:
            current = time.monotonic()
            if self._private_buffers.get(umo) is not buffer:
                return False  # 这一批已经被前面的某条发出去了
            if my_seq != buffer["seq"]:
                return False  # 后面又来了新的，交给最新的那条
            quiet_at = buffer["updated"] + delay
            if current >= quiet_at or current >= deadline:
                break
            try:
                await asyncio.sleep(min(quiet_at, deadline) - current)
            except asyncio.CancelledError:
                return False
        if self._private_buffers.get(umo) is buffer:
            self._private_buffers.pop(umo, None)
        merged = "｜".join(item for item in buffer["texts"] if item).strip()[:300]
        if len(buffer["texts"]) > 1:
            logger.info("[amo] 私聊合并 %d 条: %s" % (len(buffer["texts"]), merged[:200]))
            try:
                event.set_extra("amo_debounce_count", len(buffer["texts"]))
            except Exception:
                pass
        event.message_str = merged or (event.message_str or "")
        try:
            event.continue_event()
        except Exception:
            pass
        return True

    def _schedule_delayed_reply(self, event, profile):
        umo = event.unified_msg_origin
        delay = random.randint(
            self.cfg_int("delay_min_minutes", 4),
            self.cfg_int("delay_max_minutes", 18),
        ) * 60
        text = event.message_str or ""

        async def runner():
            try:
                await asyncio.sleep(delay)
                if not self._running or not self._ready:
                    return
                snap = self.state.snapshot()
                note = "你刚刚忙完，主动补一句；不要提等待时间，语气自然。"
                reply = await self._compose_reply(
                    event, text, snap, profile, [], "", False, note=note
                )
                if reply:
                    await self._send_to_umo(umo, reply)
            except asyncio.CancelledError:
                return
            except Exception as exc:
                logger.debug("[amo] 延迟回复失败: %s" % exc)

        self._spawn(runner())


__all__ = [
    "_HIS_SLEEP_RE",
    "_HIS_AWAY_RE",
    "proactive_pending_block_seconds",
    "PresenceMixin",
]
