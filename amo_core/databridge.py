# -*- coding: utf-8 -*-
"""Amo 终端 · 数据插件桥接（DataBridgeMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., DataBridgeMixin, Star) 混入，self.* 照旧可用。

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



class DataBridgeMixin:

    def _data_plugin(self):
        """找「我想永远陪着你-记忆」插件实例；没装就返回 None。"""
        try:
            for name in self.DATA_PLUGIN_NAMES:
                star = self._star_instance(self.context.get_registered_star(name))
                if star is not None:
                    return star
        except Exception:
            pass
        try:
            for meta in self.context.get_all_stars():
                marker = (getattr(meta, "name", "") or "") + " " + (getattr(meta, "module_path", "") or "")
                star = self._star_instance(meta)
                if star is not None and ("amo_memory" in marker.lower() or "amo_data" in marker.lower()):
                    return star
        except Exception:
            pass
        return self._embedded_data_plugin()

    def _data_mem(self):
        plugin = self._data_plugin()
        return getattr(plugin, "mem", None) if plugin is not None else None

    def _data_store(self):
        """兜底：直接拿数据插件的 DataStore（mem 门面缺失/旧版时用）。"""
        plugin = self._data_plugin()
        return getattr(plugin, "store", None) if plugin is not None else None

    def _data_connected(self):
        """数据插件此刻在不在：只看内存里的插件表，不读库、不联网。"""
        plugin = self._data_plugin()
        if plugin is None:
            return False
        return getattr(plugin, "mem", None) is not None or getattr(plugin, "store", None) is not None

    def _note_data_missing(self):
        """第一次没找到数据插件：记一次日志，并在 60 秒后再确认一次（只提醒一次）。"""
        if not self._data_missing_logged:
            self._data_missing_logged = True
            logger.info("[amo] 未检测到数据插件 Astr_Amo_data，继续用本地库（装好后面板数据为空是正常的）")
        if not self._data_warn_scheduled:
            self._data_warn_scheduled = True
            self._spawn(self._warn_data_missing_later())

    async def _warn_data_missing_later(self, delay=60.0):
        """启动 60 秒后还没连上数据插件，才升级成一条 warning；连上就不打。"""
        try:
            await asyncio.sleep(max(1.0, float(delay)))
        except asyncio.CancelledError:
            return
        if not self._running or self._data_synced or self._data_connected():
            return
        logger.warning(
            "[amo] 数据插件未连接：去「插件」页看 Astr_Amo_data 是不是被停用/加载报错；"
            "装好后 5 分钟内会自动接上，不用重启"
        )

    def _data_bot_id(self):
        return str(self.cfg_str("data_bot_id", "") or self.bot_name or "default")

    async def _data_call(self, name, *args, **kwargs):
        mem = self._data_mem()
        func = getattr(mem, name, None) if mem is not None else None
        if not callable(func):
            logger.error("[amo] 记忆库没有接口 %s（Astr_Amo_data 没连上或版本不对）" % name)
            return None
        try:
            return await asyncio.wait_for(
                func(*args, **kwargs),
                timeout=max(1.0, self.cfg_float("data_call_timeout_seconds", 15.0)),
            )
        except asyncio.TimeoutError:
            logger.error("[amo] 记忆库 %s 超时" % name)
            return None
        except Exception as exc:
            logger.error("[amo] 记忆库 %s 调用失败: %s" % (name, exc))
            return None

    async def _data_mem_list(self, uid, keyword="", limit=50):
        """面板记忆页：直接列出记忆终端里的条目。"""
        mem = self._data_mem()
        if mem is None or not uid:
            return []
        size = max(1, min(200, to_int(limit, 50)))
        try:
            if keyword:
                recall = getattr(mem, "recall", None)
                rows = await recall(self._data_bot_id(), str(uid), str(keyword), size, "", "") if callable(recall) else []
            else:
                lister = getattr(mem, "list_memories", None)
                rows = await lister(self._data_bot_id(), str(uid), size) if callable(lister) else []
        except Exception as exc:
            logger.debug("[amo] 读取记忆终端失败: %s" % exc)
            return []
        items = [dict(row) for row in (rows or []) if isinstance(row, dict)]
        for item in items:
            item.setdefault("source", "amo_data")
        return items

    def _data_memory_count(self, uid):
        """状态页记忆条数：以「记忆终端」为准，终端没有才数外挂插件。

        以前这里只数外挂插件，装的是 Astr_Amo_data 时状态页永远是 0；
        又套了 30 秒缓存，刚记住的东西要刷新才出现。
        """
        store = self._data_store()
        lister = getattr(store, "list_memories", None) if store is not None else None
        if callable(lister):
            try:
                rows = lister(self._data_bot_id(), str(uid or ""), 200) or []
                return len(rows)
            except Exception as exc:
                logger.debug("[amo] 统计记忆终端条数失败: %s" % exc)
        return 0

    async def _data_memory_write(self, uid, content, kind="fact", tier=1, scope="private", group_id=""):
        """把一条记忆交给「记忆终端」写入；它只负责存，陪伴不落本地库。"""
        mem = self._data_mem()
        if mem is None or not uid:
            return False
        content = re.sub(r"\s+", " ", str(content or "")).strip()
        if not content:
            return False
        remember = getattr(mem, "remember", None)
        if not callable(remember):
            return False
        level = to_int(tier, 1)
        importance = 0.75 if level >= 2 else (0.55 if level == 1 else 0.35)
        try:
            result = await remember(
                self._data_bot_id(), str(uid), content,
                kind=str(kind or "fact"), importance=importance,
                scope=str(scope or "private"), group_id=str(group_id or ""),
            )
        except Exception as exc:
            logger.debug("[amo] 记忆终端写入失败: %s" % exc)
            return False
        if isinstance(result, dict):
            return bool(result.get("ok", True))
        return bool(result)

    async def _push_cache_to_data(self, key, value):
        await self._data_call("cache_set", self._data_bot_id(), str(key), value)

    async def _sync_with_data_plugin(self):
        """启动时双向同步：首次把本地画像/关系/日程缓存推过去，之后以插件为准补齐本地。

        数据插件（Astr_Amo_data）可能比 amo 后加载，所以允许重试：
        - 本实例只成功同步一次（_data_synced），之后所有调用直接返回，不重复推送；
        - 启动、on_astrbot_loaded、后台 tick 三处可能同时来，用锁串行，避免重复迁移。
        """
        if self._data_synced:
            return
        async with self._data_sync_lock:
            if self._data_synced:
                return
            await self._sync_with_data_plugin_once()

    def _apply_remote_profile(self, uid, remote_row, local_profile):
        """把数据插件面板改过的画像字段拉回本地（不标记成本地手动修改）。"""
        fields = {}
        for src, dst in (("name", "name"), ("alias", "alias"), ("relation", "relation"), ("remark", "notes")):
            value = str(remote_row.get(src) or "").strip()
            if src == "remark" and _looks_auto_note(value):
                continue
            if value and value != str(local_profile.get(dst) or "").strip():
                fields[dst] = value
        if not fields:
            return False
        try:
            self.db.update_profile(uid, mark_local=False, **fields)
        except Exception as exc:
            logger.warning("[amo] 拉回画像 %s 失败: %s" % (uid, exc))
            return False
        logger.info("[amo] 画像从数据插件拉回：%s %s" % (uid, ",".join(fields.keys())))
        return True

    async def _push_relation_to_data(self, a_uid, b_uid, relation, note=""):
        # "bot"/"self" 是插件内部标识，不是真实人物：写进记忆终端会让关系图多出一个
        # 叫 bot 的节点，所以只推真实的人与人之间的关系。
        if str(a_uid) in INTERNAL_RELATION_NODES or str(b_uid) in INTERNAL_RELATION_NODES:
            return
        await self._data_call(
            "save_relation", self._data_bot_id(), str(a_uid), str(b_uid),
            str(relation or "朋友"), str(note or ""),
        )

    async def _sync_profile_relation_edge(self, uid, relation, note="画像：关系字段"):
        """画像里手动设的关系，同步成一条 bot↔对方 的关系边。

        关系图是从 relation_network 渲染的；不写这条边，就会出现「画像设成恋人、
        图上还是自动沉淀的熟人」。
        """
        uid = str(uid or "").strip()
        relation = str(relation or "").strip()
        # 画像用的是「相恋」，关系网用的是「恋人」；不换算就会被下面的白名单挡掉，
        # 于是又回到「设了恋人、图上还是熟人」。
        relation = {"相恋": "恋人", "熟识": "熟人", "仇恨": "仇人"}.get(relation, relation)
        if not uid or not relation or relation in ("普通",):
            return
        if uid in INTERNAL_RELATION_NODES or relation not in NETWORK_RELATIONS:
            return
        try:
            self.db.upsert_relation("bot", uid, relation, note)
        except Exception as exc:
            logger.debug("[amo] 画像关系写进关系网失败: %s" % exc)

    def _plugin_by_names(self, names):
        """按插件名找实例；不缓存，reload 之后拿到的是新实例。"""
        for name in names:
            try:
                meta = self.context.get_registered_star(name)
            except Exception:
                meta = None
            star = self._star_instance(meta)
            if star is not None:
                return star
        try:
            wanted = [str(item).lower() for item in names]
            for meta in self.context.get_all_stars():
                module = str(getattr(meta, "module_path", "") or "").lower()
                label = str(getattr(meta, "name", "") or "").lower()
                if any(word in module or word in label for word in wanted):
                    star = self._star_instance(meta)
                    if star is not None:
                        return star
        except Exception:
            pass
        return None

    def _log_push_failure(self, uid, exc):
        """同一次同步里最多打 3 条 warning，避免刷屏。"""
        count = to_int(getattr(self, "_push_fail_count", 0))
        self._push_fail_count = count + 1
        if count < 3:
            logger.warning(
                "[amo] 推送画像 %s 失败: %s: %s" % (uid, type(exc).__name__, exc)
            )

    def _platform_of(self, event=None):
        """当前消息来自哪个平台（aiocqhttp / lark …），失败就退回 umo 前缀。"""
        name = ""
        try:
            name = str(event.get_platform_name() or "")
        except Exception:
            name = ""
        if not name:
            try:
                name = str(event.unified_msg_origin or "").split(":", 1)[0]
            except Exception:
                name = ""
        name = name.strip().lower()
        if name:
            seen = getattr(self, "_seen_platforms", None)
            if seen is None:
                seen = set()
                self._seen_platforms = seen
            seen.add(name)
        return name

    def _platform_label(self, platform=""):
        key = str(platform or "").strip().lower()
        if not key:
            return "这里"
        return self.PLATFORM_LABELS.get(key, str(platform).strip())

    def _memory_hub(self):
        hub = getattr(self, "_mem_hub", None)
        if hub is not None:
            return hub
        if MemoryHub is None:
            return None
        try:
            hub = MemoryHub(
                self._memory_runtime(),
                buffer_size=max(8, self.cfg_int("ctx_window", 48)),
            )
        except Exception as exc:
            logger.warning("[amo] 记忆能力层初始化失败: %s" % exc)
            return None
        self._mem_hub = hub
        return hub


__all__ = [
    "DataBridgeMixin",
]
