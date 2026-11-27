# -*- coding: utf-8 -*-
"""每轮注入的 token 账本（规范第十一节）。

只统计**我们自己拼进去的文本有多大**，是按区块的字符数——不冒充模型端账单：
程序侧缓存不等于模型端省 token，这一点在日志字段名里写清楚（`chars` 不是 `tokens`）。

用法（在拼装完 system prompt 之后）：

    ledger = TurnLedger(path)
    ledger.add_from_parts(system_parts)
    ledger.log(logger, umo=umo, extra={"archive": archive_chars})
"""

from __future__ import annotations

import io
import json
import os
import re
import time

#: 区块名 → 中文标签（日志里好认）
SECTIONS = {
    "persona": "人格核心",
    "archive": "档案原文",
    "world": "世界观",
    "state": "此刻状态",
    "memory": "记忆",
    "relation": "关系",
    "recent": "对话",
    "other": "其它",
}

#: 按前缀认区块（system_parts 里的标记是我们自己写的，认起来可靠）
_PREFIX_MAP = (
    ("【档案原文】", "archive"),
    ("【世界观】", "world"),
    ("【此刻状态】", "state"),
    ("【关于对方的记忆】", "memory"),
    ("【关系网】", "relation"),
    ("【关系】", "relation"),
    ("【对方】", "relation"),
    ("你", "persona"),          # 兜底不在这里用，见 classify
)

#: JSONL 保留多少行（够复盘一个礼拜）
MAX_LINES = 3000


def classify(part: str, index: int = 0) -> str:
    """给一段 system prompt 归类。第一段（没人加前缀的那段）就是人格核心。"""
    text = str(part or "").strip()
    for prefix, section in _PREFIX_MAP[:-1]:
        if text.startswith(prefix):
            return section
    if index == 0 and "【" not in text[:2]:
        return "persona"
    return "other"


class TurnLedger:
    """一轮的注入账本：分区块记字符数，落一行 JSONL。"""

    def __init__(self, path: str = ""):
        self.path = str(path or "")
        self.parts = []
        self.sections = {}

    def add(self, section: str, text) -> int:
        size = len(str(text or ""))
        self.sections[section] = self.sections.get(section, 0) + size
        self.parts.append((section, size))
        return size

    def add_from_parts(self, parts) -> dict:
        for index, part in enumerate(list(parts or [])):
            self.add(classify(part, index), part)
        return self.sections

    #: 标记关键词 → 区块（body 里是拼成一整段的，只能按【…】拆）
    _MARKERS = (("档案原文", "archive"), ("世界观", "world"), ("此刻状态", "state"),
                ("记忆", "memory"), ("关系", "relation"))

    def add_text(self, text) -> dict:
        """把拼好的整段 body 按【标记】拆开分别计数。"""
        for chunk in re.split(r"(?=【)", str(text or "")):
            if not chunk.strip():
                continue
            section = "other"
            if chunk.startswith("【") and "】" in chunk:
                name = chunk[1:chunk.find("】")]
                for key, target in self._MARKERS:
                    if key in name:
                        section = target
                        break
            self.add(section, chunk)
        return self.sections

    def total(self) -> int:
        return sum(self.sections.values())

    def as_dict(self, umo: str = "", extra: dict = None) -> dict:
        payload = {
            "ts": round(time.time(), 3),
            "umo": str(umo or ""),
            "chars_total": self.total(),
            "chars": dict(self.sections),
            "parts": len(self.parts),
            # 明确写字符：不是 token，别拿它当账单
            "unit": "chars",
        }
        if extra:
            payload.update({str(k): v for k, v in dict(extra).items()})
        return payload

    def log(self, logger=None, umo: str = "", extra: dict = None) -> dict:
        payload = self.as_dict(umo, extra)
        line = " ".join("%s=%d" % (SECTIONS.get(k, k), v)
                        for k, v in sorted(payload["chars"].items()))
        if logger is not None:
            try:
                logger.info("[amo] 本轮注入 %d 字（%s）" % (payload["chars_total"], line))
            except Exception:
                pass
        self.append(payload)
        return payload

    def append(self, payload: dict) -> bool:
        if not self.path:
            return False
        try:
            folder = os.path.dirname(os.path.abspath(self.path))
            if folder and not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)
            with io.open(self.path, "a", encoding="utf-8") as handle:
                handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._rotate()
            return True
        except Exception:
            return False

    def _rotate(self):
        """只留最后 MAX_LINES 行，避免账本无限长。"""
        try:
            if not os.path.isfile(self.path):
                return
            if os.path.getsize(self.path) < 2 * 1024 * 1024:
                return
            with io.open(self.path, encoding="utf-8") as handle:
                lines = handle.readlines()
            if len(lines) <= MAX_LINES:
                return
            with io.open(self.path, "w", encoding="utf-8") as handle:
                handle.writelines(lines[-MAX_LINES:])
        except Exception:
            pass


__all__ = ["SECTIONS", "TurnLedger", "classify", "MAX_LINES"]
