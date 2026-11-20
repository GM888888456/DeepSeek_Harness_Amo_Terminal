# -*- coding: utf-8 -*-
"""Amo 终端 · 天气与预警（WeatherMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., WeatherMixin, Star) 混入，self.* 照旧可用。

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



class WeatherMixin:

    def _weather_alert_umos(self):
        """天气提醒的候选会话，按最近活跃排序。

        只用她**真的收到过消息**的会话（channels:<uid> + private_umo），
        没配飞书的人候选里就只有 QQ，不会随机到一个不存在的平台。
        """
        pairs = []
        try:
            for profile in self.db.proactive_profiles(limit=20):
                uid = str(profile.get("uid") or "")
                data = self.db.kv_get("channels:%s" % uid, {}) or {}
                if isinstance(data, dict):
                    for value in data.values():
                        if isinstance(value, dict) and value.get("umo"):
                            pairs.append((float(value.get("ts") or 0), str(value["umo"])))
                item = str(profile.get("private_umo") or "")
                if item:
                    pairs.append((0.0, item))
        except Exception as exc:
            logger.debug("[amo] 天气提醒选平台失败: %s" % exc)
        pairs.sort(key=lambda pair: -pair[0])
        seen = []
        for _, umo in pairs:
            if umo and umo not in seen:
                seen.append(umo)
        if not seen:
            fallback = self._last_umo or self._first_private_umo()
            if fallback:
                seen.append(fallback)
        return seen

    def _pick_weather_alert_umo(self):
        """兼容旧调用：返回最该优先尝试的那个会话。"""
        items = self._weather_alert_umos()
        return items[0] if items else ""

    async def _weather_alert_text(self, umo, tomorrow, fallback):
        """用她自己的语气说这句提醒；模型失败就退回模板。"""
        facts = []
        day_text = (str(tomorrow.get("textDay") or "") + " " + str(tomorrow.get("textNight") or "")).strip()
        if day_text:
            facts.append("明天天气：" + day_text)
        if tomorrow.get("tempMax"):
            facts.append("明天最高 " + str(tomorrow.get("tempMax")) + "℃")
        recent_lines = []
        try:
            for row in self._recent(umo, 8):
                content = str(row.get("content") or "").strip()
                if not content:
                    continue
                who = "他" if str(row.get("role") or "") == "user" else "你"
                recent_lines.append(who + "：" + content[:80])
        except Exception:
            recent_lines = []
        try:
            state_text = self.state.prompt_text(self.state.snapshot())
        except Exception:
            state_text = ""
        system = (
            await self.llm.persona(umo) + "\n\n"
            "规则：你就是角色本人，只输出要发出去的消息。"
        )
        prompt = (
            (state_text + "\n" if state_text else "")
            + "事实：\n" + "\n".join(facts) + "\n"
            + ("最近聊天：\n" + "\n".join(recent_lines) + "\n" if recent_lines else "")
            + "参考说法（不要照抄）：" + fallback + "\n"
            + "请用你平时跟他说话的语气，主动提一句明天的天气。\n"
            "要求：只发一句，20-30 字以内；像真人随口说的，不要像天气播报、客服或助手；\n"
            "不要用“提醒您/请注意/建议您/记得带伞哦/注意保暖”这种模板，不要罗列温度风力；\n"
            "可以带一点情绪（关心、吐槽、嫌麻烦都行），但别煽情；不要问“要不要带伞”，不要重复你刚说过的话。"
        )
        try:
            text = await self.llm.chat(umo, system, prompt, limit=60)
        except Exception as exc:
            logger.debug("[amo] 天气提醒文案生成失败: %s" % exc)
            text = ""
        text = self._clean_weather_alert(text)
        return text or fallback

    async def _weather_query_context(self, text=""):
        """他问天气时，用缓存里的「现在天气 + 今天 + 明天」拼一段给他看。

        只有缓存过期才会真的请求和风（现在天气 30 分钟一份、预报 3 小时一份），
        所以连着问十遍通常一次都不多请。
        """
        key = self.cfg_str("hefeng_key", "")
        city = (
            self.cfg_str("weather_city", "").strip()
            or str((getattr(self.state, "schedule_profile", {}) or {}).get("city") or "").strip()
            or "贵阳"
        )
        now_data = {}
        try:
            now_data = await self.state.refresh_weather()
        except Exception as exc:
            logger.debug("[amo] 天气查询取现在天气失败: %s" % exc)
        if not now_data:
            now_data = getattr(self.state, "weather", {}) or {}
        items = []
        if key:
            try:
                items = await self.state._fetch_qweather_daily(key, city, 3)
            except Exception as exc:
                logger.debug("[amo] 天气查询取预报失败: %s" % exc)
        today = items[0] if items else {}
        tomorrow = items[1] if len(items) > 1 else {}
        brief = forecast_brief(now_data, today, tomorrow)
        if not brief:
            logger.info("[amo] 天气查询：没有可用数据")
            return "【天气查询】这会儿取不到天气数据，别编温度，直接说看不太准。"
        logger.info("[amo] 天气查询: %s" % brief)
        return "【天气查询】" + brief

    async def _switch_weather_city(self, hit):
        """按城市跟随的结果改 weather_city / 显示名，并立刻刷一次天气。"""
        city_id = str(hit.get("id") or "").strip()
        name = str(hit.get("name") or "").strip()
        if not city_id or not name:
            return
        changed = False
        if str(self.config.get("weather_city") or "") != city_id:
            self.config["weather_city"] = city_id
            changed = True
        if self.cfg_str("weather_city_name", "").strip() != name:
            self.config["weather_city_name"] = name
            changed = True
        if not changed:
            return
        try:
            save = getattr(self.config, "save_config", None)
            if callable(save):
                save()
        except Exception as exc:
            logger.warning("[amo] 城市跟随：保存天气城市失败: %s" % exc)
        await self.state.refresh_weather(force=True)

    def _sync_weather_city_config(self):
        """配置里填了中文城市名时，自动换算并回填 LocationID（幂等）。"""
        raw = self.cfg_str("weather_city", "").strip()
        if not raw or raw.isdigit() or "," in raw:
            return False
        hit = self._city_lookup(raw)
        if not hit:
            # 同一个错城市名每小时只提醒一次，避免后台 30 秒一轮刷日志
            cache = getattr(self, "_city_warn_cache", None)
            if not isinstance(cache, dict):
                cache = {}
                self._city_warn_cache = cache
            now = time.time()
            if now - to_float(cache.get(raw), 0) > 3600:
                cache[raw] = now
                logger.warning(
                    "[amo] 城市名「%s」不在离线城市表里，天气会退回模拟数据；"
                    "可以写「省+市」或直接填 LocationID" % raw
                )
            return False
        if hit.get("ambiguous"):
            cache = getattr(self, "_city_warn_cache", None)
            if not isinstance(cache, dict):
                cache = {}
                self._city_warn_cache = cache
            now = time.time()
            key = "amb:" + raw
            if now - to_float(cache.get(key), 0) > 3600:
                cache[key] = now
                logger.warning(
                    "[amo] 天气城市%s" % (hit.get("note") or "有多个同名城市，已默认选一个")
                )
        changed = False
        if str(hit["id"]) != raw:
            self.config["weather_city"] = str(hit["id"])
            changed = True
        if not self.cfg_str("weather_city_name", "").strip():
            self.config["weather_city_name"] = hit["name"]
            changed = True
        if changed:
            try:
                if hasattr(self.config, "save_config"):
                    self.config.save_config()
                logger.info("[amo] 城市「%s」→ LocationID %s（已回填）" % (raw, hit["id"]))
            except Exception as exc:
                logger.error("[amo] 回填城市配置失败: %s" % exc)
        return changed


__all__ = [
    "WeatherMixin",
]
