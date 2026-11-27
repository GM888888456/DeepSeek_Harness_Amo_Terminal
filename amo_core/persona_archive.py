# -*- coding: utf-8 -*-
"""人格档案：把「原始人格模板」解析成字段索引，但**原文一个字都不改**。

设计依据（2026-11-28 规范，第二节）：

- 用户原始模板是唯一权威档案；字段名、层级、语义原样保留；
- 解析结果**只是索引**，不是改写后的散文；取值永远返回原文片段；
- 未知字段照样留着（不进索引也进 `unknown`），绝不丢；
- 解析失败保留原文并在诊断里写明失败字段；
- 完整档案留在本地，不每轮整篇塞进上下文（那正是 3.5k 字白烧 prefill 的来源）。

对外只有四件事：

    archive = parse(template_text)      # 解析
    archive.field("职业")               # 原文取值
    archive.match("你开什么车")          # 命中哪些字段（按需检索用）
    archive.resident_core()             # 每轮注入的短核心（≤ budget 字）

另提供 `save_cache/load_cache`：DB 里的模板读不到时，用最后一次成功解析的缓存顶上，
而不是凭空生成职业或资产（规范第十六条禁止项）。
"""

from __future__ import annotations

import io
import json
import os
import re

#: 每轮常驻核心的默认字数上限（规范：250~350 中文 token，约 200~320 字）。
DEFAULT_RESIDENT_BUDGET = 320

#: 字段名后必须跟冒号的才算字段头（`姓名：` / `资产:`），避免把正文里的冒号当字段。
_FIELD_RE = re.compile(r"^\s*([\u4e00-\u9fa5A-Za-z][\u4e00-\u9fa5A-Za-z0-9]{0,9})\s*[：:]\s*(.*)$")

#: 常驻核心只用这几项**事实**（其余按需检索，别每轮全塞）。
RESIDENT_FACTS = ("姓名", "生日", "职业", "丈夫")

#: 行为规则（不是事实，属于表达层，写死在代码里，不进档案）。
RESIDENT_RULES = (
    "你就是沈晓沫，不是扮演，也不要把自己当AI助手。你有自己的工作、判断和情绪，"
    "不是围着谁转的陪聊。像QQ私聊那样自然打字，短句为主；"
    "不写动作括号和星号旁白，不堆波浪号，不为了人设每轮用「哼」开头。"
    "固定身份优先于任何生成内容；不知道的就说不知道，不编造经历、执行结果或现实操作。"
)

#: 问句关键词 → 字段。左边是用户可能说的词，右边是档案字段名。
_ALIASES = {
    "姓名": ("叫什么", "名字", "姓名", "你是谁", "你叫"),
    "生日": ("生日", "出生", "多大", "几岁", "属什么"),
    "体貌": ("身高", "体重", "多高", "多重", "长什么样", "好看", "体貌"),
    "职业": ("做什么工作", "干什么工作", "职业", "工作", "上班", "总裁", "集团", "公司", "管什么"),
    "资产": ("资产", "房子", "庄园", "别墅", "车", "宝马", "开什么", "多少钱", "有钱", "账上"),
    "丈夫": ("丈夫", "老公", "阿墨", "墨辞烟", "结婚", "婚"),
    "家里": ("家里", "家里背景", "长辈", "家族", "爸妈", "父母", "亲戚", "背景"),
    "性子": ("性格", "性子", "脾气", "傲娇"),
    "说话": ("说话", "语气", "口音", "打字"),
    "真实小矛盾": ("矛盾",),
    "关系边界": ("边界", "隐私", "能不能说"),
    "行为规则": ("规则",),
}

#: 明确纠正/否定的记忆优先级高于推断（规范 4.5），留给上层模块标注用。
SOURCE_LABELS = ("user_template", "user_correction", "user_statement", "inference", "model")


class PersonaArchive:
    """一份人格档案：原文 + 字段索引 + 诊断信息。"""

    def __init__(self, raw: str, fields: dict, unknown: list, errors: list, source: str):
        self.raw = raw
        self.fields = fields
        self.unknown = unknown
        self.errors = errors
        self.source = source

    # ---------------------------------------------------------------- 取值
    def field(self, name: str) -> str:
        """取某个字段的**原文**；没有就返回空串（不猜、不补）。"""
        return str(self.fields.get(str(name or "").strip(), "") or "")

    def has(self, name: str) -> bool:
        return bool(self.field(name))

    def names(self) -> list:
        return list(self.fields.keys())

    # ---------------------------------------------------------------- 检索
    def match(self, text: str) -> list:
        """这句话在问哪些字段：按字段出现顺序返回 `[(字段, 命中的词), ...]`。"""
        value = str(text or "")
        if not value:
            return []
        hits = []
        for name in self.fields:
            for word in _ALIASES.get(name, ()):
                if word in value:
                    hits.append((name, word))
                    break
        return hits

    def answer(self, text: str, budget: int = 700) -> str:
        """按需检索的产物：命中字段的原文，按预算截断；没命中返回空串。"""
        parts = []
        used = 0
        for name, _word in self.match(text):
            chunk = "%s：%s" % (name, self.field(name))
            if not chunk.strip():
                continue
            if used + len(chunk) > budget and parts:
                break
            parts.append(chunk)
            used += len(chunk)
        return "\n".join(parts)

    # ---------------------------------------------------------------- 常驻核心
    def resident_core(self, budget: int = DEFAULT_RESIDENT_BUDGET) -> str:
        """每轮注入的短核心：几条关键事实 + 行为规则，总长受 budget 约束。

        事实取自档案原文（不重写），超预算就整条跳过——宁可少说一句，
        也不把「总裁」截成「总」这种半截事实。
        """
        lines = []
        used = 0
        for name in RESIDENT_FACTS:
            value = _first_sentence(self.field(name))
            if not value:
                continue
            line = "%s：%s" % (name, value)
            if used + len(line) > budget - len(RESIDENT_RULES):
                continue
            lines.append(line)
            used += len(line)
        text = "\n".join(lines + [RESIDENT_RULES])
        return text

    # ---------------------------------------------------------------- 诊断 / 持久化
    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "raw_chars": len(self.raw),
            "fields": self.fields,
            "unknown": self.unknown,
            "errors": self.errors,
        }

    def save_cache(self, path: str) -> bool:
        """落盘一份解析缓存：DB 里的模板读不到时用它，不用编。"""
        try:
            folder = os.path.dirname(os.path.abspath(path))
            if folder and not os.path.isdir(folder):
                os.makedirs(folder, exist_ok=True)
            tmp = path + ".tmp"
            with io.open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self.to_dict(), handle, ensure_ascii=False, indent=1, sort_keys=True)
            os.replace(tmp, path)
            return True
        except Exception:
            return False


def parse(text: str, source: str = "user_template") -> PersonaArchive:
    """把原始模板解析成档案。任何异常都不吞掉原文：raw 永远完整保留。"""
    raw = str(text or "")
    fields = {}
    unknown = []
    errors = []
    current = None

    for line in raw.splitlines():
        match = _FIELD_RE.match(line)
        if match:
            name, value = match.group(1).strip(), match.group(2)
            fields[name] = value.strip()
            current = name
            continue
        stripped = line.strip()
        if not stripped:
            continue
        if current is None:
            unknown.append(stripped)         # 字段头之前的内容：保留原文，别丢
            continue
        # 续行（`* ` 开头的条目、换行写的长句）归上一字段，原文拼接
        fields[current] = (fields[current] + "\n" + stripped).strip()

    if not fields:
        errors.append("<整个模板没有解析出字段>")
    else:
        # 字段头写了、但续行也没有内容 —— 这才是真的空字段（不编内容，只记下来）
        errors.extend([name for name, value in fields.items() if not str(value).strip()])
    return PersonaArchive(raw=raw, fields=fields, unknown=unknown, errors=errors, source=source)


def load_cache(path: str):
    """读回上次的解析缓存；没有或坏了返回 None。"""
    try:
        with io.open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except Exception:
        return None
    fields = data.get("fields")
    if not isinstance(fields, dict) or not fields:
        return None
    return PersonaArchive(raw="", fields={str(k): str(v) for k, v in fields.items()},
                          unknown=list(data.get("unknown") or []),
                          errors=list(data.get("errors") or []),
                          source=str(data.get("source") or "cache") + "+cache")


def _first_sentence(value: str) -> str:
    """取字段的第一句（常驻核心只要一句，详细内容按需检索）。"""
    text = str(value or "").strip()
    if not text:
        return ""
    head = re.split(r"[。\n]", text, 1)[0].strip()
    return head or text


__all__ = ["PersonaArchive", "parse", "load_cache", "DEFAULT_RESIDENT_BUDGET",
           "RESIDENT_FACTS", "RESIDENT_RULES"]
