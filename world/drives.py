# -*- coding: utf-8 -*-
"""驱动层：她的五个内驱值，会自己涨落，也会被外部事件推动。

用户口径（2026-11-26）：「让他像人一样有驱动」「不设配额，全套做完整」。

五个驱动（0~100）：
- boredom   无聊：闲着就涨，做了新事情就掉
- curiosity 好奇：长时间没新鲜输入会涨，看了新东西就掉
- social    社交欲：他多久没说话就涨，聊过就掉
- control   掌控欲（总裁身份）：公司有悬而未决的事就涨，拍板了就掉
- valued    被在意感：他回应/夸她就涨，被忽视就掉

设计边界：
- **只管数值**，不直接发消息；行为由 intents 层决定（见 world/intents.py）；
- 落盘 `plugin_data/.../drives.json`，断网/重启不丢；
- 所有函数都是纯加减 + 夹紧，不做业务判断（和当年心流的教训一致）。
"""

from __future__ import annotations

import json
import os
import time

DRIVES = ("boredom", "curiosity", "social", "control", "valued")

CN = {
    "boredom": "无聊",
    "curiosity": "好奇",
    "social": "想他",
    "control": "掌控欲",
    "valued": "被在意",
}

#: 每个驱动每小时的自然变化（醒着时）。正数=会涨
PER_HOUR = {
    "boredom": 7.0,
    "curiosity": 4.5,
    "social": 6.0,
    "control": 3.0,
    "valued": -2.0,     # 不联系就慢慢觉得被冷落
}

DEFAULT = {"boredom": 42, "curiosity": 55, "social": 40, "control": 52, "valued": 58}


def _data_path():
    for base in ("/AstrBot/data/plugin_data/DeepSeek_Harness_Amo_Terminal",
                 "/data/astrbot/plugin_data/DeepSeek_Harness_Amo_Terminal",
                 os.path.join(os.path.dirname(os.path.abspath(__file__)), ".data")):
        try:
            os.makedirs(base, exist_ok=True)
            return os.path.join(base, "drives.json")
        except Exception:
            continue
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "drives.json")


_PATH = _data_path()


def _clamp(v):
    return max(0.0, min(100.0, float(v)))


def load():
    try:
        with open(_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception:
        data = {}
    out = {"ts": float(data.get("ts") or time.time()), "values": dict(DEFAULT),
           "last": dict(data.get("last") or {}), "log": list(data.get("log") or [])[-40:]}
    for name in DRIVES:
        try:
            out["values"][name] = _clamp((data.get("values") or {}).get(name, DEFAULT[name]))
        except Exception:
            out["values"][name] = DEFAULT[name]
    return out


def save(state):
    try:
        tmp = _PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, _PATH)
        return True
    except Exception:
        return False


def advance(state, now=None, sleeping=False, hours=None):
    """按流逝时间推进数值（醒着才涨；睡着只轻微回落）。"""
    now = float(now or time.time())
    last = float(state.get("ts") or now)
    dt_h = hours if hours is not None else max(0.0, (now - last) / 3600.0)
    if dt_h <= 0:
        state["ts"] = now
        return state
    factor = 0.15 if sleeping else 1.0
    for name in DRIVES:
        delta = PER_HOUR.get(name, 0.0) * dt_h * factor
        state["values"][name] = _clamp(state["values"][name] + delta)
    state["ts"] = now
    return state


def bump(state, name, delta, reason=""):
    """外部事件推一把：他说话了、被夸了、看了新东西……"""
    if name not in DRIVES:
        return state
    state["values"][name] = _clamp(state["values"][name] + float(delta))
    if reason:
        state.setdefault("log", []).append({"ts": time.time(), "name": name,
                                           "delta": float(delta), "why": reason[:40]})
        state["log"] = state["log"][-40:]
    return state


def on_his_message(state, praised=False):
    """他发消息：社交欲掉、被在意感涨；夸了就再涨一点。"""
    bump(state, "social", -14, "他说话了")
    bump(state, "valued", 6 if praised else 3, "他理我了")
    if praised:
        bump(state, "valued", 6, "他夸我")
    return state


def on_ignored(state, minutes):
    """我主动说了但他没回：社交欲涨、被在意感掉（有上限，别一次跌光）。"""
    bump(state, "social", min(12.0, 2.0 + minutes * 0.05), "他没回")
    bump(state, "valued", -min(9.0, 3.0 + minutes * 0.03), "他没回")
    return state


def on_new_thing(state):
    """看了新东西：好奇和无聊都掉。"""
    bump(state, "curiosity", -18, "看了新东西")
    bump(state, "boredom", -12, "看了新东西")
    return state


def on_acted(state, intent="", cost=None):
    """做了点事（出门/说话/拍照）：对应驱动回落。"""
    table = {
        "go_outside": (("boredom", -16), ("curiosity", -6)),
        "talk_to_him": (("social", -20), ("valued", 2)),
        "send_photo": (("social", -12), ("valued", 3)),
        "push_company": (("control", -22),),
    }
    for name, delta in table.get(str(intent), ()):
        bump(state, name, delta, "做了：%s" % intent)
    return state


def top(state, n=2):
    """最强的几个驱动（面板与上下文用）。"""
    items = sorted(((name, state["values"][name]) for name in DRIVES),
                   key=lambda kv: -kv[1])
    return items[:n]


def describe(state):
    """一句人话：她现在最想要什么。"""
    return "、".join("%s %.0f" % (CN.get(k, k), v) for k, v in top(state, 3))


def line(state, threshold=62):
    """给上下文的一行；都在阈值以下就不给（省 token）。"""
    strong = [(k, v) for k, v in top(state, 3) if v >= threshold]
    if not strong:
        return ""
    want = {
        "boredom": "有点闷，想找点事做",
        "curiosity": "对什么都有点兴趣，想去看两眼",
        "social": "想他，想找他说话",
        "control": "心里压着几件没定的事，想催一下",
        "valued": "有点在意他是不是没当回事",
    }
    parts = ["%s（%s）" % (want.get(k, k), CN.get(k, k)) for k, _ in strong]
    return "【此刻】" + "；".join(parts) + "。想不想做点什么，你自己定。"
