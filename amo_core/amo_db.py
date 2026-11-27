# -*- coding: utf-8 -*-
"""Amo 终端 · amo_db

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

from .deps import *  # noqa: F401,F403  用到：json, logger, os, sqlite3, threading, timedelta
from .consts import *  # noqa: F401,F403  用到：PLUGIN_NAME
from .timeutil import *  # noqa: F401,F403  用到：_now, now_ts, today_str
from .util import *  # noqa: F401,F403  用到：usage_cost
__all__ = [
    "AmoDB",
]

class AmoDB:
    def __init__(self, plugin_dir):
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            data_dir = os.path.join(get_astrbot_data_path(), "plugin_data", PLUGIN_NAME)
        except Exception:
            data_dir = os.path.join(plugin_dir, "data")
        try:
            os.makedirs(data_dir, exist_ok=True)
        except Exception:
            data_dir = plugin_dir
        self.path = os.path.join(data_dir, "amo_forever.db")
        # 4.0.0 起插件标识为 Astrbot_Amo_forever。
        # 4.0.6 保持新标识，并把 3.x 的 amo_forever 旧数据迁移到新目录。
        try:
            import shutil as _shutil
            data_root = get_astrbot_data_path()
            legacy_paths = [
                os.path.join(data_root, "plugin_data", "amo_forever", "amo_forever.db"),
                os.path.join(data_root, "plugin_data", "astrbot_plugin_amo_forever", "amo_forever.db"),
            ]
            current_size = os.path.getsize(self.path) if os.path.exists(self.path) else 0
            if current_size < 4096:
                for legacy_path in legacy_paths:
                    if not os.path.exists(legacy_path) or os.path.getsize(legacy_path) < 4096:
                        continue
                    if os.path.exists(self.path):
                        _shutil.copy2(self.path, self.path + ".bak-4.0.6")
                    for suffix in ("-wal", "-shm", "-journal"):
                        stale = self.path + suffix
                        if os.path.exists(stale):
                            try:
                                os.remove(stale)
                            except Exception:
                                pass
                    _shutil.copy2(legacy_path, self.path)
                    for suffix in ("-wal", "-shm"):
                        source = legacy_path + suffix
                        if os.path.exists(source):
                            _shutil.copy2(source, self.path + suffix)
                    logger.debug("[amo] 已迁移旧版 amo_forever 数据: %s -> %s" % (legacy_path, self.path))
                    logger.debug("[amo] 升级提示：插件标识保持 Astrbot_Amo_forever；旧 amo_forever 数据已迁移到新目录，配置文件也会自动合并。")
                    break
        except Exception as exc:
            logger.warning("[amo] 旧版 amo_forever 数据迁移失败: %s" % exc)
        self.lock = threading.RLock()
        self._conn = None
        self._open()

    def _open(self):
        with self.lock:
            self._open_unlocked()

    def _open_unlocked(self):
        """打开（或重新打开）连接。

        插件重载时 AstrBot 可能先调用旧实例的 terminate()，而旧实例注册的
        Web API 仍然存在；这里保证连接被关闭后下一次访问会自动重开，避免
        "Cannot operate on a closed database"。
        """
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=15)
        self._conn.row_factory = sqlite3.Row
        try:
            self._conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass

    @property
    def conn(self):
        # Web 协程 + 后台 _tick + _ensure_ready 可能同时进来；不加锁会各自 connect，
        # 后一个覆盖前一个，先前的连接泄漏，PRAGMA journal_mode=WAL 还可能出现 database is locked。
        if self._conn is None:
            with self.lock:
                if self._conn is None:
                    self._open()
        return self._conn

    def init(self):
        with self.lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS profiles (
                    uid TEXT PRIMARY KEY,
                    name TEXT DEFAULT '',
                    alias TEXT DEFAULT '',
                    birthday TEXT DEFAULT '',
                    relation TEXT DEFAULT '普通',
                    affection INTEGER DEFAULT 10,
                    notes TEXT DEFAULT '',
                    platform TEXT DEFAULT '',
                    private_umo TEXT DEFAULT '',
                    last_group TEXT DEFAULT '',
                    first_seen REAL DEFAULT 0,
                    last_seen REAL DEFAULT 0,
                    msg_count INTEGER DEFAULT 0,
                    last_proactive REAL DEFAULT 0,
                    proactive_day TEXT DEFAULT '',
                    proactive_count INTEGER DEFAULT 0,
                    relation_at REAL DEFAULT 0,
                    is_admin INTEGER DEFAULT 0,
                    profile_updated_at REAL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    umo TEXT DEFAULT '',
                    uid TEXT DEFAULT '',
                    name TEXT DEFAULT '',
                    role TEXT DEFAULT 'user',
                    content TEXT DEFAULT '',
                    created_at REAL DEFAULT 0
                );
                CREATE INDEX IF NOT EXISTS idx_msg_umo ON messages(umo);
                CREATE TABLE IF NOT EXISTS kv (
                    key TEXT PRIMARY KEY,
                    value TEXT DEFAULT '',
                    updated REAL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS schedule (
                    day TEXT PRIMARY KEY,
                    items TEXT DEFAULT '[]',
                    updated REAL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS schedule_diary (
                    day TEXT DEFAULT '',
                    hour TEXT DEFAULT '',
                    text TEXT DEFAULT '',
                    updated REAL DEFAULT 0,
                    PRIMARY KEY(day, hour)
                );
                CREATE TABLE IF NOT EXISTS proactive_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    uid TEXT DEFAULT '',
                    kind TEXT DEFAULT '',
                    content TEXT DEFAULT '',
                    created REAL DEFAULT 0
                );                CREATE TABLE IF NOT EXISTS token_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL DEFAULT 0,
                    kind TEXT DEFAULT '',
                    model TEXT DEFAULT '',
                    input_other INTEGER DEFAULT 0,
                    input_cached INTEGER DEFAULT 0,
                    output INTEGER DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS relation_network (
                    a_uid TEXT NOT NULL,
                    b_uid TEXT NOT NULL,
                    relation TEXT DEFAULT '朋友',
                    note TEXT DEFAULT '',
                    updated_at REAL DEFAULT 0,
                    PRIMARY KEY(a_uid, b_uid)
                );
                """
            )
            self.conn.commit()
            self._migrate_legacy()
            try:
                cols = {row[1] for row in self.conn.execute("PRAGMA table_info(profiles)").fetchall()}
                if "relation_at" not in cols:
                    self.conn.execute("ALTER TABLE profiles ADD COLUMN relation_at REAL DEFAULT 0")
                    self.conn.execute("UPDATE profiles SET relation_at=last_seen WHERE relation_at=0")
                    self.conn.commit()
                if "profile_updated_at" not in cols:
                    # 画像最后一次「本地手动修改」的时间：面板/命令改画像才更新，
                    # 收消息刷新 last_seen 不算，否则面板改完聊一句就被本地旧值覆盖。
                    self.conn.execute("ALTER TABLE profiles ADD COLUMN profile_updated_at REAL DEFAULT 0")
                    self.conn.commit()
            except Exception:
                pass

    def _migrate_legacy(self):
        try:
            has_old = self.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='user_status'"
            ).fetchone()
            if has_old:
                rows = self.conn.execute(
                    "SELECT uid, relation, mem_count FROM user_status"
                ).fetchall()
                for row in rows:
                    self.conn.execute(
                        "INSERT OR IGNORE INTO profiles(uid, relation, msg_count, first_seen, last_seen) "
                        "VALUES(?,?,?,?,?)",
                        (row["uid"], row["relation"] or "普通", row["mem_count"] or 0, now_ts(), now_ts()),
                    )
            self.conn.commit()
        except Exception as exc:
            logger.debug("[amo] 旧数据迁移跳过: %s" % exc)

    def close(self):
        with self.lock:
            if self._conn is None:
                return
            try:
                self._conn.commit()
            except Exception:
                pass
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None

    # ---------- KV ----------
    def kv_get(self, key, default=None):
        with self.lock:
            row = self.conn.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(row["value"])
        except Exception:
            return default

    def kv_set(self, key, value):
        with self.lock:
            self.conn.execute(
                "INSERT INTO kv(key, value, updated) VALUES(?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated=excluded.updated",
                (key, json.dumps(value, ensure_ascii=False), now_ts()),
            )
            self.conn.commit()

    # ---------- 档案 ----------
    def get_profile(self, uid):
        with self.lock:
            row = self.conn.execute("SELECT * FROM profiles WHERE uid=?", (str(uid),)).fetchone()
        return dict(row) if row else {}

    def touch_profile(self, uid, name, platform, umo, group_id, private):
        uid = str(uid)
        name = name or ""
        now = now_ts()
        with self.lock:
            row = self.conn.execute("SELECT * FROM profiles WHERE uid=?", (uid,)).fetchone()
            if row is None:
                self.conn.execute(
                    "INSERT INTO profiles(uid, name, platform, private_umo, last_group, "
                    "first_seen, last_seen, msg_count) VALUES(?,?,?,?,?,?,?,1)",
                    (uid, name, platform or "", umo if private else "",
                     umo if not private else "", now, now),
                )
            else:
                updates = ["last_seen=?", "msg_count=msg_count+1"]
                values = [now]
                if name and not row["name"]:
                    updates.append("name=?")
                    values.append(name)
                if private:
                    updates.append("private_umo=?")
                    values.append(umo)
                elif group_id:
                    updates.append("last_group=?")
                    values.append(umo)
                values.append(uid)
                self.conn.execute(
                    "UPDATE profiles SET " + ", ".join(updates) + " WHERE uid=?", values
                )
            self.conn.commit()
            row = self.conn.execute("SELECT * FROM profiles WHERE uid=?", (uid,)).fetchone()
        return dict(row) if row else {}

    def update_profile(self, uid, mark_local=True, **fields):
        allowed = ("name", "alias", "birthday", "relation", "notes",
                   "affection", "is_admin")
        updates = []
        values = []
        for key, value in fields.items():
            if key in allowed:
                updates.append(key + "=?")
                values.append(value)
        if "relation" in fields:
            updates.append("relation_at=?")
            values.append(now_ts())
        if mark_local:
            updates.append("profile_updated_at=?")
            values.append(now_ts())
        if not updates:
            return False
        values.append(str(uid))
        with self.lock:
            self.conn.execute(
                "UPDATE profiles SET " + ", ".join(updates) + " WHERE uid=?", values
            )
            self.conn.commit()
        return True

    def delete_profile(self, uid):
        with self.lock:
            self.conn.execute("DELETE FROM profiles WHERE uid=?", (str(uid),))
            self.conn.commit()

    def list_profiles(self, keyword="", limit=100):
        limit = max(1, min(int(limit), 500))
        with self.lock:
            if keyword:
                like = "%" + str(keyword) + "%"
                rows = self.conn.execute(
                    "SELECT * FROM profiles WHERE uid LIKE ? OR name LIKE ? OR alias LIKE ? "
                    "ORDER BY last_seen DESC LIMIT ?",
                    (like, like, like, limit),
                ).fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM profiles ORDER BY last_seen DESC LIMIT ?", (limit,)
                ).fetchall()
        return [dict(row) for row in rows]

    @staticmethod
    def _relation_pair(a_uid, b_uid):
        a, b = str(a_uid or "").strip(), str(b_uid or "").strip()
        return (a, b) if a <= b else (b, a)

    def list_relations(self):
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM relation_network ORDER BY updated_at DESC"
            ).fetchall()
        return [dict(row) for row in rows]

    def relations_for(self, uid):
        uid = str(uid or "")
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM relation_network WHERE a_uid=? OR b_uid=? ORDER BY updated_at DESC",
                (uid, uid),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_relation(self, a_uid, b_uid, relation, note=""):
        a, b = self._relation_pair(a_uid, b_uid)
        if not a or not b or a == b:
            return False
        with self.lock:
            self.conn.execute(
                "INSERT INTO relation_network(a_uid, b_uid, relation, note, updated_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(a_uid, b_uid) DO UPDATE SET "
                "relation=excluded.relation, note=excluded.note, updated_at=excluded.updated_at",
                (a, b, str(relation or "朋友"), str(note or "")[:200], now_ts()),
            )
            self.conn.commit()
        return True

    def delete_relation(self, a_uid, b_uid):
        a, b = self._relation_pair(a_uid, b_uid)
        with self.lock:
            cursor = self.conn.execute(
                "DELETE FROM relation_network WHERE a_uid=? AND b_uid=?", (a, b)
            )
            self.conn.commit()
            return cursor.rowcount > 0

    def proactive_profiles(self, limit=30):
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM profiles WHERE private_umo != '' AND relation NOT IN ('仇恨','抵触') "
                "ORDER BY last_proactive ASC LIMIT ?", (int(limit),)
            ).fetchall()
        return [dict(row) for row in rows]

    def bump_proactive(self, uid):
        today = today_str()
        with self.lock:
            row = self.conn.execute(
                "SELECT proactive_day, proactive_count FROM profiles WHERE uid=?", (str(uid),)
            ).fetchone()
            if not row:
                return
            count = int(row["proactive_count"] or 0) + 1
            if row["proactive_day"] != today:
                count = 1
            self.conn.execute(
                "UPDATE profiles SET last_proactive=?, proactive_day=?, proactive_count=? WHERE uid=?",
                (now_ts(), today, count, str(uid)),
            )
            self.conn.commit()

    def log_proactive(self, uid, kind, content):
        with self.lock:
            self.conn.execute(
                "INSERT INTO proactive_log(uid, kind, content, created) VALUES(?,?,?,?)",
                (str(uid), kind, content, now_ts()),
            )
            self.conn.commit()

    # ---------- 消息 ----------
    def add_message(self, umo, uid, name, role, content):
        content = str(content or "").strip()
        if not content:
            return
        with self.lock:
            self.conn.execute(
                "INSERT INTO messages(umo, uid, name, role, content, created_at) VALUES(?,?,?,?,?,?)",
                (str(umo), str(uid), str(name or ""), role, content, now_ts()),
            )
            self.conn.commit()

    def recent_messages(self, umo, limit=10):
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE umo=? ORDER BY id DESC LIMIT ?",
                (str(umo), int(limit)),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def recent_umos(self, limit=50):
        """最近出现过消息的会话（新的在前）。

        心跳在重启后没有 ``_last_umo``，要靠它把今天的日程续生成出来；
        以前只从 profiles 拿 private_umo，而那张表根本没有这列。
        """
        with self.lock:
            rows = self.conn.execute(
                "SELECT umo, MAX(id) AS mid FROM messages "
                "WHERE umo IS NOT NULL AND umo != '' GROUP BY umo ORDER BY mid DESC LIMIT ?",
                (int(limit),),
            ).fetchall()
        return [str(row["umo"]) for row in rows if row["umo"]]

    def messages_since_umo(self, umo, since_ts, limit=200):
        """按时间取某个会话的消息（新的在后）；判定「今天早上聊过没」用。"""
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE umo=? AND created_at>=? ORDER BY id DESC LIMIT ?",
                (str(umo), int(since_ts or 0), int(limit)),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    # ---------- 自记账：插件内部调用（判分/日记）不进 provider_stats ----------

    def record_tokens(self, kind, model, input_other, input_cached, output, ts=None):
        """记一次插件内部调用的 token；出错绝不影响主流程。"""
        try:
            def _num(value):
                try:
                    return int(float(value or 0))
                except Exception:
                    return 0

            self.conn.execute(
                "INSERT INTO token_usage(ts, kind, model, input_other, input_cached, output) "
                "VALUES(?,?,?,?,?,?)",
                (float(ts or now_ts()), str(kind or ""), str(model or ""),
                 _num(input_other), _num(input_cached), _num(output)),
            )
            self.conn.commit()
        except Exception as exc:
            try:
                logger.debug("[amo] 记 token 失败: %s" % exc)
            except Exception:
                pass

    def usage_since(self, start_ts=None):
        """按 kind 汇总插件内部调用。"""
        sql = ("SELECT kind, model, COUNT(*), SUM(input_other), SUM(input_cached), SUM(output) "
               "FROM token_usage")
        params = []
        if start_ts is not None:
            sql += " WHERE ts>=?"
            params.append(float(start_ts))
        sql += " GROUP BY kind, model"
        total = {"calls": 0, "input_other": 0, "input_cached": 0, "output": 0,
                 "peak": {"calls": 0, "input_miss": 0, "input_cached": 0, "output": 0},
                 "idle": {"calls": 0, "input_miss": 0, "input_cached": 0, "output": 0},
                 "by_kind": {}, "by_model": {}}
        try:
            rows = self.conn.execute(sql, params).fetchall()
        except Exception:
            return total
        for kind, model, calls, miss, cached, out in rows:
            entry = {"calls": int(calls or 0), "input_other": int(miss or 0),
                     "input_cached": int(cached or 0), "output": int(out or 0)}
            entry["cost"] = usage_cost({
                "peak": {"input_miss": entry["input_other"], "input_cached": entry["input_cached"],
                         "output": entry["output"], "calls": entry["calls"]},
            })
            bucket = total["by_kind"].setdefault(
                str(kind or "other"),
                {"calls": 0, "input_other": 0, "input_cached": 0, "output": 0, "cost": 0.0})
            model_bucket = total["by_model"].setdefault(
                str(model or ""),
                {"calls": 0, "input_other": 0, "input_cached": 0, "output": 0})
            for key in ("calls", "input_other", "input_cached", "output"):
                bucket[key] += entry[key]
                model_bucket[key] += entry[key]
                total[key] += entry[key]
            bucket["cost"] += entry["cost"]
        total["cost"] = usage_cost({
            "peak": {"input_miss": total["input_other"], "input_cached": total["input_cached"],
                     "output": total["output"], "calls": total["calls"]},
        })
        return total

    def messages_since_ts(self, since_ts, limit=60):
        """按时间取最近的消息（半小时摘要用），新的在后。"""
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE created_at>? ORDER BY id DESC LIMIT ?",
                (int(since_ts or 0), int(limit)),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def messages_by_uid(self, uid, limit=20):
        with self.lock:
            rows = self.conn.execute(
                "SELECT * FROM messages WHERE uid=? ORDER BY id DESC LIMIT ?",
                (str(uid), int(limit)),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def chat_history(self, uid, limit=200):
        """按用户参与过的 umo 取原始聊天记录（本人 + 机器人），不是摘要记忆。"""
        uid = str(uid)
        limit = max(1, min(2000, int(limit or 200)))
        with self.lock:
            rows = self.conn.execute(
                "SELECT DISTINCT umo FROM messages WHERE uid=? AND umo!=''",
                (uid,),
            ).fetchall()
            umos = [str(row["umo"]) for row in rows if str(row["umo"] or "")]
            if not umos:
                rows = self.conn.execute(
                    "SELECT * FROM messages WHERE uid=? ORDER BY id DESC LIMIT ?",
                    (uid, limit),
                ).fetchall()
            else:
                placeholders = ",".join("?" for _ in umos)
                params = umos + [uid, limit]
                rows = self.conn.execute(
                    "SELECT * FROM messages WHERE umo IN (" + placeholders + ") "
                    "AND (uid=? OR role='bot') ORDER BY id DESC LIMIT ?",
                    params,
                ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def interaction_stats(self, days=30):
        """按 uid 统计真实互动量（只算用户自己说的话），给关系沉淀用。

        ``days <= 0`` 表示统计全部历史，这样很早以前聊过的人也会被记进关系网。
        """
        days = int(days or 0)
        cutoff = 0 if days <= 0 else now_ts() - days * 86400
        with self.lock:
            rows = self.conn.execute(
                "SELECT uid, MAX(name) AS name, COUNT(*) AS c, MIN(created_at) AS f, MAX(created_at) AS l "
                "FROM messages WHERE role='user' AND uid!='' AND uid!='bot' AND created_at>=? "
                "GROUP BY uid ORDER BY c DESC LIMIT 1000",
                (cutoff,),
            ).fetchall()
        return [dict(row) for row in rows]

    def active_users(self, since, limit=2):
        with self.lock:
            rows = self.conn.execute(
                "SELECT uid, name, COUNT(*) AS c FROM messages WHERE role='user' AND created_at>? "
                "GROUP BY uid ORDER BY c DESC LIMIT ?", (float(since), int(limit))
            ).fetchall()
        return [dict(row) for row in rows]

    def active_profiles(self, since, limit=2):
        """最近说过话、且私聊过的人（画像表一直在更新；本地 messages 表早就不写了）。"""
        with self.lock:
            rows = self.conn.execute(
                "SELECT uid, name FROM profiles WHERE last_seen > ? "
                "AND coalesce(private_umo, '') <> '' ORDER BY last_seen DESC LIMIT ?",
                (float(since), int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def purge_messages(self, days=14):
        with self.lock:
            self.conn.execute("DELETE FROM messages WHERE created_at<?",
                              (now_ts() - max(1, int(days)) * 86400,))
            self.conn.commit()

    # ---------- 日程 ----------
    def save_schedule(self, day, items):
        with self.lock:
            self.conn.execute(
                "INSERT INTO schedule(day, items, updated) VALUES(?,?,?) "
                "ON CONFLICT(day) DO UPDATE SET items=excluded.items, updated=excluded.updated",
                (str(day), json.dumps(items, ensure_ascii=False), now_ts()),
            )
            self.conn.commit()

    def fade_schedules(self, days=7):
        """7~14 天前的日程去掉细节，只保留每小时骨架。"""
        cutoff = (_now().date() - timedelta(days=max(1, int(days)))).isoformat()
        with self.lock:
            rows = self.conn.execute(
                "SELECT day, items FROM schedule WHERE day < ?", (cutoff,)
            ).fetchall()
            for row in rows:
                try:
                    items = json.loads(row["items"])
                except Exception:
                    continue
                if not isinstance(items, list):
                    continue
                for item in items:
                    if isinstance(item, dict):
                        item.pop("detail", None)
                self.conn.execute(
                    "UPDATE schedule SET items=? WHERE day=?",
                    (json.dumps(items, ensure_ascii=False), row["day"]),
                )
            self.conn.commit()

    def purge_schedules(self, days=14):
        cutoff = (_now().date() - timedelta(days=max(1, int(days)))).isoformat()
        with self.lock:
            self.conn.execute("DELETE FROM schedule WHERE day < ?", (cutoff,))
            self.conn.commit()

    def get_schedule(self, day):
        with self.lock:
            row = self.conn.execute("SELECT items FROM schedule WHERE day=?", (str(day),)).fetchone()
        if not row:
            return None
        try:
            return json.loads(row["items"])
        except Exception:
            return None

    def get_diary(self, day, hour):
        with self.lock:
            row = self.conn.execute(
                "SELECT text FROM schedule_diary WHERE day=? AND hour=?",
                (str(day), str(hour)),
            ).fetchone()
        return str(row["text"] or "") if row else ""

    def save_diary(self, day, hour, text):
        with self.lock:
            self.conn.execute(
                "INSERT INTO schedule_diary(day, hour, text, updated) VALUES(?,?,?,?) "
                "ON CONFLICT(day, hour) DO UPDATE SET text=excluded.text, updated=excluded.updated",
                (str(day), str(hour), str(text or ""), now_ts()),
            )
            self.conn.commit()

    def clear_diaries(self, day):
        with self.lock:
            self.conn.execute("DELETE FROM schedule_diary WHERE day=?", (str(day),))
            self.conn.commit()

    def clear_diaries_from(self, day, hour):
        """只清某个小时及以后的小日记（换城覆盖日程时用，过去的留着）。"""
        with self.lock:
            self.conn.execute(
                "DELETE FROM schedule_diary WHERE day=? AND hour>=?", (str(day), str(hour))
            )
            self.conn.commit()

    def purge_diaries(self, days=30):
        cutoff = (_now().date() - timedelta(days=max(1, int(days)))).isoformat()
        with self.lock:
            self.conn.execute("DELETE FROM schedule_diary WHERE day < ?", (cutoff,))
            self.conn.commit()

    # ---------- 统计 ----------
    def counts(self):
        with self.lock:
            profiles = self.conn.execute("SELECT COUNT(*) AS c FROM profiles").fetchone()["c"]
            memories = 0
            messages = self.conn.execute("SELECT COUNT(*) AS c FROM messages").fetchone()["c"]
        return {"profiles": profiles, "memories": memories, "messages": messages}
