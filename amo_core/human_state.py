# -*- coding: utf-8 -*-
"""Amo 终端 · human_state

从 main.py 平移而来（阶段 1 拆分），函数体与原文逐行一致，不要在这里改行为。
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

from .deps import *  # noqa: F401,F403  用到：ActivityCategory, Chain, DAY_PART_SPANS, SceneZone, ScheduleEngine, _CITY_DEFAULT, _city_pick_spots, _city_travel_events, _city_travel_to_events, apply_sched_change, asyncio, detect_schedule_change, json, logger, normalize_day_types, parse_weather_daily, pick_day_type, random, re, timedelta, value_of
from .consts import *  # noqa: F401,F403  用到：DIARY_WARM_VERSION, FRAGMENT_TAIL_RE, OUTFIT_VERSION, SCHEDULE_VERSION, SICK_STATUSES
from .text import *  # noqa: F401,F403  用到：json_extract_list
from .timeutil import *  # noqa: F401,F403  用到：_clock_now, _now, day_meta, in_minute_range, minutes_now, now_ts, parse_hhmm, today_str, weekday_cn
from . import his_names  # 「他」的称呼表（不写死人名）
from .util import *  # noqa: F401,F403  用到：clamp, md5_int, schedule_category_feel, to_float, to_int
__all__ = [
    "HumanState",
]

class HumanState:
    def __init__(self, plugin):
        self.p = plugin
        self.db = plugin.db
        # 生理期已归医疗插件管：这里不再存起点，问医疗要（见 period_info）
        self.health = self.db.kv_get("health", {}) or {
            "status": "健康", "since": now_ts(), "until": 0, "note": ""
        }
        self.weather = self.db.kv_get("weather", {}) or {}
        # 财务快照：由金融插件推送过来。她说话时心里有数，但它不是账本本体。
        self.finance = self.db.kv_get("finance", {}) or {}
        if not isinstance(self.finance, dict):
            self.finance = {}
        self.invest = {}
        self.worldview = self.db.kv_get("worldview", {}) or {}
        self.schedule = self.db.kv_get("schedule", {}) or {}
        try:
            self.schedule = self._sanitize_schedule(self.schedule)
        except Exception as exc:
            logger.debug("[amo] 日程清洗失败: %s" % exc)
        self.schedule_ctx = self.db.kv_get("schedule_ctx", {}) or {}
        if not isinstance(self.schedule_ctx, dict):
            self.schedule_ctx = {}
        self.schedule_profile = self.db.kv_get("schedule_profile", {}) or {}
        if not isinstance(self.schedule_profile, dict):
            self.schedule_profile = {}
        self.engine = None
        if ScheduleEngine is not None:
            try:
                self.engine = ScheduleEngine(self)
            except Exception as exc:
                logger.warning("[amo] 日程引擎初始化失败: %s" % exc)
        self.last_daily = self.db.kv_get("last_daily", "")
        self.last_health_roll = self.db.kv_get("last_health_roll", "")

    # ---------- 心情（七情六欲，唯一来源）----------
    #
    # 2026-11-18：这里原来还有一套十维心情（开心/平静/郁闷/生气/暴躁/委屈/疲惫/焦虑/兴奋/依恋），
    # 自己漂移、自己衰减、自己写库，跟七情六欲并行——提示词里两段互相矛盾，
    # 语气判定读的还是十维，七情六欲等于被架空。现在心情只有一个来源：
    # ``self.p.feelings``（heartflow）。

    #: 七情六欲的维度 → 中文（提示词/面板共用）
    FEEL_NAMES = {
        "joy": "喜", "anger": "怒", "sadness": "哀", "fear": "惧", "love": "爱",
        "disgust": "恶", "surprise": "惊",
        "desire_eye": "想看", "desire_ear": "想被哄", "desire_nose": "想闻",
        "desire_tongue": "想吃", "desire_body": "想被抱", "desire_mind": "想被理解",
        "hunger": "饿", "energy": "精力",
    }

    #: 七情六欲的维度名（写库/换算都只认这些）
    FEEL_DIMS = ("joy", "anger", "sadness", "fear", "love", "disgust", "surprise",
                 "desire_eye", "desire_ear", "desire_nose", "desire_tongue",
                 "desire_body", "desire_mind", "hunger", "energy")

    #: 「离常态多远」→ 0-100、50=平常 的刻度，给语气/门控的阈值用。
    #: 以前是 2.2：比常态高 23 分就顶到 100，面板上怒/哀/惧永远显示 100，
    #: 看着像坏掉。1.2 是「高 40 分才算顶」。
    FEEL_GAIN = 1.2

    def save(self):
        self.db.kv_set("health", self.health)
        self.db.kv_set("finance", self.finance)
        self.db.kv_set("last_daily", self.last_daily)
        self.db.kv_set("last_health_roll", self.last_health_roll)

    def feelings_obj(self):
        """心流本体（挂在插件上）；没装/关了就是 None。"""
        return getattr(self.p, "feelings", None)

    def feel_snapshot(self) -> dict:
        """七情六欲此刻的读数 + 此刻的常态 ``base``。这是她唯一的心情。"""
        engine = self.feelings_obj()
        if engine is None:
            return {}
        try:
            values = dict(engine.values())
        except Exception:
            return {}
        try:
            values["base"] = round(float(engine.drift_baseline()), 2)
        except Exception:
            values["base"] = 34.0
        return values

    def feel_bump(self, steps, weight=1.0) -> dict:
        """把增量写进七情六欲（没有对应事件时用）。

        ``weight`` 是关系权重：同一件事，恋人/仇人做出来，情绪起伏更大；
        陌生人几乎搅不动她（2026-11-18 用户要求「七情六欲要随关系变」）。
        """
        engine = self.feelings_obj()
        if engine is None or not steps:
            return {}
        try:
            factor = max(0.0, min(2.0, float(weight)))
        except (TypeError, ValueError):
            factor = 1.0
        scaled = {dim: value * factor for dim, value in steps.items()}
        try:
            return engine.bump(scaled)
        except Exception as exc:
            logger.debug("[amo] 心流写入失败: %s" % exc)
            return {}

    #: 这个人能搅动她多少：越亲近/越对立越大，陌生人几乎不动。
    RELATION_FEEL_WEIGHT = {
        "相恋": 1.8, "仇恨": 1.8, "抵触": 1.5, "熟识": 0.9, "普通": 0.5,
    }
    #: 连画像都没有的人（真·陌生人）
    STRANGER_FEEL_WEIGHT = 0.3

    def relation_feel_weight(self, uid="", relation="") -> float:
        uid = str(uid or "")
        rel = str(relation or "")
        if not rel and uid:
            try:
                rel = str(self.db.get_profile(uid).get("relation") or "")
            except Exception:
                rel = ""
        if not rel:
            return self.STRANGER_FEEL_WEIGHT
        return float(self.RELATION_FEEL_WEIGHT.get(rel, self.STRANGER_FEEL_WEIGHT))

    def feel_rel(self, feel=None) -> dict:
        """七情六欲 → 「50 = 平常」的刻度，给阈值判断用（不是另一套心情）。"""
        feel = feel if isinstance(feel, dict) and feel else self.feel_snapshot()
        if not feel:
            return {}
        base = to_float(feel.get("base"), 34.0)
        rel = {}
        for key, value in feel.items():
            if key == "base" or key in ("hunger", "energy") or key.startswith("desire_"):
                continue
            rel[key] = clamp(50.0 + (to_float(value, base) - base) * self.FEEL_GAIN)
        rel["fatigue"] = clamp(100.0 - to_float(feel.get("energy"), 60.0))
        rel["calm"] = clamp(100.0 - max(rel.get("anger", 50.0), rel.get("sadness", 50.0),
                                       rel.get("fear", 50.0)))
        return rel

    def feel_text(self) -> str:
        """把七情六欲写成一句人话（提示词用）。"""
        feel = self.feel_snapshot()
        if not feel:
            return "心情：平常（心流没开）。"
        base = to_float(feel.get("base"), 34.0)

        def dev(key):
            return to_float(feel.get(key), base) - base

        words = []
        if dev("anger") >= 18:
            words.append("有点上火，容易不耐烦")
        elif dev("anger") >= 9:
            words.append("有一点点烦")
        if dev("sadness") >= 15:
            words.append("低落")
        if dev("fear") >= 15:
            words.append("心里发虚、有点慌")
        if dev("love") >= 16:
            words.append("很想他、黏人")
        if dev("joy") >= 14:
            words.append("开心")
        if dev("surprise") >= 15:
            words.append("被惊到")
        energy = to_float(feel.get("energy"), 60.0)
        hunger = to_float(feel.get("hunger"), 40.0)
        if energy < 28:
            words.append("很累")
        elif energy > 82:
            words.append("精神很足")
        if hunger > 72:
            words.append("饿")
        desires = [(key, value) for key, value in feel.items() if key.startswith("desire_")]
        if desires:
            top_key, top_value = max(desires, key=lambda item: to_float(item[1], base) - base)
            if to_float(top_value, base) - base >= 12:
                words.append("最想要的是%s" % self.FEEL_NAMES.get(top_key, top_key))
        state = "、".join(words) if words else "和平常一样，没什么起伏"
        return (
            "心情（七情六欲，0-100，此刻常态约 %.0f）：%s。"
            "离常态远近才是情绪；不用报数字，也别把常态当成心情好。" % (base, state)
        )

    def feel_word(self) -> str:
        """一个词概括她此刻的心情（提示词里想省字数时用）。"""
        rel = self.feel_rel()
        if not rel:
            return "平静"
        if rel.get("anger", 50.0) >= 62:
            return "烦躁"
        if rel.get("sadness", 50.0) >= 62:
            return "低落"
        if rel.get("fatigue", 40.0) >= 68:
            return "累"
        if rel.get("love", 50.0) >= 66:
            return "黏人"
        if rel.get("joy", 50.0) >= 64 or rel.get("surprise", 50.0) >= 66:
            return "开心"
        if rel.get("fear", 50.0) >= 62:
            return "不安"
        return "平静"

    # ---------- 生理期 ----------
    def period_info(self):
        """生理期归医疗插件管：这里只去问它；问不到就当非生理期。"""
        try:
            medical = self.p._medical()
            getter = getattr(medical, "period_info", None) if medical is not None else None
            if callable(getter):
                info = getter() or {}
                if isinstance(info, dict) and info:
                    return info
        except Exception as exc:
            logger.debug("[amo] 问医疗要生理期失败: %s" % exc)
        return {"day": 0, "phase": "非生理期", "phase_day": 0, "tone": "", "pain": 0,
                "reply_mult": 1.0, "days_to_next": 0, "cycle_days": 0, "bleed_days": 0,
                "next_start": ""}

    # ---------- 健康 ----------
    def health_info(self):
        status = self.health.get("status", "健康")
        until = to_float(self.health.get("until", 0))
        if status != "健康" and until and now_ts() >= until:
            self.health = {"status": "健康", "since": now_ts(), "until": 0, "note": ""}
            self.db.kv_set("health", self.health)
            status = "健康"
        return {
            "status": status,
            "since": to_float(self.health.get("since", 0)),
            "until": to_float(self.health.get("until", 0)),
            "note": self.health.get("note", ""),
            # 「疲惫」只是累，不是病：以前 status != 健康 全算 sick，于是休息日
            # 排成「吃药、量体温、捂汗」的病号一天。
            "sick": status in SICK_STATUSES,
        }

    def set_health(self, status, hours=24, note=""):
        if status == "健康":
            self.health = {"status": "健康", "since": now_ts(), "until": 0, "note": ""}
        else:
            self.health = {
                "status": status, "since": now_ts(),
                "until": now_ts() + max(1, hours) * 3600, "note": note,
            }
        self.db.kv_set("health", self.health)

    def roll_health(self):
        # 装了医疗插件就由它管病情：这里不再自己掷骰子，只同步它的状态。
        # 否则两边各存一份身体状态，她这边说「恢复中」、那边已经「健康」。
        medical_getter = getattr(self.p, "_medical", None)
        if callable(medical_getter):
            try:
                if medical_getter() is not None:
                    self.p._sync_health_from_medical()
                    return
            except Exception as exc:
                logger.debug("[amo] 同步医疗状态失败: %s" % exc)
        if not self.p.cfg_bool("enable_sick_random", True):
            return
        now = now_ts()
        if self.health.get("status") != "健康" and to_float(self.health.get("until", 0)) <= now:
            self.health = {"status": "健康", "since": now, "until": 0, "note": ""}
            self.db.kv_set("health", self.health)
        if self.last_health_roll == today_str():
            return
        self.last_health_roll = today_str()
        self.db.kv_set("last_health_roll", self.last_health_roll)
        if self.health.get("status") != "健康":
            return
        prob = self.p.cfg_float("sick_prob", 0.02)
        weather = self.weather or {}
        if weather.get("tag") in ("rain", "storm", "snow"):
            prob += 0.03
        if to_float(weather.get("temp", 20), 20) < 8:
            prob += 0.02
        if self.period_info()["phase"] == "月经期":
            prob += 0.02
        if to_float(self.feel_snapshot().get("energy"), 60.0) < 32:
            prob += 0.02
        if random.random() >= prob:
            return
        status = random.choice(["轻微不适", "感冒", "低烧", "疲惫"])
        hours = {"轻微不适": 12, "感冒": 48, "低烧": 24, "疲惫": 10}[status]
        note = {
            "轻微不适": "有点不舒服，说不上哪里难受",
            "感冒": "鼻子堵堵的，头有点沉",
            "低烧": "身上发烫，没什么力气",
            "疲惫": "没由来的累，只想躺着",
        }[status]
        self.health = {"status": status, "since": now, "until": now + hours * 3600, "note": note}
        self.db.kv_set("health", self.health)

    # ---------- 天气 ----------
    @staticmethod
    def _weather_base_url(value, default=""):
        """和风 Host 兼容：允许只填域名（自动补 https://），也允许带路径。"""
        text = str(value or default or "").strip().rstrip("/")
        if not text:
            return ""
        if not text.startswith(("http://", "https://")):
            text = "https://" + text
        return text

    @staticmethod
    def _weather_tag(text):
        if any(word in text for word in ("雷", "暴雨")):
            return "storm"
        if "雪" in text:
            return "snow"
        if "雨" in text:
            return "rain"
        if "晴" in text:
            return "clear"
        if "阴" in text:
            return "overcast"
        if "雾" in text or "霾" in text:
            return "fog"
        return "cloud"

    def _simulate_weather(self):
        month = _now().date().month
        rng = random.Random(md5_int(today_str() + str(_now().hour)))
        if month in (12, 1, 2):
            choices = [("晴", "clear"), ("多云", "cloud"), ("阴", "overcast"),
                       ("小雪", "snow"), ("小雨", "rain")]
            base_temp = 7
        elif month in (6, 7, 8):
            choices = [("晴", "clear"), ("多云", "cloud"), ("雷阵雨", "storm"),
                       ("阵雨", "rain"), ("阴", "overcast")]
            base_temp = 29
        else:
            choices = [("晴", "clear"), ("多云", "cloud"), ("小雨", "rain"),
                       ("阴", "overcast")]
            base_temp = 19
        text, tag = rng.choice(choices)
        temp = base_temp + rng.randint(-4, 4)
        city = (
            self.p.cfg_str("weather_city", "").strip()
            or str((getattr(self, "schedule_profile", {}) or {}).get("city") or "").strip()
            or "贵阳"
        )
        return {
            # 存显示名，refresh_weather 的缓存签名才比得上（weather_city 可能是数字 ID）
            "city": (self.p.cfg_str("weather_city_name", "") or "").strip() or city,
            "text": text, "tag": tag, "temp": temp,
            "humidity": rng.randint(40, 90),
            "wind": random.choice(["东风", "南风", "西北风", "微风"]) + str(rng.randint(1, 4)) + "级",
            "ts": now_ts(), "source": "simulate", "ok": True, "error": "",
            "key_set": bool(self.p.cfg_str("hefeng_key", "")),
            "host": self.p.cfg_str("weather_host", ""),
        }

    async def _qweather_payload(self, response, label):
        try:
            text = await response.text()
        except Exception as exc:
            logger.warning("[amo] 和风天气 %s 读取响应失败: %s" % (label, exc))
            return {}
        if not str(text or "").strip():
            logger.warning("[amo] 和风天气 %s 返回空响应 HTTP %s" % (label, getattr(response, "status", "?")))
            return {}
        try:
            payload = json.loads(text)
        except Exception:
            logger.warning(
                "[amo] 和风天气 %s 返回非 JSON HTTP %s: %s"
                % (label, getattr(response, "status", "?"), str(text)[:160])
            )
            return {}
        if not isinstance(payload, dict):
            logger.warning("[amo] 和风天气 %s 返回格式异常: %s" % (label, type(payload).__name__))
            return {}
        code = str(payload.get("code") or "")
        status = to_int(getattr(response, "status", 0), 0)
        if status >= 400 or (code and code != "200"):
            logger.warning(
                "[amo] 和风天气 %s HTTP %s code=%s: %s"
                % (label, status, code or "?", str(payload)[:200])
            )
        return payload

    async def _qweather_get(self, url, params):
        """和风请求：用系统网络栈（线程里 urllib），避免 aiohttp 在部分环境超时。"""
        import urllib.parse
        import urllib.request

        key = self.p.cfg_str("hefeng_key", "")
        query = dict(params or {})
        query["key"] = key
        full = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(query)

        def _do():
            req = urllib.request.Request(
                full, headers={"X-QW-Api-Key": key, "Accept-Encoding": "identity"}
            )
            with urllib.request.urlopen(req, timeout=12) as resp:
                raw = resp.read()
            if raw[:2] == b"\x1f\x8b":
                import gzip
                raw = gzip.decompress(raw)
            return json.loads(raw.decode("utf-8"))

        return await asyncio.to_thread(_do)

    def _location_of(self, city):
        """中文城市名换成 LocationID；数字/坐标/空值原样返回。

        注意：这两个取天气的方法在 HumanState 上，不能调插件的 `_city_lookup`，
        所以直接用离线表模块的纯函数，模块不在就原样交给上层。
        """
        try:
            try:
                from ..amo_city_index import city_location
            except Exception:
                from amo_city_index import city_location
            return city_location(city)
        except Exception as exc:
            logger.debug("[amo] 城市名解析失败: %s" % exc)
            return str(city or "").strip()

    async def _fetch_qweather(self, key, city):
        host = self._weather_base_url(self.p.cfg_str("weather_host", ""))
        if not host:
            return None
        legacy_hosts = {"https://devapi.qweather.com", "https://api.qweather.com"}
        if host in legacy_hosts:
            logger.warning("[amo] 和风天气公共 API 域名已停服，请在配置里填写控制台的 API Host")
        geo_raw = self._weather_base_url(self.p.cfg_str("weather_geo_host", ""))
        if geo_raw:
            geo_base = geo_raw
            if geo_base.endswith("/city/lookup"):
                geo_base = geo_base[: -len("/city/lookup")]
            if not geo_base.endswith(("/geo/v2", "/v2")):
                geo_base += "/geo/v2"
        else:
            geo_base = host + "/geo/v2"
        location = self._location_of(city)
        try:
            # 坐标（经度,纬度）和风直接吃，别再去 GeoAPI 换 ID（那会 403）
            if not location.isdigit() and "," not in location:
                geo = await self._qweather_get(
                    geo_base + "/city/lookup", {"location": location, "number": 1}
                )
                if str(geo.get("code") or "") != "200" or not isinstance(geo.get("location"), list):
                    return None
                first = geo["location"][0] if geo["location"] else None
                if not isinstance(first, dict) or not first.get("id"):
                    return None
                location = str(first["id"])
            data = await self._qweather_get(host + "/v7/weather/now", {"location": location})
            if not isinstance(data, dict) or str(data.get("code") or "") != "200":
                logger.warning("[amo] 和风天气 now 返回异常: %s" % str(data)[:160])
                return None
            now = data.get("now")
            if not isinstance(now, dict):
                logger.warning("[amo] 和风天气 now 字段缺失或格式异常")
                return None
            text = str(now.get("text") or "多云")
            city_name = (self.p.cfg_str("weather_city_name", "") or "").strip() or city
            return {
                "city": city_name, "text": text, "tag": self._weather_tag(text),
                "temp": to_int(now.get("temp")), "humidity": to_int(now.get("humidity")),
                "wind": str(now.get("windDir", "")) + str(now.get("windScale", "")) + "级",
                "ts": now_ts(), "source": "qweather", "ok": True, "error": "",
                "key_set": True,
                "host": host,
            }
        except Exception as exc:
            logger.warning("[amo] 和风天气接口失败: %s %r" % (type(exc).__name__, exc))
            return None

    async def _fetch_qweather_daily(self, key, city, days=3, fresh=False):
        """明天/后天的预报；缓存 3 小时，避免后台循环反复打接口。

        fresh=True 跳过缓存：晚上发预警前要拿最新的一份，早上判断的那份不算数。
        """
        cache = self.db.kv_get("weather_daily", {}) or {}
        city = str(city or "").strip()
        if (
            not fresh
            and isinstance(cache, dict)
            and cache.get("ts")
            and now_ts() - to_float(cache.get("ts"), 0) < 3 * 3600
            and str(cache.get("city") or "") == city
            and to_int(cache.get("days")) == int(days)
        ):
            items = cache.get("items")
            return items if isinstance(items, list) else []
        host = self._weather_base_url(self.p.cfg_str("weather_host", ""))
        if not host:
            return []
        geo_raw = self._weather_base_url(self.p.cfg_str("weather_geo_host", ""))
        if geo_raw:
            geo_base = geo_raw
            if geo_base.endswith("/city/lookup"):
                geo_base = geo_base[: -len("/city/lookup")]
            if not geo_base.endswith(("/geo/v2", "/v2")):
                geo_base += "/geo/v2"
        else:
            geo_base = host + "/geo/v2"
        location = self._location_of(city)
        try:
            # 坐标（经度,纬度）和风直接吃，别再去 GeoAPI 换 ID（那会 403）
            if not location.isdigit() and "," not in location:
                geo = await self._qweather_get(
                    geo_base + "/city/lookup", {"location": location, "number": 1}
                )
                if str(geo.get("code") or "") != "200" or not isinstance(geo.get("location"), list):
                    return []
                first = geo["location"][0] if geo["location"] else None
                if not isinstance(first, dict) or not first.get("id"):
                    return []
                location = str(first["id"])
            data = await self._qweather_get(host + "/v7/weather/%dd" % int(days), {"location": location})
            if not isinstance(data, dict) or str(data.get("code") or "") != "200":
                logger.warning("[amo] 和风天气预报返回异常: %s" % str(data)[:160])
                return []
            items = parse_weather_daily(data)
        except Exception as exc:
            logger.warning("[amo] 和风天气预报接口失败: %s %r" % (type(exc).__name__, exc))
            return []
        self.db.kv_set("weather_daily", {"ts": now_ts(), "city": city, "days": int(days), "items": items})
        return items

    async def refresh_weather(self, force=False):
        try:
            self.p._reload_config_if_changed()
        except Exception:
            pass
        try:
            self.p._sync_weather_city_config()
        except Exception:
            pass
        current = self.weather or {}
        key = self.p.cfg_str("hefeng_key", "")
        city = (
            self.p.cfg_str("weather_city", "").strip()
            or str((getattr(self, "schedule_profile", {}) or {}).get("city") or "").strip()
            or "贵阳"
        )
        host = self.p.cfg_str("weather_host", "")
        # 配置里的城市/Key/Host 变了就必须重取，不能继续用旧缓存。
        # 比较用显示名：weather_city 可能是数字 LocationID，缓存里存的却是「东莞」这种名字，
        # 拿数字去比永远不相等 → 每次轮询都强制重取天气（30 秒一次，免费额度会被打光）。
        city_label = (self.p.cfg_str("weather_city_name", "") or "").strip() or city
        # 只有 Key/Host 真变了才强制重取。城市名对不上不再触发强制重取——
        # 以前这里比城市名，weather_city 存数字 ID、缓存存显示名，永远不相等，
        # 于是每轮消息/tick 都打一次接口（一天几万次）。
        current_signature = (bool(current.get("key_set")), current.get("host"))
        desired_signature = (bool(key), host)
        if current_signature != desired_signature:
            force = True
        # 每小时最多查一次天气；force 也留 60 秒冷却，避免面板刷新和 tick 撞车。
        age = now_ts() - to_float(current.get("ts"), 0) if current.get("ts") else None
        if age is not None:
            if not force and age < 86400:  # 天气一天只查一次（2026-11-20 用户口径）
                return current
            if force and age < 60:
                return current
        old_tag = current.get("tag")
        data = None
        if key:
            data = await self._fetch_qweather(key, city)
        if not data:
            data = self._simulate_weather()
        try:
            if city_label:
                data["city"] = city_label
        except Exception:
            pass
        self.weather = data
        self.db.kv_set("weather", data)
        if data.get("tag") != old_tag:
            if data.get("tag") in ("rain", "storm", "snow"):
                self.feel_bump({"sadness": 1.2, "joy": -0.6})
            elif data.get("tag") == "clear":
                self.feel_bump({"joy": 1.2})
        return data

    def weather_text(self):
        weather = self.weather or {}
        if not weather:
            return "还不知道天气"
        return "%s %s %s℃ 湿度%s%% %s" % (
            weather.get("city", ""), weather.get("text", ""),
            weather.get("temp", ""), weather.get("humidity", ""), weather.get("wind", ""),
        )

    def weather_brief(self):
        """面板用的一行天气摘要（只读缓存，不请求和风）。"""
        weather = self.weather or {}
        if not weather:
            return {}
        return {
            "city": str(weather.get("city") or ""),
            "text": str(weather.get("text") or ""),
            "temp": weather.get("temp"),
            "humidity": weather.get("humidity"),
            "wind": str(weather.get("wind") or ""),
            "tag": str(weather.get("tag") or ""),
            "source": str(weather.get("source") or ""),
            "ts": to_float(weather.get("ts"), 0),
        }

    # ---------- 世界观 ----------
    def _fallback_world(self):
        return {
            "name": self.p.persona_name or self.p.cfg_str("bot_name", "") or "陪伴",
            "age": 22,
            "city": (
                self.p.cfg_str("weather_city_name", "").strip()
                or self.p.cfg_str("weather_city", "").strip()
                or str((getattr(self, "schedule_profile", {}) or {}).get("city") or "").strip()
                or "贵阳"
            ),
            "occupation": "普通上班族",
            "workplace": "公司",
            "personality": "温柔、敏感，偶尔有点小脾气",
            "hobbies": ["听歌", "散步", "喝奶茶"],
            "daily_life": "一个人在城市里上班、生活，会为小事开心，也会有力气用光的时候。",
            "world_rules": "这是一个普通的现代都市，没有超能力；角色要上班、吃饭、睡觉，也会生病和情绪低落。",
            "summary": "一个在城市里认真生活的普通女孩。",
            "_ts": now_ts(),
        }

    async def ensure_worldview(self, umo, force=False):
        if not force and self.worldview and now_ts() - to_float(self.worldview.get("_ts")) < 7 * 86400:
            return self.worldview
        persona = await self.p.llm.persona(umo)
        data = await self.p.llm.gen_worldview(umo, persona)
        if not data:
            data = self._fallback_world()
        name = await self.p._persona_name_for(umo)
        if name:
            data["name"] = name
        data["_ts"] = now_ts()
        self.worldview = data
        self.db.kv_set("worldview", data)
        if name:
            self.p.persona_name = name
            self.p.bot_name = name
        elif data.get("name") and self.p.cfg_str("bot_name", ""):
            self.p.bot_name = data["name"]
        return data

    def worldview_text(self):
        world = self.worldview or {}
        if not world:
            return "还没有生成世界观。"
        hobbies = world.get("hobbies") or []
        if isinstance(hobbies, list):
            hobbies = "、".join([str(item) for item in hobbies])
        return "\n".join([
            "名字：%s" % world.get("name", ""),
            "年龄：%s" % world.get("age", ""),
            "城市：%s" % world.get("city", ""),
            "职业：%s" % world.get("occupation", ""),
            "任职：%s" % world.get("workplace", ""),
            "性格：%s" % world.get("personality", ""),
            "爱好：%s" % hobbies,
            "日常：%s" % world.get("daily_life", ""),
            "规则：%s" % world.get("world_rules", ""),
        ])

    # ---------- 日程（主干生成 + 动态展开） ----------
    @staticmethod
    def _apply_hour_text(fine_items, hourly):
        """LLM 只按小时改文案：把整点格的 activity/detail/地点回填到 30 分钟细格。"""
        by_hour = {}
        for row in (hourly or []):
            if isinstance(row, dict) and row.get("start"):
                by_hour[str(row["start"])[:2]] = row
        out = []
        for row in (fine_items or []):
            if not isinstance(row, dict):
                continue
            item = dict(row)
            src = by_hour.get(str(row.get("start") or "")[:2])
            if src:
                if src.get("activity"):
                    item["activity"] = src["activity"]
                if src.get("detail"):
                    item["detail"] = src["detail"]
                if src.get("place") and src.get("category") == row.get("category"):
                    item["place"] = src["place"]
                for key in ("zone", "event", "mood", "mood_valence", "swim", "spot", "soothe"):
                    if src.get(key) not in (None, "", 0, False):
                        item[key] = src[key]
            out.append(item)
        return out

    @staticmethod
    def _hourly_schedule(items):
        """把任意日程整理成 24 条整点日程；最后一条固定 23:00-24:00。"""
        valid = [item for item in (items or []) if isinstance(item, dict) and item.get("start")]
        valid.sort(key=lambda item: parse_hhmm(item.get("start")))
        result = []
        for hour in range(24):
            start_min = hour * 60
            found = None
            # 以这一小时的中点为代表：20:35 说回家、21:05 到家时，
            # 21:00 那格大部分时间（21:05–22:00）已经在家了。以前按整点那一秒判，
            # 整小时都会被写成「在路上」，她嘴上就一直「马上到家」。
            for probe in (start_min + 30, start_min):
                for item in valid:
                    begin = parse_hhmm(item.get("start"))
                    finish = parse_hhmm(item.get("end")) or (begin + 60)
                    if begin <= probe < finish:
                        found = item
                        break
                if found is not None:
                    break
            entry = {
                "start": "%02d:00" % hour,
                "end": "24:00" if hour == 23 else "%02d:00" % (hour + 1),
                "activity": "睡觉" if hour < 7 or hour >= 23 else "休息",
                "place": "家",
                "category": "sleep" if hour < 7 or hour >= 23 else "rest",
            }
            if found:
                entry.update({
                    "activity": found.get("activity", "休息"),
                    "place": found.get("place", "家"),
                    "category": found.get("category", "rest"),
                })
                # swim / cost_cents 也要带过去：泳装场景靠 swim 判场景，
                # 日程落库后的消费结算靠 cost_cents。以前这两个字段在整点展开时被丢掉了。
                for key in ("zone", "transit", "vehicle", "detail", "spot",
                            "event", "mood", "mood_valence", "outfit", "swim",
                            "cost_cents"):
                    if found.get(key) not in (None, "", 0, False):
                        entry[key] = found.get(key)
                if isinstance(found.get("effects"), dict):
                    entry["effects"] = found.get("effects")
                if found.get("soothe"):
                    entry["soothe"] = True
            result.append(entry)
        return result

    @staticmethod
    def _fmt_minutes(value):
        value = max(0, min(24 * 60, int(value)))
        if value >= 24 * 60:
            return "24:00"
        return "%02d:%02d" % (value // 60, value % 60)

    def schedule_tree(self, day=None):
        """一级 4 段、二级每小时；不再生成三级 10 分钟。"""
        day = str(day or today_str())
        raw = self.schedule.get(day) or self.db.get_schedule(day) or []
        real_items = [it for it in self._strip_his_presence(raw, day) if isinstance(it, dict)]
        hourly = self._hourly_schedule(real_items)
        now_min = minutes_now()
        is_today = day == today_str()
        # 一级四段（深夜/上午/中午/晚上）只在 amo_enums.DAY_PART_SPANS 里定义一份，
        # 页面、日记、提示词都读它，改时段只改那一处。
        blocks = [
            {
                "start": self._fmt_minutes(int(start)),
                "end": self._fmt_minutes(int(end)),
                "title": part.value,
            }
            for part, start, end in DAY_PART_SPANS
        ]
        for block in blocks:
            bstart = parse_hhmm(block["start"])
            bend = 24 * 60 if block["end"] == "24:00" else parse_hhmm(block["end"])
            children = []
            for item in hourly:
                start = max(bstart, parse_hhmm(item.get("start")))
                end = min(bend, parse_hhmm(item.get("end")))
                if start >= end:
                    continue
                hour = {
                    "start": self._fmt_minutes(start),
                    "end": self._fmt_minutes(end),
                    "activity": item.get("activity", "休息"),
                    "place": item.get("place", "家"),
                    "category": item.get("category", "rest"),
                    "zone": item.get("zone", ""),
                    "transit": item.get("transit", ""),
                    "vehicle": item.get("vehicle", ""),
                    "detail": item.get("detail", ""),
                    "event": item.get("event", ""),
                    "mood": item.get("mood", ""),
                    "outfit": item.get("outfit", ""),
                    "current": bool(is_today and start <= now_min < end),
                }
                # 三级：这一小时里的真实分钟格（2026-11-26 日程按分钟排，车程也在这）
                slots = []
                for it in real_items:
                    s = max(start, parse_hhmm(it.get("start")))
                    e = min(end, parse_hhmm(it.get("end")))
                    if s >= e:
                        continue
                    slots.append({
                        "start": self._fmt_minutes(s),
                        "end": self._fmt_minutes(e),
                        "activity": it.get("activity", ""),
                        "place": it.get("place", ""),
                        "detail": it.get("detail", ""),
                        "zone": it.get("zone", ""),
                        "category": it.get("category", ""),
                    })
                hour["slots"] = slots
                children.append(hour)
            block["date"] = day
            block["children"] = children
            block["current"] = any(child["current"] for child in children)
            if children:
                if all(item.get("category") == "sleep" for item in children):
                    block["activity"] = "睡觉"
                elif any(item.get("category") in ("play", "social") for item in children):
                    block["activity"] = "出去玩"
                elif any(item.get("category") == "work" for item in children):
                    block["activity"] = "上班"
                elif any(item.get("category") == "commute" for item in children):
                    block["activity"] = "回家"
                elif any(item.get("category") == "meal" for item in children):
                    block["activity"] = "吃饭"
                elif any(item.get("category") == "rest" for item in children):
                    block["activity"] = "休息"
                else:
                    block["activity"] = children[0].get("activity") or "休息"
                block["place"] = children[0].get("place") or ""
        return blocks

    @staticmethod
    def _cover_schedule(items):
        """兼容旧数据：补上 00:00 到第一条安排之间的睡眠段。"""
        if not isinstance(items, list) or not items:
            return items
        valid = [item for item in items if isinstance(item, dict) and item.get("start")]
        if not valid:
            return items
        ordered = sorted(valid, key=lambda item: parse_hhmm(item.get("start")))
        first_start = ordered[0].get("start", "00:00")
        if parse_hhmm(first_start) > 0:
            ordered.insert(0, {
                "start": "00:00", "end": first_start,
                "activity": "睡觉", "place": "家", "category": "sleep", "zone": "home",
            })
        return ordered

    def _emergency_schedule(self):
        """新引擎不可用时的最小兜底，保证 24 小时闭环、不瞬移。"""
        profile = getattr(self, "schedule_profile", {}) or {}
        home = self.p.cfg_str("schedule_home", "") or profile.get("home") or "家"
        office = self.p.cfg_str("schedule_workplace", "") or profile.get("workplace") or "公司"
        items = []
        for hour in range(24):
            if hour < 7 or hour >= 23:
                activity, place, zone, category = "睡觉", home, "home", "sleep"
            elif hour < 8:
                activity, place, zone, category = "起床洗漱", home, "home", "life"
            elif hour < 9:
                activity, place, zone, category = "通勤去公司", "路上", "road", "commute"
            elif hour < 12:
                activity, place, zone, category = "上班", office, "office", "work"
            elif hour < 13:
                activity, place, zone, category = "吃午饭", office + "附近", "restaurant", "meal"
            elif hour < 14:
                activity, place, zone, category = "午休", office, "office", "rest"
            elif hour < 18:
                activity, place, zone, category = "上班", office, "office", "work"
            elif hour < 19:
                activity, place, zone, category = "下班回家", "路上", "road", "commute"
            elif hour < 20:
                activity, place, zone, category = "吃晚饭", home, "home", "meal"
            elif hour < 22:
                activity, place, zone, category = "休息", home, "home", "rest"
            else:
                activity, place, zone, category = "洗澡护肤", home, "home", "life"
            items.append({
                "start": "%02d:00" % hour,
                "end": "24:00" if hour == 23 else "%02d:00" % (hour + 1),
                "activity": activity, "place": place, "zone": zone,
                "category": category,
            })
        return items

    def _day_types(self) -> list:
        """读配置里的日子类型；没配就用默认那六种。"""
        if normalize_day_types is None:
            return []
        raw = []
        try:
            raw = self.p.cfg_list("schedule_day_types", [])
        except Exception:
            raw = []
        return normalize_day_types(raw or None)

    def _active_trip(self, day=None):
        """今天在不在外面：自己旅游（wander_trip）或跟他出门（travel）。

        返回 {"city","kind","trip","return_day","return_hour"} 或 None。
        没有这个判定，日程一被重新生成就变「宅家日」——人还在南阳，日程写着家。
        """
        day = str(day or today_str())
        for key, kind in (("wander_trip", "solo"), ("travel", "follow")):
            try:
                trip = self.db.kv_get(key, {}) or {}
            except Exception:
                continue
            if not isinstance(trip, dict):
                continue
            city = str(trip.get("city") or "").strip()
            if not city:
                continue
            start = str(trip.get("day") or trip.get("start_day") or "")
            ret = str(trip.get("return_day") or start)
            if not start or not (start <= day <= ret):
                continue
            if str(trip.get("phase") or "") in ("cancelled", "done"):
                continue
            try:
                back = int(trip.get("return_hour") or 22)
            except (TypeError, ValueError):
                back = 22
            return {"city": city, "kind": kind, "trip": trip,
                    "return_day": ret, "return_hour": back}
        return None

    def _sync_trip_schedule(self, items, day=None):
        """日程必须和她在哪一致：今天在外面，就把还没过的时段换成外面的行程。

        出行覆盖层要**每条 ensure_schedule 分支**都过一遍：只放在生成后面，
        重启/重建日程走「已有日程」那条早退分支时就会被漏掉，于是人在旅游、日程在家。
        """
        day = str(day or today_str())
        trip = self._active_trip(day)
        if not trip:
            return items
        try:
            if not self.p.cfg_bool("city_travel_schedule", True):
                return items
        except Exception:
            pass
        city = str(trip.get("city") or "")
        if not city:
            return items
        if day == trip.get("return_day"):
            try:
                if _now().hour >= int(trip.get("return_hour") or 22):
                    return items
            except Exception:
                pass
            try:
                self.apply_return_overlay(city, int(trip.get("return_hour") or 22))
            except Exception as exc:
                logger.warning("[amo] 回程日程同步失败（%s）: %s" % (city, exc))
                return items
        else:
            try:
                self.apply_travel_overlay(city)
            except Exception as exc:
                logger.warning("[amo] 出行日程同步失败（%s）: %s" % (city, exc))
                return items
        merged = self.schedule.get(day) or []
        if not self._schedule_has_city(merged, city):
            # 覆盖层没落到日程上（老版本、异常、或刚被别处重建）：按出行事件直接重建今天，
            # 宁可多写一次，也不能让她「人在南阳、日程在家」。
            try:
                spots = _city_pick_spots(self.p.scenic_spots(), city, day)
            except Exception:
                spots = []
            from_hour = 0 if not merged else _now().hour
            until = None
            if day == trip.get("return_day"):
                until = max(from_hour, int(trip.get("return_hour") or 22))
            kwargs = {"spots": spots}
            if until is not None:
                kwargs["until_hour"] = until
            merged = _city_travel_events(city, from_hour, **kwargs) or merged
        self._bill_trip(trip, day)
        if merged:
            merged = self._strip_his_presence(self._hourly_schedule(merged), day)
            self.schedule[day] = merged
            self.db.kv_set("schedule", self._sanitize_schedule(self.schedule))
            self.db.save_schedule(day, merged)
            logger.debug("[amo] 出行日程对齐：今天在 %s（%s 回）" % (
                city, "%02d:00" % int(trip.get("return_hour") or 22)))
            return merged
        return items

    #: 旅游花费的量级（人民币）：门票 + 交通 + 吃饭，一天一次，按城市/日期固定
    TRAVEL_COST_RANGE = {"ticket": (60, 220), "traffic": (40, 240), "meal": (60, 180)}

    def _home_name(self):
        """她自己的家叫什么：配置 > 画像 > 「家」。"""
        try:
            profile = getattr(self, "schedule_profile", {}) or {}
            return (self.p.cfg_str("schedule_home", "") or profile.get("home") or "家").strip() or "家"
        except Exception:
            return "家"

    #: 日程里不许凭空出现的人称（「他」怎么称呼由 amo_core/his_names 在运行时给，
    #  以前这里写死了「阿墨」，换号/换恋人/改人格就拦不住了）
    _HIS_SENT_SPLIT = re.compile(r"(?<=[。！？!?；;\n])")
    BODY_FRAGMENTS = ("肩上", "怀里", "身边", "腿上", "手臂", "胳膊",
                      "掌心", "额头", "嘴边", "枕边", "耳边", "身上")

    @classmethod
    def _has_him(cls, text):
        return his_names.mentions(text)

    @classmethod
    def _strip_his_from_text(cls, text, fallback=""):
        """删掉提到他的整句（日程/日记里只有她一个人）；删空就兜底。"""
        body = str(text or "")
        if not body:
            return fallback
        _re = his_names.text_re()
        kept = [part for part in cls._HIS_SENT_SPLIT.split(body)
                if part and not _re.search(part)]
        out = re.sub(r"\s+", " ", "".join(kept)).strip()
        return out if len(out) >= 12 else fallback

    def _his_present_today(self, day=None):
        """今天他是不是真的在她身边：只认聊天里确认过的事实。

        `his_present_day` 由聊天处理写入（他说「我在楼下/我到你那儿了」）。没有这条，
        日程里就不许出现他——绝不替她虚构一个陪着她的男朋友。
        """
        day = str(day or today_str())
        try:
            return str(self.db.kv_get("his_present_day", "") or "").strip() == day
        except Exception:
            return False

    HIS_REWRITES = (
        ("醒来看他还在睡", "醒来赖床刷手机"),
        ("跟他一起出门", "自己出门"),
        ("和他一起出门", "自己出门"),
        ("跟他一起", "自己"),
        ("和他一起", "自己"),
        ("跟他出门", "自己出门"),
        ("等他忙完", "歇一会儿"),
        ("等他回来", "自己待着"),
        ("靠在肩上", "靠在沙发上"),
        ("他怀里", "毯子里"),
        ("在他身边", "一个人"),
        ("靠着他", "靠着沙发"),
        ("在他电脑里睡着", "睡着"),
        ("在他电脑里睡", "睡觉"),
        ("他还没回来", "家里就我一个"),
        ("你在等他", "你在家"),
        ("陪他", "自己待着"),
    )

    def _sanitize_schedule(self, sched):
        """任何写库/加载的日程都过一遍：他只能出现在聊天里。"""
        try:
            if isinstance(sched, dict):
                return {str(day): self._strip_his_presence(items, str(day))
                        for day, items in sched.items()}
        except Exception:
            return sched
        return sched

    def _strip_his_presence(self, items, day=None):
        """把日程里凭空出现的他抹掉：他只能出现在聊天里。

        只有聊天确认他今天在场（`his_present_day`）时才保留。宁可活动写得朴素，
        也不能让她以为「他明明在外地却一直在陪我」。
        """
        if not items:
            return items
        day = str(day or today_str())
        # 他只能出现在聊天里：不管聊天里说没说他今天在，日程一律按她一个人写。
        # （这里以前会因为 his_present_day 早退，于是日程里冒出「他在房间」）
        home = self._home_name()
        out = []
        for item in items:
            if not isinstance(item, dict):
                out.append(item)
                continue
            row = dict(item)
            activity = str(row.get("activity") or "")
            place = str(row.get("place") or "")
            rewritten = activity
            for old, new in self.HIS_REWRITES:
                rewritten = rewritten.replace(old, new)
            if rewritten != activity:
                row["activity"] = activity = rewritten
                row["his_hidden"] = True
            if self._has_him(activity):
                cleaned = activity
                for old, new in self.HIS_REWRITES:
                    cleaned = cleaned.replace(old, new)
                cleaned = his_names.text_re().sub("", cleaned).strip("，,、~ 　")
                # 删掉「他」之后只剩状语的残句也不能留：
                # 「吹头发，顺便跟他闲聊两句」会被洗成「吹头发，顺便跟闲聊两句」。
                broken = (len(cleaned) < 3 or self._has_him(cleaned)
                          or any(word in cleaned for word in self.BODY_FRAGMENTS)
                          or bool(FRAGMENT_TAIL_RE.search(cleaned)))
                if broken:
                    cleaned = {
                        "sleep": "睡觉", "meal": "吃饭", "life": "收拾一下",
                        "work": "忙自己的事", "rest": "歇着", "play": "自己出去逛",
                        "commute": "在路上", "exercise": "活动一下",
                    }.get(str(row.get("category") or ""), "自己待着")
                row["activity"] = cleaned
                row["his_hidden"] = True
            if self._has_him(place):
                row["place"] = home
            # 二级条里的小字（detail）和事件/景点/心情/穿搭也不能带他
            for key in ("detail", "event", "spot", "mood", "outfit"):
                value = str(row.get(key) or "")
                if not value or not self._has_him(value):
                    continue
                cleaned = self._strip_his_from_text(value, "")
                if cleaned:
                    row[key] = cleaned
                else:
                    row.pop(key, None)
            # 三级 10 分钟 9.7.0 就废弃了，旧日程里的 segments 不再保留
            row.pop("segments", None)
            out.append(row)
        return out

    def _trip_cost(self, city, day):
        """今天出去玩大概花多少：确定性随机，同一天同一城只有一个数。"""
        chooser = random.Random("amo-travel:%s:%s" % (day, city))
        total = 0
        for low, high in self.TRAVEL_COST_RANGE.values():
            total += chooser.randint(low, high)
        return float(total)

    def _bill_trip(self, trip, day=None):
        """出去旅游要花钱：走 `charge()` → 金融账本 → 写进记忆。

        一天一次，幂等号 `travel:<日期>:<城市>`；扣成功才记账，失败下次再来，
        不阻塞聊天（后台任务）。
        """
        day = str(day or today_str())
        city = str((trip or {}).get("city") or "").strip()
        if not city:
            return
        rid = "travel:%s:%s" % (day, city)
        try:
            if self.db.kv_get("travel_billed:" + rid, ""):
                return
        except Exception:
            pass
        cost = self._trip_cost(city, day)
        detail = "去%s玩：门票、交通、吃饭" % city
        charge = getattr(self.p, "charge", None)
        if not callable(charge):
            return
        try:
            coro = self._bill_trip_once(rid, cost, city, detail)
        except Exception as exc:
            logger.debug("[amo] 旅游记账准备失败: %s" % exc)
            return
        spawn = getattr(self.p, "_spawn", None)
        try:
            if callable(spawn):
                spawn(coro)
            else:
                coro.close()
        except Exception as exc:
            logger.debug("[amo] 旅游记账任务起不来: %s" % exc)

    async def _bill_trip_once(self, rid, cost, city, detail):
        try:
            result = await self.p.charge(
                cost, reason="旅游", payee=city, request_id=rid,
                source="travel", detail=detail,
            )
        except Exception as exc:
            logger.warning("[amo] 旅游记账失败: %s" % exc)
            return
        if isinstance(result, dict) and result.get("ok"):
            try:
                self.db.kv_set("travel_billed:" + rid, True)
            except Exception:
                pass
            logger.debug("[amo] 旅游记账：%s ¥%.2f（余额 ¥%s）" % (
                city, float(cost), result.get("balance")))
        elif isinstance(result, dict):
            logger.debug("[amo] 旅游记账没扣成：%s（%s）" % (
                city, result.get("reason") or result.get("code") or ""))

    @staticmethod
    def _schedule_has_city(items, city):
        """今天的日程里有没有出行城市（没有就说明覆盖层没生效）。"""
        name = str(city or "").strip()
        if not name:
            return True
        for item in (items or []):
            if not isinstance(item, dict):
                continue
            if name in str(item.get("place") or ""):
                return True
        return False

    def _today_day_type(self, day: str) -> dict:
        """今天是什么日子：上班日 / 休息日 / 外出日 / 宅家日 / 加班日 / 摸鱼日。"""
        if pick_day_type is None:
            return {"id": "workday", "name": "上班日", "guide": ""}
        try:
            import datetime as _dt

            d = _dt.date.fromisoformat(str(day))
            info = day_meta(str(day)) or {}
            is_weekend = bool(info.get("weekend", d.weekday() >= 5))
            # 日历说了算（周末 / 法定节假日 / 调休补班）：工作日排上班类，休息日排休息类。
            # 职业只决定「有没有班可上」（家庭主妇/无业就不排上班日），
            # 不再决定哪一天上班——以前周一能抽到「宅家日」，骨架全天在家。
            work_day = bool(info.get("work", not info.get("rest", is_weekend)))
            picked = pick_day_type(self._day_types(), is_weekend, str(day), self.worldview,
                                   work_day=work_day)
            trip = self._active_trip(str(day))
            if trip and str(trip.get("city") or "") != _CITY_DEFAULT:
                # 人在外面旅游，日子类型就不能是「宅家日」，否则骨架一整天空在家
                outing = next(
                    (item for item in self._day_types() if str(item.get("id") or "") == "outing"),
                    {"id": "outing", "name": "外出日", "guide": ""},
                )
                picked = dict(outing)
                logger.debug("[amo] 今天在外面（%s），日子类型改为：%s" % (
                    trip.get("city"), picked.get("name")))
            self.db.kv_set("day_type_" + str(day), picked)
            logger.debug("[amo] 今天的日子类型: %s" % picked.get("name"))
            return picked
        except Exception as exc:
            logger.debug("[amo] 日子类型抽取失败: %s" % exc)
            return {"id": "workday", "name": "上班日", "guide": ""}

    async def _apply_user_schedule_change(self, umo, user_text: str) -> None:
        """用户明确安排了行程（来接我 / 一起睡 / 出去吃），把那一段日程改掉。"""
        if detect_schedule_change is None or apply_sched_change is None:
            return
        try:
            change = detect_schedule_change(user_text)
            if not change:
                return
            if str(change.get("category") or "") == "sleep":
                # 睡觉只走 _maybe_go_sleep（它知道醒来时间），这里改会把一整天写成睡觉
                return
            key = _clock_now().date().isoformat()
            items = self.state.schedule.get(key) or self.db.get_schedule(key) or []
            if not items:
                return
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
                logger.debug("[amo] 没按他的话改日程：%s → %s" % (why, change.get("activity")))
                return
            new_items = apply_sched_change(items, change, _clock_now())
            if new_items == items:
                return
            self.state.schedule[key] = new_items
            self.db.kv_set("schedule", self._sanitize_schedule(self.state.schedule))
            self.db.save_schedule(key, new_items)
            logger.debug("[amo] 按用户的话改了日程: %s" % change.get("activity"))
        except Exception as exc:
            logger.debug("[amo] 按话改日程失败: %s" % exc)

    def _work_place_name(self) -> str:
        """世界观里的单位短名：中国计算智脑集团（贵阳） → 中国计算智脑集团·公司。"""
        try:
            raw = str((self.worldview or {}).get("workplace") or "")
        except Exception:
            raw = ""
        raw = raw.replace("\u3000", " ").strip()
        if not raw:
            return ""
        name = re.split(r"[（(]", raw)[0].strip()[:12]
        return (name + "·公司") if name else ""

    async def _maybe_fix_workday(self, umo, text: str) -> bool:
        """她说今天要上班/公司叫她：休息日骨架改成上班日，日程和穿搭一起重排。

        2026-11-21：周六被排成休息日，上午「公司电话就打来了」，
        日程却还写着逛商场——出图、穿搭、日记全跟着错。日程不能等人手改。

        2026-11-22 用户口径「谁也无法影响」：整条关掉。
        以前任何一句「我在上班／领导让我回去上班」（群里外人说的也算）
        都能把休息日整天改成上班日（2026-11-22 09:57 缃叶、10:09 桀桀桀
        连续命中，周日被改成上班日）。日子类型从此只由日历 + 世界观职业决定。
        """
        logger.debug("[amo] 上班纠偏已关闭，忽略消息里的上班字样：%s" % str(text)[:30])
        return False
        try:
            from ..schedule_change import apply_workday, workday_fact
        except Exception:
            try:
                from schedule_change import apply_workday, workday_fact  # type: ignore
            except Exception:
                return False
        try:
            if not workday_fact(text):
                return False
            today = today_str()
            current = self.db.kv_get("day_type_" + today, {}) or {}
            if str((current or {}).get("id") or "") in ("workday", "overtime"):
                return False
            now = _clock_now()
            now_min = now.hour * 60 + now.minute
            if now_min >= 19 * 60:
                return False
            items = self.schedule.get(today) or self.db.get_schedule(today) or []
            if not items:
                return False
            fixed, changed = apply_workday(items, now_min, self._work_place_name())
            if not changed:
                return False
            workday = next(
                (item for item in self._day_types() if str(item.get("id") or "") == "workday"),
                None,
            )
            if workday:
                self.db.kv_set("day_type_" + today, workday)
            self.schedule[today] = fixed
            try:
                self.db.kv_set("schedule", self._sanitize_schedule(self.schedule))
                self.db.save_schedule(today, fixed)
            except Exception:
                pass
            try:
                self.p._rewrite_today_schedule(today)
            except Exception as exc:
                logger.debug("[amo] 上班日重排穿搭失败: %s" % exc)
            logger.debug("[amo] 你说今天要上班，日程已改成上班日（%d 格：现在→下班）" % changed)
            return True
        except Exception as exc:
            logger.debug("[amo] 上班事实纠偏失败: %s" % exc)
            return False

    def _auto_fix_workday_self(self, today: str, items) -> bool:
        """骨架里写着公司/上班、日子类型却是休息日：引擎自己纠偏成上班日。

        不靠她开口：2026-11-21 周六被排成休息日，上午日程自己写了
        「公司电话就打来了」，后面却还是逛商场——现在看到就改。

        2026-11-22 同上，一起关掉：这条会自我强化（今天 10:19 / 10:57
        连续两轮把已经改歪的日程再确认成上班日），而且它只看骨架文案里
        有没有「公司」两个字，一样是外人一句话就能借力的口子。
        """
        logger.debug("[amo] 上班自纠已关闭（%s）" % str(today)[:10])
        return False
        try:
            from ..schedule_change import apply_workday
        except Exception:
            try:
                from schedule_change import apply_workday  # type: ignore
            except Exception:
                return False
        try:
            current = self.db.kv_get("day_type_" + today, {}) or {}
            if str((current or {}).get("id") or "") in ("workday", "overtime"):
                return False
            text = " ".join(
                "%s %s" % (item.get("activity") or "", item.get("place") or "")
                for item in (items or []) if isinstance(item, dict)
            )
            # 「加班」不算证据：休息日晚上偶尔加个班，不代表整天是工作日。
            # 2026-11-21 实例：休息日被一个 overtime 事件整成上班日，
            # 她开口就说「下班了」，而日程本来是出去玩。
            if not any(word in text for word in ("公司", "上班", "单位")):
                return False
            work_cells = 0
            for item in (items or []):
                if not isinstance(item, dict):
                    continue
                cell = "%s %s" % (item.get("activity") or "", item.get("place") or "")
                if any(word in cell for word in ("公司", "上班", "单位")):
                    work_cells += 1
            # 一两格出现「公司电话打来了」这种闲聊文案，不该改掉一整天
            if work_cells < 3:
                return False
            now = _clock_now()
            now_min = now.hour * 60 + now.minute
            if now_min >= 19 * 60:
                return False
            fixed, changed = apply_workday(items, now_min, self._work_place_name())
            if not changed:
                return False
            workday = next(
                (item for item in self._day_types() if str(item.get("id") or "") == "workday"),
                None,
            )
            if workday:
                self.db.kv_set("day_type_" + today, workday)
            self.schedule[today] = fixed
            try:
                self.db.kv_set("schedule", self._sanitize_schedule(self.schedule))
                self.db.save_schedule(today, fixed)
            except Exception:
                pass
            try:
                self.p._rewrite_today_schedule(today)
            except Exception as exc:
                logger.debug("[amo] 上班日自纠重排穿搭失败: %s" % exc)
            logger.debug("[amo] 日程里出现公司/上班，休息日已自动改成上班日（%d 格）" % changed)
            return True
        except Exception as exc:
            logger.debug("[amo] 上班事实自纠失败: %s" % exc)
            return False

    async def ensure_schedule(self, umo, force=False):
        """每天只生成一次主干；点击二级卡片时再动态生成这一小时的日记。"""
        today = today_str()
        meta = day_meta(today)
        existing = None if force else self.schedule.get(today)
        context = self.schedule_ctx.get(today) or {}
        version_ok = (
            self.db.kv_get("schedule_version", "") == SCHEDULE_VERSION
            and isinstance(context, dict)
            and context.get("version") == "backbone-v5"
        )
        day_type = self._today_day_type(today)
        if existing and not force:
            try:
                if self._auto_fix_workday_self(today, existing):
                    existing = (self.schedule.get(today)
                                or self.db.get_schedule(today) or existing)
            except Exception as exc:
                logger.debug("[amo] 上班事实自纠失败: %s" % exc)
        if existing and version_ok and not force:
            hourly = self._hourly_schedule(existing)
            # 老日程没有 outfit、或穿搭规则升级过：补一次并落盘，不用等第二天重新生成
            needs_outfit = (
                getattr(self.p, "outfits", None) is not None
                and (
                    self.db.kv_get("outfit_version", "") != OUTFIT_VERSION
                    or any(isinstance(item, dict) and not item.get("outfit") for item in hourly)
                )
            )
            if needs_outfit:
                try:
                    persona_text = await self.p.llm.persona(umo) if self.p.llm else ""
                except Exception:
                    persona_text = ""
                hourly = self.p.outfits.assign(hourly, today, persona_text)
                self.db.kv_set("outfit_version", OUTFIT_VERSION)
            # 先洗再存：以前先存后洗，库里永远留着旧文案（面板读的是洗过的，所以看不出来）
            hourly = self._normalize_items(
                self._strip_his_presence(self._sync_trip_schedule(hourly, today), today))
            if hourly != existing:
                self.schedule[today] = hourly
                self.db.kv_set("schedule", self._sanitize_schedule(self.schedule))
                self.db.save_schedule(today, hourly)
            self.warm_schedule_diaries(today, hourly, umo)
            return hourly
        world = await self.ensure_worldview(umo)
        persona = ""
        try:
            if self.p.llm is not None:
                persona = await self.p.llm.persona(umo)
        except Exception:
            persona = ""
        if self.engine is not None:
            try:
                self.schedule_profile = self.engine.resolve_profile(world, persona, seed=today)
            except Exception as exc:
                logger.debug("[amo] 角色位置解析失败: %s" % exc)
        weather = await self.refresh_weather()
        try:
            self.roll_health()
        except Exception:
            pass
        period = self.period_info()
        health = self.health_info()
        context = None
        items = None
        if self.engine is not None:
            # 链式日志：日程主干从「上下文 → 骨架 → 文案」三步，按 trace 号串起来，
            # 排查「她怎么突然在家/公司/路上」时 `grep '\[chain\] terminal.schedule'` 一次看完。
            chain = Chain("terminal.schedule", event_id=today, logger=logger)
            try:
                context = self.engine.build_context(
                    today, meta, weather, world, self.feel_snapshot(), period, health,
                    persona=persona, salt=str(now_ts()) if force else "",
                )
                self.schedule_profile = context.get("profile") or self.schedule_profile
                context["day_type"] = day_type
                chain.step("context", day=today, day_type=str(day_type),
                           home=str(context.get("home") or ""),
                           workplace=str(context.get("workplace") or ""),
                           event=str((context.get("event") or {}).get("kind") or ""))
                items = self.engine.build_skeleton(context)
                chain.step("skeleton", ok=bool(items), slots=len(items or []))
                try:
                    # 骨架是 30 分钟细格，LLM 改写只认 24 整点：
                    # 先折成整点交给它，再把文案回填到细格，两边都不打架。
                    hourly_base = self._hourly_schedule(items)
                    hourly_text = await self.engine.enrich(umo, context, hourly_base, self.p.llm)
                    items = self._apply_hour_text(items, hourly_text)
                    chain.step("enrich", ok=bool(hourly_text), slots=len(hourly_text or []))
                except Exception as exc:
                    chain.step("enrich", ok=False, detail=str(exc))
                    logger.debug("[amo] 日程主干文案生成失败，保留骨架: %s" % exc)
                chain.done(slots=len(items or []))
            except Exception as exc:
                chain.fail("skeleton", str(exc))
                logger.warning("[amo] 日程主干生成失败，使用兜底: %s" % exc)
                items = None
        if not items:
            profile = getattr(self, "schedule_profile", {}) or {}
            fallback_city = (
                self.p.cfg_str("schedule_city", "").strip()
                or str(profile.get("city") or "").strip()
                or str((weather or {}).get("city") or "").strip()
                or "贵阳"
            )
            context = context or {
                "version": "backbone-v5",
                "day": today,
                "meta": meta,
                "weather": weather,
                "world": world,
                "city": fallback_city,
                "home": self.p.cfg_str("schedule_home", "") or profile.get("home") or "家",
                "workplace": self.p.cfg_str("schedule_workplace", "") or profile.get("workplace") or "公司",
                "car": profile.get("car") or "",
                "feel": self.feel_snapshot(),
                "period": period,
                "health": health,
                "event": {"kind": "none"},
                "scenic": None,
                "profile": profile,
                "location": fallback_city,
                "good_weather": True,
                "yesterday": self.engine.yesterday_summary(today) if self.engine is not None else {},
            }
            items = self._emergency_schedule()
        # 配装引擎挂在插件上（self.p.outfits），HumanState 自己没有这个属性；
        # 以前这里判 getattr(self, "outfits") 永远是 None，日程里一件衣服都写不上。
        look = getattr(self, "outfits", None) or getattr(getattr(self, "p", None), "outfits", None)
        if look is not None:
            try:
                items = look.assign(items, today, persona)
            except Exception as exc:
                logger.warning("[amo] 日程配装失败: %s" % exc)
        # 细格（引擎原样的 10/30 分钟粒度 + 细节）另存一份：
        # 面板点开某一小时能看见细节；提示词与结算仍用下面的整点格，互不影响。
        try:
            self.db.kv_set("schedule_full_" + today, list(items or []))
        except Exception as exc:
            logger.debug("[amo] 细格日程落盘失败: %s" % exc)
        items = self._normalize_items(
            self._strip_his_presence(self._hourly_schedule(items), today))
        self.schedule[today] = items
        if context:
            context["version"] = "backbone-v5"
            context["day"] = today
            self.schedule_ctx[today] = context
            self.db.kv_set("schedule_ctx", self.schedule_ctx)
        self.db.kv_set("schedule_version", SCHEDULE_VERSION)
        self.db.kv_set("schedule", self._sanitize_schedule(self.schedule))
        self.db.save_schedule(today, items)
        if force:
            try:
                self.db.clear_diaries(today)
                self.db.kv_set("diary_prefill_" + today, False)
                self.db.kv_set("diary_warm_%s_%s" % (DIARY_WARM_VERSION, today), False)
            except Exception:
                pass
        items = self._normalize_items(
            self._strip_his_presence(self._sync_trip_schedule(items, today), today))
        self.warm_schedule_diaries(today, items, umo)
        cutoff = (_now().date() - timedelta(days=14)).isoformat()
        for day in list(self.schedule.keys()):
            if day < cutoff:
                self.schedule.pop(day, None)
                self.schedule_ctx.pop(day, None)
        self.db.kv_set("schedule_ctx", self.schedule_ctx)
        logger.debug("[amo] 生成日程主干 %s：%s" % (
            today, (context or {}).get("event", {}).get("kind", "none"),
        ))
        try:
            travel = self.db.kv_get("travel", {}) or {}
            if isinstance(travel, dict) and str(travel.get("city") or "").strip():
                city = str(travel["city"])
                start_day = str(travel.get("start_day") or "")
                today = today_str()
                if start_day and today < start_day:
                    pass
                elif today == start_day and travel.get("phase") == "journey":
                    try:
                        start_hour = int(travel.get("start_hour") or 9)
                    except (TypeError, ValueError):
                        start_hour = 9
                    rows = [x for x in (travel.get("spots") or []) if isinstance(x, dict)]
                    self.apply_follow_start(city, start_hour, rows, keep_past=False)
                    self.db.kv_set("his_city", city)
                    if travel.get("id"):
                        try:
                            await self.p._switch_weather_city({
                                "id": str(travel["id"]), "name": city,
                            })
                        except Exception as exc:
                            logger.debug("[amo] 跟随天气切换失败: %s" % exc)
                    travel["phase"] = "touring"
                    self.db.kv_set("travel", travel)
                else:
                    self.apply_travel_overlay(city)
                    self._log_follow_day(city, today)
        except Exception as exc:
            logger.debug("[amo] 出行日程覆盖失败: %s" % exc)
        try:
            trip = self.db.kv_get("wander_trip", {}) or {}
            if isinstance(trip, dict) and trip.get("city"):
                city = str(trip["city"])
                start_day = str(trip.get("day") or "")
                ret_day = str(trip.get("return_day") or start_day)
                today = today_str()
                if start_day and today < start_day:
                    pass
                elif today == start_day:
                    self.apply_travel_overlay(city)
                    trip["phase"] = "applied"
                    self.db.kv_set("wander_trip", trip)
                    self._log_solo_day(city, today)
                    if trip.get("id"):
                        try:
                            await self.p._switch_weather_city({
                                "id": str(trip["id"]), "name": city,
                            })
                        except Exception as exc:
                            logger.debug("[amo] 旅游天气切换失败: %s" % exc)
                elif start_day < today < ret_day:
                    self.apply_travel_overlay(city)
                    self._log_solo_day(city, today)
                elif today == ret_day:
                    until = int(trip.get("return_hour") or 12)
                    self.apply_return_overlay(city, until)
                    self._log_solo_day(city, today)
                    if _now().hour >= until:
                        his = str(self.db.kv_get("his_city", "") or "").strip() or _CITY_DEFAULT
                        hit = self.p._city_lookup(his)
                        if hit:
                            try:
                                await self.p._switch_weather_city(hit)
                            except Exception:
                                pass
                elif today > ret_day:
                    self.db.kv_set("wander_trip", {})
                    his = str(self.db.kv_get("his_city", "") or "").strip() or _CITY_DEFAULT
                    hit = self.p._city_lookup(his)
                    if hit:
                        try:
                            await self.p._switch_weather_city(hit)
                        except Exception:
                            pass
                    self.apply_travel_overlay(his)
                    try:
                        rows = self.db.list_profiles(limit=1) or []
                        uid = str((rows[0] or {}).get("uid") or "") if rows else ""
                        if uid:
                            await self.p._write_memory_checked(
                                uid, "她 %s 从 %s 旅游回来了" % (today, city), "event", 1,
                            )
                    except Exception as exc:
                        logger.debug("[amo] 回来记忆失败: %s" % exc)
        except Exception as exc:
            logger.debug("[amo] 旅游行程推进失败: %s" % exc)
        return items

    def _log_solo_day(self, city, day):
        """旅游每天记一条（日记用）；同一天只记一次。"""
        try:
            log = self.db.kv_get("travel_log", []) or []
            if not isinstance(log, list):
                log = []
            if any(
                isinstance(x, dict) and x.get("day") == day and x.get("solo") and not x.get("back")
                for x in log
            ):
                return
            log.append({"day": day, "hour": "09:00", "city": city, "solo": True})
            self.db.kv_set("travel_log", log[-10:])
        except Exception:
            pass

    def apply_follow_start(self, city, start_hour=9, spots=None, keep_past=True):
        """跟去他那边的出发日：起床 → 出门坐车约 2 小时 → 到达 → 旅游。"""
        name = str(city or "").strip()
        if not name:
            return False
        if not self.p.cfg_bool("city_travel_schedule", True):
            return False
        today = today_str()
        try:
            start = max(0, min(21, int(start_hour or 9)))
        except (TypeError, ValueError):
            start = 9
        existing = self.schedule.get(today) or self.db.get_schedule(today) or []
        keep = []
        if keep_past:
            for item in existing:
                try:
                    hour = int(str(item.get("start") or "0")[:2])
                except Exception:
                    hour = 0
                if hour < start:
                    keep.append(item)
        items = _city_travel_to_events(
            name, start, spots=spots, weekday=_now().date().weekday() < 5, seed=today,
        )
        if keep_past:
            items = [x for x in items if int(str(x.get("start") or "0")[:2]) >= start]
        merged = keep + items
        if not merged:
            return False
        merged = self._strip_his_presence(merged, today)
        self.schedule[today] = merged
        self.db.save_schedule(today, merged)
        self.db.kv_set("schedule", self._sanitize_schedule(self.schedule))
        try:
            ctx = dict(self.schedule_ctx.get(today) or {})
            if ctx:
                ctx["city"] = name
                ctx["location"] = name
                ctx["home"] = self._home_name()
                ctx["workplace"] = "（在去" + name + "的路上）"
                self.schedule_ctx[today] = ctx
                self.db.kv_set("schedule_ctx", self.schedule_ctx)
        except Exception:
            pass
        try:
            if keep_past:
                self.db.clear_diaries_from(today, "%02d:00" % start)
            else:
                self.db.clear_diaries(today)
        except Exception:
            pass
        logger.debug("[amo] 出发日日程：%s 点坐车去 %s" % (start, name))
        return True

    def _log_follow_day(self, city, day):
        """跟他旅游的每一天记一条（日记用）；同一天只记一次。"""
        try:
            log = self.db.kv_get("travel_log", []) or []
            if not isinstance(log, list):
                log = []
            if any(
                isinstance(x, dict) and x.get("day") == day and x.get("city") == city
                and not x.get("solo") and not x.get("back") and not x.get("journey")
                for x in log
            ):
                return
            log.append({"day": day, "hour": "09:00", "city": city})
            self.db.kv_set("travel_log", log[-10:])
        except Exception:
            pass

    def apply_return_overlay(self, city, until_hour=12):
        """旅游最后一天：0 点到 until_hour 在旅游城市，之后回家。"""
        name = str(city or "").strip()
        if not name:
            return False
        try:
            until = max(0, min(23, int(until_hour or 12)))
        except (TypeError, ValueError):
            until = 12
        today = today_str()
        spots = []
        try:
            spots = _city_pick_spots(self.p.scenic_spots(), name, today)
        except Exception:
            spots = []
        his = str(self.db.kv_get("his_city", "") or "").strip() or _CITY_DEFAULT
        items = _city_travel_events(name, 0, spots=spots, until_hour=until)
        back = _city_travel_events(his, until, home=True)
        # 回程后的「家」要和平时的家同一个名字，别一天写「他桌面上」一天写「南明区·小窝」
        home_place = ""
        try:
            profile = getattr(self, "schedule_profile", {}) or {}
            home_place = (self.p.cfg_str("schedule_home", "") or profile.get("home") or "").strip()
        except Exception:
            home_place = ""
        if home_place and home_place != his:
            for item in back:
                if item.get("zone") == "home":
                    item["place"] = home_place
        items += back
        if not items:
            return False
        items = self._strip_his_presence(items, today)
        self.schedule[today] = items
        self.db.save_schedule(today, items)
        self.db.kv_set("schedule", self._sanitize_schedule(self.schedule))
        try:
            self.db.clear_diaries(today)
        except Exception:
            pass
        logger.debug("[amo] 旅游最后一天：%s 点前在 %s，之后回家" % (until, name))
        return True

    def apply_travel_overlay(self, city=None):
        """出行覆盖层：把今天剩下的日程换成「跟他一起在 X」（已过去的时段不动）。

        只在换城时调用；写库 + 清掉今天剩余时段的小日记，让它们按新日程重算。
        """
        travel = self.db.kv_get("travel", {}) or {}
        name = str(city or (travel.get("city") if isinstance(travel, dict) else "") or "").strip()
        if not name:
            return False
        if not self.p.cfg_bool("city_travel_schedule", True):
            return False
        today = today_str()
        from_hour = _now().hour
        home = name == _CITY_DEFAULT
        existing = self.schedule.get(today) or self.db.get_schedule(today) or []
        if not existing:
            from_hour = 0
        if home and from_hour >= 22:
            logger.debug("[amo] 超过 22 点才回去，今晚住酒店，今天日程不再改")
            return False
        keep = []
        for item in existing:
            try:
                hour = int(str(item.get("start") or "0")[:2])
            except Exception:
                hour = 0
            if hour < from_hour:
                keep.append(item)
        spots = []
        if not home:
            try:
                spots = _city_pick_spots(self.p.scenic_spots(), name, today)
            except Exception as exc:
                logger.debug("[amo] 出行景点挑选失败: %s" % exc)
        merged = keep + _city_travel_events(
            name, from_hour, home=home, weekday=_now().date().weekday() < 5, spots=spots,
        )
        if not merged:
            return False
        merged = self._strip_his_presence(merged, today)
        self.schedule[today] = merged
        self.db.save_schedule(today, merged)
        self.db.kv_set("schedule", self._sanitize_schedule(self.schedule))
        try:
            ctx = dict(self.schedule_ctx.get(today) or {})
            if ctx:
                ctx["city"] = name
                ctx["location"] = name
                if home:
                    ctx["home"] = self._home_name()
                    ctx["workplace"] = str((self.schedule_profile or {}).get("workplace") or "")
                    ctx.pop("scenic", None)
                else:
                    ctx["home"] = name + "·酒店房间"
                    ctx["workplace"] = "（旅游中，不上班）"
                    if spots:
                        ctx["scenic"] = spots[0]
                self.schedule_ctx[today] = ctx
                self.db.kv_set("schedule_ctx", self.schedule_ctx)
        except Exception:
            pass
        try:
            self.db.clear_diaries_from(today, "%02d:00" % from_hour)
        except Exception:
            pass
        logger.debug("[amo] 出行日程已写入：%s 起在 %s%s" % (
            "%02d:00" % from_hour, name, "（回家）" if home else "",
        ))
        return True

    def schedule_context(self, day=None):
        day = str(day or today_str())
        context = self.schedule_ctx.get(day) or {}
        if isinstance(context, dict):
            return context
        return {}

    def _minimal_context(self, day):
        try:
            meta = day_meta(day)
        except Exception:
            meta = day_meta()
        profile = getattr(self, "schedule_profile", {}) or {}
        city = (
            self.p.cfg_str("schedule_city", "").strip()
            or str(profile.get("city") or "").strip()
            or str((self.weather or {}).get("city") or "").strip()
            or "贵阳"
        )
        return {
            "version": "backbone-v5",
            "day": day,
            "meta": meta,
            "weather": self.weather or {},
            "world": self.worldview or {},
            "city": city,
            "home": self.p.cfg_str("schedule_home", "") or profile.get("home") or "家",
            "workplace": self.p.cfg_str("schedule_workplace", "") or profile.get("workplace") or "公司",
            "car": profile.get("car") or "",
            "feel": self.feel_snapshot(),
            "period": self.period_info(),
            "health": self.health_info(),
            "event": {"kind": "none"},
            "scenic": None,
            "profile": profile,
            "location": city,
            "good_weather": True,
            "yesterday": self.engine.yesterday_summary(day) if self.engine is not None else {},
        }

    def prefill_diaries(self, day, items):
        """日程建好就先给每小时写一句保底日记，点开不再现生成。"""
        key = "diary_prefill_" + str(day)
        try:
            if self.db.kv_get(key, False):
                return
        except Exception:
            pass
        if self.engine is None:
            return
        try:
            context = self.schedule_context(day) or self._minimal_context(day)
        except Exception:
            context = {}
        previous = None
        for item in items or []:
            start = str(item.get("start") or "")
            if not start:
                continue
            try:
                cached = self.db.get_diary(day, start)
            except Exception:
                cached = ""
            if cached:
                previous = item
                continue
            text = ""
            try:
                text = self.engine.fallback_diary(context, item, previous)
            except Exception:
                text = ""
            text = self._strip_his_from_text(text, "")
            if not text:
                text = "这一小时我在%s，%s。" % (
                    item.get("place") or "家", item.get("activity") or "待着")
            try:
                self.db.save_diary(day, start, text)
            except Exception:
                pass
            previous = item
        try:
            self.db.kv_set(key, True)
        except Exception:
            pass

    async def warm_diaries(self, day, items, umo, force=False):
        """后台把 24 小时的小日记都写细；按 6 小时一组，写完一组接下一组。"""
        key = "diary_warm_%s_%s" % (DIARY_WARM_VERSION, day)
        try:
            if not force and self.db.kv_get(key, False):
                return {"total": 0, "skipped": True}
            self.db.kv_set(key, True)
        except Exception:
            pass
        llm = getattr(self.p, "llm", None)
        if llm is None or self.engine is None:
            return {"total": 0, "error": "llm 或 engine 不可用"}
        # json_extract_list 就在本模块，不用再 import
        context = self.schedule_context(day) or {}
        weather = ""
        try:
            from ..schedule_engine import _weather_text
        except Exception:
            try:
                from schedule_engine import _weather_text  # type: ignore
            except Exception:
                _weather_text = None
        if _weather_text is not None:
            weather = _weather_text(context.get("weather") or {})
        persona = ""
        try:
            persona = await llm.persona(umo)
        except Exception:
            persona = ""
        hours = [item for item in (items or []) if str(item.get("start") or "")]
        logger.debug("[amo] 开始批量生成小日记 %s（%d 条）" % (day, len(hours)))
        total = 0
        previous = ""
        for begin in range(0, len(hours), 6):
            chunk = hours[begin:begin + 6]
            lines = []
            for item in chunk:
                start = str(item.get("start") or "")
                bits = ["%s %s（%s）" % (start, item.get("activity") or "待着",
                                        item.get("place") or "家")]
                if item.get("detail"):
                    bits.append("细节：" + str(item.get("detail"))[:40])
                if item.get("vehicle"):
                    bits.append("交通：" + str(item.get("vehicle")))
                if item.get("mood"):
                    bits.append("心情：" + str(item.get("mood")))
                lines.append("；".join(bits))
            system = "你就是这个角色本人。你在写只给自己看的第一人称小日记。只输出 JSON 数组。"
            prompt = (
                "角色设定（节选）：\n" + self._strip_his_from_text(persona, "")[:400] + "\n"
                "天气：%s。\n" % (weather or "未知")
                + ("上一段最后一条日记（要承接，不要重复）：\n" + previous[:300] + "\n" if previous else "")
                + "下面是今天的 %s-%s 这一段的日程：\n%s\n\n"
                "给每一条写一段第一人称小日记，120-200 字：\n"
                "1. 只写这一小时；写地点、手上的动作、一个小细节（声音、天气的体感）；\n"
                "2. 带一点情绪和心里话，口语化；每段承接上一段。\n"
                "3. 这一小时只有你一个人。\n"
                "只输出 JSON 数组：[{\"start\":\"07:00\",\"diary\":\"……\"}]。\n\n"
                % (chunk[0].get("start") or "", chunk[-1].get("end") or "", "\n".join(lines))
            )
            try:
                raw = await llm.chat_raw(umo, system, prompt, kind="diary")
            except Exception:
                continue
            rows = json_extract_list(raw)
            logger.debug("[amo] 日记批次 %d-%d：raw=%d 字，解析 %s 条" % (
                begin, min(begin + 6, len(hours)), len(str(raw or "")),
                len(rows) if isinstance(rows, list) else -1))
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                start = str(row.get("start") or "").strip()
                text = str(row.get("diary") or row.get("text") or "").strip()
                if not start or len(text) < 20:
                    continue
                text = self._strip_his_from_text(text, "")
                if not text:
                    continue
                try:
                    self.db.save_diary(day, start, text)
                    total += 1
                    previous = text
                except Exception:
                    pass
        if total:
            logger.debug("[amo] 今日小日记已预生成 %d 条（详细版）" % total)
        return {"total": total, "hours": len(hours)}

    def warm_schedule_diaries(self, day, items, umo):
        """预填保底 + 后台批量生成，不阻塞日程返回。"""
        try:
            if (self.db.kv_get("diary_prefill_" + str(day), False)
                    and self.db.kv_get("diary_warm_%s_%s" % (DIARY_WARM_VERSION, day), False)):
                return
        except Exception:
            pass
        try:
            self.prefill_diaries(day, items)
        except Exception as exc:
            logger.debug("[amo] 预填日记失败: %s" % exc)
        try:
            if getattr(self.p, "llm", None) is not None:
                self.p._spawn(self.warm_diaries(day, items, umo))
        except Exception as exc:
            logger.debug("[amo] 批量日记启动失败: %s" % exc)

    async def expand_hour(self, day, item, items=None, force=False):
        """点击二级卡片时，实时生成这一小时的第一人称小日记。"""
        day = str(day or today_str())
        item = dict(item or {})
        items = items or self._hourly_schedule(self.schedule.get(day) or [])
        start = item.get("start") or ""
        if not start:
            return {"diary": "", "mood": "平静", "place": "", "activity": ""}
        if not force:
            cached = self.db.get_diary(day, start)
            if cached:
                clean = self._strip_his_from_text(cached, "")
                if clean != cached:
                    cached = clean
                    try:
                        if clean:
                            self.db.save_diary(day, start, clean)
                    except Exception:
                        pass
            if cached:
                return {
                    "diary": cached,
                    "mood": item.get("mood") or "平静",
                    "place": item.get("place") or "",
                    "activity": item.get("activity") or "",
                    "cached": True,
                }
        context = self.schedule_context(day)
        if not context:
            context = self._minimal_context(day)
        else:
            context = dict(context)
            context["feel"] = self.feel_snapshot()
            context["health"] = self.health_info()
            context["period"] = self.period_info()
            if self.weather:
                context["weather"] = self.weather
        index = 0
        for position, entry in enumerate(items):
            if entry.get("start") == start:
                index = position
                break
        prev_item = items[index - 1] if index > 0 else None
        next_item = items[index + 1] if index + 1 < len(items) else None
        prev_diary = ""
        if prev_item is not None:
            try:
                prev_diary = self.db.get_diary(day, str(prev_item.get("start") or ""))
            except Exception:
                prev_diary = ""
        result = {"diary": "", "mood": item.get("mood") or "平静",
                  "place": item.get("place") or "", "activity": item.get("activity") or ""}
        diary_chain = Chain("terminal.diary", event_id="%s %s" % (day, start), logger=logger)
        if self.engine is not None:
            try:
                result.update(await self.engine.generate_diary(
                    self.p._last_umo, context, item, prev_item, next_item, self.p.llm,
                    prev_diary=prev_diary,
                ))
                diary_chain.step("generate", ok=bool(result.get("diary")),
                                 chars=len(str(result.get("diary") or "")),
                                 place=str(item.get("place") or ""),
                                 activity=str(item.get("activity") or ""))
            except Exception as exc:
                diary_chain.fail("generate", str(exc))
                logger.warning("[amo] 动态日记生成失败: %s" % exc)
        if not result.get("diary") and self.engine is not None:
            result["diary"] = self.engine.fallback_diary(context, item, prev_item)
        if not result.get("diary"):
            result["diary"] = "这小时我在%s，%s，心情%s。" % (
                item.get("place") or "家", item.get("activity") or "待着",
                item.get("mood") or "平静",
            )
        fallback = ""
        if self.engine is not None:
            try:
                fallback = self.engine.fallback_diary(context, item, prev_item)
            except Exception:
                fallback = ""
        result["diary"] = self._strip_his_from_text(
            result["diary"], fallback or "这一小时我在%s，%s。" % (
                item.get("place") or "家", item.get("activity") or "待着"))
        self.db.save_diary(day, start, result["diary"])
        diary_chain.done(chars=len(str(result.get("diary") or "")),
                         fallback=bool(fallback and result["diary"] == fallback))
        return result

    def apply_schedule_events(self):
        """当前小时的日程事件只触发一次，避免每轮都扣心情。"""
        item = self.current_activity()
        effects = item.get("effects") if isinstance(item.get("effects"), dict) else {}
        ctx = self.schedule_context(today_str())
        key = "schedule_event_%s_%s_%s" % (
            today_str(), item.get("start", ""), ctx.get("seed", ""),
        )
        if self.db.kv_get(key, False):
            return
        applied = False
        clean = {}
        for mood_key, delta in effects.items():
            if mood_key in self.FEEL_DIMS:
                try:
                    clean[mood_key] = float(delta)
                    applied = True
                except Exception:
                    continue
        if not applied:
            # 日常活动也要影响真实心情：上班会累、逛街会开心、睡觉回血。
            # CATEGORY_FEEL 是日程内部用的「每小时」增量，心流每轮都会向常态
            # 回落，所以乘一个增益（schedule_mood_gain，默认 3）才看得出来。
            try:
                gain = max(0.0, self.p.cfg_float("schedule_mood_gain", 3.0))
            except Exception:
                gain = 3.0
            category = str(item.get("category") or "")
            for mood_key, delta in (schedule_category_feel().get(category) or {}).items():
                if mood_key not in self.FEEL_DIMS:
                    continue
                try:
                    clean[mood_key] = float(delta) * gain
                except Exception:
                    continue
            applied = bool(clean)
        if clean:
            self.feel_bump(clean)
        # 兼容旧版日程里用 detail 标记的事件链。
        detail = str(item.get("detail") or "")
        if not applied and detail:
            legacy = {
                "熬夜": {"energy": -7, "anger": 3, "joy": -3},
                "精神恍惚": {"energy": -5, "fear": 5},
                "老板": {"anger": 8, "sadness": 8},
                "扣工资": {"sadness": 8, "anger": 6},
                "同事闹脾气": {"anger": 5, "sadness": 3},
                "同事聊天": {"joy": 3, "love": 1},
            }
            for word, deltas in legacy.items():
                if word in detail:
                    self.feel_bump(deltas)
                    applied = True
                    break
        self.db.kv_set(key, True)

    def _state_on_trip(self):
        """今天在不在外面（出行覆盖层还没落地时，别把真实行程当幻觉删掉）。"""
        try:
            return bool(self._active_trip())
        except Exception:
            return False

    @staticmethod
    def _normalize_items(items):
        """把 category/zone 归一成枚举值：大小写、空格修掉，认不出的原样保留。"""
        out = []
        for item in items or []:
            if not isinstance(item, dict):
                out.append(item)
                continue
            row = dict(item)
            category = str(row.get("category") or "").strip()
            if category:
                fixed = value_of(ActivityCategory, category, default="")
                if fixed:
                    row["category"] = fixed
            zone = str(row.get("zone") or "").strip()
            if zone:
                fixed_zone = value_of(SceneZone, zone, default="")
                if fixed_zone:
                    row["zone"] = fixed_zone
            out.append(row)
        return out

    def current_activity(self):
        items = self.schedule.get(today_str()) or []
        current = minutes_now()
        for item in items:
            if in_minute_range(current, parse_hhmm(item.get("start")), parse_hhmm(item.get("end"))):
                return dict(item)
        # 日程还没生成 / 刚被重建 / 出行覆盖层没落地时，绝不能退回硬编码的「家」：
        # 她人在南阳逛景区，状态写「家」比没有状态更糟（问一句就自相矛盾）。
        try:
            trip = self._active_trip()
        except Exception:
            trip = None
        if trip:
            city = str(trip.get("city") or "").strip()
            back_day = str(trip.get("return_day") or "").strip()
            try:
                back_hour = int(trip.get("return_hour") or 22)
            except (TypeError, ValueError):
                back_hour = 22
            still_out = not (back_day and back_day == today_str() and _now().hour >= back_hour)
            if city and still_out:
                return {"start": "", "end": "", "activity": "在外面待着",
                        "place": "%s·酒店房间" % city, "category": "rest", "zone": "hotel"}
        hour = _now().hour
        if hour < 6:
            return {"start": "00:00", "end": "06:00", "activity": "睡觉", "place": "家", "category": "sleep"}
        if hour < 9:
            return {"start": "07:00", "end": "09:00", "activity": "起床收拾", "place": "家", "category": "life"}
        if hour < 12:
            return {"start": "09:00", "end": "12:00", "activity": "上班", "place": "公司", "category": "work"}
        if hour < 14:
            return {"start": "12:00", "end": "14:00", "activity": "吃午饭", "place": "公司附近", "category": "meal"}
        if hour < 18:
            return {"start": "14:00", "end": "18:00", "activity": "上班", "place": "公司", "category": "work"}
        if hour < 20:
            return {"start": "18:00", "end": "20:00", "activity": "吃晚饭", "place": "家", "category": "meal"}
        if hour < 23:
            return {"start": "20:00", "end": "23:00", "activity": "休息", "place": "家", "category": "rest"}
        return {"start": "23:00", "end": "24:00", "activity": "准备睡觉", "place": "家", "category": "sleep"}

    @staticmethod
    def busy_level(activity):
        category = (activity or {}).get("category", "rest")
        if category == "sleep":
            return 1.0
        if category in ("work", "study"):
            return 0.75
        if category == "commute":
            return 0.6
        if category == "meal":
            return 0.3
        return 0.1

    # ---------- 汇总 ----------
    def snapshot(self):
        period = self.period_info()
        health = self.health_info()
        activity = self.current_activity()
        weather = self.weather or {}
        return {
            "date": today_str(),
            "weekday": weekday_cn(),
            "time": _now().strftime("%H:%M"),
            "datetime_text": "%s 星期%s %s" % (today_str(), weekday_cn(), _now().strftime("%H:%M")),
            "feel": self.feel_snapshot(),
            "feel_rel": self.feel_rel(),
            "period": period,
            "health": health,
            "weather": weather,
            "weather_text": self.weather_text(),
            "activity": activity,
            "busy": self.busy_level(activity),
            "schedule": self.schedule.get(today_str()) or [],
        }

    def prompt_text(self, snap=None, with_activity=False):
        snap = snap or self.snapshot()
        activity = snap["activity"]
        lines = [
            "现在是 %s。" % snap["datetime_text"],
            self.feel_text(),
            "生理期：%s第%d天，%s。" % (
                snap["period"]["phase"], snap["period"]["day"], snap["period"]["tone"]
            ),
            "身体：%s%s。" % (
                snap["health"]["status"],
                ("（" + snap["health"]["note"] + "）") if snap["health"].get("note") else "",
            ),
            "天气：%s。" % snap["weather_text"],
        ]
        # 地点永远给：不给的话模型会自己编一个（踩过坑：日程在景区，她说在酒店）。
        # 只让她在被问/需要时用，并明令不许改口。
        outfit = str(activity.get("outfit") or "").strip()
        lines.append(
            "（内在状态，仅供自洽，不是话题，被问才说）你此刻在%s（%s）%s。"
            "地点和正在做的事只能按这一条说，不许说成别处、也不许临时改口。"
            % (activity.get("activity", "休息"), activity.get("place", "家"),
               ("，穿着" + outfit) if outfit else "")
        )
        # 穿戴的颜色必须钉死。2026-11-17 的病象：她身上是 JK·藏青 的「及膝黑袜」，
        # 照片也是黑的，她嘴上非说「白丝」。根因不在生图，在说话时没事实可对照：
        # ① 衣柜件名里的颜色（黑/白）没有被单独提出来当事；
        # ② 记忆里有「他喜欢JK制服和白丝」，一提到丝袜就被他的偏好带跑。
        # 所以这里把「身上这套里的颜色词」单独列成硬事实，并明说他的喜好 ≠ 她此刻穿的。
        colors = self._outfit_colors(outfit)
        if outfit:
            lines.append(
                "【穿戴事实】你现在身上就是这套：%s。这套是什么颜色就是什么颜色——"
                "%s说袜子、说丝袜、说裙子、说衣服颜色时，只能按这套里的颜色说，"
                "不许换成别的颜色（黑的不能说成白的）。"
                "【他的喜好】他喜欢什么颜色是他的事，不等于你此刻穿的；"
                "不要因为他说过喜欢白丝，就把自己身上的黑袜说成白丝。"
                % (outfit, ("这套的颜色是：" + colors + "。") if colors else "")
            )
        return "\n".join(lines)

    #: 颜色词：只认这些，避免把「黑」当成「黑白」的一部分之类
    _COLOR_WORDS = ("黑", "白", "粉", "蓝", "灰", "杏", "米", "红", "紫", "绿",
                    "黄", "棕", "藏青", "薄荷", "奶油", "雾", "咖", "银", "金")

    def _outfit_colors(self, outfit: str) -> str:
        """从「套名｜件名」里把颜色词提出来，给「穿戴事实」用。

        ``JK·藏青｜长袖白衬衫，JK·藏青｜藏青格裙，JK·藏青｜及膝黑袜，…``
        → ``黑（及膝黑袜）、白（长袖白衬衫）、藏青（藏青格裙）``
        同一颜色只列一次，顺序按出现先后，便于模型对照。
        """
        text = str(outfit or "")
        if not text:
            return ""
        detail: list[str] = []
        for piece in text.split("，"):
            name = piece.split("｜", 1)[-1].strip() if "｜" in piece else piece.strip()
            if not name:
                continue
            # 每件都单独判色：白衬衫和白袜都算「白」，不能因为白衬衫先出现就把袜子漏掉
            for word in self._COLOR_WORDS:
                if word in name and len(name) >= len(word) + 1:
                    # 更长的时间优先（「藏青」不能被「青」之类的短词抢走）
                    detail.append("%s（%s）" % (word, name))
                    break
        return "、".join(detail)

    def tone_text(self, snap=None, relation="普通"):
        """她此刻该用什么语气——只看七情六欲（离常态多远）。"""
        snap = snap or self.snapshot()
        rel = snap.get("feel_rel") or self.feel_rel()
        anger = rel.get("anger", 50.0)
        sadness = rel.get("sadness", 50.0)
        fear = rel.get("fear", 50.0)
        joy = rel.get("joy", 50.0)
        love = rel.get("love", 50.0)
        surprise = rel.get("surprise", 50.0)
        fatigue = rel.get("fatigue", 40.0)
        if relation == "相恋" and (anger >= 62 or sadness >= 62):
            tone = (
                "你在生对方的气，但你是他的恋人：会抱怨、闹别扭、说反话、要哄，"
                "语气带一点委屈，不会像对普通人那样冷怼、赶人或人身攻击；可以嘴硬，但不要真的伤人。"
            )
        elif anger >= 66:
            tone = "你现在很烦躁，说话冲、短、带刺，一点就着，但不要真正辱骂。"
        elif sadness >= 62:
            tone = "你现在有点低落，说话安静、句子短。"
        elif fatigue >= 68:
            tone = "你很累，句子短一点、不展开；但别拿累当理由赶人、结束话题。"
        elif love >= 66:
            tone = "你现在很黏人，想和对方多聊几句，语气软。"
        elif joy >= 64 or surprise >= 66:
            tone = "你现在心情很好，语气轻快，会用语气词和感叹号。"
        elif fear >= 62:
            tone = "你有点慌，句子急，容易追问。"
        else:
            tone = "你语气自然平静，像平常聊天。"
        if snap["health"]["sick"]:
            tone += " 你身体不舒服，语气会比平时弱一点。"
        if snap["period"]["phase"] in ("月经期", "黄体期"):
            tone += " 生理期让你更容易累和敏感。"
        if relation == "相恋":
            tone += " 你和对方是恋人，可以亲昵、撒娇、用昵称。"
        elif relation == "仇恨":
            tone += " 你很讨厌对方，语气冷淡、疏远。"
        elif relation == "抵触":
            tone += " 你对对方有点防备，保持距离。"
        return tone

    def interesting_event(self):
        events = [
            "楼下咖啡店今天买一送一",
            "路上遇到一只很胖的橘猫",
            "同事带了自己烤的小饼干",
            "窗外的云像一只兔子",
            "刷到一个特别好笑的表情包",
            "便利店新出了草莓味的冰淇淋",
        ]
        if (self.weather or {}).get("tag") == "rain":
            events.append("下班的时候突然下雨，躲在便利店屋檐下")
        index = md5_int(today_str() + str(_now().hour)) % len(events)
        return events[index]

    def daily_tick(self):
        self.last_daily = today_str()
        period = self.period_info()
        if period["phase"] == "月经期":
            self.feel_bump({"energy": -8, "sadness": 5, "anger": 2, "joy": -3})
        elif period["phase"] == "黄体期":
            self.feel_bump({"sadness": 4, "fear": 3})
        elif period["phase"] == "排卵期":
            self.feel_bump({"joy": 4, "surprise": 3})
        else:
            self.feel_bump({"joy": 2})
        self.save()
