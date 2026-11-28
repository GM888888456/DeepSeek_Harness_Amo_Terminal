# -*- coding: utf-8 -*-
"""自我形象档案：让她认得自己的脸。

为什么需要这个文件
------------------
以前每出一张图只留一张 `photo_cache/panel_last.jpg`，下一张直接覆盖。
所以「他把她拍的照片发回来」时，系统手里：

    * 没有那张图（早已被覆盖）；
    * 只有一条 7～14 天就会淡掉的 `photo_record` 文字；
    * 视觉模型看到的是像素，检索拿到的是文字，两边没有任何共同的标识。

结果就是她问「这是谁」。

这里补上三件事
--------------
1. **永久存档**：每张出图按 id 落盘，一张都不覆盖，索引写 `self_photos/index.json`；
2. **指纹比对**：整图 + 一组取景窗口的 64 位感知哈希（dHash / aHash）。
   他发回来的图哪怕被重新压过、缩过、裁过、加过白边，也能认回原档；
3. **长相事实**：`appearance()` 给出 Core_Appearance，生图提示词强制带头，
   终端也会把同一段写进永久记忆（kind=identity）。

刻意不做的事
------------
* 不引入人脸识别模型（onnxruntime 在这台 3.8G 内存的机器上不值得；
  她的照片全是同一套提示词体系生成的，哈希 + 长相事实已经够用）；
* 不删档：除非超过 `self_face_archive_max` 张，且只按时间从最老的删。
"""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import threading
import time
import urllib.request

try:  # 图像处理是硬依赖，缺了就让调用方自己兜底
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None  # type: ignore

#: 入站图片大小上限（和 draw_engine 的 localize_image 保持一致）
MAX_IMAGE_BYTES = 16 * 1024 * 1024

#: 默认容差：64 位里允许 12 位不同。重新压缩/缩放一般 0～8，不同场景约 25～35。
DEFAULT_MAX_DISTANCE = 12

#: 默认最多留多少张（约 0.5MB/张 → 1500 张约 750MB）
DEFAULT_ARCHIVE_MAX = 1500

#: 取景窗口（左、上、右、下，按整图比例）。第一个必须是整图。
#: 之所以要这么多窗口：他常把照片截图、裁掉一边、或者存下来再发回去，
#: 这时整图哈希会整体漂掉，但「同一个画面的一块区域」还能对上。
_WINDOWS = (
    (0.00, 0.00, 1.00, 1.00),   # 整图
    (0.06, 0.06, 0.94, 0.94),   # 中心 88%
    (0.12, 0.12, 1.00, 1.00),   # 靠右下 88%
    (0.00, 0.00, 0.88, 0.88),   # 靠左上 88%
    (0.12, 0.00, 1.00, 0.88),   # 右上
    (0.00, 0.12, 0.88, 1.00),   # 左下
    (0.10, 0.10, 1.00, 1.00),   # 裁掉左边和上边各 10%
    (0.00, 0.00, 1.00, 0.80),   # 裁掉底部 20%
    (0.00, 0.20, 1.00, 1.00),   # 裁掉顶部 20%
    (0.00, 0.00, 0.80, 1.00),   # 裁掉右边 20%
    (0.125, 0.125, 0.875, 0.875),  # 中心 75%
    (0.18, 0.18, 0.82, 0.82),   # 中心 64%
)

_LOCK = threading.Lock()
_CACHE = {"path": "", "mtime": 0.0, "rows": []}

#: Core_Appearance 兜底值：只在配置里没写 `core_appearance` / `character_appearance` 时用。
#: 只是一张「通用默认脸」，不指向任何具体的人——装插件的人应该自己填长相；
#: 兜底只保证开箱能出图，不保证像谁。
DEFAULT_APPEARANCE = "20岁，中等身高，偏瘦，黑色长发及腰，自然披肩，深棕色眼睛，皮肤干净"


#: 生图时必须强制写进提示词的核心特征（顺序固定，方便 diff）
CORE_FIELDS = ("发色", "瞳色", "脸型", "身高", "体型", "标志性特征")


# ------------------------------------------------------------------ 目录与索引

def plugin_data_dir(plugin) -> str:
    """插件数据目录（不写插件安装目录、不写 cwd）。"""
    getter = getattr(plugin, "_plugin_data_dir", None)
    if callable(getter):
        try:
            base = str(getter() or "")
            if base:
                return base
        except Exception:
            pass
    plugin_dir = str(getattr(plugin, "plugin_dir", "") or "")
    parent = os.path.dirname(plugin_dir) if plugin_dir else ""
    name = os.path.basename(plugin_dir) or "DeepSeek_Harness_Amo_Image"
    if parent and os.path.basename(parent) == "plugins":
        return os.path.join(os.path.dirname(parent), "plugin_data", name)
    return os.path.join(os.getcwd(), "plugin_data", name)


def archive_dir(plugin) -> str:
    path = os.path.join(plugin_data_dir(plugin), "photo_cache", "self_photos")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception:
        pass
    return path


def index_path(plugin) -> str:
    return os.path.join(archive_dir(plugin), "index.json")


def _load_index(plugin) -> list:
    path = index_path(plugin)
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        return []
    if _CACHE["path"] == path and _CACHE["mtime"] == mtime:
        return _CACHE["rows"]
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if isinstance(data, dict):
            data = data.get("photos") or []
        rows = [row for row in data if isinstance(row, dict) and row.get("file")]
    except Exception:
        rows = []
    _CACHE["path"] = path
    _CACHE["mtime"] = mtime
    _CACHE["rows"] = rows
    return rows


def _save_index(plugin, rows: list) -> None:
    path = index_path(plugin)
    tmp = path + ".tmp"
    payload = {"version": 2, "updated": int(time.time()), "photos": rows}
    try:
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass
    try:
        _CACHE["mtime"] = os.path.getmtime(path)
    except Exception:
        _CACHE["mtime"] = 0.0
    _CACHE["path"] = path
    _CACHE["rows"] = rows


def archive_max(plugin) -> int:
    try:
        value = int(getattr(plugin, "_int", lambda k, d: d)("self_face_archive_max", DEFAULT_ARCHIVE_MAX))
    except Exception:
        value = DEFAULT_ARCHIVE_MAX
    return max(50, value)


# ------------------------------------------------------------------ 指纹

def _bits_to_hex(bits: int, size: int = 8) -> str:
    return format(bits, "0%dx" % ((size * size) // 4))


def _dhash(img, size: int = 8) -> int:
    small = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(small.getdata())
    bits = 0
    for row in range(size):
        base = row * (size + 1)
        for col in range(size):
            bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
    return bits


def _ahash(img, size: int = 8) -> int:
    small = img.convert("L").resize((size, size), Image.LANCZOS)
    px = list(small.getdata())
    avg = sum(px) / float(len(px) or 1)
    bits = 0
    for value in px:
        bits = (bits << 1) | (1 if value > avg else 0)
    return bits


def _window_hashes(img) -> list:
    """一张图 → 各取景窗口的 64 位指纹（[dh, ah] 十六进制）。"""
    width, height = img.size
    out = []
    for left, top, right, bottom in _WINDOWS:
        x0 = max(0, min(width - 8, int(width * left)))
        y0 = max(0, min(height - 8, int(height * top)))
        x1 = max(x0 + 8, min(width, int(width * right)))
        y1 = max(y0 + 8, min(height, int(height * bottom)))
        tile = img.crop((x0, y0, x1, y1))
        out.append([_bits_to_hex(_dhash(tile)), _bits_to_hex(_ahash(tile))])
    return out


def hash_image(raw: bytes):
    """图片字节 → {'dh','ah','dhc','wins'}；失败返回 None。

    dh/ah 是整图，dhc 是中心 88%（老版本就存了这个，留着兼容），
    wins 是所有取景窗口的指纹，认裁剪过的图靠它。
    """
    if not raw or Image is None:
        return None
    try:
        with Image.open(io.BytesIO(raw)) as img:
            img = img.convert("RGB")
            width, height = img.size
            if width < 8 or height < 8:
                return None
            wins = _window_hashes(img)
            mx = int(width * 0.06)
            my = int(height * 0.06)
            dhc = _dhash(img.crop((mx, my, width - mx, height - my)))
            return {"dh": wins[0][0], "ah": wins[0][1],
                    "dhc": _bits_to_hex(dhc), "wins": wins}
    except Exception:
        return None


def hamming(hex_a: str, hex_b: str) -> int:
    try:
        return bin(int(str(hex_a), 16) ^ int(str(hex_b), 16)).count("1")
    except Exception:
        return 64


# ------------------------------------------------------------------ 读入站图片

def image_bytes_from_any(source) -> bytes:
    """把「他发来的那张图」变成字节：data URL / base64:// / http(s) / 本地路径都认。"""
    if not source:
        return b""
    if isinstance(source, (bytes, bytearray)):
        return bytes(source)
    text = str(source).strip()
    if not text:
        return b""
    try:
        if text.startswith("base64://"):
            import base64

            return base64.b64decode(text[len("base64://"):])
        if text.startswith("data:"):
            import base64

            head, _, payload = text.partition(",")
            if "base64" in head[:64]:
                return base64.b64decode(payload)
            return b""
        if text.startswith("file://"):
            text = text[len("file://"):]
        if text.startswith("http://") or text.startswith("https://"):
            with urllib.request.urlopen(text, timeout=20) as response:
                payload = response.read(MAX_IMAGE_BYTES + 1)
            return payload if len(payload) <= MAX_IMAGE_BYTES else b""
        if os.path.exists(text):
            if os.path.getsize(text) > MAX_IMAGE_BYTES:
                return b""
            with open(text, "rb") as handle:
                return handle.read()
    except Exception:
        return b""
    return b""


# ------------------------------------------------------------------ 存档与比对

def _now_text(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))


#: 这些是提示词里的技术词/内胆，不能出现在她看到的句子里（她会照念）
_PROMPT_NOISE = (
    "手机前置摄像头", "前置摄像头", "自然光", "生活感", "超写实", "高清", "8k", "4k",
    "手机本身不入镜", "画面里的就是她本人", "这是一张自拍",
    "（看不到手机）", "机位、构图、姿势、表情随当下场景自然发挥",
    "机位", "构图", "姿势", "表情",
)


def scene_brief(prompt, limit: int = 60) -> str:
    """把出图提示词压成一句人话：去掉【…】内胆和技术词。

    2026-11-15：原来直接把 prompt 塞给她，结果上下文里出现
    「画面：【这是一张自拍】手机前置摄像头，画面里的就是她本人…」，她容易照念。
    """
    text = re.sub(r"【[^】]*】", "", str(prompt or ""))
    text = text.split("；")[0]           # 后半段多是技术约束，不要
    for word in _PROMPT_NOISE:
        text = text.replace(word, "")
    text = re.sub(r"\s+", "", text)
    text = re.sub(r"[，,：:]{2,}", "，", text)
    text = re.sub(r"[，,]{2,}", "，", text)
    text = text.strip(" ，,。;；：:、")
    return text[:limit]


def age_text(ts) -> str:
    """相对时间。她说「才发多久啊」的时候，是因为提示词只给了绝对日期。"""
    try:
        age = max(0.0, time.time() - float(ts))
    except Exception:
        return ""
    if age < 300:
        return "就在刚刚"
    if age < 3600:
        return "%d 分钟前" % int(age // 60)
    if age < 86400:
        return "%d 小时前" % int(age // 3600)
    return "%d 天前" % int(age // 86400)


def describe(ts: float, label: str, outfit: str, place: str, activity: str, prompt: str) -> str:
    """[自我形象记忆：2026-11-15 18:00，我在家穿着白色吊带裙，给自己拍了张照。]"""
    head = "[自我形象记忆：%s，" % _now_text(ts)
    body = "我"
    if place:
        body += "在" + place
    if outfit:
        body += "穿着" + outfit
    body += "，给自己拍了张%s" % (label or "照")
    if activity:
        body += "（那会儿在%s）" % str(activity)[:24]
    text = head + body + "。"
    shot = scene_brief(prompt, 60)
    if shot:
        text += "画面：%s。" % shot
    return text + "]"


def archive(plugin, raw, prompt: str = "", place: str = "", activity: str = "",
            outfit: str = "", label: str = "自拍", kind: str = "self", ts: float = 0.0):
    """把一张出图永久存档，返回索引条目；同一张图短时间内重复调用只记一次。

    ts 不给就用当前时间；补录旧照片（比如把以前面板那张补进档案）时传拍摄时间。
    """
    if not raw:
        return None
    hashes = hash_image(raw)
    if not hashes:
        return None
    ts = float(ts or 0) or time.time()
    rows = list(_load_index(plugin))
    with _LOCK:
        # 同一张（同字节数 + 指纹几乎一致）在 15 分钟内不重复入库
        for row in reversed(rows[-200:]):
            try:
                if ts - float(row.get("ts") or 0) > 900:
                    break
            except Exception:
                continue
            if int(row.get("bytes") or 0) != len(raw):
                continue
            if hamming(hashes["dh"], row.get("dh")) <= 2:
                return row
        photo_id = time.strftime("%Y%m%d-%H%M%S", time.localtime(ts)) + "-" + \
            hashlib.sha1(raw).hexdigest()[:8]
        folder = archive_dir(plugin)
        path = os.path.join(folder, photo_id + ".jpg")
        try:
            tmp = path + ".tmp"
            with open(tmp, "wb") as handle:
                handle.write(raw)
            os.replace(tmp, path)
        except Exception:
            return None
        row = {
            "id": photo_id,
            "ts": ts,
            "date": _now_text(ts),
            "file": photo_id + ".jpg",
            "bytes": len(raw),
            "label": str(label or "自拍"),
            "kind": str(kind or "self"),
            "outfit": str(outfit or ""),
            "place": str(place or ""),
            "activity": str(activity or ""),
            "prompt": str(prompt or "")[:400],
            "text": describe(ts, label, outfit, place, activity, prompt),
            "dh": hashes["dh"],
            "ah": hashes["ah"],
            "dhc": hashes["dhc"],
            "wins": hashes["wins"],
        }
        rows.append(row)
        limit = archive_max(plugin)
        dropped = []
        while len(rows) > limit:
            dropped.append(rows.pop(0))
        _save_index(plugin, rows)
        for old in dropped:
            try:
                os.remove(os.path.join(folder, str(old.get("file") or "")))
            except Exception:
                pass
        return row


def _row_windows(row) -> list:
    """档案条目的取景窗口；老版本条目没有 wins，就用整图 + 中心裁切凑。"""
    wins = row.get("wins")
    if isinstance(wins, list):
        out = [[str(w[0]), str(w[1])] for w in wins
               if isinstance(w, (list, tuple)) and len(w) >= 2]
        if out:
            return out
    return [[row.get("dh"), row.get("ah")]]


def match(plugin, raw, max_distance: int = 0) -> dict:
    """他发来的图 → 档案里对应的那张（含 distance）；认不出返回 {}。

    两条路一起走：
      * 入站整图 ↔ 档案的每个取景窗口（他裁过、截过图）；
      * 入站每个取景窗口 ↔ 档案整图（他加了边框、拼了长图）。
    """
    if not raw:
        return {}
    hashes = hash_image(raw)
    if not hashes:
        return {}
    limit = int(max_distance or 0)
    if limit <= 0:
        try:
            limit = int(getattr(plugin, "_int", lambda k, d: d)("self_face_max_distance", DEFAULT_MAX_DISTANCE))
        except Exception:
            limit = DEFAULT_MAX_DISTANCE
    limit = max(2, min(24, limit))
    ah_gate = min(24, limit + 8)
    in_full = [hashes["dh"], hashes["ah"]]
    in_wins = hashes["wins"]
    best = {}
    best_score = 999
    for row in _load_index(plugin):
        found = 999
        found_ah = 999
        for dh, ah in _row_windows(row):
            score = hamming(in_full[0], dh)
            if score <= limit:
                ah_dist = hamming(in_full[1], ah)
                if ah_dist <= ah_gate and score < found:
                    found, found_ah = score, ah_dist
        for dh, ah in in_wins:
            score = hamming(dh, row.get("dh"))
            if score <= limit:
                ah_dist = hamming(ah, row.get("ah"))
                if ah_dist <= ah_gate and score < found:
                    found, found_ah = score, ah_dist
        if found <= limit and found_ah <= ah_gate and found < best_score:
            best_score = found
            best = dict(row)
    if best:
        best["distance"] = best_score
    return best


def photo_file(plugin, row) -> str:
    if not isinstance(row, dict):
        return ""
    path = os.path.join(archive_dir(plugin), str(row.get("file") or ""))
    return path if os.path.exists(path) else ""


def recent(plugin, count: int = 3) -> list:
    rows = _load_index(plugin)
    return rows[-max(1, int(count or 1)):]


# ------------------------------------------------------------------ 长相事实

def appearance(plugin) -> str:
    """Core_Appearance：生图提示词与自我认知共用同一段话。"""
    for key in ("core_appearance", "character_appearance"):
        try:
            value = str(getattr(plugin, "_cfg", lambda k, d=None: d)(key, "") or "").strip()
        except Exception:
            value = ""
        if value:
            return value
    return DEFAULT_APPEARANCE


def appearance_line(plugin) -> str:
    """给提示词用的强制特征行（生图侧拼进最终提示词最前面）。"""
    text = appearance(plugin)
    return "同一个人（务必保持）：%s" % text


def identity_clause(plugin) -> str:
    """给终端注入用的「我是谁 / 我长什么样」。不依赖任何会被淡掉的记忆。

    ⚠️ 措辞很关键（2026-11-15 踩过）：早先写过「不管隔了多久、不管那天的细节
    你记不记得」，模型当场顺着说出「我自己都快认不出来了」——她本来认得，
    是提示词在暗示她忘。认脸不需要回忆，这里只讲事实，不讲遗忘。
    """
    text = appearance(plugin)
    return (
        "【你的样子·事实】你的长相是：%s。"
        "照片里长这样的女孩，就是你本人。你认得自己的脸，看到就认得——"
        "认脸不需要回忆是哪天拍的。他把你发出去的照片再发回来，那还是你，不是别人。"
        "不要问「这是谁」，也不要说「快认不出来了 / 差点没认出来」这类话。"
        % text
    )


def remember_clause(row, plugin=None) -> str:
    """认出来之后注入的事实句：哪一张、什么时候、穿什么、在哪儿。"""
    if not isinstance(row, dict) or not row:
        return ""
    date = str(row.get("date") or "")
    outfit = str(row.get("outfit") or "")
    place = str(row.get("place") or "")
    bits = []
    if date:
        bits.append(date)
    if place:
        bits.append("在" + place)
    if outfit:
        bits.append("穿" + outfit)
    label = str(row.get("label") or "照片")
    age = age_text(row.get("ts"))
    when = date + (("（%s）" % age) if age else "")
    scene = ""
    if place:
        scene += "在" + place
    if outfit:
        scene += ("，" if scene else "") + "穿" + outfit
    brief = "" if scene else scene_brief(row.get("prompt"), 40)
    tail = ""
    try:
        if time.time() - float(row.get("ts") or 0) < 12 * 3600:
            tail = "这张一点都不旧，就是最近的事。"
    except Exception:
        tail = ""
    body = "【他发回来的就是你自己】他这张图就是你自己拍的：%s。" % when
    if scene:
        body += "那会儿你%s。" % scene
    if brief:
        body += "（画面：%s）" % brief
    return (
        body + "照片里的人是你本人，不是别人。%s"
        "可以按你自己的感觉反应（比如「这张腿拍得好长」「怎么把我拍得这么呆」），"
        "不要问「这是谁」，也不要说「快认不出来了」。"
        % tail
    )