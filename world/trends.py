# -*- coding: utf-8 -*-
"""趋势库：今天网上在聊什么（B 站热门 + 贴吧热榜，尽力而为）。

用户口径（2026-11-26）：「哔哩哔哩那些贴吧鱼那么聪明，是不是接入贴吧会更好？
毕竟提示词约束犹如狗被拴着狗链子」——与其把提示词捆得更紧，不如给她一点**外面的事**。

设计约束：
- **只拿标题**，不拿正文：她只需要知道「大家在聊这个」，细节她本来也说不清；
- **明确告诉她「你只看到标题」**，防止编内容（比不知道更糟的是瞎编）；
- 每 6 小时刷一次，落盘缓存，断网/超时就用旧缓存，绝不影响回复；
- 网络请求只在后台线程/心跳里做，不进消息链路。
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
TTL = 6 * 3600


def _data_path():
    for base in ("/AstrBot/data/plugin_data/DeepSeek_Harness_Amo_Terminal",
                 "/data/astrbot/plugin_data/DeepSeek_Harness_Amo_Terminal",
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), ".data")):
        try:
            os.makedirs(base, exist_ok=True)
            return os.path.join(base, "trends.json")
        except Exception:
            continue
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "trends.json")


_PATH = _data_path()


def _get(url, timeout=8):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Referer": "https://www.bilibili.com/",
        "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", "ignore")


def fetch_bili(limit=8):
    try:
        raw = _get("https://api.bilibili.com/x/web-interface/popular?ps=%d&pn=1" % max(1, limit))
        data = json.loads(raw)
        items = []
        for row in (data.get("data") or {}).get("list", [])[:limit]:
            title = str(row.get("title") or "").strip()
            owner = str((row.get("owner") or {}).get("name") or "").strip()
            if title:
                items.append({"title": title, "from": "B站", "by": owner})
        return items
    except Exception:
        return []


def fetch_tieba(limit=6):
    """贴吧热榜：只认能解析出来的标题，解析失败就返回空。"""
    try:
        raw = _get("https://tieba.baidu.com/hottopic/browse/topicList")
    except Exception:
        return []
    items = []
    # 接口/页面都试：有的是 JSON 字段 topic_name，有的是 HTML 里的 topic-text
    for pattern in (r'"topic_name"\s*:\s*"([^"]{4,60})"',
                    r'class="topic-text[^"]*"[^>]*>([^<]{4,60})<'):
        for name in re.findall(pattern, raw):
            name = name.strip()
            if not name or name in [i["title"] for i in items]:
                continue
            items.append({"title": name, "from": "贴吧", "by": ""})
            if len(items) >= limit:
                return items
    return items


def load():
    try:
        with open(_PATH, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save(data):
    try:
        tmp = _PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, _PATH)
    except Exception:
        pass


def refresh(force=False):
    """拉一次热榜（带 TTL），返回是否真的刷新了。"""
    now = time.time()
    data = load()
    if not force and data.get("ts") and now - float(data["ts"]) < TTL:
        return False
    items = []
    try:
        items.extend(fetch_bili())
    except Exception:
        pass
    try:
        items.extend(fetch_tieba())
    except Exception:
        pass
    if not items:
        return False
    save({"ts": now, "items": items[:14]})
    return True


def block(limit=3):
    """给上下文的一小段：她只知道标题，不知道内容。"""
    data = load()
    items = data.get("items") or []
    if not items:
        return ""
    picks = items[:limit]
    lines = ["【今天网上在聊】（你只扫到标题，不知道具体内容，别编细节）"]
    for it in picks:
        by = ("（%s）" % it.get("by")) if it.get("by") else ""
        lines.append("- %s%s · %s" % (it.get("title"), by, it.get("from")))
    return "\n".join(lines)


def keywords(text):
    """消息里出现这些词，才注入热榜（省 token）。"""
    words = ("热搜", "热榜", "热门", "网上", "贴吧", "B站", "b站", "视频", "刷到",
             "梗", "段子", "最近在聊", "有什么新闻", "头条", "网友")
    return any(w in str(text or "") for w in words)
