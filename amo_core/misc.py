# -*- coding: utf-8 -*-
"""Amo 终端 · 其余辅助方法（MiscMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., MiscMixin, Star) 混入，self.* 照旧可用。

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

#: 旧版本曾把某个 QQ 号写死成默认管理员；这里留空 = 不再做那次清理。
#: 真要清理，把号码填进配置 admin_uids 手动删掉即可，代码里不留任何账号。
LEGACY_DEFAULT_ADMIN = ""


class MiscMixin:

    def _core_decor_flags(self, umo=""):
        """AstrBot 核心会不会在插件 hook 之后再加「引用 / @」。

        上架要求不能改 AstrBot 核心；但核心的 platform_settings.reply_with_quote /
        reply_with_mention 是全局的，会在 on_decorating_result 之后无条件装饰结果，
        把本插件的私聊不引用、群聊按概率引用覆盖掉。这里只读配置，检测到开了就由
        插件自己发送，核心就没机会再补。
        """
        try:
            config = self.context.get_config() or {}
        except Exception:
            config = {}
        try:
            settings = config.get("platform_settings") or {}
        except Exception:
            settings = {}
        return {
            "quote": bool(settings.get("reply_with_quote", False)),
            "mention": bool(settings.get("reply_with_mention", False)),
        }

    def _sanitize_schedule(self, sched):
        """对外入口：真正的清洗在 HumanState 里，插件这边代调。"""
        state = getattr(self, "state", None)
        fn = getattr(state, "_sanitize_schedule", None)
        if callable(fn):
            try:
                return fn(sched)
            except Exception as exc:
                logger.debug("[amo] 日程清洗失败: %s" % exc)
        return sched

    def _record(self, kind, title, detail="", reason="", amount=0.0):
        """只增不改的记录：买了什么/想过什么/为什么没买/为什么买股票。"""
        plugin = self._data_plugin()
        store = getattr(plugin, "store", None) if plugin is not None else None
        fn = getattr(store, "record_add", None)
        if not callable(fn):
            return False
        try:
            bot_id = ""
            getter = getattr(self, "_data_bot_id", None)
            if callable(getter):
                bot_id = str(getter() or "")
            fn(bot_id, str(kind or "note"), str(title or ""), str(detail or ""),
               str(reason or ""), float(amount or 0))
            return True
        except Exception as exc:
            logger.debug("[amo] 记录写入失败: %s" % exc)
            return False

    def _remember_outfit_pending(self, style, umo=""):
        try:
            self.db.kv_set("outfit_pending", {
                "style": str(style or "一套")[:40],
                "day": today_str(), "ts": now_ts(), "umo": str(umo or ""),
            })
        except Exception:
            pass

    def _rewrite_today_schedule(self, day):
        """换装后把今天的日程重排一遍并落库（面板、照片都读这一份）。"""
        engine = getattr(self, "outfits", None)
        if engine is None:
            return []
        items = (self.state.schedule.get(day) or self.db.get_schedule(day) or [])
        items = engine.assign(self.state._hourly_schedule(items), day)
        self.state.schedule[day] = items
        try:
            self.db.kv_set("schedule", self._sanitize_schedule(self.state.schedule))
            self.db.save_schedule(day, items)
        except Exception as exc:
            logger.debug("[amo] 换装后写日程失败: %s" % exc)
        return items

    def _outfit_market_hint(self, style=""):
        """衣柜里没有时：市场有没有类似的（有就说价格，没有就说没开门）。"""
        market = self._market_plugin()
        if market is None:
            return "市场没开门"
        text = str(style or "").lower()
        words = [word for word in ("jk", "汉服", "襦裙", "马面", "裙", "衬衫", "卫衣", "外套")
                 if word in text]
        try:
            rows = market.net_rows("outfits") or []
        except Exception:
            rows = []
        for row in rows:
            name = str(row.get("name") or "")
            if any(word and (word in name.lower() or word in name) for word in words):
                return "市场有「%s」%.2f¥" % (name, float(row.get("price") or 0))
        return "市场也没有类似的"

    async def _settle_outfit_reply(self, event, text):
        """她嘴里说「换好了」但没调工具：答应就真换（只在这一轮被要求换装时）。"""
        style = str(getattr(event, "amo_outfit_request", "") or "")
        if not style or getattr(event, "amo_outfit_changed", False):
            return
        try:
            if not event.is_private_chat():
                return
        except Exception:
            pass
        body = str(text or "")
        if re.search(r"回家.{0,6}换|到家.{0,6}换|回去.{0,6}换", body):
            self._remember_outfit_pending(style, getattr(event, "unified_msg_origin", "") or "")
            return
        if not re.search(r"(换好了|换上了|换好咯|已经换了|这就换|我去换)", body):
            return
        try:
            activity = self.state.current_activity() or {}
        except Exception:
            activity = {}
        if not at_home(activity):
            return
        result = await self._change_outfit_now(style)
        if result.get("ok"):
            logger.debug("[amo] 她答应了换装但没调工具，已按她的意思换上：%s" % result.get("look"))

    def _spawn(self, coro):
        try:
            task = asyncio.create_task(coro)
        except RuntimeError:
            try:
                coro.close()
            except Exception:
                pass
            return None
        self._tasks.add(task)

        def _report(done):
            self._tasks.discard(done)
            if done.cancelled():
                return
            try:
                exc = done.exception()
            except Exception:
                exc = None
            if exc is not None:
                logger.warning("[amo] 后台任务异常: %s", exc, exc_info=exc)

        task.add_done_callback(_report)
        return task

    def _migrate_diary_continuity(self):
        """5.2.1：旧版动态日记是逐小时独立生成的，可能互相矛盾；升级时清一次缓存。"""
        try:
            if self.db.kv_get("diary_continuity_521", False):
                return
            self.db.conn.execute("DELETE FROM schedule_diary")
            self.db.conn.commit()
            self.db.kv_set("diary_continuity_521", True)
            logger.debug("[amo] 已清理旧版日程日记缓存（5.2.1 连续性修复）")
        except Exception as exc:
            logger.debug("[amo] 清理日记缓存失败: %s" % exc)

    def _migrate_scenic_kb_name(self):
        try:
            if self.db.kv_get("scenic_kb_name_migrated_502", False):
                return
            current = self.cfg_str("scenic_kb_name", "").strip()
            if current in ("", "中国景区知识库", "景区知识库"):
                self.config["scenic_kb_name"] = "旅游知识库-风景区"
                if hasattr(self.config, "save_config"):
                    self.config.save_config()
            self.db.kv_set("scenic_kb_name_migrated_502", True)
        except Exception as exc:
            logger.debug("[amo] 迁移景区知识库名称失败: %s" % exc)

    def _migrate_typing_defaults(self):
        """2.6.2 起把旧的 55ms/字默认值迁移到更真实的 400ms/字。"""
        try:
            if self.db.kv_get("typing_realistic_migrated", False):
                return
            changes = {}
            if to_int(self.cfg("typing_base_ms", 0), 0) == 600:
                changes["typing_base_ms"] = 700
            if to_int(self.cfg("typing_per_char_ms", 0), 0) == 55:
                changes["typing_per_char_ms"] = 400
            if to_int(self.cfg("typing_max_ms", 0), 0) == 4500:
                changes["typing_max_ms"] = 20000
            for key, value in changes.items():
                self.config[key] = value
            if changes:
                if hasattr(self.config, "save_config"):
                    self.config.save_config()
                logger.debug("[amo] 打字延迟默认值已迁移为 400ms/字（18字约8秒）")
            self.db.kv_set("typing_realistic_migrated", True)
        except Exception as exc:
            logger.debug("[amo] 迁移打字延迟失败: %s" % exc)

    def _migrate_proactive_timing(self):
        try:
            if self.db.kv_get("proactive_timing_migrated", False):
                return
            changes = {}
            if to_int(self.cfg("proactive_followup_minutes", 0), 0) == 30:
                changes["proactive_followup_minutes"] = 5
            if to_int(self.cfg("proactive_no_reply_minutes", 0), 0) == 120:
                changes["proactive_no_reply_minutes"] = 30
            for key, value in changes.items():
                self.config[key] = value
            if changes and hasattr(self.config, "save_config"):
                self.config.save_config()
            self.db.kv_set("proactive_timing_migrated", True)
        except Exception:
            pass

    def _migrate_legacy_admin_default(self):
        """旧版本把 3261748099 写成了默认管理员；2.4.0 只清理一次。"""
        try:
            if self.cfg_str("admin_uids", "").strip() != LEGACY_DEFAULT_ADMIN:
                return
            if self.db.kv_get("admin_default_cleared", False):
                return
            parts = [
                item.strip() for item in self.cfg_str("admin_uids", "").split(",")
                if item.strip() and item.strip() != LEGACY_DEFAULT_ADMIN
            ]
            self.config["admin_uids"] = ",".join(parts)
            if hasattr(self.config, "save_config"):
                self.config.save_config()
            self.admin_uids = set(parts)
            self.db.kv_set("admin_default_cleared", True)
            logger.debug("[amo] 已移除旧默认管理员 %s，请在配置里填写自己的 ID" % LEGACY_DEFAULT_ADMIN)
        except Exception as exc:
            logger.debug("[amo] 清理旧默认管理员失败: %s" % exc)

    async def _warm_up(self):
        try:
            await asyncio.sleep(3)
            umo = self._last_umo or self._first_private_umo()
            await self._sync_persona_name(umo or "")
            await self._ensure_dialect_kb()
            await self._ensure_scenic_kb()
            await self.state.ensure_worldview(umo)
            await self.state.ensure_schedule(umo)
        except Exception as exc:
            logger.debug("[amo] 预热失败: %s" % exc)

    def _image_plugin(self):
        """生图插件实例：_image_plugin 永远拿最新实例（每次按插件名重新解析）。

        2026-11-18 事故：这里曾经把实例缓存在 self._image_star 里永不失效，
        Astrbot_Amo_Image 重载 / 改配置之后陪伴仍然拿**旧实例**出图：用户把
        api_base 换成桥站、甚至重载插件，出图却一直连 api.syuan.org
        （日志 `Cannot connect to host api.syuan.org`），生图插件的新代码也
        一行都不会被执行。现在每次都解析，只把解析不到时退回上次实例当兜底。
        """
        meta = self.context.get_registered_star("DeepSeek_Harness_Amo_Image")
        star = self._image_instance(meta) if meta is not None else None
        if star is None:
            star = getattr(self, "_image_star", None)
            if star is None:
                logger.error("[amo] 生图插件 Astrbot_Amo_Image 没加载，出图不可用")
            return star
        previous = getattr(self, "_image_star", None)
        if previous is not None and previous is not star:
            logger.debug("[amo] 生图插件实例已刷新（重载/重装后自动换新）")
        self._image_star = star
        return star

    def _share_bucket(self):
        """她现在在干嘛 → 发图的场景桶；睡觉/忙正事返回 sleep（概率 0）。"""
        try:
            activity = self.state.current_activity() or {}
        except Exception:
            activity = {}
        values = activity.values() if isinstance(activity, dict) else [activity]
        blob = " ".join(str(v) for v in values if isinstance(v, (str, int, float)))
        for word in self.SHARE_SKIP_WORDS:
            if word in blob:
                return "sleep"
        for bucket, words in self.SHARE_BUCKET_WORDS.items():
            if any(word in blob for word in words):
                return bucket
        return "other"

    def _his_gloomy_now(self, umo="") -> bool:
        """他这几句是不是在往最坏处说。是的话照片这类「轻快的表达」一律先停。"""
        try:
            rows = self.db.recent_messages(umo, 8) or []
        except Exception:
            return False
        hits = 0
        for row in reversed(rows):
            if str(row.get("role") or "") != "user":
                continue
            text = str(row.get("content") or "")
            if any(word in text for word in self.GLOOMY_WORDS):
                hits += 1
        return hits >= 1

    def _digest_lines(self, since):
        """只取私聊消息；群聊内容不参与日记。"""
        try:
            rows = self.db.messages_since_ts(since, limit=80)
        except Exception:
            return []
        lines = []
        for row in rows:
            if not self._private_umo(row.get("umo")):
                continue
            content = str(row.get("content") or "").strip()
            if not content or len(content) > 200:
                continue
            if any(word in content for word in self.DIGEST_INJECTION_WORDS):
                continue
            role = "他" if str(row.get("role") or "") == "user" else "她"
            lines.append("%s：%s" % (role, content[:80]))
            if len(lines) >= 40:
                break
        return lines

    def _vitals(self) -> dict:
        """当前饱食度/水分。数据在记忆库，这里只读。"""
        plugin = self._data_plugin()
        getter = getattr(plugin, "vitals", None) if plugin is not None else None
        if not callable(getter):
            return {}
        try:
            return getter() or {}
        except Exception as exc:
            logger.debug("[amo] 读饱食度失败: %s" % exc)
            return {}

    def _food_menu(self, limit: int = 6) -> str:
        """能吃的有什么、多少钱 —— 从金融插件要，别在终端里写价格。"""
        plugin = self._finance()
        quote = getattr(plugin, "food_quote", None) if plugin is not None else None
        if not callable(quote):
            return ""
        try:
            data = quote() or {}
        except Exception as exc:
            logger.debug("[amo] 取菜单失败: %s" % exc)
            return ""
        rows = []
        for item in (data.get("ready") or [])[:limit]:
            rows.append("%s %.0f元回%d" % (
                item.get("name"), float(item.get("price") or 0),
                int(item.get("satiety") or 0)))
        for item in [c for c in (data.get("cook") or []) if c.get("can_cook")][:3]:
            rows.append("%s（自己做 %.1f元回%d）" % (
                item.get("name"), float(item.get("cost") or 0),
                int(item.get("satiety") or 0)))
        return "；".join(rows)

    def _memory_committed(self, uid, content):
        """记忆真的写进去了：登记去重指纹，并在同一天地点冲突时留一条 warning。"""
        if _mem_commit is None:
            return
        try:
            hint = _mem_commit(self.db, str(uid), str(content), _now(), now_ts())
        except Exception:
            return
        if hint:
            logger.warning("[amo] 记忆可能对不上：%s（%s）" % (hint, str(content)[:40]))

    def _kv_text(self, key, default=""):
        """读一个小字符串键；没有 db（单测里的裸对象）就当没有。"""
        db = getattr(self, "db", None)
        if db is None:
            return default
        try:
            return str(db.kv_get(key, default) or default)
        except Exception:
            return default

    def _kv_put(self, key, value):
        db = getattr(self, "db", None)
        if db is None:
            return
        try:
            db.kv_set(key, value)
        except Exception:
            pass

    def _warm_gift_reply(self, kind, amount, owed, origin="", gift=False):
        amount_text = origin or ("%.0f" % float(amount or 0))
        try:
            big = float(amount or 0) >= 1000
        except Exception:
            big = False
        if gift:
            pool = list(self.GIFT_REPLIES_GIFT_BIG if big else self.GIFT_REPLIES_GIFT)
        else:
            pool = list(self.GIFT_REPLIES_BIG if big else self.GIFT_REPLIES)
        last = self._kv_text("gift_reply_last", "")
        choices = [item for item in pool if item != last] or pool
        template = random.choice(choices)
        self._kv_put("gift_reply_last", template)
        try:
            return template.format(kind=kind, amt=amount_text, owed=float(owed or 0))
        except Exception:
            if gift:
                return "收了你的%s %s，谢谢你。" % (kind, amount_text)
            return "收了你的%s %s，我记着欠你 %.0f。" % (
                kind, amount_text, float(owed or 0))

    def _gift_reaction_style(self):
        """随机挑一种反应，且不跟上次同一种——每笔钱都是同一句就是模板味。"""
        pool = list(self.GIFT_REACTIONS)
        if not pool:
            return "", ""
        last = self._kv_text("gift_reaction_style", "")
        choices = [item for item in pool if item[0] != last] or pool
        key, hint = random.choice(choices)
        self._kv_put("gift_reaction_style", key)
        return key, hint

    def _devices(self) -> dict:
        """她手上的设备：手机、电脑（型号 + 开始用的日期）。没有就按今天往前推随机初始化。"""
        try:
            data = self.db.kv_get("devices", {}) or {}
        except Exception:
            data = {}
        if not isinstance(data, dict) or not data.get("phone") or not data.get("pc"):
            today = _clock_now().date()
            data = {
                "phone": data.get("phone") or {
                    "model": random.choice(self.PHONE_POOL),
                    "since": (today - timedelta(days=random.randint(200, 900))).isoformat(),
                    "price": 5499,
                },
                "pc": data.get("pc") or {
                    "model": random.choice(self.PC_POOL),
                    "since": (today - timedelta(days=random.randint(300, 1400))).isoformat(),
                    "price": 6999,
                },
            }
            try:
                self.db.kv_set("devices", data)
            except Exception:
                pass
        return data

    def _device_wish(self) -> dict:
        """当前最想换的那件（手机/电脑），没有就空 dict。"""
        data = self._devices()
        moods = {}
        try:
            moods = self.feelings.values() if getattr(self, "feelings", None) else {}
        except Exception:
            moods = {}
        eye = float(moods.get("desire_eye") or 0)
        mind = float(moods.get("desire_mind") or 0)
        phone = data.get("phone") or {}
        pc = data.get("pc") or {}
        if eye >= 70 and self._device_age_days(phone) >= 240:
            return {"kind": "phone", "current": phone,
                    "model": random.choice(self.PHONE_POOL),
                    "price": round(float(phone.get("price") or 5499) * 0.95, 2)}
        if mind >= 75 and self._device_age_days(pc) >= 400:
            return {"kind": "pc", "current": pc,
                    "model": random.choice(self.PC_POOL),
                    "price": round(float(pc.get("price") or 6999) * 0.9, 2)}
        return {}

    def _heartflow_tick(self) -> None:
        """内驱动：按上次 tick 到现在的时间衰减，重启也不会一次性掉一大截。"""
        if getattr(self, "feelings", None) is None:
            return
        now = now_ts()
        last = to_float(self.db.kv_get("heartflow_tick_ts", 0), 0)
        minutes = (now - last) / 60.0 if last else 0.0
        # 时间戳只在「真的结算过」之后才往前拨。以前是先写时间戳、再判「不足 0.5 分钟
        # 就 return」，而后台循环正好 30 秒一轮 —— 每两轮就白丢一次衰减（实测 3 分钟
        # 只走了 2 分钟的量）。现在攒着，够 0.5 分钟再一次性结算。
        if last and 0.5 <= minutes <= 24 * 60:
            self.feelings.decay(minutes, sleeping=self._is_sleeping_hour())
            self.db.kv_set("heartflow_tick_ts", now)
        elif not last or minutes > 24 * 60:
            # 第一次跑，或者断开太久（>24 小时）：只把表拨到当下，不补算这一大截
            self.db.kv_set("heartflow_tick_ts", now)
        self._sync_hunger_from_vitals()
        self._wake_energy_tick()
        self._energy_day_tick()

    def _sync_hunger_from_vitals(self) -> None:
        """心流的「饿」直接跟着记忆库的饱食度走（饿 = 100 - 饱食度）。

        两套数字各算各的时候，面板显示饿 100、实际饱食度 7，吃饭也压不下来。
        """
        if getattr(self, "feelings", None) is None:
            return
        vitals = self._vitals()
        if not vitals:
            return
        try:
            satiety = float(vitals.get("satiety") or 0)
        except (TypeError, ValueError):
            return
        try:
            self.feelings.set_physiology(hunger=100.0 - satiety)
        except Exception as exc:
            logger.debug("[amo] 同步饥饿失败: %s" % exc)

    def emit_event(self, name, payload=None) -> dict:
        """挂载插件唯一的事件入口：只交事件名 + 少量参数。

        加减表、边界锁定全在 ``heartflow.py``；这里也不做业务判断，只把
        ``payload["severity"]``（0–10）透传成这一次的放大倍数。
        """
        if getattr(self, "feelings", None) is None:
            return {}
        payload = payload if isinstance(payload, dict) else {}
        severity = payload.get("severity")
        try:
            return self.feelings.apply(name, severity=severity)
        except Exception as exc:
            logger.debug("[amo] 事件 %s 处理失败: %s" % (name, exc))
            return {}

    def feel(self, event, extra=None) -> None:
        """挂载/终端把「发生了什么」丢进来；加减表在 heartflow.py 里，这里不写业务判断。"""
        if getattr(self, "feelings", None) is None:
            return
        try:
            self.feelings.apply(event, extra)
        except Exception as exc:
            logger.debug("[amo] 心流事件失败(%s): %s" % (event, exc))

    def _sleeping_now(self) -> bool:
        try:
            return bool(self.sleep is not None and self.sleep.is_asleep(_clock_now()))
        except Exception:
            return False

    def _is_owner(self, event) -> bool:
        try:
            return bool(self.draw is not None and self.draw.is_owner(event))
        except Exception:
            return False

    async def _wake_from_sleep(self, event, text) -> None:
        """他叫醒她：状态改成醒着，记一笔，然后正常聊天。"""
        now = _clock_now()
        reason = self.sleep.today_woke_reason()
        self.sleep.wake_up(now, woke_early=True)
        uid = self._primary_uid()
        if uid:
            try:
                await self._write_memory_checked(
                    uid, "他把我叫醒了（%s）" % now.strftime("%H:%M"),
                    kind="event", tier=0)
            except Exception:
                pass
        try:
            self.db.save_diary(now.date().isoformat(), now.strftime("%H:00"),
                               "他喊我起床，我迷迷糊糊应了一声。")
        except Exception:
            pass
        logger.debug("[amo] 被他叫醒（夜里原因：%s）" % (reason.value if reason else "无"))

    def _disturb_category(self, snap):
        category = (snap.get("activity") or {}).get("category", "")
        return category in ("sleep", "work", "study")

    def _disturb_active(self, umo):
        return to_float(getattr(self, "_disturb_until", {}).get(str(umo), 0), 0) > now_ts()

    def _tone_with_continuity(self, umo, tone):
        """给语气加情绪惯性，避免上一秒发火、下一秒突然甜蜜。"""
        tone = str(tone or "")
        if self._disturb_active(umo):
            if "不要一秒变甜蜜" not in tone:
                tone += " 你刚被吵醒/打扰，还在烦躁，不要一秒变甜蜜。"
        last = getattr(self, "_last_affect", {}).get(str(umo))
        if last and now_ts() - to_float(last[0], 0) < 1200:
            previous = str(last[1] or "")
            if any(word in previous for word in ("烦躁", "暴躁", "生气", "被打扰")) and "慢慢缓和" not in tone:
                tone += " 上一轮你还在气头上，态度要慢慢缓和，不要突然撒娇甜蜜。"
        self._last_affect[str(umo)] = (now_ts(), tone)
        return tone

    def _apply_disturbance(self, umo):
        now = now_ts()
        self._disturb_until[str(umo)] = now + max(30, self.cfg_int("disturb_tone_seconds", 900))
        self._disturb_cooldown[str(umo)] = now + 120
        self._disturb_reset_at[str(umo)] = now
        last = to_float(getattr(self, "_disturb_last", {}).get(str(umo), 0), 0)
        if now - last >= 60:
            penalty = max(1, self.cfg_int("disturb_mood_penalty", 6))
            self.state.feel_bump(weight=0.6, steps={
                "anger": float(penalty) * 0.7,
                "sadness": float(max(1, penalty // 2)) * 0.6,
                "energy": -float(max(1, penalty // 2)) * 0.5,
                "joy": -float(max(1, penalty // 3)) * 0.6,
            })
            self._disturb_last[str(umo)] = now
        logger.debug("[amo] 被打扰：消息过多，强制回复并降低心情（%s）" % umo)

    def _mark_bot_initiated(self, umo):
        key = str(umo)
        self._bot_initiated[key] = now_ts()
        # 她主动发的消息代表当前是她来找你，不该延续上一轮的火气。
        self._disturb_until[key] = 0
        self._last_affect[key] = (now_ts(), "你主动发起聊天，语气自然亲昵")

    def _recent_bot_initiated(self, umo, seconds=3600):
        return now_ts() - to_float(getattr(self, "_bot_initiated", {}).get(str(umo), 0), 0) < seconds

    def _should_disturb(self, snap, umo, uid, text="", group=False):
        if not self.cfg_bool("disturb_reply_enabled", True):
            return False
        if self._recent_bot_initiated(umo):
            return False
        if not self._disturb_category(snap):
            return False
        if to_float(getattr(self, "_disturb_cooldown", {}).get(str(umo), 0), 0) > now_ts():
            return False
        threshold = max(1, self.cfg_int("disturb_reply_threshold", 3))
        return self._disturb_pressure(umo, uid, text, group=group) >= threshold

    def _private_answer_anchor(self, umo, text):
        """他这句是短回话时，把她上一句原样带出来当锚点。

        没有这个锚点，「不了吧」这种三个字的回答会被模型当成「新话题」，
        于是她挑一个更早的话题接上去——就是用户说的「答非所问」。
        """
        body = str(text or "").strip()
        if not body or len(body) > 12:
            return ""
        if not any(body.startswith(word) for word in self.SHORT_REPLY_WORDS):
            # 也认「不了吧」「可以呀」「没机会了」这类 4 字以内的短句
            if len(body) > 4:
                return ""
        try:
            rows = self.db.recent_messages(umo, 12) or []
        except Exception:
            return ""
        for row in reversed(rows):
            if str(row.get("role") or "") != "bot":
                continue
            said = str(row.get("content") or "").strip()
            if not said:
                continue
            return ("【他在回你这句话】你刚说「%s」，他这轮只回了「%s」。"
                    "这轮要接的是你上面这句话，别换成别的话题——"
                    "他答得短不代表换题，就是在回答这一句。" % (said[:60], body[:20]))
        return ""

    def _strip_place_marks(self, text):
        """兜底：把「东莞·商场·餐厅」这类内部地点串缩成口语的「餐厅」。"""
        value = str(text or "")
        marks = set()
        try:
            city = str((self.state.worldview or {}).get("city") or "").strip()
            if city:
                marks.add(city)
        except Exception:
            pass
        try:
            marks.add(str((self.state.current_activity() or {}).get("place") or ""))
        except Exception:
            pass
        for mark in marks:
            parts = [item.strip() for item in mark.split("·") if item.strip()]
            if len(parts) < 2:
                continue
            for index in range(len(parts) - 1, 0, -1):
                value = value.replace("·".join(parts[:index]) + "·", "")
        return value

    def _trim_reply(self, text):
        # SPEAK 协议兜底：模型写的「SPEAK 1 / SPEAK 0」绝不许进正文或历史。
        # SPEAK 0 → 返回空串（上游判空即不发）；SPEAK 1 → 剥掉协议行只留正文。
        try:
            try:
                from ..text_clean import strip_speak_protocol as _sst
            except Exception:
                from text_clean import strip_speak_protocol as _sst  # type: ignore
            text, _spd = _sst(text)
            if _spd == "0":
                logger.debug("[amo] 🤐 SPEAK 0：这轮不开口")
                return ""
        except Exception as _sst_exc:
            logger.debug("[amo] SPEAK 剥离失败: %s" % _sst_exc)
        # 口语化：书面词换成人话（「因此/然而/非常/是否/如何」这类）
        try:
            try:
                from .humanize import humanize as _humanize
            except Exception:
                from amo_core.humanize import humanize as _humanize  # type: ignore
            text = _humanize(text)
        except Exception as _hz_exc:
            logger.debug("[amo] 口语化失败: %s" % _hz_exc)
        value = self._strip_place_marks(str(text or "").strip())
        limit = max(1, self.cfg_int("reply_max_sentences", 3))
        parts = [item for item in re.split(r"(?<=[。！？!?~～])", value) if item.strip()]
        if len(parts) <= limit:
            return value
        return "".join(parts[:limit]).strip()

    def _remember_sent_reply(self, event, text):
        """守护没接手时（发送异常）的兜底记录。"""
        msg_obj = getattr(event, "message_obj", None)
        if msg_obj is not None and not getattr(msg_obj, "message_id", None):
            return  # 别的插件伪造的主动消息事件，不是这一轮的正常回复
        self._remember_bot_message(event.unified_msg_origin, text)

    async def _send_now(self, event, text, quote_id=None):
        """直接发一条（守护失败时兜底，用来绕开 AstrBot 核心的引用/@）。"""
        if Comp is None or MessageChain is None:
            return False
        chain = []
        if quote_id is not None:
            try:
                chain.append(Comp.Reply(id=quote_id))
            except Exception:
                pass
        chain.append(Comp.Plain(text))
        try:
            await event.send(MessageChain(chain))
        except Exception as exc:
            logger.error("[amo] 直接发送失败: %s" % exc)
            return False
        self._remember_sent_reply(event, text)
        try:
            self._last_reply_at[event.unified_msg_origin] = now_ts()
        except Exception:
            pass
        logger.debug("[amo] 直接发送 -> %s: %s" % (event.unified_msg_origin, text[:300]))
        return True

    def _guard_self_location(self, text, place):
        value = str(text or "")
        place = self._short_place(place)
        if not value or not place:
            return value
        if place in ("家", "家里"):
            value = re.sub(
                r"我(?:刚|正|一直|还|才)?(?:在|回|去|到)(?:酒店|咖啡店|景区|外面|路上)",
                "我在家", value,
            )
            value = re.sub(r"(?:酒店|咖啡店|景区)", "家", value)
        else:
            value = re.sub(
                r"我(?:刚|正|一直|还|才)?(?:窝)?在(?:家|家里)",
                "我在" + place, value,
            )
        return value

    def _lean_parts(self, parts):
        """精简模式：合并重复禁令、去掉多余解释；full 模式原样保留。"""
        if self.cfg_str("context_style", "lean").strip().lower() != "lean":
            return parts
        out = []
        for part in parts:
            tag = ""
            if isinstance(part, str) and part.startswith("【"):
                end = part.find("】")
                if end > 0:
                    tag = part[:end + 1]
            if tag in self.LEAN_PARTS:
                replacement = self.LEAN_PARTS[tag]
                if replacement is None:
                    continue
                out.append(replacement)
                continue
            out.append(part)
        return out

    def _promise_lines(self, snap):
        """她答应过、还没兑现的事：只给事实，做不做她自己定。"""
        if self.promises is None:
            return []
        try:
            activity = (snap or {}).get("activity") or {}
            return self.promises.facts(activity)
        except Exception as exc:
            logger.debug("[amo] 承诺事实失败: %s" % exc)
            return []

    def _promise_photo_later(self, reply_text):
        """她这句话里有没有「等会儿/到了再拍」。"""
        try:
            return detect_photo_later(reply_text) if detect_photo_later else ""
        except Exception:
            return ""

    def _note_photo_promise(self, event, reply_text=""):
        """这轮拍不了（在开车）或她说了等会儿——记成照片承诺，停下后补拍。"""
        text = self._promise_photo_later(reply_text) or ""
        if not text:
            text = "等停了车拍给你看"
        style, want = self._promise_style(event, reply_text)
        return self._note_promise(event, text, KIND_PHOTO, WAIT_DRIVE,
                                  style=style, want=want)

    def _settle_reply_promises(self, event, text):
        """她说出口的「等会儿/到了再拍」「到了就去…」记成承诺。"""
        if self.promises is None or not text:
            return None
        style, want = self._promise_style(event, text)
        photo = self._promise_photo_later(text)
        if photo:
            return self._note_promise(event, photo, KIND_PHOTO, style=style, want=want)
        act = detect_act_later(text) if detect_act_later else ""
        if act:
            return self._note_promise(event, act, KIND_ACT, style=style, want=want)
        return None

    def _promise_style(self, event, text=""):
        """这句约定要穿什么：返回 (风格, 他原话)；没提就是 ("", "")。"""
        engine = getattr(self, "outfits", None)
        if engine is None or not hasattr(engine, "style_camp"):
            return "", ""
        for part in (text, getattr(event, "message_str", "") or ""):
            camp = engine.style_camp(part)
            if camp:
                return camp, str(part or "")[:60]
        return "", ""

    def _promise_settle_siblings(self, row):
        """同一场对话里等着的那几张照片，一张就算全兑现，别一分钟发一张。"""
        try:
            now = now_ts()
            umo = str(row.get("umo") or "")
            for other in self.promises.rows():
                if other.get("done") or other.get("id") == row.get("id"):
                    continue
                if other.get("kind") != KIND_PHOTO:
                    continue
                if umo and str(other.get("umo") or "") != umo:
                    continue
                if now - float(other.get("ts") or 0) > 1800:
                    continue
                self.promises.mark_done(other.get("id"))
        except Exception as exc:
            logger.debug("[amo] 合并同批承诺失败: %s" % exc)

    def _drive_line(self, snap) -> str:
        """她自己日程里在开车：别把「我在开」说成「你在开」。"""
        activity = snap.get("activity") or {}
        text = "%s %s" % (activity.get("activity") or "", activity.get("place") or "")
        if not any(word in text for word in ("开车", "驾车", "路上", "通勤", "堵车")):
            return ""
        return (
            "【开车的是你】现在「%s（%s）」是你自己的日程，不是他。"
            "说你自己的事要用「我」：我在开车、我路上慢点，别反过来说成他在开。"
            % (activity.get("activity") or "在路上",
               self._short_place(activity.get("place") or ""))
        )

    def _sick_line(self, snap, can_ask_money: bool = False) -> str:
        """生病时会难受、会想被照顾，但不会自己跑去医院。"""
        health = snap.get("health") or {}
        status = str(health.get("status") or "")
        note = str(health.get("note") or "")
        if can_ask_money:
            money_hint = "他催你去医院时，可以委屈地说没钱，等他转钱给你、说带你去，你才去。"
        else:
            money_hint = "钱的事只在心里盘算，别在别人面前哭穷，更别跟人借钱。"
        return (
            "【生病】你现在得了%s，%s。整个人难受、没力气、想被照顾。"
            "有钱的话你会自己去医院看病（医疗那边会自动判断）；钱不够就先扛着。"
            "%s别硬撑着说没事。" % (status, note or "浑身不舒服", money_hint)
        )

    def _his_state_lines(self, umo) -> list:
        """他刚说的状态，当事实给她（防「他明明在睡，她却问下班没」）。"""
        flags = self._his_state_flags(umo)
        try:
            from .signals import render_lines
        except Exception:
            from amo_core.signals import render_lines  # type: ignore
        try:
            return render_lines(flags)
        except Exception:
            return []

    def _voice_urge_from_state(self) -> float:
        """心流数值给的「想用声音」冲动（0~1）；私聊也走这条判定。"""
        try:
            feelings = getattr(self, "feelings", None)
            if feelings is None or not hasattr(feelings, "voice_urge"):
                return 0.0
            return max(0.0, min(1.0, float(feelings.voice_urge())))
        except Exception as exc:
            logger.debug("[amo] 语音冲动计算失败: %s" % exc)
            return 0.0

    def _user_asks_voice(self, text: str) -> bool:
        """他这轮有没有明确要语音。命中就下硬要求，不再等心流打分。"""
        body = str(text or "")
        if not body:
            return False
        if any(word in body for word in self.VOICE_ASK_WORDS):
            return True
        return any(re.search(pattern, body) for pattern in self.VOICE_ASK_PATTERNS)

    def _self_face_plugin(self):
        """生图插件：自我形象档案的所有者。没装就 None。"""
        try:
            star = self._photo_star()
        except Exception:
            return None
        return star if hasattr(star, "self_face_match") else None

    async def _background_loop(self):
        try:
            await asyncio.sleep(4)
        except asyncio.CancelledError:
            return
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("[amo] 后台任务异常")
            try:
                await asyncio.sleep(self.cfg_int("loop_interval_seconds", 30))
            except asyncio.CancelledError:
                return

    def _decay_hate_relations(self):
        try:
            cutoff = now_ts() - 7 * 86400
            rows = self.db.conn.execute(
                "SELECT uid FROM profiles WHERE relation='仇恨' AND relation_at>0 AND relation_at<=?",
                (cutoff,),
            ).fetchall()
            for row in rows:
                self.db.update_profile(str(row["uid"]), relation="抵触")
                logger.debug("[amo] 仇恨超过7天，降为抵触: %s" % row["uid"])
        except Exception as exc:
            logger.debug("[amo] 仇恨关系衰减失败: %s" % exc)
        # 2026-11-21：越界打的「抵触」是**临时**的。人家可能只是开玩笑，
        # 冷够了就降回陌生人，只降由 boundary 自动打过标记的那些，
        # 管理员手动设的抵触不动。
        try:
            marks = list(self.db.kv_get("boundary_marks", []) or [])
            if not marks:
                return
            cold_days = max(1, int(self.cfg_int("boundary_cold_days", 3)))
            cutoff = now_ts() - cold_days * 86400
            kept = []
            changed = False
            for mark in marks:
                if not isinstance(mark, dict):
                    changed = True
                    continue
                uid = str(mark.get("uid") or "")
                stamp = float(mark.get("ts") or 0)
                if not uid:
                    changed = True
                    continue
                if stamp <= cutoff:
                    prof = self.db.get_profile(uid) or {}
                    if str(prof.get("relation") or "") == "抵触":
                        self.db.update_profile(uid, relation="陌生人")
                        logger.debug("[amo] 越界冷了 %d 天，降为陌生人: %s" % (cold_days, uid))
                    changed = True
                    continue
                kept.append(mark)
            if changed:
                self.db.kv_set("boundary_marks", kept)
        except Exception as exc:
            logger.debug("[amo] 抵触到期降级失败: %s" % exc)

    def _diary_prompt(self, day, chat_lines, hourly_lines) -> str:
        """拼日记提示词：只给事实骨架，长度和口吻由她自己定。"""
        return (
            "日期：" + day.strftime("%Y年%m月%d日") + "\n"
            "这一天的聊天节选（他和我）：\n" + ("\n".join(list(chat_lines)[-200:]) or "（这天没怎么聊）") + "\n\n"
            "这一天的生活小日记：\n" + ("\n".join(list(hourly_lines)[-24:]) or "（没有小日记）") + "\n\n"
            "写今天这篇日记，正文直接开始：\n"
            "1. 以「生活小日记」为骨架：几点在哪、在做什么、吃了什么、天气怎样。\n"
            "2. 聊天里的话和你的感受可以写进去。\n"
            "3. 长短随你，一句话也可以。\n"
            "4. 口吻就是你平时的样子，可以有情绪、小脾气、细节。\n"
            "5. 小日记和聊天是你今天的事实来源，写的就是这些。\n"
            "6. 这是私人日记，结尾想带一句就带，换着说法："
            + "、".join("「" + item + "」" for item in _diary_pick_hints(DIARY_ENDING_HINTS, 16, day)) + "。\n"
            "直接输出正文。"
        )

    def _diary_clock(self):
        """diary_time 默认 10:00。"""
        raw = str(self.cfg_str("diary_time", "10:00") or "10:00").strip()
        try:
            hour, _, minute = raw.partition(":")
            return max(0, min(23, int(hour))), max(0, min(59, int(minute or 0)))
        except (TypeError, ValueError):
            return 10, 0

    async def _diary_store_put(self, day, text) -> str:
        """日记只写记忆库（本地 txt 那套已删）。"""
        iso = day.isoformat() if hasattr(day, "isoformat") else str(day)
        ok = await self._data_call("diary_put", self._data_bot_id(), iso, str(text or ""), "我的日记")
        if ok:
            return "memory:" + iso
        logger.warning("[amo] 日记写入记忆库失败：%s" % iso)
        return ""

    async def _diary_store_get(self, day) -> str:
        iso = day.isoformat() if hasattr(day, "isoformat") else str(day)
        text = await self._data_call("diary_get", self._data_bot_id(), iso)
        return text if isinstance(text, str) else ""

    async def _diary_chat_lines(self, day):
        """当天聊天 → 「谁：内容」行；取不到就返回空列表。"""
        day_start = int(datetime.combine(day, datetime.min.time()).timestamp())
        mem = self._data_mem()
        if mem is None or not callable(getattr(mem, "messages_between", None)):
            return []
        try:
            rows = await self._data_call(
                "messages_between", self._data_bot_id(), day_start, day_start + 86400, "", 500,
            ) or []
        except Exception as exc:
            logger.debug("[amo] 日记取聊天失败: %s" % exc)
            return []
        # 日记是从她的视角写的，之后会按私聊范围进记忆：群里的对话不该混进来
        rows = _private_rows(rows)
        lines = []
        for row in rows:
            text = str(row.get("content") or "").strip().replace("\n", " ")
            if not text or str(row.get("role") or "") == "system":
                continue
            who = "我" if str(row.get("role") or "") == "bot" else (str(row.get("name") or "") or "他")
            lines.append(who + "：" + text[:200])
        return lines

    def _first_private_umo(self):
        try:
            for profile in self.db.list_profiles(limit=50):
                if profile.get("private_umo"):
                    return str(profile["private_umo"])
        except Exception:
            pass
        # profiles 表没有 private_umo 列（2026-11-21 实测），回落到消息表。
        # 顺带清掉重复嵌套的脏 umo：「aiocqhttp:FriendMessage:aiocqhttp:FriendMessage:1」
        try:
            for umo in self.db.recent_umos(limit=50):
                if "FriendMessage" in umo:
                    parts = str(umo).split(":")
                    if len(parts) > 3:
                        return ":".join([parts[0], parts[-2], parts[-1]])
                    return str(umo)
        except Exception:
            pass
        return ""

    async def _auto_learn(self):
        """定时提炼长期事实，写进记忆库；本插件不再存记忆。"""
        try:
            users = self.db.active_profiles(now_ts() - 3600, limit=2)
        except Exception as exc:
            logger.warning("[amo] 自动学习取人失败: %s" % exc)
            return
        if not users:
            logger.debug("[amo] 自动学习：这一小时没有可学的人")
            return
        for user in users:
            uid = str(user.get("uid", ""))
            if not uid:
                continue
            key = "auto_learn_" + uid
            last = to_float(self.db.kv_get(key, 0))
            interval = max(5, self.cfg_int("auto_learn_minutes", 15)) * 60
            if now_ts() - last < interval:
                continue
            try:
                profile_row = self.db.get_profile(uid) or {}
                home_umo = str(profile_row.get("private_umo") or "").strip()
                if not home_umo:
                    # 还没私聊过：不要退到全局会话，否则群聊的话会被当成他说的
                    continue
                rows = await self._recent_by_uid(uid, 20, umo=home_umo)
                lines = []
                for row in rows:
                    row_umo = str(row.get("umo") or "").strip()
                    if row_umo and row_umo != home_umo:
                        continue
                    role = str(row.get("role") or "")
                    if role == "summary":
                        continue
                    who = "我" if role == "bot" else "他"
                    lines.append("[" + who + "] " + str(row.get("content") or ""))
                if not lines:
                    continue
                facts = await self.llm.extract_facts(
                    home_umo, user.get("name", "") or uid, lines
                )
                ok_any = False
                for fact in facts:
                    written = await self._write_memory_checked(
                        uid, fact["content"], fact["kind"], fact["tier"]
                    )
                    ok_any = ok_any or written
                if facts and not ok_any:
                    logger.warning("[amo] 记忆写入失败，本轮不标记已学: %s" % uid)
                    continue
                if facts:
                    logger.debug("[amo] 自动学习：%s 学到 %d 条事实" % (user.get("name") or uid, len(facts)))
                self.db.kv_set(key, now_ts())
            except Exception as exc:
                logger.debug("[amo] 自动学习失败: %s" % exc)

    def _resolve_target(self, event, args, index):
        if Comp is not None:
            for comp in event.get_messages():
                if isinstance(comp, Comp.At):
                    target = str(getattr(comp, "qq", ""))
                    if target and target != "all" and target != str(event.get_self_id()):
                        return target
        if index < len(args):
            token = str(args[index]).strip().lstrip("@")
            if token in ("我", "me", "self"):
                return self._canonical_uid(event)
            if token:
                return token
        return self._canonical_uid(event)

    def _format_status(self, data):
        mood = data["mood"]
        mood_line = " ".join([key + str(int(value)) for key, value in mood.items()])
        threshold = data["threshold"]
        return "\n".join([
            "🌙 陪伴 · 当前状态",
            "🕒 " + str(data["time"]),
            "💛 心情：" + str(data["dominant"]) + "（" + mood_line + "）",
            "🩸 生理期：" + str(data["period"]["phase"]) + " 第" + str(data["period"]["day"]) + "天（" + str(data["period"]["tone"]) + "）",
            "🩺 身体：" + str(data["health"]["status"]),
            "🌦 天气：" + str(data["weather_text"]),
            "📅 正在：" + str(data["activity"].get("activity", "休息")) + "（" + str(data["activity"].get("place", "")) + "）",
            "🎚 心流阈值：" + str(threshold["value"]) + "（基础 " + str(threshold["base"]) + "，活跃度 " + str(data["activity_rate"]) + "%）",
            "📚 档案 " + str(data["counts"]["profiles"]) + " · 记忆 " + str(data["counts"]["memories"]) + " · 消息 " + str(data["counts"]["messages"]),
        ])

    def _city_module(self):
        """离线城市表模块（懒加载；缺失时返回 None，天气按原样走）。"""
        try:
            try:
                from . import amo_city_index
            except Exception:
                import amo_city_index
            return amo_city_index
        except Exception as exc:
            logger.debug("[amo] 城市表不可用: %s" % exc)
            return None

    def _city_lookup(self, text):
        """把「东莞」「北京朝阳」解析成 LocationID；失败返回 None。"""
        module = self._city_module()
        if module is None:
            return None
        try:
            return module.resolve_city(text)
        except Exception as exc:
            logger.debug("[amo] 城市名解析失败: %s" % exc)
            return None

    async def _reject_follow_trip(self, uid, offer):
        """他让她好好上班：她闷闷不乐，日程不变，日记记一笔。"""
        city = str(offer.get("city") or "").strip()
        self.db.kv_set("follow_offer", {})
        self.db.kv_set("follow_declined", {"city": city, "day": today_str()})
        try:
            self.state.feel_bump({"sadness": 9, "love": 2, "joy": -5})
        except Exception:
            pass
        try:
            content = "她说想去%s陪他，他让她好好上班，她闷闷不乐" % city
            if not await self._write_memory_checked(uid, content, "event", 1):
                logger.warning("[amo] 被拒记忆没写进去")
        except Exception as exc:
            logger.warning("[amo] 被拒记忆失败: %s" % exc)
        try:
            log = self.db.kv_get("follow_reject_log", []) or []
            if not isinstance(log, list):
                log = []
            log.append({"day": today_str(), "hour": "%02d:00" % _now().hour, "city": city})
            self.db.kv_set("follow_reject_log", log[-10:])
        except Exception:
            pass
        return _follow_block(False, city)

    def _voice_plugin(self):
        """找「我想永远陪着你-语音」插件实例；没装或没启用返回 None。"""
        for name in self.VOICE_PLUGIN_NAMES:
            try:
                meta = self.context.get_registered_star(name)
            except Exception:
                meta = None
            star = self._voice_instance(meta)
            if star is not None:
                return star
        try:
            for meta in self.context.get_all_stars():
                marker = ((getattr(meta, "name", "") or "") + " "
                          + (getattr(meta, "module_path", "") or "")).lower()
                if "speechsound" not in marker:
                    continue
                star = self._voice_instance(meta)
                if star is not None:
                    return star
        except Exception:
            pass
        return None

    def _voice_panel_items(self):
        """面板「语音」分组的行：值来自语音插件的配置。"""
        plugin = self._voice_plugin()
        if plugin is None:
            return []
        config = getattr(plugin, "config", {}) or {}
        items = []
        for key, kind, title, hint, default in self.VOICE_SETTING_KEYS:
            items.append({
                "key": key,
                "type": kind,
                "description": title,
                "hint": hint,
                "default": default,
                "options": [],
                "special": "",
                "group": "语音",
                "external": "voice",
                "value": self._voice_value(config, key, kind, default),
            })
        return items

    def _brain_thoughts(self, limit=40):
        """她想过什么：记忆库 records 里 kind=thought 的那批（倒序）。"""
        db = os.path.join(os.path.dirname(os.path.dirname(self.plugin_dir)),
                          "plugin_data", "Astr_Amo_data", "amo_data.db")
        if not os.path.exists(db):
            return []
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=3)
        try:
            rows = con.execute(
                "select kind, title, detail, ts from records "
                "where kind in ('thought', 'idea', '想法') order by ts desc limit ?",
                (int(limit),)).fetchall()
        except Exception:
            rows = []
        finally:
            con.close()
        return [{"kind": r[0], "title": r[1], "text": r[2], "ts": r[3]} for r in rows]

    def _finance(self):
        """找「我想永远陪着你-金融」实例；没装返回 None（只有这一个名字）。"""
        try:
            meta = self.context.get_registered_star("DeepSeek_Harness_Amo_Finance")
        except Exception:
            meta = None
        return self._finance_instance(meta)

    def _charge_conflict(self, note="终端缓存"):
        """同一个幂等号配了不同金额：调用方拿错了号，不许当同一笔账复用。"""
        return {"ok": False, "code": "idempotency_conflict", "repeated": True,
                "reason": "同一幂等号的金额不一致（%s）" % note,
                "balance": self.balance()}

    def event_bus(self):
        """懒加载一条事件总线；没装模块时返回 None。"""
        if _baseline is None or _event_bus_mod is None:
            return None
        bus = getattr(self, "_event_bus_instance", None)
        if bus is None:
            try:
                baseline = _baseline.Baseline(self.config)
            except Exception:
                baseline = _baseline.Baseline()
            bus = _event_bus_mod.EventBus(
                baseline,
                scorer=self._event_score,
                retry_after=max(0, self.cfg_int("event_retry_after", 60)),
            )
            self._event_bus_instance = bus
        return bus

    def _event_score(self, proposal) -> float:
        """心流打分的占位实现：先用配置分，接心流时只换这一个函数。"""
        try:
            return float(self.cfg_float("event_default_score", 0.8))
        except Exception:
            return 0.8

    def submit_event(self, raw) -> dict:
        """插件入口：交一个提案，拿 allow / deny / defer。"""
        event_id = str((raw or {}).get("event_id") or "") if isinstance(raw, dict) else ""
        if not self.cfg_bool("event_bus_enable", True):
            return {"event_id": event_id, "approved": True, "decision": "allow",
                    "reason": "事件总线关闭", "score": 1.0, "fallback": ""}
        bus = self.event_bus()
        if bus is None:
            return {"event_id": event_id, "approved": True, "decision": "allow",
                    "reason": "事件总线模块未加载", "score": 1.0, "fallback": ""}
        payload = raw if isinstance(raw, dict) else {}
        chain = Chain("terminal.bus", event_id=event_id, logger=logger)
        chain.step("submit", type=str(payload.get("event_type") or ""),
                   source=str(payload.get("source") or ""),
                   cost=(payload.get("payload") or {}).get("cost"),
                   scene=str(payload.get("scene") or ""))
        decision = bus.submit(raw)
        chain.step("decide", ok=bool((decision or {}).get("approved")),
                   detail=str((decision or {}).get("reason") or ""),
                   decision=str((decision or {}).get("decision") or ""),
                   score=(decision or {}).get("score"))
        return decision

    def event_receipt(self, raw) -> dict:
        """插件入口：执行完（成功/失败）回执，终端据此归档。"""
        if not self.cfg_bool("event_bus_enable", True):
            return {"accepted": False, "ack": False, "reason": "事件总线关闭"}
        bus = self.event_bus()
        if bus is None:
            return {"accepted": False, "ack": False, "reason": "事件总线模块未加载"}
        payload = raw if isinstance(raw, dict) else {}
        result = bus.receipt(raw)
        Chain("terminal.bus", event_id=str(payload.get("event_id") or ""), logger=logger).step(
            "receipt", ok=bool((result or {}).get("accepted")),
            detail=str(payload.get("status") or ""),
            amount=payload.get("amount"), balance=payload.get("balance"),
        )
        return result

    def event_status(self) -> dict:
        bus = self.event_bus()
        if bus is None:
            return {"enabled": False, "stats": {}, "recent": {}}
        return {"enabled": self.cfg_bool("event_bus_enable", True),
                "stats": bus.stats(), "recent": bus.recent(10)}

    async def charge(self, amount, reason: str = "", payee: str = "",
                     request_id: str = "", source: str = "", detail: str = "",
                     uid: str = "") -> dict:
        """花钱的唯一入口：**审批 → 交给金融 → 把结果告诉记忆**。

        她不自己算账：余额只认金融返回的数字，这里不写余额、不算流水。
        ``request_id`` 是幂等号——同一个号重试只扣一次（医疗重试、网络重发都走这里）。
        """
        try:
            value = round(float(amount or 0), 2)
        except Exception:
            value = 0.0
        rid = str(request_id or "").strip()
        if value <= 0:
            return {"ok": False, "code": "bad_amount", "reason": "金额不对",
                    "balance": self.balance()}
        if value > self.CHARGE_MAX:
            return {"ok": False, "code": "over_limit", "reason": "超过单笔上限",
                    "balance": self.balance()}
        cached = self._charge_cache_get(rid, amount=value)
        if cached is not None:
            cached["repeated"] = True
            return cached

        plugin = self._finance()
        if plugin is None:
            result = {"ok": False, "code": "no_finance", "reason": "没有金融插件", "balance": 0}
        else:
            try:
                try:
                    # 幂等号一起交给金融：它才是账本，重启后也认得出这笔扣过没有
                    result = await asyncio.to_thread(
                        plugin.charge, value, reason, payee, request_id=rid or None)
                except TypeError as exc:
                    if "request_id" not in str(exc):
                        raise
                    # 老版本金融不认识 request_id：退回三参数
                    result = await asyncio.to_thread(plugin.charge, value, reason, payee)
            except Exception as exc:
                logger.warning("[amo] 扣款调用失败: %s" % exc)
                result = {"ok": False, "code": "call_failed", "reason": "扣款出错"}
            if not isinstance(result, dict):
                result = {"ok": False, "code": "bad_result", "reason": "返回值异常"}
        result.setdefault("code", "ok" if result.get("ok") else "failed")
        result.setdefault("transaction_id", rid or ("amo" + uuid.uuid4().hex[:10]))
        self._sync_finance()
        self._charge_cache_put(rid, result, amount=value)
        if not result.get("repeated"):
            await self._record_expense(value, reason, detail, source, result, uid)
            if result.get("ok"):
                self._record("buy", reason or "花钱", detail or payee,
                             "source=%s" % (source or "-"), value)
        return result

    async def income(self, amount, reason: str = "") -> dict:
        plugin = self._finance()
        if plugin is None:
            return {"ok": False, "reason": "没有金融插件"}
        try:
            result = await asyncio.to_thread(plugin.income, amount, reason, "")
        except Exception as exc:
            logger.warning("[amo] 入账调用失败: %s" % exc)
            return {"ok": False, "reason": "入账出错"}
        self._sync_finance()
        return result if isinstance(result, dict) else {"ok": False}

    def balance(self) -> float:
        plugin = self._finance()
        if plugin is None:
            return 0.0
        try:
            return float(plugin.balance())
        except Exception:
            return 0.0

    def _set_period_start(self, value):
        """生理期起点现在归医疗插件：这里只负责转给它。"""
        medical = self._medical()
        setter = getattr(medical, "set_period", None) if medical is not None else None
        if not callable(setter):
            logger.debug("[amo] 医疗插件没连上，生理期起点没写进去")
            return False
        try:
            setter(None, str(value or ""))
            return True
        except Exception as exc:
            logger.debug("[amo] 写生理期起点失败: %s" % exc)
            return False

    def _medical(self):
        """找医疗实例：医疗并入世态之后，它就在世态插件里（代理 status/treat）。"""
        try:
            meta = self.context.get_registered_star("DeepSeek_Harness_Amo_Medical")
        except Exception:
            meta = None
        found = self._finance_instance(meta) if meta is not None else None
        if found is not None:
            return found
        try:
            meta = self.context.get_registered_star("DeepSeek_Harness_Amo_Finance")
        except Exception:
            meta = None
        if meta is None:
            return None
        for attr in ("star_cls", "instance", "star", "plugin"):
            star = getattr(meta, attr, None)
            if star is not None and not isinstance(star, type) and hasattr(star, "treat"):
                return star
        return None

    async def _market_memory(self, text: str, kind: str = "event") -> None:
        try:
            uid = self._primary_uid()
        except Exception:
            uid = ""
        if not uid:
            return
        try:
            await self._write_memory_checked(uid, text, kind=kind, tier=0,
                                             scope="private", group_id="")
        except Exception as exc:
            logger.debug("[amo] 股市心情没写进记忆: %s" % exc)

    async def _market_reward(self, pnl: float) -> None:
        """赚了就奖励自己吃顿好的——真花钱，走同一个账本。"""
        if not self.cfg_bool("market_reward_enable", True):
            return
        amount = 68.0 if pnl < 500 else (128.0 if pnl < 3000 else 198.0)
        try:
            result = await self.charge(
                amount, reason="犒劳自己吃顿好的", payee="餐厅",
                request_id="market-reward-%s" % today_str(),
                source="market", detail="今天股票赚了",
            )
        except Exception as exc:
            logger.debug("[amo] 奖励自己失败: %s" % exc)
            return
        if result.get("ok"):
            logger.debug("[amo] 股市赚了，奖励自己一顿 %.0f 元" % amount)

    def _doctor_line(self) -> str:
        """刚被带去看病（或没看成）：让她的反应接得上。"""
        note = self.db.kv_get("doctor_note", {}) or {}
        try:
            age = now_ts() - float(note.get("ts") or 0)
        except Exception:
            return ""
        if not note or age < 0 or age > 900:
            return ""
        if note.get("ok"):
            return (
                "【他带你去医院】%d 分钟前他带你去看了病（自付 %.0f），现在在恢复。"
                "记得谢谢他、跟他撒个娇，别装没事，也别报流水。"
                % (max(1, int(age // 60)), float(note.get("self_pay") or 0))
            )
        return (
            "【他带你去医院】%d 分钟前他要带你去医院，但没治成：%s。"
            "可以委屈地跟他说，别硬撑。"
            % (max(1, int(age // 60)), note.get("reason") or "没钱")
        )

    def _selfie_prompt(self, look=""):
        """按她此刻的穿搭/地点/在做的事拼自拍提示词；look 用来钉住答应那一刻的穿搭。"""
        activity = {}
        try:
            activity = self.state.current_activity() or {}
        except Exception:
            activity = {}
        parts = ["自拍"]
        # 穿搭只留一处真相：look 给了就照 look（答应那一刻那套），否则用日程这一格。
        # 半套（只有外套没有裙袜鞋）先按套名补整，模型就不会自己补出「抹胸」来。
        outfit = str(look or "").strip() or str(activity.get("outfit") or "").strip()
        outfit = self._complete_outfit(outfit)
        if outfit:
            parts.append("穿着" + outfit)
        place = str(activity.get("place") or "").strip()
        if place:
            parts.append("在" + place)
        doing = str(activity.get("activity") or "").strip()
        if doing:
            parts.append(doing[:30])
        parts.extend(["自然光", "手机前置摄像头", "生活感"])
        return "，".join(parts)

    def _image_photo_call(self, name):
        """取生图插件上的照片方法；没加载就 None。"""
        plugin = self._image_plugin()
        handler = getattr(plugin, name, None) if plugin is not None else None
        return handler if callable(handler) else None

    def _photo_star(self):
        star = self._image_plugin()
        return star if star is not None else None


__all__ = [
    "LEGACY_DEFAULT_ADMIN",
    "MiscMixin",
]
