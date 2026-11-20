# -*- coding: utf-8 -*-
"""Amo 终端 · 用量与余额（UsageMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., UsageMixin, Star) 混入，self.* 照旧可用。

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

def fetch_deepseek_balance(api_key, base_url="https://api.deepseek.com", timeout=8.0):
    """查 DeepSeek 余额；失败返回 {ok: False, error}，不抛异常。"""
    api_key = str(api_key or "").strip()
    if not api_key:
        return {"ok": False, "error": "未配置 API Key"}
    import urllib.request
    url = str(base_url or "https://api.deepseek.com").rstrip("/") + "/user/balance"
    request = urllib.request.Request(url, headers={
        "Authorization": "Bearer " + api_key,
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}
    infos = payload.get("balance_infos") or []
    chosen = None
    for item in infos:
        if str(item.get("currency") or "").upper() == "CNY":
            chosen = item
            break
    if chosen is None and infos:
        chosen = infos[0]
    if not isinstance(chosen, dict):
        return {"ok": False, "error": "返回里没有余额信息"}

    def money(value):
        try:
            return round(float(value), 2)
        except (TypeError, ValueError):
            return None

    return {
        "ok": True,
        "available": bool(payload.get("is_available")),
        "currency": str(chosen.get("currency") or "CNY"),
        "amount": money(chosen.get("total_balance")),
        "granted": money(chosen.get("granted_balance")),
        "topped_up": money(chosen.get("topped_up_balance")),
    }


class UsageMixin:

    def _record_tokens(self, kind, provider, response):
        """把这次调用的 token 记进自己的表；provider_stats 只统计主回复，这里补内部调用。"""
        try:
            usage = getattr(response, "usage", None)
            if usage is None:
                return
            if isinstance(usage, dict):
                miss = usage.get("input_other", 0)
                cached = usage.get("input_cached", 0)
                out = usage.get("output", 0)
            else:
                miss = getattr(usage, "input_other", 0)
                cached = getattr(usage, "input_cached", 0)
                out = getattr(usage, "output", 0)
            if not (int(miss or 0) or int(cached or 0) or int(out or 0)):
                return
            model = ""
            try:
                model = str(provider.get_model() or "")
            except Exception:
                model = ""
            self.db.record_tokens(kind, model, miss, cached, out)
        except Exception as exc:
            logger.debug("[amo] 记 token 失败: %s" % exc)

    def _usage_db_path(self):
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            return os.path.join(str(get_astrbot_data_path()), "data_v4.db")
        except Exception:
            try:
                data_dir = os.path.dirname(os.path.dirname(os.path.dirname(str(self.db.path))))
                return os.path.join(data_dir, "data_v4.db")
            except Exception:
                return ""

    def _deepseek_api_key(self):
        key = str(self.cfg_str("deepseek_api_key", "") or "").strip()
        if key:
            return key
        for name in ("DEEPSEEK_API_KEY", "COMPANION_V2_BALANCE_API_KEY"):
            value = str(os.environ.get(name, "") or "").strip()
            if value:
                return value
        return ""

    def _usage_prices(self):
        prices = {}
        for key in ("hit_peak", "hit_idle", "miss_peak", "miss_idle", "out_peak", "out_idle"):
            prices[key] = self.cfg_float("usage_price_" + key, USAGE_DEFAULT_PRICES[key])
        return prices

    def _usage_start_of_today(self):
        now = _now()
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return start.timestamp()

    def _judge_provider_id(self):
        try:
            if self.heartflow is not None:
                return str(self.heartflow.judge_provider_info().get("id") or "")
        except Exception:
            pass
        return ""

    def _using_provider_id(self):
        try:
            provider = self.context.get_using_provider()
            return str((getattr(provider, "provider_config", None) or {}).get("id") or "")
        except Exception:
            return ""

    def _provider_api_key(self, item):
        """从 AstrBot 供应商配置里取密钥；只在内存中使用，不写日志不回传。"""
        config = {}
        try:
            for provider in (self.context.get_all_providers() or []):
                candidate = getattr(provider, "provider_config", None) or {}
                if str(candidate.get("id") or "") == str(item.get("id") or ""):
                    config = candidate
                    break
        except Exception:
            config = {}
        key = config.get("key") or ""
        if isinstance(key, list):
            key = next((str(item or "").strip() for item in key if str(item or "").strip()), "")
        return str(key or "").strip()

    async def _balance_cached(self):
        """余额 60 秒内复用，避免面板每刷一次就打一次外网。"""
        now = time.time()
        cache = getattr(self, "_balance_cache", None)
        if isinstance(cache, dict) and now - float(cache.get("at") or 0) < 60:
            return cache.get("data") or {"ok": False, "error": "查询失败"}
        key = self._deepseek_api_key()
        data = await asyncio.to_thread(fetch_deepseek_balance, key)
        self._balance_cache = {"at": now, "data": data}
        return data


__all__ = [
    "fetch_deepseek_balance",
    "UsageMixin",
]
