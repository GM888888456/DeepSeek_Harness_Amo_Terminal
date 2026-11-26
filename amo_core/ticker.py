# -*- coding: utf-8 -*-
"""Amo 终端 · 心跳与主动行为（TickerMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., TickerMixin, Star) 混入，self.* 照旧可用。

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

_SALARY_RE = re.compile(
    r"(月薪|月工资|工资|薪资|年薪|收入)\s*[:：约是]?\s*(\d+(?:\.\d+)?)\s*(万|w|k|千)?",
    re.IGNORECASE,
)
def extract_salary(text, default: float = 0.0) -> float:
    """从人格文本里读月薪（税前）。读不到返回 default。

    支持「月薪 8000」「工资 1.2 万」「年薪 20 万」（÷12）。数字明显不合理就忽略——
    宁可回落到城市平均，也不要把「工作 3 年」当成月薪 3 万。
    """
    value = 0.0
    for match in _SALARY_RE.finditer(str(text or "")):
        word = (match.group(1) or "").lower()
        try:
            amount = float(match.group(2))
        except (TypeError, ValueError):
            continue
        unit = (match.group(3) or "").lower()
        if unit in ("万", "w"):
            amount *= 10000
        elif unit in ("k", "千"):
            amount *= 1000
        if "年薪" in word:
            amount /= 12.0
        if not (1000 <= amount <= 2000000):
            continue
        value = max(value, amount)
    return round(value, 2) if value else float(default or 0.0)


class TickerMixin:

    async def _maybe_chat_digest(self):
        """每半小时看一次私聊，把「刚才聊了什么」写进当前小时的日记。"""
        if not self.cfg_bool("chat_digest_enable", True):
            return
        if self.llm is None or self.state is None:
            return
        interval = max(5, self.cfg_int("chat_digest_minutes", 30)) * 60
        now = now_ts()
        last = to_float(self.db.kv_get("chat_digest_ts", 0), 0)
        if last and now - last < interval:
            return
        self.db.kv_set("chat_digest_ts", now)
        since = last or (now - interval)
        lines = self._digest_lines(since)
        if not lines:
            return
        day = today_str()
        activity = self.state.current_activity() or {}
        start = str(activity.get("start") or "")[:5]
        cached = ""
        try:
            cached = self.db.get_diary(day, start)
        except Exception:
            cached = ""
        system = "你就是这个角色本人。你在补写自己这一小时的小日记，只输出 JSON。"
        prompt = (
            "现在是 %s，你正在%s（%s），穿着%s。\n"
            "这一小时已经写下的小日记：\n%s\n\n"
            "这一小时你和他刚聊过（只算私聊）：\n%s\n\n"
            "请把「聊天里真正发生的事」补进这一小时的日记：\n"
            "1. 只补充，不要推翻已经写下的内容；原日记里有的地点、天气、穿着保持不变；\n"
            "2. 聊天只影响「你聊了什么、心情怎么变」，不能改你在哪、在做什么；\n"
            "3. 120-200 字，第一人称，口语化；\n"
            "4. 如果这段聊天只是寒暄、没有实质内容，就把原日记原样返回。\n"
            '只输出 JSON：{"diary":"……"}，不要解释。'
            % (_now().strftime("%H:%M"),
               activity.get("activity") or "待着", activity.get("place") or "家",
               activity.get("outfit") or "常服", cached or "（还没写）", "\n".join(lines))
        )
        try:
            raw = await asyncio.wait_for(
                self.llm.chat_raw("", system, prompt, kind="diary"), timeout=60)
        except Exception as exc:
            logger.debug("[amo] 聊天摘要失败: %s" % exc)
            return
        data = json_extract(raw)
        diary = ""
        if isinstance(data, dict):
            diary = str(data.get("diary") or "").strip()
        if len(diary) < 30:
            return
        try:
            self.db.save_diary(day, start, diary)
            logger.debug("[amo] 聊天摘要已更新 %s %s 的日记" % (day, start))
        except Exception as exc:
            logger.debug("[amo] 日记写入失败: %s" % exc)

    async def _maybe_share_image(self, event):
        """入口：只做判断，出图丢后台任务——绝不卡住回复链路。"""
        try:
            decision = await self._share_decision(event)
            if not decision:
                return
            if self._spawn(self._share_image_task(decision)) is None:
                self._share_inflight = False
        except Exception as exc:
            logger.debug("[amo] 主动分享入口异常: %s" % exc)

    async def _maybe_auto_meal(self) -> None:
        """饿/渴到极点还没动：终端替她吃一口、喝一口，别让她一直饿着。

        吃和喝分开算：喝水不能顶替吃饭，也不能把「刚吃过」写成「喝了水」。
        各自 2 小时最多一次；只兜底，口味仍归她自己挑。
        """
        vitals = self._vitals()
        if not vitals or not vitals.get("enabled", True):
            return
        try:
            satiety = float(vitals.get("satiety") or 0)
            hydration = float(vitals.get("hydration") or 0)
        except (TypeError, ValueError):
            return

        def _stamp(key):
            try:
                return float(self.db.kv_get(key, 0) or 0)
            except Exception:
                return 0.0

        now = now_ts()
        need_food = satiety < 20 and (now - _stamp("auto_food_ts")) > 2 * 3600
        need_drink = hydration < 25 and (now - _stamp("auto_drink_ts")) > 2 * 3600
        if not (need_food or need_drink):
            return
        plugin = self._finance()
        propose = getattr(plugin, "food_propose", None) if plugin is not None else None
        if not callable(propose):
            return

        if need_food:
            best = ""
            quote = getattr(plugin, "food_quote", None)
            if callable(quote):
                try:
                    # 按「能不能吃饱」挑，不是按最便宜挑：泡面 15 点，吃完还是饿。
                    rows = [row for row in ((quote() or {}).get("ready") or [])
                            if float(row.get("price") or 0) <= 80]
                    rows.sort(key=lambda row: (-float(row.get("satiety") or 0),
                                               float(row.get("price") or 0)))
                except Exception:
                    rows = []
                if rows:
                    best = str(rows[0].get("name") or "")
            for dish in ([best] if best else []) + ["晚餐"]:
                try:
                    result = propose(dish, "order") or {}
                except Exception as exc:
                    logger.debug("[amo] 自动吃饭失败: %s" % exc)
                    continue
                if not result.get("ok"):
                    logger.debug("[amo] 自动吃饭没成：%s %s" % (
                        result.get("code") or "?", result.get("reason") or ""))
                    continue
                try:
                    self.db.kv_set("auto_food_ts", now)
                    self.db.kv_set("last_meal", {"ts": now, "dish": dish,
                                                 "method": "auto", "auto": True})
                except Exception:
                    pass
                try:
                    self.feel(FeelEvent.MEAL)
                except Exception:
                    pass
                self._sync_hunger_from_vitals()
                logger.debug("[amo] 饿到极点，自动吃了：%s" % dish)
                break

        if need_drink:
            try:
                result = propose("水", "drink") or {}
            except Exception as exc:
                logger.debug("[amo] 自动喝水失败: %s" % exc)
                result = {}
            if result.get("ok"):
                try:
                    self.db.kv_set("auto_drink_ts", now)
                except Exception:
                    pass
                self._sync_hunger_from_vitals()
                logger.debug("[amo] 渴到极点，自动喝了：水")
            elif result:
                logger.debug("[amo] 自动喝水没成：%s %s" % (
                    result.get("code") or "?", result.get("reason") or ""))

    async def _maybe_hunger_sick(self) -> None:
        """饿到极限 → 给医疗插件一个信号，让她有机会真的病一场。

        6 小时只触发一次；医疗插件没装就什么都不做（不许自己造病）。
        """
        plugin = self._medical()
        fall = getattr(plugin, "fall_sick", None) if plugin is not None else None
        if not callable(fall):
            return
        try:
            last = float(self.db.kv_get("hunger_sick_ts", 0) or 0)
        except Exception:
            last = 0.0
        if last and now_ts() - last < 6 * 3600:
            return
        try:
            result = fall("gastro") or {}
        except Exception as exc:
            logger.debug("[amo] 低饱食触发就医失败: %s" % exc)
            return
        try:
            self.db.kv_set("hunger_sick_ts", now_ts())
        except Exception:
            pass
        if result.get("ok"):
            logger.debug("[amo] 饿到极限，她病了一场：%s" % result.get("name"))

    async def _maybe_his_day_digest(self):
        """每天晚上把他今天干了什么写成一条记忆（7 天降权 / 14 天删除）。

        用户的原话：记忆里为什么不记录他干了什么？这不是给他做档案，是让她第二天
        还能记得他昨天去哪了、忙什么、身体怎么样——但不能变成永久事实，按事件走。
        """
        if not self.cfg_bool("his_digest_enabled", True):
            return
        now = _now()
        if now.hour < max(0, min(23, self.cfg_int("his_digest_hour", 23))):
            return
        day = now.strftime("%Y-%m-%d")
        guard = "his_digest:" + day
        try:
            if self.db.kv_get(guard, ""):
                return
            tries = to_int(self.db.kv_get("his_digest_tries:" + day, 0), 0)
            if tries >= 3:
                return
        except Exception:
            tries = 0
        uid = self._primary_uid()
        if not uid or self.llm is None:
            return
        umo = self._first_private_umo() or self._last_umo or ""
        rows = []
        try:
            rows = await self._data_call(
                "recall_messages", self._data_bot_id(), query=day,
                umo="", uid=uid, limit=300,
            )
        except Exception as exc:
            logger.debug("[amo] 他的今日摘要取聊天失败: %s" % exc)
            rows = None
        messages = (rows or {}).get("messages") or []
        if not messages:
            try:
                messages = self.db.chat_history(uid, limit=200) or []
            except Exception:
                messages = []
        lines = []
        for row in messages:
            if str(row.get("role") or "") != "user":
                continue
            text = str(row.get("content") or "").strip().replace("\n", " ")
            if text:
                lines.append(text[:120])
        lines = lines[-80:]
        if len(lines) < 3:
            return
        system = "你在整理「他今天做了什么」，只输出一段中文事实清单，不寒暄。"
        prompt = (
            "下面是主人（他）今天在聊天里说过的话：\n" + "\n".join(lines) + "\n\n"
            "只提取**他自己**今天做过/说过的事：去了哪、吃了什么、工作或学习、出行、"
            "身体状态、打算。用不超过 4 行，每行一件事，主语一律写「他」；"
            "不许写你和他的对话过程，不许编没说过的事，不许写天气这类废话。"
            "没有具体内容就只输出「今天没说什么」。"
        )
        try:
            raw = await asyncio.wait_for(
                self.llm.chat_raw(umo, system, prompt, kind="digest"), timeout=60)
        except Exception as exc:
            logger.debug("[amo] 他的今日摘要生成失败: %s" % exc)
            raw = ""
        summary = re.sub(r"[ \t]+", " ", str(raw or "")).strip()
        summary = re.sub(r"\n{2,}", "\n", summary)
        if len(summary) < 6 or "今天没说什么" in summary:
            try:
                self.db.kv_set(guard, day)
            except Exception:
                pass
            return
        content = "【%s 他的今天】%s" % (day, summary[:400])
        written = await self._write_memory_checked(uid, content, kind="his_day", tier=0)
        logger.debug("[amo] 他的今日摘要%s: %s" % ("已写入" if written else "写入失败", content[:80]))
        if written:
            try:
                self.db.kv_set(guard, day)
            except Exception:
                pass
        else:
            try:
                self.db.kv_set("his_digest_tries:" + day, tries + 1)
            except Exception:
                pass

    async def _maybe_go_sleep(self, event, text) -> bool:
        """他让她去睡：晚上十一点后答应，之前会说还早；睡着后不再回消息。"""
        if self.sleep is None or not text:
            return False
        if not event.is_private_chat() or not self._is_owner(event):
            return False
        if not any(word in text for word in GO_SLEEP_WORDS):
            return False
        now = _clock_now()
        if self.sleep.is_asleep(now):
            return False
        answer = self.sleep.answer(now)
        uid = self._primary_uid()
        if answer is SleepAnswer.TOO_EARLY:
            line = "现在才 %s，还早呢，我再玩会儿。" % now.strftime("%H:%M")
            await self.context.send_message(event.unified_msg_origin, line)
            try:
                event.stop_event()
            except Exception:
                pass
            return True

        self.sleep.go_to_sleep(now)
        try:
            key = now.date().isoformat()
            items = self.state.schedule.get(key) or self.db.get_schedule(key) or []
            if items and apply_sched_change is not None:
                change = {"activity": "睡觉", "place": self.state._home_name(),
                          "category": "sleep",
                          "until": str(self.sleep.load().get("wake_at") or "")}
                new_items = apply_sched_change(items, change, now)
                if new_items and new_items != items:
                    self.state.schedule[key] = new_items
                    self.db.kv_set("schedule", self._sanitize_schedule(self.state.schedule))
                    self.db.save_schedule(key, new_items)
        except Exception as exc:
            logger.debug("[amo] 睡觉日程落盘失败: %s" % exc)
        if uid:
            try:
                await self._write_memory_checked(
                    uid, "他让我去睡，我答应了（%s 睡，%s 起）"
                    % (now.strftime("%H:%M"), self.sleep.load().get("wake_at") or ""),
                    kind="event", tier=0)
            except Exception:
                pass
        try:
            self.db.save_diary(now.date().isoformat(), now.strftime("%H:00"),
                               "他说该睡了，我关了灯躺下。")
        except Exception:
            pass
        line = "好，我去睡了。晚安，别熬太晚。"
        await self.context.send_message(event.unified_msg_origin, line)
        try:
            event.stop_event()
        except Exception:
            pass
        return True

    async def _sleep_tick(self) -> None:
        """每分钟看一次：该起就起；半夜可能醒一次，记进日程和日记。"""
        if self.sleep is None:
            return
        now = _clock_now()
        if not self.sleep.is_asleep(now):
            return
        state = self.sleep.load()
        wake_day = str(state.get("wake_day") or "")
        wake_at = str(state.get("wake_at") or "")
        today = now.date().isoformat()
        hhmm = now.strftime("%H:%M")
        if (today > wake_day) or (today == wake_day and wake_at and hhmm >= wake_at):
            reason = self.sleep.today_woke_reason()
            self.sleep.wake_up(now)
            day = now.date().isoformat()
            text = "早上 %s 醒了。" % hhmm
            if reason is not None:
                text = "早上 %s 醒来。昨晚%s。" % (hhmm, reason_for(reason))
            uid = self._primary_uid()
            if uid:
                try:
                    await self._write_memory_checked(uid, text, kind="event", tier=0)
                except Exception:
                    pass
            try:
                self.db.save_diary(day, now.strftime("%H:00"), text)
            except Exception:
                pass
            logger.debug("[amo] 睡醒了：%s" % text)
            return

        reason = self.sleep.maybe_night_wake(now)
        if reason is not None:
            day = now.date().isoformat()
            text = reason_for(reason)
            uid = self._primary_uid()
            if uid:
                try:
                    await self._write_memory_checked(
                        uid, "半夜 %s %s" % (hhmm, text), kind="event", tier=0)
                except Exception:
                    pass
            try:
                items = self.state.schedule.get(day) or self.db.get_schedule(day) or []
                hour = now.strftime("%H:00")
                changed = False
                for index, item in enumerate(items):
                    if str(item.get("start") or "") == hour:
                        row = dict(item)
                        row["activity"] = "半夜醒来：" + text
                        row["category"] = "rest"
                        items[index] = row
                        changed = True
                        break
                if changed:
                    self.state.schedule[day] = items
                    self.db.kv_set("schedule", self._sanitize_schedule(self.state.schedule))
                    self.db.save_schedule(day, items)
            except Exception as exc:
                logger.debug("[amo] 半夜醒来落日程失败: %s" % exc)
            try:
                existing = self.db.get_diary(day, hour) or ""
                self.db.save_diary(day, hour,
                                   (existing + "；" if existing else "") +
                                   "半夜%s，躺了一会儿又睡过去了。" % text)
            except Exception:
                pass
            logger.debug("[amo] 半夜醒来：%s" % text)
            self.sleep.back_to_sleep(now)

    async def _maybe_user_move(self, event, text) -> bool:
        """他说「回来吧 / 去超市 / 别逛了」：她自己掂量愿不愿意，愿意就**先走过去**。

        - 只认私聊里的主人/恋人；
        - 心情差（生气+暴躁+郁闷+委屈偏高）：直接不答应；
        - 心情还行：答应，日程拆成「原来的活动 → 在路上 → 到达」，不瞬移；
        - 答不答应都写进记忆，她记得这件事。
        """
        if detect_schedule_change is None or apply_sched_change is None:
            return False
        if not event.is_private_chat():
            return False
        try:
            change = detect_schedule_change(text)
        except Exception:
            change = None
        if not change:
            return False
        if str(change.get("category") or "") == "sleep":
            # 「睡吧 / 该睡了」交给 _maybe_go_sleep 管，别从移动逻辑改日程
            return False

        mood = {}
        try:
            mood = (self.state.snapshot() or {}).get("mood") or {}
        except Exception:
            mood = {}
        negative = sum(float(mood.get(k) or 0) for k in ("生气", "暴躁", "郁闷", "委屈"))
        positive = sum(float(mood.get(k) or 0) for k in ("开心", "兴奋", "依恋"))
        uid = self._primary_uid()

        if negative >= 70 and positive < 60:
            line = "我不去。我现在烦着呢，别指挥我。"
            if uid:
                try:
                    await self._write_memory_checked(
                        uid, "他让我「%s」，我心情不好，直接没答应" % change.get("activity"),
                        kind="event", tier=0)
                except Exception:
                    pass
            await self.context.send_message(event.unified_msg_origin, line)
            try:
                event.stop_event()
            except Exception:
                pass
            return True

        key = _clock_now().date().isoformat()
        items = self.state.schedule.get(key) or self.db.get_schedule(key) or []
        if not items:
            return False
        allowed, why = True, ""
        try:
            try:
                from ..schedule_change import hold_change
            except Exception:
                from schedule_change import hold_change  # type: ignore
            allowed, why = hold_change(change, items, _clock_now())
        except Exception as exc:
            logger.debug("[amo] 判断上班时段失败（按允许处理）: %s" % exc)
        if not allowed:
            # 只当聊天：不挪地方，也不发「我这就过去」，交给正常回复
            logger.debug("[amo] 没答应挪地方：%s（%s）" % (why, change.get("activity")))
            return False
        try:
            travel = self.cfg_int("move_transition_minutes", 30)
            hold = self.cfg_int("move_hold_hours", 3)
            new_items = apply_sched_change(items, change, _clock_now(),
                                           transition_minutes=travel, hold_hours=hold)
        except Exception as exc:
            logger.debug("[amo] 按他的话改日程失败: %s" % exc)
            return False
        if new_items == items:
            return False
        self.state.schedule[key] = new_items
        self.db.kv_set("schedule", self._sanitize_schedule(self.state.schedule))
        self.db.save_schedule(key, new_items)
        if uid:
            try:
                await self._write_memory_checked(
                    uid, "他让我「%s」；我答应了，正在路上（%d 分钟后到 %s）"
                    % (change.get("activity"), max(0, travel), change.get("place")),
                    kind="event", tier=0)
            except Exception:
                pass
        target = str(change.get("place") or "").strip()
        if target and target not in ("路上", "车里"):
            line = "行吧，我往%s去了，路上要 %d 分钟。" % (target, max(5, travel))
        else:
            line = "行吧，我这就过去，等我 %d 分钟。" % max(5, travel)
        await self.context.send_message(event.unified_msg_origin, line)
        try:
            event.stop_event()
        except Exception:
            pass
        return True

    async def _maybe_mirror(self):
        """照镜子：换上新衣服后自己拍一张，她得知道镜子里那个人现在什么样。

        触发条件（全部满足才拍）：
          * mirror_enabled 打开；没在睡觉；在 mirror_hour_from ~ mirror_hour_to 之间；
          * 身上那套衣服和上次照镜子的不一样（同一套不重复拍）；
          * 离上次照镜子够久（mirror_min_gap_minutes，默认 90 分钟）；
          * 今天还没到 mirror_daily_cap（默认 1 张）。

        **不发给任何人**：照镜子是给自己看的。照片由生图插件自动进自我形象档案，
        画面描述写进「自我形象记忆」，并挂到上下文里（最近 6 小时），
        这样她说「今天这套」的时候，是真看见过自己。
        """
        if not self.cfg_bool("mirror_enabled", True):
            return
        try:
            if self._sleeping_now():
                return
        except Exception:
            pass
        now = _now()
        if not (self.cfg_int("mirror_hour_from", 7) <= now.hour < self.cfg_int("mirror_hour_to", 23)):
            return
        try:
            scene = self._activity_snapshot() or {}
        except Exception:
            scene = {}
        look = str(scene.get("outfit") or "").strip()
        if not look:
            return
        place = str(scene.get("place") or "").strip()
        doing = str(scene.get("activity") or "").strip()
        day = now.strftime("%Y-%m-%d")
        try:
            count = to_int(self.db.kv_get("mirror_count:" + day, 0), 0)
            if count >= max(1, self.cfg_int("mirror_daily_cap", 1)):
                return
            last = self.db.kv_get("mirror_last", {}) or {}
        except Exception:
            return
        if str(last.get("outfit") or "") == look:
            return
        if now_ts() - to_float(getattr(self, "_mirror_try_at", 0), 0) < 600:
            return
        if now_ts() - to_float(last.get("ts"), 0) < max(15, self.cfg_int("mirror_min_gap_minutes", 90)) * 60:
            return
        self._mirror_try_at = now_ts()
        prompt = self._selfie_prompt(look) + "，换好衣服站在镜子前看了看自己"
        try:
            data = await self._image_bytes(prompt, "", "mirror", selfie=True, scene=scene)
        except Exception as exc:
            logger.debug("[amo] 照镜子出图异常: %s" % exc)
            return
        if not data:
            logger.debug("[amo] 照镜子没出图（额度或后端），下次换衣服再试")
            return
        try:
            self.db.kv_set("mirror_count:" + day, count + 1)
            self.db.kv_set("mirror_last", {"ts": now_ts(), "outfit": look, "place": place})
            self.db.kv_set("self_look", {"ts": now_ts(), "outfit": look, "place": place,
                                         "activity": doing, "prompt": prompt[:200],
                                         "bytes": len(data)})
        except Exception:
            pass
        try:
            self.feel(FeelEvent.MIRROR)
        except Exception:
            pass
        try:
            uid = self._primary_uid()
            if uid:
                where = ("在" + place) if place else "在家"
                text = "[自我形象记忆·%s] 换好%s，我%s照了照镜子：%s。" % (
                    now.strftime("%m-%d %H:%M"), look, where, prompt[:60])
                await self._write_memory_checked(uid, text, kind="event", tier=0)
        except Exception as exc:
            logger.debug("[amo] 照镜子记忆写入失败: %s" % exc)
        logger.debug("[amo] 照镜子完成（%s / %s），已进自我形象档案" % (look, place or "未定"))

    async def _tick(self):
        if not self._ready or self.state is None:
            return
        started_at = now_ts()
        # 数据插件可能在陪伴之后才装：每 5 分钟重新探测一次，装上就自动接管/迁移
        if (self._data_mem() is None and self._data_store() is None
                and now_ts() - to_float(getattr(self, "_last_data_probe", 0), 0) > 300):
            self._last_data_probe = now_ts()
            self._spawn(self._sync_with_data_plugin())
        elif now_ts() - to_float(getattr(self, "_last_digest_check", 0), 0) > 300:
            self._last_digest_check = now_ts()
            self._spawn(self._maybe_daily_digest())
        # 数据插件晚于 amo 加载：它一出现就补做第一次同步（60 秒最多试一次，成功后就停）
        if (not self._data_synced and self._data_connected()
                and now_ts() - to_float(getattr(self, "_last_data_sync_try", 0), 0) > 60):
            self._last_data_sync_try = now_ts()
            self._spawn(self._sync_with_data_plugin())
        if now_ts() - to_float(getattr(self, "_last_chat_digest", 0), 0) > 60:
            self._last_chat_digest = now_ts()
            self._spawn(self._maybe_chat_digest())
        if now_ts() - to_float(getattr(self, "_last_his_digest", 0), 0) > 300:
            self._last_his_digest = now_ts()
            self._spawn(self._maybe_his_day_digest())
        if now_ts() - to_float(getattr(self, "_last_night_close", 0), 0) > 180:
            self._last_night_close = now_ts()
            self._spawn(self._maybe_night_close())
        if now_ts() - to_float(getattr(self, "_last_office_tick", 0), 0) > 600:
            self._last_office_tick = now_ts()
            self._spawn(self._auto_office_tick())
        if now_ts() - to_float(getattr(self, "_last_diary_check", 0), 0) > 300:
            self._last_diary_check = now_ts()
            self._spawn(self._maybe_daily_diary())
        if now_ts() - to_float(getattr(self, "_last_solo_return", 0), 0) > 120:
            self._last_solo_return = now_ts()
            self._spawn(self._maybe_solo_return())
        if now_ts() - to_float(getattr(self, "_last_milestone_check", 0), 0) > 300:
            self._last_milestone_check = now_ts()
            self._spawn(self._maybe_milestone_archive())
        elif now_ts() - to_float(getattr(self, "_last_profile_sync", 0), 0) > 600:
            # 画像每 10 分钟对一次账，保证面板和本地不脱节
            self._last_profile_sync = now_ts()
            self._spawn(self._sync_profiles_to_data())
            self._spawn(self._sync_relations_from_data())
        try:
            await self._sleep_tick()
        except Exception as exc:
            logger.debug("[amo] 睡眠推进失败: %s" % exc)
        try:
            self._heartflow_tick()
        except Exception as exc:
            logger.debug("[amo] 心流衰减失败: %s" % exc)

        try:
            self._world_tick()
        except Exception as exc:
            logger.debug("[amo] 世界推进失败: %s" % exc)
        try:
            self._period_feel_tick()
        except Exception as exc:
            logger.debug("[amo] 生理期事件失败: %s" % exc)
        try:
            self._bill_meals()
        except Exception as exc:
            logger.debug("[amo] 吃饭补扣失败: %s" % exc)
        try:
            self._maybe_shopping()
        except Exception as exc:
            logger.debug("[amo] 想买东西失败: %s" % exc)
        try:
            self._money_pressure_tick()
            self._invest_tick()
            self._earn_tick()
        except Exception as exc:
            logger.debug("[amo] 钱的节奏失败: %s" % exc)
        if now_ts() - to_float(getattr(self, "_last_auto_meal_check", 0), 0) > 600:
            self._last_auto_meal_check = now_ts()
            self._spawn(self._maybe_auto_meal())
        try:
            self._spawn(self._fulfill_outfit_pending())
        except Exception as exc:
            logger.debug("[amo] 回家换装补做失败: %s" % exc)
        if now_ts() - to_float(getattr(self, "_last_mirror_check", 0), 0) > 300:
            self._last_mirror_check = now_ts()
            try:
                self._spawn(self._maybe_mirror())
            except Exception as exc:
                logger.debug("[amo] 照镜子失败: %s" % exc)
        try:
            self._device_wish_tick()
        except Exception as exc:
            logger.debug("[amo] 换设备念头失败: %s" % exc)
        if self.state.last_daily != today_str():
            self.state.daily_tick()
        self.state.roll_health()
        try:
            self._sync_finance()
        except Exception as exc:
            logger.debug("[amo] 财务同步失败: %s" % exc)
        # 慢活儿（网络 / LLM / 发消息）整段丢到后台：出图中转站一次超时、语音合成慢、
        # 日程生成卡住，都不许再把 30 秒一轮的心跳拖成十分钟（2026-11-20 实测停过 10 分钟，
        # 心流/饥饿/精力跟着一起停）。上一轮没跑完就跳过这一轮，不会堆任务。
        slow = getattr(self, "_tick_slow_task", None)
        if slow is not None and not slow.done():
            started = to_float(getattr(self, "_tick_slow_at", 0), 0)
            if started and now_ts() - started > 300:
                # 整段慢活儿卡了 5 分钟还没完（中转站长时间不回、模型一直重试）：
                # 取消重来，别让后面每一轮都跳过。
                logger.warning("[amo] 后台慢活儿卡了 %.0f 秒，取消重来" % (now_ts() - started))
                try:
                    slow.cancel()
                except Exception:
                    pass
                slow = None
        if slow is None or slow.done():
            self._tick_slow_at = now_ts()
            self._tick_slow_task = self._spawn(self._tick_slow())
        took = now_ts() - started_at
        if took > 10:
            logger.warning("[amo] 心跳这一轮用了 %.0f 秒（慢活儿已挪到后台）" % took)


    async def _auto_office_tick(self):
        """她自己处理公司的事：没人签的文件到点自己签/驳。"""
        try:
            mk = self._market_plugin()
        except Exception:
            mk = None
        if mk is None or not hasattr(mk, "office"):
            return
        try:
            import asyncio as _aio
            await _aio.to_thread(self._auto_office_run, mk)
        except Exception as exc:
            logger.debug("[amo] 自律批文失败: %s" % exc)

    def _auto_office_run(self, mk):
        """规则：投资/合作、超大额 → 驳回；其余 → 签。一次最多三份。"""
        try:
            brief = (mk.office("brief") or {}).get("brief") or {}
            docs = brief.get("docs") or []
            strategy = str((brief.get("strategy") or {}).get("id") or "")
            cash = 0.0
            try:
                cash = float(((brief.get("money") or {}).get("cash")) or 0)
            except Exception:
                cash = 0.0
            try:
                from .office_rules import decide as _decide
            except Exception:
                from amo_core.office_rules import decide as _decide  # type: ignore
            for d in docs[:3]:
                act, why = _decide(d, strategy=strategy, cash=cash)
                res = mk.office(act, str(d.get("id") or ""), why)
                logger.info("[amo] 她自己%s「%s」——%s"
                            % ("签了" if act == "approve" else "驳了",
                               str(d.get("title") or "")[:18], why))
        except Exception as exc:
            logger.debug("[amo] 自律批文规则失败: %s" % exc)

    async def _tick_slow(self) -> None:
        """心跳里所有会等网络 / LLM / 发消息的活儿。跑在后台任务里，不占心跳的 30 秒。

        出图中转站超时、语音合成慢、日程生成的模型卡住 —— 这些都不该再拖死
        ``_tick()``：以前它们是直接 await 在心跳里的。
        """
        # 日程最先做：以前它排在还款/股市/就医/天气后面，前面任何一个网络调用
        # 卡住（天气接口不返回最典型），今天就没有日程，她开始自由发挥。
        umo = self._last_umo or self._first_private_umo()
        if umo:
            try:
                await self._hydrate_recent(umo, 30)
            except Exception:
                pass
        if (
            not self.state.schedule.get(today_str())
            or self.db.kv_get("schedule_version", "") != SCHEDULE_VERSION
            or not self.state.schedule_context(today_str())
        ):
            # 以前这里异常会冒到心跳外面被吞掉：日程一整天不生成、日志里一个字都没有
            try:
                await self.state.ensure_schedule(umo)
            except Exception as exc:
                logger.warning("[amo] 日程续生成失败（umo=%r）: %s" % (umo, exc))
            else:
                logger.debug("[amo] 日程续生成走完：%d 格（umo=%r）"
                            % (len(self.state.schedule.get(today_str()) or []), umo))
        try:
            self.state.apply_schedule_events()
        except Exception:
            pass

        try:
            await self._maybe_notify_repay()
        except Exception as exc:
            logger.debug("[amo] 还款通知失败: %s" % exc)
        try:
            await self._maybe_push_salary()
        except Exception as exc:
            logger.debug("[amo] 薪资同步失败: %s" % exc)
        try:
            await self._maybe_push_assets()
        except Exception as exc:
            logger.debug("[amo] 房车同步失败: %s" % exc)
        try:
            await self._note_invest_seed()
        except Exception as exc:
            logger.debug("[amo] 建仓记忆失败: %s" % exc)
        try:
            await self._sync_market_mood()
        except Exception as exc:
            logger.debug("[amo] 股市心情同步失败: %s" % exc)
        try:
            await self._maybe_treat()
        except Exception as exc:
            logger.debug("[amo] 就医判断失败: %s" % exc)
        # 这一行以前没有 try：天气接口一抖，整个 _tick_slow 就断在这里，
        # 后面的日程生成永远轮不到——于是「今天没有日程」，她开始自由发挥。
        try:
            import asyncio as _aio
            await _aio.wait_for(self.state.refresh_weather(), timeout=25)
        except Exception as exc:
            logger.warning("[amo] 天气刷新失败/超时（不影响后面的日程）: %s" % exc)
        try:
            await self._maybe_weather_alert()
        except Exception as exc:
            logger.debug("[amo] 天气提醒失败: %s" % exc)
        # 社交圈：没群消息也能发现「有人加你好友 / 有人拉你进群」。
        try:
            await self._circle_refresh()
        except Exception as exc:
            logger.debug("[amo] 社交圈刷新失败: %s" % exc)


        now = now_ts()
        if now - self._last_relation_decay > 3600:
            self._last_relation_decay = now
            self._decay_hate_relations()
        if (self.cfg_bool("enable_auto_relation", True)
                and now - self._last_relation_sediment > 1800):
            self._last_relation_sediment = now
            try:
                await self._sediment_relations()
            except Exception as exc:
                logger.debug("[amo] 关系沉淀失败: %s" % exc)
            try:
                # 人↔人的边靠群聊里互相 @ 推测出来（低置信度，note 带「推测：」）
                await self._infer_group_edges()
            except Exception as exc:
                logger.debug("[amo] 群聊关系推测失败: %s" % exc)
        if now - self._last_purge > 3600:
            self._last_purge = now
            self.db.purge_messages(self.cfg_int("chat_log_days", 14))

        if self.cfg_bool("enable_auto_learn", True) and now - self._last_auto_learn > 1800:
            self._last_auto_learn = now
            await self._auto_learn()

        if now - self._last_pending_check >= 60:
            self._last_pending_check = now
            try:
                await self._check_proactive_pending()
            except Exception as exc:
                logger.debug("[amo] 检查主动私聊回复失败: %s" % exc)
            try:
                if not self._promise_inflight and self.promises is not None:
                    self._promise_inflight = True
                    if self._spawn(self._run_due_promises()) is None:
                        self._promise_inflight = False
            except Exception as exc:
                self._promise_inflight = False
                logger.debug("[amo] 兑现承诺起不来: %s" % exc)

        current_dt = _now()
        if current_dt.hour == 23 and current_dt.minute >= 59:
            save_key = today_str()
            if self._last_schedule_save != save_key:
                self._last_schedule_save = save_key
                try:
                    items = self.state.schedule.get(save_key) or []
                    if items:
                        self.db.save_schedule(save_key, items)
                    self.db.fade_schedules(7)
                    self.db.purge_schedules(14)
                    self.db.purge_diaries(30)
                except Exception as exc:
                    logger.debug("[amo] 保存/清理日程失败: %s" % exc)

        if now - self._proactive_last >= self.cfg_int("proactive_check_seconds", 300):
            self._proactive_last = now
            await self._maybe_proactive()
            try:
                await self._anniversary_maybe_send()
            except Exception as _ann_exc:
                logger.debug("[amo] 纪念日检查失败: %s" % _ann_exc)
        if now - self._last_ritual >= 60:
            await self._maybe_rituals()

    async def _maybe_daily_diary(self):
        """每天 diary_time（默认 10:00）给「昨天」写一篇日记。"""
        if not self.cfg_bool("diary_enabled", True):
            return
        now = _now()
        hh, mm = self._diary_clock()
        if (now.hour, now.minute) < (hh, mm):
            return
        if getattr(self, "_diary_writing", False):
            return
        end_day = (now - timedelta(days=1)).date()
        try:
            last_written = str(self.db.kv_get("diary_last_day", "") or "")
            start_day = (date.fromisoformat(last_written) + timedelta(days=1)) if last_written else end_day
        except Exception:
            start_day = end_day
        if start_day > end_day:
            return
        if (end_day - start_day).days > 6:
            start_day = end_day - timedelta(days=6)
        days = []
        cursor = start_day
        while cursor <= end_day:
            days.append(cursor)
            cursor += timedelta(days=1)
        self._diary_writing = True
        try:
            for day in days:
                guard = "diary_written:" + day.isoformat()
                attempt_key = "diary_attempt:" + day.isoformat()
                try:
                    if self.db.kv_get(guard, ""):
                        continue
                    last = to_float(self.db.kv_get(attempt_key, 0), 0)
                    if last and now_ts() - last < 1800:
                        continue
                except Exception:
                    pass
                try:
                    text = await self._generate_daily_diary(day)
                    if not text:
                        try:
                            self.db.kv_set(attempt_key, now_ts())
                        except Exception:
                            pass
                        continue
                    path = await self._diary_store_put(day, text)
                    try:
                        self.db.kv_set(guard, path)
                        self.db.kv_set("diary_last_day", day.isoformat())
                    except Exception:
                        pass
                    logger.debug("[amo] 日记已写: %s" % path)
                except Exception as exc:
                    logger.warning("[amo] 写日记失败: %s" % exc)
                    try:
                        self.db.kv_set(attempt_key, now_ts())
                    except Exception:
                        pass
        finally:
            self._diary_writing = False

    async def _maybe_milestone_archive(self):
        """每 N 轮私聊压成一条「里程碑」记忆；原始聊天不删，只多一条归纳。"""
        if getattr(self, "_milestone_running", False):
            return
        self._milestone_running = True
        try:
            await self._milestone_archive_once()
        finally:
            self._milestone_running = False

    async def _maybe_night_close(self):
        """每天 23:55：把今天的记录写成一条总结记忆，然后备份一次。

        幂等：同一天只做一次。备份走记忆插件的 backup_now（整库快照，含日程缓存）。
        """
        now = _now()
        if not (now.hour == 23 and now.minute >= 55):
            return
        day = now.strftime("%Y-%m-%d")
        guard = "night_close:" + day
        try:
            if self.db.kv_get(guard, ""):
                return
        except Exception:
            pass
        lines = []
        plugin = self._data_plugin()
        store = getattr(plugin, "store", None) if plugin is not None else None
        lister = getattr(store, "records_list", None)
        if callable(lister):
            try:
                rows = (lister("", "", 200, 0) or {}).get("items") or []
            except Exception:
                rows = []
            for row in rows:
                if not str(row.get("time") or "").startswith(day):
                    continue
                text = str(row.get("title") or "").strip()
                why = str(row.get("reason") or "").strip()
                lines.append(text + (("（" + why + "）") if why else ""))
        summary = "；".join(lines[-12:]) if lines else "今天没什么特别的"
        uid = ""
        try:
            uid = str(self._primary_uid() or "")
        except Exception:
            uid = ""
        if uid:
            try:
                await self._write_memory_checked(
                    uid, "【%s 收尾】%s" % (day, summary[:800]),
                    kind="daily_digest", tier=0)
            except Exception as exc:
                logger.debug("[amo] 夜间总结写入失败: %s" % exc)
        backed = ""
        backup = getattr(plugin, "backup_now", None) if plugin is not None else None
        if callable(backup):
            try:
                backed = str(await backup(7) or "")
            except Exception as exc:
                logger.debug("[amo] 夜间备份失败: %s" % exc)
        try:
            self.db.kv_set(guard, day)
        except Exception:
            pass
        logger.debug("[amo] 夜间收尾完成：%d 条记录，备份 %s" %
                    (len(lines), backed or "失败"))

    async def _maybe_daily_digest(self):
        """每天上午把"昨天"的聊天压成一条长期记忆（阶段记忆）。"""
        if not self.cfg_bool("daily_digest_enabled", True):
            return
        now = _now()
        if now.hour < max(0, min(23, self.cfg_int("daily_digest_hour", 6))):
            return
        today = now.strftime("%Y-%m-%d")
        guard = "daily_digest:" + today
        try:
            if self.db.kv_get(guard, ""):
                return
        except Exception:
            pass
        mem = self._data_mem()
        if mem is None or not callable(getattr(mem, "recall_messages", None)):
            return
        try:
            profiles = self.db.list_profiles(limit=20) or []
        except Exception:
            profiles = []
        digest_written = 0
        digest_failed = 0
        digest_attempted = 0
        for profile in profiles:
            uid = str(profile.get("uid") or "")
            home_umo = str(profile.get("private_umo") or "")
            if not uid or not home_umo:
                continue
            if str(profile.get("relation") or "") != "相恋":
                continue
            try:
                # 按人取（不限会话）：他上午可能在飞书、晚上在 QQ
                result = await self._data_call(
                    "recall_messages", self._data_bot_id(), query="昨天",
                    umo="", uid=uid, limit=300,
                )
            except Exception as exc:
                logger.debug("[amo] 每日总结取聊天失败: %s" % exc)
                continue
            messages = (result or {}).get("messages") or []
            # 每日总结写的是 scope='private' 的记忆：群里聊的事不算「你们俩的昨天」
            messages = _private_rows(messages)
            lines = []
            for row in messages:
                text = str(row.get("content") or "").strip().replace("\n", " ")
                if not text or str(row.get("role") or "") == "system":
                    continue
                who = "我" if str(row.get("role") or "") == "bot" else "他"
                lines.append("[" + who + "] " + text[:120])
            if len(lines) < 6:
                continue
            digest_attempted += 1
            system = "你是长期记忆整理器。只输出一段中文总结（无标题、无分点、无时间戳）。"
            prompt = (
                "下面是昨天（" + (now - timedelta(days=1)).strftime("%Y-%m-%d") + "）两人的聊天记录。\n"
                "压成 2-4 句长期记忆：聊到的事、约定、双方的状态变化（工作/情绪/计划）。\n"
                "每句带主体：他的事写「他……」，你的事写「我……」；身体、病痛、生理期一律是「我」。\n"
                "只写事实，不写「今天/昨天」这种相对时间，不抄原话；聊天里没有的不写。\n\n"
                + "\n".join(lines[-120:])
            )
            try:
                summary = await self.llm.chat_raw(home_umo, system, prompt)
            except Exception as exc:
                logger.debug("[amo] 每日总结生成失败: %s" % exc)
                summary = ""
            summary = re.sub(r"\s+", " ", str(summary or "")).strip()
            # 摘要也会被当记忆注入：无主语句子会被读成角色自己的经历，统一补「他」
            fixed = []
            for piece in re.split(r"(?<=[。！？!?；;])", summary):
                piece = piece.strip()
                if not piece:
                    continue
                if not piece.startswith(("他", "我", "她", "用户")):
                    piece = "他" + piece
                fixed.append(piece)
            summary = "".join(fixed)
            if len(summary) < 8:
                # 模型拒答/限流会一直返回空：不计数的话 every-5-min tick 会无限重跑
                digest_failed += 1
                continue
            content = "【" + (now - timedelta(days=1)).strftime("%Y-%m-%d") + "】" + summary[:400]
            written = await self._write_memory_checked(uid, content, "daily_digest", 2)
            logger.debug("[amo] 每日总结%s: %s" % ("已写入" if written else "写入失败", content[:80]))
            if written:
                digest_written += 1
            else:
                digest_failed += 1
        # 只有"确实生成过"或"根本没有足够的聊天"才落 guard；
        # 生成失败会重试（最多 3 次/天），避免一天都没有阶段记忆。
        if digest_written or (digest_failed == 0 and digest_attempted == 0):
            try:
                self.db.kv_set(guard, today)
            except Exception:
                pass
        elif digest_failed:
            try:
                tries = to_int(self.db.kv_get("daily_digest_tries:" + today, 0), 0) + 1
                self.db.kv_set("daily_digest_tries:" + today, tries)
                if tries >= 3:
                    self.db.kv_set(guard, today)
                    logger.warning("[amo] 每日总结连续失败 %d 次，今天不再重试" % tries)
            except Exception:
                pass

    async def _maybe_rituals(self):
        if not self.cfg_bool("ritual_enabled", True):
            return
        now = now_ts()
        if now - to_float(getattr(self, "_last_ritual", 0), 0) < 60:
            return
        self._last_ritual = now
        try:
            profiles = self.db.proactive_profiles(limit=100)
        except Exception:
            return
        snap = self.state.snapshot()
        for profile in profiles:
            if str(profile.get("relation") or "") != "相恋":
                continue
            uid = str(profile.get("uid") or "")
            umos = self._ritual_umos(profile)
            if not umos or not uid:
                continue
            home_umo = str(profile.get("private_umo") or "")
            name = str(profile.get("alias") or profile.get("name") or "宝").strip() or "宝"
            for kind, _enabled_key, window_key, default_window in self.RITUAL_SPECS:
                if not self.cfg_bool("ritual_enabled", True):
                    continue
                if not self._ritual_in_window(self.cfg_str(window_key, default_window)):
                    continue
                daily_key = "ritual_" + kind + "_" + uid + "_" + today_str()
                if self.db.kv_get(daily_key, False):
                    continue
                if kind == "morning" and (snap.get("activity") or {}).get("category") == "sleep":
                    continue
                if self._recent_greeting(uid, self.cfg_int("ritual_min_gap_minutes", 30)):
                    continue
                if not await self._ritual_should_send_async(umos, kind, uid):
                    continue
                targets = _greeting_targets(
                    umos,
                    home_umo,
                    randomize=self.cfg_bool("ritual_random_platform", True),
                )
                if not targets:
                    continue
                text = ""
                try:
                    text = await self.llm.gen_proactive(targets[0], profile, snap, kind)
                except Exception as exc:
                    logger.debug("[amo] 仪式生成失败: %s" % exc)
                if not text:
                    # 兜底句里也不能问「还没起来吗」：他可能早就醒了（13.3.0）
                    text = {
                        "goodnight": name + "，太晚了，我先去睡觉啦，你也早点睡。",
                        "morning": name + "，早呀，今天也一起吃好点。",
                        "lunch": name + "，今天中午吃啥子哦？",
                    }.get(kind, "")
                if not text:
                    continue
                if self.WAKE_ASK_RE.search(text) and self._his_presence_line(uid, home_umo):
                    # 他已经醒着、刚在群里说过话，这条还在问「醒没」→ 这次不发。
                    logger.debug("[amo] 问候又要问他醒没，已丢弃: %s" % text[:40])
                    continue
                sent_umo = ""
                for candidate in targets:
                    if await self._send_to_umo(candidate, text):
                        sent_umo = candidate
                        break
                if not sent_umo:
                    continue
                # 只标记真正收到的那一处；另一头靠 greeting_last 跨平台去重，
                # 不能把「她刚跟我说过话」的副作用（火气/打扰冷却）打到没收到消息的平台
                self._mark_bot_initiated(sent_umo)
                self._mark_greeting(uid, kind, sent_umo)
                self.db.kv_set(daily_key, True)
                self.db.log_proactive(uid, kind, text)
                logger.debug(
                    "[amo] 每日问候(%s) -> %s [%s]: %s"
                    % (kind, name, str(sent_umo).split(":", 1)[0], text[:200])
                )
                break

    async def _maybe_weather_alert(self):
        """明天天气变坏时，到点提醒一次（每天最多一条）。

        判断一天只做两次：
        - 早上 `weather_alert_morning_time`（默认 08:00）：只判断、不发送；
        - 晚上 `weather_alert_time`（默认 20:00）：到点才真的发预报，
          且**跳过预报缓存**拿最新一份，保证当天晚上这条的准确性。

        以前每 30 秒的后台循环都会重算一遍，日志刷屏、还每次都要请一次和风接口。
        用 `weather_alert_checked`（形如 `2026-11-08|evening`）记住今天哪个槽位
        已经判断过，没到点 / 判断过的直接返回。
        """
        if not self.cfg_bool("weather_alert_enabled", False):
            return
        key = self.cfg_str("hefeng_key", "")
        if not key:
            return
        target = self.cfg_str("weather_alert_time", "20:00")
        evening_min = parse_clock(target, 20, 0)
        morning_raw = str(self.cfg_str("weather_alert_morning_time", "08:00") or "").strip()
        morning_min = parse_clock(morning_raw, 8, 0) if morning_raw else None
        now = _now()
        today = today_str()
        if str(self.db.kv_get("weather_alert_sent", "") or "") == today:
            return
        checked = str(self.db.kv_get("weather_alert_checked", "") or "")
        slot = next_check_slot(
            now.hour * 60 + now.minute, morning_min, evening_min, checked, today
        )
        if not slot:
            return
        label = "早上" if slot == "morning" else "晚上"
        city = (
            self.cfg_str("weather_city", "").strip()
            or str((getattr(self.state, "schedule_profile", {}) or {}).get("city") or "").strip()
            or "贵阳"
        )
        # 晚上要发预警，必须用最新预报：跳过 3 小时缓存。
        items = await self.state._fetch_qweather_daily(
            key, city, 3, fresh=(slot == "evening")
        )
        if len(items) < 2:
            # 拿不到预报就别每 30 秒重试，今天不提醒。
            self.db.kv_set("weather_alert_checked", slot_key(today, slot))
            return
        text = evaluate_weather_alert(
            items[0], items[1], self.cfg_int("weather_alert_temp_drop", 8)
        )
        self.db.kv_set("weather_alert_checked", slot_key(today, slot))
        if not text:
            logger.debug("[amo] 天气提醒（%s）：明天天气正常，不提醒" % label)
            return
        if slot == "morning":
            # 早上只判断，真正的预报晚上再发，一天一条不追发。
            logger.debug("[amo] 天气提醒（早上）：明天要变天，晚上 %s 再发给他" % target)
            return
        umos = self._weather_alert_umos()
        if not umos:
            logger.debug("[amo] 天气提醒：没有可发送的会话")
            return
        text = await self._weather_alert_text(umos[0], items[1], text)
        # 一个一个平台试：某个平台的会话失效时换下一个，而不是整天发不出去
        sent_umo = ""
        for umo in umos:
            if await self._send_to_umo(umo, text):
                sent_umo = umo
                break
            logger.warning("[amo] 天气提醒这个平台发送失败，换下一个: %s" % umo)
        if sent_umo:
            self.db.kv_set("weather_alert_sent", today)
            self.db.kv_set("weather_alert_open", today)
            logger.debug("[amo] 天气提醒已发送: %s -> %s" % (text, sent_umo))
        else:
            # 所有平台都失败：清掉 checked 让下一轮重试（原来也是每轮重试）。
            self.db.kv_set("weather_alert_checked", "")
            logger.warning("[amo] 天气提醒所有平台都失败: %s" % umos)

    async def _anniversary_maybe_send(self):
        """纪念日当天主动发一句（预设台词，一天一次，不调模型）。"""
        try:
            try:
                from ..world import dates as _dates
            except Exception:
                from world import dates as _dates  # type: ignore
        except Exception:
            return
        mark = _dates.today_mark()
        if not mark:
            return
        key = "anniv_sent:" + str(mark.get("date") or "")
        try:
            if self.db.kv_get(key, False):
                return
        except Exception:
            pass
        window = str(mark.get("window") or "09:00-22:00")
        try:
            if not quiet_now(window):      # 只在时段内发
                return
        except Exception:
            pass
        try:
            profiles = self.db.proactive_profiles(limit=20)
        except Exception:
            return
        lovers = [p for p in profiles if str(p.get("relation") or "") == "相恋"]
        profile = (lovers or profiles or [None])[0]
        if not profile:
            return
        umo = ""
        try:
            umo = self._pick_proactive_umo(profile) or ""
        except Exception:
            umo = ""
        text = str(mark.get("line") or "").strip()
        if not text or not umo:
            return
        for candidate in self._proactive_candidates(profile, umo):
            try:
                ok = await self._send_to_umo(candidate, text)
            except Exception:
                ok = False
            if not ok:
                continue
            try:
                self.db.kv_set(key, True)
                self.db.bump_proactive(profile.get("uid"))
                self.db.log_proactive(profile.get("uid"), "anniversary", text)
                self._set_proactive_pending(profile.get("uid"), "anniversary", text, umo=candidate)
            except Exception:
                pass
            try:
                uid = self._primary_uid()
                if uid:
                    await self._write_memory_checked(
                        uid, "今天是%s：我说了「%s」" % (mark.get("name"), text),
                        kind="event", tier=0)
            except Exception:
                pass
            logger.info("[amo] 纪念日主动（%s）：%s" % (mark.get("name"), text[:24]))
            return

    async def _maybe_proactive(self):
        quiet = quiet_now(self.cfg_str("quiet_hours", "23:30-07:30"))
        try:
            profiles = self.db.proactive_profiles(limit=100)
        except Exception:
            return
        if self.cfg_bool("proactive_require_friend", True):
            profiles = [profile for profile in profiles if self._is_proactive_friend(profile)]
        # 名单留空 = 管理员 + 相恋；配了名单就只认名单
        owner_ids = self._proactive_owner_ids(profiles)
        if owner_ids:
            profiles = [p for p in profiles if str(p.get("uid") or "") in owner_ids]
        if not profiles:
            return
        random.shuffle(profiles)
        now = now_ts()
        interval = max(10, self.cfg_int("proactive_interval_min", 90)) * 60
        daily_max = max(0, self.cfg_int("proactive_daily_max", 3))
        for profile in profiles:
            uid = str(profile.get("uid") or "")
            if await self._ritual_pending(profile):
                continue
            if self._recent_greeting(uid, self.cfg_int("proactive_after_greeting_minutes", 60)):
                continue
            target_umo = self._pick_proactive_umo(profile)
            if not target_umo:
                continue
            if self._recent_bot_initiated(target_umo, 3600):
                continue
            if self._proactive_user_just_talked(profile, now):
                continue
            count = to_int(profile.get("proactive_count"))
            if profile.get("proactive_day") != today_str():
                count = 0
            if count >= daily_max:
                continue
            relation = str(profile.get("relation") or "普通")
            guaranteed = (
                relation == "相恋"
                and count == 0
                and self.cfg_bool("proactive_daily_guarantee", True)
                and _now().hour >= 8
            )
            if quiet and not guaranteed:
                continue
            if self._pending_still_blocking(profile.get("uid"), profile, now):
                continue
            snap = self.state.snapshot()
            category = (snap.get("activity") or {}).get("category", "")
            if category in ("sleep", "work", "study") and not guaranteed:
                continue
            forced = (
                relation == "相恋"
                and category in ("meal", "rest", "play", "commute")
                and self._proactive_forced_allowed(profile, now)
                and not self._forced_sent_this_hour(profile.get("uid"))
            )
            if not guaranteed and not forced and now - to_float(profile.get("last_proactive", 0)) < interval:
                continue
            if not guaranteed and not forced and random.random() > self.cfg_float("proactive_prob", 0.25):
                continue
            if not guaranteed and self.cfg_bool("proactive_schedule_only", True) and category not in ("meal", "rest", "play", "commute"):
                continue
            his_flags = self._his_state_flags(target_umo)
            if his_flags.get("asleep") and not guaranteed:
                logger.debug("[amo] 他说要睡了，这次不主动打扰：%s" % profile.get("name", ""))
                continue
            kind = self._choose_proactive_kind(profile, snap, category)
            if his_flags.get("away") and kind in ("offwork", "commute"):
                kind = "slack"
            text = await self.llm.gen_proactive(
                target_umo, profile, snap, kind
            )
            if not text:
                continue
            if self.WAKE_ASK_RE.search(text) and self._his_presence_line(profile.get("uid"), target_umo):
                # 他已经醒着，这条却还在问他醒没：这次不发，下一轮会带着事实重生成。
                logger.debug("[amo] 主动消息又要问他醒没，已丢弃: %s" % text[:40])
                continue
            sent_umo = ""
            for candidate in self._proactive_candidates(profile, target_umo):
                if await self._send_to_umo(candidate, text):
                    sent_umo = candidate
                    break
            ok = bool(sent_umo)
            if ok:
                target_umo = sent_umo
                self._mark_bot_initiated(target_umo)
                self.db.kv_set("last_channel:%s" % profile.get("uid"), target_umo)
                self.db.bump_proactive(profile["uid"])
                self.db.log_proactive(profile["uid"], kind, text)
                self._set_proactive_pending(profile["uid"], kind, text, umo=target_umo)
                self._mark_forced_hour(profile.get("uid"))

                logger.debug("[amo] 主动私聊 -> %s (%s)" % (profile.get("name", ""), kind))

    async def _maybe_follow_city(self, event, uid, profile):
        """他到了某地：她问「我来陪你吧」；同意就跟去（路上约 2 小时），拒绝就闷闷不乐。"""
        if not self.cfg_bool("city_follow_enabled", True):
            return ""
        try:
            if not event.is_private_chat():
                return ""
        except Exception:
            return ""
        if str(profile.get("relation") or "") != "相恋":
            return ""
        text = str(event.message_str or "")
        now = now_ts()
        offer = self.db.kv_get("follow_offer", {}) or {}
        offer = offer if isinstance(offer, dict) else {}
        if offer and now - to_float(offer.get("ts"), 0) > 1800:
            self.db.kv_set("follow_offer", {})
            offer = {}
        travel = self.db.kv_get("travel", {}) or {}
        travel = travel if isinstance(travel, dict) else {}
        if travel.get("city") and re.search(r"(回来吧|回家吧|别玩了|该回来了|我回东莞)", text):
            await self._end_follow_trip(uid)
            return "【回家】他说回来了：自然应一句「好，我这就回」，别拖，也别说还没玩够。"
        if travel.get("city"):
            return ""
        if self.db.kv_get("wander_trip", {}):
            return ""
        if _follow_invite(text):
            city = str(self.db.kv_get("he_city", "") or "").strip()
            if not city:
                return "【邀请】他让你过去，但你不知道他在哪个城市：先问一句他在哪。"
            if city == _CITY_DEFAULT:
                return "【邀请】他让你过去，可你俩都在东莞：自然回一句“我不就在你旁边吗”之类的。"
            self.db.kv_set("follow_declined", {})
            return await self._start_follow_trip(uid, {
                "city": city, "id": "",
                "tomorrow": _now().hour >= 22,
            })
        if offer.get("city"):
            if _wander_agree(text):
                return await self._start_follow_trip(uid, offer)
            if _follow_refuse(text):
                return await self._reject_follow_trip(uid, offer)
        old_he = str(self.db.kv_get("he_city", "") or "").strip()
        old = str(self.db.kv_get("his_city", "") or "").strip()
        hit = _city_detect(text, prefer_city=old or old_he)
        if not hit:
            return ""
        name = str(hit.get("name") or "").strip()
        declined = self.db.kv_get("follow_declined", {}) or {}
        declined_city = str(declined.get("city") or "") if isinstance(declined, dict) else ""
        if not name or name == old_he:
            if declined_city and declined_city == name:
                return "【别重复提】你之前问过要不要去陪他，他没让；别再主动提这事，按他说的上班就好。"
            return ""
        if name == _CITY_DEFAULT:
            self.db.kv_set("he_city", name)
            self.db.kv_set("follow_declined", {})
            return ""
        # 到了新的城市：之前"被拒过"的标记作废，可以再问一次
        self.db.kv_set("follow_declined", {})
        tomorrow = _now().hour >= 22
        self.db.kv_set("he_city", name)
        self.db.kv_set("wander_offer", {})
        self.db.kv_set("follow_offer", {
            "ts": now, "city": name, "id": str(hit.get("id") or ""), "tomorrow": tomorrow,
        })
        return _follow_block(True, name, tomorrow)

    async def _maybe_wander(self, event, uid, profile):
        """她自己出去玩：问意愿 → 同意 → 定行程；旅行中让他叫回来。"""
        if not self.cfg_bool("wander_enabled", True):
            return ""
        try:
            if not event.is_private_chat():
                return ""
        except Exception:
            return ""
        if str(profile.get("relation") or "") != "相恋":
            return ""
        if self.db.kv_get("travel", {}) or self.db.kv_get("follow_offer", {}):
            return ""
        text = str(event.message_str or "")
        now = now_ts()
        trip = self.db.kv_get("wander_trip", {}) or {}
        trip = trip if isinstance(trip, dict) else {}
        if trip.get("city") and re.search(r"(回来吧|回家吧|别玩了|早点回来|该回来了)", text):
            await self._end_solo_trip(uid, "他让你回来")
            return "【旅游】他让你回来：自然应一句“好，我收拾下就回”，别拖，也别说还没玩够。"
        offer = self.db.kv_get("wander_offer", {}) or {}
        offer = offer if isinstance(offer, dict) else {}
        if offer and now - to_float(offer.get("ts"), 0) > 1800:
            self.db.kv_set("wander_offer", {})
            offer = {}
        if _wander_question(text):
            if (
                self.db.kv_get("travel", {})
                or self.db.kv_get("follow_offer", {})
                or self.db.kv_get("wander_trip", {})
            ):
                return ""
            today = today_str()
            count = 0
            if str(self.db.kv_get("wander_asked_day", "") or "") == today:
                try:
                    count = int(self.db.kv_get("wander_ask_count", 0) or 0)
                except (TypeError, ValueError):
                    count = 0
            limit = _wander_ask_limit(self.cfg_bool("wander_ask_three_times", False))
            if count >= limit:
                return (
                    "【旅游提议】今天已经问过 " + str(count) + " 次了（一天最多 " + str(limit)
                    + " 次），别再重新决定、别再报新城市；按之前说的自然接一句。"
                )
            self.db.kv_set("wander_asked_day", today)
            self.db.kv_set("wander_ask_count", count + 1)
            low, tired = _wander_assess(self.state.mood, self.state.health_info())
            want = _wander_want(
                low, tired, random,
                self.cfg_float("wander_prob_low", 0.85),
                self.cfg_float("wander_prob_good", 0.15),
            )
            city, spots = "", []
            if want:
                city, spots = _wander_pick(
                    self.scenic_spots(), random, count=4,
                    exclude_city=str(self.db.kv_get("his_city", "") or ""),
                )
                want = bool(city)
            if not want:
                self.db.kv_set("wander_offer", {"ts": now, "want": False})
            else:
                self.db.kv_set("wander_offer", {
                    "ts": now, "want": True, "city": city,
                    "spots": [str(x.get("name") or "") for x in spots][:4],
                    "spot_rows": spots[:4],
                })
            return _wander_offer_block(bool(want), city, spots)
        if offer.get("want") and _wander_agree(text):
            return await self._start_solo_trip(uid, offer)
        if offer.get("want") and _wander_refuse(text):
            self.db.kv_set("wander_offer", {})
            try:
                self.state.feel_bump({"sadness": 5})
            except Exception:
                pass
            return (
                "【不出去了】他说这次不让你去：你有点失落，但别闹，用自己的口吻说一句："
                + _wander_solo_refuse_text(random)
            )
        if trip.get("city") and not trip.get("announced"):
            start = str(trip.get("day") or "")
            ret = str(trip.get("return_day") or start)
            if start and start <= today_str() <= ret:
                try:
                    day_no = (_now().date() - date.fromisoformat(start)).days + 1
                except Exception:
                    day_no = 1
                return _wander_solo_block(str(trip["city"]), trip.get("spots") or [], day_no=day_no)
        return ""

    async def _maybe_solo_return(self):
        """旅游最后一天到点回家：换天气、报平安、写记忆/日记。"""
        trip = self.db.kv_get("wander_trip", {}) or {}
        if not isinstance(trip, dict) or not trip.get("city") or trip.get("announced"):
            return
        ret_day = str(trip.get("return_day") or "")
        if not ret_day or today_str() != ret_day:
            return
        try:
            hour = int(trip.get("return_hour") or 12)
        except (TypeError, ValueError):
            hour = 12
        if _now().hour < hour:
            return
        city = str(trip["city"])
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
        # 报平安必须进私聊：以前用 _last_umo，他最后一句是在群里就会把「我回来啦」发进群。
        umo = self._first_private_umo()
        if not umo:
            last = str(getattr(self, "_last_umo", "") or "")
            umo = last if "FriendMessage" in last else ""
        uid = ""
        try:
            rows = self.db.list_profiles(limit=1) or []
            uid = str((rows[0] or {}).get("uid") or "") if rows else ""
        except Exception:
            uid = ""
        try:
            if umo:
                text = random.choice((
                    "我回来啦，刚到家。",
                    "到家啦，你在干嘛呢？",
                    "我回来了，你吃饭了没？",
                ))
                if await self._send_to_umo(umo, text):
                    self._mark_bot_initiated(umo)
                    if uid:
                        self._set_proactive_pending(uid, "travel_back", text, umo=umo)
        except Exception as exc:
            logger.warning("[amo] 回来报平安失败: %s" % exc)
        try:
            if uid:
                if not await self._write_memory_checked(
                    uid, "她 %s 从 %s 旅游回来了" % (today_str(), city), "event", 1,
                ):
                    logger.warning("[amo] 回来记忆没写进去")
        except Exception as exc:
            logger.warning("[amo] 回来记忆失败: %s" % exc)
        try:
            log = self.db.kv_get("travel_log", []) or []
            if isinstance(log, list):
                log.append({
                    "day": today_str(), "hour": "%02d:00" % _now().hour,
                    "city": city, "solo": True, "back": True,
                })
                self.db.kv_set("travel_log", log[-10:])
        except Exception:
            pass
        trip["announced"] = True
        self.db.kv_set("wander_trip", trip)
        logger.debug("[amo] 旅游回来：%s" % city)

    async def _maybe_notify_repay(self) -> None:
        """她自动还了钱：在私聊里说一声，不要只在账本里静默扣。"""
        plugin = self._finance()
        reader = getattr(plugin, "money_repay", None) if plugin is not None else None
        if not callable(reader):
            return
        try:
            note = reader() or {}
            amount = float(note.get("amount") or 0)
        except Exception:
            return
        if amount <= 0:
            return
        ts = float(note.get("ts") or 0)
        last = to_float(self.db.kv_get("last_repay_notified_ts", 0), 0)
        if ts and ts <= last:
            return
        umo = self._first_private_umo() or self._last_umo
        if not umo:
            return
        remaining = float(note.get("remaining") or 0)
        text = self._repay_message(amount, remaining)
        if not text:
            return
        try:
            await self.context.send_message(umo, text)
        except Exception as exc:
            logger.debug("[amo] 还款通知发送失败: %s" % exc)
            return
        self.db.kv_set("last_repay_notified_ts", ts or now_ts())
        logger.debug("[amo] 还款通知已发：%.0f（还欠 %.0f）" % (amount, remaining))

    async def _maybe_push_salary(self) -> None:
        """把人格里的月薪同步给金融。

        人格没写薪资是常态：这时不推，金融按城市平均发。人格改过就重新读一次。
        """
        now = now_ts()
        if now - to_float(getattr(self, "_salary_checked_at", 0), 0) < 600:
            return
        self._salary_checked_at = now
        plugin = self._finance()
        setter = getattr(plugin, "set_salary", None) if plugin is not None else None
        if not callable(setter):
            return
        umo = self._last_umo or self._first_private_umo()
        text = ""
        try:
            if self.llm is not None and umo:
                text = await self.llm.persona(umo) or ""
        except Exception as exc:
            logger.debug("[amo] 读人格失败（薪资）: %s" % exc)
            return
        gross = extract_salary(text)
        if gross <= 0:
            return
        try:
            result = await asyncio.to_thread(setter, gross, "persona")
        except Exception as exc:
            logger.debug("[amo] 推送月薪失败: %s" % exc)
            return
        if isinstance(result, dict) and result.get("skipped"):
            return
        logger.debug("[amo] 从人格读到月薪 %.0f，已交给金融" % gross)

    async def _maybe_push_assets(self) -> None:
        """把人格里的房/车同步给金融：她开奔驰，就不能被随机成比亚迪。"""
        now = now_ts()
        if now - to_float(getattr(self, "_assets_checked_at", 0), 0) < 600:
            return
        self._assets_checked_at = now
        plugin = self._finance()
        setter = getattr(plugin, "set_persona_assets", None) if plugin is not None else None
        if not callable(setter):
            return
        car = ""
        house = ""
        try:
            profile = getattr(self.state, "schedule_profile", {}) or {}
            car = str(profile.get("car") or "").strip()
            house = str(profile.get("home") or "").strip()
        except Exception as exc:
            logger.debug("[amo] 读人格资产失败: %s" % exc)
            return
        if not car and not house:
            return
        try:
            result = await asyncio.to_thread(setter, car, house)
        except Exception as exc:
            logger.debug("[amo] 推送房车失败: %s" % exc)
            return
        city = ""
        try:
            profile_city = (getattr(self.state, "schedule_profile", {}) or {}).get("city")
            city = str(profile_city or "").strip()
        except Exception:
            city = ""
        city_setter = getattr(plugin, "set_persona_city", None)
        if city and callable(city_setter):
            try:
                await asyncio.to_thread(city_setter, city)
            except Exception as exc:
                logger.debug("[amo] 推送城市失败: %s" % exc)
        if isinstance(result, dict) and result.get("changed"):
            logger.debug("[amo] 从人格读到房车，已交给金融：%s｜%s" % (house or "-", car or "-"))

    async def _maybe_user_takes_her_to_doctor(self, event, text) -> bool:
        """他说要带她去医院，这才是她去看病的入口。

        她自己不会主动去（后台每天自动判断那条路已经停掉）；只有他发现她不对劲、
        说「都病成这样了还不去医院看看，走我带你去医院」，才走医疗插件的手动就医。
        """
        if not text or not event.is_private_chat():
            return False
        medical = self._medical()
        if medical is None:
            return False
        try:
            info = medical.status()
        except Exception:
            return False
        if not info.get("sick"):
            return False
        if not any(word in text for word in self.DOCTOR_WORDS):
            return False
        try:
            result = await medical.treat(auto=False) or {}
        except Exception as exc:
            logger.warning("[amo] 带她去医院失败: %s" % exc)
            return False
        note = {
            "ts": now_ts(),
            "name": str(result.get("name") or ""),
            "self_pay": float(result.get("self_pay") or 0),
            "ok": bool(result.get("ok")),
            "reason": str(result.get("reason") or ""),
        }
        self.db.kv_set("doctor_note", note)
        if result.get("ok"):
            logger.debug("[amo] 他带她去看了病：%s，自付 %.0f"
                        % (note["name"], note["self_pay"]))
            self._sync_health_from_medical()
        else:
            logger.debug("[amo] 带她去医院没治成：%s"
                        % (note["reason"] or "余额不足"))
        return True

    async def _maybe_treat(self) -> None:
        """换成医疗插件管的病情后，由它决定治不治、钱够不够。

        她自己会去看病；医疗插件会回调 self.charge()——**所以这里仍然是
        「她知情」的那条路**。成功只写状态，不刷日志；失败由医疗插件记 warning。
        """
        medical = self._medical()
        if medical is None:
            return
        try:
            info = medical.status()
        except Exception:
            return
        if not info.get("sick"):
            return
        # 同一个病一天只判断一次，避免后台循环反复去治
        key = "%s|%s" % (today_str(), info.get("illness") or info.get("status"))
        if getattr(self, "_treat_marked", None) == key:
            return
        self._treat_marked = key
        try:
            result = await medical.treat(auto=True)
        except Exception as exc:
            logger.warning("[amo] 就医失败: %s" % exc)
            return
        if result.get("skipped"):
            # 手动模式 / 她自己先扛着：都不是失败，不该记成焦虑
            logger.debug("[amo] 这次没去看病：%s" % result.get("reason"))
            return
        if result.get("ok"):
            logger.debug("[amo] 去看了病：%s，自付 %.0f"
                        % (result.get("name"), float(result.get("self_pay") or 0)))
            # 状态交给医疗插件：它说「恢复中」就写恢复中
            self._sync_health_from_medical()
        else:
            self.state.feel_bump({"fear": 6, "sadness": 3})


__all__ = [
    "_SALARY_RE",
    "extract_salary",
    "TickerMixin",
]
