# -*- coding: utf-8 -*-
"""Relationship domain store.

Owns durable people/organization identities, relationship edges and interaction history.
The Terminal remains the orchestration layer; it must not duplicate these records.
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager


class RelationshipStore:
    """Small SQLite-backed relationship domain with idempotent, auditable writes."""

    def __init__(self, data_dir: str):
        self.data_dir = os.path.abspath(str(data_dir))
        os.makedirs(self.data_dir, exist_ok=True)
        self.path = os.path.join(self.data_dir, "relationship.db")
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS people (
                    person_id TEXT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    aliases TEXT NOT NULL DEFAULT '[]',
                    entity_type TEXT NOT NULL DEFAULT 'person',
                    attributes TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS relationships (
                    relation_id TEXT PRIMARY KEY,
                    subject_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
                    object_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
                    relation_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    familiarity REAL NOT NULL DEFAULT 0,
                    trust REAL NOT NULL DEFAULT 0,
                    confidence REAL NOT NULL DEFAULT 1,
                    source TEXT NOT NULL DEFAULT 'manual',
                    note TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    UNIQUE(subject_id, object_id, relation_type)
                );
                CREATE INDEX IF NOT EXISTS idx_relationship_subject ON relationships(subject_id);
                CREATE INDEX IF NOT EXISTS idx_relationship_object ON relationships(object_id);
                CREATE TABLE IF NOT EXISTS interactions (
                    interaction_id TEXT PRIMARY KEY,
                    person_id TEXT NOT NULL REFERENCES people(person_id) ON DELETE CASCADE,
                    occurred_at REAL NOT NULL,
                    channel TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT 'conversation',
                    summary TEXT NOT NULL DEFAULT '',
                    sentiment REAL,
                    source_event_id TEXT UNIQUE,
                    metadata TEXT NOT NULL DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_interactions_person_time
                    ON interactions(person_id, occurred_at DESC);
                CREATE TABLE IF NOT EXISTS social_events (
                    event_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    event_type TEXT NOT NULL DEFAULT 'social',
                    starts_at REAL,
                    ends_at REAL,
                    location TEXT NOT NULL DEFAULT '',
                    participant_ids TEXT NOT NULL DEFAULT '[]',
                    status TEXT NOT NULL DEFAULT 'planned',
                    metadata TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );
            """)
            self._conn.commit()

    @contextmanager
    def _write(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield self._conn
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    @staticmethod
    def _json(value, fallback):
        try:
            return json.dumps(value if value is not None else fallback, ensure_ascii=False)
        except (TypeError, ValueError):
            return json.dumps(fallback, ensure_ascii=False)

    @staticmethod
    def _decode(row):
        return dict(row) if row is not None else None

    def upsert_person(self, display_name, person_id=None, aliases=None,
                      entity_type="person", attributes=None):
        name = str(display_name or "").strip()
        if not name:
            raise ValueError("display_name is required")
        pid = str(person_id or ("P-" + uuid.uuid4().hex[:16]))
        now = time.time()
        with self._write() as conn:
            conn.execute("""
                INSERT INTO people(person_id,display_name,aliases,entity_type,attributes,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?)
                ON CONFLICT(person_id) DO UPDATE SET
                    display_name=excluded.display_name, aliases=excluded.aliases,
                    entity_type=excluded.entity_type, attributes=excluded.attributes,
                    updated_at=excluded.updated_at
            """, (pid, name, self._json(aliases, []), str(entity_type or "person"),
                  self._json(attributes, {}), now, now))
        return self.get_person(pid)

    def get_person(self, person_id):
        with self._lock:
            return self._decode(self._conn.execute(
                "SELECT * FROM people WHERE person_id=?", (str(person_id),)
            ).fetchone())

    def find_people(self, query="", limit=50):
        q = str(query or "").strip()
        limit = max(1, min(int(limit), 200))
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM people WHERE display_name LIKE ? OR aliases LIKE ? "
                "ORDER BY updated_at DESC LIMIT ?", ("%" + q + "%", "%" + q + "%", limit)
            ).fetchall()
        return [self._decode(row) for row in rows]

    def set_relationship(self, subject_id, object_id, relation_type,
                         familiarity=None, trust=None, confidence=1.0,
                         source="manual", note="", status="active"):
        a, b = str(subject_id or "").strip(), str(object_id or "").strip()
        kind = str(relation_type or "").strip()
        if not a or not b or a == b or not kind:
            raise ValueError("distinct subject_id, object_id and relation_type are required")
        now = time.time()
        with self._write() as conn:
            for pid in (a, b):
                if not conn.execute("SELECT 1 FROM people WHERE person_id=?", (pid,)).fetchone():
                    raise ValueError("unknown person_id: " + pid)
            old = conn.execute(
                "SELECT relation_id,familiarity,trust FROM relationships "
                "WHERE subject_id=? AND object_id=? AND relation_type=?", (a, b, kind)
            ).fetchone()
            rid = old["relation_id"] if old else "R-" + uuid.uuid4().hex[:16]
            fam = float(familiarity if familiarity is not None else (old["familiarity"] if old else 0))
            tr = float(trust if trust is not None else (old["trust"] if old else 0))
            conn.execute("""
                INSERT INTO relationships(relation_id,subject_id,object_id,relation_type,status,
                    familiarity,trust,confidence,source,note,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(subject_id,object_id,relation_type) DO UPDATE SET
                    status=excluded.status, familiarity=excluded.familiarity, trust=excluded.trust,
                    confidence=excluded.confidence, source=excluded.source, note=excluded.note,
                    updated_at=excluded.updated_at
            """, (rid, a, b, kind, str(status or "active"), max(0,min(100,fam)),
                  max(0,min(100,tr)), max(0,min(1,float(confidence))), str(source or "manual"),
                  str(note or "")[:1000], now, now))
        return self.list_relationships(a, include_inactive=True)

    def list_relationships(self, person_id=None, include_inactive=False):
        clauses, args = [], []
        if person_id:
            clauses.append("(subject_id=? OR object_id=?)")
            args.extend([str(person_id), str(person_id)])
        if not include_inactive:
            clauses.append("status='active'")
        sql = "SELECT * FROM relationships"
        if clauses:
            sql += " WHERE " + " AND ".join(clauses)
        sql += " ORDER BY updated_at DESC"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [self._decode(row) for row in rows]

    def record_interaction(self, person_id, summary="", channel="", kind="conversation",
                           occurred_at=None, sentiment=None, source_event_id=None, metadata=None):
        pid = str(person_id or "").strip()
        if not self.get_person(pid):
            raise ValueError("unknown person_id: " + pid)
        iid = "I-" + uuid.uuid4().hex[:16]
        with self._write() as conn:
            if source_event_id:
                existing = conn.execute(
                    "SELECT * FROM interactions WHERE source_event_id=?", (str(source_event_id),)
                ).fetchone()
                if existing:
                    return self._decode(existing)
            conn.execute("""
                INSERT INTO interactions(interaction_id,person_id,occurred_at,channel,kind,
                    summary,sentiment,source_event_id,metadata)
                VALUES(?,?,?,?,?,?,?,?,?)
            """, (iid, pid, float(occurred_at or time.time()), str(channel or ""),
                  str(kind or "conversation"), str(summary or "")[:2000],
                  None if sentiment is None else max(-1,min(1,float(sentiment))),
                  str(source_event_id) if source_event_id else None, self._json(metadata, {})))
            row = conn.execute("SELECT * FROM interactions WHERE interaction_id=?", (iid,)).fetchone()
        return self._decode(row)

    def list_interactions(self, person_id, limit=50):
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM interactions WHERE person_id=? ORDER BY occurred_at DESC LIMIT ?",
                (str(person_id), max(1, min(int(limit), 500)))
            ).fetchall()
        return [self._decode(row) for row in rows]

    def record_social_event(self, title, event_type="social", starts_at=None,
                            ends_at=None, location="", participant_ids=None,
                            status="planned", metadata=None, event_id=None):
        name = str(title or "").strip()
        if not name:
            raise ValueError("title is required")
        eid = str(event_id or ("E-" + uuid.uuid4().hex[:16]))
        now = time.time()
        participants = [str(x) for x in (participant_ids or []) if str(x)]
        with self._write() as conn:
            for pid in participants:
                if not conn.execute("SELECT 1 FROM people WHERE person_id=?", (pid,)).fetchone():
                    raise ValueError("unknown participant: " + pid)
            conn.execute("""
                INSERT INTO social_events(event_id,title,event_type,starts_at,ends_at,location,
                    participant_ids,status,metadata,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(event_id) DO UPDATE SET title=excluded.title,
                    event_type=excluded.event_type, starts_at=excluded.starts_at,
                    ends_at=excluded.ends_at, location=excluded.location,
                    participant_ids=excluded.participant_ids, status=excluded.status,
                    metadata=excluded.metadata, updated_at=excluded.updated_at
            """, (eid, name, str(event_type or "social"), starts_at, ends_at,
                  str(location or ""), self._json(participants, []), str(status or "planned"),
                  self._json(metadata, {}), now, now))
            row = conn.execute("SELECT * FROM social_events WHERE event_id=?", (eid,)).fetchone()
        return self._decode(row)

    def list_social_events(self, limit=100):
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM social_events ORDER BY coalesce(starts_at,created_at) DESC LIMIT ?",
                (max(1, min(int(limit), 500)),)
            ).fetchall()
        return [self._decode(row) for row in rows]

    def import_legacy(self, profiles=None, relations=None):
        """Idempotently import Terminal's old UID graph without importing its private user-affection state."""
        profile_rows = profiles if isinstance(profiles, list) else []
        relation_rows = relations if isinstance(relations, list) else []
        people_count = edge_count = 0
        for row in profile_rows:
            if not isinstance(row, dict):
                continue
            uid = str(row.get("uid") or "").strip()
            if not uid or uid in ("bot", "self"):
                continue
            name = str(row.get("alias") or row.get("name") or uid)
            self.upsert_person(name, person_id=uid, aliases=[row.get("name"), row.get("alias")],
                               entity_type="person",
                               attributes={"legacy_uid": uid})
            people_count += 1
        for row in relation_rows:
            if not isinstance(row, dict):
                continue
            a = str(row.get("a_uid") or "").strip()
            b = str(row.get("b_uid") or "").strip()
            if not a or not b or a in ("bot", "self") or b in ("bot", "self"):
                continue
            for pid in (a, b):
                if not self.get_person(pid):
                    self.upsert_person(pid, person_id=pid, attributes={"legacy_uid": pid})
            self.set_relationship(a, b, str(row.get("relation") or "朋友"),
                                  source="terminal_legacy", note=str(row.get("note") or ""))
            edge_count += 1
        return {"people_imported": people_count, "relationships_imported": edge_count}

    def snapshot(self):
        with self._lock:
            counts = {}
            for table in ("people", "relationships", "interactions", "social_events"):
                counts[table] = int(self._conn.execute("SELECT COUNT(*) FROM " + table).fetchone()[0])
        return {"database": os.path.basename(self.path), "counts": counts}

    def close(self):
        with self._lock:
            self._conn.close()
