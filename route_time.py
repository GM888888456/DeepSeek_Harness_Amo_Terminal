# -*- coding: utf-8 -*-
"""真实车程：地名 → 坐标（Nominatim），坐标 → 车程（OSRM），带离线兜底。

2026-11-26 用户口径：「从 A 点去 B 点视察，要花 X 时间，从 B 点回 A 点又要多久——
要有时间因果」。容器里实测：观山湖 → 贵安 = 27.4 分钟 / 28.1 公里。

设计约束：

* ``drive_minutes()`` **永远立即返回**：只读内置表 / 磁盘缓存，网络查询全部丢给
  后台线程（daemon），查到就写缓存，下次（以及当天的日程）就用真数。
* 查不到、没网、地名太含糊 → 按同城/异地估一个合理的分钟数，绝不返回 0。
* 缓存落 ``<插件目录>/data/route_cache.json``，30 天有效。
"""

from __future__ import annotations

import json
import math
import os
import threading
import time
import urllib.parse
import urllib.request

_TTL = 30 * 86400
_TIMEOUT = 6
_UA = "amo-schedule/1.0 (+serverbox)"

#: 地名关键词 → 查地图用的地址（越具体的排前面）
ALIASES = (
    ("贵安", "贵安新区"),
    ("观山湖", "贵阳 观山湖区"),
    ("智脑", "贵阳 观山湖区"),
    ("云岩", "贵阳 云岩区"),
    ("南明", "贵阳 南明区"),
    ("龙洞堡", "贵阳 龙洞堡机场"),
    ("机场", "贵阳 龙洞堡机场"),
    ("北站", "贵阳北站"),
    ("东站", "贵阳东站"),
    ("京都", "日本 京都市"),
    ("东莞", "广东省 东莞市"),
    ("西湖", "杭州 西湖区"),
)

#: 已经查过的常见路线：(起点, 终点) → (分钟, 公里)。没网时靠它保住时间因果。
BAKED = {
    ("贵阳 观山湖区", "贵安新区"): (27, 28.1),
    ("贵安新区", "贵阳 观山湖区"): (27, 28.1),
}

#: 同一座城市里默认的市内通勤时间（分钟）
_SAME_CITY = 18
#: 两座城市之间没查到路线时的兜底（分钟）
_FAR_CITY = 150
#: 市区平均车速（公里/小时），用来把直线距离换成分钟
_SPEED = 26.0
#: 道路绕行系数：直线距离 ×1.35 ≈ 实际里程
_DETOUR = 1.35

_LOCK = threading.Lock()
_CACHE = None
_INFLIGHT = set()


# ------------------------------------------------------------------ 缓存

def _cache_path() -> str:
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    try:
        os.makedirs(base, exist_ok=True)
    except Exception:
        pass
    return os.path.join(base, "route_cache.json")


def _load() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    data = {"geo": {}, "route": {}}
    try:
        with open(_cache_path(), encoding="utf-8") as fh:
            raw = json.load(fh)
        if isinstance(raw, dict):
            data["geo"] = dict(raw.get("geo") or {})
            data["route"] = dict(raw.get("route") or {})
    except Exception:
        pass
    _CACHE = data
    return _CACHE


def _save() -> None:
    try:
        path = _cache_path()
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_CACHE or {"geo": {}, "route": {}}, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception:
        pass


# ------------------------------------------------------------------ 地名

def _plain(place: str) -> str:
    """去掉「·/（）」尾巴和空白，只留地名主干，用来比两处是不是同一处。"""
    text = str(place or "").strip()
    for tail in ("会议室", "会客室", "门口", "附近", "楼下", "工位", "前台", "食堂",
                 "走廊", "车库", "停车场", "路边"):
        if text.endswith(tail):
            text = text[:-len(tail)]
    return text.replace(" ", "").strip("·/")


def query_for(place: str, city: str = "") -> str:
    """「贵安机房」→「贵安新区」；认不出来的名字带上城市再查一次。"""
    text = str(place or "").strip()
    if not text:
        return ""
    for word, query in ALIASES:
        if word in text:
            return query
    head = text.replace("·", "/").split("/")[0].strip()
    head = head.split("（")[0].strip() or text
    city = str(city or "").strip()
    if city and city not in head:
        return "%s %s" % (city, head)
    return head


def _city_of(place: str) -> str:
    text = str(place or "")
    for word, query in ALIASES:
        if word in text:
            return query.split(" ")[0]
    return ""


def _same_area(a: str, b: str) -> bool:
    qa, qb = query_for(a), query_for(b)
    if qa and qa == qb:
        return True
    return bool(_city_of(a)) and _city_of(a) == _city_of(b)


# ------------------------------------------------------------ 网络（后台）

def _http_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _geocode(query: str):
    """地址 → (lat, lon)；按查询串缓存。查不到返回 None。"""
    if not query:
        return None
    cache = _load()
    with _LOCK:
        hit = cache["geo"].get(query)
    if hit:
        return tuple(hit)
    try:
        url = ("https://nominatim.openstreetmap.org/search?format=json&limit=1&q="
               + urllib.parse.quote(query))
        rows = _http_json(url)
        if not rows:
            return None
        lat, lon = float(rows[0]["lat"]), float(rows[0]["lon"])
    except Exception:
        return None
    with _LOCK:
        cache["geo"][query] = [lat, lon]
        _save()
    return lat, lon


def _route(origin: str, dest: str):
    """两个地址 → (分钟, 公里)；查不到返回 None。"""
    a = _geocode(origin)
    if not a:
        return None
    time.sleep(1.0)          # Nominatim 限速：一秒一次
    b = _geocode(dest)
    if not b:
        return None
    try:
        url = ("https://router.project-osrm.org/route/v1/driving/%s,%s;%s,%s?overview=false"
               % (a[1], a[0], b[1], b[0]))
        data = _http_json(url)
        route = (data.get("routes") or [None])[0]
        if not route:
            return None
        return (round(float(route["duration"]) / 60.0, 1),
                round(float(route["distance"]) / 1000.0, 1))
    except Exception:
        return None


def _prefetch(origin: str, dest: str) -> None:
    key = "%s|%s" % (origin, dest)
    with _LOCK:
        if key in _INFLIGHT:
            return
        _INFLIGHT.add(key)
    try:
        got = _route(origin, dest)
        if got:
            cache = _load()
            with _LOCK:
                cache["route"][key] = {"minutes": got[0], "km": got[1], "ts": time.time()}
                _save()
    finally:
        with _LOCK:
            _INFLIGHT.discard(key)


def _spawn(origin: str, dest: str) -> None:
    try:
        threading.Thread(target=_prefetch, args=(origin, dest), daemon=True).start()
    except Exception:
        pass


# ------------------------------------------------------------ 查询入口

def _estimate(origin: str, dest: str):
    """没查到路线时的估算：有坐标就按直线距离，没有就按同城/异地。"""
    cache = _load()
    a = cache["geo"].get(origin)
    b = cache["geo"].get(dest)
    if a and b:
        lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        h = (math.sin(dlat / 2) ** 2
             + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
        km = 2 * 6371.0 * math.asin(math.sqrt(max(0.0, min(1.0, h)))) * _DETOUR
        return max(8.0, round(km / _SPEED * 60.0, 1)), round(km, 1)
    if _same_area(origin, dest):
        return float(_SAME_CITY), 0.0
    return float(_FAR_CITY), 0.0


def drive_minutes(origin: str, dest: str, city: str = "", background: bool = True):
    """两地开车要多久 → (分钟, 公里)。**立即返回**，网络查询在后台补。"""
    a = query_for(origin, city)
    b = query_for(dest, city)
    if a and b and a == b:
        # 同一个片区、查出来是同一个地址：分清「就在隔壁」和「同区两处」
        x, y = _plain(origin), _plain(dest)
        if x == y or (x and y and (x in y or y in x)):
            return 0.0, 0.0
        prefix = 0
        for c1, c2 in zip(x, y):
            if c1 != c2:
                break
            prefix += 1
        return (8.0, 0.0) if prefix >= 2 else (15.0, 0.0)
    if not a or not b:
        return 0.0, 0.0
    baked = BAKED.get((a, b))
    if baked:
        return float(baked[0]), float(baked[1])
    key = "%s|%s" % (a, b)
    cache = _load()
    hit = cache["route"].get(key)
    if hit and (time.time() - float(hit.get("ts") or 0)) < _TTL:
        return float(hit.get("minutes") or 0), float(hit.get("km") or 0)
    if background:
        _spawn(a, b)
        if "%s|%s" % (b, a) not in cache["route"]:
            _spawn(b, a)
    return _estimate(a, b)


def facts_line(origin: str, dest: str, city: str = "") -> str:
    """给上下文/提示词用的一句话事实。"""
    minutes, km = drive_minutes(origin, dest, city=city)
    if minutes <= 0:
        return ""
    tail = "，约 %.0f 公里" % km if km else ""
    return "从%s到%s开车约 %d 分钟%s" % (origin, dest, int(round(minutes)), tail)
