# -*- coding: utf-8 -*-
"""Amo 终端 · 基础设施与配置（InfraMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., InfraMixin, Star) 混入，self.* 照旧可用。

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

PANEL_HIDDEN_KEYS = frozenset({"hf_judge_rules"})
def lark_quote_kwargs(is_private, message_id, sender_id, chat_id, quote):
    """飞书发送参数：决定走「引用回复」还是普通发送。

    AstrBot 的飞书适配器在 `LarkMessageEvent.send()` 里固定传
    `reply_message_id=self.message_obj.message_id`，所以不管私聊群聊、也不管
    `platform_settings.reply_with_quote`，每条消息都会变成飞书里的「回复」，
    私聊看起来就是一直在引用他上一条。

    - 私聊：普通发送（receive_id = 他的 open_id），不引用；
    - 群聊且按概率判定要引用：reply；
    - 群聊但不引用：普通发送（receive_id = 会话 chat_id）；
    - 拿不到 open_id / chat_id 时退回原来的 reply，宁可引用也别发不出去。
    """
    message_id = str(message_id or "")
    sender_id = str(sender_id or "")
    chat_id = str(chat_id or "")
    if is_private and sender_id:
        return {
            "receive_id": sender_id,
            "receive_id_type": "open_id",
            "fallback_chat_id": chat_id or None,
        }
    if quote and message_id:
        return {"reply_message_id": message_id}
    if chat_id:
        return {"receive_id": chat_id, "receive_id_type": "chat_id"}
    if message_id:
        return {"reply_message_id": message_id}
    return {}
def fetch_provider_balance(api_key, base_url, kind, timeout=8.0):
    """尽力查询供应商余额；查不到就返回 {ok: False, error}，不抛异常。

    支持：DeepSeek（/user/balance）、SiliconFlow（/v1/user/info）、
    OpenAI 兼容中转（/v1/dashboard/billing/subscription + usage，one-api/new-api 常见）。
    """
    import urllib.request

    api_key = str(api_key or "").strip()
    base = str(base_url or "").rstrip("/")
    if not api_key or not base:
        return {"ok": False, "error": "缺密钥或地址"}

    def _request(url, headers=None):
        auth = dict(headers or {})
        auth.setdefault("Authorization", "Bearer " + api_key)
        auth.setdefault("Accept", "application/json")
        request = urllib.request.Request(url, headers=auth)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    try:
        if kind == "deepseek":
            payload = _request(base + "/user/balance", {"Accept": "application/json"})
            infos = payload.get("balance_infos") or []
            chosen = None
            for item in infos:
                if str(item.get("currency") or "").upper() == "CNY":
                    chosen = item
                    break
            if chosen is None and infos:
                chosen = infos[0]
            if not isinstance(chosen, dict):
                return {"ok": False, "error": "返回里没有余额信息"}

            def money(value):
                try:
                    return round(float(value), 2)
                except (TypeError, ValueError):
                    return None

            return {
                "ok": True,
                "available": bool(payload.get("is_available")),
                "currency": str(chosen.get("currency") or "CNY"),
                "amount": money(chosen.get("total_balance")),
                "granted": money(chosen.get("granted_balance")),
                "topped_up": money(chosen.get("topped_up_balance")),
            }
        if kind == "siliconflow":
            payload = _request(base + "/v1/user/info", {"Accept": "application/json"})
            data = payload.get("data") or {}
            amount = None
            for field in ("balance", "totalBalance"):
                try:
                    amount = round(float(data.get(field)), 2)
                    break
                except (TypeError, ValueError):
                    continue
            if amount is None:
                return {"ok": False, "error": "返回里没有余额字段"}
            return {"ok": True, "currency": "CNY", "amount": amount}
        # openai 兼容中转（one-api/new-api 常见）
        subscription = _request(base + "/v1/dashboard/billing/subscription")
        hard_limit = None
        try:
            hard_limit = float(subscription.get("hard_limit_usd"))
        except (TypeError, ValueError):
            hard_limit = None
        if hard_limit is None:
            return {"ok": False, "error": "返回里没有 hard_limit_usd"}
        today = _now()
        month_start = today.replace(day=1).strftime("%Y-%m-%d")
        end_date = (today + timedelta(days=1)).strftime("%Y-%m-%d")
        used_cents = 0.0
        try:
            usage = _request(
                base + "/v1/dashboard/billing/usage?start_date=" + month_start + "&end_date=" + end_date
            )
            used_cents = float(usage.get("total_usage") or 0)
        except Exception:
            used_cents = 0.0
        remaining = round(hard_limit - used_cents / 100.0, 2)
        return {
            "ok": True,
            "currency": "USD",
            "amount": max(0.0, remaining),
            "used": round(used_cents / 100.0, 2),
            "limit": round(hard_limit, 2),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:120]}
WRITE_ROUTES = frozenset({
    "/config/save", "/config_save",
    "/voice/save",
    "/profile/save", "/profile_save",
    "/profile/delete", "/profile_delete",
    "/relation/save", "/relation_save",
    "/relation/delete", "/relation_delete",
    "/memory/add", "/memory_add",
    "/memory/delete", "/memory_delete",
    "/mood/update", "/mood_update",
    "/schedule/regen", "/schedule_regen",
    "/kb/regen", "/kb_regen",
    "/scenic_kb/regen", "/scenic_kb_regen",
    "/worldview/regen", "/worldview_regen",
    "/say",
    "/city/set",
    "/draw/test",
    "/draw/decide",
    "/refresh_status",
})


class InfraMixin:

    def _config_schema_items(self):
        schema = self._schema_map()
        items = []
        for key, meta in schema.items():
            if not isinstance(meta, dict):
                continue
            if key in FORCED_ON_CONFIG_KEYS:
                # 默认常开、关了会整块失效的开关：不在面板显示，值固定为开。
                continue
            if key in PANEL_HIDDEN_KEYS:
                # 面板不展示（配置文件仍可改）：评分规则、判定提示词这类「改错了很难查」的项
                continue
            if key.startswith("hf_"):
                group = "心流"
            elif key.startswith("voice_"):
                group = "语音"
            elif key.startswith("image_share_") or key.startswith("draw_") or key.startswith("photo_"):
                group = "照片"
            elif key.startswith("companion_") or key.startswith("memory_") or key in ("admin_uids",):
                group = "记忆"
            elif key.startswith("proactive_") or key.startswith("delay_") or key.startswith("disturb_") or key in ("quiet_hours", "auto_active_msg"):
                group = "私聊"
            elif key.startswith("period_") or key.startswith("enable_period") or key.startswith("enable_sick"):
                group = "状态"
            elif (
                key in ("timezone", "hefeng_key", "weather_city", "weather_city_name",
                        "weather_host", "weather_geo_host")
                or key.startswith("weather_alert_")
                or key.startswith("city_follow_")
                or key == "city_travel_schedule"
            ):
                group = "时间天气"
            else:
                group = "基础"
            items.append({
                "key": key,
                "type": meta.get("type", "string"),
                "description": meta.get("description") or key,
                "hint": meta.get("hint", ""),
                "default": meta.get("default"),
                "options": meta.get("options") or [],
                "special": meta.get("_special", ""),
                "group": group,
                "value": (
                    self._mask_secret(self.cfg(key, meta.get("default")))
                    if key in self.SENSITIVE_KEYS
                    else self.cfg(key, meta.get("default"))
                ),
                "configured": (
                    bool(str(self.cfg(key, "") or "").strip())
                    if key in self.SENSITIVE_KEYS
                    else True
                ),
                "sensitive": key in self.SENSITIVE_KEYS,
            })
        return items

    def _reload_config_if_changed(self):
        """AstrBot 原生插件配置页保存后，运行中的 self.config 可能不是新对象。

        读取配置文件 mtime，变化时把新值合并进当前配置，保证天气城市、
        管理员、主动私聊等动态配置不需要重启插件也能生效。
        """
        path = getattr(self.config, "config_path", "")
        if not path:
            return
        try:
            mtime = os.path.getmtime(path)
        except Exception:
            return
        if mtime <= self._config_mtime:
            return
        try:
            with open(path, encoding="utf-8-sig") as stream:
                data = json.load(stream)
            if not isinstance(data, dict):
                return
            old_engine_config = {
                key: value for key, value in self.config.items()
                if key.startswith("hf_")
            }
            self.config.update(data)
            new_engine_config = {
                key: value for key, value in self.config.items()
                if key.startswith("hf_")
            }
            if old_engine_config and old_engine_config != new_engine_config:
                self._spawn(self._apply_runtime_config())
            self._config_mtime = mtime
            if data.get("bot_name"):
                self.bot_name = str(data.get("bot_name"))
            if data.get("bot_aliases") is not None:
                self.bot_aliases = [
                    item.strip() for item in str(data.get("bot_aliases")).split(",") if item.strip()
                ]
            if self.heartflow is not None:
                self.heartflow.set_identity(self.bot_name, self.bot_aliases)
            self._persona_name_cache.clear()
            raw_admins = data.get("admin_uids", None)
            if raw_admins is not None:
                self.admin_uids = {
                    item.strip() for item in str(raw_admins).split(",") if item.strip()
                }
            start = str(data.get("period_start") or "").strip()
            if start:
                self._set_period_start(start)
            try:
                self._sync_weather_city_config()
            except Exception:
                pass
            logger.debug("[amo] 检测到插件配置变更，已重新加载")
        except Exception as exc:
            logger.debug("[amo] 重新加载插件配置失败: %s" % exc)

    def _migrate_legacy_config(self):
        """把旧版 amo_forever_config.json 合并到 Astrbot_Amo_forever_config.json。"""
        path = str(getattr(self.config, "config_path", "") or "")
        if not path:
            return
        base = os.path.dirname(path)
        legacy_candidates = [
            os.path.join(base, "amo_forever_config.json"),
            os.path.join(base, "astrbot_plugin_amo_forever_config.json"),
        ]
        legacy = next((item for item in legacy_candidates if os.path.exists(item)), "")
        if not legacy:
            return
        try:
            import shutil as _shutil
            with open(path, encoding="utf-8-sig") as stream:
                current = json.load(stream)
            with open(legacy, encoding="utf-8-sig") as stream:
                old = json.load(stream)
            if not isinstance(current, dict) or not isinstance(old, dict):
                return
            schema = {}
            try:
                with open(os.path.join(self.plugin_dir, "_conf_schema.json"), encoding="utf-8-sig") as stream:
                    schema = json.load(stream) or {}
            except Exception:
                schema = {}
            merged = {}
            for key, value in old.items():
                meta = schema.get(key) if isinstance(schema.get(key), dict) else {}
                default = meta.get("default")
                if key not in current or current.get(key) == default:
                    current[key] = value
                    merged[key] = value
            if not merged:
                return
            backup = path + ".bak-4.0.0"
            if os.path.exists(path) and not os.path.exists(backup):
                _shutil.copy2(path, backup)
            self.config.update(current)
            if hasattr(self.config, "save_config"):
                self.config.save_config()
            logger.info(
                "[amo] 已迁移旧版 amo_forever 配置: %s（%d 项）"
                % (legacy, len(merged))
            )
            logger.info("[amo] 升级提示：插件标识保持 Astrbot_Amo_forever；旧 amo_forever 配置/数据已自动迁移。")
        except Exception as exc:
            logger.warning("[amo] 旧版 amo_forever 配置迁移失败: %s" % exc)

    def _migrate_schedule_defaults(self):
        """5.1.1：位置/资产改为“人格优先、缺失随机”，清掉 5.1.0 自动写入的固定默认值。"""
        try:
            if self.db.kv_get("schedule_defaults_511", False):
                return
            auto_filled = bool(self.db.kv_get("schedule_defaults_510", False))
            changed = False
            cleared_city = False
            old_defaults = {
                "schedule_city": "贵阳",
                "schedule_home": "观山湖区·小窝",
                "schedule_workplace": "公司（贵阳·观山湖区）",
                "schedule_car": "黑色奔驰C级",
            }
            for key, value in old_defaults.items():
                if self.cfg_str(key, "").strip() == value:
                    self.config[key] = ""
                    changed = True
                    if key == "schedule_city":
                        cleared_city = True
            weather_city = self.cfg_str("weather_city", "").strip()
            if weather_city == "杭州" or ((cleared_city or auto_filled) and weather_city == "贵阳"):
                self.config["weather_city"] = ""
                changed = True
            if changed and hasattr(self.config, "save_config"):
                self.config.save_config()
            self.db.kv_set("schedule_defaults_511", True)
        except Exception as exc:
            logger.debug("[amo] 日程默认配置迁移失败: %s" % exc)

    def _safe_register(self, route, handler, methods, desc):
        # 写接口只收 POST：面板的 WRITE_ACTIONS 已经强制带 body 走 POST，
        # 老版本面板桥接没有 apiPost 时会收到 405/403，然后自动退回 fetch POST（前端有兜底）。
        # 读接口不套守卫，避免给状态轮询加额外开销。
        # 注意：route 带插件名前缀（/Astrbot_Amo_forever/...），WRITE_ROUTES 里存的是不带前缀的
        # 路径，所以要拿 desc（注册时传的 path）来判定，否则所有写路由都会被漏掉。
        path = str(desc or "")
        if path in self.DEBUG_ROUTES and not self.cfg_bool("debug_enabled", False):
            logger.debug("[amo] 调试接口没注册（debug_enabled=false）：%s" % path)
            return False
        is_write = path in WRITE_ROUTES
        if is_write:
            methods = ["POST"]
        if is_write:
            handler = self._web_guard(handler, is_write=True)
        try:
            self.context.register_web_api(route, handler, methods, desc)
            return True
        except TypeError:
            pass
        except Exception as exc:
            logger.debug("[amo] Web API 注册失败 %s: %s" % (route, exc))
            return False
        try:
            self.context.register_web_api(route, methods, desc, handler)
            return True
        except Exception as exc:
            logger.debug("[amo] Web API 兼容注册失败 %s: %s" % (route, exc))
            return False

    def _web_guard(self, handler, is_write=False):
        """写操作的前置检查：只收 POST + 拒绝跨站来源。

        这不是完整鉴权（AstrBot 侧有它自己的登录态），而是挡住
        <img src>/聊天预览/外链/跨站表单这类最容易触发的 CSRF 面。

        - 写路由在 `_safe_register` 里已经只注册 POST，这里再兜一层（防止别的注册路径漏掉）；
        - `Sec-Fetch-Site: cross-site` 直接 403（浏览器自己标的跨站，最可靠）；
        - Origin/Referer 与 Host 不一致：带 `same-origin/same-site` 的放行（反向代理/内网穿透下
          Host 常被改写），没有 Sec-Fetch-Site 的按跨站处理。
        """
        async def wrapper(*args, **kwargs):
            try:
                method = ""
                origin = ""
                host = ""
                site = ""
                headers = None
                if web_request is not None:
                    method = str(getattr(web_request, "method", "") or "").upper()
                    headers = getattr(web_request, "headers", None)
                    if headers is not None:
                        origin = str(headers.get("origin") or headers.get("referer") or "")
                        host = str(headers.get("host") or "")
                        site = str(headers.get("sec-fetch-site") or "").strip().lower()
                if is_write and method and method != "POST":
                    logger.warning("[amo] 拒绝非 POST 的 Web 写操作（%s）" % method)
                    return {"code": 403, "msg": "写操作只接受 POST（面板请刷新到最新版）"}
                if is_write and site == "cross-site":
                    logger.warning("[amo] 拒绝跨站 Web 写操作（origin=%s）" % origin)
                    return {"code": 403, "msg": "拒绝跨站请求"}
                if is_write and origin and host:
                    from urllib.parse import urlparse
                    origin_host = (urlparse(origin).hostname or "").lower()
                    allowed_hosts = {(host.split(":")[0] or "").strip().lower()}
                    if headers is not None:
                        for key in ("x-forwarded-host", "x-real-host"):
                            value = str(headers.get(key) or "").split(",")[0].strip()
                            if value:
                                allowed_hosts.add(value.split(":")[0].strip().lower())
                    allowed_hosts.discard("")
                    if origin_host and allowed_hosts and origin_host not in allowed_hosts:
                        if site in ("same-origin", "same-site"):
                            logger.debug("[amo] Web 写操作 Host 与 Origin 不一致（同源请求，放行）: %s -> %s"
                                         % (origin, host))
                        else:
                            logger.warning("[amo] 拒绝来源不一致的 Web 写操作: %s -> %s" % (origin, host))
                            return {"code": 403, "msg": "拒绝来源不一致的请求"}
            except Exception as exc:
                logger.debug("[amo] Web 守卫检查失败（放行）: %s" % exc)
            return await handler(*args, **kwargs)
        return wrapper

    def _install_lark_quote_guard(self):
        """飞书私聊不要引用：适配器把每条消息都发成「回复」。

        只装在飞书环境；装一次就够（类上留标记，热重载不会套娃）。
        群聊仍然按 `_should_quote_group()` 的概率决定引用，私聊一律普通发送。
        """
        try:
            from astrbot.core.platform.sources.lark.lark_event import LarkMessageEvent
        except Exception:
            return
        async def send(ev, message):
            try:
                is_private = bool(ev.is_private_chat())
            except Exception:
                is_private = False
            # 只认消息链里已经有的 Reply（插件按人数+概率加的那一条）；
            # 这里不能重新掷一次概率，否则「插件决定不引用」会被守卫再翻成引用。
            try:
                has_reply = any(isinstance(comp, Comp.Reply) for comp in message.chain)
            except Exception:
                has_reply = False
            quote = bool(has_reply and not is_private)
            if not quote:
                try:
                    message.chain = [comp for comp in message.chain if not isinstance(comp, Comp.Reply)]
                except Exception:
                    pass
            kwargs = lark_quote_kwargs(
                is_private,
                getattr(ev.message_obj, "message_id", ""),
                ev.get_sender_id(),
                ev.get_group_id(),
                quote,
            )
            message_type = getattr(getattr(ev.message_obj, "type", None), "value", "")
            try:
                await LarkMessageEvent.send_message_chain(
                    message, ev.bot, message_type=message_type, **kwargs,
                )
            except Exception as exc:
                if "reply_message_id" in kwargs:
                    raise
                # 普通发送失败（比如 open_id 被拒）就退回原来的引用发送，别把话吞了
                logger.warning("[amo] 飞书普通发送失败，退回引用发送: %s" % exc)
                await LarkMessageEvent.send_message_chain(
                    message, ev.bot,
                    reply_message_id=getattr(ev.message_obj, "message_id", ""),
                    message_type=message_type,
                )
            finally:
                # 父类只做 metrics 记录，不能少
                await AstrMessageEvent.send(ev, message)

        LarkMessageEvent.send = send
        LarkMessageEvent._amo_quote_guard = True
        logger.info("[amo] 飞书引用守卫已安装：私聊不引用，群聊按概率")

    def _install_qq_quote_guard(self):
        """QQ 私聊也不许引用。

        AstrBot 核心的 `reply_with_quote` 是在插件 `on_decorating_result` **之后**
        才往消息链里插 Reply 的，插件钩子里摘不干净；所以在发送前再兜一层。
        群聊保持原样（插件自己按人数 + 概率加 Reply）。
        """
        try:
            from astrbot.core.platform.sources.aiocqhttp.aiocqhttp_message_event import (
                AiocqhttpMessageEvent,
            )
        except Exception:
            return
        original = getattr(AiocqhttpMessageEvent, "_amo_original_send", None)
        if original is None:
            original = AiocqhttpMessageEvent.send
            AiocqhttpMessageEvent._amo_original_send = original

        async def send(ev, message):
            try:
                if not ev.get_group_id():
                    message.chain = [
                        comp for comp in message.chain if not isinstance(comp, Comp.Reply)
                    ]
            except Exception:
                pass
            await original(ev, message)

        AiocqhttpMessageEvent.send = send
        AiocqhttpMessageEvent._amo_quote_guard = True
        logger.info("[amo] QQ 引用守卫已安装：私聊不引用，群聊按概率")

    def _is_admin(self, event):
        uid = self._canonical_uid(event)
        if uid in self.admin_uids:
            return True
        try:
            umo = str(event.unified_msg_origin or "")
        except Exception:
            umo = ""
        # 每条消息都会走这里，get_config 没必要每次读：按会话缓存 60 秒
        cache = getattr(self, "_admin_cache", None)
        if cache is None:
            cache = {}
            self._admin_cache = cache
        now = time.time()
        hit = cache.get(umo)
        if hit and now - hit[0] < 60:
            return uid in hit[1]
        try:
            cfg = self.context.get_config(umo)
            admins = cfg.get("admins_id", []) if cfg else []
            if isinstance(admins, str):
                admins = [item.strip() for item in admins.split(",") if item.strip()]
            names = {str(item) for item in (admins or [])}
        except Exception:
            names = set()
        cache[umo] = (now, names)
        return uid in names

    async def _ensure_ready(self):
        if self._ready:
            return
        async with self._init_lock:
            if self._ready:
                return
            try:
                await asyncio.to_thread(self.db.init)
            except Exception as exc:
                logger.error("[amo] 数据库初始化失败: %s" % exc)
            self._migrate_proactive_timing()
            self._migrate_typing_defaults()
            self._migrate_legacy_admin_default()
            self._migrate_scenic_kb_name()
            self._migrate_schedule_defaults()
            self._migrate_diary_continuity()
            self._apply_forced_on_config()
            self._cleanup_legacy_memory_profiles()
            await asyncio.to_thread(self._merge_alias_profiles)
            self.state = HumanState(self)
            try:
                await self._sync_with_data_plugin()
            except Exception as exc:
                logger.debug("[amo] 与数据插件同步失败: %s" % exc)
            self._ready = True
            self._loop_task = self._spawn(self._background_loop())
            self._spawn(self._warm_up())

    def _body_tag_block(self, satiety: float, hydration: float, hungry_at: float) -> str:
        """本能模式的身体事实：只有数值，没有台词，带 ts。"""
        try:
            last = self.db.kv_get("last_meal", {}) or {}
        except Exception:
            last = {}
        last_meal = "None"
        try:
            age = now_ts() - float(last.get("ts") or 0)
        except Exception:
            age = 1e9
        if last and age < 6 * 3600:
            last_meal = "%s（%d分钟前）" % (
                str(last.get("dish") or "吃了点东西"), max(1, int(age // 60)))
        fields = {
            "Hunger": round(100.0 - satiety, 1),
            "Thirst": round(100.0 - hydration, 1),
            "Satiety": round(satiety, 1),
            "Hydration": round(hydration, 1),
            "Last_Meal": last_meal,
        }
        if _label_bus is not None:
            lines = [_label_bus.format_tag("Body", fields, ts=now_ts())]
        else:  # 兜底：标签模块没加载也不能空着
            lines = ["[Body: Hunger=%.1f, Thirst=%.1f, Satiety=%.1f, Hydration=%.1f]"
                     % (fields["Hunger"], fields["Thirst"],
                        fields["Satiety"], fields["Hydration"])]
        if satiety < hungry_at:
            menu = self._food_menu()
            if menu:
                lines.append("【现在能吃的（价格来自金融）】" + menu)
        return "\n" + "\n".join(lines)

    def _group_roster(self, umo, current_uid="", limit=8):
        """群里最近说过话的人：uid → 称呼 / 关系 / 聊过多少句。

        让她在群里先认人：谁在说话、和她什么关系、该用什么语气，而不是把所有人都当同一个人。
        """
        roster = []
        seen = set()
        try:
            rows = self._recent(umo, 40)
        except Exception:
            return roster
        for row in rows:
            if str(row.get("role") or "") != "user":
                continue
            uid = str(row.get("uid") or "")
            if not uid or uid in seen:
                continue
            seen.add(uid)
            profile = {}
            try:
                profile = self.db.get_profile(uid) or {}
            except Exception:
                profile = {}
            name = (
                str(profile.get("alias") or "").strip()
                or str(profile.get("name") or "").strip()
                or str(row.get("name") or "").strip()
                or uid
            )
            relation = str(profile.get("relation") or "普通")
            msg_count = to_int(profile.get("msg_count"), 0)
            roster.append({
                "uid": uid,
                "name": name,
                "relation": relation,
                "msg_count": msg_count,
                "current": bool(current_uid) and uid == str(current_uid),
            })
            if len(roster) >= max(1, int(limit)):
                break
        roster.sort(key=lambda item: (not item["current"], -item["msg_count"]))
        return roster

    def _provider_inventory(self):
        """读取 AstrBot 已配置的对话供应商；只返回脱敏信息，绝不回传密钥。"""
        items = []
        try:
            providers = self.context.get_all_providers() or []
        except Exception:
            providers = []
        for provider in providers:
            config = getattr(provider, "provider_config", None) or {}
            pid = str(config.get("id") or "")
            if not pid:
                continue
            model = ""
            try:
                model = str(provider.get_model() or "")
            except Exception:
                model = str(config.get("model") or "")
            api_base = str(config.get("api_base") or config.get("url") or "").strip()
            key = config.get("key") or ""
            if isinstance(key, list):
                has_key = any(str(item or "").strip() for item in key)
            else:
                has_key = bool(str(key or "").strip())
            items.append({
                "id": pid,
                "model": model,
                "type": str(config.get("type") or ""),
                "enable": config.get("enable", True) is not False,
                "has_key": has_key,
                "api_base": api_base,
            })
        return items

    async def _provider_balances_cached(self, providers):
        """逐个探测供应商余额；60 秒缓存，失败不阻塞面板。"""
        now = time.time()
        signature = "|".join(sorted(
            item["id"] + ":" + item["api_base"] + ":" + str(item["has_key"]) for item in providers
        ))
        cache = getattr(self, "_provider_balance_cache", None)
        if (
            isinstance(cache, dict)
            and now - to_float(cache.get("at"), 0) < 60
            and cache.get("signature") == signature
        ):
            return cache.get("data") or []
        enabled = [item for item in providers if item["enable"] and item["has_key"] and item["api_base"]]

        def probe(item):
            kind = self._balance_probe_kind(item["api_base"])
            key = self._provider_api_key(item)
            result = {"id": item["id"], "model": item["model"], "kind": kind}
            if not key:
                result.update({"ok": False, "error": "未配置密钥"})
                return result
            data = fetch_provider_balance(key, item["api_base"], kind)
            data["id"] = item["id"]
            data["model"] = item["model"]
            data["kind"] = kind
            return data

        results = []
        if enabled:
            def run_all():
                return [probe(item) for item in enabled]

            try:
                results = await asyncio.to_thread(run_all)
            except Exception as exc:
                logger.debug("[amo] 供应商余额探测失败: %s" % exc)
                results = []
        self._provider_balance_cache = {"at": now, "signature": signature, "data": results}
        return results


__all__ = [
    "PANEL_HIDDEN_KEYS",
    "lark_quote_kwargs",
    "fetch_provider_balance",
    "WRITE_ROUTES",
    "InfraMixin",
]
