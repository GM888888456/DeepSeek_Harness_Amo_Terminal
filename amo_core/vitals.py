# -*- coding: utf-8 -*-
"""Amo 终端 · 状态与精力（VitalsMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., VitalsMixin, Star) 混入，self.* 照旧可用。

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



class VitalsMixin:

    def _energy_day_tick(self) -> None:
        """白天也回点力气：午后眯一会儿、晚上到家歇一歇，各补一次（一天各一次）。

        以前精力只有两个来源（23:00-07:00 睡着、07:00 醒来补到 88），之后一路掉，
        中午就剩二十几、傍晚趴到 0，面板上永远是「累得睁不开眼」。
        """
        if getattr(self, "feelings", None) is None:
            return
        try:
            import time as _time

            now = _time.localtime()
            hour, today = int(now.tm_hour), _time.strftime("%Y-%m-%d", now)
            energy = float(self.feelings.values().get("energy") or 0)
        except Exception:
            return
        # (标记键, 起始小时, 结束小时, 低于这个值才补, 补到多少)
        windows = (
            ("energy_noon_date", 13, 16, 66.0, 66.0),
            ("energy_evening_date", 18, 22, 52.0, 52.0),
        )
        for key, start, end, floor, target in windows:
            if not (start <= hour < end):
                continue
            try:
                if str(self.db.kv_get(key, "") or "") == today:
                    continue
            except Exception:
                continue
            try:
                self.db.kv_set(key, today)
            except Exception:
                pass
            if energy >= floor:
                continue
            try:
                self.feelings.set_physiology(energy=target)
                logger.info("[amo] 歇了一会儿，精力回到 %d" % int(target))
            except Exception as exc:
                logger.debug("[amo] 白天回精力失败: %s" % exc)
            return

    def _wake_energy_tick(self) -> None:
        """早上睡醒精力回满，一天一次。

        没有这一步，精力只会在 23:00–07:00 回涨，白天从 0 开始一路掉，
        面板永远是「精力 0」，她也就一直显得没力气。
        """
        if getattr(self, "feelings", None) is None:
            return
        try:
            import time as _time

            now = _time.localtime()
            hour, today = int(now.tm_hour), _time.strftime("%Y-%m-%d", now)
        except Exception:
            return
        if hour < 7 or hour >= 23:
            return
        try:
            if str(self.db.kv_get("energy_wake_date", "") or "") == today:
                return
        except Exception:
            pass
        try:
            values = self.feelings.values()
            if float(values.get("energy") or 0) >= 70:
                self.db.kv_set("energy_wake_date", today)
                return
            self.feelings.set_physiology(energy=88.0)
            self.db.kv_set("energy_wake_date", today)
            logger.info("[amo] 早上醒了，精力回满")
        except Exception as exc:
            logger.debug("[amo] 睡醒回精力失败: %s" % exc)

    def _period_feel_tick(self) -> None:
        """生理期开始/结束时给心流发一次事件（每天最多一次）。"""
        if getattr(self, "feelings", None) is None or FeelEvent is None:
            return
        # 医疗插件在的时候由它发 PERIOD_START/END（带痛经等级），终端只做兜底
        try:
            if self._medical() is not None:
                return
        except Exception:
            pass
        try:
            info = self.state.period_info() or {}
        except Exception:
            return
        day = int(info.get("day") or 0)
        bleed = int(info.get("bleed_days") or 0)
        if not day or not bleed:
            return
        today = today_str()
        try:
            marker = self.db.kv_get("period_feel", {}) or {}
        except Exception:
            marker = {}
        if not isinstance(marker, dict):
            marker = {}
        if day == 1 and marker.get("start") != today:
            self.feel(FeelEvent.PERIOD_START)
            marker["start"] = today
            self.db.kv_set("period_feel", marker)
        elif day == bleed + 1 and marker.get("end") != today:
            self.feel(FeelEvent.PERIOD_END)
            marker["end"] = today
            self.db.kv_set("period_feel", marker)

    def _device_wish_tick(self) -> None:
        """每天最多念一次：想换手机/电脑就写一条记忆，聊到的时候她会说。"""
        wish = self._device_wish()
        if not wish:
            return
        today = today_str()
        try:
            if self.db.kv_get("device_wish_day", "") == today:
                return
        except Exception:
            pass
        name = "手机" if wish["kind"] == "phone" else "电脑"
        text = ("我想换%s了（现在用的%s，%d 天了）：想要 %s，大概 ¥%.0f"
                % (name, (wish.get("current") or {}).get("model") or "旧的",
                   self._device_age_days(wish.get("current") or {}),
                   wish.get("model"), float(wish.get("price") or 0)))
        uid = self._primary_uid()
        if uid:
            try:
                self._spawn(self._write_memory_checked(uid, text, kind="event", tier=0))
            except Exception:
                pass
        try:
            self.db.kv_set("device_wish_day", today)
            self.db.kv_set("device_wish", wish)
        except Exception:
            pass
        logger.info("[amo] 想换设备：%s" % text)

    async def _ritual_pending(self, profile):
        """现在是否正处在「还没发」的问候时段。

        主动消息要让路：早晨 8 点主动搭话和早安问候撞在一起，就是
        「两个地方各响一次」的来源。非恋人的好友、刚问候过的、没有会话可发的，
        都不算待发，否则会白让路一整个时段。
        """
        if not self.cfg_bool("ritual_enabled", True):
            return False
        if str(profile.get("relation") or "") != "相恋":
            return False
        uid = str(profile.get("uid") or "")
        umos = self._ritual_umos(profile)
        if not uid or not umos:
            return False
        if self._recent_greeting(uid, self.cfg_int("ritual_min_gap_minutes", 30)):
            return False
        for kind, _enabled_key, window_key, default_window in self.RITUAL_SPECS:
            # 早/午/晚安已经合成一个总开关：开就三个时段都问，关就都不问
            if not self.cfg_bool("ritual_enabled", True):
                continue
            if not self._ritual_in_window(self.cfg_str(window_key, default_window)):
                continue
            if self.db.kv_get("ritual_" + kind + "_" + uid + "_" + today_str(), False):
                continue
            if not await self._ritual_should_send_async(umos, kind, uid):
                continue
            return True
        return False

    async def _run_due_promises(self):
        """条件到了就真的做：答应的照片这时候补拍发过去。"""
        try:
            if self.promises is None:
                return
            try:
                if quiet_now(self.cfg_str("quiet_hours", "23:30-07:30")):
                    return
            except Exception:
                pass
            activity = {}
            try:
                activity = self.state.current_activity() or {}
            except Exception:
                activity = {}
            if driving and driving(activity):
                return
            self.promises.prune()
            for row in self.promises.due_rows(activity, kind=KIND_PHOTO):
                umo = str(row.get("umo") or "")
                pid = row.get("id")
                if not umo:
                    self.promises.mark_done(pid)
                    continue
                look = str(row.get("look") or "").strip()
                style = str(row.get("style") or "").strip()
                if style:
                    changed = await self._promise_change_outfit(
                        style, str(row.get("want") or ""))
                    if changed:
                        look = changed
                prompt = self._selfie_prompt(look=look)
                data = await self._image_bytes(
                    prompt, umo, str(row.get("uid") or ""), selfie=True)
                if not data:
                    logger.info("[amo] 答应的照片没拍成，等下一轮：%s" % row.get("text"))
                    continue
                ok = await self._send_image_to_umo(
                    umo, data, text="", label="自拍", prompt=prompt)
                if ok:
                    self.promises.mark_done(pid)
                    self._promise_settle_siblings(row)
                    logger.info("[amo] 答应的照片补拍发出（%s）：%s"
                                % (look or "此刻穿着", row.get("text")))
                return  # 一轮只补一张
        except Exception as exc:
            logger.warning("[amo] 兑现承诺失败: %s" % exc)
        finally:
            self._promise_inflight = False

    def _chat_feel(self, text: str, ambient: bool = False, uid: str = "") -> None:
        """每一句话都让她的七情六欲动一点。

        13.0.0 那套「一条只推一个方向 + 900~1800 秒冷却 + 每天 14 点额度」已经拆掉：
        额度早上被群聊花光之后，一整天怎么聊都不动，看起来就是「情绪死了」。
        现在每一句都算，靠小量 + 向上饱和 + 自然回落防止顶死。
        """
        engine = getattr(self, "feelings", None)
        if engine is None or FeelEvent is None:
            return
        body = str(text or "").strip()
        if not body:
            return
        key = "ambient" if ambient else "reply"
        if not ambient:
            for name, words in (
                ("insult", self.INSULT_WORDS),
                ("praise", self.PRAISE_WORDS),
                ("tease", self.CHAT_TEASE_WORDS),
                ("food", self.CHAT_FOOD_WORDS),
                ("affection", self.CHAT_AFFECTION_WORDS),
                ("greed", self.CHAT_GREED_WORDS),
            ):
                if any(word in body for word in words):
                    key = name
                    break
        # 说得越多，这一下越重（一句话比三个字重），最多 1.8 倍
        scale = 1.0 + min(0.8, max(0.0, (len(body) - 6) / 80.0))
        # 谁说的才算数：恋人的一句顶陌生人的六句（关系权重）
        scale *= self.state.relation_feel_weight(uid)
        steps = {dim: value * scale for dim, value in self.CHAT_FEEL_WEIGHTS.get(key, {}).items()}
        if not steps:
            return
        try:
            engine.bump(steps)
        except Exception as exc:
            logger.debug("[amo] 心流写入失败: %s" % exc)

    def _vitals_hint(self, event) -> str:
        """饿了/渴了/刚吃过什么，注入给模型。不满足条件时返回空串。

        本能模式（``instinct_mode``）下只给 ``[Body: ...]`` 事实标签，不再写长句，
        见执行文档 5.2。兜底动作（极端饥饿自动吃、口渴提醒冷却）与模式无关，两边都跑。
        """
        vitals = self._vitals()
        if not vitals or not vitals.get("enabled", True):
            return ""
        try:
            satiety = float(vitals.get("satiety") or 0)
            hydration = float(vitals.get("hydration") or 0)
        except (TypeError, ValueError):
            return ""
        hungry_at = float(vitals.get("hungry_at") or 30)
        starving_at = float(vitals.get("starving_at") or 10)
        if satiety < starving_at:
            # 兜底喂食/生病判定：这是终端的事，跟标签模式无关
            self._spawn(self._maybe_hunger_sick())
            self._spawn(self._maybe_auto_meal())
        if self.cfg_bool("instinct_mode", False):
            return self._body_tag_block(satiety, hydration, hungry_at)
        texts = []
        if satiety < starving_at:
            texts.append(
                "【状态：极度饥饿 %.0f/100】你很久没吃东西了，胃里发空、手有点抖，"
                "注意力没法集中，说话也没力气。" % satiety)
        elif satiety < hungry_at:
            texts.append("【状态：饥饿 %.0f/100】你有点饿了，注意力开始散。" % satiety)
        if hydration < hungry_at:
            try:
                last_thirst = float(self.db.kv_get("thirst_hint_ts", 0) or 0)
            except Exception:
                last_thirst = 0.0
            gap = 30 * 60 if hydration < 10 else 90 * 60
            if now_ts() - last_thirst >= gap:
                texts.append("【状态：口渴 %.0f/100】你渴了，嗓子发干。" % hydration)
                try:
                    self.db.kv_set("thirst_hint_ts", now_ts())
                except Exception:
                    pass
        try:
            last = self.db.kv_get("last_meal", {}) or {}
        except Exception:
            last = {}
        try:
            age = now_ts() - float(last.get("ts") or 0)
        except Exception:
            age = 1e9
        if last and age < 6 * 3600:
            texts.append("【你刚才吃了】%d 分钟前你吃了%s。" % (
                max(1, int(age // 60)), str(last.get("dish") or "点东西")))
        if texts:
            menu = self._food_menu()
            if menu:
                texts.append("【现在能吃的（价格来自金融）】" + menu)
        return ("\n" + "\n".join(texts)) if texts else ""

    def _sync_health_from_medical(self) -> None:
        """身体状态以医疗插件为准。

        医疗说「恢复中」就写恢复中，别抢着改成健康——否则人格资料里会出现
        「刚看完病」和「身体：健康」并存的自相矛盾。
        """
        medical = self._medical()
        if medical is None:
            return
        try:
            info = medical.status()
        except Exception:
            return
        status = str(info.get("status") or "").strip() or "健康"
        note = str(info.get("note") or "")
        current = self.state.health or {}
        if str(current.get("status") or "") == status and str(current.get("note") or "") == note:
            return
        hours = 0
        try:
            until = float(info.get("until") or 0)
            if until > time.time():
                hours = max(1, int((until - time.time()) / 3600.0) + 1)
        except Exception:
            hours = 0
        self.state.set_health(status, hours, note)


__all__ = [
    "VitalsMixin",
]
