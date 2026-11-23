# -*- coding: utf-8 -*-
"""Amo 终端 · 消息与命令处理（CommandMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., CommandMixin, Star) 混入，self.* 照旧可用。

注意：常量/工具只在这里或 amo_core 里有一份，不要在 main.py 再定义一份。
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import inspect
import json
import math
import os
import random
import re
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone

try:
    from astrbot.api import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("amo_terminal")

from .shared import *



class CommandMixin:

    async def _handle_command(self, event):
        args = self._args(event)
        sub = args[0].lower() if args else "help"
        uid = self._canonical_uid(event)

        if sub in ("help", "帮助", ""):
            # 指令合并成三行：能一眼扫完，不用往回翻
            return (
                "🌙 陪伴 · /amo 后面接这些\n"
                "查看：status 状态｜mood 心情｜period 生理期｜health 身体｜schedule 日程｜"
                "weather 天气｜worldview 世界观｜threshold 阈值\n"
                "看人：profile [@人]｜memories [@人]｜photo 照片\n"
                "管理：rel @人 关系｜set @人 字段 值｜memo @人 内容 [0/1/2]｜period set 日期｜"
                "health set 状态｜regen 日程/世界观｜say 内容｜clean"
            )

        if sub in ("draw", "画图"):
            engine = getattr(self, "draw", None)
            if engine is None:
                return "画图引擎未加载"
            text = " ".join(args[1:]).strip()
            return engine.manual(event, text)

        if sub in ("photo", "照片"):
            engine = getattr(self, "photo", None)
            if engine is None:
                return "照片引擎未加载"
            tail = " ".join(args[1:]).strip().lower()
            if tail in ("test", "测试", "share"):
                return "照片测试：" + await engine.share_now("daily")
            if tail in ("travel", "shopping", "weekend", "daily", "outfit"):
                return "照片测试：" + await engine.share_now(tail)
            return engine.status_text()

        if sub == "status" or sub == "状态":
            return self._format_status(await self._status_data())

        if sub == "mood" or sub == "心情":
            snap = self.state.snapshot()
            feel = snap.get("feel") or {}
            if not feel:
                return "🫀 七情六欲没开（hf_enable_heartflow）"
            base = feel.get("base", 34.0)
            lines = ["🫀 七情六欲（常态约 %.0f，离常态越远越算情绪）" % base]
            for key in ("joy", "anger", "sadness", "fear", "love", "disgust", "surprise"):
                value = float(feel.get(key, base))
                bar = "█" * int(round(value / 10)) + "░" * (10 - int(round(value / 10)))
                lines.append("%s %s %d" % (self.state.FEEL_NAMES.get(key, key), bar, int(round(value))))
            lines.append("身体：饿 %.0f / 精力 %.0f" % (
                float(feel.get("hunger", 0)), float(feel.get("energy", 0))))
            wants = sorted(
                ((key, float(value)) for key, value in feel.items() if key.startswith("desire_")),
                key=lambda item: item[1], reverse=True)[:3]
            if wants:
                lines.append("六欲最强：" + "、".join(
                    "%s%.0f" % (self.state.FEEL_NAMES.get(k, k), v) for k, v in wants))
            lines.append("此刻：%s；语气：%s" % (
                self.state.feel_word(), self.state.tone_text(snap, "普通")))
            return "\n".join(lines)

        if sub == "profile" or sub == "档案":
            target = self._resolve_target(event, args, 1)
            profile = self.db.get_profile(target)
            if not profile:
                return "还没有这个人的档案。多聊几句就会自动建立。"
            return "\n".join([
                "📁 档案 · " + (profile.get("name") or profile.get("uid")),
                "ID：" + str(profile.get("uid")),
                "称呼：" + str(profile.get("alias") or "未设置"),
                "生日：" + str(profile.get("birthday") or "未知"),
                "关系：" + str(profile.get("relation") or "普通"),
                "好感：" + str(profile.get("affection") or 0),
                "消息数：" + str(profile.get("msg_count") or 0),
                "记忆数：" + str(self._data_memory_count(target)),
                "备注：" + str(profile.get("notes") or "无"),
            ])

        if sub == "memories" or sub == "记忆":
            target = self._resolve_target(event, args, 1)
            if target != uid and not self._is_admin(event):
                return "只有管理员才能查看别人的记忆。"
            items = await self._data_mem_list(target, "", 20)
            if not items:
                return "暂时没有记忆。"
            lines = ["📖 记忆 · " + target]
            for item in items:
                tier = to_int(item.get("tier"))
                label = "珍贵" if tier >= 2 else ("重要" if tier == 1 else "普通")
                expires = item.get("expires_at")
                if not expires:
                    left = "永久"
                else:
                    left = "%d天" % max(0, int((to_float(expires) - now_ts()) / 86400))
                lines.append("#%s [%s|%s] %s" % (item["id"], label, left, item["content"]))
            return "\n".join(lines)

        if sub in ("rel", "关系"):
            if not self._is_admin(event):
                return "只有管理员才能调整关系。"
            if len(args) < 3:
                return "用法：/amo rel @人 仇恨|抵触|普通|熟识|相恋"
            target = self._resolve_target(event, args, 1)
            relation = args[2]
            if relation not in RELATIONS:
                return "关系只能是：" + "、".join(RELATIONS)
            self.db.update_profile(target, relation=relation)
            if relation == "相恋":
                self._register_lover(target)
            await self._sync_profile_relation_edge(target, relation)
            await self._write_memory_checked(target, "与角色的关系是" + relation, "relation", 2)
            return "✅ 已将 " + target + " 的关系设为「" + relation + "」"

        if sub == "set" or sub == "设置":
            if not self._is_admin(event):
                return "只有管理员才能修改档案。"
            if len(args) < 4:
                return "用法：/amo set @人 name|alias|birthday|notes|affection 值"
            target = self._resolve_target(event, args, 1)
            field = args[2]
            value = " ".join(args[3:])
            if field == "relation":
                return "请用 /amo rel 设置关系。"
            if field == "birthday":
                match = re.match(r"^(\d{4}-)?(\d{1,2})-(\d{1,2})$", value)
                if not match:
                    return "生日格式：MM-DD 或 YYYY-MM-DD"
                value = "%02d-%02d" % (to_int(match.group(2)), to_int(match.group(3)))
            if field == "affection":
                value = int(clamp(to_int(value), 0, 100))
            if field not in ("name", "alias", "birthday", "notes", "affection"):
                return "可修改字段：name、alias、birthday、notes、affection"
            self.db.update_profile(target, **{field: value})
            return "✅ 已更新 " + target + " 的 " + field

        if sub == "memo" or sub == "记住":
            if not self._is_admin(event):
                return "只有管理员才能手动写入记忆。"
            if len(args) < 3:
                return "用法：/amo memo @人 内容 [0普通/1重要/2珍贵]"
            target = self._resolve_target(event, args, 1)
            content_parts = args[2:]
            tier = 1
            if content_parts and content_parts[-1] in ("0", "1", "2"):
                tier = to_int(content_parts[-1])
                content_parts = content_parts[:-1]
            content = " ".join(content_parts).strip()
            if not content:
                return "内容不能为空。"
            scope, group_id = self._memory_scope(event)
            if await self._write_memory_checked(target, content, "manual", tier, scope, group_id):
                return "✅ 已记住：" + content
            return "⚠️ 记忆库没写进去，稍后再试。"

        if sub == "forget" or sub == "忘记":
            if not self._is_admin(event):
                return "只有管理员才能删除记忆。"
            if len(args) < 2:
                return "用法：/amo forget 记忆ID"
            return "记忆由外挂插件保存，请到该插件里删除；本插件不再单独存记忆。"

        if sub == "period" or sub == "生理期":
            if len(args) >= 3 and args[1].lower() == "set":
                if not self._is_admin(event):
                    return "只有管理员才能调整生理期。"
                if self._set_period_start(args[2]):
                    return "✅ 生理期起始日已设为 " + args[2] + "（由医疗插件保存）"
                return "日期格式应为 YYYY-MM-DD"
            period = self.state.period_info()
            return (
                "🩸 生理期\n阶段：" + period["phase"] + " 第" + str(period["day"]) + "天\n"
                "状态：" + period["tone"] + "\n"
                "疼痛：" + str(period["pain"]) + "/10\n"
                "周期：" + str(period.get("cycle_days", 28)) + "天｜经期：" + str(period.get("bleed_days", 5)) + "天\n"
                "距离下次：" + str(period["days_to_next"]) + "天（预计 " + str(period.get("next_start", "")) + "）\n"
                "起始日：" + str(period.get("start") or "未记录") + "（/amo period set YYYY-MM-DD，或在医疗面板双击标题改）"
            )

        if sub == "health" or sub == "健康":
            if len(args) >= 3 and args[1].lower() == "set":
                if not self._is_admin(event):
                    return "只有管理员才能调整健康状态。"
                status = args[2]
                if status not in ("健康", "轻微不适", "感冒", "低烧", "疲惫"):
                    return "状态：健康 / 轻微不适 / 感冒 / 低烧 / 疲惫"
                self.state.set_health(status, 24, "管理员设置")
                return "✅ 健康状态已设为 " + status
            health = self.state.health_info()
            return (
                "🩺 身体状态：" + health["status"] + "\n"
                + ("备注：" + health["note"] + "\n" if health.get("note") else "")
                + "恢复时间：" + (
                    datetime.fromtimestamp(health["until"]).strftime("%m-%d %H:%M")
                    if health.get("until") else "—"
                )
            )

        if sub == "schedule" or sub == "日程":
            if len(args) >= 2 and args[1].lower() == "regen":
                if not self._is_admin(event):
                    return "只有管理员才能重生成日程。"
                items = await self.state.ensure_schedule(self._last_umo, force=True)
                return "✅ 日程已重新生成，共 " + str(len(items)) + " 条。"
            items = self.state.schedule.get(today_str()) or []
            if not items:
                items = await self.state.ensure_schedule(self._last_umo)
            activity = self.state.current_activity()
            lines = ["📅 今日日程"]
            for item in items:
                lines.append("%s-%s %s（%s）" % (
                    item.get("start", ""), item.get("end", ""),
                    item.get("activity", ""), item.get("place", ""),
                ))
            lines.append("现在应该在：" + str(activity.get("activity", "")))
            return "\n".join(lines)

        if sub == "weather" or sub == "天气":
            if len(args) >= 2 and args[1].lower() in ("refresh", "刷新"):
                await self.state.refresh_weather(force=True)
            weather = await self.state.refresh_weather()
            return (
                "🌦 " + str(weather.get("city", "")) + " " + str(weather.get("text", ""))
                + " " + str(weather.get("temp", "")) + "℃\n"
                + "湿度：" + str(weather.get("humidity", "")) + "%\n"
                + "风：" + str(weather.get("wind", "")) + "\n"
                + "来源：" + ("和风天气" if weather.get("source") == "qweather" else "本地模拟")
            )

        if sub == "worldview" or sub == "世界观":
            if len(args) >= 2 and args[1].lower() == "regen":
                if not self._is_admin(event):
                    return "只有管理员才能重生成世界观。"
                await self.state.ensure_worldview(self._last_umo, force=True)
                return "✅ 世界观已重新生成。"
            await self.state.ensure_worldview(self._last_umo)
            return "🌍 世界观\n" + self.state.worldview_text()

        if sub == "threshold" or sub == "阈值":
            data = await self._status_data()
            threshold = data["threshold"]
            return (
                "🎚 心流回复阈值\n"
                "当前动态阈值：" + str(round(threshold["value"] / 100, 3)) + "\n"
                "基础阈值：" + str(round(threshold["base"] / 100, 3)) + "\n"
                "绝对分数阈值：" + str(threshold["absolute"]) + "/10\n"
                "当前群活跃度：" + str(data["activity_rate"]) + "%\n"
                "说明：阈值越高越不想说话；详细状态用 /heartflow。"
            )

        if sub == "say" or sub == "说":
            if not self._is_admin(event):
                return "只有管理员才能测试发言。"
            content = " ".join(args[1:]).strip()
            if not content:
                return "用法：/amo say 内容"
            await event.send(MessageChain([Comp.Plain(content)]))
            return ""

        if sub == "clean" or sub == "清理":
            if not self._is_admin(event):
                return "只有管理员才能清理。"
            self.db.purge_messages(self.cfg_int("chat_log_days", 14))
            return "✅ 已清理过期聊天记录。"

        return "未知指令。发送 /amo help 查看帮助。"

    async def _sync_face_library_once(self, event):
        """把库里还没进 QQ 收藏表情的旧图补收一遍（每个进程只做一次）。"""
        if getattr(self, "_face_synced", False):
            return
        self._face_synced = True
        if not self.cfg_bool("emoji_enable", True):
            return
        try:
            import asyncio as _aio_s
            import os as _os_s
            try:
                from . import emoji_lib
            except Exception:
                from amo_core import emoji_lib  # type: ignore
            try:
                from . import qq_face
            except Exception:
                from amo_core import qq_face  # type: ignore
            root = emoji_lib.root_dir(self.db.path)
            index = emoji_lib.load_index(root)
            todo = [k for k, v in index.items()
                    if isinstance(v, dict) and not v.get("fav")]
            if not todo:
                return
            logger.debug("[amo] 补收 QQ 收藏表情 %d 张" % len(todo))
            for key in todo[:60]:
                entry = emoji_lib.get_entry(root, key)
                path = _os_s.path.join(root, entry.get("file") or "")
                if not _os_s.path.isfile(path):
                    emoji_lib.set_fav(root, key, False)
                    continue
                ok = await qq_face.add_favorite(
                    event, path,
                    remote_path=qq_face.napcat_emoji_path(entry.get("file")))
                emoji_lib.set_fav(root, key, ok)
                logger.debug("[amo] %s 收进 QQ 收藏表情：%s"
                            % ("已" if ok else "没", path.split("/")[-1]))
                await _aio_s.sleep(0.8)
        except Exception as exc:
            logger.debug("[amo] 补收收藏表情失败: %s" % exc)

    async def _collect_emoji(self, event):
        """把聊天里的表情包收进库（小图才收，大图当照片，不算表情）。

        2026-11-21 口径：表情要能收藏、能打标签、别一直发也别一直不发；
        标签先留空，挑图时没标签的只给三成机会，标了才按情绪发。
        """
        if not self.cfg_bool("emoji_enable", True):
            return
        # 2026-11-21 事故：他私聊发来的自拍被当成表情收进库，后来还发到群里。
        # 两条硬闸：私聊一手都不收；恋人发的东西永远不进表情库。
        try:
            if event.is_private_chat():
                return
        except Exception:
            pass
        if bool(getattr(event, "amo_sender_is_lover", False)):
            return
        comps = getattr(getattr(event, "message_obj", None), "message", None) or []
        images = [c for c in comps if c.__class__.__name__ == "Image"]
        if images:
            logger.debug("[amo] 表情收藏检查：%d 个组件，其中图片 %d 张" % (len(comps), len(images)))
        if not images:
            return
        _msg_text = str(getattr(event, "message_str", "") or "").strip()
        if len(_msg_text) > 12:
            # 带说明文字的多半是照片（自拍/随手拍），不是表情
            return
        import os as _os
        try:
            from . import emoji_lib
        except Exception:
            from amo_core import emoji_lib  # type: ignore
        root = emoji_lib.root_dir(self.db.path)
        saved_n = 0
        for comp in images[:3]:
            try:
                path = await comp.convert_to_file_path()
            except Exception as _e:
                logger.debug("[amo] 表情跳过：取文件失败 %s" % _e)
                continue
            if not path or not _os.path.isfile(path):
                logger.debug("[amo] 表情跳过：本地文件不存在 %r" % path)
                continue
            try:
                _size = _os.path.getsize(path)
                if _size > 1500 * 1024:
                    logger.debug("[amo] 表情跳过：文件过大 %d 字节" % _size)
                    continue
            except Exception as _e:
                logger.debug("[amo] 表情跳过：读大小失败 %s" % _e)
                continue
            # 只收「真表情」：GIF / 带透明的 PNG / 小方图 JPEG。
            # 照片（尤其手机拍的）一律不收 —— 表情少几张无所谓，别人的照片不能进库。
            try:
                import asyncio as _aio_t
                if await _aio_t.to_thread(emoji_lib.looks_like_photo, path):
                    logger.debug("[amo] 表情跳过：看着是照片，不收")
                    continue
            except Exception as _e:
                logger.debug("[amo] 表情跳过：判定照片失败 %s" % _e)
                continue
            import asyncio as _aio_w
            key, saved = await _aio_w.to_thread(emoji_lib.add_file, root, path)
            if key:
                saved_n += 1
                # 同一张还要收进 QQ「收藏表情」：留在本地发出去是大图，
                # 进了收藏才是一个小表情（2026-11-21 她的要求）
                try:
                    import asyncio as _aio_fav
                    _aio_fav.create_task(self._fav_emoji(event, root, key, saved))
                except Exception:
                    pass
                # 标签交给视觉模型，后台跑，不拖这条消息
                try:
                    import asyncio as _aio
                    _provider = await self.context.get_using_provider_async(
                        event.unified_msg_origin)
                    if _provider is not None:
                        _aio.create_task(self._tag_emoji(root, saved, _provider))
                except Exception:
                    pass
        if not saved_n and images:
            logger.debug("[amo] 表情收藏 0 张（可能尺寸过大或取不到本地文件），根目录=%s" % root)
        if saved_n:
            st = emoji_lib.stats(root)
            logger.debug("[amo] 收藏表情 %d 张（库存 %d，已标注 %d 类）"
                        % (saved_n, st.get("total", 0), len(st.get("tags") or {})))

    async def _tag_emoji(self, root, path, provider):
        """给一张表情打情绪标签（只认标签词，猜不出就留空，不硬塞）。"""
        try:
            import base64
            try:
                from . import emoji_lib
            except Exception:
                from amo_core import emoji_lib  # type: ignore
            with open(path, "rb") as fh:
                b64 = base64.b64encode(fh.read()).decode()
            prompt = ("这是聊天用的表情包。从这些词里选 1~2 个最贴的："
                      + "、".join(emoji_lib.ALL_TAGS)
                      + "。只输出词，用逗号分隔，不要解释，猜不出就输出「无」。")
            resp = await provider.text_chat(
                # AstrBot 4.29.4：不传就是 0，会被兜成 1 还打 WARN；这里显式给 2
                request_max_retries=2,
                prompt=prompt, image_urls=["base64://" + b64])
            text = (getattr(resp, "completion_text", "") or "").strip()
            tags = [t for t in emoji_lib.ALL_TAGS if t in text]
            if tags:
                emoji_lib.set_tags(root, path, tags)
                logger.debug("[amo] 表情已标注：%s -> %s"
                            % (path.split("/")[-1], ",".join(tags)))
        except Exception as exc:
            logger.debug("[amo] 表情打标签失败: %s" % exc)

    async def _fav_emoji(self, event, root, key, path, attempt=0):
        """把收藏到的表情同步进 QQ 的「收藏表情」面板。

        NapCat 原生只认自己容器里的路径，所以传 /app/napcat/config/emoji/xxx
        （宿主 /opt/napcat_config/emoji 由宿主 cron 同步）。失败不静默：
        打 WARN，并在后台隔 90s / 180s / 270s 再试一次。
        """
        try:
            try:
                from . import emoji_lib
            except Exception:
                from amo_core import emoji_lib  # type: ignore
            try:
                from . import qq_face
            except Exception:
                from amo_core import qq_face  # type: ignore
            entry = emoji_lib.get_entry(root, key)
            if entry.get("fav"):
                return
            remote = qq_face.napcat_emoji_path(entry.get("file"))
            ok = await qq_face.add_favorite(event, path, remote_path=remote)
            if ok:
                emoji_lib.set_fav(root, key, True)
                logger.debug("[amo] 表情已收进 QQ 收藏表情：%s" % path.split("/")[-1])
                return
            logger.warning("[amo] 表情没收进 QQ 收藏（第 %d 次）：%s"
                           % (attempt + 1, path.split("/")[-1]))
            if attempt < 3:
                import asyncio as _aio_r
                _aio_r.create_task(
                    self._fav_emoji_later(event, root, key, path, attempt + 1))
        except Exception as exc:
            logger.warning("[amo] 收藏表情同步异常: %s" % exc)

    async def _fav_emoji_later(self, event, root, key, path, attempt):
        """收藏失败后隔一会儿再试（等 cron 把文件同步进 napcat）。"""
        try:
            import asyncio as _aio_w
            await _aio_w.sleep(90.0 * attempt)
            await self._fav_emoji(event, root, key, path, attempt=attempt)
        except Exception:
            pass

    async def _handle_message(self, event):
        if not self._ready or self.state is None:
            return
        self._reload_config_if_changed()
        await self._sync_persona_name(event)
        try:
            self.state.apply_schedule_events()
        except Exception:
            pass
        uid = self._canonical_uid(event)
        if not uid or uid == str(event.get_self_id()):
            return
        text = (event.message_str or "").strip()
        if not text:
            # 纯图片：不能当没看见。给个占位让流程继续，图片由 AstrBot 交给视觉模型转述
            try:
                for _comp in (getattr(getattr(event, "message_obj", None), "message", None) or []):
                    if _comp.__class__.__name__ == "Image":
                        text = "[图片]"
                        try:
                            event.message_str = text
                        except Exception:
                            pass
                        break
            except Exception:
                pass
            if not text:
                return
        if self._looks_like_command(text):
            return

        umo = event.unified_msg_origin
        private = event.is_private_chat()
        if private:
            self._clear_proactive_pending(uid)
            self._try_soothe(uid, text)
        if private and not self.cfg_bool("enable_private_reply", True):
            return
        if not private and not self.cfg_bool("enable_group_reply", True):
            return
        if private and self.cfg_bool("private_debounce_enabled", True):
            # 同一个人连着发的几条先合起来，只让最后一条走完整回复流程
            if not await self._debounce_private(event, text):
                return
            text = (event.message_str or "").strip()
            if not text:
                return

        if not private:
            try:
                self._detect_impersonation(event)
            except Exception as exc:
                logger.debug("[amo] 冒充检测失败: %s" % exc)
        await self._learn(event, text)
        self._restore_lover_relation(uid)
        profile = self.db.get_profile(uid)

        if private:
            # 私聊里她刚说过的最后一句，这一轮一定要当「他这句在回什么」的锚点。
            # 病象：她说「周末我开黑车来接你呀」→ 他「不了吧」→ 她答「空着肚子可不行」，
            # 接的是更早的吃饭话题。根因是上下文里他那句「不了吧」没有指向，
            # 模型只能在最近十几条里随便挑一个话题接。
            try:
                anchor = self._private_answer_anchor(umo, text)
                if anchor:
                    setattr(event, "amo_answer_anchor", anchor)
            except Exception as exc:
                logger.debug("[amo] 私聊锚点计算失败: %s" % exc)
            await self._handle_private(event, profile)
            return

        # 群聊只走完整心流引擎；旧的五维门控/防抖/直发逻辑不再参与。
        if self.heartflow is None or not self.cfg_bool("hf_enable_heartflow", True):
            return
        snap = self.state.snapshot()
        if self._should_disturb(snap, umo, uid, text, group=True):
            self._apply_disturbance(umo)
            setattr(event, "amo_force_reply", True)
        try:
            await self.heartflow.on_group_message(event)
        except Exception as exc:
            logger.error("[amo] 心流处理失败: %s" % exc)

    async def _handle_private(self, event, profile):
        snap = self.state.snapshot()
        umo = event.unified_msg_origin
        uid = self._canonical_uid(event)
        if self._recent_bot_initiated(umo):
            self._disturb_until[str(umo)] = 0
            logger.info("[心流] ❤️心流：回（她刚主动找过他）")
            return
        if self._should_disturb(snap, umo, uid, event.message_str or "", group=False):
            logger.info("[心流] ❤️心流：回（在忙被打扰，带着脾气回）")
            self._apply_disturbance(umo)
            # 不 stop_event，让 AstrBot 正常生成；<amo_state> 会带上被打扰的语气。
            return
        # FUSE 2026-11-23（用户口径：融合，不要两套引擎）：私聊也交给心流，
        # 旧的「概率 roll」只在心流没启用时兜底。
        _reply = None
        if self.heartflow is not None and self.cfg_bool("hf_enable_heartflow", True):
            try:
                _reply = await self.heartflow.on_private_message(event)
            except Exception as exc:
                logger.error("[amo] 私聊心流失败，按正常回复: %s" % exc)
                _reply = True
        if _reply is None:
            _p = self.gate.private_probability(snap, profile)
            _reply = random.random() <= _p
            logger.debug("[amo] 私聊判定（旧概率兜底）| 概率=%.2f | %s"
                        % (_p, "回复" if _reply else "不回"))
        if _reply:
            return
        event.stop_event()
        if (
            self.cfg_bool("delay_reply", True)
            and profile.get("relation", "普通") not in ("仇恨", "抵触")
            and random.random() < 0.45
        ):
            self._schedule_delayed_reply(event, profile)

    async def _handle_money_gift(self, event, text) -> bool:
        """他转钱/发红包给她：算借款，走金融账本。

        返回 True 表示这条消息已经处理完（不用再进聊天链路）。
        """
        if not event.is_private_chat():
            return False
        parsed = self._parse_money_gift(text)
        if not parsed:
            return False
        channel, amount, currency = parsed
        plugin = self._finance()
        if plugin is None:
            return False
        cny = amount
        if currency != "CNY":
            rate = 1.0
            reader = getattr(plugin, "fx_rate", None) if plugin is not None else None
            if callable(reader):
                try:
                    rate = float(reader(currency) or 1.0)
                except Exception:
                    rate = 1.0
            cny = round(amount * rate, 2)
        try:
            if channel == "red":
                # 红包是礼物，不用还；转账仍然是借款
                receiver = getattr(plugin, "red_packet", None)
                if not callable(receiver):
                    return False
                result = receiver(cny, str(event.get_sender_id() or ""))
            else:
                borrower = getattr(plugin, "borrow", None)
                if not callable(borrower):
                    return False
                result = borrower(cny, channel, str(event.get_sender_id() or ""))
        except Exception as exc:
            logger.warning("[amo] 收钱失败: %s" % exc)
            result = {"ok": False, "reason": "账本没响应"}
        if not result.get("ok"):
            reason = result.get("reason") or "借不了"
            left = result.get("left")
            if isinstance(left, dict) and left.get("transfer_left") is not None:
                reason += "（今天还能转 %.0f）" % float(left.get("transfer_left") or 0)
            yield_text = "这个我收不下：" + reason
        else:
            kind = "红包" if result.get("channel") == "red" else "转账"
            owed = float(result.get("owed") or 0)
            gift = bool(result.get("gift"))
            origin = (("%s %.2f（折合 ¥%.2f）" % (currency, amount, cny))
                      if currency != "CNY" else ("%.2f" % cny))
            yield_text = self._warm_gift_reply(kind, cny, 0 if gift else owed,
                                               origin=origin, gift=gift)
            try:
                self.feel(FeelEvent.MONEY_GIFT)
            except Exception:
                pass
        try:
            await self.context.send_message(event.unified_msg_origin, yield_text)
        except Exception as exc:
            logger.debug("[amo] 回执发送失败: %s" % exc)
        try:
            event.stop_event()
        except Exception:
            pass
        self._sync_finance()
        return True


__all__ = [
    "CommandMixin",
]
