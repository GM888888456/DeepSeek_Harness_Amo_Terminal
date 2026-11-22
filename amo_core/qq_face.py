# -*- coding: utf-8 -*-
"""表情按 QQ 的规矩走：收进「收藏表情」，发出来是小表情而不是大图。

2026-11-21 她的原话：「她的表情你收藏在QQ表情啊！在本地的话会显得很大！」

两个毛病都在这一层修：

1. 收藏 —— NapCat 的 `add_custom_face`（收藏表情面板里真能看到，
   她自己也能直接拿去发）。文件走 base64，不依赖两个容器共享目录。
2. 发送 —— AstrBot 发图只给 `image` 段，NapCat 按「普通图片」处理，
   铺满一个气泡，所以显得很大；带 `sub_type=1`（QQ 里的 picSubType=1）
   才是表情，缩成小贴图。

这两个动作都要求走 aiocqhttp 的 bot（`event.bot`），
不能只靠 `context.send_message`，那条路已经把图片字段定死了。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os

from astrbot.api import logger

# QQ 里 picSubType=1 就是「表情」，0 是普通图片
PIC_SUBTYPE_EMOJI = 1
# napcat 容器里能看到的表情目录（宿主 /opt/napcat_config/emoji 由 cron 同步）
NAPCAT_EMOJI_DIR = "/app/napcat/config/emoji"


def napcat_emoji_path(rel: str) -> str:
    """库里的相对路径（files/xxx.gif）→ napcat 容器里的绝对路径。

    宿主 cron 把 files/ 里的文件平铺同步到 /opt/napcat_config/emoji，
    所以 napcat 侧是 /app/napcat/config/emoji/<文件名>，没有 files/ 这层。
    """
    name = os.path.basename(str(rel or "").replace("\\", "/"))
    if not name:
        return ""
    return NAPCAT_EMOJI_DIR + "/" + name
SUMMARY = "[动画表情]"


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        data = fh.read()
    if not data:
        raise RuntimeError("表情文件是空的")
    return data


def _bot(event):
    bot = getattr(event, "bot", None)
    if bot is None:
        raise RuntimeError("拿不到 aiocqhttp 的 bot")
    return bot


def _b64(data: bytes) -> str:
    return "base64://" + base64.b64encode(data).decode()


async def add_favorite(event, path: str, remote_path: str = "") -> bool:
    """把一张表情收进 QQ「收藏表情」。成功 True，失败 False（不抛）。

    NapCat 的 `add_custom_face` 把 `file` 原样塞给原生 `addFavEmoji`
    （`emojiPath: e.file`），原生只认**它自己容器里能读到的文件路径**；
    base64:// 读不出来，这就是之前 77 张全 fav=False 的原因。按顺序试：
    1) remote_path —— napcat 侧路径（/app/napcat/config/emoji/xxx）
    2) base64:// —— 万一新版原生支持
    失败要留痕，别再静默吞掉。
    """
    try:
        data = await asyncio.to_thread(_read, path)
    except Exception as exc:
        logger.warning("[amo] 收藏表情读文件失败 %s: %s" % (path, exc))
        return False
    md5 = hashlib.md5(data).hexdigest()
    candidates = []
    if remote_path:
        candidates.append(remote_path)
    candidates.append(_b64(data))
    last = ""
    for cand in candidates:
        params = {
            "file": cand,
            "file_name": os.path.basename(path),
            "file_size": str(len(data)),
            "md5": md5,
            "is_origin": True,
            "is_mark_face": False,
        }
        try:
            await _bot(event).call_action("add_custom_face", **params)
            return True
        except Exception as exc:
            last = str(exc)[:200]
            logger.info("[amo] add_custom_face 失败 file=%s → %s"
                        % (cand[:48], last))
    logger.warning("[amo] 表情进 QQ 收藏失败 %s：%s"
                   % (os.path.basename(path), last))
    return False


async def send_as_face(event, path: str) -> bool:
    """按「表情」发一张图（小图），成功 True。

    失败不抛，让调用方回落到普通图片，别把这条回复整个弄丢。
    """
    try:
        data = _read(path)
        segment = {
            "type": "image",
            "data": {
                "file": _b64(data),
                "sub_type": PIC_SUBTYPE_EMOJI,
                "summary": SUMMARY,
            },
        }
        bot = _bot(event)
        group_id = ""
        try:
            group_id = str(event.get_group_id() or "")
        except Exception:
            group_id = ""
        if group_id.isdigit():
            await bot.call_action(
                "send_group_msg", group_id=int(group_id), message=[segment])
            return True
        sender = ""
        try:
            sender = str(event.get_sender_id() or "")
        except Exception:
            sender = ""
        if sender.isdigit():
            await bot.call_action(
                "send_private_msg", user_id=int(sender), message=[segment])
            return True
        return False
    except Exception:
        return False


__all__ = ["add_favorite", "send_as_face", "PIC_SUBTYPE_EMOJI",
           "SUMMARY", "NAPCAT_EMOJI_DIR", "napcat_emoji_path"]
