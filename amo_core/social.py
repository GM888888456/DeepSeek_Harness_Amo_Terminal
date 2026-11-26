# -*- coding: utf-8 -*-
"""Amo 终端 · 人物与群聊（SocialMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., SocialMixin, Star) 混入，self.* 照旧可用。

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

def merge_uid_alias_data(conn, alias_map):
    """把别名 uid 的档案/记忆/消息/关系/称呼并进主 uid（一次性、幂等）。

    返回统计 dict，调用方负责记 kv 标记，避免每次启动重复跑。
    """
    report = {"profiles": 0, "memories": 0, "messages": 0, "proactive_log": 0,
              "relations": 0, "kv": 0}
    if not isinstance(alias_map, dict) or not alias_map:
        return report
    cur = conn.cursor()

    def table_columns(name):
        try:
            return [row[1] for row in cur.execute("PRAGMA table_info(%s)" % name)]
        except Exception:
            return []

    profile_cols = table_columns("profiles")
    if not profile_cols:
        return report

    def to_num(value, default=0.0):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return default

    for alias_uid, canon_uid in list(alias_map.items()):
        alias_uid = str(alias_uid or "")
        canon_uid = str(canon_uid or "")
        if not alias_uid or not canon_uid or alias_uid == canon_uid:
            continue
        cur.execute("SELECT * FROM profiles WHERE uid=?", (alias_uid,))
        alias_raw = cur.fetchone()
        cur.execute("SELECT * FROM profiles WHERE uid=?", (canon_uid,))
        canon_raw = cur.fetchone()

        def as_dict(row):
            if row is None:
                return None
            if hasattr(row, "keys"):
                return dict(row)
            return {col[0]: value for col, value in zip(cur.description, row)}

        alias_row = as_dict(alias_raw)
        canon_row = as_dict(canon_raw)
        if alias_row is not None and canon_row is None:
            # 只有别名档案：直接改主键，历史原样保留
            cur.execute("UPDATE profiles SET uid=? WHERE uid=?", (canon_uid, alias_uid))
            report["profiles"] += 1
        elif alias_row is not None and canon_row is not None:
            a = alias_row
            b = canon_row
            merged = dict(b)
            merged["uid"] = canon_uid
            for key in ("name", "birthday", "alias", "notes", "platform"):
                if key not in profile_cols:
                    continue
                if key in ("alias", "notes"):
                    parts = []
                    for value in (b.get(key), a.get(key)):
                        text = str(value or "").strip()
                        if text and text not in parts:
                            parts.append(text)
                    merged[key] = " | ".join(parts)
                else:
                    merged[key] = b.get(key) or a.get(key) or ""
            if "relation" in profile_cols:
                canon_rel = str(b.get("relation") or "普通")
                alias_rel = str(a.get("relation") or "普通")
                merged["relation"] = canon_rel if canon_rel != "普通" else alias_rel
            for key in ("affection", "msg_count", "proactive_count", "is_admin"):
                if key in profile_cols:
                    merged[key] = max(int(to_num(b.get(key))), int(to_num(a.get(key))))
            for key in ("last_seen", "last_proactive", "relation_at"):
                if key in profile_cols:
                    merged[key] = max(to_num(b.get(key)), to_num(a.get(key)))
            if "first_seen" in profile_cols:
                values = [v for v in (to_num(b.get("first_seen")), to_num(a.get("first_seen"))) if v > 0]
                merged["first_seen"] = min(values) if values else None
            if "private_umo" in profile_cols:
                merged["private_umo"] = b.get("private_umo") or a.get("private_umo") or ""
            if "last_group" in profile_cols:
                merged["last_group"] = b.get("last_group") or a.get("last_group") or ""
            if "proactive_day" in profile_cols:
                merged["proactive_day"] = b.get("proactive_day") or a.get("proactive_day") or ""
            cols = [c for c in profile_cols if c in merged]
            cur.execute("DELETE FROM profiles WHERE uid=?", (alias_uid,))
            cur.execute(
                "INSERT OR REPLACE INTO profiles(%s) VALUES(%s)"
                % (",".join(cols), ",".join("?" * len(cols))),
                [merged.get(c) for c in cols],
            )
            report["profiles"] += 1

        # 消息：改归属 + 只对"别名带来的"那几条去重
        try:
            alias_msgs = [tuple(r) for r in cur.execute(
                "SELECT umo, role, content, created_at FROM messages WHERE uid=?", (alias_uid,))]
            cur.execute("UPDATE messages SET uid=? WHERE uid=?", (canon_uid, alias_uid))
            report["messages"] += cur.rowcount or 0
            for umo, role, content, created in alias_msgs:
                cur.execute(
                    "DELETE FROM messages WHERE umo=? AND uid=? AND role=? AND content=? AND created_at=? "
                    "AND rowid NOT IN (SELECT MIN(rowid) FROM messages WHERE umo=? AND uid=? AND role=? AND content=? AND created_at=?)",
                    (umo, canon_uid, role, content, created, umo, canon_uid, role, content, created),
                )
        except Exception:
            pass

        # 主动记录
        try:
            alias_pro = [tuple(r) for r in cur.execute(
                "SELECT kind, content, created FROM proactive_log WHERE uid=?", (alias_uid,))]
            cur.execute("UPDATE proactive_log SET uid=? WHERE uid=?", (canon_uid, alias_uid))
            report["proactive_log"] += cur.rowcount or 0
            for kind, content, created in alias_pro:
                cur.execute(
                    "DELETE FROM proactive_log WHERE uid=? AND kind=? AND content=? AND created=? "
                    "AND rowid NOT IN (SELECT MIN(rowid) FROM proactive_log WHERE uid=? AND kind=? AND content=? AND created=?)",
                    (canon_uid, kind, content, created, canon_uid, kind, content, created),
                )
        except Exception:
            pass

        # 关系网
        try:
            cur.execute("UPDATE OR IGNORE relation_network SET a_uid=? WHERE a_uid=?", (canon_uid, alias_uid))
            cur.execute("UPDATE OR IGNORE relation_network SET b_uid=? WHERE b_uid=?", (canon_uid, alias_uid))
            # OR IGNORE 遇到已存在的同一对关系会跳过，残留的别名行要显式删掉
            cur.execute("DELETE FROM relation_network WHERE a_uid=? OR b_uid=?", (alias_uid, alias_uid))
            cur.execute("DELETE FROM relation_network WHERE a_uid=b_uid")
            cur.execute(
                "DELETE FROM relation_network WHERE rowid NOT IN "
                "(SELECT MIN(rowid) FROM relation_network GROUP BY a_uid, b_uid)"
            )
            report["relations"] += 1
        except Exception:
            pass

        # kv：通道记录要合并成一份，其余带别名的键改名
        try:
            old_key = "channels:%s" % alias_uid
            new_key = "channels:%s" % canon_uid
            old_ch = cur.execute("SELECT value FROM kv WHERE key=?", (old_key,)).fetchone()
            new_ch = cur.execute("SELECT value FROM kv WHERE key=?", (new_key,)).fetchone()

            def load(raw):
                try:
                    return json.loads(raw[0] or "{}") if raw else {}
                except Exception:
                    return {}

            merged_ch = load(new_ch) if isinstance(load(new_ch), dict) else {}
            alias_ch = load(old_ch) if isinstance(load(old_ch), dict) else {}
            for platform, value in alias_ch.items():
                if not isinstance(value, dict):
                    continue
                current = merged_ch.get(platform)
                if not isinstance(current, dict) or to_num(value.get("ts")) > to_num(current.get("ts")):
                    merged_ch[platform] = value
            if merged_ch:
                cur.execute("UPDATE OR IGNORE kv SET key=? WHERE key=?", (new_key, old_key))
                cur.execute("DELETE FROM kv WHERE key=?", (old_key,))
                cur.execute("INSERT OR REPLACE INTO kv(key, value, updated) VALUES(?,?,?)",
                            (new_key, json.dumps(merged_ch, ensure_ascii=False), time.time()))
                report["kv"] += 1
            else:
                cur.execute("DELETE FROM kv WHERE key=?", (old_key,))
        except Exception:
            pass
        try:
            # 用 Python 侧的包含判断，避免 LIKE 里 '_' 被当成通配符误伤别的键
            for row in list(cur.execute("SELECT key FROM kv")):
                key = str(row[0] or "")
                if alias_uid not in key:
                    continue
                new = key.replace(alias_uid, canon_uid)
                if new == key:
                    continue
                cur.execute("UPDATE OR IGNORE kv SET key=? WHERE key=?", (new, key))
                cur.execute("DELETE FROM kv WHERE key=?", (key,))
                report["kv"] += 1
        except Exception:
            pass

    try:
        conn.commit()
    except Exception:
        pass
    return report


class SocialMixin:

    def _canonical_uid(self, event):
        """把平台账号换算成同一个人的主 uid；关掉开关就返回原 uid。"""
        try:
            uid = str(event.get_sender_id())
        except Exception:
            return ""
        if not self.cfg_bool("uid_merge_enabled", True):
            return uid
        return self._uid_alias_mapping().get(uid, uid)

    def _merge_alias_profiles(self):
        """一次性把旧版本按平台 ID 建好的档案并进主 uid（映射变了会再跑一次）。"""
        if not self.cfg_bool("uid_merge_enabled", True):
            return
        mapping = self._uid_alias_mapping()
        if not mapping:
            return
        signature = json.dumps(mapping, sort_keys=True, ensure_ascii=False)
        try:
            if self.db.kv_get("uid_alias_merged_signature", "") == signature:
                return
        except Exception:
            pass
        try:
            report = merge_uid_alias_data(self.db.conn, mapping)
            self.db.kv_set("uid_alias_merged_signature", signature)
            logger.debug("[amo] 跨平台账号合并完成: %s" % report)
        except Exception as exc:
            logger.warning("[amo] 跨平台账号合并失败: %s" % exc)

    def _register_lover(self, uid):
        uid = str(uid or "").strip()
        if uid:
            self.db.kv_set("lover_uid_" + uid, True)

    def _is_registered_lover(self, uid):
        uid = str(uid or "").strip()
        if not uid:
            return False
        if self.db.kv_get("lover_uid_" + uid, False):
            return True
        profile = self.db.get_profile(uid) or {}
        if str(profile.get("relation") or "") == "相恋":
            self._register_lover(uid)
            return True
        return False

    def _restore_lover_relation(self, uid):
        uid = str(uid or "").strip()
        if not self._is_registered_lover(uid):
            return
        profile = self.db.get_profile(uid) or {}
        if str(profile.get("relation") or "") in ("抵触", "仇恨"):
            self.db.update_profile(uid, relation="相恋")
            logger.debug("[amo] 恋人 UID 恢复为相恋: %s" % uid)

    def _lover_aliases(self):
        aliases = {}
        try:
            profiles = self.db.list_profiles("", 500)
        except Exception:
            profiles = []
        for profile in profiles:
            uid = str(profile.get("uid") or "")
            if str(profile.get("relation") or "") == "相恋":
                self._register_lover(uid)
            elif not self._is_registered_lover(uid):
                continue
            values = [profile.get("name") or ""]
            values.extend(re.split(r"[；;、,，/\s]+", str(profile.get("alias") or "")))
            for value in values:
                name = str(value or "").strip()
                if len(name) >= 1:
                    aliases[name] = uid
        return aliases

    def _is_talking_to_me(self, event):
        """这句是不是冲她来的：私聊、被 @ / 叫名字、或心流判定对象是 bot。"""
        try:
            if event.is_private_chat():
                return True
        except Exception:
            return True
        try:
            if getattr(event, "is_at_or_wake_command", False):
                return True
        except Exception:
            pass
        return False

    def _recent(self, umo, limit=10):
        """近聊上下文钩子：能力层缓冲优先，没有再读本地缓存表。"""
        size = max(1, int(limit or 10))
        rows = []
        hub = self._memory_hub()
        if hub is not None:
            try:
                rows = hub.buffer.recent(umo, size)
            except Exception:
                rows = []
        if len(rows) >= size:
            return rows[-size:]
        try:
            local = self.db.recent_messages(umo, size)
        except Exception:
            local = []
        if not rows:
            return local
        # 缓冲只有一小段时，用本地补前面
        known = {(row.get("role"), row.get("content")) for row in rows}
        merged = [row for row in local if (row.get("role"), row.get("content")) not in known]
        merged.extend(rows)
        return merged[-size:]

    def _ctx_remember(self, umo, uid, name, role, content):
        """把一句话放进内存缓冲；不落库也能有上下文。

        只留 ChatBuffer 一个真相源：以前这里还并写一份 _ctx_buffer，
        _recent / _recent_by_uid / _hydrate_recent 三处各读一份，谁先谁后都能吵起来。
        """
        umo = str(umo or "")
        text = str(content or "").strip()
        if not umo or not text:
            return
        hub = self._memory_hub()
        if hub is None:
            return
        try:
            hub.buffer.add(umo, uid, name, role, text)
        except Exception:
            pass
        try:
            if str(role) != "bot":
                hub.next_turn()
        except Exception:
            pass

    def _remember_turn_activity(self, umo, activity):
        """记下这一轮注入给模型的活动，出图时复用同一份（说 A 就画 A）。"""
        key = str(umo or "")
        if not key or not isinstance(activity, dict) or not activity:
            return
        try:
            if not isinstance(getattr(self, "_turn_activity", None), dict):
                self._turn_activity = {}
            self._turn_activity[key] = (dict(activity), now_ts())
            if len(self._turn_activity) > 32:
                keep = sorted(self._turn_activity, key=lambda k: self._turn_activity[k][1])[-16:]
                self._turn_activity = {k: self._turn_activity[k] for k in keep}
        except Exception as exc:
            logger.debug("[amo] 记录活动快照失败: %s" % exc)

    def _activity_snapshot(self, umo="", max_age=None):
        """这一轮该用的「她在哪」：优先用注入过的那份，过期才重新读。"""
        limit = self.TURN_SNAPSHOT_TTL if max_age is None else max_age
        key = str(umo or "")
        try:
            entry = (getattr(self, "_turn_activity", None) or {}).get(key)
            if entry and (now_ts() - float(entry[1] or 0)) <= limit:
                return dict(entry[0])
        except Exception:
            pass
        try:
            return dict(self.state.current_activity() or {})
        except Exception:
            return {}

    def _group_roster_text(self, umo, current_uid="", limit=8):
        roster = self._group_roster(umo, current_uid, limit)
        if not roster:
            return ""
        lines = []
        for item in roster:
            tag = "（现在这句就是ta说的）" if item["current"] else ""
            if item["msg_count"] >= 200:
                familiar = "很熟"
            elif item["msg_count"] >= 30:
                familiar = "熟识"
            elif item["msg_count"] >= 1:
                familiar = "刚认识"
            else:
                familiar = "陌生"
            lines.append(
                "· %s（UID %s）：和你关系「%s」，%s%s"
                % (item["name"], item["uid"], item["relation"], familiar, tag)
            )
        return "\n".join(lines)

    @staticmethod
    def _rel_when(ts):
        """关系/互动时间戳 → 「今天 20:06」「昨天 14:02」「11-20 15:32」。"""
        try:
            stamp = float(ts or 0)
        except Exception:
            return ""
        if stamp <= 0:
            return ""
        try:
            moment = datetime.fromtimestamp(stamp)
            today = datetime.fromtimestamp(now_ts()).date()
        except Exception:
            return ""
        delta = (today - moment.date()).days
        if delta == 0:
            return "今天 %02d:%02d" % (moment.hour, moment.minute)
        if delta == 1:
            return "昨天 %02d:%02d" % (moment.hour, moment.minute)
        return "%02d-%02d %02d:%02d" % (moment.month, moment.day, moment.hour, moment.minute)

    def _display_name(self, uid, fallback=""):
        uid = str(uid or "").strip()
        try:
            profile = self.db.get_profile(uid) or {}
        except Exception:
            profile = {}
        return (str(profile.get("name") or "").strip()
                or str(profile.get("alias") or "").strip()
                or str(fallback or "").strip()
                or uid)

    def _mentioned_person_lines(self, event, limit=2):
        """这句话里点到的人：先认出是谁，再给两条关系（都带时间）。

        RELATION_WIRE 2026-11-23 20:08：真的懈问「我和小澜什么关系？」，她答
        「哪个小澜，我怎么晓得」——其实 profiles 里小澜是「熟识」、聊过 73 条，
        relation_network 里还记着「真的懈↔小澜：熟人」。认得人却答不上来，
        是因为「说话人↔这个人」这条边从来没被查出来喂给她。
        """
        try:
            text = str(getattr(event, "message_str", "") or "")
        except Exception:
            return []
        if len(text) < 2:
            return []
        try:
            rows = self.db.list_profiles("", 500) or []
        except Exception:
            return []
        try:
            speaker = str(event.get_sender_id() or "").strip()
        except Exception:
            speaker = ""
        hits = {}
        for row in rows:
            try:
                name = str(row.get("name") or "").strip()
                alias = str(row.get("alias") or "").strip()
                uid = str(row.get("uid") or "").strip()
            except Exception:
                continue
            if len(name) < 2 or not uid or uid == speaker:
                continue
            matched = ""
            if name in text:
                matched = name
            elif len(alias) >= 2 and alias in text:
                matched = alias
            if matched:
                hits[matched] = (len(matched), dict(row))
        if not hits:
            return []
        picked = [item[1] for item in sorted(
            hits.values(), key=lambda item: -item[0])[:max(1, int(limit))]]
        speaker_name = self._display_name(speaker, "他") if speaker else "他"
        lines = []
        for row in picked:
            name = str(row.get("name") or row.get("uid") or "").strip()
            uid = str(row.get("uid") or "").strip()
            relation = str(row.get("relation") or "").strip() or "普通"
            try:
                msg_count = int(row.get("msg_count") or 0)
            except Exception:
                msg_count = 0
            line = "· %s（UID %s）：你俩「%s」" % (name, uid, relation)
            if msg_count:
                line += "，聊过 %d 条" % msg_count
            when = self._rel_when(row.get("last_seen"))
            if when:
                line += "，最后一次 %s" % when
            lines.append(line)
            edge = {}
            if speaker:
                try:
                    for item in (self.db.relations_for(speaker) or []):
                        a = str(item.get("a_uid") or "")
                        b = str(item.get("b_uid") or "")
                        if uid in (a, b) and speaker in (a, b):
                            edge = item
                            break
                except Exception:
                    edge = {}
            if edge:
                sub = "  └ %s和她：「%s」" % (speaker_name, str(edge.get("relation") or "?"))
                ewhen = self._rel_when(edge.get("updated_at"))
                if ewhen:
                    sub += "，%s 记的" % ewhen
                note = str(edge.get("note") or "").strip()
                if note:
                    sub += "（%s）" % note[:40]
                lines.append(sub)
            else:
                lines.append("  └ %s和她：关系网里没有记录，别替他编" % speaker_name)
        return lines

    def _group_reply_guide(self, relation, name):
        """按关系给一句“该怎么回”的指引。"""
        relation = str(relation or "普通")
        if relation == "相恋":
            return "对" + name + "可以亲近、撒娇、用昵称，但别在群里太露骨。"
        if relation == "熟识":
            return "对" + name + "像老朋友一样随便聊，可以开玩笑，但不用恋人语气。"
        if relation == "抵触":
            return "对" + name + "有点距离感，句子短，不主动热络。"
        if relation == "仇恨":
            return "对" + name + "很冷淡，不接他的茬，也不解释。"
        return "对" + name + "客气一点、像普通群友，不要叫老公/宝贝，也别装得很熟。"

    def _group_speaker_count(self, umo, limit=20, window=600):
        """最近一段时间内群聊里的不同发言人数。"""
        try:
            rows = self._recent(umo, limit)
        except Exception:
            return 0
        cutoff = now_ts() - window
        speakers = {
            str(row.get("uid") or "")
            for row in rows
            if row.get("role") == "user"
            and to_float(row.get("created_at"), 0) >= cutoff
            and str(row.get("uid") or "")
        }
        return len(speakers)

    def _should_quote_group(self, umo):
        """群聊要不要引用原消息：人数过阈值后按概率引用。

        人数没到阈值（人少）就不引用；到了阈值也不该句句引用——
        真人只在需要指代时才引用，所以再加一层概率。
        `quote_group_probability`：1.0 = 旧行为（一直引用），0 = 从不引用。
        """
        try:
            threshold = self.cfg_int("quote_group_speaker_threshold", 3)
        except Exception:
            threshold = 3
        if threshold <= 0:
            return False
        try:
            if self._group_speaker_count(umo) < threshold:
                return False
            prob = self.cfg_float("quote_group_probability", 0.4)
            if prob <= 0:
                return False
            if prob >= 1:
                return True
            return random.random() < prob
        except Exception:
            return False

    def _quote_allowed(self, umo, group=None):
        """能不能引用原消息：私聊（任何平台）永远不引用，群聊按人数 + 概率。

        `group` 不传就看 umo 里的消息类型。私聊不引用是硬规则：无论 QQ、飞书
        还是别的平台，都不该在私聊里把他的话再引用一遍；群聊才看
        `_should_quote_group()`（人数阈值 + `quote_group_probability`）。
        """
        umo = str(umo or "")
        if group is None:
            group = "GroupMessage" in umo
        if not group:
            return False
        if "GroupMessage" not in umo:
            return False
        try:
            return bool(self._should_quote_group(umo))
        except Exception:
            return False

    def _primary_uid(self) -> str:
        """花钱要记在「人」身上，不能记到群里随便谁。

        顺序：相恋关系的人 → 最近私聊的人 → 随便一个画像（最后兜底）。
        之前直接取 ``list_profiles(limit=1)``，结果记到了列表里第一个陌生人头上。
        """
        try:
            for uid in self._lover_aliases().values():
                if uid:
                    return str(uid)
        except Exception:
            pass
        try:
            umo = str(getattr(self, "_last_umo", "") or "") or self._first_private_umo()
        except Exception:
            umo = ""
        parts = [part for part in str(umo).split(":") if part]
        if len(parts) >= 3 and "group" not in str(umo).lower():
            return parts[-1]
        try:
            rows = self.db.list_profiles(limit=1)
        except Exception:
            rows = []
        return str(rows[0].get("uid") or "") if rows else ""

    def _cleanup_legacy_memory_profiles(self):
        """4.3.2 回到原版：删除旧版本从记忆插件导入的画像，只保留本地聊天档案。"""
        try:
            if self.db.kv_get("legacy_memory_profiles_cleaned_432", False):
                return
            removed = 0
            for row in self.db.list_profiles(limit=1000):
                if str(row.get("platform") or "") in ("angel_memory", "memory_companion"):
                    self.db.delete_profile(str(row.get("uid") or ""))
                    removed += 1
            self.db.kv_set("legacy_memory_profiles_cleaned_432", True)
            if removed:
                logger.debug("[amo] 已移除 %d 个旧记忆插件导入画像，恢复本地画像模式" % removed)
        except Exception as exc:
            logger.debug("[amo] 清理旧记忆画像失败: %s" % exc)


__all__ = [
    "merge_uid_alias_data",
    "SocialMixin",
]
