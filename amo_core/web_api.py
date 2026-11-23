# -*- coding: utf-8 -*-
"""Amo 终端 · Web 面板接口（WebApiMixin）

从 main.py 的 HumanCorePlugin 整体搬出来的 49 个 api_* 方法，方法体逐行未改。
由 HumanCorePlugin(WebApiMixin, Star) 混入，所以 self.* 照旧可用。

注意：constants / helpers 只在这里或 amo_core 里有一份，不要在 main.py 再定义一份。
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



def _panel_default_uid_of(plugin):
    """面板调试用的默认 uid：恋人 → 管理员 → 最近有画像的人；都没有就空串。

    以前这里写死了一个 QQ 号，换号或者别人用就不对了。
    """
    try:
        for _name, uid in (plugin._lover_aliases() or {}).items():
            if uid:
                return str(uid)
    except Exception:
        pass
    try:
        admins = sorted(plugin.admin_uids or [])
        if admins:
            return str(admins[0])
    except Exception:
        pass
    try:
        for row in plugin.db.list_profiles("", 20):
            if row.get("uid"):
                return str(row["uid"])
    except Exception:
        pass
    return ""


class WebApiMixin:

    def _panel_default_uid(self):
        return _panel_default_uid_of(self)


    async def api_weather_brief(self):
        """面板用：当前天气一行摘要 + 配置里的城市（只读缓存）。"""
        await self._ensure_ready()
        if not self.state.weather:
            try:
                await self.state.refresh_weather()
            except Exception as exc:
                logger.debug("[amo] 面板取天气失败: %s" % exc)
        return {
            "code": 0,
            "data": {
                "weather": self.state.weather_brief(),
                "city": self.cfg_str("weather_city", ""),
                "city_name": self.cfg_str("weather_city_name", ""),
            },
        }

    async def api_city_search(self):
        """面板用：中文城市名候选。"""
        await self._ensure_ready()
        query = str(self._q("q", "") or "").strip()
        if not query:
            data = await self._body()
            if isinstance(data, dict):
                query = str(data.get("q") or "").strip()
        if not query:
            return {"code": 0, "data": {"items": [], "query": ""}}
        module = self._city_module()
        if module is None:
            return {"code": 1, "msg": "城市表缺失：amo_city_index.py 没装好"}
        try:
            items = module.search_city(query, 20)
        except Exception as exc:
            return {"code": 1, "msg": "城市表读取失败：%s" % exc}
        return {"code": 0, "data": {"items": items, "query": query}}

    async def api_city_set(self):
        """面板用：中文城市名 → 写入 weather_city(LocationID) + 城市显示名。"""
        await self._ensure_ready()
        data = await self._body()
        data = data if isinstance(data, dict) else {}
        text = str(data.get("city") or data.get("q") or "").strip()
        if not text:
            return {"code": 1, "msg": "请填写城市名"}
        hit = self._city_lookup(text)
        if not hit:
            return {
                "code": 1,
                "msg": "没找到「%s」；重名或冷门地方请写「省+市」，例如「广东东莞」「北京朝阳」" % text,
            }
        save = False
        if str(self.config.get("weather_city") or "") != str(hit["id"]):
            self.config["weather_city"] = str(hit["id"])
            save = True
        if not data.get("keep_name"):
            if self.cfg_str("weather_city_name", "").strip() != hit["name"]:
                self.config["weather_city_name"] = hit["name"]
                save = True
        if save:
            try:
                if hasattr(self.config, "save_config"):
                    self.config.save_config()
            except Exception as exc:
                return {"code": 1, "msg": "保存配置失败：%s" % exc}
        weather = None
        if not save and self.state.weather:
            # 城市没变，别为一次「设置」白打接口
            weather = self.state.weather
        else:
            try:
                weather = await self.state.refresh_weather(force=bool(save))
            except Exception as exc:
                logger.debug("[amo] 切换城市后刷新天气失败: %s" % exc)
        return {
            "code": 0,
            "data": {
                "id": hit["id"], "name": hit["name"],
                "label": hit["label"], "weather": weather or {},
                "ambiguous": hit.get("ambiguous", 0),
                "candidates": hit.get("candidates", []),
                "note": hit.get("note", ""),
            },
        }

    async def api_config(self):
        await self._ensure_ready()
        # 面板「设置」打开前先跟 AstrBot 的配置文件对一次：
        # 你在原生设置页改过、还没触发下一轮对话时，内存里还是旧值。
        try:
            self._reload_config_if_changed()
        except Exception as exc:
            logger.debug("[amo] 读取配置前重载失败: %s" % exc)
        items = self._config_schema_items()
        notes = {}
        try:
            voice_items = self._voice_panel_items()
            items.extend(voice_items)
            if not voice_items:
                notes["语音"] = ("没找到「我想永远陪着你-语音」（未安装或未启用）。"
                                  "装好并启用它，语音设置才会出现在这里；key、后端、音色仍在它自己的配置页填。")
        except Exception as exc:
            logger.warning("[amo] 读取语音设置失败: %s" % exc)
            notes["语音"] = "读取语音设置失败：%s" % exc
        return {"code": 0, "data": {"items": items, "groupNotes": notes}}

    async def api_providers(self):
        """面板下拉用：列出已配置的模型供应商（脱敏），并标注心流判定/主对话模型。"""
        await self._ensure_ready()
        judge_id = self._judge_provider_id()
        using_id = self._using_provider_id()
        items = self._provider_inventory()
        for item in items:
            item["judge"] = bool(judge_id) and item["id"] == judge_id
            item["using"] = bool(using_id) and item["id"] == using_id
        return {"code": 0, "data": {"items": items}}

    async def api_usage(self):
        await self._ensure_ready()
        if not self.cfg_bool("usage_stats_enabled", True):
            return {"code": 0, "data": {"enabled": False}}
        db_path = self._usage_db_path()
        prices = self._usage_prices()
        day_start = self._usage_start_of_today()

        def build():
            result = {"enabled": True, "currency": "元", "prices": prices}
            try:
                result["clock"] = usage_clock(_now())
            except Exception as exc:
                logger.debug("[amo] 峰谷分段失败: %s" % exc)
            for label, start in (("today", day_start), ("week", day_start - 6 * 86400), ("total", None)):
                usage = summarize_token_usage(db_path, start)
                usage["cost"] = usage_cost(usage, prices)
                # 插件内部调用（判分/日记）不进 provider_stats，这里补自记账
                internal = self.db.usage_since(start)
                usage["internal"] = internal
                usage["all_calls"] = int(usage.get("calls") or 0) + int(internal["calls"])
                usage["all_input"] = (int(usage.get("input_miss") or 0) + int(usage.get("input_cached") or 0)
                                      + int(internal["input_other"]) + int(internal["input_cached"]))
                usage["all_output"] = int(usage.get("output") or 0) + int(internal["output"])
                # 面板要能一眼看到「一共跑了多少」，不能只给主回复那一半
                usage["all_total"] = int(usage["all_input"]) + int(usage["all_output"])
                usage["internal_total"] = (int(internal["input_other"]) + int(internal["input_cached"])
                                            + int(internal["output"]))
                usage["all_cost"] = float(usage.get("cost") or 0) + float(internal["cost"])
                result[label] = usage
            return result

        data = await asyncio.to_thread(build)
        if self.cfg_bool("deepseek_balance_enabled", True):
            data["balance"] = await self._balance_cached()
        else:
            data["balance"] = {"ok": False, "error": "余额查询已关闭"}
        # 多模型用量：已配置供应商 + 逐个余额探测 + 按模型匹配今日 token
        providers = self._provider_inventory()
        judge_id = self._judge_provider_id()
        using_id = self._using_provider_id()
        today_by_model = {}
        for entry in (data.get("today", {}) or {}).get("by_model", []) or []:
            today_by_model[str(entry.get("model") or "")] = entry
        # 判分/摘要这些内部调用也吃同一份额度，模型卡片不能只算主回复
        internal_by_model = ((data.get("today") or {}).get("internal") or {}).get("by_model") or {}
        for item in providers:
            item["judge"] = bool(judge_id) and item["id"] == judge_id
            item["using"] = bool(using_id) and item["id"] == using_id
            stats = today_by_model.get(item["model"]) or today_by_model.get(item["id"]) or {}
            tokens = int(stats.get("input_miss") or 0) + int(stats.get("input_cached") or 0) + int(stats.get("output") or 0)
            extra = internal_by_model.get(str(item.get("model") or "")) or {}
            extra_tokens = (int(extra.get("input_other") or 0) + int(extra.get("input_cached") or 0)
                            + int(extra.get("output") or 0))
            item["today_tokens"] = tokens + extra_tokens
            item["today_internal_tokens"] = extra_tokens
            item["today_calls"] = int(stats.get("calls") or 0) + int(extra.get("calls") or 0)
            item["today_cost"] = float(stats.get("cost") or 0) if isinstance(stats.get("cost"), (int, float)) else 0.0
        if self.cfg_bool("usage_balance_enabled", True) and self.cfg_bool("deepseek_balance_enabled", True):
            balances = await self._provider_balances_cached(providers)
            by_id = {str(item.get("id") or ""): item for item in balances}
            for item in providers:
                item["balance"] = by_id.get(item["id"]) or {"ok": False, "error": "未配置密钥或地址"}
        else:
            for item in providers:
                item["balance"] = {"ok": False, "error": "余额查询已关闭"}
        data["providers"] = providers
        return {"code": 0, "data": data}

    async def api_balance(self):
        await self._ensure_ready()
        data = await self._balance_cached()
        return {"code": 0, "data": data}

    async def api_voice_save(self):
        """把「语音」分组里的设置写进语音插件（内存立即生效 + 落盘）。"""
        await self._ensure_ready()
        data = await self._body()
        changes = data.get("changes") if isinstance(data.get("changes"), dict) else data
        plugin = self._voice_plugin()
        if plugin is None:
            return {"code": 1, "msg": "没找到「我想永远陪着你-语音」（未安装或未启用）"}
        config = getattr(plugin, "config", None)
        if config is None or not hasattr(config, "update"):
            return {"code": 1, "msg": "语音插件的配置对象不可写"}
        kinds = {key: kind for key, kind, _t, _h, _d in self.VOICE_SETTING_KEYS}
        applied = {}
        for key, value in (changes or {}).items():
            kind = kinds.get(key)
            if not kind:
                continue
            try:
                applied[key] = self._coerce_config_value(kind, value)
            except Exception as exc:
                logger.warning("[amo] 语音设置 %s 值无效: %s" % (key, exc))
                continue
        if not applied:
            return {"code": 0, "data": {"saved": {}, "persisted": False}}
        try:
            config.update(applied)
        except Exception as exc:
            logger.error("[amo] 写入语音插件配置失败: %s" % exc)
            return {"code": 1, "msg": "写入失败：" + str(exc)}
        persisted = False
        saver = getattr(plugin, "_persist_config", None)
        if callable(saver):
            try:
                result = saver()
                if hasattr(result, "__await__"):
                    result = await result
                persisted = bool(result)
            except Exception as exc:
                logger.warning("[amo] 语音设置落盘失败（内存已生效）: %s" % exc)
        logger.debug("[amo] 语音设置已更新: %s" % ", ".join(sorted(applied)))
        return {"code": 0, "data": {"saved": applied, "persisted": persisted}}

    async def api_config_save(self):
        await self._ensure_ready()
        data = await self._body()
        changes = data.get("changes") if isinstance(data.get("changes"), dict) else data
        schema = self._schema_map()
        saved = {}
        for key, value in (changes or {}).items():
            if key in FORCED_ON_CONFIG_KEYS:
                continue
            meta = schema.get(key)
            if not isinstance(meta, dict):
                # 操作页的「语种」下拉不在 schema 里，单独放行（普通话/各地方言）
                if key == "dialect_style":
                    meta = {"type": "string", "default": ""}
                else:
                    continue
            try:
                coerced = self._coerce_config_value(meta.get("type", "string"), value)
            except Exception as exc:
                logger.warning("[amo] 配置 %s 值无效: %s" % (key, exc))
                continue
            if key in self.SENSITIVE_KEYS:
                current = str(self.cfg(key, "") or "")
                incoming = str(coerced or "")
                # 面板回传的是打码串、或者干脆留空 → 当作"不修改"，别把真 key 覆盖掉
                if not incoming or incoming == self._mask_secret(current):
                    continue
            self.config[key] = coerced
            saved[key] = coerced
        if saved:
            try:
                if hasattr(self.config, "save_config"):
                    self.config.save_config()
            except Exception as exc:
                logger.error("[amo] 保存插件配置失败: %s" % exc)
                return {"code": 1, "msg": "保存配置失败：" + str(exc)}
            try:
                await self._apply_runtime_config()
            except Exception as exc:
                logger.error("[amo] 应用配置失败: %s" % exc)
        return {"code": 0, "data": {"saved": saved}}

    async def api_profiles_sync(self):
        # 4.3.2 起用户画像只来自本插件聊天/手动建档；
        # 不再把记忆插件的用户导入画像，记忆由 LLM hook 读取。
        return {
            "code": 0,
            "data": {"synced": 0, "profiles": self.db.list_profiles(limit=500)},
            "msg": "原版模式：画像只从聊天建立，不再从记忆插件同步用户",
        }

    async def api_relations(self):
        await self._ensure_ready()
        profiles = self.db.list_profiles(limit=500)
        names = {str(item.get("uid")): (item.get("alias") or item.get("name") or item.get("uid")) for item in profiles}
        names["bot"] = str(getattr(self, "bot_name", "") or "你")
        edges = []
        for edge in self.db.list_relations():
            row = dict(edge)
            row["a_name"] = names.get(str(row.get("a_uid")), row.get("a_uid"))
            row["b_name"] = names.get(str(row.get("b_uid")), row.get("b_uid"))
            edges.append(row)
        # 画像里显式设过的关系要压过自动沉淀：否则把对方设成「恋人」，
        # 关系图还停在 relation_sediment 自动算出来的「熟人」。
        by_pair = {}
        for row in edges:
            key = tuple(sorted([str(row.get("a_uid") or ""), str(row.get("b_uid") or "")]))
            by_pair[key] = row
        for profile in profiles:
            uid = str(profile.get("uid") or "").strip()
            relation = str(profile.get("relation") or "").strip()
            if not uid or not relation or uid in INTERNAL_RELATION_NODES:
                continue
            relation = {"相恋": "恋人", "熟识": "熟人", "仇恨": "仇人"}.get(relation, relation)
            if relation in ("普通", ""):
                continue
            key = tuple(sorted(["bot", uid]))
            row = by_pair.get(key)
            if row is None:
                row = {
                    "a_uid": "bot", "b_uid": uid, "relation": relation,
                    "note": "画像：关系字段", "updated_at": 0,
                    "a_name": names.get("bot", "你"), "b_name": names.get(uid, uid),
                }
                edges.append(row)
                by_pair[key] = row
            elif str(row.get("relation") or "") != relation:
                row["relation"] = relation
                row["note"] = "画像：关系字段"
        return {"code": 0, "data": {"edges": edges, "profiles": profiles, "relations": list(NETWORK_RELATIONS)}}

    async def api_profile_links(self):
        """面板用：这个 UID 关联了哪些平台身份（QQ / 飞书等）。"""
        data = await self._body()
        uid = str(data.get("uid") or "").strip()
        platform = str(data.get("platform") or "").strip() or "aiocqhttp"
        if not uid:
            return {"code": 0, "data": {"links": []}}
        mem = self._data_mem()
        if mem is None or not callable(getattr(mem, "person_context", None)):
            return {"code": 0, "data": {"links": []}}
        try:
            detail = await self._data_call("person_context", self._data_bot_id(), platform, uid, 1)
        except Exception as exc:
            logger.debug("[amo] 读取关联身份失败: %s" % exc)
            detail = {}
        links = []
        for item in (detail or {}).get("links") or []:
            links.append({
                "platform": str(item.get("platform") or ""),
                "label": str(item.get("label") or item.get("platform") or ""),
                "uid": str(item.get("uid") or ""),
                "name": str(item.get("name") or ""),
            })
        return {"code": 0, "data": {"links": links}}

    async def api_profile_delete(self):
        """面板用：删掉一个人的档案，并把本插件跟他有关的引用清干净。

        清掉：profiles / messages / proactive_log / relation_network、
              他专属的 kv（channels:、last_channel:、节流、主动消息、纪念日…）、
              礼物心愿与礼物墙、内存里的临时缓存。
        不清（属于别处）：AstrBot 核心会话库、牢记/livingmemory 等记忆插件的库。
        """
        await self._ensure_ready()
        data = await self._body()
        data = data if isinstance(data, dict) else {}
        uid = str(data.get("uid") or "").strip()
        confirm = str(data.get("confirm") or "").strip().lower()
        if not uid:
            return {"code": 1, "msg": "缺少 uid"}
        if confirm not in ("1", "true", "yes", "on"):
            return {"code": 1, "msg": "删除档案需要确认：再带一次 confirm=1"}
        profile = {}
        try:
            profile = self.db.get_profile(uid) or {}
        except Exception:
            profile = {}
        umos = set()
        for value in (profile.get("private_umo"), profile.get("last_group")):
            if value:
                umos.add(str(value))
        try:
            channels = self.db.kv_get("channels:%s" % uid, {}) or {}
            if isinstance(channels, dict):
                for entry in channels.values():
                    if isinstance(entry, dict) and entry.get("umo"):
                        umos.add(str(entry["umo"]))
        except Exception:
            pass
        counts = {}
        try:
            for table in ("profiles", "messages", "proactive_log"):
                try:
                    cur = self.db.conn.execute("DELETE FROM %s WHERE uid=?" % table, (uid,))
                    counts[table] = max(0, cur.rowcount or 0)
                except Exception as exc:
                    logger.debug("[amo] 删除档案时清理 %s 失败: %s" % (table, exc))
            try:
                cur = self.db.conn.execute(
                    "DELETE FROM relation_network WHERE a_uid=? OR b_uid=?", (uid, uid)
                )
                counts["relation_network"] = max(0, cur.rowcount or 0)
            except Exception as exc:
                logger.debug("[amo] 删除档案时清理关系网失败: %s" % exc)
            counts["kv"] = self._purge_profile_kv(uid)
            try:
                self.db.conn.commit()
            except Exception:
                pass
        except Exception as exc:
            return {"code": 1, "msg": "删除失败：%s" % exc}
        try:
            if str(getattr(self, "_last_umo", "") or "") in umos:
                self._last_umo = ""
            cache = getattr(self, "_last_reply_at", None)
            if isinstance(cache, dict):
                for umo in umos:
                    cache.pop(umo, None)
        except Exception:
            pass
        logger.debug("[amo] 已删除档案 %s（清理 %s）" % (uid, counts))
        return {"code": 0, "msg": "已删除", "data": {"uid": uid, "counts": counts}}

    async def api_relation_save(self):
        await self._ensure_ready()
        data = await self._body()
        a_uid = str(data.get("a_uid") or "").strip()
        b_uid = str(data.get("b_uid") or "").strip()
        relation = str(data.get("relation") or "朋友").strip()
        note = str(data.get("note") or "").strip()
        if not a_uid or not b_uid or a_uid == b_uid:
            return {"code": 1, "msg": "请选择两个不同的用户"}
        if relation not in NETWORK_RELATIONS:
            return {"code": 1, "msg": "关系类型无效"}
        self.db.upsert_relation(a_uid, b_uid, relation, note)
        try:
            await self._push_relation_to_data(a_uid, b_uid, relation, note)
        except Exception as exc:
            logger.debug("[amo] 关系同步失败: %s" % exc)
        logger.debug("[amo] 关系网更新: %s <-> %s = %s" % (a_uid, b_uid, relation))
        return await self.api_relations()

    async def api_relation_delete(self):
        await self._ensure_ready()
        data = await self._body()
        a_uid = str(data.get("a_uid") or "").strip()
        b_uid = str(data.get("b_uid") or "").strip()
        if not a_uid or not b_uid:
            return {"code": 1, "msg": "缺少用户"}
        self.db.delete_relation(a_uid, b_uid)
        await self._data_call("delete_relation", self._data_bot_id(), a_uid, b_uid)
        return await self.api_relations()

    async def api_brain(self):
        """记忆只有两样：思维图（人物关系）+ 她在想什么。"""
        await self._ensure_ready()
        edges, persons, thoughts = [], [], []
        try:
            rel = await self.api_relations()
            edges = ((rel or {}).get("data") or {}).get("edges") or []
        except Exception as exc:
            logger.debug("[amo] 思维图读取失败: %s" % exc)
        try:
            prof = await self.api_profiles()
            persons = (prof or {}).get("data") or []
        except Exception as exc:
            logger.debug("[amo] 人物列表读取失败: %s" % exc)
        try:
            thoughts = self._brain_thoughts()
        except Exception as exc:
            logger.debug("[amo] 想法读取失败: %s" % exc)
        now = {}
        try:
            now = {"activity": self.state.current_activity() or {},
                   "feel": self.state.feel_snapshot() if hasattr(self.state, "feel_snapshot") else {}}
        except Exception:
            now = {}
        return {"code": 0, "data": {"edges": edges, "persons": persons,
                                    "thoughts": thoughts, "now": now}}

    async def api_records(self):
        """面板「想法」页：只读转发记忆库的 records（只增不改，面板删不掉）。"""
        await self._ensure_ready()
        payload = await self._body()
        try:
            limit = int((payload or {}).get("limit") or 100)
        except Exception:
            limit = 100
        bot_id = ""
        try:
            getter = getattr(self, "_data_bot_id", None)
            if callable(getter):
                bot_id = str(getter() or "")
        except Exception:
            bot_id = ""
        store = self._data_store()
        reader = getattr(store, "records_list", None) if store is not None else None
        if not callable(reader):
            return {"code": 1, "msg": "记忆库没连上，记录读不到"}
        try:
            # store 是同步的 SQLite 门面：放到线程里，别卡事件循环。
            data = await asyncio.to_thread(reader, bot_id, "", limit, 0)
        except Exception as exc:
            logger.warning("[amo] 读取记录失败: %s" % exc)
            return {"code": 1, "msg": "读取记录失败"}
        if not isinstance(data, dict):
            return {"code": 1, "msg": "记录返回异常"}
        return {"code": 0, "data": data}

    async def api_events(self):
        """事件总线观测：统计 + 最近几条，排查用。"""
        return {"code": 0, "data": self.event_status()}

    async def api_dispatch(self, action: str = ""):
        await self._ensure_ready()
        name = (action or "").replace("/", "_").strip("_").lower()
        try:
            if name in ("", "index", "status", "get_status"):
                return await self.api_get_status()
            if name in ("profiles", "profile_list"):
                return await self.api_profiles()
            if name in ("profile_delete", "delete_profile"):
                return await self.api_profile_delete()
            if name in ("profile_save", "save_profile"):
                return await self.api_profile_save()
            if name in ("memories", "memory_list"):
                return await self.api_memories()
            if name in ("memory_add", "add_memory"):
                return await self.api_memory_add()
            if name in ("memory_delete", "delete_memory"):
                return await self.api_memory_delete()
            if name == "schedule":
                return await self.api_schedule()
            if name in ("scenic_kb_regen", "regen_scenic_kb"):
                return await self.api_scenic_kb_regen()
            if name in ("kb_regen", "regen_kb", "dialect_kb_regen"):
                return await self.api_kb_regen()
            if name in ("schedule_regen", "regen_schedule"):
                return await self.api_schedule_regen()
            if name in ("weather", "weather_refresh", "refresh_weather"):
                return await self.api_weather()
            if name == "worldview":
                return await self.api_worldview()
            if name in ("worldview_regen", "regen_worldview"):
                return await self.api_worldview_regen()
            if name in ("say", "send"):
                return await self.api_say()
            if name in ("refresh_status", "refresh"):
                return await self.api_refresh_status()
            if name in ("get_profile", "profile"):
                return await self.api_get_profile()
            return {"code": 1, "msg": "未知接口：" + name}
        except Exception as exc:
            logger.error("[amo] Web API %s 异常: %s" % (name, exc))
            return {"code": 1, "msg": str(exc)}

    async def api_status(self):
        await self._ensure_ready()
        data = await self._status_data()
        return {"code": 0, "data": data}

    async def api_get_status(self):
        await self._ensure_ready()
        data = await self._status_data()
        return {
            "code": 0,
            "data": {
                "mood": data["dominant"] + "（" + data["mood"].__str__() + "）",
                "schedule": data["activity"].get("activity", ""),
                "health": data["health"]["status"],
                "period": data["period"]["phase"] + " 第" + str(data["period"]["day"]) + "天",
                "weather": data["weather_text"],
                "switch_status": data["config"],
                "threshold": data["threshold"],
                "counts": data["counts"],
            },
        }

    async def api_get_profile(self):
        await self._ensure_ready()
        data = await self._body()
        uid = str(data.get("uid") or self._q("uid", "") or "")
        if uid:
            profile = self.db.get_profile(uid)
        else:
            profiles = self.db.list_profiles(limit=1)
            profile = profiles[0] if profiles else {}
        mem_uid = str(profile.get("uid") or uid or "")
        mem_count = self._data_memory_count(mem_uid)
        return {
            "code": 0,
            "data": {
                "relation": profile.get("relation", "普通"),
                "mem_count": mem_count,
                "profile": profile,
            },
        }

    async def api_refresh_status(self):
        await self._ensure_ready()
        # 限频：这个接口会强制刷新天气（和风额度），被 <img>/外链或连点触发时不能每次都打出去
        now = now_ts()
        last = to_float(getattr(self, "_refresh_status_at", 0), 0)
        if last and now - last < 5:
            return {"code": 0, "msg": "刚刚刷新过，请稍候", "data": {"throttled": True}}
        self._refresh_status_at = now
        try:
            await self.state.refresh_weather(force=True)
        except Exception as exc:
            logger.warning("[amo] 手动刷新天气失败: %s" % exc)
            return {"code": 1, "msg": "刷新失败：%s" % exc}
        return {"code": 0, "msg": "刷新成功"}

    async def api_profiles(self):
        await self._ensure_ready()
        data = await self._body()
        keyword = str(data.get("q") or self._q("q", "") or "")
        limit = to_int(data.get("limit") or self._q("limit", 100), 100)
        return {"code": 0, "data": self.db.list_profiles(keyword, limit)}

    async def api_profile_save(self):
        await self._ensure_ready()
        data = await self._body()
        uid = str(data.get("uid") or "").strip()
        if not uid:
            return {"code": 1, "msg": "uid 不能为空"}
        fields = {}
        for key in ("name", "alias", "birthday", "relation", "notes"):
            value = data.get(key, None)
            if value is not None:
                if key == "notes" and _looks_auto_note(value):
                    value = ""
                fields[key] = str(value)[:100]
        if "relation" in fields and fields["relation"] not in RELATIONS:
            return {"code": 1, "msg": "关系只能是：" + "、".join(RELATIONS)}
        if "birthday" in fields and fields["birthday"]:
            match = re.match(r"^(\d{4}-)?(\d{1,2})-(\d{1,2})$", fields["birthday"])
            if not match:
                return {"code": 1, "msg": "生日格式应为 MM-DD 或 YYYY-MM-DD"}
            fields["birthday"] = "%02d-%02d" % (to_int(match.group(2)), to_int(match.group(3)))
        affection = data.get("affection", None)
        if affection is not None:
            fields["affection"] = int(clamp(to_int(affection, 10), 0, 100))
        if not self.db.get_profile(uid):
            self.db.touch_profile(uid, fields.get("name", ""), "web", "", "", True)
        self.db.update_profile(uid, **fields)
        if fields.get("relation") == "相恋":
            self._register_lover(uid)
        if fields.get("relation"):
            await self._sync_profile_relation_edge(uid, fields["relation"])
        try:
            await self._push_profile_to_data(uid, self.db.get_profile(uid))
        except Exception as exc:
            logger.debug("[amo] 画像同步失败: %s" % exc)
        return {"code": 0, "data": self.db.get_profile(uid)}

    async def api_chat_history(self):
        await self._ensure_ready()
        data = await self._body()
        uid = str(data.get("uid") or self._q("uid", "") or "")
        if not uid:
            return {"code": 1, "msg": "uid 不能为空"}
        limit = to_int(data.get("limit") or self._q("limit", 200), 200)
        profile = self.db.get_profile(uid) or {}
        # 面板的“读取记忆”先读记忆终端；数据插件是主终端，不能只读外挂插件，
        # 否则装的是 Astr_Amo_data 时这里永远显示 0 条。
        memories = await self._data_mem_list(uid, "", limit)
        return {
            "code": 0,
            "data": {
                # 本地不再写聊天：面板聊天记录也要从记忆终端取，否则新消息永远为空。
                "chat": await self._recent_by_uid(uid, limit),
                "memories": memories,
            },
        }

    async def api_memories(self):
        """面板记忆页：只读外挂记忆插件的记忆（本插件不再存记忆）。"""
        await self._ensure_ready()
        data = await self._body()
        uid = str(data.get("uid") or self._q("uid", "") or "")
        if not uid:
            return {"code": 1, "msg": "uid 不能为空"}
        keyword = str(data.get("q") or self._q("q", "") or "")
        limit = self._q_int("limit", 50)
        items = await self._data_mem_list(uid, keyword, limit)
        return {"code": 0, "data": items[:max(1, min(100, limit))]}

    async def api_memory_add(self):
        """面板“添加记忆”改为写进外挂记忆插件。"""
        await self._ensure_ready()
        data = await self._body()
        uid = str(data.get("uid") or "").strip()
        content = str(data.get("content") or "").strip()
        if not uid or not content:
            return {"code": 1, "msg": "uid 和 content 不能为空"}
        tier = to_int(data.get("tier", 1), 1)
        kind = str(data.get("kind", "manual"))
        scope = str(data.get("scope") or "private")
        group_id = str(data.get("group_id") or "")
        # 面板点“记住”要等真的写进去再返回，否则紧接着点“读取记忆”会空一次，
        # 用户只能再刷新；旧代码 fire-and-forget，写失败也报成功。
        if await self._write_memory_checked(uid, content, kind, tier, scope, group_id):
            return {"code": 0, "msg": "已写入记忆库"}
        return {"code": 1, "msg": "记忆库没连上（Astr_Amo_data），这次没写进去"}

    async def api_memory_delete(self):
        """有记忆终端就删终端里的那条；没有就还按老规矩让对方插件自己管。"""
        await self._ensure_ready()
        data = await self._body()
        memory_id = to_int(data.get("id") or 0)
        if memory_id and self._data_mem() is not None:
            ok = await self._data_call("delete_memory", self._data_bot_id(), memory_id)
            if ok:
                return {"code": 0, "msg": "已删除"}
        return {
            "code": 1,
            "msg": "记忆由记忆终端保存，请到「我想永远陪着你-记忆」面板里删除",
        }

    async def api_schedule(self):
        await self._ensure_ready()
        data = await self._body()
        day = str(data.get("date") or self._q("date", "") or today_str())
        if day == today_str():
            items = await self.state.ensure_schedule(self._last_umo)
        else:
            items = self.state._normalize_items(self.state._strip_his_presence(
                self.state._hourly_schedule(self.db.get_schedule(day) or []), day))
        full = []
        try:
            raw = self.db.kv_get("schedule_full_" + day, [])
            for _ in range(2):  # 兼容以前写过两层 JSON 的旧值
                if isinstance(raw, str):
                    raw = json.loads(raw) if raw else []
            parsed = raw if isinstance(raw, list) else []
            if isinstance(parsed, list):
                full = [row for row in parsed if isinstance(row, dict) and row.get("start")]
        except Exception:
            full = []
        if not full:
            # 老日子没有细格：至少把整点格当细格给出去，面板不会空
            full = items
        return {"code": 0, "data": {"day": day, "meta": day_meta(day), "items": items, "tree": self.state.schedule_tree(day), "current": self.state.current_activity(), "context": self.state.schedule_context(day), "full": full}}

    async def api_schedule_detail(self):
        await self._ensure_ready()
        data = await self._body()
        day = str(data.get("date") or "").strip() or today_str()
        start_raw = str(data.get("start") or "").strip()
        matched = re.match(r"^(\d{1,2})(?::(\d{2}))?$", start_raw)
        if not matched:
            return {"code": 1, "msg": "start 需要 HH:MM，例如 10:00"}
        hour = max(0, min(23, int(matched.group(1))))
        start = "%02d:00" % hour
        if day == today_str():
            items = await self.state.ensure_schedule(self._last_umo)
        else:
            items = self.state._normalize_items(self.state._strip_his_presence(
                self.state._hourly_schedule(self.db.get_schedule(day) or []), day))
        item = None
        for entry in items:
            if str(entry.get("start") or "") == start:
                item = entry
                break
        if item is None:
            return {"code": 1, "msg": "没有找到这一小时的日程：" + start}
        force_raw = data.get("force", "")
        force = str(force_raw).lower() in ("1", "true", "yes", "on")
        result = await self.state.expand_hour(day, item, items, force=force)
        payload = {"day": day, "start": item.get("start", start), "end": item.get("end", "")}
        payload.update(result)
        return {"code": 0, "data": payload}

    async def api_wardrobe(self):
        """服装库：GET 列表，POST 也能读（面板桥接只有 GET 时用）。"""
        await self._ensure_ready()
        if self.wardrobe is None:
            return {"code": 1, "msg": "服装库不可用"}
        try:
            await self.wardrobe.refresh()
        except Exception as exc:
            logger.debug("[amo] 衣柜同步失败: %s" % exc)
        data = self.wardrobe.panel_data()
        current = ""
        try:
            current = str((self.state.current_activity() or {}).get("outfit") or "")
        except Exception:
            current = ""
        data["current"] = current
        data["today"] = today_str()
        return {"code": 0, "data": data}

    async def api_wardrobe_save(self):
        """新增或修改一件衣服。"""
        await self._ensure_ready()
        if self.wardrobe is None:
            return {"code": 1, "msg": "服装库不可用"}
        payload = await self._body()
        payload = payload if isinstance(payload, dict) else {}
        item_id = str(payload.get("id") or "").strip()
        name = str(payload.get("name") or "").strip()
        scenes = payload.get("scenes") if isinstance(payload.get("scenes"), list) else []
        gender = str(payload.get("gender") or "通用").strip()
        note = str(payload.get("note") or "").strip()
        try:
            if item_id:
                item = await self.wardrobe.update(item_id, name=name, scenes=scenes,
                                                  gender=gender, note=note)
            else:
                item = await self.wardrobe.add(name, scenes=scenes, gender=gender, note=note)
        except Exception as exc:
            return {"code": 1, "msg": "保存失败：%s" % exc}
        if not item:
            return {"code": 1, "msg": "名字太短或场景没选"}
        return {"code": 0, "msg": "已保存：" + item["name"], "data": item}

    async def api_wardrobe_delete(self):
        await self._ensure_ready()
        if self.wardrobe is None:
            return {"code": 1, "msg": "服装库不可用"}
        payload = await self._body()
        payload = payload if isinstance(payload, dict) else {}
        item_id = str(payload.get("id") or "").strip()
        if not item_id:
            return {"code": 1, "msg": "缺少 id"}
        ok = await self.wardrobe.delete(item_id)
        return {"code": 0 if ok else 1, "msg": "已删除" if ok else "没找到这件"}

    async def api_wardrobe_wear(self):
        """让今天的她换上一件（面板/聊天共用同一份 override）。"""
        await self._ensure_ready()
        if self.outfits is None:
            return {"code": 1, "msg": "穿搭引擎不可用"}
        payload = await self._body()
        payload = payload if isinstance(payload, dict) else {}
        name = str(payload.get("name") or "").strip()
        if not name:
            return {"code": 1, "msg": "缺少衣服名"}
        day = today_str()
        try:
            ok, place = self.outfits.can_change_to(name)
        except Exception:
            ok, place = True, ""
        if not ok:
            return {"code": 1, "msg": "她现在在%s，私密衣物只在家换" % place}
        data = self.outfits.change_outfit(day, name, from_hour=str(payload.get("from") or ""))
        if not data:
            return {"code": 1, "msg": "现在不能换这套（私密衣物只在家，而且这一格不能是出门/去公司）"}
        items = self.state.schedule.get(day) or self.db.get_schedule(day) or []
        items = self.outfits.assign(self.state._hourly_schedule(items), day)
        self.state.schedule[day] = items
        try:
            self.db.kv_set("schedule", self._sanitize_schedule(self.state.schedule))
            self.db.save_schedule(day, items)
        except Exception:
            pass
        label = str(data.get("set") or data.get("name") or name)
        return {"code": 0, "msg": "换好了：" + label + "（整套一起穿）", "data": data}

    async def api_scenic_kb_regen(self):
        await self._ensure_ready()
        kb = await self._ensure_scenic_kb()
        if kb is None:
            return {
                "code": 1,
                "msg": "景区知识库创建失败：请检查 Embedding 供应商，并查看 AstrBot 日志",
            }
        return {"code": 0, "msg": "景区知识库已就绪：" + self._scenic_kb_name()}

    async def api_kb_regen(self):
        await self._ensure_ready()
        try:
            data = await self._body()
        except Exception:
            data = {}
        style = str(data.get("dialect_style") or "").strip()
        if style in DIALECT_REGIONS:
            self.config["dialect_style"] = style
            try:
                if hasattr(self.config, "save_config"):
                    self.config.save_config()
            except Exception:
                pass
        style_now = self._dialect_style().strip()
        logger.debug("[amo] 重建语种: style=%s region=%s rows=%d kb=%s" % (
            style_now, self._dialect_region(), len(self._dialect_rows()), self._dialect_kb_name()
        ))
        kb = await self._ensure_dialect_kb()
        if kb is None:
            return {
                "code": 1,
                "msg": "知识库创建失败：请检查是否配置了 Embedding 供应商，并查看 AstrBot 日志",
            }
        return {"code": 0, "msg": "知识库已就绪：" + self._dialect_kb_name()}

    async def api_draw_status(self):
        await self._ensure_ready()
        engine = getattr(self, "draw", None)
        if engine is None:
            return {"code": 1, "msg": "画图引擎未加载"}
        try:
            return {"code": 0, "msg": engine.diagnostics()}
        except Exception as exc:
            return {"code": 1, "msg": "画图自检失败：%s" % exc}

    async def api_draw_decide(self):
        """调试：给一段用户消息和她的回复，看会不会触发、提示词是什么。"""
        await self._ensure_ready()
        data = await self._body()
        data = data if isinstance(data, dict) else {}
        text = str(data.get("text") or "")
        reply = str(data.get("reply") or "")
        uid = str(data.get("uid") or self._panel_default_uid())
        engine = getattr(self, "draw", None)
        if engine is None:
            return {"code": 1, "msg": "画图引擎未加载"}

        class _FakeEvent:
            def __init__(self, message, sender):
                self.message_str = message
                self.unified_msg_origin = "debug:private:%s" % sender
                self._sender = sender

            def is_private_chat(self):
                return True

            def get_sender_id(self):
                return self._sender

            def is_admin(self):
                return False

        try:
            plan = engine.decide(_FakeEvent(text, uid), reply)
        except Exception as exc:
            return {"code": 1, "msg": "decide 异常：%s" % exc}
        safe = None
        if isinstance(plan, dict):
            safe = {k: v for k, v in plan.items() if k != "cached"}
            safe["cached"] = bool(plan.get("cached"))
        return {"code": 0, "data": {"plan": safe}}

    async def api_draw_test(self):
        """调试：按当前场景真画一张并发到最近会话（会花钱，仅测试用）。"""
        await self._ensure_ready()
        data = await self._body()
        data = data if isinstance(data, dict) else {}
        text = str(data.get("text") or "拍照给我看看")
        reply = str(data.get("reply") or "在呀")
        umo = str(data.get("umo") or self._last_umo or "")
        if not umo:
            try:
                for profile in self.db.proactive_profiles(limit=5) or []:
                    candidate = self._pick_proactive_umo(profile)
                    if candidate:
                        umo = str(candidate)
                        break
            except Exception as exc:
                logger.debug("[amo] 画图测试取会话失败: %s" % exc)
        engine = getattr(self, "draw", None)
        if engine is None:
            return {"code": 1, "msg": "画图引擎未加载"}
        if not umo:
            return {"code": 1, "msg": "没有可发送的会话"}
        plugin = self

        class _FakeEvent:
            def __init__(self):
                self.message_str = text
                self.unified_msg_origin = umo

            def is_private_chat(self):
                return True

            def get_sender_id(self):
                return str(data.get("uid") or self._panel_default_uid())

            def is_admin(self):
                return False

            async def send(self, chain):
                await plugin.context.send_message(umo, chain)

        plan = engine.decide(_FakeEvent(), reply)
        if not plan:
            return {"code": 0, "msg": "没有触发（看日志里的 [amo] 画图跳过）", "data": {"plan": None}}
        engine._schedule(_FakeEvent(), plan["prompt"], plan.get("reason", "test"),
                         plan.get("cached"), plan.get("cache_key", ""), plan.get("selfie", False))
        return {"code": 0, "msg": "已开始画：%s" % plan["prompt"], "data": {"umo": umo}}

    async def api_schedule_regen(self):
        await self._ensure_ready()
        items = await self.state.ensure_schedule(self._last_umo, force=True)
        return {"code": 0, "data": items}

    async def api_weather(self):
        await self._ensure_ready()
        weather = await self.state.refresh_weather(force=True)
        return {"code": 0, "data": weather}

    async def api_photo_self(self):
        await self._ensure_ready()
        data = await self._body()
        star = self._photo_star()
        if star is None or not hasattr(star, "photo_self"):
            return {"code": 1, "msg": "生图插件没加载，暂时拍不了"}
        try:
            return await star.photo_self(data if isinstance(data, dict) else {})
        except Exception as exc:
            logger.warning("[amo] 代发生成照片失败: %s" % exc)
            return {"code": 1, "msg": "生成失败：%s" % str(exc)[:60]}

    async def api_photo_job(self):
        await self._ensure_ready()
        data = await self._body()
        star = self._photo_star()
        if star is None or not hasattr(star, "photo_job"):
            return {"code": 1, "msg": "生图插件没加载，暂时拍不了"}
        try:
            return star.photo_job(str((data or {}).get("id") or ""))
        except Exception as exc:
            logger.debug("[amo] 代发查询照片任务失败: %s" % exc)
            return {"code": 1, "msg": str(exc)[:60]}

    async def api_photo_last(self):
        await self._ensure_ready()
        star = self._photo_star()
        if star is None or not hasattr(star, "photo_last"):
            return {"code": 1, "msg": "生图插件没加载，暂时拍不了"}
        try:
            return star.photo_last()
        except Exception as exc:
            logger.debug("[amo] 代发读取上次照片失败: %s" % exc)
            return {"code": 1, "msg": str(exc)[:60]}

    async def api_photo_clear(self):
        await self._ensure_ready()
        star = self._photo_star()
        if star is None or not hasattr(star, "photo_clear"):
            return {"code": 1, "msg": "生图插件没加载，暂时拍不了"}
        try:
            return star.photo_clear()
        except Exception as exc:
            logger.debug("[amo] 代发清除照片失败: %s" % exc)
            return {"code": 1, "msg": str(exc)[:60]}

    async def api_worldview(self):
        await self._ensure_ready()
        await self.state.ensure_worldview(self._last_umo)
        world = self.state.worldview
        try:
            data = dict(world or {})
        except Exception:
            return {"code": 0, "data": world}
        return {"code": 0, "data": data}

    async def api_worldview_regen(self):
        await self._ensure_ready()
        worldview = await self.state.ensure_worldview(self._last_umo, force=True)
        return {"code": 0, "data": worldview}

    async def api_say(self):
        """面板「代她说一句」。只允许发到已知会话，参数只认 body。"""
        await self._ensure_ready()
        data = await self._body()
        text = str(data.get("text") or "").strip()
        umo = str(data.get("umo") or "").strip() or str(self._last_umo or "")
        if not text:
            return {"code": 1, "msg": "text 不能为空"}
        if not umo:
            return {"code": 1, "msg": "没有可发送的会话"}
        known = set()
        try:
            for profile in self.db.list_profiles(limit=500):
                for key in ("private_umo", "last_group"):
                    value = str(profile.get(key) or "").strip()
                    if value:
                        known.add(value)
        except Exception as exc:
            logger.debug("[amo] 读取已知会话失败: %s" % exc)
        if umo not in known:
            logger.warning("[amo] 拒绝向未知会话发送: %s" % umo)
            return {"code": 1, "msg": "umo 不在已知会话内"}
        ok = await self._send_to_umo(umo, text)
        return {"code": 0 if ok else 1, "msg": "已发送" if ok else "发送失败"}

    def _register_web_apis(self):
        prefixes = uniq([
            getattr(self, "name", None),
            PLUGIN_NAME,
            os.path.basename(self.plugin_dir),
            "astrbot_plugin_Astrbot_Amo_forever",
            "astrbot_plugin_amo_forever",
        ])
        # 清除上一实例/旧版本残留的 Web API 路由。
        # AstrBot 重载插件时不会自动清理 registered_web_apis，旧路由会继续
        # 指向已经 terminate 的旧实例，表现为 "Cannot operate on a closed database"。
        try:
            own_prefixes = tuple(
                "/" + str(prefix).strip("/") + "/"
                for prefix in prefixes
                if str(prefix).strip("/")
            )
            holders = (type(self.context), self.context)
            seen_holders = set()
            for holder in holders:
                if id(holder) in seen_holders:
                    continue
                seen_holders.add(id(holder))
                registry = getattr(holder, "registered_web_apis", None)
                if not isinstance(registry, list):
                    continue
                registry[:] = [
                    item
                    for item in registry
                    if not (
                        isinstance(item, tuple)
                        and item
                        and (
                            str(item[0]).startswith(own_prefixes)
                            or str(item[0]) in ("get_status", "get_profile", "refresh_status")
                        )
                    )
                ]
        except Exception as exc:
            logger.warning("[amo] 清理旧 Web API 路由失败（插件重载后如遇 closed database，请完整重启）: %s" % exc)
        routes = [
            ("/status", self.api_status, ["GET"]),
            ("/records", self.api_records, ["GET", "POST"]),
            ("/get_status", self.api_get_status, ["GET"]),
            ("/events", self.api_events, ["GET", "POST"]),
            ("/profiles", self.api_profiles, ["GET", "POST"]),
            ("/get_profile", self.api_get_profile, ["GET", "POST"]),
            ("/profiles/sync", self.api_profiles_sync, ["GET", "POST"]),
            ("/relations", self.api_relations, ["GET", "POST"]),
            ("/brain", self.api_brain, ["GET", "POST"]),
            ("/relation/save", self.api_relation_save, ["GET", "POST"]),
            ("/relation_save", self.api_relation_save, ["GET", "POST"]),
            ("/relation/delete", self.api_relation_delete, ["GET", "POST"]),
            ("/relation_delete", self.api_relation_delete, ["GET", "POST"]),
            ("/profiles_sync", self.api_profiles_sync, ["GET", "POST"]),
            ("/config", self.api_config, ["GET"]),
            ("/voice/save", self.api_voice_save, ["GET", "POST"]),
            ("/weather/brief", self.api_weather_brief, ["GET", "POST"]),
            ("/city/search", self.api_city_search, ["GET", "POST"]),
            ("/city/set", self.api_city_set, ["GET", "POST"]),
            ("/draw/status", self.api_draw_status, ["GET", "POST"]),
            ("/draw/test", self.api_draw_test, ["GET", "POST"]),
            ("/draw/decide", self.api_draw_decide, ["GET", "POST"]),
            ("/usage", self.api_usage, ["GET"]),
            ("/providers", self.api_providers, ["GET"]),
            ("/providers_list", self.api_providers, ["GET"]),
            ("/balance", self.api_balance, ["GET"]),
            ("/config/save", self.api_config_save, ["GET", "POST"]),
            ("/config_save", self.api_config_save, ["GET", "POST"]),
            ("/profile/save", self.api_profile_save, ["GET", "POST"]),
            ("/profile/links", self.api_profile_links, ["GET", "POST"]),
            ("/profile_save", self.api_profile_save, ["GET", "POST"]),
            ("/profile/delete", self.api_profile_delete, ["GET", "POST"]),
            ("/profile_delete", self.api_profile_delete, ["GET", "POST"]),
            ("/memories", self.api_memories, ["GET", "POST"]),
            ("/chat/history", self.api_chat_history, ["GET", "POST"]),
            ("/chat_history", self.api_chat_history, ["GET", "POST"]),
            ("/memory/add", self.api_memory_add, ["GET", "POST"]),
            ("/memory_add", self.api_memory_add, ["GET", "POST"]),
            ("/memory/delete", self.api_memory_delete, ["GET", "POST"]),
            ("/memory_delete", self.api_memory_delete, ["GET", "POST"]),
            ("/schedule", self.api_schedule, ["GET", "POST"]),
            ("/wardrobe", self.api_wardrobe, ["GET", "POST"]),
            ("/wardrobe/save", self.api_wardrobe_save, ["GET", "POST"]),
            ("/wardrobe/delete", self.api_wardrobe_delete, ["GET", "POST"]),
            ("/wardrobe/wear", self.api_wardrobe_wear, ["GET", "POST"]),
            ("/schedule/detail", self.api_schedule_detail, ["GET", "POST"]),
            ("/schedule_detail", self.api_schedule_detail, ["GET", "POST"]),
            ("/schedule/regen", self.api_schedule_regen, ["GET", "POST"]),
            ("/kb/regen", self.api_kb_regen, ["GET", "POST"]),
            ("/scenic_kb/regen", self.api_scenic_kb_regen, ["GET", "POST"]),
            ("/scenic_kb_regen", self.api_scenic_kb_regen, ["GET", "POST"]),
            ("/kb_regen", self.api_kb_regen, ["GET", "POST"]),
            ("/schedule_regen", self.api_schedule_regen, ["GET", "POST"]),
            ("/weather", self.api_weather, ["GET"]),
            ("/photo/self", self.api_photo_self, ["GET", "POST"]),
            ("/photo/job", self.api_photo_job, ["GET", "POST"]),
            ("/photo/last", self.api_photo_last, ["GET", "POST"]),
            ("/photo/clear", self.api_photo_clear, ["GET", "POST"]),
            ("/worldview", self.api_worldview, ["GET"]),
            ("/worldview/regen", self.api_worldview_regen, ["GET", "POST"]),
            ("/worldview_regen", self.api_worldview_regen, ["GET", "POST"]),
            ("/say", self.api_say, ["GET", "POST"]),
            ("/refresh_status", self.api_refresh_status, ["GET"]),
        ]
        for prefix in prefixes:
            clean = str(prefix).strip("/")
            if not clean:
                continue
            for path, handler, methods in routes:
                self._safe_register("/" + clean + path, handler, methods, path)


