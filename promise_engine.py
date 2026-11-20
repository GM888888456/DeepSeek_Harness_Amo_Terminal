# -*- coding: utf-8 -*-
"""她答应过的事（承诺账本）。

病象（2026-11-15 10:07，私聊）：他要一张照片，她回「等我把车停稳了嘛，开着车咋个拍嘛」，
可出图判定在同一秒就放行了，几秒后图发到他手机上；十分钟后她又说「等我先找个地方把车停好」。
话和图各走各的——因为出图判定只看「他要不要照片」，既不看日程，也没有任何地方记着「她答应了」。

做法（只给事实，不给台词）：

* 她说出口的承诺落成一条 kv 记录：kind / 等什么条件 / 原话 / 会话 / 时间；
* 每一轮把还没兑现的那几条当事实注入，怎么说由她自己定；
* 条件满足（车停了、到地方了、到点了）由 60 秒巡检真的去做：照片补拍发出去。

记录最多 5 条、3 小时过期，兑现过的留 10 分钟给下一轮对话对得上。
"""

from __future__ import annotations

import re
import time

#: kv 键
KEY = "promises"

#: 承诺的方向。2026-11-15 的病象：她明明答应「穿 JK 拍给他看」，
#: 转头变成「你答应我的那事还没做，自己想」——账本里只记了她那句话、
#: 没记「谁答应的」，注入时又统一写成「你答应过的事」，方向就反了。
SIDE_HER = "her"   # 她答应他：要做的是她
SIDE_HIS = "his"   # 他答应她：等他做，她只记着

KIND_PHOTO = "photo"   # 答应拍一张：车停了 / 到地方了就拍
KIND_ACT = "act"       # 答应到地方做某件事：到了就去逛 / 回家再弄

WAIT_DRIVE = "drive"   # 等车停下来
WAIT_PLACE = "place"   # 等到某个地方
WAIT_TIME = "time"     # 等到某个时刻

#: 日程里出现这些词就算「在路上/在开车」，这时候拍不了一张自拍
DRIVE_WORDS = ("开车", "驾车", "驾驶", "路上", "通勤", "堵车", "赶路",
               "在车里", "等红灯", "高速", "导航")

#: 「等会儿/到了/停好车」这类将来时的引子
LATER_WORDS = ("等", "等会", "等会儿", "待会", "待会儿", "一会", "一会儿",
               "稍后", "晚点", "到了", "停好", "停稳", "停了车", "下了车",
               "回家", "到家", "下班", "回头")

#: 说到「拍」的动词
PHOTO_WORDS = ("拍", "自拍", "照片", "给你看", "发你", "发给你")

#: 已经做完的说法，别当成承诺
PAST_WORDS = ("已经", "刚才", "刚拍", "拍好", "拍完", "刚发", "发了")

#: 「到了XX就」里的地点
PLACE_RE = re.compile(r"到了([^，。！？!?、\s]{2,12}?)(?:就|再|之后|以后|的时候|后)")
#: 这些不是地点，别拿它当条件
NOT_PLACE = ("那儿", "那里", "这儿", "这里", "地方", "时候", "家里", "车上")

#: 「到了/回家 + 就/再 + 动词」才算「到地方做某件事」
ACT_VERBS = ("去", "找", "吃", "逛", "换", "弄", "买", "试", "见", "做", "看")

#: 他说「我答应你…」「答应你的…」——这是他欠她的事，别记成她欠他的。
#: 2026-11-15 10:12 的病象：她答应的 JK 照片，被她说成「你答应我的那事还没做」。
HIS_PROMISE_RE = re.compile(
    r"(?:我|咱)(?:一定|肯定|保证)?(?:会|要|去|来)?(?:答应|承诺)"
    r"|(?:你|您)(?:的|那件事?)?(?:答应|承诺)(?:我的|过我)"
    r"|我(?:说好了|说好)|我们说好的")


def his_side(text, *, speaker="", bot_uid="", sender_uid="") -> str:
    """这句话里的承诺是谁答应的：返回 ``his`` / ``her``。

    ``speaker`` 只在能分清是谁说的时候给（``user`` / ``bot``）；
    分不清时按字面判断——「我答应你」是他在答应，所以是 his。
    """
    body = str(text or "")
    if not body.strip():
        return SIDE_HER
    if str(speaker or "") == "bot":
        return SIDE_HER
    return SIDE_HIS if HIS_PROMISE_RE.search(body) else SIDE_HER


SENTENCE_RE = re.compile(r"[^。！？!?\n]+")


def activity_text(activity) -> str:
    """日程那一格拼成一句，只用来判断在不在开车。"""
    if isinstance(activity, dict):
        return "%s %s" % (activity.get("place") or "", activity.get("activity") or "")
    return str(activity or "")


def driving(activity) -> str:
    """在开车就返回那个词，否则空串。"""
    text = activity_text(activity)
    for word in DRIVE_WORDS:
        if word in text:
            return word
    return ""


def place_of(activity) -> str:
    if isinstance(activity, dict):
        return str(activity.get("place") or "").strip()
    return ""


def _sentences(text):
    return [item.strip() for item in SENTENCE_RE.findall(str(text or "")) if item.strip()]


def detect_photo_later(text) -> str:
    """她说「等…再拍 / 到了…给你拍」→ 返回那句原话；不是将来时的不算。"""
    for sentence in _sentences(text):
        if len(sentence) > 60:
            continue
        if not any(word in sentence for word in PHOTO_WORDS):
            continue
        if any(word in sentence for word in PAST_WORDS):
            continue
        if any(word in sentence for word in LATER_WORDS):
            return sentence
    return ""


def detect_act_later(text) -> str:
    """「到了古镇我就去逛」「回家再弄」这类到地方才做的事；返回原话或空串。"""
    for sentence in _sentences(text):
        if len(sentence) > 60:
            continue
        if not any(word in sentence for word in ("到了", "回家", "到家", "下班", "停好", "停稳")):
            continue
        if not any(word in sentence for word in ("就", "再")):
            continue
        if not any(word in sentence for word in ACT_VERBS):
            continue
        if any(word in sentence for word in PAST_WORDS):
            continue
        return sentence
    return ""


def detect_place(text) -> str:
    """「到了古镇就…」里的「古镇」；不是地点就返回空串。"""
    match = PLACE_RE.search(str(text or ""))
    if not match:
        return ""
    place = match.group(1).strip()
    if not place or place in NOT_PLACE:
        return ""
    return place[:16]


class PromiseEngine:
    """她的承诺账本：记着、提醒她、条件到了就真的做。"""

    MAX_ROWS = 5
    TTL = 3 * 3600
    KEEP_DONE = 600

    def __init__(self, db, clock=None):
        self.db = db
        self.clock = clock or time.time

    # ---------- 读写 ----------
    def rows(self):
        try:
            data = self.db.kv_get(KEY, []) or []
        except Exception:
            data = []
        if not isinstance(data, list):
            return []
        return [row for row in data if isinstance(row, dict)]

    def _save(self, rows):
        try:
            self.db.kv_set(KEY, list(rows)[-self.MAX_ROWS:])
        except Exception:
            pass

    def add(self, kind, text, *, umo="", uid="", wait=WAIT_TIME,
            due_ts=0, place="", from_place="", look="", style="", want="",
            side=SIDE_HER):
        """记一条她答应的事；同一件事还欠着就不再记第二条。

        2026-11-16 的病象：同一张照片，她 17:09「等哈嘛…拍一张给你」、17:12「收个尾就拍给你」、
        17:23「我正收尾呢，拍好就发你」、17:24「再等哈哈儿，我收好尾就发你」——
        四句话各记一条，`facts()` 每轮把四条一起喂回去，模型只好再保证一次，
        于是「一直重复收尾就发给你」停不下来。

        现在按「同一件事」合并：kind 相同、都没兑现、且目标一致（同款式/同地点/同类等待），
        就算同一件事——保留最早那条（先答应的时间更算数），把新原话记进去，
        并把「又被催了一次」的次数记上，等真正兑现时一起清掉。
        """
        text = str(text or "").strip()[:60]
        if not text:
            return None
        now = float(self.clock())
        rows = self.rows()
        style = str(style or "")
        for row in rows:
            if row.get("done") or row.get("kind") != kind:
                continue
            if row.get("text") == text:
                return row
            if self._same_thing(row, wait=wait, place=place, style=style, kind=kind):
                # 同一件事：不新增，只把最新说法与催促次数补上
                row["text"] = text
                row["repeat"] = int(row.get("repeat") or 1) + 1
                row["last_nag_ts"] = now
                if due_ts and not row.get("due_ts"):
                    row["due_ts"] = int(due_ts)
                if look and not row.get("look"):
                    row["look"] = str(look)[:200]
                self._save(rows)
                return row
        row = {
            "id": int(now * 1000),
            "kind": str(kind or KIND_PHOTO),
            "text": text,
            "wait": str(wait or WAIT_TIME),
            "place": str(place or "")[:16],
            "from_place": str(from_place or "")[:16],
            "due_ts": int(due_ts or 0),
            # 答应那一刻身上这套 / 他要求的款式 / 他原话：兑现时照这个拍，不照后来的日程
            "look": str(look or "")[:200],
            "style": str(style or "")[:16],
            "want": str(want or "")[:60],
            # 这条承诺是谁答应的：her=她答应他（要做的是她）/ his=他答应她（等他做）
            "side": str(side or SIDE_HER),
            "umo": str(umo or ""),
            "uid": str(uid or ""),
            "ts": now,
            "done": False,
        }
        rows.append(row)
        self._save(rows)
        return row

    @staticmethod
    def _same_thing(row, *, wait="", place="", style="", kind="") -> bool:
        """两条记录是不是「同一件事」：同一类承诺、同一个目标。

        只比目标，不比措辞——「等哈拍给你」「收个尾就拍给你」「拍好就发你」
        是同一件事的三种说法。款式不同（JK 和汉服）或地点不同就不算。
        """
        if str(row.get("kind") or "") != str(kind or ""):
            return False
        row_style = str(row.get("style") or "")
        want_style = str(style or "")
        if row_style and want_style and row_style != want_style:
            return False
        row_place = str(row.get("place") or "")
        want_place = str(place or "")
        if row_place and want_place and row_place != want_place:
            return False
        row_wait = str(row.get("wait") or "")
        want_wait = str(wait or "")
        # 等的东西不一样就不是同一件：等车停 vs 等到某个地方 vs 等到点
        if row_wait and want_wait and row_wait != want_wait:
            return False
        return True

    def mark_done(self, pid, now=None):
        now = float(now or self.clock())
        rows = self.rows()
        changed = False
        for row in rows:
            if row.get("id") == pid and not row.get("done"):
                row["done"] = True
                row["done_ts"] = now
                changed = True
        if changed:
            self._save(rows)

    def clear(self):
        self._save([])

    def prune(self, now=None):
        """过期/兑现太久的清掉，免得一年后还在提醒她。"""
        now = float(now or self.clock())
        keep = []
        for row in self.rows():
            if row.get("done"):
                if now - float(row.get("done_ts") or 0) < self.KEEP_DONE:
                    keep.append(row)
                continue
            if now - float(row.get("ts") or 0) > self.TTL:
                continue
            keep.append(row)
        self._save(keep)
        return keep

    # ---------- 条件 ----------
    @staticmethod
    def ready(row, activity, now=None) -> bool:
        now = float(now or time.time())
        wait = str(row.get("wait") or WAIT_TIME)
        if wait == WAIT_DRIVE:
            return not driving(activity)
        if wait == WAIT_PLACE:
            place = str(row.get("place") or "")
            current = place_of(activity)
            if not current:
                return False
            if place and (place in current or current in place):
                return True
            # 换了个地方也算「到了」：她说的地儿和日程写法不一定对得上
            return bool(place) and current != str(row.get("from_place") or "")
        due = float(row.get("due_ts") or 0)
        return bool(due) and now >= due

    def due_rows(self, activity, now=None, kind=None):
        now = float(now or self.clock())
        out = []
        for row in self.rows():
            if row.get("done"):
                continue
            if kind and row.get("kind") != kind:
                continue
            if self.ready(row, activity, now):
                out.append(row)
        return out

    # ---------- 给模型的事实 ----------
    def facts(self, activity, now=None):
        """还没兑现的那几条，按事实写：等什么、现在能不能做。"""
        now = float(now or self.clock())
        lines = []
        for row in self.rows():
            if row.get("done"):
                continue
            text = str(row.get("text") or "").strip()
            if not text:
                continue
            ready = self.ready(row, activity, now)
            status = self._ready_note(row, activity) if ready else self._wait_note(row, activity)
            repeat = int(row.get("repeat") or 1)
            side = str(row.get("side") or SIDE_HER)
            if side == SIDE_HIS:
                # 他答应她的事：等他做，她只记着——绝不能写成「你还没做」
                prefix = "【他答应过你的事】"
                if repeat >= 2:
                    lines.append(
                        "%s「%s」——你已经问过 %d 次了。这是**他**答应你的，"
                        "不是你要做的；别再追问同一个细节，也别把这件事说成你自己欠他的。"
                        % (prefix, text, repeat))
                else:
                    lines.append("%s「%s」——还没兑现，可以提一句，但别催得太紧。"
                                 % (prefix, text))
                continue
            if repeat >= 2:
                # 同一件事已经保证过好几轮：再保证一次就是复读机，明确要求换说法或直接做
                lines.append(
                    "【你已经答应过 %d 次的事】「%s」——%s。"
                    "这件事你已经说过不止一次「收尾就发你/等会儿就给你」了，"
                    "这回别再重复保证，要么直接做，要么说点别的。"
                    % (repeat, text, status))
                continue
            if ready:
                lines.append("【你答应过他的事】「%s」——%s，可以做。" % (text, status))
            else:
                lines.append("【你答应过他的事】「%s」——%s。" % (text, status))
        return lines

    def _wait_note(self, row, activity):
        wait = str(row.get("wait") or WAIT_TIME)
        if wait == WAIT_DRIVE:
            return "你还在%s，这时候做不了" % (driving(activity) or "路上")
        if wait == WAIT_PLACE:
            return "还没到%s" % (str(row.get("place") or "") or "那个地方")
        due = float(row.get("due_ts") or 0)
        left = max(0, int(due - float(self.clock())))
        if left >= 60:
            return "还没到点（大概 %d 分钟以后）" % max(1, left // 60)
        return "还不到时候"

    @staticmethod
    def _ready_note(row, activity):
        place = place_of(activity)
        if place:
            return "已经到%s了" % place
        return "时间到了"


#: 给 「到了地方就做某事」 用的公共判断，测试和别处都能直接用
def step_ready(row, activity, now=None) -> bool:
    return PromiseEngine.ready(row, activity, now)
