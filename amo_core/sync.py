# -*- coding: utf-8 -*-
"""Amo 终端 · 数据同步与运行时配置（SyncMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., SyncMixin, Star) 混入，self.* 照旧可用。

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

from .deps import *
from .consts import *
from .text import *
from .timeutil import *
from .util import *

PLUGIN_VERSION = "1.0.0"


class SyncMixin:

    async def _sync_profiles_to_data(self):
        """把本地画像补齐到数据插件：缺的补、改过的重推。不依赖一次性迁移标记。

        之前迁移是一次性的，标记写早了就永远是 0；这里改成每次都对一遍，
        而且推完再查一次条数，日志里能直接看到到底写进去没有。
        """
        mem = self._data_mem()
        store = self._data_store()
        if mem is None and store is None:
            return 0
        bot_id = self._data_bot_id()
        try:
            local = self.db.list_profiles(limit=500) or []
        except Exception as exc:
            logger.warning("[amo] 读本地画像失败: %s" % exc)
            return 0
        try:
            remote_rows = await self._data_call("list_profiles", bot_id, "", 500) or []
        except Exception:
            remote_rows = []
        if not remote_rows:
            # mem 门面不可用的旧版：直接读 DataStore
            lister = getattr(self._data_store(), "list_profiles", None)
            if callable(lister):
                try:
                    remote_rows = await asyncio.to_thread(lambda: lister(bot_id, "", 500)) or []
                except Exception:
                    remote_rows = []
        self._push_fail_count = 0
        remote = {}
        for row in remote_rows:
            if not isinstance(row, dict):
                continue
            uid = str(row.get("uid") or "")
            if uid:
                remote[uid] = row
        pushed = 0
        failed = 0
        pulled = 0
        for profile in local:
            if not isinstance(profile, dict):
                continue
            uid = str(profile.get("uid") or "")
            if not uid:
                continue
            name = str(profile.get("name") or "")
            alias = str(profile.get("alias") or "")
            relation = str(profile.get("relation") or "")
            remark = str(profile.get("notes") or "")
            old = remote.get(uid)
            if old is not None:
                if (
                    str(old.get("name") or "") == name
                    and str(old.get("alias") or "") == alias
                    and str(old.get("relation") or "") == relation
                    and str(old.get("remark") or "") == remark
                ):
                    continue
                # 数据插件里更新过（面板手动改了名字/关系）就以远端为准，拉回本地。
                # 比较基准是 profile_updated_at（本地手动改画像的时间），不是 last_seen：
                # last_seen 每收一条消息都会刷新，拿它比会把面板改动永远判成「更旧」。
                remote_at = to_float(old.get("updated_at"), 0)
                local_at = to_float(profile.get("profile_updated_at"), 0)
                if remote_at and remote_at > local_at:
                    if self._apply_remote_profile(uid, old, profile):
                        pulled += 1
                    continue
            try:
                ok = await self._push_profile_to_data(uid, profile)
            except Exception as exc:
                logger.warning("[amo] 推送画像 %s 异常: %s: %s" % (uid, type(exc).__name__, exc))
                ok = False
            if ok:
                pushed += 1
            else:
                failed += 1
        # 推完再查一次，拿到“真的写进去了多少条”
        after = []
        try:
            after = await self._data_call("list_profiles", bot_id, "", 500) or []
        except Exception:
            after = []
        if not after:
            lister = getattr(self._data_store(), "list_profiles", None)
            if callable(lister):
                try:
                    after = await asyncio.to_thread(lambda: lister(bot_id, "", 500)) or []
                except Exception:
                    after = []
        total = max(len(after), len(remote))
        message = (
            "[amo] 画像同步：本地 %d 条 / 数据插件 %d 条，本次补推 %d 条，拉回 %d 条，失败 %d 条"
            % (len(local), total, pushed, pulled, failed)
        )
        if failed:
            logger.warning(message)
            if failed >= len(local) and local:
                logger.warning(
                    "[amo] 画像一条都没写进去：先确认 Astr_Amo_data 已启用且版本 >= 2.0.4"
                )
        elif pushed or not getattr(self, "_profile_sync_logged", False):
            self._profile_sync_logged = True
            logger.info(message)
        else:
            logger.debug(message)
        return pushed

    async def _sync_with_data_plugin_once(self):
        """真正干活的同步；没找到数据插件就只记一笔、安排 60 秒后的一次提醒。"""
        mem = self._data_mem()
        if mem is None and self._data_store() is None:
            self._note_data_missing()
            return
        if not self._data_found_logged:
            self._data_found_logged = True
            logger.info("[amo] 已连接数据插件 Astr_Amo_data，开始同步")
        if self.wardrobe is not None:
            try:
                await self.wardrobe.refresh()
            except Exception as exc:
                logger.debug("[amo] 衣柜同步失败: %s" % exc)
        bot_id = self._data_bot_id()
        marker = "data_plugin_migrated_" + bot_id
        migrated = bool(self.db.kv_get(marker, False))
        if not migrated:
            pushed = {"relations": 0, "cache": 0}
            try:
                for edge in self.db.list_relations():
                    await self._push_relation_to_data(
                        edge.get("a_uid"), edge.get("b_uid"),
                        edge.get("relation"), edge.get("note"),
                    )
                    pushed["relations"] += 1
            except Exception as exc:
                logger.debug("[amo] 关系网迁移失败: %s" % exc)
            for key in ("schedule", "schedule_ctx", "schedule_profile", "worldview"):
                try:
                    value = self.db.kv_get(key, None)
                    if value:
                        await self._push_cache_to_data(key, value)
                        pushed["cache"] += 1
                except Exception:
                    pass
            self.db.kv_set(marker, True)
            logger.info("[amo] 已把关系网/日程缓存迁移到「我想永远陪着你-记忆」：%s" % pushed)
        # 画像每次都对齐（不看一次性标记）：缺的补、改过的重推
        try:
            await self._sync_profiles_to_data()
        except Exception as exc:
            logger.warning("[amo] 画像同步失败: %s" % exc)
        # 插件里有、本地没有的，补回本地
        try:
            rows = await self._data_call("list_relations", bot_id) or []
            for edge in rows:
                try:
                    self.db.upsert_relation(
                        edge.get("a_uid"), edge.get("b_uid"),
                        edge.get("relation") or "朋友", edge.get("note") or "",
                    )
                except Exception:
                    continue
        except Exception as exc:
            logger.debug("[amo] 拉取关系网失败: %s" % exc)
        try:
            rows = await self._data_call("list_profiles", bot_id, "", 500) or []
            for row in rows:
                uid = str(row.get("uid") or "")
                if not uid:
                    continue
                local = self.db.get_profile(uid) or {}
                if not local:
                    self.db.touch_profile(uid, str(row.get("name") or ""), "", "", "", True)
                    local = self.db.get_profile(uid) or {}
                # 只有数据插件里的这条更新（面板改过）才覆盖本地，否则以本地为准，
                # 免得上一条自动改名被旧值顶回去、来回打架。
                try:
                    remote_at = to_float(row.get("updated_at"), 0)
                    local_at = to_float(local.get("profile_updated_at"), 0)
                except Exception:
                    remote_at = local_at = 0
                if remote_at and remote_at <= local_at:
                    continue
                self._apply_remote_profile(uid, row, local)
        except Exception as exc:
            logger.debug("[amo] 拉取画像失败: %s" % exc)
        # 日程/世界观缓存：本地空的才用插件的
        for key, attr in (("schedule", "schedule"), ("schedule_ctx", "schedule_ctx"),
                          ("schedule_profile", "schedule_profile"), ("worldview", "worldview")):
            try:
                local = self.db.kv_get(key, None)
                if local:
                    continue
                value = await self._data_call("cache_get", bot_id, key)
                if value:
                    self.db.kv_set(key, value)
                    if self.state is not None:
                        setattr(self.state, attr, value)
            except Exception:
                continue
        # 到这里才算这次启动真的同步完了：以后不再探测、不再重复推
        self._data_synced = True
        self._data_missing_logged = False

    async def _apply_runtime_config(self):
        self._admin_cache = {}
        # 配置里的 bot_name 是空的就别拿「陪伴」把她名字盖掉（2026-11-20）：
        # 名字应该优先跟着人格走，否则「晓沫」这种叫法永远匹配不上。
        configured_name = str(self.cfg_str("bot_name", "") or "").strip()
        if configured_name:
            self.bot_name = configured_name
        else:
            try:
                persona_name = await self._persona_name_for("")
            except Exception:
                persona_name = ""
            if persona_name:
                self.bot_name = persona_name
            else:
                # 人格还没解析出来（刚启动很常见）：用上次记住的名字，别再退回「陪伴」
                try:
                    stored = str(self.db.kv_get("bot_name_last", "") or "").strip()
                except Exception:
                    stored = ""
                if stored:
                    self.bot_name = stored
                elif not str(getattr(self, "bot_name", "") or "").strip():
                    self.bot_name = "陪伴"
        self._persona_name_cache.clear()
        # 别把人格里带来的别名冲掉：配置里的 + 上次从人格里提的，合起来
        merged_aliases = [
            item.strip() for item in self.cfg_str("bot_aliases", "").split(",") if item.strip()
        ]
        try:
            stored_aliases = self.db.kv_get("bot_aliases_last", [])
        except Exception:
            stored_aliases = []
        for item in (stored_aliases if isinstance(stored_aliases, list) else []):
            text = str(item or "").strip()
            if text and text not in merged_aliases:
                merged_aliases.append(text)
        self.bot_aliases = merged_aliases
        self.admin_uids = {
            item.strip() for item in self.cfg_str("admin_uids", "").split(",") if item.strip()
        }
        if self.state is not None:
            start = self.cfg_str("period_start", "").strip()
            if start:
                self._set_period_start(start)
            try:
                await self.state.refresh_weather(force=True)
            except Exception:
                pass
        if HeartflowEngine is not None:
            old = self.heartflow
            if old is not None:
                try:
                    await old.terminate()
                except Exception:
                    pass
            try:
                hf_config = self._hf_config()
                hf_config.setdefault("enable_heartflow", True)
                hf_config.setdefault("enable_dynamic_threshold", True)
                hf_config.setdefault("judge_provider_name", "")
                self.heartflow = HeartflowEngine(self.context, hf_config)
                try:
                    self.heartflow.plugin = self
                except Exception:
                    pass
                self.heartflow.set_identity(self.bot_name, self.bot_aliases)
            except Exception as exc:
                logger.error("[amo] 应用心流配置失败: %s" % exc)

    async def _status_data(self):
        self._reload_config_if_changed()
        umo = self._last_umo or self._first_private_umo()
        if not self.state.weather:
            self.state.weather = self.state._simulate_weather()
        desired_city = (
            self.cfg_str("weather_city_name", "").strip()
            or self.cfg_str("weather_city", "").strip()
            or str((getattr(self.state, "schedule_profile", {}) or {}).get("city") or "").strip()
            or "贵阳"
        )
        if self.state.weather.get("city") != desired_city:
            await self.state.refresh_weather(force=True)
        else:
            self._spawn(self.state.refresh_weather())
        if not self.state.worldview:
            self.state.worldview = self.state._fallback_world()
            self._spawn(self.state.ensure_worldview(umo))
        if (
            not self.state.schedule.get(today_str())
            or self.db.kv_get("schedule_version", "") != SCHEDULE_VERSION
            or not self.state.schedule_context(today_str())
        ):
            await self.state.ensure_schedule(umo)
        snap = self.state.snapshot()
        activity = 0.0
        threshold = {"value": 0.0, "base": 0.0, "absolute": 0.0}
        if self.heartflow is not None:
            try:
                hf_threshold, hf_activity, hf_absolute = self.heartflow._get_dynamic_threshold(umo)
                threshold = {
                    "value": round(float(hf_threshold) * 100, 1),
                    "base": round(float(self.heartflow.reply_threshold) * 100, 1),
                    "absolute": round(float(hf_absolute), 1),
                }
                activity = float(hf_activity) * 100
            except Exception as exc:
                logger.debug("[amo] 心流阈值读取失败: %s" % exc)
        counts = self.db.counts()
        # 记忆条数改成外挂插件的：本插件不再存记忆，面板显示外部模块里的条数
        primary_uid = ""
        try:
            primary = self.db.list_profiles(limit=1)
            primary_uid = str(primary[0].get("uid") or "") if primary else ""
        except Exception:
            primary_uid = ""
        try:
            # 状态页会被轮询，但记忆条数必须跟写入同步：读一次 sqlite 很便宜，
            # 30 秒缓存会让“刚记住”在面板上消失，用户只能手动刷新。
            counts["memories"] = self._data_memory_count(primary_uid) if primary_uid else 0
        except Exception:
            counts["memories"] = 0
        return {
            "time": snap["datetime_text"],
            "day": day_meta(),
            "feel": snap.get("feel") or {},
            "feel_rel": snap.get("feel_rel") or {},
            "heartflow": (self.feelings.values() if getattr(self, "feelings", None) else {}),
            "period": snap["period"],
            "health": snap["health"],
            "weather": snap["weather"],
            "weather_text": snap["weather_text"],
            "activity": snap["activity"],
            "schedule": snap["schedule"],
            "schedule_tree": self.state.schedule_tree(),
            "worldview": self.state.worldview,
            "threshold": threshold,
            "activity_rate": round(activity, 2),
            "counts": counts,
            "config": {
                "enable_group_reply": self.cfg_bool("enable_group_reply", True),
                "enable_private_reply": self.cfg_bool("enable_private_reply", True),
                "auto_active_msg": self.cfg_bool("auto_active_msg", True),
                "heartflow": self.heartflow is not None,
                "weather_key_set": bool(self.cfg_str("hefeng_key", "")),
                "weather_host": self.cfg_str("weather_host", "https://devapi.qweather.com"),
                "version": PLUGIN_VERSION,
                "dialect_style": self._dialect_style(),
                "dialect_count": len(self._dialect_rows()) if self._dialect_active() else 0,
            },
            "data_plugin": {
                "name": "Astr_Amo_data",
                "connected": self._data_connected(),
                "synced": bool(self._data_synced),
            },
        }

    async def _ensure_dialect_kb(self):
        """把方言同步进 AstrBot 知识库；失败会明确写日志，不再静默。"""
        if not self._dialect_active():
            return None
        if not self.cfg_bool("create_dialect_kb", True):
            return None
        try:
            manager = getattr(self.context, "kb_manager", None)
            if manager is None:
                logger.warning("[amo] 当前 AstrBot 没有 kb_manager，无法创建知识库")
                return None
            if callable(manager) and not hasattr(manager, "create_kb"):
                try:
                    manager = manager()
                except Exception:
                    manager = None
            if manager is None or not hasattr(manager, "create_kb"):
                logger.warning("[amo] kb_manager 不支持 create_kb，无法创建知识库")
                return None
            name = self._dialect_kb_name()
            kb = await manager.get_kb_by_name(name)
            if kb is None:
                providers = []
                getter = getattr(self.context, "get_all_embedding_providers", None)
                if callable(getter):
                    try:
                        providers = list(getter() or [])
                    except Exception:
                        providers = []
                if not providers:
                    pm = getattr(self.context, "provider_manager", None)
                    providers = list(getattr(pm, "embedding_provider_insts", []) or [])
                if not providers:
                    logger.warning(
                        "[amo] 没有可用的 Embedding 供应商，知识库未创建；"
                        "请先在 AstrBot 模型提供商里配置 embedding"
                    )
                    return None
                provider_id = self._embedding_provider_id(providers[0])
                if not provider_id:
                    logger.warning("[amo] Embedding 供应商没有有效 id，知识库未创建")
                    return None
                try:
                    created = manager.create_kb(
                        name,
                        "陪伴角色方言与口语表达，用于聊天时的自然替换",
                        emoji="🗣️",
                        embedding_provider_id=provider_id,
                    )
                    kb = await created if inspect.isawaitable(created) else created
                except Exception as exc:
                    logger.warning("[amo] 创建知识库 %s 失败: %s" % (name, exc), exc_info=True)
                    return None

            rows = []
            try:
                rows = self._dialect_rows()
            except Exception:
                rows = []
            lines = [
                "%s（%s）：普通话“%s”，例：%s" % (
                    row.get("term", ""), row.get("region", ""),
                    row.get("meaning", ""), row.get("example", ""),
                )
                for row in rows
                if row.get("term") and row.get("meaning")
            ]
            if lines:
                try:
                    docs = await kb.list_documents(search="amo_dialect")
                    for doc in docs or []:
                        doc_id = getattr(doc, "doc_id", "") or getattr(doc, "id", "")
                        if doc_id:
                            await kb.delete_document(doc_id)
                except Exception as exc:
                    logger.warning("[amo] 清理旧方言文档失败: %s" % exc)
                try:
                    await kb.upload_document(
                        "amo_dialect.txt",
                        "\n".join(lines).encode("utf-8"),
                        "txt",
                        pre_chunked_text=lines,
                    )
                except Exception as exc:
                    logger.warning("[amo] 方言知识库上传失败: %s" % exc, exc_info=True)
            logger.debug("[amo] 知识库 %s 已同步，写入 %d 条方言" % (name, len(lines)))
            return kb
        except Exception as exc:
            logger.warning("[amo] 方言知识库创建失败: %s" % exc, exc_info=True)
            return None


__all__ = [
    "PLUGIN_VERSION",
    "SyncMixin",
]
