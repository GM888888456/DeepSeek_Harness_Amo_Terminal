# -*- coding: utf-8 -*-
"""Amo 终端 · 配置读取（ConfigMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., ConfigMixin, Star) 混入，self.* 照旧可用。

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

def looks_like_plain_command(text):
    text = (text or "").strip()
    return text.startswith("/") or text.startswith("／")


class ConfigMixin:

    def cfg(self, key, default=None):
        try:
            value = self.config.get(key, default)
        except Exception:
            value = default
        return default if value is None else value

    def cfg_bool(self, key, default=False):
        value = self.cfg(key, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on", "是")

    def cfg_int(self, key, default=0):
        try:
            return int(float(self.cfg(key, default)))
        except Exception:
            return default

    def cfg_float(self, key, default=0.0):
        try:
            return float(self.cfg(key, default))
        except Exception:
            return default

    def cfg_str(self, key, default=""):
        try:
            return str(self.cfg(key, default))
        except Exception:
            return default

    def _schema_map(self):
        path = os.path.join(self.plugin_dir, "_conf_schema.json")
        try:
            with open(path, encoding="utf-8") as stream:
                schema = json.load(stream)
            return schema if isinstance(schema, dict) else {}
        except Exception as exc:
            logger.warning("[amo] 读取配置 schema 失败: %s" % exc)
            return {}

    def _apply_forced_on_config(self):
        for key in FORCED_ON_CONFIG_KEYS:
            try:
                if key in self.config and self.config.get(key) is not True:
                    self.config[key] = True
            except Exception:
                pass

    def _command_prefixes(self):
        if self._prefix_cache is not None:
            return self._prefix_cache
        prefixes = []
        try:
            cfg = self.context.get_config()
            raw = cfg.get("wake_prefix", []) if cfg else []
            if isinstance(raw, str):
                raw = [raw]
            prefixes = [str(item) for item in (raw or []) if item]
        except Exception:
            pass
        self._prefix_cache = prefixes
        return prefixes

    def _looks_like_command(self, text):
        if looks_like_plain_command(text):
            return True
        first = text.split()[0].lower() if text.split() else ""
        if first in ("amo", "陪伴", "c_status", "c_profile", "c_setrel", "learn_and_gate"):
            return True
        return any(prefix and text.startswith(prefix) for prefix in self._command_prefixes())

    def _args(self, event):
        raw = (event.message_str or "").strip()
        raw = re.sub(r"^[/／]\s*", "", raw)
        parts = raw.split()
        if parts and parts[0].lower() in ("amo", "陪伴", "amo_forever", "astrbot_amo_forever"):
            parts = parts[1:]
        return parts

    def _q(self, key, default=None):
        try:
            if web_request is not None:
                return web_request.query.get(key, default)
        except Exception:
            pass
        return default

    def _q_int(self, key, default=0):
        return to_int(self._q(key, default), default)

    async def _body(self):
        try:
            if web_request is not None and hasattr(web_request, "json"):
                data = await web_request.json(default={})
                return data if isinstance(data, dict) else {}
        except Exception:
            pass
        try:
            if web_request is not None:
                data = await web_request.get_json(silent=True)
                return data or {}
        except Exception:
            pass
        return {}


__all__ = [
    "looks_like_plain_command",
    "ConfigMixin",
]
