# -*- coding: utf-8 -*-
"""Amo 终端 · 穿搭与衣柜（OutfitMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., OutfitMixin, Star) 混入，self.* 照旧可用。

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



class OutfitMixin:

    def _outfit_change_request(self, text):
        """「换上那条蓝裙子」→ 返回衣服名；不是在说换装就返回空。"""
        body = str(text or "").strip()
        if not body or len(body) > 80:
            return ""
        wants_change = bool(self.OUTFIT_CHANGE_RE.search(body))
        if not wants_change:
            # 「今天穿白衬衫」也算，但必须提到衣服，避免「穿得好看」误触
            if "穿" not in body or not any(word in body for word in self.CLOTHES_WORDS):
                return ""
        store = getattr(self, "wardrobe", None)
        if store is not None:
            try:
                hit = store.match_text(body)
                if hit:
                    return hit["name"]
            except Exception:
                pass
        # 库里没有：从原话里抠一个像衣服的短描述
        match = re.search(
            r"(?:换上|换成|穿|换)(?:上|一件|一条|一身|一套|那件|这件)?\s*"
            r"([\u4e00-\u9fa5A-Za-z0-9，、]{2,18}?)(?:吧|呀|啊|了|好不好|行不行|[。！？!?]|$)",
            body,
        )
        if not match:
            return ""
        candidate = match.group(1).strip("，、 ")
        for filler in ("那条", "这条", "那件", "这件", "那套", "这套", "一身", "一套"):
            if candidate.startswith(filler) and len(candidate) > len(filler):
                candidate = candidate[len(filler):].strip("，、 ")
        if len(candidate) < 2:
            return ""
        if not any(word in candidate for word in self.CLOTHES_WORDS):
            return ""
        return candidate[:20]

    async def _promise_change_outfit(self, style, want=""):
        """答应穿那一款拍：在家就真换上（提了白色优先白袜那套），换来那套给照片用。"""
        engine = getattr(self, "outfits", None)
        if engine is None or not style:
            return ""
        try:
            activity = self.state.current_activity() or {}
        except Exception:
            activity = {}
        if not at_home(activity):
            return ""
        camp = engine.style_camp(want) or engine.style_camp(style) or style
        set_name = ""
        try:
            names = engine.find_sets(camp, exclude=engine.current_set())
            if "白" in str(want or ""):
                white = [name for name in names
                         if any("白" in str(row.get("name") or "")
                                for row in (engine.sets().get(name) or []))]
                names = white or names
            if names:
                set_name = names[0]
        except Exception as exc:
            logger.debug("[amo] 兑现承诺挑衣服失败: %s" % exc)
        try:
            result = await self._change_outfit_now(camp, set_name=set_name)
        except Exception as exc:
            logger.debug("[amo] 兑现承诺换装失败: %s" % exc)
            return ""
        if isinstance(result, dict) and result.get("ok"):
            return str(result.get("look") or "")
        return ""

    async def _fulfill_outfit_pending(self):
        """在外面答应「回家换」的：到家后真的换，并留一句事实给她。"""
        try:
            data = self.db.kv_get("outfit_pending", {}) or {}
        except Exception:
            return ""
        if not isinstance(data, dict) or not data.get("style"):
            return ""
        if str(data.get("day") or "") != today_str():
            try:
                self.db.kv_set("outfit_pending", {})
            except Exception:
                pass
            return ""
        try:
            activity = self.state.current_activity() or {}
        except Exception:
            activity = {}
        if not at_home(activity):
            return ""
        style = str(data.get("style") or "")
        result = await self._change_outfit_now(style)
        try:
            self.db.kv_set("outfit_pending", {})
        except Exception:
            pass
        if not result.get("ok"):
            return ""
        return ("【换装】你答应他回家换「%s」，现在到家已经换上了：%s。"
                % (style or "一套", result.get("look") or ""))

    def _outfit_request_style(self, text):
        """他这句是不是在要她换衣服；是就返回款式（只说「换一套」返回「一套」）。

        他自己的事（「我想换一套衣服」）、聊换衣服但没要求（「换衣服的话穿哪件」）
        都不算，免得凭空塞一条换装提示。
        """
        body = str(text or "").strip()
        if not body or len(body) > 100:
            return ""
        if re.match(r"^(我|咱|我们)", body):
            return ""
        match = self.OUTFIT_REQUEST_RE.search(body)
        if not match:
            return ""
        tail = re.split(r"[。！？!?，,]", body[match.end():], 1)[0].strip()
        for word in ("给我看看", "给我看", "看看", "看一下", "好吗", "好不好", "行吗", "吧", "呀", "啊"):
            if tail.endswith(word):
                tail = tail[:-len(word)].strip()
        tail = tail.strip("的了吧呀啊哦嘛 ")
        if tail and any(word in tail.lower() for word in self.OUTFIT_STYLE_WORDS):
            return tail[:20]
        # 「换jk」这种款式就写在前缀里，匹配段本身带款式
        extra = re.sub(r"^换", "", match.group(0)).strip()
        if extra and extra not in ("一套", "一件", "一身") and any(
                word in extra.lower() for word in self.OUTFIT_STYLE_WORDS):
            return extra[:20]
        return "一套"

    async def _outfit_request_hint(self, event):
        """他要她换衣服：只给事实（在家/在外面、衣柜里有什么）；换不换她自己定。"""
        style = self._outfit_request_style(getattr(event, "message_str", "") or "")
        if not style:
            return ""
        try:
            event.amo_outfit_request = style
        except Exception:
            pass
        engine = getattr(self, "outfits", None)
        if engine is None:
            return ""
        try:
            activity = self.state.current_activity() or {}
        except Exception:
            activity = {}
        if not at_home(activity):
            return ("【换装】他想让你换「%s」，你现在在%s，换不了衣服；回家以后才能换。"
                    % (style, str(activity.get("place") or "外面")))
        names = engine.find_sets(style, exclude=engine.current_set())
        lines = ["【换装】他想让你换「%s」，你现在在家。" % style]
        if names:
            lines.append("衣柜里这类有：" + "、".join(names[:8]) + "（挑一套就是整套穿）。")
        else:
            lines.append("衣柜里没有这类；市场有的话可以自己去买。")
        lines.append("换不换、穿哪套你自己定。")
        return "".join(lines)

    def _complete_outfit(self, value):
        """把「只写了半套」的穿搭按套名补成整套。

        2026-11-16：14:01 那张提示词里只有「穿着汉服·雪霁｜对襟褙子」，裙、袜、鞋
        都没写，模型自己补成抹胸；17:23 那张又只写三件。日程本身是完整的四件套，
        所以这里是「某一格被写残了」的兜底：补不上就原样返回，绝不编衣服。
        """
        text = str(value or "").strip()
        if not text:
            return ""
        pieces = [item.strip() for item in re.split(r"[，,]", text) if item.strip()]
        heads = {item.split("｜", 1)[0].strip() for item in pieces if "｜" in item}
        if len(heads) != 1 or len(pieces) >= 3:
            return text
        engine = getattr(self, "outfits", None)
        compose = getattr(engine, "compose_set", None) if engine is not None else None
        if not callable(compose):
            return text
        try:
            full = str(compose(next(iter(heads))) or "").strip()
        except Exception as exc:
            logger.debug("[amo] 补齐整套穿搭失败: %s" % exc)
            return text
        if not full:
            return text
        logger.info("[amo] 穿搭只有半套，按套名补整：%s -> %s" % (text[:40], full[:60]))
        return full

    async def _change_outfit_now(self, style="", set_name=""):
        """她答应换：从衣柜挑一整套，写进今天（从现在穿到今晚睡觉）。"""
        engine = getattr(self, "outfits", None)
        if engine is None:
            return {"ok": False, "reason": "穿搭引擎不可用"}
        text = str(style or "").strip()
        if not text or text in ("一套", "衣服", "换一套", "随便"):
            text = "换一套衣服"
        set_name = str(set_name or "").strip() or engine.pick_set(
            text, exclude=engine.current_set(), seed=str(now_ts()))
        if not set_name:
            return {"ok": False, "reason": "衣柜里没有", "hint": self._outfit_market_hint(text)}
        look = engine.compose_set(set_name) or set_name
        ok, place = engine.can_change_to(look)
        if not ok:
            return {"ok": False, "reason": "现在在%s，贴身衣物不能换" % place, "outside": True}
        day = today_str()
        engine.change_outfit(day, look, from_hour=time.strftime("%H:00"),
                             note="换装：%s" % text[:40])
        self._rewrite_today_schedule(day)
        try:
            engine.remember_camp(engine.camp_of(set_name))
        except Exception:
            pass
        logger.info("[审批] 换装放行（%s）：%s" % (text, look))
        return {"ok": True, "look": look, "set": set_name}

    async def _reseed_wardrobe_from_market(self) -> None:
        """衣柜按内置汉服/JK 套装重建；只在版本标记不对时做一次，旧衣服全清。"""
        if self.wardrobe is None:
            return
        # 版本标记没变、库里也有衣服：不重建。
        # 以前每次启动都重建 120 件并重排今天，她手改的日程/穿搭会被冲掉。
        try:
            if (str(self.db.kv_get("wardrobe_seed", "")) == self.WARDROBE_SEED
                    and self.wardrobe.count() > 0):
                return
        except Exception:
            pass
        items = (list(hanfu_jk_items())
                 if hanfu_jk_items is not None else [])
        if not items:
            return
        # 保留她自己在市场买的衣服：只补内置套装，不整库清空
        try:
            existing = self.wardrobe.items() or []
        except Exception:
            existing = []
        names = {str(row.get("name") or "") for row in items}
        for row in existing:
            name = str(row.get("name") or "")
            # 只保留她在市场买的；旧版 108 件现代衣服不再带回来
            if not name or name in names:
                continue
            # 只有真正在 market 买过的（amo_buy 写「市场买」）才保留；
            # 旧版「市场目录」播种的现代衣服不再带回来
            if str(row.get("note") or "") != "市场买":
                continue
            # 2026-11-21：丝袜全部下架，买过的也不再带回来（出图必被拒）
            if "丝袜" in name:
                continue
            items.append(row)
            names.add(name)
        try:
            await self.wardrobe.replace_all(items)
        except Exception as exc:
            logger.warning("[amo] 衣柜重建失败: %s" % exc)
            return
        # 重建只是写库：Wardrobe 读的是内存快照，不 refresh 的话 pool 还是空的，
        # 日程里就一个 outfit 都写不上（今天这一批踩到的就是这个）。
        try:
            await self.wardrobe.refresh(force=True)
            logger.info("[amo] 衣柜快照已刷新：%d 件" % self.wardrobe.count())
        except Exception as exc:
            logger.warning("[amo] 衣柜快照刷新失败: %s" % exc)
        # 衣柜重建后按新衣服重排今天。
        # 2026-11-21：不再清「私密」override——那是撤私密功能时的旧逻辑，
        # 11-20 私密 10 套已经回来了；她在家里选的私密套不能被重建顺手抹掉。
        try:
            self._rewrite_today_schedule(today_str())
        except Exception as exc:
            logger.debug("[amo] 重建衣柜后重排今日日程失败: %s" % exc)
        self.db.kv_set("wardrobe_seed", self.WARDROBE_SEED)
        logger.info("[amo] 衣柜已重建（内置汉服/JK）：%d 件" % len(items))


__all__ = [
    "OutfitMixin",
]
