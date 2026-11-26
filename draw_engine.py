# -*- coding: utf-8 -*-
"""画图引擎：判定在终端，出图交给生图插件。

玩法：她正常回完话之后，按配置判断这轮要不要顺手画一张给她发过去。

- 触发方式（``draw_trigger_mode``）：
  - ``topic``：他这句话里出现 ``draw_topic_keywords`` 里的词（默认：吃什么/吃啥/在干嘛…），
    就用她刚才的回复当画面描述；
  - ``explicit``：他明确说「画一张 / 给我画 / 发张图 / 自拍」才画，用他这句话当描述；
  - ``both``：两种都算。
- 生成走生图插件 ``Astrbot_Amo_Image.draw_for()``（终端只拿字节，不自己管模型/额度），
  拿到图之后再通过 ``event.send()`` 补一条图片消息，所以她的文字一定先到，图后到。
- 每次生成都在后台任务里跑，不阻塞她说话；失败只记日志，不会把回复吞掉。

和主脑的关系：
- ``maybe_after_reply()`` 由 ``on_decorating_result()`` 调用（只负责判断 + 起任务）；
- ``/amo draw 描述`` 是给测试用的手动入口（不依赖触发词）。

数据只在内存里（冷却、每小时/每天计数），重启清零；不写数据库。
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import os
import re
import time
import urllib.request

from astrbot.api import logger

try:  # 统一时区：容器/服务器常在 UTC 跑
    from .clock import today_str as _today_str
except ImportError:  # 直接按文件加载时
    try:
        from clock import today_str as _today_str
    except ImportError:  # pragma: no cover
        from datetime import datetime as _dt

        def _today_str(*args, **kwargs):
            return _dt.now().date().isoformat()


try:  # 主模块有被吞异常计数，能复用就复用（既有的 amo_observability）
    from .amo_observability import note as _note_swallowed
except ImportError:
    try:
        from amo_observability import note as _note_swallowed
    except ImportError:
        def _note_swallowed(where, exc):
            logger.debug("[amo] %s 已忽略: %s", where, exc)


try:
    from astrbot.api.message_components import Image
except ImportError:  # 老版本/兼容路径
    try:
        from astrbot.api.event.components import Image
    except Exception:  # pragma: no cover
        Image = None

try:
    from astrbot.core.message.message_result import MessageChain
except Exception:  # pragma: no cover - 单测会注入桩
    try:
        from astrbot.core.message.message_event_result import MessageChain
    except Exception:
        MessageChain = None

GENERATE_TIMEOUT_SECONDS = 180
# data_url 是 base64，超过这个长度就不进 kv（否则数据库会被撑大）
_MAX_CACHED_DATA_URL = 200000

OMNI_PLUGIN_NAME = "astrbot_plugin_omnidraw"

DEFAULT_TOPIC_KEYWORDS = (
    "吃什么,吃啥,吃点什么,想吃什么,去哪吃,在干嘛,在做什么,做什么,好饿,饿了,"
    "想喝,喝什么,喝啥,想玩,在忙什么"
)

DEFAULT_EXPLICIT_KEYWORDS = (
    # 2026-11-26 用户口径：没人喊「画一张」，都是「拍一张 / 拍个照」。
    # 触发词只留拍照说法，出图依旧是画她自己（自拍）。
    "拍张,拍一张,拍个照,拍一张照,拍张照片,拍一张照片,拍照,拍给我,拍一下,"
    "拍来看看,拍拍看,再拍一张,再拍张,多拍几张,发张照片,发张自拍,来张照片,"
    "发我一张,给我拍,照片给我,照片发我,看看照片,照片看看,你的照片,照片呢,"
    "说好的照片,自拍,想看看你,让我看看你"
)

#: 命中这些词就当他是在要照片：明着要照片不该被普通冷却拦住（每小时/每天上限照旧）
PHOTO_ASK_WORDS = (
    "拍给我", "拍照", "拍张", "拍一张", "拍个照", "拍来看看", "拍拍看", "拍一下",
    "照片", "自拍", "想看看你", "让我看看你", "发张照",
    # 「再发一张 / 再来一张 / 再拍一张 / 多拍几张」：这是在继续要她的照片。
    # 缺了这几个说法时，「再发一张」只命中 explicit 触发词里的「发一张」，
    # 于是 selfie 判成 False，生图走 OTHER_CAMERA —— 就成了别人举手机拍的她。
    "再发一张", "再发张", "再发个", "再发两", "再发几", "再来一张", "再来张",
    "再拍一张", "再拍张", "再拍个", "多拍一张", "多拍几", "多发一张", "多发几张",
    "换一张", "换张", "再给我发", "再给我拍", "要一张",
)

_EXPLICIT_CLEAN_RE = re.compile(
    r"(请|麻烦)?(你)?(能不能|可不可以|可以|要不要)?(给我|帮我|替我)?"
    r"(拍张照片|拍一张照片|拍个照|拍张照|拍一张照|拍照给我看看|拍照给我|拍照|"
    r"照片给我看看|照片给我|照片发我|发张照片|发张自拍|来张照片|发我一张|"
    r"给我拍一张|给我拍|拍一张给我|拍个照给我|拍给我看看|拍给我看|拍给我|"
    r"拍来看看|拍拍看|多拍几张|再拍一张|再拍张|拍张|拍一张|拍一下|拍个|"
    r"想看看你|让我看看你|看看照片|照片看看|你的照片|照片呢|说好的照片|自拍|"
    r"给我看看|发一张|发张|发个)"
)
_TAIL_PUNCT_RE = re.compile(r"[\s，,。.！!？?~～…]+$")
_FILLER_TAIL_RE = re.compile(r"(吧|呀|啊|呢|啦|哦|哈|嘛|咯)+$")

QUESTION_WORDS = (
    "吗", "呢", "怎么样", "如何", "在干吗", "干嘛", "在做什么", "做什么", "开心",
    "好不好", "是不是", "在不在", "在哪", "玩得", "有没有", "什么", "啥", "哪里",
)

FILLER_WORDS = (
    "开心", "在呀", "好呀", "是呀", "对呀", "还行", "还好", "哈哈", "嘿嘿",
    "老婆", "老公", "宝贝", "能不能", "可不可以", "可以", "要不要",
    "看看", "看一下", "拍", "照片", "图片",
    "呀", "啊", "啦", "哦", "嗯", "呢", "吧", "嘛",
)

# 用来做「同一场景」缓存的词；命中越多越容易被当成同一张图
SCENE_KEYWORDS = (
    "公园", "狗", "猫", "咖啡", "奶茶", "面条", "火锅", "烧烤", "蛋糕", "海边", "沙滩",
    "山", "古镇", "街", "商场", "书店", "花", "樱花", "雨", "雪", "夕阳", "夜景",
    "电影院", "地铁", "公交", "办公室", "家", "厨房", "阳台", "床", "餐桌", "餐厅",
    "学校", "操场", "湖", "河", "跑步", "散步", "蛋糕", "冰淇淋", "水果", "衣服",
    "裙子", "毛衣", "围巾", "帽子", "电脑", "书", "电影", "音乐", "旅行",
)


def _split_keywords(text):
    return [item.strip() for item in str(text or "").replace("，", ",").split(",") if item.strip()]


def clean_explicit_prompt(text):
    """「给我画一碗面」→「一碗面」。"""
    text = str(text or "").strip()
    cleaned = _EXPLICIT_CLEAN_RE.sub(" ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return _TAIL_PUNCT_RE.sub("", cleaned)


def clean_topic_prompt(text, max_chars=80):
    """她刚说的话 → 画面描述。去掉换行/引号/末尾语气词，截断到 max_chars。"""
    text = str(text or "").replace("\n", " ").strip()
    text = text.strip("\"'“”‘’「」『』 ")
    text = _TAIL_PUNCT_RE.sub("", text)
    text = _FILLER_TAIL_RE.sub("", text).strip()
    max_chars = max(12, int(max_chars or 80))
    if len(text) > max_chars:
        text = text[:max_chars].rstrip("，,。.、 ")
    return text


class DrawEngine:
    def __init__(self, plugin):
        self.plugin = plugin
        self._last_draw = {}      # uid -> monotonic
        self._draw_times = {}     # uid -> [monotonic, ...]
        self._inflight = set()    # umo
        self._last_prompt = {}    # uid -> (prompt, monotonic)
        self._omni = None
        self._omni_checked = 0.0
        self._stats = {"scheduled": 0, "sent": 0, "failed": 0, "skipped": 0, "cached": 0}
        self._last_error = ""

    # ---------- 配置 ----------

    def _cfg_bool(self, key, default=False):
        try:
            return bool(self.plugin.cfg_bool(key, default))
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine._cfg_bool", _amo_exc)
            return default

    def _cfg_int(self, key, default=0):
        try:
            return int(self.plugin.cfg_int(key, default))
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine._cfg_int", _amo_exc)
            return default

    def _cfg_float(self, key, default=0.0):
        try:
            return float(self.plugin.cfg_float(key, default))
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine._cfg_float", _amo_exc)
            return default

    def _cfg_str(self, key, default=""):
        try:
            return str(self.plugin.cfg_str(key, default))
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine._cfg_str", _amo_exc)
            return default

    @property
    def enabled(self):
        return self._cfg_bool("draw_enable", True)

    def _mode(self):
        mode = self._cfg_str("draw_trigger_mode", "topic").strip().lower()
        return mode if mode in ("topic", "explicit", "both") else "topic"

    def _topic_keywords(self):
        raw = self._cfg_str("draw_topic_keywords", DEFAULT_TOPIC_KEYWORDS)
        return _split_keywords(raw) or _split_keywords(DEFAULT_TOPIC_KEYWORDS)

    def _explicit_keywords(self):
        raw = self._cfg_str("draw_explicit_keywords", DEFAULT_EXPLICIT_KEYWORDS)
        return _split_keywords(raw) or _split_keywords(DEFAULT_EXPLICIT_KEYWORDS)

    # ---------- 权限 / 限额 ----------

    def is_owner(self, event):
        """谁能触发画图：draw_owner_ids（配了只认名单）> 管理员 > 关系「相恋」。"""
        raw = self._cfg_str("draw_owner_ids", "")
        owners = {item for item in _split_keywords(raw.replace(" ", ","))}
        uid = ""
        try:
            uid = str(self.plugin._canonical_uid(event) or "")
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine.is_owner", _amo_exc)
        if owners:
            return bool(uid) and uid in owners
        try:
            if self.plugin._is_admin(event):
                return True
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine.is_owner", _amo_exc)
        if uid:
            try:
                profile = self.plugin.db.get_profile(uid) or {}
                if str(profile.get("relation") or "") == "相恋":
                    return True
            except Exception as _amo_exc:
                _note_swallowed("draw_engine.DrawEngine.is_owner", _amo_exc)
        return False

    @staticmethod
    def _is_photo_ask(text):
        body = str(text or "")
        return any(word in body for word in PHOTO_ASK_WORDS)

    def _check_limits(self, uid, explicit=False, private=False):
        """返回 None 表示可以画；否则返回跳过原因。

        2026-11-18：私聊不限量、不冷却（用户明确要求）——她一个人跟主人聊天，
        一小时多要几张照片是天经地义的；每小时 3 张 / 每天 10 张只用于群聊。
        """
        # private_unlimited
        if private:
            return None
        now = time.monotonic()
        cooldown = max(0, self._cfg_int("draw_cooldown_minutes", 30)) * 60
        last = self._last_draw.get(uid, 0.0)
        # 他明着要照片时不吃冷却（每小时/每天上限照旧兜着），
        # 否则「刚发过一张」的 30 分钟里要图只会石沉大海。
        if cooldown and last and now - last < cooldown and not explicit:
            return "冷却中（%d 秒）" % int(cooldown - (now - last))
        times = list(self._draw_times.get(uid, []))
        hour = [ts for ts in times if now - ts < 3600]
        max_hour = max(0, self._cfg_int("draw_max_per_hour", 3))
        if max_hour <= 0:
            return "画图限额为 0（已关闭）"
        if len(hour) >= max_hour:
            return "这一小时画满了"
        # 以前这里从 hour 里再筛 86400，等于"每天"只看最近一小时，日限额根本拦不住
        day = [ts for ts in times if now - ts < 86400]
        max_day = max(0, self._cfg_int("draw_max_per_day", 10))
        if max_day <= 0:
            return "画图限额为 0（已关闭）"
        if len(day) >= max_day:
            return "今天画满了"
        return None

    def _record(self, uid):
        now = time.monotonic()
        self._last_draw[uid] = now
        times = [ts for ts in self._draw_times.get(uid, []) if now - ts < 86400]
        times.append(now)
        self._draw_times[uid] = times

    # ---------- 触发判断 ----------

    # ---------- 场景缓存（同一场景在哪个平台问，都发同一张） ----------

    @staticmethod
    def _cache_key(prompt, keywords=None, selfie=False, residual=""):
        parts = [_today_str(), "selfie" if selfie else "scene"]
        if selfie:
            # 自拍别拿同一张顶一整天：5 分钟一个桶，换个姿势重新画
            parts.append("bucket:%d" % int(time.time() // 300))
        if keywords:
            parts.append(",".join(sorted(set(keywords))))
        if residual:
            parts.append(hashlib.sha1(str(residual).encode("utf-8")).hexdigest()[:8])
        if not keywords and not residual:
            parts.append(hashlib.sha1(str(prompt or "").encode("utf-8")).hexdigest())
        return "draw_cache:" + hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:16]

    def _cache_get(self, key):
        minutes = self._cfg_int("draw_cache_minutes", 1440)
        if minutes <= 0:
            return None
        try:
            item = self.plugin.db.kv_get(key, {}) or {}
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine._cache_get", _amo_exc)
            return None
        if not isinstance(item, dict):
            return None
        try:
            ts = float(item.get("ts") or 0)
        except Exception:
            ts = 0.0
        if not ts or time.time() - ts > minutes * 60:
            return None
        path = str(item.get("file_path") or "")
        if path and not os.path.exists(path):
            path = ""
        url = str(item.get("url") or "")
        data_url = str(item.get("data_url") or "")
        if not path and not url and not data_url:
            return None
        return {"file_path": path, "url": url, "data_url": data_url}

    def _cache_put(self, key, item):
        if self._cfg_int("draw_cache_minutes", 1440) <= 0 or not isinstance(item, dict):
            return
        file_path = str(item.get("file_path") or "")
        url = str(item.get("url") or item.get("image_url") or "")
        data_url = str(item.get("data_url") or "")
        if not (file_path or url or data_url):
            return
        # 有本地文件/外链就够了；data_url 是 base64，存进 kv 会把库撑到几百 MB
        if data_url and (file_path or url or len(data_url) > _MAX_CACHED_DATA_URL):
            data_url = ""
        if not (file_path or url or data_url):
            return
        payload = {
            "ts": time.time(),
            "file_path": file_path,
            "url": url,
            "data_url": data_url,
        }
        try:
            self.plugin.db.kv_set(key, payload)
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine._cache_put", _amo_exc)

    @staticmethod
    def _concrete_len(text):
        """去掉问句词和语气词后还剩多少“实词”，用来判断哪句话更有画面。"""
        body = str(text or "")
        for word in QUESTION_WORDS + FILLER_WORDS:
            body = body.replace(word, "")
        body = re.sub(r"[\s，,。.！!？?~～…]+", "", body)
        return len(body)

    def _is_vague_request(self, text):
        """「你在公园吗」「公园玩的开心吗」这类问句，不能拿它本身当画面。"""
        cleaned = clean_explicit_prompt(text)
        if not cleaned:
            return True
        return any(word in text for word in QUESTION_WORDS)

    def _richer(self, *texts):
        best = ""
        for text in texts:
            text = str(text or "").strip()
            if self._concrete_len(text) > self._concrete_len(best):
                best = text
        return best

    def _driving_word(self):
        """日程说她在开车/在路上：这时候拍不了一张自拍。"""
        try:
            activity = self.plugin.state.current_activity() or {}
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine._driving_word", _amo_exc)
            return ""
        text = "%s %s" % (activity.get("place") or "", activity.get("activity") or "")
        for word in ("开车", "驾车", "驾驶", "路上", "通勤", "堵车", "赶路",
                     "在车里", "等红灯", "高速", "导航"):
            if word in text:
                return word
        return ""

    def _place_text(self):
        try:
            activity = self.plugin.state.current_activity() or {}
            return "%s %s" % (activity.get("place") or "", activity.get("activity") or "")
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine._place_text", _amo_exc)
            return ""

    @staticmethod
    def _clean_place(place):
        place = str(place or "").strip()
        if not place:
            return ""
        if "桌" in place or place.startswith("他") or place.startswith("她"):
            return "家里"
        return place[:16]

    def _current_scene(self):
        """她此刻真实在哪、在干嘛（来自日程）。"""
        try:
            activity = self.plugin.state.current_activity() or {}
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine._current_scene", _amo_exc)
            return ""
        place = self._clean_place(activity.get("place"))
        act = str(activity.get("activity") or "").strip()
        if place and act:
            return "%s，%s" % (place, act)
        return place or act

    def _scene_keywords(self, text):
        text = str(text or "")
        words = list(SCENE_KEYWORDS)
        extra = self._cfg_str("draw_scene_keywords", "")
        for item in extra.replace("，", ",").split(","):
            item = item.strip()
            if item and item not in words:
                words.append(item)
        found = []
        for word in words:
            if word in text and word not in found:
                found.append(word)
        return found

    @staticmethod
    def _scene_residual(text, keywords):
        """场景词以外的具体细节（喂鸽子/放风筝…），有就参与缓存键，避免被当成同一张。"""
        body = str(text or "")
        for word in keywords:
            body = body.replace(word, "")
        for word in QUESTION_WORDS + FILLER_WORDS:
            body = body.replace(word, "")
        for word in ("在", "了", "着", "和", "跟", "我", "你", "他", "她", "它", "的",
                     "是", "有", "去", "来", "那边", "这里", "那里", "一起", "看到",
                     "看见", "今天", "现在", "还", "就", "也", "都", "很", "一个",
                     "到", "玩", "逛", "走", "看", "坐", "吃", "喝", "聊", "待", "呆",
                     "转", "跑", "睡", "躺", "站", "拍", "买"):
            body = body.replace(word, "")
        body = re.sub(r"[\s，,。.！!？?~～…]+", "", body)
        return body if len(body) >= 3 else ""

    def _last_bot_line(self, event, reply_text):
        """她上一条说过的话（「拍照给我看看」时拿它当画面描述）。

        先按 uid 跨平台找（QQ 说过的话，飞书那边也认），再退回当前会话。
        """
        current = str(reply_text or "").strip()
        rows = []
        uid = ""
        try:
            uid = str(self.plugin._canonical_uid(event) or "")
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine._last_bot_line", _amo_exc)
        if uid:
            try:
                rows = self.plugin.db.messages_by_uid(uid, 12) or []
            except Exception as _amo_exc:
                _note_swallowed("draw_engine.DrawEngine._last_bot_line", _amo_exc)
                rows = []
        if not rows:
            umo = str(getattr(event, "unified_msg_origin", "") or "")
            if umo:
                try:
                    rows = self.plugin.db.recent_messages(umo, 8) or []
                except Exception as _amo_exc:
                    _note_swallowed("draw_engine.DrawEngine._last_bot_line", _amo_exc)
                    rows = []
        for row in reversed(rows):
            if str(row.get("role") or "") != "bot":
                continue
            content = str(row.get("content") or "").strip()
            if not content or content == current:
                continue
            return content
        return ""

    def _skip(self, reason):
        """跳过原因打到 INFO（同一原因 60 秒只打一次）。

        2026-11-18：这些原因一直是 debug 级，用户看到的是「她说了要拍但没反应」，
        后台查不到任何记录。额度用满（每小时 3 张）这种最容易被误当成
        「生图坏了 / 尺寸不支持」。
        """
        try:
            now = time.time()
            log = getattr(self, "_skip_log", None)
            if log is None:
                log = {}
                self._skip_log = log
            if now - log.get(reason, 0.0) >= 60:
                log[reason] = now
                logger.debug("[amo] 画图跳过：%s" % reason)
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine._skip", _amo_exc)
        return None

    def _is_at_me(self, event):
        """群里是不是真 @ 了她：只认消息里的 At 组件，唤醒词不算。"""
        try:
            self_id = str(event.get_self_id() or "")
            message = getattr(getattr(event, "message_obj", None), "message", None) or []
            for comp in message:
                if type(comp).__name__ == "At" and self_id and str(getattr(comp, "qq", "")) == self_id:
                    return True
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine._is_at_me", _amo_exc)
        return False

    def _group_mode(self):
        """群聊放行策略：off 不画 / at 必须真 @（默认）/ any 都可以。"""
        raw = self._cfg_str("draw_group_mode", "at").strip().lower()
        return raw if raw in ("off", "at", "any") else "at"

    def _allowed_here(self, event):
        """私聊照旧；群聊按 draw_group_mode 判，判定全在本地，不叫模型。

"""
        try:
            if event.is_private_chat():
                return True
        except Exception:
            return False
        mode = self._group_mode()
        if mode == "off":
            return False
        if mode == "any":
            return True
        return self._is_at_me(event)

    def wants_photo(self, event):
        """他这轮是不是明确在要照片（给主脑提示用：别一口拒绝）。"""
        if not self.enabled:
            return False
        try:
            if not self._allowed_here(event):
                return False
            if not self.is_owner(event):
                return False
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine.wants_photo", _amo_exc)
            return False
        if self._mode() == "topic":
            return False
        text = str(getattr(event, "message_str", "") or "")
        return any(kw and kw.lower() in text.lower() for kw in self._explicit_keywords())

    def decide(self, event, reply_text):
        """返回 dict(prompt, mode, reason) 或 None。"""
        if not self.enabled:
            return self._skip("draw_enable=false")
        if not self._allowed_here(event):
            return self._skip("群聊没 @ 或画图没放行")
        if not self.is_owner(event):
            return self._skip("不是主人/相恋关系")
        text = str(getattr(event, "message_str", "") or "").strip()
        try:
            private = bool(event.is_private_chat())
        except Exception:
            private = False
        reply_text = str(reply_text or "").strip()
        if not text:
            return self._skip("空消息")
        # 「拍张照/拍照给我/发张照片/再发一张」都是在要她的照片，默认自拍（别退化成他拍）
        selfie = ("自拍" in text) or self._is_photo_ask(text)
        # 明着要照片就是自拍：只有他这一句里带了明确的别人/环境线索才按他拍。
        # 否则「再发一张」这种续拍请求一定会被下面的 others 词表误伤（家里/山/街都在表里）。
        if selfie and self._is_photo_ask(text):
            scene_text = text + " " + reply_text
            others = ("别人", "朋友", "同事", "同学", "大家", "合影", "路人")
            if not any(word in scene_text for word in others):
                selfie = True
        mode = self._mode()
        lowered = text.lower()
        explicit_hit = mode in ("explicit", "both") and any(
            kw and kw.lower() in lowered for kw in self._explicit_keywords()
        )
        topic_hit = mode in ("topic", "both") and any(
            kw and kw in text for kw in self._topic_keywords()
        )
        if not explicit_hit and not topic_hit:
            return self._skip("没命中触发词")
        if not selfie and topic_hit and not explicit_hit:
            # 话题补图：她一个人待着的时候，镜头只可能是她自己举着的。
            # 只有画面里明确有别人/别的东西时才按他拍（以前这里一律 selfie=False，
            # 于是「手机随手拍」被生图插件当成「他拍」，自拍变成了别人举手机拍）。
            others = ("别人", "朋友", "同事", "同学", "大家", "一起", "合影",
                      "他", "她", "猫", "狗")
            scene = text + " " + reply_text
            selfie = not any(word in scene for word in others)
        if not reply_text:
            return self._skip("没有回复文本")
        if explicit_hit and any(word in reply_text for word in (
            "画好", "画了", "给你画", "这就画", "马上画", "稍等", "等我画", "发给你",
        )):
            # 模型已经自己调了画图工具，别重复画
            return self._skip("模型回复里已经在画")
        if explicit_hit:
            source = "explicit"
            cleaned = clean_explicit_prompt(text)
            max_chars = self._cfg_int("draw_prompt_max_chars", 80)
            if self._is_vague_request(text) or len(cleaned) < 2:
                # 问「你在公园吗/你在干嘛」：她到底在哪由日程决定，图也按日程里的真实地点画
                scene = self._current_scene()
                if scene:
                    subject = scene
                else:
                    previous = self._last_bot_line(event, reply_text)
                    best = self._richer(reply_text, previous)
                    subject = clean_topic_prompt(best, max_chars) if best else cleaned
            else:
                subject = cleaned
                if len(subject) < 4:
                    previous = self._last_bot_line(event, reply_text)
                    if previous:
                        subject = clean_topic_prompt(previous, max_chars)
        else:
            subject = clean_topic_prompt(reply_text, self._cfg_int("draw_prompt_max_chars", 80))
            source = "topic"
        if not subject:
            subject = clean_topic_prompt(reply_text, self._cfg_int("draw_prompt_max_chars", 80))
        if not subject and selfie:
            subject = "自拍"
        if not subject:
            return self._skip("没有可画的画面")
        if explicit_hit and self._is_vague_request(text):
            # 「你在公园吗/拍照给我看看」：拍她自己，用固定形象参考图
            selfie = True
        if selfie:
            # 在开车/在路上，或者她自己说了「等会儿/到了再拍」：这一轮不拍。
            # 记成承诺，条件到了由终端补拍——图和话不能再各走各的。
            later = ""
            getter = getattr(self.plugin, "_promise_photo_later", None)
            if callable(getter):
                try:
                    later = getter(reply_text) or ""
                except Exception as _amo_exc:
                    _note_swallowed("draw_engine.DrawEngine.decide", _amo_exc)
                    later = ""
            word = self._driving_word()
            if word or later:
                notifier = getattr(self.plugin, "_note_photo_promise", None)
                if callable(notifier):
                    try:
                        notifier(event, later)
                    except Exception as _amo_exc:
                        _note_swallowed("draw_engine.DrawEngine.decide", _amo_exc)
                return self._skip("在开车/她说了等会儿，先记成承诺")
        if selfie:
            # 「发张自拍」：按自拍提示词走，穿今天固定的那一套
            # 机位/姿势交给生图插件的自拍池，这里只钉「是我自己拍的」，不钉死构图
            parts = ["自拍（手机前置，画面里只有我自己，不是别人拿手机拍）"]
            outfit = ""
            outfit = schedule_outfit(self.plugin)
            if outfit:
                parts.append("穿着" + outfit)
            # 他发了图说「照这个姿势」：把图里的姿势/机位钉进提示词
            pose_ref = ""
            try:
                getter = getattr(self.plugin, "_photo_pose_reference", None)
                if callable(getter):
                    pose_ref = str(getter(text) or "")
            except Exception as _amo_exc:
                _note_swallowed("draw_engine.pose_reference", _amo_exc)
            if pose_ref:
                parts.append("自拍姿势：" + pose_ref)
            if subject and subject != "自拍":
                parts.append(subject)
            parts.extend(["自然光", "手机前置摄像头", "生活感",
                          "人物长相参考模板，衣服颜色和款式以文字为准，不要照搬模板里的衣服"])
            prompt = "，".join(parts)
        else:
            prefix = self._cfg_str("photo_prompt_prefix", "自然生活照，手机随手拍，")
            prompt = (prefix + subject).strip()
        scene_text = " ".join(filter(None, [subject, reply_text, self._place_text()]))
        keywords = self._scene_keywords(scene_text)
        residual = self._scene_residual(scene_text, keywords)
        cache_key = self._cache_key(prompt, keywords, selfie, residual)
        uid = str(self.plugin._canonical_uid(event) or "")
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        cached = self._cache_get(cache_key)
        if cached:
            # 同一个场景在别的平台再问：直接发同一张，不重新画、也不吃冷却
            return {"prompt": prompt, "mode": source, "reason": "cache",
                    "cached": cached, "cache_key": cache_key}
        if umo and umo in self._inflight:
            return self._skip("上一张还在画")
        reason = self._check_limits(uid, explicit=self._is_photo_ask(text), private=private)
        if reason:
            return self._skip("额度：%s（每小时上限 %d 张 / 每天 %d 张）"
                              % (reason, self._cfg_int("draw_max_per_hour", 3),
                                 self._cfg_int("draw_max_per_day", 10)))
        last = self._last_prompt.get(uid)
        if last and last[0] == prompt and time.monotonic() - last[1] < 120:
            return self._skip("120 秒内同一句")
        return {"prompt": prompt, "mode": source, "reason": "explicit" if explicit_hit else "topic",
                "cache_key": cache_key, "selfie": selfie}

    def maybe_after_reply(self, event, reply_text):
        """on_decorating_result 里调用：判断 + 起一个后台任务，不阻塞。"""
        plan = self.decide(event, reply_text)
        if not plan:
            return None
        self._schedule(event, plan["prompt"], plan["reason"], plan.get("cached"),
                       plan.get("cache_key", ""), plan.get("selfie", False))
        return plan

    def manual(self, event, text):
        """``/amo draw 描述``：跳过触发词，直接画（给测试用）。"""
        if not self.enabled:
            return "画图没开（draw_enable=false）。"
        if not self.is_owner(event):
            return "这个只给主人用哦。"
        text = str(text or "").strip()
        if not text:
            return self.diagnostics()
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        if umo and umo in self._inflight:
            return "上一张还在画，等它出来。"
        prefix = self._cfg_str("photo_prompt_prefix", "自然生活照，手机随手拍，")
        prompt = (prefix + text).strip()
        self._schedule(event, prompt, "manual")
        return "🎨 开始画：%s（画好会单独发一张）" % text

    # ---------- 任务 ----------

    def _spawn(self, coro):
        try:
            spawned = self.plugin._spawn(coro)
            if spawned is not None:
                return spawned
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine._spawn", _amo_exc)
        try:
            return asyncio.create_task(coro)
        except RuntimeError:
            try:
                coro.close()
            except Exception:
                pass
            return None

    def _schedule(self, event, prompt, reason, cached=None, cache_key="", selfie=False):
        uid = str(self.plugin._canonical_uid(event) or "")
        umo = str(getattr(event, "unified_msg_origin", "") or "")
        if umo:
            self._inflight.add(umo)
        self._last_prompt[uid] = (prompt, time.monotonic())
        self._stats["scheduled"] += 1
        logger.debug("[审批] 画图放行（%s%s）：%s"
                    % (reason, "/缓存" if cached else "", prompt[:60]))
        if self._spawn(self._run(event, prompt, uid, umo, cached, cache_key, selfie)) is None:
            if umo:
                self._inflight.discard(umo)

    async def _run(self, event, prompt, uid, umo, cached=None, cache_key="", selfie=False):
        try:
            delay = max(0.0, self._cfg_float("draw_delay_seconds", 1.5))
            if delay:
                await asyncio.sleep(delay)
            if not self.enabled:
                return
            if cached:
                if await self._send_image(event, cached):
                    self._stats["cached"] += 1
                return
            image = await self._generate(event, prompt, selfie)
            if not image:
                self._stats["failed"] += 1
                await self._tell_draw_failed(event, reason)
                return
            try:
                image = await localize_image(self.plugin, image)
            except Exception as _amo_exc:
                _note_swallowed("draw_engine.DrawEngine._run", _amo_exc)
            self._cache_put(cache_key, image)
            if await self._send_image(event, image):
                self._record(uid)
                self._stats["sent"] += 1
                remember = getattr(self.plugin, "_remember_photo", None)
                if callable(remember):
                    try:
                        scene = self.plugin._activity_snapshot(umo)
                        await remember(umo, prompt, scene,
                                       label="自拍" if selfie else "照片")
                    except Exception as _amo_exc:
                        _note_swallowed("draw_engine.DrawEngine._run", _amo_exc)
            else:
                self._stats["failed"] += 1
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._stats["failed"] += 1
            self._last_error = str(exc)
            logger.warning("[amo] 画图失败: %s" % exc)
        finally:
            if umo:
                self._inflight.discard(umo)

    # ---------- OmniDraw ----------

    async def _generate(self, event, prompt, selfie=False):
        """出图：只走生图插件（Astrbot_Amo_Image）。

        判定、额度、冷却都在终端；万象画卷那一套（人设参考图/模板/试画）已经下线，
        机器上本来也没装，留着只是一个永远走不到的分支。
        """
        helper = getattr(self.plugin, "_image_bytes", None)
        data = None
        if callable(helper):
            data = await helper(
                prompt,
                str(getattr(event, "unified_msg_origin", "") or ""),
                str(self.plugin._canonical_uid(event) or ""),
                selfie=selfie,
            )
        if not data:
            self._last_error = "生图插件没出图（Astrbot_Amo_Image）"
            logger.warning("[amo] 生图插件没出图（Astrbot_Amo_Image）")
            return None
        return {"data_url": "data:image/png;base64," + base64.b64encode(data).decode()}

    #: 出图失败时说的话（2026-11-21 她定的口径）：不假装画了，就说现在没时间。
    #: 主动分享走 amo_core/media.py 那条路，失败只记日志，不走这里。
    DRAW_FAIL_LINES = (
        "这会儿没时间拍，下次再给你",
        "暂时没空，晚点再说",
        "现在不太方便，改天拍给你",
    )

    async def _tell_draw_failed(self, event, reason=""):
        """图生图没过 / 出图失败时补一句话；manual 是主人在测，回真实错误。"""
        try:
            if str(reason or "") == "manual":
                text = "画图失败：%s" % (self._last_error or "未知原因")
            else:
                pool = self.DRAW_FAIL_LINES
                text = pool[int(time.time()) % len(pool)]
            try:
                from astrbot.api.message_components import Plain as _Plain
            except Exception:
                from astrbot.core.message.components import Plain as _Plain
            chain_cls = MessageChain
            if chain_cls is None:
                return
            await event.send(chain_cls([_Plain(text=text)]))
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine._tell_draw_failed", _amo_exc)

    # ---------- 发送 ----------

    @staticmethod
    def _image_component(item):
        if Image is None:
            return None
        data_url = str(item.get("data_url") or "")
        if data_url:
            payload = data_url.split(",", 1)[1] if "," in data_url else data_url
            try:
                return Image.fromBase64(payload)
            except Exception as _amo_exc:
                _note_swallowed("draw_engine.DrawEngine._image_component", _amo_exc)
        path = str(item.get("file_path") or "")
        if path:
            try:
                return Image.fromFileSystem(path)
            except Exception as _amo_exc:
                _note_swallowed("draw_engine.DrawEngine._image_component", _amo_exc)
        url = str(item.get("url") or item.get("image_url") or "")
        if url.startswith("http"):
            try:
                return Image.fromURL(url)
            except Exception as _amo_exc:
                _note_swallowed("draw_engine.DrawEngine._image_component", _amo_exc)
        return None

    async def _send_image(self, event, item):
        component = self._image_component(item)
        if component is None:
            logger.warning("[amo] 画图结果没有可发送的图片字段: %s" % list(item.keys()))
            return False
        if MessageChain is None:
            logger.warning("[amo] 画图发送失败：拿不到 MessageChain")
            return False
        try:
            await event.send(MessageChain([component]))
        except Exception as exc:
            self._last_error = str(exc)
            logger.warning("[amo] 画图发送失败: %s" % exc)
            return False
        return True

    # ---------- 状态 ----------

    def diagnostics(self):
        """没收到图时用来自查：开关、冷却、生图插件、上次报错。"""
        plugin = None
        try:
            plugin = self.plugin._image_plugin()
        except Exception as _amo_exc:
            _note_swallowed("draw_engine.DrawEngine.diagnostics", _amo_exc)
        lines = [self.status_text()]
        lines.append("生图插件：" + ("已连接（Astrbot_Amo_Image）" if plugin is not None
                                    else "没找到（插件没装/没启用）"))
        lines.append("上次错误：" + (self._last_error or "无"))
        return "\n".join(lines)

    def status_text(self):
        try:
            has_image = self.plugin._image_plugin() is not None
        except Exception:
            has_image = False
        mode = self._mode()
        mode_text = {"topic": "话题触发", "explicit": "明确要图", "both": "话题+明确"}.get(mode, mode)
        return "\n".join([
            "🎨 画图：%s" % ("开" if self.enabled else "关"),
            "触发：" + mode_text,
            "冷却：%d 分钟｜上限 %d/小时、%d/天" % (
                self._cfg_int("draw_cooldown_minutes", 30),
                self._cfg_int("draw_max_per_hour", 3),
                self._cfg_int("draw_max_per_day", 10),
            ),
            "生图插件：" + ("已连接" if has_image else "没找到（插件没装/没启用）"),
            "本轮统计：排 %d｜发 %d｜复用 %d｜失败 %d｜跳过 %d" % (
                self._stats["scheduled"], self._stats["sent"], self._stats["cached"],
                self._stats["failed"], self._stats["skipped"],
            ),
        ])


# ---------------------------------------------------------------- 照片辅助
# 这两件事原来是 photo_engine.PhotoEngine 的全部内容（2026-11-15 合并进来）：
# ① 此刻穿什么——只读日程那一格，日程没写才按场景现配，不做任何服装兜底；
# ② 远端图片先落盘再发，避免发送时图床偶发连不上。

_MAX_IMAGE_BYTES = 16 * 1024 * 1024


def _photo_cache_dir(plugin):
    """图片落地目录：必须在插件数据目录（不写插件安装目录、不写 cwd）。"""
    base = os.path.dirname(str(getattr(getattr(plugin, "db", None), "path", "") or ""))
    if not base:
        plugin_dir = str(getattr(plugin, "plugin_dir", "") or "")
        name = os.path.basename(plugin_dir) or "Astrbot_Amo_forever"
        parent = os.path.dirname(plugin_dir)
        base = os.path.join(parent, "plugin_data", name) if parent else os.getcwd()
    path = os.path.join(base, "photo_cache")
    try:
        os.makedirs(path, exist_ok=True)
    except Exception as exc:
        _note_swallowed("draw_engine._photo_cache_dir", exc)
    return path


def fetch_image(url):
    """线程里把图片读完再回来；事件循环里 read() 会把整条链路卡住。"""
    with urllib.request.urlopen(url, timeout=60) as response:
        content_type = str(response.headers.get("Content-Type") or "").lower()
        payload = response.read(_MAX_IMAGE_BYTES + 1)
    if len(payload) > _MAX_IMAGE_BYTES:
        raise ValueError("图片超过 %d MB，丢弃" % (_MAX_IMAGE_BYTES // (1024 * 1024)))
    return payload, content_type


async def localize_image(plugin, item):
    """远端图片先落到本地缓存，返回带 file_path 的副本。"""
    if not isinstance(item, dict):
        return item
    if item.get("data_url"):
        return item
    path = str(item.get("file_path") or "")
    if path and os.path.exists(path):
        return item
    url = str(item.get("url") or item.get("image_url") or "")
    if not url.startswith("http"):
        return item
    cache_dir = _photo_cache_dir(plugin)
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    for _ in range(3):
        try:
            payload, content_type = await asyncio.to_thread(fetch_image, url)
            if "png" in content_type or payload[:8] == b"\x89PNG\r\n\x1a\n":
                ext = ".png"
            elif "webp" in content_type or payload[:4] == b"RIFF":
                ext = ".webp"
            else:
                ext = ".jpg"
            target = os.path.join(cache_dir, digest + ext)
            with open(target, "wb") as handle:
                handle.write(payload)
            copied = dict(item)
            copied["file_path"] = target
            return copied
        except Exception as exc:
            _note_swallowed("draw_engine.localize_image", exc)
            await asyncio.sleep(2)
    return item


def schedule_outfit(plugin):
    """日程里此刻那一格穿什么；那格没写 outfit 就按场景现配一套。

    拍照、自拍、主动分享都必须跟日程穿同一套，否则就是「日程写着汉服、
    照片穿牛仔裤」。日程读不到（没生成过 / 出行兜底那几格）才返回空。
    """
    try:
        activity = plugin.state.current_activity() or {}
    except Exception as exc:
        _note_swallowed("draw_engine.schedule_outfit", exc)
        return ""
    if not isinstance(activity, dict) or not activity:
        return ""
    outfit = str(activity.get("outfit") or "").strip()
    if outfit:
        # 私密套只在家出图：日程写着私密、人却在外面上班/逛街时，换成今天那套正常衣服
        try:
            from .outfit_engine import is_private_wear, private_ok
        except Exception:
            try:
                from outfit_engine import is_private_wear, private_ok  # type: ignore
            except Exception:
                is_private_wear = private_ok = None
        if is_private_wear is not None and is_private_wear(outfit) and not private_ok(activity):
            try:
                engine = getattr(plugin, "outfits", None)
                day = _today_str()
                items = (getattr(plugin.state, "schedule", {}) or {}).get(day) or []
                normal = engine._compose(engine.day_scene(items), day, engine.gender())
                if normal:
                    return str(normal)
            except Exception as exc:
                _note_swallowed("draw_engine.schedule_outfit", exc)
            return ""
        return outfit
    engine = getattr(plugin, "outfits", None)
    getter = getattr(engine, "for_activity", None) if engine is not None else None
    if not callable(getter):
        return ""
    try:
        return str(getter(activity, _today_str()) or "").strip()
    except Exception as exc:
        _note_swallowed("draw_engine.schedule_outfit", exc)
        return ""
