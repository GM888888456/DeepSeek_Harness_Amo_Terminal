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
            logger.info("[amo] 主动消息后的回复，按正常聊天处理")
            return
        if self._should_disturb(snap, umo, uid, event.message_str or "", group=False):
            self._apply_disturbance(umo)
            # 不 stop_event，让 AstrBot 正常生成；<amo_state> 会带上被打扰的语气。
            return
        probability = self.gate.private_probability(snap, profile)
        roll = random.random()
        logger.info(
            "[amo] 私聊判定 | 概率=%.2f | roll=%.2f | %s"
            % (probability, roll, "回复" if roll <= probability else "不回")
        )
        if roll <= probability:
            return
        event.stop_event()
        if (
            self.cfg_bool("delay_reply", True)
            and probability >= 0.20
            and profile.get("relation", "普通") not in ("仇恨", "抵触")
            and random.random() < 0.45
        ):
            self._schedule_delayed_reply(event, profile)

    async def _handle_group_directed(self, event, text, profile):
        umo = event.unified_msg_origin
        group_id = event.get_group_id()
        snap = self.state.snapshot()
        recent = self._recent(umo, 8 if self.cfg_str("context_style", "lean") == "lean" else 12)
        result = await self.gate.should_reply_group(
            umo, group_id, text, recent, True, profile, snap
        )
        if self.cfg_bool("debug_log", False):
            logger.debug("[amo] 群聊定向判定: %s" % json.dumps(result, ensure_ascii=False))
        if not result["reply"]:
            event.stop_event()

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
