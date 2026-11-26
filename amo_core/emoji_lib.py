# -*- coding: utf-8 -*-
"""表情包库：收藏、打标签、按情绪挑、控频率。

存储（都在 plugin_data/Astr_Amo_data/emoji/ 下）：
    files/<sha1>.<ext>     图片本体，按内容哈希命名，同一张不会存两遍
    index.json             {sha1: {"file","tags","added","uses","last"}}

标签用和颜文字同一套词（开心/撒娇/无语/生气/委屈/惊讶/困/敷衍），
这样「此刻的情绪 → 挑一张」不用再翻译一次。

频率（"不能一直发，也不能一直不发"）：
    · 基础概率 10%，冷却 8 分钟；
    · 保底：60 分钟没发过、且最近 10 条回复都没带 —— 概率提到 45%；
    · 刚带过就绝不再带（调用方传 last_had）。
"""

from __future__ import annotations

import hashlib
import json
import os
import random
import time
from typing import Optional

TAG_BY_DIM = {
    "joy": "开心",
    "love": "撒娇",
    "disgust": "无语",
    "anger": "生气",
    "sadness": "委屈",
    "surprise": "惊讶",
    "energy": "困",
}

ALL_TAGS = ("开心", "撒娇", "无语", "生气", "委屈", "惊讶", "困", "敷衍")

BASE_PROB = 0.10
COOLDOWN_SECONDS = 8 * 60
IDLE_FORCE_SECONDS = 60 * 60
FORCE_PROB = 0.45
IDLE_STREAK = 10          # 连续多少条没带表情算「冷场」

_EXTS = {b"\xff\xd8\xff": "jpg", b"\x89PNG": "png", b"GIF8": "gif", b"RIFF": "webp"}


# EMOJI_MAX_CAP 2026-11-24：用户口径 —— 总库 50 张，每种情绪 5 张，收满了就不再收新的。
# （2026-11-23 那版是 500，按 QQ 收藏面板的硬上限；现在按她的要求收窄。）
MAX_ITEMS = 50
PER_TAG_CAP = 5


def _entry_tags(entry: dict) -> list:
    tags = (entry or {}).get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    return [t for t in tags if t in ALL_TAGS]


def _counters(index: dict) -> tuple:
    """(总数, {标签: 张数})"""
    counts = {t: 0 for t in ALL_TAGS}
    for entry in index.values():
        if not isinstance(entry, dict):
            continue
        for tag in _entry_tags(entry):
            counts[tag] = counts.get(tag, 0) + 1
    return len(index), counts


def is_saturated(root: str) -> bool:
    """是不是已经收满了：总数到 MAX_ITEMS，或者每种情绪都有 PER_TAG_CAP 张。"""
    total, counts = _counters(load_index(root))
    if total >= MAX_ITEMS:
        return True
    return all(counts.get(tag, 0) >= PER_TAG_CAP for tag in ALL_TAGS)


def _blocked(index: dict, tags=()) -> tuple:
    """这张还能不能收：(能不能, 原因)。总库满了、或它带的情绪槽都满了，就不再收。"""
    total, counts = _counters(index)
    tags = [t for t in (tags or []) if t in ALL_TAGS]
    if total >= MAX_ITEMS:
        return True, "total"
    for tag in tags:
        if counts.get(tag, 0) >= PER_TAG_CAP:
            return True, "tag:" + tag
    return False, ""


def _drop(root: str, index: dict, key: str) -> bool:
    entry = index.get(key)
    if not isinstance(entry, dict):
        return False
    try:
        rel = entry.get("file") or ""
        path = os.path.join(root, rel)
        if rel and os.path.exists(path):
            os.remove(path)
    except Exception:
        pass
    index.pop(key, None)
    return True


def _evict_one(root: str, index: dict, tag: str = "") -> bool:
    """删一张，返回删没删。

    顺序：先删没标签的，再删没收藏的，再删用得最少的，再删最久没发的，最后才动加得最早的。
    """
    pool = [(key, entry) for key, entry in index.items() if isinstance(entry, dict)]
    if tag:
        pool = [(k, e) for k, e in pool if tag in _entry_tags(e)]
    if not pool:
        return False
    pool.sort(key=lambda item: (
        bool(_entry_tags(item[1])),
        bool(item[1].get("fav")),
        int(item[1].get("uses") or 0),
        int(item[1].get("last") or 0),
        int(item[1].get("added") or 0),
    ))
    return _drop(root, index, pool[0][0])


def _evict_for_room(root: str, index: dict, need: int = 1) -> int:
    """给新表情腾位置，返回删掉几张（总库超 MAX_ITEMS 时才动）。"""
    removed = 0
    need = max(0, int(need))
    while removed < need and len(index) >= MAX_ITEMS:
        if not _evict_one(root, index):
            break
        removed += 1
    return removed


def _score(entry: dict) -> tuple:
    """一张表情该不该留：收藏过 > 用得多 > 最近用过 > 放得晚的。"""
    return (
        bool(entry.get("fav")),
        int(entry.get("uses") or 0),
        int(entry.get("last") or 0),
        int(entry.get("added") or 0),
    )


def _primary_tag(entry: dict) -> str:
    """一张图只算一个情绪：ALL_TAGS 里第一个命中的标签（没有就空）。"""
    tags = _entry_tags(entry)
    for tag in ALL_TAGS:
        if tag in tags:
            return tag
    return ""


def _select_keep(index: dict) -> tuple:
    """每种情绪留最该留的 PER_TAG_CAP 张，一张图只归一类，没标签的不留。

    按「候选张数」稀缺优先分配：像「敷衍」这种大部分图还带着别的标签、
    候选本来就少的类别先挑，免得被前面的类别把图吃光。
    返回 (留, 删)；留下的图会被改成只带被分到的那个标签。
    """
    cands: dict = {}
    for tag in ALL_TAGS:
        pool = [(k, e) for k, e in index.items()
                if isinstance(e, dict) and tag in _entry_tags(e)]
        if pool:
            cands[tag] = sorted(pool, key=lambda item: _score(item[1]), reverse=True)
    keep: dict = {}
    taken: set = set()
    for tag in sorted(cands, key=lambda t: len(cands[t])):
        got = 0
        for key, entry in cands[tag]:
            if got >= PER_TAG_CAP:
                break
            if key in taken:
                continue
            taken.add(key)
            entry["tags"] = [tag]        # 归到这一类，索引里也只留这一个
            keep[key] = entry
            got += 1
    # 8 类 × 5 张 = 40；剩下 10 个名额留给以后新收的（先没标签进来，标好才占某类的位）
    drop = [k for k in index if k not in keep]
    return list(keep), drop


def rebalance(root: str) -> dict:
    """按「每种情绪 PER_TAG_CAP 张、总数 MAX_ITEMS 张」重新选一遍，返回统计。"""
    index = load_index(root)
    keep, drop = _select_keep(index)
    for key in drop:
        _drop(root, index, key)
    if drop or keep:
        save_index(root, index)
    counts = _counters(index)[1]
    return {"removed": len(drop), "total": len(index), "tags": counts}


def enforce_limit(root: str) -> int:
    """把现有表情库裁到上限内，返回删掉几张。"""
    return int(rebalance(root).get("removed") or 0)


def root_dir(db_path: str) -> str:
    """表情库根目录（跟 amo_forever.db 同一个 plugin_data 目录）。"""
    return os.path.join(os.path.dirname(str(db_path or "")), "emoji")


def _files_dir(root: str) -> str:
    path = os.path.join(root, "files")
    os.makedirs(path, exist_ok=True)
    return path


def _index_path(root: str) -> str:
    return os.path.join(root, "index.json")


def load_index(root: str) -> dict:
    try:
        with open(_index_path(root), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_index(root: str, index: dict) -> None:
    os.makedirs(root, exist_ok=True)
    tmp = _index_path(root) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(index, fh, ensure_ascii=False, indent=1)
    os.replace(tmp, _index_path(root))


def _guess_ext(data: bytes) -> str:
    for magic, ext in _EXTS.items():
        if data.startswith(magic):
            return ext
    return "gif"


def add_bytes(root: str, data: bytes, tags=()) -> tuple[str, str]:
    """存一张表情，返回 (哈希, 文件路径)。同一张内容只存一次。"""
    if not data:
        return "", ""
    key = hashlib.sha1(data).hexdigest()
    index = load_index(root)
    entry = index.get(key)
    if entry and os.path.exists(os.path.join(root, entry.get("file") or "")):
        if tags:
            merged = list(dict.fromkeys(list(entry.get("tags") or []) + list(tags)))
            entry["tags"] = merged
            index[key] = entry
            save_index(root, index)
        return key, os.path.join(root, entry["file"])
    # EMOJI_MAX_CAP 2026-11-24：满了就不收（总库 50 张、每种情绪 5 张），不再挤掉旧的
    tags = [t for t in (tags or []) if t in ALL_TAGS]
    blocked, _why = _blocked(index, tags)
    if blocked:
        return "", ""
    ext = _guess_ext(data)
    rel = os.path.join("files", "%s.%s" % (key, ext))
    abs_path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(abs_path), exist_ok=True)
    with open(abs_path, "wb") as fh:
        fh.write(data)
    index[key] = {
        "file": rel,
        "tags": list(dict.fromkeys(list(tags or []))),
        "added": int(time.time()),
        "uses": 0,
        "last": 0,
    }
    save_index(root, index)
    return key, abs_path


def add_file(root: str, path: str, tags=()) -> tuple[str, str]:
    try:
        with open(path, "rb") as fh:
            return add_bytes(root, fh.read(), tags)
    except Exception:
        return "", ""


def looks_like_photo(path: str) -> bool:
    """这张图是不是照片（而不是表情包）。

    2026-11-21 的事故：她把他发来的自拍当表情收了，还发到群里。
    判据（宁严勿松，表情少几张没关系，别人的照片流出去是大事）：
      · GIF / WebP：表情（照片很少用这两个，WebP 动图基本都是表情）；
      · PNG 带透明：表情；
      · JPEG：小（<100KB）且接近正方（0.88~1.15）才算表情，其余一律当照片。
    取不到尺寸/打不开 → 当照片（不收）。
    """
    try:
        from PIL import Image
    except Exception:
        return True
    path = str(path or "")
    if not os.path.isfile(path):
        return True
    try:
        with Image.open(path) as im:
            fmt = (im.format or "").upper()
            size = im.size
            mode = im.mode
            try:
                px = im.convert("RGBA").getpixel((0, 0))
                alpha = int(px[3]) if isinstance(px, tuple) and len(px) == 4 else 255
            except Exception:
                alpha = 255
    except Exception:
        return True
    if fmt in ("GIF", "WEBP"):
        return False
    if fmt == "PNG" and (mode in ("RGBA", "LA", "P") or alpha < 255):
        return False
    try:
        w, h = int(size[0]), int(size[1])
        kb = os.path.getsize(path) / 1024.0
    except Exception:
        return True
    if fmt == "JPEG":
        ratio = (w / float(h)) if h else 0
        return not (kb < 100 and 0.88 <= ratio <= 1.15)
    return True


def purge_photos(root: str, move_dir: str = "") -> dict:
    """把库里的照片挪出去（不硬删，挪进 quarantine 目录），返回统计。"""
    index = load_index(root)
    files = _files_dir(root)
    move_dir = move_dir or os.path.join(root, "_quarantine_" + time.strftime("%Y%m%d-%H%M%S"))
    moved, kept, err = [], 0, 0
    for key, entry in list(index.items()):
        rel = str((entry or {}).get("file") or "")
        path = os.path.join(root, rel) if rel else ""
        if not path or not os.path.isfile(path):
            index.pop(key, None)
            err += 1
            continue
        if looks_like_photo(path):
            try:
                os.makedirs(move_dir, exist_ok=True)
                os.replace(path, os.path.join(move_dir, os.path.basename(path)))
                moved.append(rel)
            except Exception:
                err += 1
                continue
            index.pop(key, None)
        else:
            kept += 1
    save_index(root, index)
    return {"moved": len(moved), "kept": kept, "missing": err, "dir": move_dir if moved else ""}


def tag_of(feel: Optional[dict]) -> str:
    """此刻最突出的情绪 → 标签；都不明显返回空串。"""
    best, best_val = "", -1.0
    for dim, tag in TAG_BY_DIM.items():
        try:
            val = float((feel or {}).get(dim) or 0)
        except (TypeError, ValueError):
            continue
        if val > best_val:
            best, best_val = tag, val
    if best_val < 55:
        return ""
    energy = (feel or {}).get("energy")
    if energy is not None:
        try:
            if float(energy) <= 12:
                return "困"
        except (TypeError, ValueError):
            pass
    return best


def _candidates(root: str, index: dict, tag: str) -> list[tuple[str, dict]]:
    out = []
    for key, entry in index.items():
        if not isinstance(entry, dict):
            continue
        path = os.path.join(root, entry.get("file") or "")
        if not os.path.isfile(path):
            continue
        tags = entry.get("tags") or []
        if tag and tag not in tags:
            continue
        out.append((path, entry))
    return out


def pick(
    root: str,
    feel: Optional[dict] = None,
    rng: Optional[random.Random] = None,
    last_sent_at: float = 0.0,
    idle_streak: int = 0,
    last_had: bool = False,
    now: Optional[float] = None,
) -> str:
    """按节奏决定这轮要不要发、发哪张；不发返回空串。"""
    r = rng or random
    now = float(now if now is not None else time.time())
    if last_had:
        return ""
    if now - float(last_sent_at or 0) < COOLDOWN_SECONDS:
        return ""
    index = load_index(root)
    if not index:
        return ""
    tag = tag_of(feel)
    pool = _candidates(root, index, tag)
    if not pool:
        # 没有对应情绪的图就退到全库，但只给三成机会，免得乱贴
        pool = _candidates(root, index, "")
        if not pool or r.random() > 0.3:
            return ""
    # 「不能一直不发」必须是确定的：冷场够久就发，不再掷骰子。
    # （原来只是把概率抬到 45%，仍可能连着几次不中，等于没保底。）
    if (now - float(last_sent_at or 0) >= IDLE_FORCE_SECONDS
            and int(idle_streak or 0) >= IDLE_STREAK):
        forced = True
    else:
        forced = False
    if not forced and r.random() >= BASE_PROB:
        return ""
    # 少用的优先，避免总发同一张
    pool.sort(key=lambda item: (item[1].get("uses") or 0, item[1].get("last") or 0))
    top = pool[: max(1, len(pool) // 3)]
    return r.choice(top)[0]


def mark_used(root: str, path: str) -> None:
    index = load_index(root)
    for key, entry in index.items():
        if isinstance(entry, dict) and os.path.join(root, entry.get("file") or "") == path:
            entry["uses"] = int(entry.get("uses") or 0) + 1
            entry["last"] = int(time.time())
            index[key] = entry
            save_index(root, index)
            return


def stats(root: str) -> dict:
    index = load_index(root)
    tag_count: dict[str, int] = {}
    for entry in index.values():
        if not isinstance(entry, dict):
            continue
        for tag in entry.get("tags") or []:
            tag_count[tag] = tag_count.get(tag, 0) + 1
    return {"total": len(index), "tags": tag_count}


def untagged(root: str) -> list[str]:
    index = load_index(root)
    return [os.path.join(root, e.get("file") or "") for e in index.values()
            if isinstance(e, dict) and not (e.get("tags") or [])]


def set_tags(root: str, path: str, tags) -> bool:
    """给一张表情打标签；某个情绪已经满 PER_TAG_CAP 张时不再往上加（免得刚标完就被裁）。"""
    index = load_index(root)
    for key, entry in index.items():
        if isinstance(entry, dict) and os.path.join(root, entry.get("file") or "") == path:
            counts = _counters(index)[1]
            own = _entry_tags(entry)
            picked = []
            for tag in tags or []:
                if tag not in ALL_TAGS:
                    continue
                if tag in own or counts.get(tag, 0) < PER_TAG_CAP:
                    picked = [tag]          # 一张图只归一个情绪，不重复占名额
                    break
            entry["tags"] = picked
            index[key] = entry
            save_index(root, index)
            return True
    return False


def get_entry(root: str, key: str) -> dict:
    """取一条索引记录（不存在返回空 dict）。"""
    entry = load_index(root).get(str(key))
    return entry if isinstance(entry, dict) else {}


def set_fav(root: str, key: str, ok: bool) -> None:
    """记下这张有没有进 QQ 收藏表情，免得每次收藏都去重试一遍。"""
    index = load_index(root)
    entry = index.get(str(key))
    if not isinstance(entry, dict):
        return
    entry["fav"] = bool(ok)
    entry["fav_at"] = int(time.time())
    index[str(key)] = entry
    save_index(root, index)


__all__ = [
    "ALL_TAGS", "TAG_BY_DIM", "add_bytes", "add_file", "load_index", "mark_used",
    "get_entry", "pick", "root_dir", "save_index", "set_tags", "set_fav", "stats",
    "tag_of", "untagged", "rebalance", "is_saturated", "PER_TAG_CAP", "MAX_ITEMS",
]
