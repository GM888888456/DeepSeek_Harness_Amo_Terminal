# -*- coding: utf-8 -*-
"""Amo 终端 · 记忆读写（MemoryOpsMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., MemoryOpsMixin, Star) 混入，self.* 照旧可用。

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



class MemoryOpsMixin:

    async def _write_memory_checked(self, uid, content, kind="fact", tier=1, scope="private", group_id=""):
        """写一条记忆并返回是否真的成功；失败打 warning，调用方据此决定要不要标记。

        scope/group_id 必须一路传到数据终端：群聊写入 private、群聊却按 group 读，
        就会表现为“群里聊过但她完全不记得”。
        """
        if _mem_prepare is not None:
            try:
                allowed, fixed, why = _mem_prepare(self.db, str(uid), content, _now(), now_ts())
            except Exception:
                allowed, fixed, why = True, content, "guard_error"
            if not allowed:
                logger.debug("[amo] 记忆没写（%s）: %s" % (why, str(content)[:40]))
                return False
            content = fixed
        hub = self._memory_hub()
        level = to_int(tier, 1)
        importance = 0.75 if level >= 2 else (0.55 if level == 1 else 0.35)
        if hub is not None and hub.writable():
            try:
                result = await hub.remember(str(uid), content, str(kind or "fact"), importance, scope, group_id)
            except Exception as exc:
                logger.warning("[amo] 记忆写入异常: %s" % exc)
                result = {"ok": False}
            if isinstance(result, dict) and result.get("ok"):
                self._memory_committed(uid, content)
                return True
            logger.warning(
                "[amo] 记忆没写进去（%s）: %s" % ((result or {}).get("reason", "?"), str(content)[:40])
            )
            return False
        if self._data_mem() is not None:
            try:
                result = await self._data_memory_write(uid, content, kind, tier, scope, group_id)
            except Exception:
                result = False
            if result:
                self._memory_committed(uid, content)
                return True
        return False

    async def _data_memory_recall(self, uid, text, limit=6, event=None):
        """从「记忆终端」（Astr_Amo_data）取回这个人的记忆。

        陪伴自己不存记忆：装了就只问它要，没装才退回外挂记忆插件。
        """
        mem = self._data_mem()
        if mem is None or not uid:
            return []
        recall = getattr(mem, "recall", None)
        if not callable(recall):
            return []
        scope = "private"
        group_id = ""
        try:
            if event is not None and not event.is_private_chat():
                scope = "group"
                group_id = str(event.get_group_id() or "")
        except Exception:
            pass
        try:
            rows = await recall(
                self._data_bot_id(), str(uid), str(text or ""),
                max(1, to_int(limit, 6)), scope, group_id,
            )
        except Exception as exc:
            logger.debug("[amo] 记忆终端召回失败: %s" % exc)
            return []
        items = []
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            content = re.sub(r"\s+", " ", str(row.get("content") or "")).strip()
            if len(content) < 2:
                continue
            importance = to_float(row.get("importance"), 0.5)
            items.append({
                "content": content[:500],
                "tier": 2 if importance >= 0.72 else (1 if importance >= 0.42 else 0),
                "kind": str(row.get("kind") or "fact"),
                "source": "amo_data",
                "memory_type": str(row.get("kind") or ""),
                "created_at": row.get("created_at", 0),
                "hits": 0,
                "expires_at": None,
            })
        return items

    def _normalize_memories(self, rows):
        """把各家插件返回的记忆统一成 {content, tier, name, kind, ...}。"""
        items = []
        for row in rows or []:
            if isinstance(row, dict):
                content = str(row.get("content") or row.get("memory") or "").strip()
                importance = to_float(row.get("importance"), 0.5)
                name = str(row.get("name") or row.get("who") or "").strip()
                kind = str(row.get("kind") or row.get("memory_type") or "fact")
                created_at = row.get("created_at", 0)
            else:
                memory = getattr(row, "memory", None) or row
                content = str(getattr(memory, "content", "") or "").strip()
                importance = to_float(getattr(memory, "importance", 0.5), 0.5)
                name = str(getattr(memory, "name", "") or "").strip()
                kind = str(getattr(memory, "memory_type", "") or "fact")
                created_at = getattr(memory, "created_at", 0)
            if len(content) < 2:
                continue
            items.append({
                "content": content[:500],
                "tier": 2 if importance >= 0.72 else (1 if importance >= 0.42 else 0),
                "importance": importance,
                "kind": kind,
                "name": name,
                "source": "hub",
                "created_at": created_at,
                "hits": 0,
                "expires_at": None,
            })
        return items

    def _memory_runtime(self):
        star = self

        class _Runtime:
            logger = logger

            @staticmethod
            def cfg(key, default=None):
                try:
                    data = star.config
                    if isinstance(data, dict):
                        return data.get(key, default)
                except Exception:
                    pass
                return default

            @staticmethod
            def bot_id():
                return star._data_bot_id()

            @staticmethod
            def get_plugin(names):
                return star._plugin_by_names(names)

            @staticmethod
            def normalize_memories(rows):
                return star._normalize_memories(rows)

        return _Runtime()

    async def _hydrate_recent(self, umo, limit=30):
        """从记忆终端把这个会话最近的话捞回内存，重启后也有上下文。"""
        umo = str(umo or "")
        if not umo:
            return
        if str(umo) in getattr(self, "_ctx_hydrated", set()):
            return
        rows = []
        hub = self._memory_hub()
        if hub is not None:
            try:
                rows = await hub.recent(umo, "", max(1, int(limit))) or []
            except Exception as exc:
                logger.debug("[amo] 能力层取上下文失败: %s" % exc)
                rows = []
        if not rows:
            mem = self._data_mem()
            lister = getattr(mem, "list_messages", None) if mem is not None else None
            if callable(lister):
                try:
                    rows = await lister(self._data_bot_id(), umo, max(1, int(limit))) or []
                except Exception as exc:
                    logger.debug("[amo] 从记忆终端取上下文失败: %s" % exc)
                    rows = []
        if not rows:
            try:
                rows = self.db.recent_messages(umo, max(1, int(limit)))
            except Exception:
                rows = []
        if not rows:
            return
        ordered = sorted(rows, key=lambda item: to_float(item.get("created_at"), 0))
        if hub is not None:
            try:
                hub.buffer.hydrate(umo, ordered[-self.CONTEXT_BUFFER_LIMIT:])
            except Exception:
                pass
        self._ctx_hydrated = getattr(self, "_ctx_hydrated", set())
        self._ctx_hydrated.add(str(umo))

    async def _recent_by_uid(self, uid, limit=20, umo=""):
        """取近聊：优先按会话，其次按 uid；都没有再退回缓冲/本地缓存。"""
        uid = str(uid or "")
        size = max(1, int(limit or 20))
        mem = self._data_mem()
        lister = getattr(mem, "list_messages", None) if mem is not None else None
        if callable(lister) and umo:
            # 按会话取：bot 行的 uid 是字面量 "bot"，按 uid 过滤会把她说的话全滤掉
            try:
                rows = await lister(self._data_bot_id(), str(umo), size) or []
            except Exception as exc:
                logger.debug("[amo] 读最近消息失败: %s" % exc)
                rows = []
            if rows:
                return sorted(rows, key=lambda item: to_float(item.get("created_at"), 0))[-size:]
        if callable(lister):
            try:
                rows = await lister(self._data_bot_id(), "", size, uid=uid) or []
            except Exception:
                rows = []
            if rows:
                return sorted(rows, key=lambda item: to_float(item.get("created_at"), 0))[-size:]
        merged = []
        hub = self._memory_hub()
        if hub is not None:
            try:
                merged = hub.buffer.by_uid(uid, size)
            except Exception:
                merged = []
        if merged:
            return sorted(merged, key=lambda item: to_float(item.get("created_at"), 0))[-size:]
        try:
            return self.db.messages_by_uid(uid, size)
        except Exception:
            return []

    async def _time_recall_context(self, event, uid):
        """按时间回看：他问"昨天下午/前天/上周三"时，去记忆终端取那段时间的聊天。"""
        if not self.cfg_bool("time_recall_enabled", True):
            return ""
        text = str(getattr(event, "message_str", "") or "")
        if not _looks_like_time_query(text):
            return ""
        mem = self._data_mem()
        if mem is None or not callable(getattr(mem, "recall_messages", None)):
            return ""
        try:
            umo = str(getattr(event, "unified_msg_origin", "") or "")
            # 配 0 / 负数时以前会「请求 4 条、只渲染 1 条」，两边都按同一档位收敛
            limit = max(1, min(40, self.cfg_int("time_recall_limit", 6)))
            result = await self._data_call(
                "recall_messages", self._data_bot_id(), query=text, umo=umo,
                uid=str(uid), limit=min(limit * 2, 40),
            )
        except Exception as exc:
            logger.debug("[amo] 时间回看失败: %s" % exc)
            return ""
        if not isinstance(result, dict):
            return ""
        messages = result.get("messages") or []
        label = str(result.get("label") or "")
        if not label:
            return ""
        return _render_time_block(label, messages, max_lines=max(1, int(limit)))

    def _embedded_data_plugin(self):
        """内嵌记忆：找不到独立记忆插件时，在进程内起一份。

        用的是同一个 Context、同一份 plugin_data/Astr_Amo_data/amo_data.db，
        对外接口（plugin.mem）与独立插件完全一致，所以上层代码不用改。
        """
        cached = getattr(self, "_embedded_data", None)
        if cached is not None:
            return cached
        if getattr(self, "_embedded_data_failed", False):
            return None
        try:
            from ..mem.mem_main import AmoDataPlugin as _EmbeddedData
        except Exception:
            try:
                from mem.mem_main import AmoDataPlugin as _EmbeddedData  # type: ignore
            except Exception as exc:
                self._embedded_data_failed = True
                logger.error("[amo] 内嵌记忆导入失败（记忆功能不可用）: %s" % exc)
                return None
        try:
            plugin = _EmbeddedData(self.context, self._embedded_data_config())
            self._embedded_data = plugin
            try:
                if getattr(plugin, "mem", None) is not None:
                    # 兄弟插件（影音/医疗/金融）找终端时要能拿到记忆门面
                    self.mem = plugin.mem
            except Exception:
                pass
            logger.info("[amo] 内嵌记忆已启动（融合模式，%s）" % getattr(plugin, "db_path", ""))
            return plugin
        except Exception as exc:
            self._embedded_data_failed = True
            logger.error("[amo] 内嵌记忆启动失败（记忆功能不可用）: %s" % exc)
            return None


__all__ = [
    "MemoryOpsMixin",
]
