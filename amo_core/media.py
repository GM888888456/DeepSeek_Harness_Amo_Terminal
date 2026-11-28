# -*- coding: utf-8 -*-
"""Amo 终端 · 发送与影音（MediaMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., MediaMixin, Star) 混入，self.* 照旧可用。

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

MODEL_LEAK_RE = re.compile(
    r"(?:deepseek|openai|anthropic|claude|gemini|chatgpt|gpt-?[0-9]|qwen|通义|千问|"
    r"glm|chatglm|智谱|moonshot|kimi|doubao|豆包|ernie|文心|hunyuan|混元|llama|mistral|"
    r"grok|sonnet|opus|haiku|dp-?[0-9]|llm|大模型|语言模型|模型名称|api\s*key|"
    r"token|提示词|prompt|system\s*prompt|插件|astrbot)",
    re.I,
)
SELF_LEAK_RE = re.compile(
    r"(?:我|本人|咱)(?:就|也|其实|确实|大概)?(?:是|用的?|基于|跑在|接的?|部署在|由)"
    r"[^。！？，]{0,24}(?:模型|提示词|插件|astrbot|api|服务端|后端)"
    r"|(?:我|本人)的(?:模型|提示词|系统提示|底层|设定文件|配置)"
    r"|(?:我|本人)(?:被|是由)[^。！？，]{0,16}(?:训练|开发|部署|接入)"
    r"|(?:我|本人)(?:用的?是?|在用的?|跑)在?[^。！？，]{0,16}"
    r"(?:deepseek|openai|anthropic|claude|gpt|gemini|qwen|智谱|通义|豆包|kimi)",
    re.I,
)
LEAK_DEFLECTS = (
    "这个啊，不聊。",
    "问点别的吧。",
    "说这个干嘛。",
    "不告诉你。",
    "你猜。",
)
def leak_deflect_text():
    return random.choice(LEAK_DEFLECTS)
def looks_like_model_leak(text):
    """回复里有没有把她自己的模型/提示词/插件这类后台信息说出来。

    注意：只拦「说的是她自己」的句子。用户在聊自己的项目（插件、提示词、模型选型）时，
    她顺着聊是正常的，不能被换成「秘密，不告诉你」。
    """
    raw = str(text or "")
    if not raw:
        return False
    if not MODEL_LEAK_RE.search(raw):
        return False
    if SELF_LEAK_RE.search(raw):
        return True
    # 短句里直接报出厂商/模型名、且没有任何「他/你/这个项目」之类的第三方指向时，
    # 仍然按自曝处理（她不会无端说这些名字）
    compact = re.sub(r"\s+", "", raw)
    if len(compact) <= 12 and re.search(
            r"(?:deepseek|openai|anthropic|claude|gemini|chatgpt|qwen|智谱|通义)", compact, re.I):
        return True
    return False


class MediaMixin:

    async def _send_to_umo(self, umo, text, quote_id=None, group=False):
        text = clean_reply(text, self.cfg_int("max_reply_chars", 220))
        if looks_like_model_leak(text):
            text = leak_deflect_text()
        if not text or not umo:
            return False
        scene = "group" if (group or "GroupMessage" in str(umo)) else "private"
        # 整条原文直接发，宁可长一点也不能把话吞了（守护插件已下线）。
        try:
            import re as _re
            try:
                from .send_bookkeeping import typing_pause as _typing_pause
            except Exception:
                try:
                    from send_bookkeeping import typing_pause as _typing_pause
                except Exception:
                    _typing_pause = None
            _parts = [p.strip() for p in _re.split(r"\n+|(?<=[。！？!?…~])\s*", text) if p.strip()]
            _parts = _parts[:4] or [text]
            for _i, _seg in enumerate(_parts):
                if _i:
                    # 主动消息没有 event，打不了「正在输入」，只按字数停一下
                    await asyncio.sleep(random.uniform(0.5, 1.2))
                if _typing_pause is not None:
                    await _typing_pause(self, None, _seg)
                elif _i:
                    await asyncio.sleep(max(0.6, min(8.0, len(_seg) * 0.28)))
                _chain = []
                if _i == 0 and quote_id is not None and self._quote_allowed(umo, scene == "group"):
                    try:
                        _chain.append(Comp.Reply(id=quote_id))
                    except Exception:
                        pass
                _chain.append(Comp.Plain(_seg))
                try:
                    await self.context.send_message(umo, MessageChain(_chain))
                except Exception as _send_exc:
                    if not await self._send_plain_fallback(umo, _seg, _send_exc):
                        raise
        except Exception as exc:
            # 2026-11-27：这个异常 str() 常常是空串（框架抛的空 Exception），
            # 只打 exc 等于什么都没记，排不出问题。类型 + repr 一起打。
            logger.warning("[amo] 主动发送失败: %s: %r" % (type(exc).__name__, exc))
            return False
        self._last_reply_at[umo] = now_ts()
        logger.debug("[amo] 主动 -> %s: %s" % (umo, text[:300]))
        self._remember_bot_message(umo, text)
        return True

    async def _send_plain_fallback(self, umo, text, exc):
        """主动发送失败时的兜底：去掉引用/富消息，退到纯文本，再退到字符串。

        AstrBot 在平台适配器不认某个组件时会抛 ApiNotAvailable（`str()` 常常是空的），
        常见就是 MessageChain 里的 Reply/图片该平台不支持；纯文本通常还能发出去。
        每次降级都写清原因，别再出现「只看到 ApiNotAvailable」这种查不下去的日志。
        """
        kind = "unknown"
        try:
            try:
                from .provider_router import classify_error
            except ImportError:
                from provider_router import classify_error  # type: ignore
            kind = classify_error(exc)
        except Exception:
            pass
        tried = []
        if Comp is not None and MessageChain is not None:
            try:
                await self.context.send_message(umo, MessageChain([Comp.Plain(str(text or ""))]))
                logger.info("[amo] 主动发送降级为纯文本成功（原异常 %s/%s）"
                            % (type(exc).__name__, kind))
                return True
            except Exception as exc2:
                tried.append("纯文本失败:%s" % type(exc2).__name__)
        try:
            await self.context.send_message(umo, str(text or ""))
            logger.info("[amo] 主动发送降级为字符串成功（原异常 %s/%s）"
                        % (type(exc).__name__, kind))
            return True
        except Exception as exc3:
            tried.append("字符串失败:%s" % type(exc3).__name__)
        logger.warning("[amo] 主动发送降级也失败（原异常 %s/%s）：%s"
                       % (type(exc).__name__, kind, "；".join(tried)))
        # 后台任务没有事件上下文，aiocqhttp 可能根本发不出去：存起来，等他下次说话补发
        try:
            try:
                from .undelivered import queue as _queue
            except ImportError:
                from undelivered import queue as _queue  # type: ignore
            _queue(self, umo, text, log=logger)
        except Exception as _q_exc:
            logger.debug("[amo] 入队待补发失败: %s" % _q_exc)
        return False

    async def _send_image_to_umo(self, umo, data, text="", quote_id="", label="照片",
                                 prompt="", scene=None):
        """在后台把图发到会话；用 context.send_message，不依赖已经结束的事件。

        带 `quote_id` 时把图挂在那条消息下面，用户一眼知道这张图接的是哪句话。
        Reply 个别平台不认，发失败会去掉引用再发一次，不影响出图。
        """
        if Comp is None or MessageChain is None or not umo:
            return False
        question = str(text or "").strip()

        def build(with_quote):
            chain = []
            if with_quote and quote_id:
                chain.append(Comp.Reply(id=str(quote_id)))
            if question:
                chain.append(Comp.Plain(question))
            chain.append(Comp.Image.fromBytes(data))
            return MessageChain(chain)

        try:
            chain = build(bool(quote_id))
        except Exception:
            return False
        try:
            await self.context.send_message(umo, chain)
        except Exception as exc:
            if not quote_id:
                logger.error("[amo] 主动发图失败: %s" % exc)
                return False
            try:
                await self.context.send_message(umo, build(False))
            except Exception as retry_exc:
                logger.error("[amo] 主动发图失败: %s" % retry_exc)
                return False
        # 发出去就记一条：以后「拍过什么」都能查得到，不靠调用方自觉。
        # scene 必须传进来：以前固定给 {}，于是这条记忆永远没有地点，
        # 只剩提示词里那句「家里」——和日程的「路上」打架，看着就像记忆错了。
        try:
            await self._remember_photo(umo, prompt, scene or {}, label=label)
        except Exception as exc:
            logger.debug("[amo] 发图后写记忆失败: %s" % exc)
        return True

    async def _image_bytes(self, prompt, umo="", uid="", selfie=None, scene=None):
        """出图兜底入口：让生图插件（Astrbot_Amo_Image）直接吐图片字节。

        画图/照片引擎原先只认万象画卷（OmniDraw），机器上没装就一张都出不来；
        有了这个兜底，装万象画卷或装生图插件都能出图。
        """
        plugin = self._image_plugin()
        if plugin is None:
            return None
        prompt = str(prompt or "").strip()
        if not prompt:
            return None
        scene = scene if isinstance(scene, dict) else self._activity_snapshot(umo)
        place = str((scene or {}).get("place") or "").strip()
        activity = str((scene or {}).get("activity") or "").strip()
        zone = str((scene or {}).get("zone") or "").strip()
        logger.debug("[amo] 出图场景：%s / %s" % (place or "未定", activity or "未定"))
        try:
            return await asyncio.wait_for(
                plugin.draw_for(str(umo or ""), str(uid or ""), prompt, selfie=selfie,
                                place=place, activity=activity, zone=zone),
                timeout=180,
            )
        except Exception as exc:
            logger.error("[amo] 生图失败（Astrbot_Amo_Image.draw_for）: %s" % exc)
            self._image_star = None   # 下次重新解析实例，别一直抱着可能已失效的那个
            return None

    def _image_share_quota(self, now, private=True):
        """返回 (能不能发, 今天已发张数)。

        张数**只认生图插件**（Astrbot_Amo_Image）：主插件不再自己记一份，
        否则同一张图会被数两遍，两边迟早对不上。冷却和概率仍在这里。
        """
        if not private:
            cooldown = max(0, self.cfg_int("image_share_cooldown_minutes", 180)) * 60
            try:
                last = to_float(self.db.kv_get("image_share_last", 0), 0)
            except Exception:
                last = 0
            if cooldown and last and now - last < cooldown:
                return False, 0
        plugin = self._image_plugin()
        reader = getattr(plugin, "quota", None) if plugin is not None else None
        if not callable(reader):
            return True, 0
        try:
            info = reader("", "", not private) or {}
        except Exception:
            info = {}
        if not isinstance(info, dict):
            return True, 0
        used = to_int(info.get("used"), 0)
        return (info.get("allowed", True) is not False), used

    #: 私密/寝衣类关键词：这类衣服只在私聊出现，绝不进群。
    PRIVATE_OUTFIT_WORDS = ("寝衣", "睡衣", "睡裙", "睡袍", "抹胸", "薄纱", "内衣", "泳衣", "泳装", "私密")

    def _outfit_is_private(self, outfit):
        """这套衣服能不能给群里看。2026-11-23（用户口径：寝衣别分享到群里）"""
        text = str(outfit or "")
        if not text:
            return False
        return any(word in text for word in self.PRIVATE_OUTFIT_WORDS)

    def _image_share_prompt(self, scene=None):
        """按她此刻在干嘛拼提示词；拿不到状态就用一句通用的自拍。

        衣服必须写进来：以前这个模板只有「{activity}，{place}」，没有衣服这一项，
        于是主动分享那张图生图插件读到空穿搭、模型自己配一套 —— 同一次对话里
        主动分享穿一套、要照片又穿另一套。
        """
        activity = ""
        place = ""
        outfit = ""
        try:
            current = scene if isinstance(scene, dict) else self._activity_snapshot()
            activity = str((current or {}).get("activity") or "").strip()
            place = str((current or {}).get("place") or "").strip()
            outfit = self._complete_outfit(str((current or {}).get("outfit") or "").strip())
        except Exception:
            pass
        template = self.cfg_str(
            "image_share_prompt_template",
            "自拍，{activity}，{place}，{outfit}，自然光，看向镜头",
        )
        if "{outfit}" not in template:
            template += "，{outfit}"
        text = (template.replace("{activity}", activity)
                        .replace("{place}", place)
                        .replace("{outfit}", ("穿着" + outfit) if outfit else ""))
        text = re.sub(r"[，,]{2,}", "，", text).strip("，, ")
        return text or "自拍，日常光线，看向镜头"

    async def _share_image_task(self, decision):
        """后台任务：出图 → 发送 → 记账。超时/失败都只记日志，不打扰聊天。"""
        plugin = decision.get("plugin")
        umo = decision.get("umo") or ""
        prompt = decision.get("prompt") or ""
        timeout = max(1, self.cfg_int("image_share_timeout", 90))
        self._share_inflight = True
        try:
            scene = decision.get("scene") if isinstance(decision.get("scene"), dict) else {}
            try:
                data = await asyncio.wait_for(
                    plugin.draw_for(umo, decision.get("uid") or "", prompt,
                                    place=str(scene.get("place") or ""),
                                    activity=str(scene.get("activity") or ""),
                                    zone=str(scene.get("zone") or "")),
                    timeout=timeout,
                )
            except Exception as exc:
                logger.warning("[amo] 主动分享出图失败: %s" % exc)
                return
            if not data:
                return
            prefix = self.cfg_str("image_share_prefix", "")
            quote = str(decision.get("quote") or "")
            # 记忆由 _send_image_to_umo 统一写（它发完就会写一条 photo_record），
            # 这里以前又写一遍，结果同一张图在库里两条，还带着不同的地点。
            if not await self._send_image_to_umo(
                    umo, data, prefix, quote, label="自拍",
                    prompt=prompt, scene=scene):
                return
            # 张数由生图插件自己记（draw_for 里 _mark_call），这里只记冷却时间，
            # 不重复计数——「今天发了几张」只有一个地方说了算。
            self.db.kv_set("image_share_last", now_ts())
            logger.debug("[amo] 主动分享了一张图（%s）" % ("群聊" if "GroupMessage" in umo else "私聊"))
            # 让她下一轮知道自己刚发过图，别一问三不知
            self.db.kv_set("image_share_note", {"ts": now_ts(), "text": prefix or ""})
        except asyncio.TimeoutError:
            logger.warning("[amo] 主动分享出图超时（%ss），本次跳过" % timeout)
        except Exception as exc:
            logger.debug("[amo] 主动分享失败（跳过）: %s" % exc)
        finally:
            self._share_inflight = False

    async def _share_decision(self, event):
        """判断这次要不要分享；只做判断，不出图、不发送。"""
        if not self.cfg_bool("image_share_enable", True):
            return None
        if event is None:
            return None
        private = bool(event.is_private_chat())
        # 2026-11-23（用户口径：额度 + 寝衣）：主动分享照片只在私聊发生。
        # 群里一律不自发出图——省额度，也杜绝睡衣/私密衣服被自动发到公开场合。
        if not private:
            return None
        # 情绪闸：他这轮在说扛不住/想不开，她不该挑这个时候发一张自拍。
        # 病象（11-17 09:15）：他连着说「阿墨怕是扛不过这次了」，她主动发了一张自拍。
        try:
            if self._his_gloomy_now(str(event.unified_msg_origin)):
                return None
        except Exception as exc:
            logger.debug("[amo] 主动分享情绪闸判断失败: %s" % exc)
        # 活动门控：她在吃饭 / 摸鱼 / 出去玩 / 在家才按概率发，睡觉和忙正事不发
        bucket = self._share_bucket()
        default_prob = self.SHARE_PROB_DEFAULTS.get(bucket, 0.0)
        prob = max(0.0, min(1.0, self.cfg_float("image_share_prob_" + bucket, default_prob)))
        if prob <= 0:
            return None
        # 心流给的「此刻适不适合发照片」（0~1）当乘数：心流说别发就不发
        try:
            urge = float(getattr(event, "amo_photo_urge", 1.0))
        except Exception:
            urge = 1.0
        prob *= max(0.0, min(1.0, urge))
        if prob <= 0 or random.random() >= prob:
            return None
        now = now_ts()
        allowed, used = self._image_share_quota(now, private)
        if not allowed:
            return None
        if getattr(self, "_share_inflight", False):
            return None
        plugin = self._image_plugin()
        if plugin is None:
            return None
        quote = ""
        if self.cfg_bool("image_share_quote", True):
            quote = str(getattr(getattr(event, "message_obj", None), "message_id", "") or "")
        scene = self._activity_snapshot(str(event.unified_msg_origin))
        # 2026-11-23（用户口径）：寝衣/私密衣服只在私聊，群里一律不发
        if not private:
            try:
                if self._outfit_is_private(str((scene or {}).get("outfit") or "")):
                    logger.info("[amo] 群里不发这张：现在穿的是寝衣/私密衣服")
                    return None
            except Exception as exc:
                logger.debug("[amo] 私密衣服闸判定失败: %s" % exc)
        return {
            "plugin": plugin,
            "umo": str(event.unified_msg_origin),
            "uid": str(event.get_sender_id() or ""),
            "prompt": self._image_share_prompt(scene),
            "scene": scene,
            "quote": quote,
            "now": now,
            "used": used,
        }

    async def _generate_daily_diary(self, day):
        """用当天的聊天 + 每小时日程小日记，写一篇大肥鱼口吻的日记。"""
        chat_lines = await self._diary_chat_lines(day)
        hourly_lines = self._diary_hourly_lines(day)
        if not chat_lines and not hourly_lines:
            return ""
        umo = self._last_umo or self._first_private_umo()
        try:
            persona = await self.llm.persona(umo)
        except Exception:
            persona = ""
        system = (
            (persona or "你是一个生活在中国城市的普通女孩，说话自然口语化。") +
            "\n\n你现在要保持这个人格，用自己的口吻写日记：第一人称、像真人写给自己的，"
            "不是助手汇报，也不要提 AI、模型、插件、日程表这些词。"
        )
        prompt = self._diary_prompt(day, chat_lines, hourly_lines)
        try:
            text = await self.llm.chat_raw(umo, system, prompt)
        except Exception as exc:
            logger.warning("[amo] 日记生成失败: %s" % exc)
            return ""
        text = str(text or "").strip()
        text = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        text = re.sub(r"\s*```$", "", text).strip()
        text = re.sub(r"^我的日记[^\n]*\n+", "", text)
        return text if len(text) >= 10 else ""

    async def _diary_store_tree(self):
        rows = await self._data_call("diary_list", self._data_bot_id())
        if not isinstance(rows, list) or not rows:
            return {"total": 0, "latest": "", "years": [], "root": "记忆库"}
        years = {}
        latest = ""
        for row in rows:
            day = str((row or {}).get("day") or "")
            if len(day) != 10:
                continue
            try:
                y, m, d = int(day[:4]), int(day[5:7]), int(day[8:10])
            except ValueError:
                continue
            latest = max(latest, day)
            years.setdefault(y, {}).setdefault(m, []).append({
                "date": day, "day": d,
                "title": str((row or {}).get("title") or "我的日记"),
                "chars": int((row or {}).get("chars") or 0),
                "size": int((row or {}).get("chars") or 0),
                "path": "memory:" + day,
            })
        total = 0
        tree_years = []
        for y in sorted(years, reverse=True):
            months = []
            for m in sorted(years[y], reverse=True):
                days = sorted(years[y][m], key=lambda item: item["date"], reverse=True)
                total += len(days)
                months.append({"month": m, "days": days})
            tree_years.append({"year": y, "months": months})
        return {"total": total, "latest": latest, "years": tree_years, "root": "记忆库"}

    def _diary_hourly_lines(self, day):
        """当天每小时小日记 → 「HH:MM 内容」行。"""
        try:
            cursor = self.db.conn.execute(
                "SELECT hour, text FROM schedule_diary WHERE day=? ORDER BY hour ASC",
                (day.isoformat(),),
            )
            rows = cursor.fetchall()
        except Exception:
            return []
        lines = []
        for hour, text in rows:
            text = str(text or "").strip()
            if text:
                lines.append(str(hour)[:5] + " " + text[:160])
        try:
            log = self.db.kv_get("travel_log", []) or []
            for entry in log[-10:]:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("day") or "") != day.isoformat():
                    continue
                city = str(entry.get("city") or "").strip()
                hour = str(entry.get("hour") or "").strip()
                if city and hour:
                    if entry.get("journey"):
                        lines.append(hour + " 她坐车去" + city + "陪他，路上约 2 小时")
                    elif entry.get("solo"):
                        if entry.get("back"):
                            lines.append(hour + " 她自己从" + city + "旅游回来了")
                        else:
                            lines.append(hour + " 她自己出门去" + city + "旅游，晚上住酒店")
                    elif entry.get("back"):
                        lines.append(hour + " 跟他从" + city + "回来了")
                    else:
                        lines.append(hour + " 跟他出门到了" + city + "，晚上住酒店")
        except Exception:
            pass
        try:
            rejects = self.db.kv_get("follow_reject_log", []) or []
            for entry in rejects[-5:]:
                if not isinstance(entry, dict):
                    continue
                if str(entry.get("day") or "") != day.isoformat():
                    continue
                city = str(entry.get("city") or "").strip()
                hour = str(entry.get("hour") or "").strip()
                if city:
                    lines.append(hour + " 她说想陪他去" + city + "，他说让她好好上班，她闷闷不乐")
        except Exception:
            pass
        return lines


__all__ = [
    "MODEL_LEAK_RE",
    "SELF_LEAK_RE",
    "LEAK_DEFLECTS",
    "leak_deflect_text",
    "looks_like_model_leak",
    "MediaMixin",
]
