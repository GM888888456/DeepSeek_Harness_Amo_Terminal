# -*- coding: utf-8 -*-
"""Amo 终端 · 学习与记忆沉积（LearnMixin）

从 main.py 的 HumanCorePlugin 整块搬出来的方法，方法体逐行未改。
由 HumanCorePlugin(..., LearnMixin, Star) 混入，self.* 照旧可用。

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



class LearnMixin:

    async def _learn(self, event, text):
        uid = self._canonical_uid(event)
        name = event.get_sender_name() or uid
        umo = event.unified_msg_origin
        group_id = event.get_group_id()
        private = event.is_private_chat()
        profile = self.db.touch_profile(
            uid, name, event.get_platform_name(), umo, group_id, private
        )
        if private and umo:
            self._record_channel(uid, umo, event.get_platform_name())
        if profile and not profile.get("is_admin") and uid in self.admin_uids:
            self.db.update_profile(uid, is_admin=1)
            profile["is_admin"] = 1

        if self.cfg_bool("auto_relation", True):
            try:
                await self._learn_relations(event, text, uid)
            except Exception as exc:
                logger.debug("[amo] 关系自动识别失败: %s" % exc)
        # 上下文先进内存；本地缓存默认关掉，原始聊天交给记忆终端
        self._ctx_remember(umo, uid, name, "user", text)
        try:
            await self._data_call(
                "add_message", self._data_bot_id(), umo, uid, name, "user", text,
                platform=self._platform_of(event), message_id=self._event_message_id(event),
            )
        except Exception as exc:
            logger.debug("[amo] 聊天记录同步失败: %s" % exc)

        senti = sentiment(text)
        affection = to_int(profile.get("affection"), 10)
        if senti["aff"] or senti["pos"]:
            affection += 2
        if senti["neg"] or senti["insult"]:
            affection -= 2
        affection = int(clamp(affection, 0, 100))

        # 记忆只在记忆库里；这里只把生日这种档案字段记进画像。
        match = re.search(r"生日(?:是|在)?\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]?", text or "")
        if match:
            self.db.update_profile(uid, birthday="%02d-%02d" % (to_int(match.group(1)), to_int(match.group(2))))

        fields = {"affection": affection}
        relation = profile.get("relation", "普通")
        if relation == "普通" and to_int(profile.get("msg_count"), 0) >= self.cfg_int("familiar_msg_count", 30):
            fields["relation"] = "熟识"
        elif relation == "熟识" and senti["insult"]:
            fields["relation"] = "抵触"
        self.db.update_profile(uid, **fields)
        try:
            self._learn_alias(event, text, uid, profile)
        except Exception as exc:
            logger.debug("[amo] 学习称呼失败: %s" % exc)

        if group_id:
            times = self._group_times.setdefault(group_id, [])
            times.append(now_ts())
            if len(times) > 200:
                self._group_times[group_id] = times[-200:]
            self._last_group = group_id
        self._last_umo = umo

    def _learn_alias(self, event, text, uid, profile):
        """从“以后叫我XX / 叫他XX”里学习称呼，并在后续沿用。"""
        blocked = {"干嘛", "什么", "名字", "滚", "闭嘴", "一声", "一下", "出来"}
        alias = ""
        for pattern in (
            r"(?:以后|今后|你可以|可以|请)?叫我\s*([\u4e00-\u9fa5A-Za-z0-9_]{1,12})",
            r"叫我\s*([\u4e00-\u9fa5A-Za-z0-9_]{1,12})\s*(?:就行|就好|吧)",
        ):
            match = re.search(pattern, str(text or ""))
            if match:
                candidate = match.group(1).strip()
                if candidate and candidate not in blocked:
                    alias = candidate
                    break
        if alias:
            current = str(profile.get("alias") or "")
            if alias not in current:
                new_alias = (current + "；" + alias).strip("；")[:80]
                self.db.update_profile(uid, alias=new_alias)
                logger.debug("[amo] 记住称呼: %s -> %s" % (uid, alias))

        try:
            messages = event.message_obj.message
        except Exception:
            messages = []
        at_targets = [
            str(getattr(comp, "qq", ""))
            for comp in (messages or [])
            if Comp is not None and isinstance(comp, Comp.At)
        ]
        for comp in messages:
            if Comp is None or not isinstance(comp, Comp.At):
                continue
            target = str(getattr(comp, "qq", ""))
            if not target or target in ("all", str(event.get_self_id())):
                continue
            # “以后喊他XX”通常跟在最后一个 @ 后面；不要误记到前一个被 @ 的人。
            if at_targets and target != at_targets[-1]:
                continue
            for pattern in (
                r"(?:以后|就)?(?:喊|叫|称呼)(?:他|她|ta|TA|做)\s*([\u4e00-\u9fa5A-Za-z0-9_]{1,12})",
            ):
                match = re.search(pattern, str(text or ""))
                if not match:
                    continue
                candidate = match.group(1).strip()
                if not candidate or candidate in blocked:
                    continue
                target_profile = self.db.get_profile(target)
                if not target_profile:
                    self.db.touch_profile(target, candidate, event.get_platform_name(), "", "", False)
                    target_profile = self.db.get_profile(target)
                current = str(target_profile.get("alias") or "")
                if candidate not in current:
                    self.db.update_profile(target, alias=(current + "；" + candidate).strip("；")[:80])
                break
            # 群里反复 @ 同一个人并叫同一个短称呼，累计三次后记住。
            plain = re.sub(r"@\S+", "", str(text or "")).strip()
            common = {
                "在吗", "你好", "早安", "晚安", "吃了吗", "干嘛", "出来", "看这个",
                "哈哈", "笑死", "救命", "谢谢", "收到", "好的", "可以", "不行",
                "快看", "快来", "过来", "上线", "打游戏", "起床", "睡觉", "上班", "下班",
            }
            if 1 <= len(plain) <= 8 and plain not in common and not re.search(r"[，。！？!?、；;：:]", plain):
                seen_key = "alias_seen_" + target + "_" + plain
                seen = to_int(self.db.kv_get(seen_key, 0), 0) + 1
                self.db.kv_set(seen_key, seen)
                if seen >= 3:
                    alias_profile = self.db.get_profile(target) or {}
                    current = str(alias_profile.get("alias") or "")
                    if plain not in current:
                        self.db.update_profile(target, alias=(current + "；" + plain).strip("；")[:80])
                    self.db.kv_set(seen_key, 0)

    async def _sediment_relations(self):
        """按真实互动量沉淀关系网：聊得多就是熟人/朋友，并让 bot 通过你认识你的人。

        只补两类 note（算法见 relation_sediment.py）：
        1. bot ↔ 用户（全部历史累计）：聊过一句 / 只在人物列表里 → 陌生人；
           ≥15 条且跨 ≥2 天 → 熟人；≥60 条且跨 ≥7 天 → 朋友；
        2. 两跳推断：bot↔用户已是熟/朋友，而用户↔A 有非仇人边 → bot↔A 记「朋友」，
           note「推断：经X认识」，每人最多 5 条。
        管理员手设的关系（note 不带「自动：」「推断：」）永远不覆盖；
        家人/恋人/仇人不改；自动边只升不降。
        """
        if plan_relation_edges is None:
            return
        # 0 = 统计全部历史：老用户、只聊过一两句的人也要进关系网
        days = max(0, int(self.cfg_int("relation_sediment_days", 0)))
        try:
            stats = self.db.interaction_stats(days)
        except Exception as exc:
            logger.debug("[amo] 互动统计失败: %s" % exc)
            return
        if self.cfg_bool("relation_stranger_edges", True):
            seen = {str(row.get("uid") or "") for row in stats}
            try:
                # 只出现在人物列表、从没聊过天的人，也记成「陌生人」进图；
                # 觉得面板边太多就把 relation_stranger_edges 关掉，只记聊过天的人
                for item in self.db.list_profiles(limit=1000):
                    uid = str(item.get("uid") or "")
                    if uid and uid not in seen:
                        stats.append({"uid": uid, "c": 0, "f": 0, "l": 0})
                        seen.add(uid)
            except Exception as exc:
                logger.debug("[amo] 读取人物列表失败: %s" % exc)
        if not stats:
            return

        names = {}
        try:
            for item in self.db.list_profiles(limit=500):
                names[str(item.get("uid"))] = str(item.get("alias") or item.get("name") or "")
        except Exception:
            names = {}

        existing = {}
        try:
            for edge in self.db.list_relations():
                pair = tuple(sorted([str(edge.get("a_uid") or ""), str(edge.get("b_uid") or "")]))
                existing[pair] = (str(edge.get("relation") or ""), str(edge.get("note") or ""))
        except Exception as exc:
            logger.debug("[amo] 读取关系网失败: %s" % exc)
            return

        infer_limit = max(1, min(10, int(self.cfg_int("relation_infer_per_user", 5))))
        try:
            plan = plan_relation_edges(stats, existing, names, infer_limit)
        except Exception as exc:
            logger.debug("[amo] 关系沉淀计算失败: %s" % exc)
            return
        # 一次最多写 300 条，人物很多时分成几轮补齐，别把 tick 卡太久
        for a_uid, b_uid, relation, note in plan[:300]:
            try:
                if not self.db.upsert_relation(a_uid, b_uid, relation, note):
                    continue
                await self._push_relation_to_data(a_uid, b_uid, relation, note)
            except Exception as exc:
                logger.debug("[amo] 关系沉淀写入失败: %s" % exc)

    def _note_promise(self, event, text, kind=KIND_PHOTO, wait=None, style="", want=""):
        """把一句答应的事记进账本；群聊不记。"""
        if self.promises is None:
            return None
        try:
            if not event.is_private_chat():
                return None
        except Exception:
            return None
        text = str(text or "").strip()
        if not text:
            return None
        try:
            activity = self.state.current_activity() or {}
            word = driving(activity) if driving else ""
            place = detect_place(text) if detect_place else ""
            here = place_of(activity) if place_of else ""
            look = str(activity.get("outfit") or "").strip()
            if not look and getattr(self, "outfits", None) is not None:
                try:
                    look = str(self.outfits.for_activity(activity, today_str()) or "").strip()
                except Exception:
                    look = ""
            if wait is None:
                if word:
                    wait = WAIT_DRIVE
                elif place:
                    wait = WAIT_PLACE
                else:
                    wait = WAIT_TIME
            due_ts = now_ts() + 15 * 60 if wait == WAIT_TIME else 0
            # 方向：这条是她答应的（跟她答应的东西比，他这轮有没有亲口许她什么）。
            # 2026-11-15 10:12 她把「我答应穿 JK 拍给你看」说成了
            # 「你答应我的那事还没做」——账本里没有方向，注入时又统一写成
            # 「你答应过的事」，方向就这么反了。
            row = self.promises.add(
                kind, text,
                umo=str(getattr(event, "unified_msg_origin", "") or ""),
                uid=str(self._canonical_uid(event) or ""),
                wait=wait, due_ts=due_ts, place=place, from_place=here,
                look=look, style=style, want=want,
                side=his_side(text, speaker="bot"),
            )
            # 他这轮亲口答应她的，单独记一条「他答应过你」的事实；只记事实，不催。
            try:
                his_text = str(getattr(event, "message_str", "") or "").strip()
                if his_text and his_side(his_text, speaker="user") == "his":
                    self.promises.add(
                        KIND_ACT, "他答应：%s" % his_text[:40],
                        umo=str(getattr(event, "unified_msg_origin", "") or ""),
                        uid=str(self._canonical_uid(event) or ""),
                        wait=WAIT_TIME, due_ts=now_ts() + 7200,
                        side="his",
                    )
            except Exception as exc:
                logger.debug("[amo] 记他答应的事失败: %s" % exc)
        except Exception as exc:
            logger.debug("[amo] 记承诺失败: %s" % exc)
            return None
        if row:
            logger.info("[amo] 记下她答应的事（%s/%s）：%s"
                        % (kind, row.get("wait"), text[:40]))
        return row

    def _remember_bot_message(self, umo, text):
        """把机器人自己发出去的话也写进 messages 表。

        这张表既是主动消息的上下文，也是「这句话回过没有」的唯一依据。
        正常回复走守护发送，以前只写 AstrBot 的会话历史，表里没有，
        主动消息就会把已经答过的话当成没答过，再答一遍。
        """
        umo = str(umo or "").strip()
        text = str(text or "").strip()
        if not umo or not text:
            return
        last_user = ""
        try:
            saved = self._last_bot_saved.get(umo)
            try:
                for row in reversed(self._recent(umo, 4) or []):
                    if str(row.get("role") or "") == "user":
                        last_user = str(row.get("content") or "").strip()
                        break
            except Exception:
                last_user = ""
            # 同一句在 3 分钟内又发一次很常见（「嗯嗯」「好呀」）；只有「对应的
            # 他最后那句话也没变」才算重复。以前只看文字，第二次「好呀」会被丢掉，
            # 表里就变成「他还没被回过」，主动消息再把同一句答一遍。
            if saved and saved[0] == text and time.time() - saved[1] < 180:
                saved_user = str(saved[2] if len(saved) > 2 else "")
                if saved_user == last_user:
                    return
            self._ctx_remember(umo, "bot", self.bot_name, "bot", text)
            # 直接同步写进记忆终端：fire-and-forget 在 reload/退出时会丢这句
            saved = False
            store = self._data_store()
            if store is not None and callable(getattr(store, "add_message", None)):
                try:
                    store.add_message(
                        self._data_bot_id(), umo, "bot", self.bot_name, "bot", text,
                        platform=str(umo).split(":", 1)[0],
                    )
                    saved = True
                except Exception as exc:
                    logger.warning("[amo] 自己的回复写入终端失败: %s" % exc)
            if not saved:
                try:
                    loop = asyncio.get_running_loop()
                    task = loop.create_task(self._data_call(
                        "add_message", self._data_bot_id(), umo, "bot", self.bot_name, "bot", text,
                        platform=str(umo).split(":", 1)[0],
                    ))
                    def _log_failed_task(task):
                        if task.cancelled():
                            return
                        exc = task.exception()
                        if exc is not None:
                            logger.warning("[amo] 自己的回复异步落库失败: %s" % exc)

                    task.add_done_callback(_log_failed_task)
                except Exception:
                    pass
            self._last_bot_saved[umo] = (text, time.time(), last_user)
        except Exception as exc:
            logger.debug("[amo] 记录自己的回复失败: %s" % exc)

    async def _remember_photo(self, umo, prompt, scene=None, label="照片"):
        """发出去一张图就记一条：她记得自己拍过什么、在哪儿拍的。

        走事件记忆（kind=photo_record）：7 天降权、14 天删除，不占核心记忆。
        """
        try:
            uid = self._primary_uid()
        except Exception:
            uid = ""
        if not uid:
            return False
        scene = scene if isinstance(scene, dict) else {}
        place = str(scene.get("place") or "").strip()
        activity = str(scene.get("activity") or "").strip()
        # 同一张图同一分钟内只记一次：draw_for 内部会写一条记录，发图这一步再写一条，
        # 以前一张自拍在库里就是两条（还各带不同的地点），召回时互相打架。
        now = now_ts()
        try:
            last = self.db.kv_get("photo_memo_last", {}) or {}
            if (str(last.get("umo") or "") == str(umo or "")
                    and abs(now - float(last.get("ts") or 0)) < 90):
                logger.debug("[amo] 照片记忆刚写过，跳过重复写")
                return True
        except Exception:
            pass
        text = "[自我形象记忆·%s] 给他发了一张%s" % (
            time.strftime("%m-%d %H:%M", time.localtime()), label or "照片")
        if place:
            text += "，在" + place
        if activity:
            text += "，" + activity[:30]
        shoot = str(prompt or "").strip()
        if shoot:
            # 地点是日程给的唯一真相：画面里那句「家里/在他那儿」要是和地点打架，
            # 就别把矛盾的那半句记进库里（以前会记成「在路上…（画面：…家里）」）。
            if place:
                for wrong, right in (("在家", ""), ("家里", ""), ("在他那儿", ""),
                                     ("公司", ""), ("办公室", "")):
                    if wrong in shoot and wrong not in place:
                        shoot = shoot.replace(wrong, "")
            shoot = re.sub(r"[，,]{2,}", "，", shoot).strip("，, ")
        if shoot:
            text += "（画面：%s）" % shoot[:60]
        try:
            self.feel(FeelEvent.PHOTO_SENT)
        except Exception:
            pass
        try:
            self._record("photo", "拍了一张%s" % (label or "照片"), text, "", 0)
            ok = await self._write_memory_checked(uid, text, kind="photo_record", tier=0)
            if ok:
                try:
                    self.db.kv_set("photo_memo_last",
                                   {"ts": now_ts(), "umo": str(umo or "")})
                except Exception:
                    pass
                return True
            # photo_record 这条路被守门人拦下过（结果就是拍了一堆照片一条记录都没有），
            # 退一步用普通事件记，宁可降级也不能丢
            logger.info("[amo] photo_record 没写进去，降级为 event: %s" % text[:40])
            return await self._write_memory_checked(uid, "【照片】" + text, kind="event", tier=0)
        except Exception as exc:
            logger.warning("[amo] 照片记忆写入失败: %s" % exc)
            return False

    async def _milestone_archive_once(self):
        """真正的归档逻辑（外面包了并发锁）。"""
        if not self.cfg_bool("milestone_enabled", True):
            return
        mem = self._data_mem()
        if mem is None or not callable(getattr(mem, "messages_since", None)):
            return
        every = max(2, self.cfg_int("milestone_every_turns", 20))
        min_messages = max(4, self.cfg_int("milestone_min_messages", 12))
        try:
            profiles = self.db.list_profiles(limit=20) or []
        except Exception:
            profiles = []
        for profile in profiles:
            uid = str(profile.get("uid") or "")
            home_umo = str(profile.get("private_umo") or "")
            if not uid or not home_umo:
                continue
            if str(profile.get("relation") or "") != "相恋":
                continue
            key = "milestone_ts:" + uid
            try:
                since = to_int(self.db.kv_get(key, 0))
            except Exception:
                since = 0
            try:
                rows = await self._data_call("messages_since", self._data_bot_id(), uid, since, 400)
            except Exception as exc:
                logger.debug("[amo] 里程碑取聊天失败: %s" % exc)
                continue
            if not rows:
                continue
            # 按人取（跨平台）会把群聊一起带回来，而这条总结写的是 scope='private'：
            # 群友说的话不能变成她「只在私聊里记得」的事。
            rows = _private_rows(rows)
            if not rows:
                continue
            if not since:
                # 第一次只从"现在"开始记，不把全部历史一次性压成一条。
                # 注意不能用 rows[-1]（那是本批 400 条里最旧的一条），否则会从历史开始滚。
                try:
                    self.db.kv_set(key, now_ts())
                except Exception:
                    pass
                logger.info("[amo] 里程碑起点已设置（从现在开始）: uid=%s" % uid)
                continue
            if not _ms_should_archive(rows, every, min_messages):
                continue
            body = _ms_transcript(rows)
            label = _now().strftime("%Y-%m-%d")
            system = "你是长期记忆整理器。只输出一段中文总结，不要标题、不要分点、不要时间戳。"
            prompt = _ms_build_prompt(label, body)
            try:
                summary = await self.llm.chat_raw(home_umo, system, prompt)
            except Exception as exc:
                logger.debug("[amo] 里程碑总结失败: %s" % exc)
                summary = ""
            summary = re.sub(r"\s+", " ", str(summary or "")).strip()
            if len(summary) < 8:
                continue
            content = _ms_build_content(label, summary)
            written = await self._write_memory_checked(uid, content, "milestone", 2)
            logger.info("[amo] 里程碑归档%s: %s" % ("已写入" if written else "写入失败", content[:80]))
            if written:
                try:
                    last_ts = int(rows[-1].get("created_at") or now_ts())
                    self.db.kv_set(key, max(last_ts + 1, since))
                except Exception:
                    pass


__all__ = [
    "LearnMixin",
]
