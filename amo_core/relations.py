# -*- coding: utf-8 -*-
"""Amo 终端 · 身份与关系（RelationsMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., RelationsMixin, Star) 混入，self.* 照旧可用。

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



class RelationsMixin:

    async def _self_identity(self, event):
        uid = ""
        try:
            uid = str(event.get_self_id() or "")
        except Exception:
            pass
        role_name = str(self.persona_name or self.bot_name or "陪伴")
        display_name = ""
        for attr in ("get_self_name", "get_bot_name"):
            try:
                value = getattr(event, attr, None)
                if callable(value):
                    value = value()
                if value:
                    display_name = str(value)
                    break
            except Exception:
                continue
        qq_nick = ""
        if uid and getattr(self, "_self_nickname_uid", "") == uid:
            qq_nick = str(getattr(self, "_self_nickname", "") or "")
        if uid and not qq_nick:
            try:
                api = getattr(getattr(event, "bot", None), "api", None)
                action = getattr(api, "call_action", None)
                if callable(action):
                    result = action("get_login_info")
                    if inspect.isawaitable(result):
                        result = await asyncio.wait_for(result, timeout=3)
                    data = result.get("data") if isinstance(result, dict) and isinstance(result.get("data"), dict) else result
                    if isinstance(data, dict):
                        qq_nick = str(data.get("nickname") or "")
                        if data.get("user_id"):
                            uid = str(data.get("user_id"))
                    if not qq_nick and uid:
                        stranger = action("get_stranger_info", user_id=int(uid))
                        if inspect.isawaitable(stranger):
                            stranger = await asyncio.wait_for(stranger, timeout=3)
                        stranger_data = stranger.get("data") if isinstance(stranger, dict) and isinstance(stranger.get("data"), dict) else stranger
                        if isinstance(stranger_data, dict):
                            qq_nick = str(stranger_data.get("nickname") or "")
            except Exception as exc:
                logger.debug("[amo] 获取机器人QQ昵称失败: %s" % exc)
        if not qq_nick:
            qq_nick = display_name or role_name
            logger.debug("[amo] get_login_info 不可用，QQ昵称回退为 %s" % qq_nick)
        if not display_name:
            display_name = qq_nick
        if uid:
            self._self_nickname = qq_nick
            self._self_nickname_uid = uid
            self._self_display = display_name
        if getattr(self, "_self_identity_logged", "") != (uid + "|" + qq_nick + "|" + display_name):
            self._self_identity_logged = uid + "|" + qq_nick + "|" + display_name
            logger.debug(
                "[amo] 自身身份 | 角色名=%s | QQ昵称=%s | 显示名=%s | UID=%s"
                % (role_name, qq_nick, display_name, uid or "未知")
            )
        return role_name, uid, qq_nick, display_name

    async def _ensure_self_identity_memory(self) -> None:
        """把「我长什么样」钉成永久记忆（kind=identity，永不进删除队列）。只写一次。"""
        try:
            if self.db.kv_get("self_face_identity_v1", False):
                return
        except Exception:
            return
        star = self._self_face_plugin()
        getter = getattr(star, "self_face_identity", None) if star is not None else None
        if not callable(getter):
            return
        try:
            clause = str(getter() or "")
        except Exception:
            clause = ""
        if not clause:
            return
        try:
            uid = self._primary_uid()
        except Exception:
            uid = ""
        if not uid:
            return
        text = "【我自己的样子】" + clause.replace("【你的样子·永久事实】", "")
        try:
            ok = await self._write_memory_checked(uid, text, kind="identity", tier=2)
        except Exception as exc:
            logger.warning("[amo] 自我形象永久记忆写入失败: %s" % exc)
            return
        if ok:
            try:
                self.db.kv_set("self_face_identity_v1", True)
            except Exception:
                pass
            logger.debug("[amo] 自我形象永久记忆已写入（kind=identity）")
        else:
            logger.debug("[amo] 自我形象永久记忆没写进去（守门人拦下），下轮再试")

    def _relation_network_text(self, uid):
        """从 Relationship 读取两跳关系摘要；旧 AmoDB 仅作为升级失败时的兼容回退。"""
        uid = str(uid or "")
        store = getattr(self, "relationship_store", None)
        if store is None:
            try:
                edges = [e for e in self.db.list_relations()
                         if str(e.get("relation") or "") != "陌生人"]
                names = {str(p.get("uid")): p.get("alias") or p.get("name") or str(p.get("uid"))
                         for p in self.db.list_profiles(limit=500)}
                names["bot"] = str(getattr(self, "bot_name", "") or "你")
            except Exception:
                return ""
        else:
            try:
                edges = []
                for row in store.list_relationships(include_inactive=False):
                    if row.get("status") == "inactive":
                        continue
                    edges.append({
                        "a_uid": str(row.get("subject_id") or ""),
                        "b_uid": str(row.get("object_id") or ""),
                        "relation": str(row.get("relation_type") or "朋友"),
                        "note": str(row.get("note") or ""),
                    })
                names = {str(p.get("person_id")): str(p.get("display_name") or p.get("person_id"))
                         for p in store.find_people("", 200)}
                names["bot"] = str(getattr(self, "bot_name", "") or "你")
            except Exception as exc:
                logger.debug("[relationship] 读取关系图失败，回退旧库: %s", exc)
                return ""
        if not edges:
            return ""
        picked = []
        if _rank_edges is not None:
            try:
                picked = _rank_edges(edges, uid, 12, 3 if len(edges) <= 40 else 2)
            except Exception:
                picked = []
        if not picked:
            direct, neighbors, second = [], set(), []
            for edge in edges:
                a, b = str(edge.get("a_uid")), str(edge.get("b_uid"))
                if uid in (a, b):
                    direct.append(edge)
                    neighbors.add(b if a == uid else a)
            for edge in edges:
                if edge not in direct and (str(edge.get("a_uid")) in neighbors or str(edge.get("b_uid")) in neighbors):
                    second.append(edge)
            picked = (direct + second)[:12]
        def _label(edge):
            relation = str(edge.get("relation") or "朋友")
            note = str(edge.get("note") or "")
            if "推断" in note or "推测" in note:
                return relation + "（推测关系，别当成确定事实）"
            return relation
        direct, second = [], []
        for edge in picked[:12]:
            a, b = str(edge.get("a_uid")), str(edge.get("b_uid"))
            (direct if uid in (a, b) else second).append(edge)
        if not second:
            known = {str(e.get("a_uid")) for e in direct} | {str(e.get("b_uid")) for e in direct}
            second = [e for e in edges if str(e.get("a_uid")) in known or str(e.get("b_uid")) in known][:4]
        lines = []
        for edge in direct + second[:6]:
            a, b = str(edge.get("a_uid")), str(edge.get("b_uid"))
            na, nb = names.get(a, a), names.get(b, b)
            lines.append(("%s和%s是%s" if uid in (a, b) else "（隔一层的）%s和%s是%s")
                         % (na, nb, _label(edge)))
        if lines:
            lines.append("这些是背景，心里有数就行，不用主动拿出来说。")
        return "\n".join(lines)

    async def _learn_relations(self, event, text, uid):
        """只从明确陈述学习关系；写入 Relationship，保留管理员手工关系。"""
        if parse_relations is None or not text or not uid:
            return
        store = getattr(self, "relationship_store", None)
        try:
            pairs = parse_relations(text)
        except Exception:
            return
        if not pairs:
            return
        name_map, profile_map = {}, {}
        try:
            for item in self.db.list_profiles(limit=5000):
                pid = str(item.get("uid") or "")
                if not pid:
                    continue
                profile_map[pid] = item
                for key in ("name", "alias"):
                    raw = str(item.get(key) or "").strip()
                    for name in re.split(r"[;；,，、/|]", raw):
                        name = name.strip()
                        if len(name) >= 2:
                            name_map.setdefault(name, set()).add(pid)
        except Exception:
            return
        if store is not None:
            try:
                existing_rows = store.list_relationships(include_inactive=True)
                existing = {tuple(sorted((str(x.get("subject_id")), str(x.get("object_id"))))): x
                            for x in existing_rows}
            except Exception:
                existing = {}
        else:
            try:
                existing = {tuple(sorted((str(x.get("a_uid")), str(x.get("b_uid"))))): x
                            for x in self.db.list_relations()}
            except Exception:
                existing = {}
        for who, relation, evidence in pairs:
            targets = [pid for pid in name_map.get(who, set()) if pid and pid != str(uid)]
            if len(targets) != 1:
                continue
            target = targets[0]
            pair = tuple(sorted((str(uid), target)))
            old = existing.get(pair)
            old_note = str((old or {}).get("note") or "")
            if old_note and not old_note.startswith("对话："):
                continue
            note = "对话：" + truncate(evidence, 24)
            try:
                if store is not None:
                    for pid in (str(uid), target):
                        if not store.get_person(pid):
                            profile = profile_map.get(pid) or {}
                            display = str(profile.get("alias") or profile.get("name") or pid)
                            aliases = [profile.get("name"), profile.get("alias")]
                            store.upsert_person(display, person_id=pid, aliases=aliases,
                                                attributes={"legacy_uid": pid})
                    store.set_relationship(str(uid), target, relation, source="conversation",
                                           note=note, confidence=0.8)
                elif not self.db.upsert_relation(uid, target, relation, note):
                    continue
                logger.debug("[relationship] 自动记录关系: %s --%s--> %s" % (uid, relation, target))
                await self._push_relation_to_data(uid, target, relation, note)
            except Exception as exc:
                logger.debug("[relationship] 自动关系写入失败: %s" % exc)

    async def _sync_relations_from_data(self):
        """把记忆终端里的关系网拉回本地（面板改过的也能生效，不用重启）。"""
        try:
            rows = await self._data_call("list_relations", self._data_bot_id())
        except Exception:
            return 0
        if rows is None:
            # 终端不可用时不要动本地，避免把关系网清空
            return 0
        remote = set()
        count = 0
        for edge in rows:
            a_uid = str(edge.get("a_uid") or "")
            b_uid = str(edge.get("b_uid") or "")
            if not a_uid or not b_uid:
                continue
            if a_uid in INTERNAL_RELATION_NODES or b_uid in INTERNAL_RELATION_NODES:
                # 老版本可能推过 bot 边：不参与比较，也不动本地
                continue
            remote.add(tuple(sorted([a_uid, b_uid])))
            try:
                self.db.upsert_relation(a_uid, b_uid, edge.get("relation") or "朋友", edge.get("note") or "")
                store = getattr(self, "relationship_store", None)
                if store is not None:
                    for _pid in (a_uid, b_uid):
                        if not store.get_person(_pid):
                            store.upsert_person(_pid, person_id=_pid,
                                                attributes={"legacy_uid": _pid})
                    store.set_relationship(a_uid, b_uid, edge.get("relation") or "朋友",
                                           source="memory_sync", note=edge.get("note") or "")
                count += 1
            except Exception:
                continue
        # 面板上删掉的关系，本地也同步删掉（终端为准）；
        # 终端返回空、或远端的边比本地还少时都不删——那多半是换库/重装/恢复残缺备份，
        # 照删一次就能把本地关系网清空（之后还得靠聊天慢慢沉淀）。
        try:
            local_rows = self.db.list_relations()
        except Exception:
            local_rows = []
        # bot/self 边推不到远端，比较前先排掉：不然远端永远"比本地少"，
        # 这条 warning 会每轮都响，而且下面"终端删了本地也删"永远不会执行。
        local_rows = [
            item for item in local_rows
            if str(item.get("a_uid") or "") not in INTERNAL_RELATION_NODES
            and str(item.get("b_uid") or "") not in INTERNAL_RELATION_NODES
        ]
        if not remote or len(remote) < len(local_rows):
            if remote:
                logger.warning(
                    "[amo] 关系网不同步：远端 %d 条 < 本地 %d 条，先不删本地"
                    % (len(remote), len(local_rows))
                )
            return count
        try:
            for item in local_rows:
                pair = tuple(sorted([str(item.get("a_uid") or ""), str(item.get("b_uid") or "")]))
                if pair not in remote:
                    self.db.delete_relation(pair[0], pair[1])
        except Exception:
            pass
        return count

    def _detect_impersonation(self, event):
        """群里非恋人 UID 使用/冒充恋人的名字或爱称时，5 分钟内累计降级。"""
        group_id = str(event.get_group_id() or "")
        if not group_id:
            return False
        uid = self._canonical_uid(event)
        lovers = self._lover_aliases()
        if not lovers or uid in set(lovers.values()) or self._is_registered_lover(uid):
            return False
        sender_name = str(event.get_sender_name() or "").strip()
        text = str(event.message_str or "").strip()
        hit = ""
        if sender_name in lovers:
            hit = sender_name
        elif text in lovers:
            hit = text
        else:
            for alias in lovers:
                if re.search(r"(?:我才是|我是|叫我|叫我做|以后叫我|我才是那个)\s*" + re.escape(alias), text):
                    hit = alias
                    break
        if not hit:
            return False
        setattr(event, "amo_impersonation", True)
        key = "impersonate_%s_%s" % (group_id, uid)
        now = now_ts()
        stamps = self.db.kv_get(key, [])
        if not isinstance(stamps, list):
            stamps = []
        stamps = [to_float(item, 0) for item in stamps if now - to_float(item, 0) <= 300]
        stamps.append(now)
        self.db.kv_set(key, stamps)
        count = len(stamps)
        profile = self.db.get_profile(uid) or {}
        current = str(profile.get("relation") or "普通")
        relation = current
        if count >= 3 and current != "仇恨":
            relation = "仇恨"
        elif count == 1 and current != "仇恨":
            relation = "抵触"
        if relation != current:
            self.db.update_profile(uid, relation=relation)
            logger.debug(
                "[amo] 识别到冒充恋人称呼: %s -> %s（%s，5分钟内第%d次）"
                % (uid, relation, hit, count)
            )
        return True

    def _uid_alias_mapping(self):
        """读映射表（配置优先，其次数据目录 uid_map.json）；按内容+mtime 缓存。"""
        cache_key = None
        try:
            text = str(self.cfg_str("uid_alias_map", "") or "").strip().lstrip("﻿")
            map_path = os.path.join(os.path.dirname(str(self.db.path)), "uid_map.json")
            stamp = os.path.getmtime(map_path) if os.path.exists(map_path) else 0
            cache_key = (text, stamp)
        except Exception:
            cache_key = None
        if getattr(self, "_uid_alias_cache_key", None) != cache_key:
            raw = {}
            try:
                text = str(self.cfg_str("uid_alias_map", "") or "").strip().lstrip("﻿")
                parsed = json.loads(text) if text else {}
                if isinstance(parsed, dict):
                    raw.update(parsed)
            except Exception as exc:
                logger.warning("[amo] uid_alias_map 配置解析失败: %s" % exc)
            try:
                map_path = os.path.join(os.path.dirname(str(self.db.path)), "uid_map.json")
                if os.path.exists(map_path):
                    # utf-8-sig：Windows 记事本另存的 JSON 常带 BOM，用 utf-8 会直接解析失败
                    with open(map_path, "r", encoding="utf-8-sig") as fh:
                        parsed = json.load(fh)
                    if isinstance(parsed, dict):
                        for key, value in parsed.items():
                            raw.setdefault(key, value)
            except Exception as exc:
                logger.warning("[amo] uid_map 读取失败: %s" % exc)
            raw = {str(k): str(v) for k, v in raw.items() if k and v}
            # 解析链式映射（A→B、B→C 归到 A→C），并丢掉自映射
            resolved = {}
            for key in raw:
                current = key
                seen = {key}
                while current in raw:
                    nxt = raw[current]
                    if nxt in seen:
                        break
                    seen.add(nxt)
                    current = nxt
                if current != key:
                    resolved[key] = current
            self._uid_alias_map = resolved
            self._uid_alias_cache_key = cache_key
        return getattr(self, "_uid_alias_map", {}) or {}

    async def _resolve_persona(self, umo=""):
        """解析当前会话的人格对象（300 秒缓存）；读不到返回 None。"""
        key = str(umo or "default")
        cache = getattr(self, "_persona_obj_cache", None)
        if cache is None:
            cache = {}
            self._persona_obj_cache = cache
        hit = cache.get(key)
        if hit and now_ts() - hit[0] < 300:
            return hit[1]
        manager = getattr(self.context, "persona_manager", None)
        persona = None
        if manager is not None:
            try:
                conversation_persona_id = None
                cm = getattr(self.context, "conversation_manager", None)
                if cm is not None:
                    cid = await cm.get_curr_conversation_id(key)
                    if cid:
                        conv = await cm.get_conversation(key, cid)
                        conversation_persona_id = getattr(conv, "persona_id", None)
                platform_name = key.split(":", 1)[0] if ":" in key else ""
                _, persona, _, _ = await manager.resolve_selected_persona(
                    umo=key,
                    conversation_persona_id=conversation_persona_id,
                    platform_name=platform_name,
                    provider_settings={},
                )
            except Exception as exc:
                logger.debug("[amo] 解析当前人格失败: %s" % exc)
            if persona is None:
                try:
                    persona = await manager.get_default_persona_v3(key or None)
                except Exception as exc:
                    logger.debug("[amo] 读取默认人格失败: %s" % exc)
        cache[key] = (now_ts(), persona)
        return persona

    async def _sync_persona_name(self, event_or_umo):
        umo = getattr(event_or_umo, "unified_msg_origin", event_or_umo)
        try:
            name, aliases = await self._persona_names_for(umo)
        except Exception as exc:
            logger.debug("[amo] 同步人格名失败: %s" % exc)
            return
        if not name:
            return
        changed = name != self.persona_name
        self.persona_name = name
        self.bot_name = name
        if aliases:
            # 别名以人格里写的那一套为准（2026-11-20 用户口径），不是写死一个短名
            self.bot_aliases = aliases
        try:
            # 记住名字和别名：下次重启、人格还没解析出来时先用这个，别让她几秒钟里叫不出名字
            if str(self.db.kv_get("bot_name_last", "") or "") != name:
                self.db.kv_set("bot_name_last", name)
            if aliases and self.db.kv_get("bot_aliases_last", []) != aliases:
                self.db.kv_set("bot_aliases_last", aliases)
        except Exception:
            pass
        # 世界观挂在 HumanState 上，不是插件实例；这里以前写成了 self.worldview，
        # 一旦人格名变化就会 AttributeError，整条消息处理直接中断。
        world = getattr(getattr(self, "state", None), "worldview", None)
        if changed and isinstance(world, dict) and world.get("name") != name:
            world["name"] = name
            try:
                self.db.kv_set("worldview", world)
            except Exception:
                pass

    def _purge_profile_kv(self, uid):
        """删掉这个 uid 专属的 kv（渠道/节流/主动消息/纪念日…），返回删除条数。"""
        prefixes = (
            "channels:", "last_channel:", "lover_uid_", "auto_learn_",
            "angel_profile_sync_", "companion_profile_sync_", "memcomp_profile_sync_",
            "proactive_ignored_", "proactive_depressed_until_",
            "proactive_followup_last_", "proactive_forced_hour_", "proactive_pending_",
            "ext_mem_count_", "ext_mem_count_at_",
        )
        try:
            rows = self.db.conn.execute("SELECT key FROM kv").fetchall()
        except Exception:
            return 0
        keys = []
        for row in rows:
            try:
                key = str(row["key"] if hasattr(row, "keys") else row[0])
            except Exception:
                continue
            if any(key == prefix + uid for prefix in prefixes):
                keys.append(key)
            elif key.startswith("ritual_") and ("_" + uid + "_") in key:
                keys.append(key)
        if not keys:
            return 0
        try:
            for key in keys:
                self.db.conn.execute("DELETE FROM kv WHERE key=?", (key,))
            self.db.conn.commit()
        except Exception as exc:
            logger.debug("[amo] 清理 kv 失败: %s" % exc)
            return 0
        return len(keys)

    async def _push_profile_to_data(self, uid, profile=None, platform=""):
        """把本地画像推给数据插件（名字/称呼/关系/备注），顺带记下平台身份。

        返回“是否真的写进去了”：数据插件没装、旧版没有 platform 参数、或者内部报错，
        都会返回 False，调用方好统计失败条数，不再假装成功。
        """
        if not uid:
            return False
        profile = profile or self.db.get_profile(uid) or {}
        name = str(profile.get("name") or "")
        # 本地画像自己记着这个人是哪个平台的，补推时别把飞书用户错标成 QQ
        platform = str(platform or profile.get("platform") or "").strip().lower()
        fields = {
            "name": name,
            "alias": str(profile.get("alias") or ""),
            "relation": str(profile.get("relation") or ""),
            "remark": ("" if _looks_auto_note(profile.get("notes"))
                       else str(profile.get("notes") or "")),
        }
        mem = self._data_mem()
        save = getattr(mem, "save_profile", None) if mem is not None else None
        result = None
        if callable(save):
            # 直接调一次，异常不再被 _data_call 吞掉，好定位到底哪一步失败
            try:
                result = await save(self._data_bot_id(), str(uid), platform=platform, **fields)
            except Exception as exc:
                self._log_push_failure(uid, exc)
                result = None
            except Exception as exc:
                self._log_push_failure(uid, exc)
                result = None
        if isinstance(result, dict) and result.get("uid"):
            return True
        return False


__all__ = [
    "RelationsMixin",
]
