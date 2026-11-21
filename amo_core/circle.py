# -*- coding: utf-8 -*-
"""Amo 终端 · 社交圈（CircleMixin）

她自己的社交圈：加了哪些群、这个群叫什么、群里多少人、有哪些好友、
最近又被拉进了哪个群 / 谁加了她好友 / 谁在申请加她。

数据来源只有两处：OneBot 的 get_group_list / get_friend_list（半小时拉一次），
和平台的 notice / request 事件（有人加好友、有人拉她进群、她被踢）。
整份名单就一张 JSON，存在 kv 表里（social_circle_v1），不新建表：
提示词、调试命令、面板都只读这一份。
"""
from __future__ import annotations

try:
    from astrbot.api import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("amo_terminal")

from .shared import *

CIRCLE_KEY = "social_circle_v1"
CIRCLE_REFRESH_GAP = 1800          # 半小时拉一次名单
CIRCLE_NEW_WINDOW = 7 * 86400      # 七天内的变化还提一嘴
CIRCLE_KEEP_WINDOW = 30 * 86400    # 新变化最多留三十天
CIRCLE_MAX_GROUPS = 60
CIRCLE_MAX_FRIENDS = 400
CIRCLE_MAX_NEW = 40
CIRCLE_LIST_IN_PROMPT = 5          # 提示词里最多念几个群名


def _circle_clean(value, limit=24):
    """把群名/昵称清成一行短文本：去换行、去控制符、截断。"""
    text = str(value or "")
    # QQ 群里带花色的名字会混进 <$ǿĀD> 这种标记，念出来像乱码
    text = re.sub(r"<\$[^>]{0,30}>", "", text)
    for ch in ("\r", "\n", "\t"):
        text = text.replace(ch, " ")
    text = "".join(ch for ch in text if ch >= " " or ch == " ").strip()
    if len(text) > limit:
        text = text[:limit] + "…"
    return text


def _circle_day(ts, now=None):
    """给提示词用的日期：今天 / 昨天 / 前天 / 09-27。"""
    try:
        ts = float(ts)
    except Exception:
        return ""
    if ts <= 0:
        return ""
    today = date.today()
    day = datetime.fromtimestamp(ts).date()
    delta = (today - day).days
    if delta <= 0:
        return "今天"
    if delta == 1:
        return "昨天"
    if delta == 2:
        return "前天"
    return day.strftime("%m-%d")


class CircleMixin:
    # ---------------------------------------------------------------- 存取
    def _circle_data(self):
        try:
            data = self.db.kv_get(CIRCLE_KEY, {}) or {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            data = {}
        for key in ("groups", "friends", "new", "pending"):
            if not isinstance(data.get(key), list):
                data[key] = []
        try:
            data["ts"] = float(data.get("ts") or 0)
        except Exception:
            data["ts"] = 0.0
        return data

    def _circle_save(self, data):
        try:
            self.db.kv_set(CIRCLE_KEY, data)
        except Exception as exc:
            logger.debug("[amo] 社交圈写库失败: %s" % exc)

    # ---------------------------------------------------------------- 取数据
    def _circle_bot(self):
        """不靠消息事件也能拿到 OneBot 客户端（心跳里刷名单用）。"""
        try:
            for inst in self.context.platform_manager.get_insts():
                getter = getattr(inst, "get_client", None)
                if getter is None:
                    continue
                try:
                    client = getter()
                except Exception:
                    continue
                if client is not None:
                    return client
        except Exception as exc:
            logger.debug("[amo] 找不到 OneBot 客户端: %s" % exc)
        return None

    async def _circle_api(self, action, event=None, **kwargs):
        bot = getattr(event, "bot", None) if event is not None else None
        if bot is None:
            bot = self._circle_bot()
        if bot is None:
            return None
        try:
            return await bot.call_action(action, **kwargs)
        except Exception as exc:
            logger.debug("[amo] OneBot %s 失败: %s" % (action, exc))
            return None

    async def _circle_call_ok(self, action, **kwargs):
        """执行一次没有返回值的 OneBot 动作（通过好友/进群申请），只回成功与否。"""
        bot = self._circle_bot()
        if bot is None:
            return False
        try:
            await bot.call_action(action, **kwargs)
            return True
        except Exception as exc:
            logger.debug("[amo] OneBot %s 失败: %s" % (action, exc))
            return False

    def _circle_merge(self, data, kind, rows, now):
        """把一次 get_*_list 的结果并进名单，顺便认出新来的。"""
        key = "groups" if kind == "group" else "friends"
        id_key = "group_id" if kind == "group" else "user_id"
        name_key = "group_name" if kind == "group" else "nickname"
        old = {}
        for item in data[key]:
            if isinstance(item, dict) and item.get("id"):
                old[str(item["id"])] = item
        merged, fresh = [], []
        for row in rows:
            if not isinstance(row, dict):
                continue
            ident = str(row.get(id_key) or row.get("user_id") or row.get("group_id") or "")
            if not ident:
                continue
            prev = old.get(ident) or {}
            item = {
                "id": ident,
                "name": _circle_clean(row.get(name_key) or prev.get("name") or ident),
                "since": float(prev.get("since") or 0),
                "seen": now,
            }
            if kind == "group":
                try:
                    item["count"] = int(row.get("member_count") or prev.get("count") or 0)
                except Exception:
                    item["count"] = int(prev.get("count") or 0)
            merged.append(item)
            if prev:
                continue
            if data["ts"]:
                # 第一次拉到的名单不算「新加的」，否则她会以为一下进了几十个群
                fresh.append({"kind": kind, "id": ident, "name": item["name"], "ts": now})
        data[key] = merged[:CIRCLE_MAX_GROUPS if kind == "group" else CIRCLE_MAX_FRIENDS]
        if fresh:
            data["new"] = (list(data["new"]) + fresh)[-CIRCLE_MAX_NEW:]
            for item in fresh:
                logger.info("[amo] 社交圈：新%s「%s」"
                            % ("群" if kind == "group" else "好友", item["name"]))
        # 通知里只剩号码的，等名单拿到后补上名字
        names = {str(item["id"]): item["name"] for item in data[key]}
        for item in data["new"]:
            if not isinstance(item, dict):
                continue
            ident = str(item.get("id") or "")
            if ident in names and (not item.get("name") or str(item.get("name")) == ident):
                item["name"] = names[ident]
        return data

    async def _circle_refresh(self, event=None, force=False):
        """按需刷新名单（默认半小时一次）。event 可以没有。"""
        data = self._circle_data()
        now = now_ts()
        if not force and data["ts"] and now - data["ts"] < CIRCLE_REFRESH_GAP:
            return data
        changed = False
        login = await self._circle_api("get_login_info", event)
        if isinstance(login, dict) and login.get("user_id"):
            data["self"] = {"id": str(login.get("user_id")),
                            "name": _circle_clean(login.get("nickname") or "")}
        groups = await self._circle_api("get_group_list", event)
        if isinstance(groups, list):
            data = self._circle_merge(data, "group", groups, now)
            changed = True
        friends = await self._circle_api("get_friend_list", event)
        if isinstance(friends, list):
            self_id = str((data.get("self") or {}).get("id") or "")
            if self_id:
                friends = [f for f in friends
                           if str((f or {}).get("user_id") or "") != self_id]
            data = self._circle_merge(data, "friend", friends, now)
            changed = True
        if not changed:
            return data
        data["ts"] = now
        cutoff = now - CIRCLE_KEEP_WINDOW
        data["new"] = [i for i in data["new"]
                       if isinstance(i, dict) and float(i.get("ts") or 0) >= cutoff][-CIRCLE_MAX_NEW:]
        data["pending"] = [i for i in data["pending"]
                           if isinstance(i, dict) and float(i.get("ts") or 0) >= cutoff][-20:]
        self._circle_save(data)
        logger.info("[amo] 社交圈已更新：%d 个群 / %d 个好友（登录号 %s %s）"
                    % (len(data["groups"]), len(data["friends"]),
                       (data.get("self") or {}).get("id") or "?",
                       (data.get("self") or {}).get("name") or ""))
        return data

    # ---------------------------------------------------------------- 通知
    async def _circle_signal(self, raw):
        """notice / request：她被拉进群、被踢、有人加她好友、有人申请。"""
        if not isinstance(raw, dict):
            return
        post = str(raw.get("post_type") or "")
        notice = str(raw.get("notice_type") or "")
        self_id = str(raw.get("self_id") or "")
        user_id = str(raw.get("user_id") or "")
        group_id = str(raw.get("group_id") or "")
        data = self._circle_data()
        now = now_ts()
        changed = False
        note = ""
        if post == "request":
            rtype = str(raw.get("request_type") or "")
            who = user_id or group_id
            if not who:
                return
            kind = "好友申请" if rtype == "friend" else "入群邀请"
            comment = _circle_clean(raw.get("comment") or "", 30)
            data["pending"] = ([{"kind": kind, "id": who, "note": comment, "ts": now}]
                               + [p for p in data["pending"] if isinstance(p, dict)])[:20]
            data["new"] = (data["new"] + [{"kind": "request", "id": who,
                                           "name": comment or who, "ts": now}])[-CIRCLE_MAX_NEW:]
            changed, note = True, "收到%s（%s）" % (kind, comment or who)
            # 2026-11-21：自动通过好友（群邀请默认不自动接，免得被拉进乱七八糟的群）
            flag = str(raw.get("flag") or "")
            sub_type = str(raw.get("sub_type") or "")
            if rtype == "friend" and flag and self.cfg_bool("auto_accept_friend", True):
                if await self._circle_call_ok("set_friend_add_request", flag=flag, approve=True):
                    changed = True
                    note = "已自动通过好友申请（%s）" % (comment or who)
                    data["new"] = (data["new"] + [{"kind": "friend", "id": who,
                                                   "name": comment or who, "ts": now}])[-CIRCLE_MAX_NEW:]
                    self._circle_save(data)
                    try:
                        await self._circle_refresh(None, force=True)
                    except Exception as exc:
                        logger.debug("[amo] 通过好友后刷新名单失败: %s" % exc)
            elif (rtype == "group" and sub_type == "invite" and flag
                  and self.cfg_bool("auto_accept_group_invite", False)):
                if await self._circle_call_ok("set_group_add_request", flag=flag,
                                              sub_type="invite", approve=True):
                    changed = True
                    note = "已自动接受入群邀请（%s）" % (comment or who)
                    data["new"] = (data["new"] + [{"kind": "group", "id": group_id or who,
                                                   "name": comment or who, "ts": now}])[-CIRCLE_MAX_NEW:]
        elif post == "notice" and notice == "friend_add":
            info = await self._circle_api("get_stranger_info", None, user_id=user_id) if user_id else None
            name = _circle_clean((info or {}).get("nickname") if isinstance(info, dict) else "") or user_id
            data["new"] = (data["new"] + [{"kind": "friend", "id": user_id,
                                           "name": name, "ts": now}])[-CIRCLE_MAX_NEW:]
            changed, note = True, "新好友 %s" % name
        elif post == "notice" and notice == "group_increase" and group_id and user_id == self_id:
            info = await self._circle_api("get_group_info", None, group_id=group_id)
            info = info if isinstance(info, dict) else {}
            name = _circle_clean(info.get("group_name") or group_id) or group_id
            try:
                count = int(info.get("member_count") or 0)
            except Exception:
                count = 0
            data["groups"] = [g for g in data["groups"]
                              if not (isinstance(g, dict) and str(g.get("id")) == group_id)]
            data["groups"].append({"id": group_id, "name": name, "count": count,
                                   "since": now, "seen": now})
            data["new"] = (data["new"] + [{"kind": "group", "id": group_id,
                                           "name": name, "ts": now}])[-CIRCLE_MAX_NEW:]
            changed, note = True, "被拉进群「%s」" % name
        elif post == "notice" and notice == "group_decrease" and group_id and user_id == self_id:
            before = len(data["groups"])
            data["groups"] = [g for g in data["groups"]
                              if not (isinstance(g, dict) and str(g.get("id")) == group_id)]
            changed = len(data["groups"]) != before
            note = "退出了群 %s" % group_id
        if changed:
            self._circle_save(data)
            if note:
                logger.info("[amo] 社交圈：%s" % note)

    async def _circle_track(self, event):
        """每条消息都过一遍：通知类记下来，名单过期就顺手刷新。"""
        raw = None
        try:
            raw = getattr(getattr(event, "message_obj", None), "raw_message", None)
        except Exception:
            raw = None
        if isinstance(raw, dict):
            try:
                await self._circle_signal(raw)
            except Exception as exc:
                logger.debug("[amo] 社交圈通知处理失败: %s" % exc)
        try:
            await self._circle_refresh(event)
        except Exception as exc:
            logger.debug("[amo] 社交圈刷新失败: %s" % exc)

    # ---------------------------------------------------------------- 提示词
    def _circle_context_lines(self, event=None, is_group=False):
        """给提示词的两三行：这个群叫什么、她还在哪些群、最近谁新来。"""
        try:
            data = self._circle_data()
        except Exception:
            return []
        now = now_ts()
        groups = [g for g in data["groups"] if isinstance(g, dict) and g.get("id")]
        gid = ""
        if is_group and event is not None:
            try:
                gid = str(event.get_group_id() or "")
            except Exception:
                gid = ""
        lines = []
        current = next((g for g in groups if str(g.get("id")) == gid), None) if gid else None
        if current is None and gid and event is not None:
            # 名单还没拉到她刚被拉进的群：先用消息自带的群名顶一下
            try:
                _g = getattr(getattr(event, "message_obj", None), "group", None)
                _name = _circle_clean(getattr(_g, "group_name", "") or "")
            except Exception:
                _name = ""
            if _name:
                current = {"id": gid, "name": _name, "count": 0}
        if current is not None:
            name = _circle_clean(current.get("name") or gid)
            try:
                count = int(current.get("count") or 0)
            except Exception:
                count = 0
            lines.append("【这个群】你现在说话的这个群叫「%s」%s。"
                         % (name, ("（%d 人）" % count) if count > 1 else ""))
        others = [g for g in groups if str(g.get("id")) != gid]
        names = ["「" + _circle_clean(g.get("name") or g.get("id")) + "」"
                 for g in others[:CIRCLE_LIST_IN_PROMPT]]
        if names:
            tail = ""
            if len(others) > len(names):
                tail = "等 %d 个群" % len(others)
            lines.append(("【别的群】你还在：" if is_group else "【你在的群】")
                         + "、".join(names) + tail + "。")
        # 好友名册不往提示词里放：人物和关系归「思维图」（画像 + relation_network），
        # 社交圈只管群，以及「谁刚加了你 / 谁刚把你拉进群」这种变化，别两边各说一套。
        # 最近的变化：被拉进新群 / 有人加她好友 / 有人申请还没通过
        bits = []
        for item in reversed(data["new"]):
            if not isinstance(item, dict):
                continue
            ts = float(item.get("ts") or 0)
            if now - ts > CIRCLE_NEW_WINDOW:
                continue
            kind = str(item.get("kind") or "")
            name = _circle_clean(item.get("name") or item.get("id") or "")
            day = _circle_day(ts, now)
            if kind == "group":
                bits.append("%s被拉进了「%s」这个群" % (day, name))
            elif kind == "friend":
                bits.append("%s「%s」加了你好友" % (day, name))
            elif kind == "request":
                bits.append("%s有人申请加你（%s），你还没管" % (day, name))
            if len(bits) >= 2:
                break
        if bits:
            lines.append("【最近】" + "；".join(bits) + "。")
        return lines

    # ---------------------------------------------------------------- 调试
    def _circle_dump(self):
        """一行摘要 + 明细，给 /circle 命令和面板用。"""
        data = self._circle_data()
        now = now_ts()
        ago = ""
        if data["ts"]:
            ago = "（%d 分钟前拉过名单）" % int(max(0, now - data["ts"]) // 60)
        head = "群 %d 个 / 好友 %d 个%s" % (
            len([g for g in data["groups"] if isinstance(g, dict)]),
            len([f for f in data["friends"] if isinstance(f, dict)]),
            ago,
        )
        lines = [head]
        for g in data["groups"][:20]:
            if not isinstance(g, dict):
                continue
            lines.append("· 群「%s」（%s，%s 人）"
                         % (_circle_clean(g.get("name") or g.get("id")),
                            g.get("id"), g.get("count") or "?"))
        for f in data["friends"][:10]:
            if not isinstance(f, dict):
                continue
            lines.append("· 好友 %s（%s）" % (_circle_clean(f.get("name") or f.get("id")),
                                              f.get("id")))
        kind_cn = {"group": "新群", "friend": "新好友", "request": "申请"}
        news = [i for i in data["new"] if isinstance(i, dict)]
        if news:
            lines.append("最近变化：")
            for item in news[-8:]:
                lines.append("· %s %s %s"
                             % (_circle_day(item.get("ts"), now),
                                kind_cn.get(str(item.get("kind") or ""), item.get("kind")),
                                _circle_clean(item.get("name") or item.get("id"))))
        pend = [i for i in data["pending"] if isinstance(i, dict)]
        if pend:
            lines.append("待处理申请：")
            for item in pend[:5]:
                lines.append("· %s %s" % (item.get("kind"),
                                          _circle_clean(item.get("note") or item.get("id"))))
        return "\n".join(lines)


__all__ = ["CircleMixin", "CIRCLE_KEY", "CIRCLE_REFRESH_GAP"]
