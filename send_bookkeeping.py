# -*- coding: utf-8 -*-
"""守护把话发出去之后，终端这边的收尾动作。

分段引擎拆掉后，这四件事只剩一份实现：
关打字状态、写会话历史、写自己的消息表、通知心流「这一轮回过了」。
"""

from __future__ import annotations

import asyncio
import json
import random
import time

from astrbot.api import logger


async def set_typing(event, typing: bool) -> None:
    """已停用：TIM / 新版 QQ 不再显示「对方正在输入」，她会显得像机器人。

    2026-11-21 她的原话：「不要正在输入这个啊？Tim 和很多版本都没有这个了」。
    这里保留空实现，免得别处的调用报错；群里/私聊都只靠停顿模拟打字。
    """
    return None


def typing_seconds(plugin, text, min_seconds=0.6, max_seconds=12.0) -> float:
    """按这一段自己的字数算「打完这段话要多久」，只算不睡。

    · 基础 700ms + 每字 400ms + 标点补一点（都来自配置 typing_*）；
    · 随机 ±25%，别让每次间隔都一样——固定节奏最容易露馅；
    · 上下限 min_seconds ~ max_seconds（默认 0.6~12 秒，不再统一卡 8 秒）。
    """
    try:
        base = int(float(plugin.cfg_int("typing_base_ms", 700)))
        per_char = int(float(plugin.cfg_int("typing_per_char_ms", 400)))
        cap_ms = int(float(plugin.cfg_int("typing_max_ms", 20000)))
    except Exception:
        base, per_char, cap_ms = 700, 400, 20000
    clean = "".join(str(text or "").split())
    if not clean:
        return 0.0
    pauses = sum(clean.count(ch) for ch in ("。", "！", "？", "!", "?", "…"))
    commas = sum(clean.count(ch) for ch in ("，", ",", "、"))
    value = min(base + len(clean) * per_char + pauses * 70 + commas * 35, cap_ms)
    value *= random.uniform(0.75, 1.25)
    return max(min_seconds, min(max_seconds, value / 1000.0))


async def typing_pause(plugin, event, text, min_seconds=0.6, max_seconds=12.0,
                       first_delay=0.0) -> float:
    """模拟「正在打字」的停顿（不点亮「正在输入」），返回实际停了几秒。

    2026-11-21：守护插件不在部署里，`guard_bridge` 的 typing 任务从没有执行者，
    群聊回复又是一整段 —— 所以这里补终端自带的实现。只停，不发任何状态。
    """
    try:
        enable = getattr(plugin, "cfg_bool", None)
        if callable(enable) and not enable("typing_simulate", True):
            return 0.0
    except Exception:
        pass
    seconds = typing_seconds(plugin, text, min_seconds, max_seconds)
    if seconds <= 0:
        return 0.0
    await asyncio.sleep(max(0.0, float(first_delay or 0.0)) + seconds)
    return seconds


async def save_to_conversation_history(context, event, content: str) -> None:
    """把合并后的完整回复写进对话历史，保证上下文连贯。"""
    try:
        conv_mgr = getattr(context, "conversation_manager", None)
        if not conv_mgr:
            return
        umo = event.unified_msg_origin
        curr_cid = await conv_mgr.get_curr_conversation_id(umo)
        if not curr_cid:
            return
        conversation = await conv_mgr.get_conversation(umo, curr_cid)
        if not conversation:
            return
        try:
            history = json.loads(conversation.history) if isinstance(conversation.history, str) else conversation.history
        except (json.JSONDecodeError, TypeError):
            history = []
        user_content = getattr(event, "message_str", "")
        if user_content and (not history or history[-1].get("role") != "user"):
            history.append({"role": "user", "content": user_content})
        history.append({"role": "assistant", "content": content})
        await conv_mgr.update_conversation(
            unified_msg_origin=umo,
            conversation_id=curr_cid,
            history=history,
        )
    except Exception as exc:
        logger.error("[amo] 保存对话历史失败: %s" % exc)


def notify_heartflow(plugin, event, text: str = "") -> None:
    """手工发送后主动清除「判断暂停」，否则她会哑到超时。"""
    return  # 心流已删除，没有需要清的状态


async def after_external_send(plugin, event, text: str) -> None:
    """别的模块（守护）已经把话发出去时，这里只补记账，不再发一遍。"""
    text = str(text or "")
    if not text.strip():
        return
    try:
        await set_typing(event, False)
    except Exception:
        pass
    try:
        await save_to_conversation_history(getattr(plugin, "context", None), event, text)
    except Exception:
        pass
    try:
        remember = getattr(plugin, "_remember_bot_message", None)
        if callable(remember):
            remember(getattr(event, "unified_msg_origin", ""), text)
    except Exception:
        pass
    try:
        notify_heartflow(plugin, event, text)
    except Exception:
        pass
    try:
        getattr(plugin, "_last_reply_at", {})[getattr(event, "unified_msg_origin", "")] = time.time()
    except Exception:
        pass
