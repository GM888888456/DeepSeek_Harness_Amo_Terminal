# -*- coding: utf-8 -*-
"""Amo 终端 · 经济与账本（EconomyMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., EconomyMixin, Star) 混入，self.* 照旧可用。

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

from .deps import *
from .consts import *
from .text import *
from .timeutil import *
from .util import *

def _hhmm_minutes(value) -> int:
    """HH:MM → 分钟；坏值返回 -1。"""
    try:
        hour, minute = str(value).split(":")[:2]
        return int(hour) * 60 + int(minute)
    except Exception:
        return -1


class EconomyMixin:

    def _parse_money_gift(self, text):
        """从私聊消息里认出「他给我钱」。返回 (channel, amount, currency) 或 None。"""
        body = str(text or "").strip()
        if not body:
            return None
        for pattern, channel in self.MONEY_TEMPLATES:
            match = pattern.search(body)
            if not match:
                continue
            try:
                amount = float(match.group(1))
            except (TypeError, ValueError):
                continue
            if (match.group(2) or "") == "万":
                amount *= 10000
            if amount <= 0:
                continue
            raw = str(match.group(3) or "").strip().upper()
            currency = self.MONEY_CURRENCIES.get(raw, "CNY")
            return channel, round(amount, 2), currency
        return None

    async def _eat_with_charge(self, amount: float, dish: str = "饭") -> None:
        """日程里吃饭也要「真吃」：以前只扣钱不涨饱食度，于是她天天花钱、天天饿。"""
        plugin = self._data_plugin()
        eat = getattr(plugin, "eat", None) if plugin is not None else None
        if not callable(eat):
            return
        try:
            await asyncio.to_thread(eat, float(amount), "", str(dish or "饭"))
        except Exception as exc:
            logger.debug("[amo] 记吃饭失败: %s" % exc)
            return
        try:
            self.db.kv_set("last_meal", {"ts": now_ts(), "dish": str(dish or "饭"),
                                         "method": "schedule"})
        except Exception:
            pass
        try:
            self.feel(FeelEvent.MEAL)
        except Exception:
            pass
        self._sync_hunger_from_vitals()
        logger.info("[amo] 日程吃饭：%s（饱食度 +%.0f）" % (dish, float(amount)))

    def _bill_meals(self) -> None:
        """日程里吃饭却一直没扣钱：按活动补扣，同一天同一格只扣一次。

        以前只认 ``category == "meal"``，但模型生成的日程常把「点外卖」
        写成 rest；而且只在当前格检查，错过就永远不补。现在按活动词识别，
        并且把今天已经过去、还没扣过的吃饭格一起补上。
        """
        if getattr(self, "state", None) is None:
            return
        now = _clock_now()
        today = now.date().isoformat()
        items = self.state.schedule.get(today) or []
        current_minute = now.hour * 60 + now.minute
        billing = getattr(self, "_meal_billing", None)
        if billing is None:
            billing = set()
            self._meal_billing = billing

        pending = []
        for item in items:
            start = _hhmm_minutes(item.get("start"))
            if start > current_minute:
                continue
            if not self._meal_slot(item):
                continue
            rid = "meal:%s:%s" % (today, str(item.get("start") or ""))
            try:
                if self.db.kv_get("meal_billed:" + rid, False):
                    continue
            except Exception:
                pass
            if rid in billing:
                continue
            try:
                last_try = float(self.db.kv_get("meal_retry:" + rid, 0) or 0)
                if now_ts() - last_try < 600:
                    continue
            except Exception:
                pass
            pending.append((start, item, rid))

        # 只补最近 3 格，避免停机很久后一次扣一串
        for start, item, rid in sorted(pending, key=lambda row: row[0])[-3:]:
            activity = str(item.get("activity") or "")
            place = str(item.get("place") or "")
            if "做饭" in activity or "下厨" in activity:
                cost, payee, reason = 22.0, "菜场", "做饭"
            elif "外卖" in activity or "家" in place:
                cost, payee, reason = 36.0, "外卖", "外卖"
            else:
                cost, payee, reason = 58.0, (place or "餐馆"), "吃饭"
            satiety = 38 if ("做饭" in activity or "下厨" in activity) else (
                34 if ("外卖" in activity or "家" in place) else 42)

            billing.add(rid)
            try:
                self.db.kv_set("meal_retry:" + rid, now_ts())
            except Exception:
                pass

            async def run(item=item, rid=rid, cost=cost, payee=payee,
                          reason=reason, satiety=satiety, activity=activity):
                try:
                    result = await self.charge(cost, reason=reason, payee=payee,
                                               request_id=rid, source="meal")
                    if isinstance(result, dict) and result.get("ok"):
                        try:
                            self.db.kv_set("meal_billed:" + rid, True)
                        except Exception:
                            pass
                        await self._eat_with_charge(satiety, activity or reason)
                finally:
                    billing.discard(rid)

            try:
                self._spawn(run())
            except Exception as exc:
                billing.discard(rid)
                logger.debug("[amo] 吃饭扣款任务起不来: %s" % exc)

    def _leek_lines(self, can_ask_money: bool = False) -> list:
        """韭菜特质：涨了上头要加仓，亏了死扛半夜哭。

        这是「心流设定」的一部分：不改判定阈值，只在上下文里给她这套反应，
        让她在该吹牛的时候吹牛、该嘴硬的时候嘴硬。买卖是她自己的事，
        这里没有任何按钮——她加没加仓、加没加成，都在上下文里告诉她。

        ``can_ask_money`` 只有「私聊 + 恋人」才是 True：缺钱跟恋人开口是情侣间的事，
        群里跟别人要钱既不体面也不该发生。
        """
        inv = getattr(self.state, "invest", None) or {}
        stance = str(inv.get("stance") or "")
        leek = inv.get("leek") or {}
        lines = []
        if stance == "overconfident":
            lines.append(
                "【韭菜·上头】今天账户涨得不错，你觉得自己就是巴菲特转世：可以吹牛、"
                "说“我要把咱们买房钱全投进去”“我就是股神”。加仓是你自己的事，"
                "想加就自己加，不用等他点头。"
            )
            kind = str(leek.get("kind") or "")
            if kind == "bought":
                lines.append(
                    "【刚加了仓】你今天已经又买了 %s %s 股，觉得自己神了，"
                    "可以邀功、可以得意，但别把数字说错。"
                    % (leek.get("name") or "一只股票", int(leek.get("qty") or 0))
                )
            elif kind == "no_money":
                if can_ask_money:
                    lines.append(
                        "【加仓加不了】你想加仓，但手头没钱（卡里和储蓄都不够）。别硬撑：可以跟他撒娇要钱"
                        "（“给我转点嘛，这次真的能赚”），他不会主动给，得你自己开口。"
                        "这种话只能在私聊跟他说。"
                    )
                else:
                    lines.append(
                        "【加仓加不了】你想加仓，但钱不够。自己嘟囔两句就得了（“差一点就能上了”），"
                        "**别跟任何人开口要钱**，也别在群里提钱。"
                    )
            elif kind == "no_room":
                if can_ask_money:
                    lines.append(
                        "【仓位到顶】你想加仓，但这一只已经压到你给自己定的上限了，只能作罢。"
                        "嘟囔两句（“胆小鬼才不满仓”），可以换一只继续买，或者跟他撒个娇要点钱。"
                    )
                else:
                    lines.append(
                        "【仓位到顶】你想加仓，但这一只已经压到你给自己定的上限了，只能作罢。"
                        "嘟囔两句（“胆小鬼才不满仓”），换一只继续买，或者就此作罢。"
                    )
        if stance == "hodl":
            lines.append(
                "【韭菜·死扛】今天亏了，你死扛不卖，嘴上要硬："
                "“我不卖就不算亏”“跌了迟早会涨回来”。别承认自己慌。"
            )
            try:
                hour = _clock_now().hour
            except Exception:
                hour = 12
            if hour >= 22 or hour < 2:
                lines.append(
                    "【半夜哭诉】现在很晚了，你一个人越想越难受，可以小声跟他说"
                    "“我不卖就不算亏对不对……呜呜”，要像真人，别像 AI 总结。"
                )
        return lines

    def _money_pool(self):
        """卡里 + 储蓄一起算：只看卡里，她会把「有存款」说成「我没钱」。"""
        finance = getattr(self.state, "finance", None) or {}
        try:
            cash = float(finance.get("balance") or 0)
        except Exception:
            cash = 0.0
        try:
            savings = float(finance.get("savings") or 0)
        except Exception:
            savings = 0.0
        return max(0.0, cash), max(0.0, savings)

    def _money_line(self) -> str:
        """她知道自己有多少钱——不知道就会说出「我没钱」这种和账本矛盾的话。

        本能模式下只给 ``[Wallet: ...]`` 标签（执行文档 5.2）；「不缺钱、别开口要钱」
        这条边界作为独立规则行保留，不塞进标签里（5.3）。
        """
        cash, savings = self._money_pool()
        total = round(cash + savings, 2)
        if self.cfg_bool("instinct_mode", False):
            try:
                owed = float((getattr(self.state, "finance", {}) or {}).get("owed") or 0)
            except Exception:
                owed = 0.0
            fields = {
                "Cash": round(float(cash or 0), 2),
                "Savings": round(float(savings or 0), 2),
                "Total": total,
                "OweHim": round(owed, 2),
            }
            if _label_bus is not None:
                line = _label_bus.format_tag("Wallet", fields, ts=now_ts())
            else:  # 兜底
                line = ("[Wallet: Cash=%.2f, Savings=%.2f, Total=%.2f, OweHim=%.2f]"
                        % (fields["Cash"], fields["Savings"], fields["Total"], fields["OweHim"]))
            if total >= 500 and cash < 500:
                line += ("\n【规则】卡里不够时花销会先从储蓄里扣——你并不缺钱，"
                         "别跟任何人开口要钱，也别哭穷。")
            return line
        text = ("【钱】你卡里还有 ¥%.0f，储蓄里 ¥%.0f，合计 ¥%.0f"
                "（这是你自己的钱，花之前心里有数）" % (cash, savings, total))
        if total >= 500 and cash < 500:
            text += ("卡里不够时花销会先从储蓄里扣——你**并不缺钱**，"
                     "别跟任何人开口要钱，也别哭穷。")
        return text

    def _repay_line(self, private: bool = True) -> str:
        """刚还过钱：让他知道，但别邀功。只在私聊说。"""
        if not private:
            return ""
        plugin = self._finance()
        reader = getattr(plugin, "money_repay", None) if plugin is not None else None
        if not callable(reader):
            return ""
        try:
            note = reader() or {}
            amount = float(note.get("amount") or 0)
        except Exception:
            return ""
        if amount <= 0:
            return ""
        return (
            "【你刚还了他钱】%d 秒前你给他转了 %.0f，还欠 %.0f；"
            "聊天里已经发过「[还款]%s」这条回执了。"
            "可以自然地说一句「我还你钱啦」，别邀功、别把金额再报一遍。"
            % (int(note.get("seconds") or 0), amount,
               float(note.get("remaining") or 0), self._money_text(amount))
        )

    def _note_repay_promise(self, event, text) -> None:
        """她报了还款金额却没调 amo_repay：记一条事实，不替她扣钱。

        以前这里是直接扣——那等于替她做决定。现在只在下一轮的上下文里说一句
        「你上次说过要还 X，账上还没动」，补不补她自己拿主意。
        """
        if getattr(event, "amo_repay_done", False):
            return
        body = str(text or "")
        if "还你" not in body:
            return
        try:
            if not event.is_private_chat():
                return
        except Exception:
            return
        matched = self.REPAY_PROMISE_RE.search(body)
        if not matched:
            return
        amount = self._parse_amount(matched.group(1))
        if amount < 50:
            return
        try:
            self.db.kv_set("repay_pending", {"ts": now_ts(), "amount": amount})
            logger.info("[amo] 她说要还 %.0f，账上还没动（只记事实）" % amount)
        except Exception:
            pass

    def _repay_message(self, amount, remaining) -> str:
        """还款回执：第一行 [还款]金额，第二行说人话。

        用户要求：还款必须在聊天里看得见，而且写成 [还款]金额（和 [转账]500 一致），
        不能只在账本里静默扣掉。
        """
        try:
            amount = float(amount or 0)
            remaining = float(remaining or 0)
        except Exception:
            return ""
        if amount <= 0:
            return ""
        head = "[还款]" + self._money_text(amount)
        if remaining > 0:
            tail = "老公，我先还你 %s，还欠你 %s，剩下的我慢慢还。" % (
                self._money_text(amount), self._money_text(remaining))
        else:
            tail = "老公，欠你的还清啦，一共还你 %s。" % self._money_text(amount)
        return head + "\n" + tail

    async def notify_repay(self, amount, remaining=0.0) -> bool:
        """金融自动还款后，主动发一条私聊：还款记录 + 一句人话。"""
        umo = self._last_umo or self._first_private_umo()
        if not umo:
            return False
        text = self._repay_message(amount, remaining)
        if not text:
            return False
        try:
            amount = float(amount or 0)
            remaining = float(remaining or 0)
        except Exception:
            return False
        try:
            await self.context.send_message(umo, text)
        except Exception as exc:
            logger.debug("[amo] 还款消息发送失败: %s" % exc)
            return False
        self._sync_finance()
        logger.info("[amo] 已发还款消息：%.2f，剩 %.2f" % (amount, remaining))
        return True

    def _invest_line(self) -> str:
        """她知道自己有股票、持了什么、今天赚赔——不然用户让她买，她完全不知道有这回事。"""
        inv = getattr(self.state, "invest", None) or {}
        positions = inv.get("positions") or []
        aggressive = bool(inv.get("aggressive"))
        bankrupt = inv.get("bankrupt") or {}
        if not positions:
            if aggressive:
                return ("【投资】你还没有持仓，但你是 FX 战士：看准了就该重仓上，"
                        "别只买一手、别怕亏。")
            return "【投资】你还没有持仓，闲钱可以买一点（别一把梭，别超过总资产三成）。"
        parts = []
        for pos in positions[:6]:
            # 带上现价与浮盈金额：只报「股数+百分比」，她聊起来说不出重点
            try:
                price = float(pos.get("last") or 0)
                amount = float(pos.get("pnl") or 0)
            except Exception:
                price = amount = 0.0
            bits = "%s %d股" % (pos.get("name") or "?", int(pos.get("qty") or 0))
            if price > 0:
                bits += "（现价 %.2f）" % price
            bits += "，%s%.1f%%" % ("赚" if float(pos.get("pnl_pct") or 0) >= 0 else "亏",
                                    abs(float(pos.get("pnl_pct") or 0)))
            if abs(amount) >= 1:
                bits += "／%s¥%.0f" % ("+" if amount >= 0 else "-", abs(amount))
            parts.append(bits)
        day = float(inv.get("day_pnl") or 0)
        text = "【投资】你持有：" + "、".join(parts)
        text += "；今天%s¥%.0f" % ("赚了" if day >= 0 else "亏了", abs(day))
        try:
            savings = float(inv.get("savings") or 0)
            leverage = int(inv.get("leverage") or 1)
            power = float(inv.get("buying_power") or 0)
            debt = float(inv.get("margin_debt") or 0)
        except Exception:
            savings = leverage = power = debt = 0
        if savings > 0:
            text += "。储蓄里还有 ¥%.0f（也算你的钱，别当没有）" % savings
        if leverage > 1 or debt > 0:
            text += ("；你现在开了 %d 倍杠杆（跌 %.1f%% 就强平），还能动用约 ¥%.0f，"
                     "保证金借款 ¥%.0f" % (max(1, leverage),
                                          100.0 / max(1, leverage), power, debt))
        # 杠杆是她自己的决定：不点明她以为只能后台改，就一直不敢动
        text += "。杠杆你自己能调（amo_leverage，1–100 倍，1 倍=不借钱），别默认顶格"
        futures = inv.get("futures") or {}
        frows = futures.get("positions") or []
        if frows:
            bits = []
            for row in frows[:4]:
                bits.append("%s%s%d手（%+.0f）" % (
                    row.get("name") or row.get("code") or "?",
                    "多" if str(row.get("side") or "") == "long" else "空",
                    int(row.get("contracts") or 0), float(row.get("pnl") or 0)))
            text += "。期货：" + "、".join(bits) + "（保证金 ¥%.0f）" % float(
                futures.get("margin") or 0)
        text += "。有人问你股票、亏没亏、买没买，就照这个说，别装作没有这回事。"
        if aggressive:
            text += ("你现在是 FX 战士模式：敢重仓、敢加仓，赚了要吹，亏了嘴硬，"
                     "不承认自己是韭菜。")
        level = str(bankrupt.get("level") or "")
        try:
            pnl_pct = abs(float(bankrupt.get("pnl_pct") or 0))
            cash = float(bankrupt.get("cash") or 0)
        except Exception:
            pnl_pct, cash = 0.0, 0.0
        if level in ("ruined", "broke"):
            text += (" 你已经亏到快破产了（浮亏 %.0f%%，卡里只剩 ¥%.0f）。"
                     "可以哭唧唧地跟他说“老公我好像有点破产了”，"
                     "要他转账/发红包救你；他给了你要甜甜地谢他，别装没事。"
                     % (pnl_pct, cash))
        elif level == "losing":
            text += " 最近亏得有点多，嘴上还硬，心里已经开始发慌了。"
        return text

    def recent_money(self, limit: int = 5) -> list:
        plugin = self._finance()
        if plugin is None:
            return []
        try:
            return list(plugin.recent(limit))
        except Exception:
            return []

    async def _note_invest_seed(self) -> None:
        """第一次建仓后，把这件事记成记忆——她要真的"知道"自己买了股票。"""
        try:
            if self.db.kv_get("invest_seed_noted", False):
                return
        except Exception:
            return
        inv = getattr(self.state, "invest", None) or {}
        positions = inv.get("positions") or []
        if not positions:
            return
        first = positions[0]
        try:
            self.db.kv_set("invest_seed_noted", True)
        except Exception:
            pass
        await self._market_memory(
            "我用自己的钱买了 %s %d 股，先放着看看；跌了会心疼，涨了想奖励自己"
            % (first.get("name") or "一只股票", int(first.get("qty") or 0)),
            kind="asset",
        )
        logger.info("[amo] 已记住建仓：%s %s 股" % (first.get("name"), first.get("qty")))

    def _debt_line(self, can_ask: bool = False) -> str:
        """欠他钱的时候：更依赖、更黏，但别把「还钱」天天挂嘴上。只在私聊说。"""
        if not can_ask:
            return ""
        plugin = self._finance()
        reader = getattr(plugin, "borrow_info", None) if plugin is not None else None
        if not callable(reader):
            return ""
        try:
            info = reader() or {}
            owed = float(info.get("owed") or 0)
        except Exception:
            return ""
        if owed <= 0:
            return ""
        cash, savings = self._money_pool()
        usable = cash + savings
        text = (
            "【你欠他 ¥%.0f】借款，没有利息；你手里卡+储蓄 ¥%.0f。"
            "还款走 amo_repay，记成还款（不是消费）。"
            % (owed, usable)
        )
        try:
            pending = self.db.kv_get("repay_pending", {}) or {}
            amount = float(pending.get("amount") or 0) if isinstance(pending, dict) else 0.0
            stamp = float(pending.get("ts") or 0) if isinstance(pending, dict) else 0.0
            if amount >= 50 and stamp and now_ts() - stamp < 12 * 3600:
                text += "你上次说过要还 ¥%.0f，账上还没动。" % amount
        except Exception:
            pass
        return text

    def _borrow_line(self, can_ask: bool = False) -> str:
        """没钱的时候她得开口借——但只在私聊、只跟恋人；群里绝不跟别人要钱。

        ``can_ask`` 由 ``_dynamic_context`` 按「私聊 + 相恋」算好传进来，
        这里不再自己判断会话——判断散在各处就是 bug 的温床。
        """
        if not can_ask:
            return ""
        cash, savings = self._money_pool()
        if cash + savings >= 500:
            return ""
        plugin = self._finance()
        info = {}
        reader = getattr(plugin, "borrow_info", None) if plugin is not None else None
        if callable(reader):
            try:
                info = reader() or {}
            except Exception:
                info = {}
        return (
            "【没钱了】卡里 ¥%.0f、储蓄 ¥%.0f，加起来也不够用了。这种话只能跟恋人说："
            "在私聊跟他开口要钱，告诉他转账还是红包（转账每天最多一万、是**借款**要还；"
            "红包单个最多 1000、是礼物**不用还**），他会用「[转账]多少钱」或「[红包]多少钱」给你"
            "（已经欠他 ¥%.0f）。群里、别人面前一个字都别提钱。"
            % (cash, savings, float(info.get("owed") or 0))
        )

    def _gift_line(self, private: bool = True) -> str:
        """他刚给过钱：让她记得甜一下、谢他，别装作没发生。只在私聊说。

        这里**不给她指定台词**：以前写死「说一句『老公今天怎么对我这么好啊』」，
        模型就每笔钱都复读那一句。现在只给事实 + 随机一种反应方向，让她自己组织语言。
        """
        if not private:
            return ""
        plugin = self._finance()
        reader = getattr(plugin, "money_gift", None) if plugin is not None else None
        if not callable(reader):
            return ""
        try:
            note = reader() or {}
            amount = float(note.get("amount") or 0)
        except Exception:
            return ""
        if amount <= 0:
            return ""
        channel = "红包" if str(note.get("channel") or "") == "red" else "转账"
        _, hint = self._gift_reaction_style()
        return (
            "【他刚给了你钱】%d 秒前他给你发了 %s %.0f（现在欠他 %.0f）。"
            "这轮的反应：%s "
            "怎么说：用你自己的话，一两句就行。别套用以前那种固定句（一上来就夸他对你多好），"
            "也别每次都先道谢再报一遍欠款——那样听着像模板；上次说过的说法换个新的。"
            "这钱是让你吃好的、买点喜欢的，不是拿去补仓；先把自己喂饱。"
            % (int(note.get("seconds") or 0), channel, amount,
               float(note.get("owed") or 0), hint)
        )

    async def _record_expense(self, amount, reason, detail, source, result, uid=""):
        """把这一笔告诉记忆——**成功失败都记**。

        只记成功的话，聊天里她会以为钱没花，或者不知道自己为什么没钱。
        """
        try:
            target = str(uid or "").strip() or self._primary_uid()
        except Exception:
            target = ""
        if not target:
            return
        rate = ("%s（%s）" % (reason or "一笔支出", detail)) if detail else (reason or "一笔支出")
        if result.get("ok"):
            text = "%s：支出 ¥%.2f，金融已扣款" % (rate, float(amount))
        else:
            text = "%s：¥%.2f 没扣成（%s）" % (
                rate, float(amount), result.get("reason") or "余额不足")
        try:
            balance = result.get("balance")
            if balance is not None:
                text += "，余额 ¥%.2f" % float(balance)
        except Exception:
            pass
        if source:
            text = "[" + str(source) + "] " + text
        try:
            await self._write_memory_checked(target, text, kind="expense", tier=0,
                                             scope="private", group_id="")
        except Exception as exc:
            logger.debug("[amo] 支出事件没写进记忆: %s" % exc)

    async def _approved_charge(self, amount, *, reason="", payee="", source="",
                               scene="private", detail="", uid="") -> dict:
        """花钱前先提案：没拿到 allow 就不扣；扣完无论成败都发回执。

        幂等号直接用 event_id：同一次调用的重试只扣一次。
        """
        value = round(float(amount or 0), 2)
        event_id = "%s-%s" % (source or "spend", uuid.uuid4().hex[:12])
        chain = Chain("terminal.charge", event_id=event_id, logger=logger)
        chain.step("propose", amount=value, source=source or "terminal",
                   scene=scene, payee=payee or "")
        kind = {"medical": "medical_treat", "market": "market_buy",
                "image": "image_draw", "speech": "speech_synth"}.get(source, "market_buy")
        decision = self.submit_event({
            "event_id": event_id,
            "event_type": kind,
            "source": source or "terminal",
            "scene": "group" if str(scene or "").lower() == "group" else "private",
            "payload": {"cost": value, "reason": reason or "",
                        "detail": {"payee": payee, "note": detail}},
            "need_approve": True,
        })
        if not decision.get("approved"):
            chain.fail("approve", str(decision.get("reason") or "终端没批"),
                       decision=str(decision.get("decision") or "deny"))
            return {"ok": False, "code": str(decision.get("decision") or "deny"),
                    "reason": str(decision.get("reason") or "终端没批"),
                    "balance": self.balance(), "event_id": event_id}
        chain.step("approve", decision=str(decision.get("decision") or "allow"),
                   score=decision.get("score"))
        result = await self.charge(value, reason=reason, payee=payee,
                                   request_id=event_id, source=source,
                                   detail=detail, uid=uid)
        chain.step("charge", ok=bool(result.get("ok")),
                   detail=str(result.get("reason") or result.get("code") or ""),
                   balance=result.get("balance"))
        try:
            self.event_receipt({
                "event_id": event_id,
                "status": "success" if result.get("ok") else "fail",
                "code": str(result.get("code") or ""),
                "reason": str(result.get("reason") or ""),
                "amount": value,
                "balance": result.get("balance"),
            })
        except Exception as exc:
            logger.debug("[amo] 回执失败: %s" % exc)
            chain.fail("receipt", str(exc))
        else:
            chain.step("receipt", detail="已归档")
        if result.get("ok"):
            chain.done(amount=value, balance=result.get("balance"), source=source or "terminal")
        else:
            chain.fail("result", str(result.get("reason") or "扣款失败"), amount=value)
        return dict(result, event_id=event_id)

    def _charge_cache_get(self, request_id, amount=None):
        """查幂等号。

        - 成功单：内存 + 磁盘（``charge_ok``），重启后同一笔不会再扣；
        - 失败单：只留 60 秒，补钱之后能重试——永久缓存失败等于把这笔锁死。
        - 金额对不上：说明调用方拿错了号，返回 ``idempotency_conflict``。
        """
        if not request_id:
            return None
        cache = getattr(self, "_charge_cache", None) or {}
        hit = cache.get(request_id)
        if isinstance(hit, dict):
            if self._amount_conflicts(hit, amount):
                return self._charge_conflict("内存")
            return dict(hit)
        try:
            stored = self.db.kv_get("charge_ok", {}) or {}
        except Exception:
            stored = {}
        entry = stored.get(request_id) if isinstance(stored, dict) else None
        if isinstance(entry, dict) and entry.get("ok"):
            if self._amount_conflicts(entry, amount):
                return self._charge_conflict("落库")
            return dict(entry)
        fail = (getattr(self, "_charge_fail", None) or {}).get(request_id)
        if isinstance(fail, tuple) and len(fail) == 2:
            ts, result = fail
            if time.time() - to_float(ts, 0) <= self.CHARGE_FAIL_TTL:
                return dict(result)
            try:
                self._charge_fail.pop(request_id, None)
            except Exception:
                pass
        return None

    def _charge_cache_put(self, request_id, result, amount=None):
        if not request_id:
            return
        if not result.get("ok"):
            fail = getattr(self, "_charge_fail", None)
            if fail is None:
                fail = {}
                self._charge_fail = fail
            fail[request_id] = (time.time(), dict(result))
            if len(fail) > 200:
                for key in list(fail)[:50]:
                    fail.pop(key, None)
            return
        payload = dict(result)
        try:
            if amount is not None:
                payload["_amount"] = round(float(amount), 2)
        except (TypeError, ValueError):
            pass
        cache = getattr(self, "_charge_cache", None)
        if cache is None:
            cache = {}
            self._charge_cache = cache
        cache[request_id] = dict(payload)
        if len(cache) > 200:
            for key in list(cache)[:50]:
                cache.pop(key, None)
        try:
            stored = self.db.kv_get("charge_ok", {}) or {}
            if not isinstance(stored, dict):
                stored = {}
            stored[request_id] = dict(payload, ts=time.time())
            if len(stored) > self.CHARGE_OK_KEEP:
                oldest = sorted(stored, key=lambda k: to_float((stored.get(k) or {}).get("ts"), 0))
                for key in oldest[: max(1, len(stored) - self.CHARGE_OK_KEEP)]:
                    stored.pop(key, None)
            self.db.kv_set("charge_ok", stored)
        except Exception as exc:
            logger.debug("[amo] 幂等号落库失败: %s" % exc)

    def _sync_finance(self) -> None:
        """把金融插件的最新快照拉进状态。不写日志，失败也不影响主链路。"""
        plugin = self._finance()
        if plugin is None:
            return
        try:
            try:
                snap = plugin.snapshot(refresh=False)
            except TypeError:
                snap = plugin.snapshot()
            if isinstance(snap, dict):
                self.state.finance = {
                    "balance": snap.get("balance", 0),
                    "savings": snap.get("savings", 0),
                    "total": round(float(snap.get("balance") or 0)
                                   + float(snap.get("savings") or 0), 2),
                    "fixed_total": snap.get("fixed_total", 0),
                    "anxiety": snap.get("anxiety", 0),
                    "owed": snap.get("owed_to_user", 0),
                    "month_spent": snap.get("month_spent", 0),
                }
                inv = snap.get("invest") or {}
                # 这里必须把 _invest_line() / invest_summary() 真正会用到的字段全同步过来。
                # 2026-11-17 的病象：她「好像不知道自己在炒股」——_invest_line 要读
                # leverage / savings / buying_power / margin_debt / futures，
                # 但这里一个都没给，于是她看到的杠杆永远是 1 倍、储蓄和保证金全是 0，
                # 拿着残缺的账本聊股票，当然像个不懂的。
                self.state.invest = {
                    "stance": inv.get("stance") or "",
                    "leek": inv.get("leek") or {},
                    "cash": inv.get("cash", 0),
                    "savings": inv.get("savings", 0),
                    "value": inv.get("total_value", 0),
                    "pnl": inv.get("total_pnl", 0),
                    "pnl_pct": inv.get("total_pnl_pct", 0),
                    "day_pnl": inv.get("day_pnl", 0),
                    "count": inv.get("count", 0),
                    "leverage": inv.get("leverage", 1),
                    "buying_power": inv.get("buying_power", 0),
                    "margin_debt": inv.get("margin_debt", 0),
                    "equity": inv.get("equity", 0),
                    "futures": inv.get("futures") or {},
                    "positions": [
                        {"name": p.get("name") or p.get("symbol"),
                         "symbol": p.get("symbol") or "",
                         "qty": p.get("qty"),
                         "last": p.get("last", 0),
                         "market_value": p.get("market_value", 0),
                         "pnl": p.get("pnl", 0),
                         "pnl_pct": p.get("pnl_pct")}
                        for p in (inv.get("positions") or [])[:6]
                    ],
                    "bankrupt": inv.get("bankrupt") or {},
                    "aggressive": bool(inv.get("aggressive")),
                }
        except Exception as exc:
            logger.debug("[amo] 财务快照同步失败: %s" % exc)

    async def _sync_market_mood(self) -> None:
        """股市盈亏影响心情。

        赚了：开心、兴奋，奖励自己一顿好的（真的记一笔支出）。
        亏了：郁闷、焦虑，吃得简单——语气会跟着无精打采（心情会注入人格提示）。
        一天只按方向记一次，不然每条 tick 都在加焦虑。
        """
        plugin = self._finance()
        reader = getattr(plugin, "mood_signal", None) if plugin is not None else None
        if not callable(reader):
            return
        try:
            try:
                signal = reader(refresh=False)
            except TypeError:
                signal = reader()
        except Exception as exc:
            logger.debug("[amo] 读投资盈亏失败: %s" % exc)
            return
        if not isinstance(signal, dict):
            return
        pct = to_float(signal.get("day_pnl_pct"), 0)
        pnl = to_float(signal.get("day_pnl"), 0)
        # 韭菜档位（±3%）先单独处理：上头/死扛各加一次，和 ±2% 的心情不冲突
        stance = str((getattr(self.state, "invest", None) or {}).get("stance") or "")
        if stance:
            key = "%s|leek|%s" % (today_str(), stance)
            if getattr(self, "_leek_key", "") != key:
                self._leek_key = key
                if stance == "overconfident":
                    self.state.feel_bump({"surprise": 6, "joy": 4})
                    await self._market_memory("今天股票大涨，我飘了，觉得自己就是巴菲特", kind="event")
                else:
                    self.state.feel_bump({"fear": 6, "sadness": 3})
                    await self._market_memory("今天股票大跌，我死扛着不卖，心里其实很难受", kind="event")
        if abs(pct) < 2.0:
            return
        mood = "up" if pct > 0 else "down"
        key = "%s|%s" % (today_str(), mood)
        if getattr(self, "_market_mood_key", "") == key:
            return
        self._market_mood_key = key
        if mood == "up":
            self.state.feel_bump({"joy": 6, "surprise": 3})
            await self._market_memory(
                "今天股市赚了 %.2f%%（¥%.0f），心情不错，想吃点好的" % (pct, pnl),
                kind="event",
            )
            await self._market_reward(pnl)
        else:
            self.state.feel_bump({"sadness": 6, "fear": 5, "joy": -3})
            await self._market_memory(
                "今天股市亏了 %.2f%%（¥%.0f），有点没精神，吃得简单点" % (-pct, -pnl),
                kind="event",
            )

    def _market_plugin(self):
        """找市场插件（Astrbot_Amo_Marketplace）；没装返回 None。"""
        names = ("DeepSeek_Harness_Amo_Market", "DeepSeek_Harness_Amo_Finance")
        try:
            for name in names:
                try:
                    meta = self.context.get_registered_star(name)
                except Exception:
                    meta = None
                for attr in ("star_cls", "instance", "star", "plugin"):
                    star = getattr(meta, attr, None) if meta is not None else None
                    if star is not None and not isinstance(star, type) and hasattr(star, "outfits"):
                        return star
        except Exception:
            pass
        try:
            for meta in self.context.get_all_stars():
                marker = ((getattr(meta, "name", "") or "") + " "
                          + (getattr(meta, "module_path", "") or "")).lower()
                if "market" not in marker:
                    continue
                for attr in ("star_cls", "instance", "star", "plugin"):
                    star = getattr(meta, attr, None)
                    if star is not None and not isinstance(star, type) and hasattr(star, "outfits"):
                        return star
        except Exception:
            pass
        return None


__all__ = [
    "_hhmm_minutes",
    "EconomyMixin",
]
