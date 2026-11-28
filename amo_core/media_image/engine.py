# -*- coding: utf-8 -*-
"""我想永远陪着你-相片（Astrbot_Amo_Image）：生图联动。

给「我想永远陪着你-终端」（Astrbot_Amo_forever）和「我想永远陪着你-记忆」（Astr_Amo_data）
配套的第三块：**只负责画图**。

- 人设外观从 `character_appearance` 读，拼在提示词最前面，保证每次是同一个人；
- 上下文从数据插件的记忆接口读（`recall_messages` / `messages_since`），让画面对得上剧情；
- 后端走 OpenAI 兼容的 `POST {api_base}/images/generations`，同时支持 `url` 与 `b64_json`；
- 找不到数据插件、后端报错、超时、返回空——一律降级成人设化的一句话，不抛异常。

它不参与聊天判定、不改 AstrBot 核心链路，也不依赖另外两个插件必须在场。
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import tempfile
import time
import unicodedata
import zlib
from datetime import datetime, timedelta, timezone
from collections import deque

from astrbot.api import logger

try:
    from . import config_watch as _config_watch
except ImportError:
    import config_watch as _config_watch  # type: ignore

try:
    from .chain import Chain
except ImportError:
    from chain import Chain  # type: ignore
try:
    from . import self_face
except ImportError:  # pragma: no cover
    import self_face  # type: ignore
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context

try:  # AstrBot 4.x
    from astrbot.api.message_components import Image, Plain, Reply
except Exception:  # pragma: no cover - 老版本路径
    from astrbot.core.message.components import Image, Plain, Reply  # type: ignore

try:  # 面板后端：AstrBot 4.x 的插件 Web API
    from astrbot.api.web import error_response, json_response, request as web_request
except Exception:  # pragma: no cover - 老版本没有该模块
    error_response = json_response = web_request = None

try:
    import aiohttp
except Exception:  # pragma: no cover - 没装 aiohttp 时退回线程 + urllib
    aiohttp = None  # type: ignore

try:
    from .providers import (
        APIError,
        ImageOptions,
        build_provider,
        parse_image_response,
        ratio_from_size,
    )
except Exception:  # pragma: no cover - 直接以脚本方式加载时
    from providers import (  # type: ignore
        APIError,
        ImageOptions,
        build_provider,
        parse_image_response,
        ratio_from_size,
    )

try:
    from .consistency import (
        CONSISTENCY_NEGATIVE,
        FACE_LOCK,
        POSE_NEGATIVE,
        SELFIE_DIRECTIVE,
        NO_PROP_CLAUSE,
    no_prop_clause,
        REF_ONLY_CLAUSE,
        pose_clause,
        selfie_directive,
        match_scene,
        pattern_clause,
        form_clause,
        scene_anchor,
        split_prompts,
        place_words_scene,
    )
except Exception:  # pragma: no cover - 直接以脚本方式加载时
    from consistency import (  # type: ignore
        CONSISTENCY_NEGATIVE,
        FACE_LOCK,
        POSE_NEGATIVE,
        SELFIE_DIRECTIVE,
        NO_PROP_CLAUSE,
    no_prop_clause,
        REF_ONLY_CLAUSE,
        pose_clause,
        selfie_directive,
        match_scene,
        pattern_clause,
        form_clause,
        scene_anchor,
        split_prompts,
        place_words_scene,
    )

try:
    from .link import probe as _link_probe
except Exception:  # pragma: no cover
    from link import probe as _link_probe  # type: ignore

class EmptyBackendResponse(RuntimeError):
    """后端返回 200 但响应体为空 / 不是 JSON（网关限流、CDN 空包都长这样）。EmptyBackendResponse 的诊断 见 _json_or_empty。"""


PLUGIN_NAME = "DeepSeek_Harness_Amo_Terminal"
PLUGIN_VERSION = "1.0.0"
try:  # 版本号以 metadata.yaml 为准，避免两处不一致
    import yaml as _amo_meta_yaml
    with open(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "metadata.yaml"),
              encoding="utf-8") as _amo_meta_fh:
        _amo_meta = _amo_meta_yaml.safe_load(_amo_meta_fh) or {}
    if _amo_meta.get("version"):
        PLUGIN_VERSION = str(_amo_meta["version"])
except Exception:
    pass

# 服装池留空时的保底：宁可穿得普通，也不能每次随机换一身
DEFAULT_OUTFITS = [
    "米色针织开衫配浅蓝牛仔裤",
    "白色棉质衬衫配深色半身裙",
    "浅灰连帽卫衣配宽松长裤",
    "碎花连衣裙外搭薄开衫",
    "藏青色针织衫配卡其长裤",
    "奶油色毛衣配直筒长裤",
]

# 负面提示词：支持 negative_prompt 的后端（Kolors / SiliconFlow 等）会用它，
# 不支持的（OpenAI images）会自动去掉这个字段重试，不会因此报错。
DEFAULT_NEGATIVE_PROMPT = (
    "different face, different hairstyle, different clothes, different person, "
    "change location, other scenic spot, blurry, low quality, extra fingers"
)

# 「换一套衣服」这类手动换装：整句就是指令，不能当成生图提示词
OUTFIT_COMMANDS = ("换一套衣服", "换套衣服", "换身衣服", "换衣服", "换一件衣服")

# 拍摄角度：拍自己=自拍（前置、第一人称）；拍别人/别的东西=他拍（第三人称，别人拿手机）
SELFIE_CAMERA = ("手机前置摄像头，第一人称自拍视角，镜头在她手里、靠近脸，"
                 "近景半身，直视镜头，不是别人拿手机拍")
OTHER_CAMERA = "他拍，第三人称视角，对面的人拿手机拍，画面里不要出现拿手机的人"
SELFIE_WORDS = ("自拍", "拍你", "拍我", "看看你", "你的照片", "自拍照", "前置",
                "镜头对着自己", "来张自拍", "发张自拍")
OTHER_WORDS = ("他", "她", "朋友", "猫", "狗", "宠物", "一起", "合影", "全身", "背影",
               "桌上", "风景", "街", "店", "咖啡", "蛋糕", "花", "书", "电脑", "相机",
               "天空", "海", "山", "路", "窗外", "雨", "食物", "菜", "画")

# 兜底话术：不要说「画不了 / 生成失败」这类机器话，像人一样推一下时间。
# 随机取一条，免得每次都同一句，露馅。
FALLBACK_LINES = (
    "等我一下，这会儿手头有点事，晚点拍给你",
    "现在不太方便，等下有光了再给你拍",
    "先欠你一张，晚点补上",
    "这里拍出来不好看，回去再拍",
)
BLOCKED_LINES = (
    "这个不行啦",
    "这个我不拍",
    "换个别的嘛",
)

# 没配外观时的保底描述：宁可普通，也不能每次换一张脸
DEFAULT_APPEARANCE = "长发，五官清秀，自然妆容，日常穿搭"

# 内容边界：私聊只拦露骨裸体 / 性器官 / 性行为 / 未成年相关；
# 群聊额外拦「只穿内衣 / 比基尼 / 情趣内衣」这类。这是一层关键词防线，
# 挡不住谐音、外语、拆字和极端变体，别当唯一保险。
EXPLICIT_TERMS = (
    "裸体", "裸體", "全裸", "赤裸", "一丝不挂", "未着寸缕",
    "露阴", "阴部", "私处", "生殖器", "下体裸露",
    "性交", "做爱", "口交", "肛交", "性行为", "自慰", "射精",
    # 2026-11-21：姿势参考图里「双腿分开 / 劈腿」是普通动作描述，别当露骨拦
    "张开腿", "张开双腿", "m字腿",
    "porn", "nude", "naked", "genital", "explicitsex", "spreadlegs",
)
MINOR_TERMS = (
    "幼女", "未成年", "儿童色情", "未成年性", "childporn", "loli", "萝莉",
)
INJECTION_TERMS = (
    "忽略之前", "忽略以上", "ignoreprevious", "ignoreabove",
    "systemprompt", "系统提示", "越狱", "jailbreak", "不要遵守",
)

# 群聊额外档：内衣 / 比基尼 / 走光。文本已归一化（小写、去空白），
# 所以英文词也要写成连写形式。
_GROUP_BLOCK_PATTERNS = (
    re.compile(r"(只|仅|单)穿.{0,6}(内衣|泳衣|泳装|比基尼)"),
    re.compile(r"(穿|着).{0,4}内衣"),
    re.compile(r"内衣.{0,4}(照|写真|自拍)"),
    re.compile(r"情趣内衣|蕾丝内衣|比基尼|bikini|lingerie"),
    re.compile(r"露乳|露臀|走光|underwearonly|swimsuitonly"),
)

# 面板里的后端预设：只填 base/model，密钥由用户自己填
PROVIDER_PRESETS = (
    {"id": "openai", "name": "OpenAI 官方", "provider": "openai",
     "api_base": "https://api.openai.com/v1", "model": "gpt-image-1"},
    {"id": "siliconflow", "name": "硅基流动", "provider": "openai",
     "api_base": "https://api.siliconflow.cn/v1", "model": "Kwai-Kolors/Kolors"},
    {"id": "zhipu", "name": "智谱 BigModel", "provider": "openai",
     "api_base": "https://open.bigmodel.cn/api/paas/v4", "model": "cogview-3-flash"},
    {"id": "dashscope", "name": "阿里百炼", "provider": "openai",
     "api_base": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "wanx2.1-t2i-turbo"},
    {"id": "gemini", "name": "Gemini 官方", "provider": "gemini",
     "api_base": "https://generativelanguage.googleapis.com/v1beta",
     "model": "gemini-2.5-flash-image"},
    {"id": "chat", "name": "Chat 通道（gpt-image / 代理）", "provider": "openai_chat",
     "api_base": "https://api.openai.com/v1", "model": "gpt-4o-image"},
    {"id": "custom", "name": "自定义端点", "provider": "custom",
     "api_base": "", "model": ""},
)

# 面板能改的配置项（其余走 AstrBot 自己的配置页）
WEB_EDITABLE = (
    "provider", "api_base", "api_key", "model", "size", "n", "quality", "style",
    "timeout", "request_style", "negative_prompt", "aspect_ratio", "chat_modalities",
    "custom_url", "custom_body", "custom_response_path",
    "enable", "allow_private", "allow_group", "require_at_in_group", "quote_in_group",
    "cooldown_seconds", "private_daily_limit", "group_daily_limit", "safe_mode",
    "blocked_reply", "reply_prefix", "error_reply",
    "character_appearance", "character_hairstyle", "character_outfits",
    "character_gender", "character_persona", "camera_mode",
    "outfit_change_keywords", "outfit_change_cooldown_minutes",
    "lock_scene_to_schedule", "keywords", "photo_keywords", "photo_default_prompt",
    "use_memory_context", "memory_context_limit",
)
WEB_BOOL_KEYS = frozenset({
    "enable", "allow_private", "allow_group", "require_at_in_group", "quote_in_group",
    "safe_mode", "lock_scene_to_schedule", "use_memory_context", "chat_modalities",
})
WEB_INT_KEYS = frozenset({
    "n", "timeout", "cooldown_seconds", "private_daily_limit", "group_daily_limit",
    "memory_context_limit", "outfit_change_cooldown_minutes", "batch_max",
})
WEB_LIST_KEYS = frozenset({"character_outfits", "outfit_change_keywords", "keywords", "photo_keywords"})

DATA_PLUGIN_NAMES = (
    "DeepSeek_Harness_Amo_Memory",
    "deepseek_harness_amo_memory",
    "Astr_Amo_data",
    "astrbot_plugin_amo_data",
    "amo_data",
)

DEFAULT_KEYWORDS = ["画一张", "画个", "帮我画", "生成图片", "来张图", "画张"]
DEFAULT_PHOTO_KEYWORDS = ["拍张照", "拍一张", "拍个照", "拍张照片", "拍一张照片",
                          "自拍", "来张自拍", "发张照片"]
# 「给我拍张照」去掉触发词后只剩「给我」，这些词不该当提示词
_FILLER_WORDS = ("给我", "帮我", "帮忙", "请你", "请", "你", "我", "一张", "张",
                 "照片", "图片", "一下", "吧", "呗", "看看")

# 触发词后面常跟的标点/空白，去掉再当提示词
_TRIM_CHARS = " \t\r\n，,。.：:；;、!！?？\"'“”‘’"

_UNSAFE_PROMPT = re.compile(r"[\x00-\x1f]")


def clean_prompt(text: str, keyword: str) -> str:
    """把「画一张 一只在雨里的猫」里的触发词和标点去掉，只留提示词。"""
    body = str(text or "")
    if keyword:
        idx = body.find(keyword)
        if idx >= 0:
            body = body[idx + len(keyword):]
    body = _UNSAFE_PROMPT.sub(" ", body)
    return body.strip(_TRIM_CHARS)


def strip_filler(text: str) -> str:
    """把「给我 / 帮我 / 一下」这类没信息量的词去掉，剩下的才当提示词。"""
    body = str(text or "").strip()
    changed = True
    while changed and len(body) <= 6:
        changed = False
        for word in _FILLER_WORDS:
            if body.startswith(word) and len(body) > len(word):
                body = body[len(word):].strip(_TRIM_CHARS)
                changed = True
            elif body.endswith(word) and len(body) > len(word):
                body = body[: -len(word)].strip(_TRIM_CHARS)
                changed = True
    return body


def match_keyword(text: str, keywords) -> str:
    """返回命中的触发词（没命中返回空串）。长的优先，避免「画个」抢了「画个图」。"""
    body = str(text or "")
    for word in sorted([str(k) for k in (keywords or []) if str(k)], key=len, reverse=True):
        if word and word in body:
            return word
    return ""


def _look_mentioned(body: str, look: str) -> bool:
    """正文里是不是已经提到这套衣服（哪怕只提了其中一件）。

    ``look`` 是「套名｜件名」用逗号拼起来的完整一套；正文只要出现任意一件，
    就说明这一套已经写进提示词了，不能再追加一条，否则同一张图会出现两套描述。
    """
    text = str(body or "")
    target = str(look or "")
    if not text or not target:
        return False
    if target in text:
        return True
    for piece in re.split(r"[，,、]", target):
        name = str(piece).strip()
        if not name:
            continue
        # 「汉服·雪霁｜对襟褙子」→ 取竖线后半段的件名
        if "｜" in name:
            name = name.split("｜", 1)[1].strip()
        if len(name) >= 2 and name in text:
            return True
    # 套名单独出现（「穿着汉服」）也算提到
    head = target.split("｜", 1)[0].strip()
    return bool(head) and len(head) >= 2 and head in text


#: 正文里出现这些词，说明形制已经写在正文里了，不再追加。
_FORM_WORDS = ("宋制", "明制", "唐制", "汉制", "曲裾", "直裾", "立领", "马面裙",
               "齐胸", "交领", "对襟", "圆领袍", "百迭裙", "坦领")


def _form_mentioned(body: str) -> bool:
    """正文是不是已经交代过形制。"""
    text = str(body or "")
    return any(word in text for word in _FORM_WORDS)


def _pattern_mentioned(body: str, pattern_text: str) -> bool:
    """正文里是不是已经把这套衣服的纹样写清楚了。

    只认纹样句里那几个关键特征（格子/绣花/暗纹/纯色…）：正文只要命中其中两个，
    就说明她（或陪伴侧的模板）已经交代过布料，这里不再追加，免得一句话两套花纹。
    """
    text = str(body or "")
    clause = str(pattern_text or "")
    if not text or not clause:
        return False
    body_text = clause.split("：", 1)[-1]
    keys = [w for w in ("格裙", "格子", "绣花", "暗纹", "织金", "纯色", "印纹",
                        "无纹", "条纹", "素缎") if w in body_text]
    if not keys:
        return False
    hit = sum(1 for w in keys if w in text)
    return hit >= 2


def body_clause(appearance: str) -> str:
    """身高/体态锚：只写「155cm」模型会按默认 8 头身模特画，必须把比例写死。

    2026-11-21 她报：人格里 155cm、娇小纤细，出图看着像 170。
    """
    text = str(appearance or "")
    if not text:
        return ""
    match = re.search(r"(\d{2,3})\s*(?:cm|厘米|CM|Cm)", text)
    height = match.group(1) if match else ""
    small = any(word in text for word in ("娇小", "纤细", "小巧", "矮", "萝莉", " petite", "petite"))
    if not height and not small:
        return ""
    pieces = []
    if height:
        pieces.append("真实身高 %s cm" % height)
    if small:
        pieces.append("娇小纤细的矮个女孩体型")
    pieces.append("头身比约 6 头身，腿身比例按真实身高，不要画成 8 头身的长腿模特；"
                  "肩膀窄、骨架小、四肢纤细")
    return "；".join(pieces)


def build_prompt(appearance: str, prompt: str, context_lines=None, look: str = "",
                 place: str = "", activity: str = "", gender: str = "",
                 persona: str = "", camera: str = "", scene: str = "",
                 pose: str = "", face: str = "", selfie: bool = False,
                 no_prop: bool = False,
                 look_label: str = "今天的样子：",
                 selfie_text: str = "",
                 hairstyle: str = "",
                 lighting: str = "") -> str:
    """拼最终提示词：性别 → 角色 → 外观 → 今日固定造型 → 地点/在干嘛 → 要求 → 上下文。

    性别和角色放在最前面，是因为模型默认会「猜」人物：不写性别就容易画出男的，
    不写角色名就接不上人格。地点和 activity 都来自日程里此刻那一格，不随机换。
    """
    parts = []
    body = str(prompt or "")
    if selfie:
        parts.append(selfie_text or SELFIE_DIRECTIVE)
    if str(gender or "").strip():
        parts.append(str(gender).strip())
    if str(persona or "").strip() and str(persona).strip() not in body:
        parts.append("角色：" + str(persona).strip())
    if str(appearance or "").strip():
        parts.append(str(appearance).strip())
    body_text = body_clause(str(appearance or ""))
    if body_text:
        parts.append(body_text)
    # 陪伴那边的分享模板本身就带了 {place}，这里别再叠一遍「此刻在××」
    #
    # 2026-11-16 的病象：同一张照片里有两套衣服描述——正文里只写了一件
    # （「穿着汉服·雪霁｜对襟褙子」，没有裙/袜/鞋），这里又追加一条完整的四件套。
    # 原来只比「整串 look 是否原样出现在正文里」，正文写了半套就判成没有，
    # 于是两句话打架，出图看哪句都说得通（前一张交领、后一张抹胸就是这么来的）。
    # 现在只要正文里出现了这套的任一件，就以正文为准，不再追加；
    # 没出现才补一条完整的，保证一套衣服只有一个出处。
    look_text = str(look or "").strip()
    if look_text and not _look_mentioned(body, look_text):
        parts.append(str(look_label or "今天的样子：") + look_text)
    # 布料纹样单独一条：衣柜只写「樱粉格裙」「织金马面裙」，格子和绣花全靠模型自己发挥，
    # 于是同一套衣服每张照片的花纹都不一样。按套名取一句固定的纹样，写死在这里。
    # 正文里已经写了这套的纹样就不再叠（避免同一张图两套花纹描述打架）。
    pattern_text = pattern_clause(look_text)
    if pattern_text and not _pattern_mentioned(body, pattern_text):
        parts.append(pattern_text)
    # 形制（宋制/明制/唐制…）单独一条：只固定纹样不够，褙子照样会被画成立领
    form_text = form_clause(look_text)
    if form_text and not _form_mentioned(body):
        parts.append(form_text)
    # 发型单独一条：日程里的 outfit 只有衣服，没有发型，不补就会一张一个发型
    if str(hairstyle or "").strip() and str(hairstyle).strip() not in body:
        parts.append("发型：" + str(hairstyle).strip())
    if str(camera or "").strip():
        parts.append(str(camera).strip())
    where = str(place or "").strip()
    doing = str(activity or "").strip()
    if where and where not in body:
        if doing and doing not in body:
            doing_text = doing[:40]
            if doing_text.startswith("在"):
                doing_text = doing_text[1:]
            parts.append("此刻在%s，正在%s" % (where, doing_text))
        else:
            parts.append("此刻在" + where)
    elif doing and doing not in body:
        parts.append("正在" + doing[:40])
    if str(lighting or "").strip():
        # 时间/光线单独一条：以前完全没算时刻，晚上也照着大白天画
        parts.append(str(lighting).strip())
    if body.strip():
        parts.append(body.strip())
    if context_lines:
        tail = "；".join([str(x).strip() for x in context_lines if str(x).strip()][-6:])
        if tail:
            parts.append("画面只接这段对话的气氛和情绪，不要把对话里提到的物品画进画面：%s" % tail)
    # 脸 / 环境 / 姿势：这三条决定「一眼看出是不是同一个场景里的同一个人」
    if str(face or "").strip():
        parts.append(str(face).strip())
    if str(scene or "").strip() and str(scene).strip() not in body:
        parts.append(str(scene).strip())
    if str(pose or "").strip():
        parts.append(str(pose).strip())
    if no_prop:
        try:
            parts.append(no_prop_clause(bool(selfie)))
        except Exception:
            parts.append(NO_PROP_CLAUSE)
    if str(appearance or "").strip() or str(look or "").strip():
        parts.append("同一个人，脸、发型、服装与母图保持一致")
    parts.append("手机随手拍的原片质感，画面干净利落，只有人和景物本身")
    return "，".join(parts)


class AmoImageEngine:
    """生图插件：认人设、接上下文、只画图。"""

    # 语音运行时与事件钩子已迁入 Terminal；本插件只保留社会关系数据与关系面板。

    def __init__(self, context: Context, config: dict = None):
        self.context = context
        self.config = config if config is not None else {}

        # 配置自愈：升级/重装/改目录名之后，把空掉的 key 从快照补回来。
        # 快照在 plugin_data/<插件名>/config_snapshot.json（0600），升级不覆盖、
        # schema 重写也删不到它。
        try:
            from .config_guard import heal as _cfg_heal, fallback_data_dir as _cfg_data_dir
        except ImportError:
            try:
                from config_guard import heal as _cfg_heal, fallback_data_dir as _cfg_data_dir
            except Exception:
                _cfg_heal = None
        if _cfg_heal is not None:
            try:
                _guard_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                _healed = _cfg_heal(self.config, plugin_name=PLUGIN_NAME,
                                    plugin_dir=_guard_dir,
                                    data_dir=_cfg_data_dir(_guard_dir, PLUGIN_NAME),
                                    logger=logger)
                if _healed.get("restored"):
                    logger.info("[config] 本次启动补回 %d 项配置（%s）"
                                % (len(_healed["restored"]), ", ".join(_healed["restored"])))
            except Exception as exc:
                logger.debug("[config] 配置自愈失败: %s" % exc)
        self._last_call = {}   # uid -> 上次生图时间
        self._daily = {}       # uid -> [日期字符串, 次数]
        self._daily_group = {} # umo -> [日期字符串, 次数]
        self._history = deque(maxlen=40)   # 最近几次生图（面板用）
        self._style_cache = {}             # endpoint -> 试通过的参数风格
        self._negative_ok = {}             # endpoint -> 后端认不认 negative_prompt
        self._look_state = None            # 手动换装记录（按天，落盘）
        self._calls_total = 0
        self._started_at = time.time()
        self.plugin_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        self._cfg_sync_at = 0.0          # 配置热同步的节流时间戳
        self._register_web_apis()

    # ---------- 配置 ----------

    def _cfg(self, name, default=None):
        self._sync_config_throttled()
        value = self.config.get(name, default)
        return default if value is None else value

    def _bool(self, name, default=False):
        value = self._cfg(name, default)
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on", "是")

    def _int(self, name, default=0):
        try:
            return int(float(self._cfg(name, default)))
        except Exception:
            return default

    def _float(self, name, default=0.0):
        try:
            return float(self._cfg(name, default))
        except Exception:
            return default

    def _keywords(self):
        value = self._cfg("keywords", DEFAULT_KEYWORDS)
        if isinstance(value, str):
            value = [x.strip() for x in value.split(",")]
        return [str(x) for x in (value or DEFAULT_KEYWORDS) if str(x).strip()]

    def _photo_keywords(self):
        value = self._cfg("photo_keywords", DEFAULT_PHOTO_KEYWORDS)
        if isinstance(value, str):
            value = [x.strip() for x in value.split(",")]
        return [str(x) for x in (value or []) if str(x).strip()]

    # ---------- 数据插件联动 ----------

    @staticmethod
    def _star_instance(meta, require_mem=True):
        """AstrBot 各版本把实例放在不同属性上，挨个试。

        require_mem=True 用于找数据插件（必须带 mem）；False 用于找陪伴主插件。
        """
        if meta is None:
            return None
        for attr in ("star_cls", "instance", "star", "plugin"):
            value = getattr(meta, attr, None)
            if value is None:
                continue
            if not require_mem or hasattr(value, "mem"):
                return value
        return None

    def _data_plugin(self):
        """找「我想永远陪着你-记忆」的实例；没装就 None。"""
        try:
            for name in DATA_PLUGIN_NAMES:
                star = self._star_instance(self.context.get_registered_star(name))
                if star is not None:
                    return star
        except Exception:
            pass
        try:
            for meta in self.context.get_all_stars():
                marker = (getattr(meta, "name", "") or "") + " " + (getattr(meta, "module_path", "") or "")
                star = self._star_instance(meta)
                if star is not None and ("amo_memory" in marker.lower() or "amo_data" in marker.lower()):
                    return star
        except Exception:
            pass
        # 融合态：记忆是终端自带的数据层，没有独立插件时用终端的
        companion = self._companion()
        if companion is not None and getattr(companion, "mem", None) is not None:
            return companion
        return None

    COMPANION_NAMES = ("DeepSeek_Harness_Amo_Terminal", "deepseek_harness_amo_terminal",
                       "Astrbot_Amo_forever", "astrbot_plugin_amo_forever", "amo_forever")

    def _companion(self):
        """找陪伴主插件实例；找不到返回 None。"""
        try:
            for name in self.COMPANION_NAMES:
                star = self._star_instance(self.context.get_registered_star(name), require_mem=False)
                if star is not None:
                    return star
        except Exception:
            pass
        try:
            for meta in self.context.get_all_stars():
                marker = (getattr(meta, "name", "") or "") + " " + (getattr(meta, "module_path", "") or "")
                if "amo_terminal" not in marker.lower() and "amo_forever" not in marker.lower():
                    continue
                star = self._star_instance(meta, require_mem=False)
                if star is not None:
                    return star
        except Exception:
            pass
        return None

    def mount_mode(self) -> bool:
        """中央集权：陪伴主插件（Amo）在的时候，我只当执行者。

        判定权全在 Amo：它决定这轮要不要图、换不换装、发不发；我只负责出图
        （``draw_for``）和给造型（``change_outfit_for``）。没装 Amo（或 Amo 被禁用）
        时才回到独立模式，免得整条链路哑掉。
        """
        if not self._bool("mount_only", True):
            return False
        return self._companion() is not None

    def change_outfit_for(self, reason: str = "") -> str:
        """执行者入口：换下一套造型并返回造型描述；发不发、怎么说由 Amo 决定。"""
        if not self._bool("enable", True):
            return ""
        try:
            look = str(self._change_outfit() or "")
        except Exception as exc:
            logger.debug("[amo_image] 换装失败: %s" % exc)
            return ""
        if look:
            logger.info("[amo_image] 执行换装（%s）：%s" % (reason or "mount", look))
        return look

    def _bot_id(self) -> str:
        """和陪伴插件用同一个 bot_id，否则数据插件里的聊天记录读不到。"""
        companion = self._companion()
        if companion is not None:
            getter = getattr(companion, "_data_bot_id", None)
            if callable(getter):
                try:
                    value = str(getter() or "").strip()
                    if value:
                        return value
                except Exception:
                    pass
            conf = getattr(companion, "config", None) or {}
            value = str(conf.get("data_bot_id") or conf.get("bot_name") or "").strip()
            if value:
                return value
        plugin = self._data_plugin()
        conf = getattr(plugin, "config", None) or {}
        return str(conf.get("bot_id") or "").strip()

    def _mem(self):
        plugin = self._data_plugin()
        return getattr(plugin, "mem", None) if plugin is not None else None

    async def _context_lines(self, umo: str, uid: str):
        """取最近几条对话当画面参考；任何异常都静默返回空列表。"""
        if not self._bool("use_memory_context", True):
            return []
        mem = self._mem()
        if mem is None:
            return []
        limit = max(1, self._int("memory_context_limit", 6))
        lines = []
        try:
            bot_id = self._bot_id()
            if callable(getattr(mem, "messages_since", None)):
                rows = await mem.messages_since(bot_id, uid=uid, since_ts=0, limit=limit)
            elif callable(getattr(mem, "recall_messages", None)):
                got = await mem.recall_messages(bot_id, query="", umo=umo, uid=uid, limit=limit)
                rows = got.get("messages") if isinstance(got, dict) else got
            else:
                rows = []
            for row in rows or []:
                if isinstance(row, dict):
                    text = row.get("content") or row.get("text") or ""
                else:
                    text = str(row)
                text = str(text).strip()
                if text:
                    lines.append(text[:120])
        except Exception as exc:
            logger.debug("[amo_image] 取上下文失败，跳过: %s" % exc)
            return []
        return lines[-limit:]

    # ---------- 闸门 ----------

    def _is_group(self, event) -> bool:
        try:
            return not bool(event.is_private_chat())
        except Exception:
            return False

    @staticmethod
    def _group_from_umo(umo) -> bool:
        """分享入口没有 event，只能从 UMO 判断是不是群聊。"""
        return "groupmessage" in str(umo or "").lower()

    @staticmethod
    def _normalize_text(text: str) -> str:
        """归一化：全角转半角、转小写、去掉空白和零宽字符，防「裸 体」这类拆字。"""
        value = unicodedata.normalize("NFKC", str(text or "")).lower()
        return re.sub(r"[\s\u200b\u200c\u200d\ufeff]+", "", value)

    def _safe_text(self, text: str, group: bool = False) -> bool:
        """输入边界：返回 True 表示可以画。

        2026-11-21 她明确要求：**私聊不做任何阻拦**（尤其恋人私聊），
        生图模型那边自有内容策略，我们不再自己先拦一遍。
        群聊是公开场合，仍然只拦「只穿内衣 / 比基尼 / 情趣内衣」和露骨词。
        """
        if not group:
            return True
        if not self._bool("safe_mode", True):
            return True
        raw = self._normalize_text(text)
        if not raw:
            return True
        if len(raw) > 600:
            return False
        # 2026-11-23（用户口径）：寝衣/私密衣服绝不画到群里
        for term in ("寝衣", "睡衣", "睡裙", "睡袍", "抹胸", "薄纱", "内衣", "泳衣", "泳装", "私密"):
            if term in raw:
                logger.info("[amo_image] 群聊不画私密衣服：命中「%s」" % term)
                return False
        for term in EXPLICIT_TERMS + MINOR_TERMS + INJECTION_TERMS:
            if self._normalize_text(term) in raw:
                # 只记命中的词，不记整段提示词（里面有她的穿搭和聊天内容）
                logger.warning("[relationship] 内容边界拦下：命中「%s」" % term)
                return False
        if group and any(pattern.search(raw) for pattern in _GROUP_BLOCK_PATTERNS):
            return False
        return True

    def _clean_context(self, lines, group: bool = False):
        """记忆上下文也要过边界：群友在聊天里塞「画裸体」不能顺着拼进提示词。"""
        return [x for x in (lines or []) if self._safe_text(x, group)]

    def _is_at_me(self, event, strict: bool = False) -> bool:
        """是否真的 @ 了机器人。

        strict=True 只认消息里的 At 组件，不认唤醒前缀——群里用唤醒词不算 @。
        """
        if not strict:
            try:
                if bool(getattr(event, "is_at_or_wake_command", False)):
                    return True
            except Exception:
                pass
        try:
            self_id = str(event.get_self_id() or "")
            message = getattr(getattr(event, "message_obj", None), "message", None) or []
            for comp in message:
                if type(comp).__name__ == "At" and str(getattr(comp, "qq", "")) == self_id and self_id:
                    return True
        except Exception:
            pass
        return False

    def quota(self, uid: str = "", umo: str = "", group: bool = False) -> dict:
        """今天还能画几张。**每日张数只在这里记**，终端不再自己保存一份。

        返回 {"allowed", "used", "limit", "remaining"}；limit=0 表示不限量。
        """
        today = time.strftime("%Y-%m-%d")
        if group:
            limit = max(0, self._int("group_daily_limit", 20))
            record = self._daily_group.get(str(umo or "")) or [today, 0]
        else:
            limit = max(0, self._int("private_daily_limit", 0))
            record = self._daily.get(str(uid or "")) or [today, 0]
        used = int(record[1]) if record and record[0] == today else 0
        return {
            "allowed": True if not limit else used < limit,
            "used": used,
            "limit": limit,
            "remaining": (limit - used) if limit else -1,
        }

    def _quota_ok(self, uid: str, umo: str = "", group: bool = False) -> tuple:
        """冷却 + 每日次数。私聊默认不限量，群聊按群每天 20 张。"""
        now = time.time()
        cooldown = max(0, self._int("cooldown_seconds", 30))
        last = self._last_call.get(uid, 0)
        if cooldown and last and now - last < cooldown:
            return (False, "刚画过，等我缓一下")
        today = time.strftime("%Y-%m-%d")
        if group:
            limit = max(0, self._int("group_daily_limit", 20))
            key = str(umo or "")
            if limit and key:
                record = self._daily_group.get(key) or [today, 0]
                if record[0] != today:
                    record = [today, 0]
                if record[1] >= limit:
                    self._daily_group[key] = record
                    return (False, "这个群今天画得够多啦，明天再画")
                self._daily_group[key] = record
            return (True, "")
        limit = max(0, self._int("private_daily_limit", 0))
        if limit:
            record = self._daily.get(uid) or [today, 0]
            if record[0] != today:
                record = [today, 0]
            if record[1] >= limit:
                self._daily[uid] = record
                return (False, "今天画得够多啦，明天再画")
            self._daily[uid] = record
        return (True, "")

    def _mark_call(self, uid: str, umo: str = "", group: bool = False, cooldown: bool = True):
        """记一次出图。cooldown=False 用于陪伴主动分享：算额度，但不占用户的冷却。"""
        if cooldown:
            self._last_call[uid] = time.time()
        today = time.strftime("%Y-%m-%d")
        record = self._daily.get(uid) or [today, 0]
        if record[0] != today:
            record = [today, 0]
        record[1] = int(record[1]) + 1
        self._daily[uid] = record
        if group:
            key = str(umo or "")
            if key:
                grecord = self._daily_group.get(key) or [today, 0]
                if grecord[0] != today:
                    grecord = [today, 0]
                grecord[1] = int(grecord[1]) + 1
                self._daily_group[key] = grecord

    # ---------- 后端 ----------

    def _endpoint(self) -> str:
        """生图接口地址。

        坑（2026-11-17 线上排查）：New API / one-api 这类网关把 OpenAI 兼容接口
        挂在 ``/v1`` 下面。配置里只填 ``https://aiapi.syuan.org`` 时，
        ``/images/generations`` 会命中网站首页，返回一段 HTML，
        解析 JSON 就抛 ``Expecting value: line 1 column 1 (char 0)``
        ——看起来像「接口坏了」，其实是路径少了 /v1。
        所以这里自动补一次：已经带 /v1 的不动，没带的补上。
        """
        return self._api_root() + "/images/generations"

    def _api_root(self) -> str:
        """api_base 归一化成「带 /v1 的根地址」。

        坑（2026-11-18）：拉模型列表那几处曾经直接拼 base + "/models"，
        用户在原生设置页把 api_base 写成 https://api.syuan.org（不带 /v1）时，
        /models 打不通 → 列表拉不到 → 下拉里留着上一站的旧模型名，
        看起来像「模型被固定死了」。出图那条路因为走 _endpoint() 会自动补 /v1，
        所以是通的 —— 两条路必须用同一个根地址。
        """
        base = str(self._cfg("api_base", "") or "").strip().rstrip("/")
        if not base:
            raise ValueError("没配置 api_base")
        if not base.endswith("/v1") and "/v1/" not in base:
            base += "/v1"
        return base

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        key = str(self._cfg("api_key", "") or "").strip()
        if key:
            headers["Authorization"] = "Bearer " + key
        return headers

    def _fallback_line(self, kind: str = "error") -> str:
        """兜底话术：优先用配置里的，配置留空或还是旧默认值就用内置的人话。"""
        key = "error_reply" if kind == "error" else "blocked_reply"
        value = str(self._cfg(key, "") or "").strip()
        pool = FALLBACK_LINES if kind == "error" else BLOCKED_LINES
        legacy = ("画不出来，等会儿再试试", "这个画不了，换个描述吧")
        if value and value not in legacy:
            return value
        return pool[int(time.time()) % len(pool)]

    def _negative(self, prompt: str = "") -> str:
        """负面词 = 用户配置 + 一致性 + 姿势。

        后两段是硬约束，不放进配置项里让人误删：换脸、换背景、手机入镜、抱臂
        这几样一出现，图就「不像同一个场景」了。
        """
        value = self._cfg("negative_prompt", DEFAULT_NEGATIVE_PROMPT)
        if value is None:
            value = DEFAULT_NEGATIVE_PROMPT
        base = str(value).strip()
        items: list[str] = []
        chunks = [base, CONSISTENCY_NEGATIVE, POSE_NEGATIVE]
        if prompt and not self._has_food_prop(prompt):
            chunks.append("cup, glass, drink, milk tea, coffee cup, food, "
                          "holding cup, straw, 杯子, 奶茶杯, 饮料杯, 食物, 吸管, 餐具")
        for chunk in chunks:
            for item in str(chunk or "").split(","):
                item = item.strip()
                if item and item.lower() not in {x.lower() for x in items}:
                    items.append(item)
        return ", ".join(items)

    def _body(self, prompt: str, style: str = "openai", negative: str = "") -> dict:
        """请求体。不认厂商，只按「参数名风格」组装。

        openai：size / n（+ quality / style）
        aliases：image_size / batch_size —— 有些兼容层只认这两个名字
        negative：negative_prompt，后端认识就传，不认识由 `_generate` 去掉重试
        """
        body = {"prompt": prompt}
        if negative:
            body["negative_prompt"] = negative
        model = str(self._cfg("model", "") or "").strip()
        if model:
            body["model"] = model
        size = str(self._cfg("size", "1024x1024"))
        count = max(1, self._int("n", 1))
        if style == "aliases":
            body["image_size"] = size
            body["batch_size"] = count
            return body
        body["size"] = size
        body["n"] = count
        quality = str(self._cfg("quality", "") or "").strip()
        if quality:
            body["quality"] = quality
        style_name = str(self._cfg("style", "") or "").strip()
        if style_name:
            body["style"] = style_name
        return body

    async def _post_json(self, url: str, body: dict, headers=None) -> dict:
        """POST 一个 JSON；遇到「200 但空包 / 不是 JSON」自动重试。

        2026-11-18 事故：站点偶发回 HTTP 200 + 0 字节（网关限流、CDN 空包都长这样），
        旧代码在这里 json.loads("") 抛 `Expecting value: line 1 column 1 (char 0)`，
        日志看着像插件坏了，而且一次失败整轮出图就彻底没图。现在重试 3 次。
        """
        timeout = max(10.0, self._float("timeout", 90.0))
        raw = json.dumps(body).encode("utf-8")
        headers = dict(headers or self._headers())
        attempts = 3
        last = ""
        for index in range(attempts):
            try:
                if aiohttp is not None:
                    client_timeout = aiohttp.ClientTimeout(total=timeout)
                    async with aiohttp.ClientSession(timeout=client_timeout) as session:
                        async with session.post(url, data=raw, headers=headers) as resp:
                            text = await resp.text()
                            if resp.status >= 400:
                                raise APIError(resp.status, text[:300])
                            return self._json_or_empty(text, resp.status, resp.headers)
                text, status = await asyncio.to_thread(
                    self._post_text_blocking, url, raw, timeout, headers)
                return self._json_or_empty(text, status)
            except EmptyBackendResponse as exc:
                last = str(exc)
                if index + 1 < attempts:
                    logger.warning("[amo_image] %s，%.1f 秒后重试（%d/%d）"
                                   % (last, 1.5 * (index + 1), index + 1, attempts))
                    await asyncio.sleep(1.5 * (index + 1))
        raise EmptyBackendResponse("%s（已重试 %d 次）" % (last, attempts))

    @staticmethod
    def _json_or_empty(text, status, headers=None) -> dict:
        """解析响应体；空包或非 JSON 抛 EmptyBackendResponse（可重试）。

        2026-11-18：把响应的 server / cf-ray / content-length 一起带进错误里，
        下次再出「200 + 0 字节」时能从日志看出是哪一层（源站还是 CDN）返回的空包。
        """
        body = str(text or "").strip()
        extra = ""
        if headers is not None:
            try:
                keep = {}
                for name in ("server", "cf-ray", "x-request-id", "content-length", "via"):
                    value = headers.get(name)
                    if value:
                        keep[name] = value
                if keep:
                    extra = " [%s]" % json.dumps(keep, ensure_ascii=False)
            except Exception:
                extra = ""
        if not body:
            raise EmptyBackendResponse("后端返回空响应（HTTP %s，0 字节）%s" % (status, extra))
        try:
            return json.loads(body)
        except Exception:
            raise EmptyBackendResponse(
                "后端返回的不是 JSON（HTTP %s）：%s%s" % (status, body[:120], extra))

    def _post_text_blocking(self, url: str, raw: bytes, timeout: float, headers=None):
        import urllib.error
        import urllib.request

        req = urllib.request.Request(url, data=raw, headers=dict(headers or self._headers()), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                return resp.read().decode("utf-8", "ignore"), getattr(resp, "status", 200)
        except urllib.error.HTTPError as exc:
            detail = ""
            try:
                detail = exc.read().decode("utf-8", "ignore")[:300]
            except Exception:
                pass
            raise APIError(exc.code, detail) from exc

    async def _get_json(self, url: str, headers=None):
        """GET 一个 JSON（拉模型列表用）；失败抛异常，由调用方转成提示。"""
        timeout = max(10.0, self._float("timeout", 90.0))
        headers = dict(headers or self._headers())
        if aiohttp is not None:
            client_timeout = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.get(url, headers=headers) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        raise APIError(resp.status, text[:300])
                    return json.loads(text)
        return await asyncio.to_thread(self._get_json_blocking, url, timeout, headers)

    def _get_json_blocking(self, url: str, timeout: float, headers=None):
        import urllib.request

        req = urllib.request.Request(url, headers=dict(headers or self._headers()))
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))

    async def _download(self, url: str) -> bytes:
        timeout = max(10.0, self._float("timeout", 90.0))
        if aiohttp is not None:
            client_timeout = aiohttp.ClientTimeout(total=timeout)
            async with aiohttp.ClientSession(timeout=client_timeout) as session:
                async with session.get(url) as resp:
                    if resp.status >= 400:
                        raise RuntimeError("下载图片 %s: %s" % (resp.status, await resp.text()))
                    return await resp.read()
        return await asyncio.to_thread(self._download_blocking, url, timeout)

    def _download_blocking(self, url: str, timeout: float) -> bytes:
        import urllib.request

        req = urllib.request.Request(url, headers={"User-Agent": "amo-image"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            return resp.read()

    RETRY_STATUS = (400, 404, 415, 422)

    def _style_order(self):
        """参数风格顺序：配置指定就用指定的；auto 时先试上次成功的，再换另一种。"""
        configured = str(self._cfg("request_style", "auto") or "auto").strip().lower()
        if configured in ("openai", "aliases"):
            return [configured]
        cached = self._style_cache.get(self._endpoint(), "")
        order = [cached] if cached in ("openai", "aliases") else []
        for item in ("openai", "aliases"):
            if item not in order:
                order.append(item)
        return order

    def _provider(self):
        """按配置挑后端（openai / openai_chat / gemini / custom）。"""
        return build_provider(self)

    def _options(self, prompt: str = ""):
        return ImageOptions(
            size=self._cfg("size", "1024x1024"),
            n=self._int("n", 1),
            quality=str(self._cfg("quality", "") or ""),
            style=str(self._cfg("style", "") or ""),
            negative=self._negative(prompt),
            aspect_ratio=str(self._cfg("aspect_ratio", "") or ""),
        )

    def _reference_image(self) -> bytes:
        """母参考图：固定 ref_body.png（她 2026-11-21 定稿的三视图）。"""
        try:
            path = os.path.join(self._plugin_data_dir(), "ref_body.png")
            if not os.path.exists(path):
                return b""
            with open(path, "rb") as handle:
                raw = handle.read()
            return raw if 0 < len(raw) <= 20 * 1024 * 1024 else b""
        except Exception:
            return b""

    async def _generate_edit(self, prompt: str, raw: bytes) -> bytes:
        """图生图：把母参考图一起发到 /images/edits，锁脸和身材比例。"""
        url = self._api_root() + "/images/edits"
        model = str(self._cfg("model", "") or "").strip()
        size = str(self._cfg("size", "1024x1024"))
        timeout = max(10.0, self._float("timeout", 120.0))
        key = str(self._cfg("api_key", "") or "").strip()
        headers = {"Authorization": "Bearer " + key} if key else {}
        if aiohttp is not None:
            form = aiohttp.FormData()
            if model:
                form.add_field("model", model)
            form.add_field("prompt", prompt)
            form.add_field("size", size)
            form.add_field("n", "1")
            form.add_field("image", raw, filename="ref.png", content_type="image/png")
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.post(url, data=form, headers=headers) as resp:
                    text = await resp.text()
                    if resp.status >= 400:
                        raise RuntimeError("生图接口 %s: %s" % (resp.status, text[:280]))
                    payload = json.loads(text or "{}")
        else:
            def _post():
                import uuid as _uuid
                boundary = _uuid.uuid4().hex

                def part(name, value):
                    return ('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                            % (boundary, name, value)).encode()

                body = b""
                if model:
                    body += part("model", model)
                body += part("prompt", prompt)
                body += part("size", size)
                body += part("n", "1")
                body += ('--%s\r\nContent-Disposition: form-data; name="image"; filename="ref.png"'
                         '\r\nContent-Type: image/png\r\n\r\n' % boundary).encode()
                body += raw + b"\r\n"
                body += ("--%s--\r\n" % boundary).encode()
                req = urllib.request.Request(
                    url, data=body, method="POST",
                    headers=dict(headers, **{"Content-Type": "multipart/form-data; boundary=" + boundary}))
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.read()
            text = await asyncio.to_thread(_post)
            payload = json.loads(text.decode() or "{}")
        kind, value = parse_image_response(payload)
        return await self._download(value) if kind == "url" else value

    #: 私密套 → 中文「内衣品牌产品拍摄」话术（款式照旧：肚兜/三角裤/薄透袜）
    PRIVATE_DRAW_MAP = (
        ("肚兜", "白色真丝系颈露背肚兜"),
        ("内裤", "白色棉质三角内裤"),
        ("白丝", "白色薄透长袜"),
        ("丝袜", "白色薄透长袜"),
    )

    def _is_private_prompt(self, prompt: str) -> bool:
        text = str(prompt or "")
        return any(word in text for word in ("私密", "肚兜", "内裤", "白丝", "丝袜"))

    def _private_draw_prompt(self, prompt: str) -> str:
        """私密套换说法：款式照旧，只换成内衣品牌拍摄的正当语境。"""
        text = str(prompt or "")
        for word, replacement in self.PRIVATE_DRAW_MAP:
            text = text.replace(word, replacement)
        text = re.sub(r"私密·[^｜，,\s]+｜", "", text)
        text = re.sub(r"（[^）]*系颈系腰[^）]*）", "", text)
        return "内衣品牌产品拍摄，居家保守穿搭，不露点。" + text

    #: 内容检查是概率性的（2026-11-21 实测：同一句提示词时过时不过，约一半），被拒就重发。
    #: 私密套已换成「寝衣·抹胸薄纱长裙」，不再走「换说法」那条分支，一律走三视图母体图生图。
    POLICY_RETRY = 3

    def _size_expects_landscape(self) -> bool:
        """配置的 size 是不是横图（1536x1024）。"""
        match = re.fullmatch(r"\s*(\d+)\s*[xX×]\s*(\d+)\s*", str(self._cfg("size", "") or ""))
        if not match:
            return False
        return int(match.group(1)) > int(match.group(2))

    @staticmethod
    def _image_size(raw: bytes):
        """读图片的宽高；读不出来返回 None。"""
        try:
            import io as _io
            from PIL import Image as _PILImage
            with _PILImage.open(_io.BytesIO(raw)) as img:
                return img.size
        except Exception:
            return None

    def _bad_frame(self, raw: bytes) -> str:
        """画幅对不对：空串=对；否则返回一句说明。

        2026-11-21 她报：照片又变竖屏，比例不对、身体被拉长、脸成了马脸。
        根因是站点偶尔无视 size=1536x1024，直接返 1086×1448 竖图。
        """
        if not raw or not self._size_expects_landscape():
            return ""
        size = self._image_size(raw)
        if not size:
            return ""
        width, height = size
        if width >= height:
            return ""
        return "%d×%d 竖图（配置要横图）" % (width, height)

    def _frame_clause(self) -> str:
        """画幅锚：竖构图会把人和脸纵向拉长，写在提示词里压一压。"""
        if not self._size_expects_landscape():
            return ""
        return ("。画面必须是横向横幅构图（横屏，宽大于高），人物比例自然："
                "脸不要纵向拉长，身体不要被拉长或压扁")

    async def _generate(self, prompt: str) -> bytes:
        """出图：有母参考就只走图生图。

        2026-11-21 她的口径：**图生图过不去就直接不发**，绝不回落文生图
        ——文生图没有母参考，脸和 155cm/6 头身那套比例全丢，出来的图一眼假。
        失败由终端说一句「暂时没时间，下次再拍」；主动分享那条路本来就只记日志。
        """
        raw = self._reference_image()
        tries = max(1, self.POLICY_RETRY)
        if raw:
            if time.time() < getattr(self, "_edit_pause_until", 0):
                raise RuntimeError("图生图暂停中（额度不足），这次不发")
            last = ""
            wrong_frame = b""
            for index in range(tries):
                try:
                    edit_prompt = (str(prompt or "").strip()
                                   + self._frame_clause()
                                   + "。只输出一张单人生活照：不要三视图、不要多人并排、不要白底产品图。")
                    data = await self._generate_edit(edit_prompt, raw)
                    problem = self._bad_frame(data)
                    if not problem:
                        return data
                    wrong_frame = data
                    last = "画幅不对：" + problem
                    logger.warning("[amo_image] %s，重拍（%d/%d）" % (last, index + 1, tries))
                    await asyncio.sleep(0.8)
                    continue
                except Exception as exc:
                    text = str(exc)
                    last = text
                    # 402 是额度，短时间不会恢复：停 10 分钟，别让她每张都白等一轮
                    if "402" in text or "insufficient_quota" in text:
                        self._edit_pause_until = time.time() + 600
                        logger.warning("[amo_image] 图生图额度不足，暂停 10 分钟再试")
                        break
                    if "content_policy_violation" in text or "content check" in text:
                        logger.info("[amo_image] 图生图被内容检查拒了（%d/%d），重发"
                                    % (index + 1, tries))
                        await asyncio.sleep(1.0 + index)
                        continue
                    logger.warning("[amo_image] 图生图失败：%s" % text)
                    break
            if wrong_frame:
                logger.warning("[amo_image] 重拍 %d 次还是竖图，这张先用着" % tries)
                return wrong_frame
            raise RuntimeError("图生图没通过（不回落文生图）：%s" % last)
        # 只有母参考图不存在时才走文生图（首次部署 / 文件被删）
        last = ""
        for index in range(tries):
            try:
                return await self._provider().generate(prompt, self._options(prompt))
            except Exception as exc:
                last = str(exc)
                if "content_policy_violation" in last or "content check" in last:
                    logger.info("[amo_image] 文生图被内容检查拒了（%d/%d），重发" % (index + 1, tries))
                    await asyncio.sleep(1.0 + index)
                    continue
                raise
        raise RuntimeError("文生图没通过（没有母参考图）：%s" % last)

    # ---------- 一致性：同一个人、同一天同一套造型、同一个地点 ----------

    def _companion_state(self):
        """从陪伴读她的运行状态（此刻在干嘛、今天的日程）；读不到就返回空。"""
        companion = self._companion()
        if companion is None:
            return {}
        try:
            state = getattr(companion, "state", None)
            if state is None:
                return {}
            snapshot = {}
            try:
                snapshot = state.snapshot() or {}
            except Exception:
                snapshot = {}
            activity = {}
            try:
                activity = state.current_activity() or {}
            except Exception:
                activity = {}
            schedule = {}
            try:
                schedule = getattr(state, "schedule", {}) or {}
            except Exception:
                schedule = {}
            return {"snapshot": snapshot, "activity": activity, "schedule": schedule}
        except Exception:
            return {}

    def _outfits(self):
        value = self._cfg("character_outfits", [])
        if isinstance(value, str):
            value = [line.strip() for line in value.split("\n")]
        return [str(item).strip() for item in (value or []) if str(item).strip()]

    def _outfit_pool(self):
        """服装候选：没配就用内置保底，绝不让提示词里缺服装。"""
        return self._outfits() or list(DEFAULT_OUTFITS)

    def _outfit_cooldown(self):
        return max(0, self._int("outfit_change_cooldown_minutes", 60))

    def _outfit_change_words(self):
        value = self._cfg("outfit_change_keywords", ["换衣服", "换装", "洗澡", "换上", "换一身"])
        if isinstance(value, str):
            value = [item.strip() for item in value.split(",")]
        return [str(item).strip() for item in (value or []) if str(item).strip()]

    # ---------- 手动换装（/换一套衣服）----------

    def _plugin_data_dir(self):
        """媒体资产兼容目录：沿用旧 Relationship 数据目录，避免参考图/自拍档案丢失。"""
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            data_root = str(get_astrbot_data_path())
        except Exception:
            data_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        legacy = os.path.join(data_root, "plugin_data", "DeepSeek_Harness_Amo_Relationship")
        terminal = os.path.join(data_root, "plugin_data", "DeepSeek_Harness_Amo_Terminal")
        target = legacy if os.path.isdir(legacy) else os.path.join(terminal, "media_image")
        try:
            os.makedirs(target, exist_ok=True)
        except Exception:
            pass
        return target

    def _look_state_path(self):
        root = self._plugin_data_dir()
        try:
            os.makedirs(root, exist_ok=True)
        except Exception:
            pass
        return os.path.join(root, "look_state.json")

    def _load_look_state(self):
        if isinstance(self._look_state, dict):
            return self._look_state
        state = {}
        try:
            with open(self._look_state_path(), "r", encoding="utf-8") as handle:
                data = json.load(handle)
            if isinstance(data, dict):
                state = data
        except Exception:
            state = {}
        self._look_state = state
        return state

    def _look_bonus(self, day):
        """手动换装累计次数：只对当天有效，换了天自动归零。"""
        state = self._load_look_state()
        if str(state.get("date") or "") != str(day or ""):
            return 0
        try:
            return max(0, int(state.get("bonus") or 0))
        except Exception:
            return 0

    def _bump_look(self, day):
        """手动换下一套，返回新的累计次数；落盘失败也只影响重启后丢失。"""
        state = self._load_look_state()
        bonus = self._look_bonus(day) + 1
        self._look_state = {"date": str(day or ""), "bonus": bonus}
        try:
            path = self._look_state_path()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(self._look_state, handle, ensure_ascii=False)
            os.replace(tmp, path)
        except Exception as exc:
            logger.debug("[amo_image] 换装记录落盘失败: %s" % exc)
        return bonus

    def _today(self):
        day = str((self._companion_state().get("snapshot") or {}).get("date") or "").strip()
        return day or time.strftime("%Y-%m-%d")

    def _wake_prefixes(self):
        """AstrBot 的唤醒词；消息里带着它就剥掉，再判断是不是换装指令。"""
        try:
            config = self.context.get_config()
            prefixes = config.get("wake_prefix") or []
        except Exception:
            return []
        if isinstance(prefixes, str):
            prefixes = [prefixes]
        return [str(item) for item in prefixes if str(item)]

    def _outfit_request(self, text):
        """整句就是「换一套衣服」才算，别把聊天里提到换衣服当成指令。"""
        body = str(text or "").strip().strip(_TRIM_CHARS)
        if not body:
            return ""
        for prefix in self._wake_prefixes():
            if body.startswith(prefix):
                body = body[len(prefix):].strip().strip(_TRIM_CHARS)
                break
        for word in OUTFIT_COMMANDS:
            if body == word:
                return word
        return ""

    def _change_outfit(self):
        """手动换下一套，返回新的造型描述。"""
        day = self._today()
        self._bump_look(day)
        return self._daily_look()

    @staticmethod
    def _minutes_of(text):
        try:
            hour, minute = str(text or "").split(":")[:2]
            return int(hour) * 60 + int(minute)
        except Exception:
            return -1

    def _outfit_changes(self, day, now_minutes):
        """今天已经生效的换装次数。

        - 同一段日程只算一次：两次换装至少隔 `outfit_change_cooldown_minutes`，
          避免「换裙子」「换外套」连着两条把造型连跳好几套；
        - 只算已经开始的事件，没到点的不算。
        """
        words = self._outfit_change_words()
        gap = self._outfit_cooldown()          # 分钟
        schedule = (self._companion_state().get("schedule") or {}).get(day) or []
        starts = []
        for item in schedule:
            activity = str(item.get("activity") or "")
            if not any(word in activity for word in words):
                continue
            start = self._minutes_of(item.get("start"))
            if start < 0:
                start = 0          # 没写时间的换装：当天一早就算发生
            if start > now_minutes:
                continue
            starts.append(start)
        starts.sort()
        accepted = []
        for start in starts:
            if accepted and start - accepted[-1] < gap:
                continue
            accepted.append(start)
        return len(accepted)

    def _daily_look(self):
        """今天穿什么、头发什么样。

        - 服装池按「日期 + 今天已生效的换装次数 + 手动换装次数」取一套，
          同一天结果稳定，重启也不变；
        - 日程里出现「换衣服/洗澡」这类词，且间隔够久，才会换下一套；
        - 服装池留空时用内置保底池，保证提示词里永远有服装描述。
        """
        hairstyle = str(self._cfg("character_hairstyle", "") or "").strip()
        outfits = self._outfit_pool()
        state = self._companion_state()
        snapshot = state.get("snapshot") or {}
        day = str(snapshot.get("date") or "").strip()
        if not day:
            day = time.strftime("%Y-%m-%d")
        now_minutes = self._minutes_of(snapshot.get("time") or "")
        if now_minutes < 0:
            now = time.localtime()
            now_minutes = now.tm_hour * 60 + now.tm_min
        changes = self._outfit_changes(day, now_minutes) + self._look_bonus(day)
        index = (zlib.crc32(day.encode("utf-8")) + changes) % len(outfits)
        outfit = outfits[index]
        if hairstyle:
            return "穿%s，%s" % (outfit, hairstyle)
        return "穿%s" % outfit

    def _scene_place(self):
        """此刻她在哪。锁定日程时，就在日程那一格的地点，不随机换场景。"""
        if not self._bool("lock_scene_to_schedule", True):
            return ""
        state = self._companion_state()
        activity = state.get("activity") or {}
        return str(activity.get("place") or "").strip()

    def _scene_zone(self):
        """日程里的场景类型（hotel/scenic/home…）；锁日程才用。"""
        if not self._bool("lock_scene_to_schedule", True):
            return ""
        activity = (self._companion_state().get("activity") or {})
        return str(activity.get("zone") or "").strip().lower()

    def _scene_activity(self):
        """此刻在干嘛；和地点一样来自日程，避免图和日程对不上。"""
        if not self._bool("lock_scene_to_schedule", True):
            return ""
        activity = (self._companion_state().get("activity") or {})
        return str(activity.get("activity") or "").strip()[:40]

    def _gender(self):
        """性别锚：不写的话模型会自由发挥，之前就出现过画成男生。

        `自动` 时先看外观/角色描述里有没有线索，没有就按 Amo 的默认女生。
        """
        raw = str(self._cfg("character_gender", "自动") or "自动").strip()
        if raw in ("女", "女生", "female", "f", "F"):
            return "女生"
        if raw in ("男", "男生", "male", "m", "M"):
            return "男生"
        text = " ".join([self._appearance(), str(self._cfg("character_persona", "") or "")])
        if any(word in text for word in ("男生", "男孩", "少年", "男性")):
            return "男生"
        return "女生"

    def _persona(self):
        """角色名/一句话人设；没配就用陪伴的人格名。"""
        value = str(self._cfg("character_persona", "") or "").strip()
        if value:
            return value
        companion = self._companion()
        name = str(getattr(companion, "persona_name", "") or "").strip()
        if not name:
            conf = getattr(companion, "config", None) or {}
            name = str(conf.get("persona_name") or conf.get("bot_name") or "").strip()
        return name

    def _camera(self, prompt, forced=None):
        """拍摄角度：拍自己=自拍，拍别人/别的东西=他拍。

        这条不写，模型会把「桌上的一杯咖啡」也画成怼脸自拍，或者把「自拍」画成
        别人站在对面拍——角度错了比衣服错了还明显。

        ``forced`` 是陪伴插件（唯一大脑）给的明确判定：True 自拍 / False 他拍。
        给了就以它为准——不能再去扫拼好的整段提示词，那里有地点（…山…/…街…/…店…），
        会把「自拍」误判成他拍（踩过的坑：在景区自拍被画成路人举着手机拍）。
        """
        mode = str(self._cfg("camera_mode", "自动") or "自动").strip()
        if mode in ("自拍", "selfie"):
            return SELFIE_CAMERA
        if mode in ("他拍", "third", "第三人称"):
            return OTHER_CAMERA
        if forced is not None:
            return SELFIE_CAMERA if forced else OTHER_CAMERA
        value = str(prompt or "")
        if any(word in value for word in SELFIE_WORDS):
            return SELFIE_CAMERA
        if any(word in value for word in OTHER_WORDS):
            return OTHER_CAMERA
        return SELFIE_CAMERA  # 没线索时按自拍：她要给人看的通常是自己的照片

    def _is_selfie(self, prompt, forced=None) -> bool:
        """这句是不是自拍。姿势约束要靠它分叉：自拍必须拿着手机，他拍不能出现手机。"""
        mode = str(self._cfg("camera_mode", "自动") or "自动").strip()
        if mode in ("自拍", "selfie"):
            return True
        if mode in ("他拍", "third", "第三人称"):
            return False
        if forced is not None:
            return bool(forced)
        value = str(prompt or "")
        if any(word in value for word in SELFIE_WORDS):
            return True
        if any(word in value for word in OTHER_WORDS):
            return False
        return True

    def _scheduled_outfit(self):
        """日程里这一段穿什么；陪伴没装/旧日程没有 outfit 时返回空。

        2026-11-16：日程里偶尔只剩一件（「穿着汉服·雪霁｜对襟褙子」，裙袜鞋都没了），
        模型只好自己补，前一张交领、后一张就成抹胸了。这里按套名把它补回整套，
        补不上就原样返回——宁可只有一件，也不能编不存在的衣服。
        """
        activity = (self._companion_state().get("activity") or {})
        value = str(activity.get("outfit") or "").strip()
        if value:
            return self._complete_outfit(value)
        # 这一格没写衣服时，不能自己换一个池子另抽一套：走终端同一个「当天锁定」，
        # 否则群里一张淡蓝、私聊一张淡粉。
        engine = getattr(self._companion(), "outfits", None)
        getter = getattr(engine, "for_activity", None)
        if callable(getter):
            try:
                got = str(getter(dict(activity), time.strftime("%Y-%m-%d")) or "").strip()
                if got:
                    return self._complete_outfit(got)
            except Exception as exc:
                logger.debug("[amo_image] 按日程补穿搭失败: %s" % exc)
        return ""

    def _complete_outfit(self, value: str) -> str:
        """把「只写了半套」的穿搭按套名补成整套。"""
        text = str(value or "").strip()
        if not text:
            return ""
        pieces = [item.strip() for item in re.split(r"[，,]", text) if item.strip()]
        heads = {item.split("｜", 1)[0].strip() for item in pieces if "｜" in item}
        if len(heads) != 1:
            return text
        set_name = next(iter(heads))
        # 已经是整套（>=3 件）就不动
        if len(pieces) >= 3:
            return text
        wardrobe = self._companion()
        engine = None
        for attr in ("outfits",):
            engine = getattr(wardrobe, attr, None) if wardrobe is not None else None
            if engine is not None:
                break
        compose = getattr(engine, "compose_set", None) if engine is not None else None
        if not callable(compose):
            return text
        try:
            full = str(compose(set_name) or "").strip()
        except Exception as exc:
            logger.debug("[amo_image] 补整套失败: %s" % exc)
            return text
        if not full:
            return text
        logger.info("[amo_image] 穿搭只有半套，按套名补成整套：%s -> %s"
                    % (text[:40], full[:60]))
        return full

    def _appearance(self):
        """外观：Core_Appearance（自我形象档案）优先，没配才用旧的人设外观。

        2026-11-15 自我认知升级：长相不再只是「提示词参数」，而是她认人的依据。
        生图提示词和终端注入的永久事实必须同源，所以两张表都走 self_face.appearance。
        """
        try:
            value = self_face.appearance(self)
        except Exception:
            value = ""
        if value:
            return value
        value = str(self._cfg("character_appearance", "") or "").strip()
        return value or DEFAULT_APPEARANCE

    def _last_scene(self) -> str:
        try:
            with open(self._scene_state_path(), "r", encoding="utf-8") as handle:
                return str((json.load(handle) or {}).get("scene") or "").strip()
        except Exception:
            return ""

    def _scene_state_path(self):
        return os.path.join(self._plugin_data_dir(), "scene_lock.json")

    def _remember_scene(self, place: str, strict: bool = False, zone: str = "") -> str:
        """地点读得到就记住；读不到就沿用上次的，宁可重复也不让背景乱跳。

        ``strict=True``：地点是 Amo 明确给的（这一轮唯一真相），没识别出来也不许
        回落到上次那张图的场景——否则就是「她说在酒店、照片还是昨天的公园」。
        """
        scene = match_scene(place, zone=zone)
        if not scene:
            return "" if strict else self._last_scene()
        try:
            root = self._plugin_data_dir()
            os.makedirs(root, exist_ok=True)
            with open(self._scene_state_path(), "w", encoding="utf-8") as handle:
                json.dump({"place": place, "scene": scene}, handle, ensure_ascii=False)
        except Exception as exc:
            logger.debug("[amo_image] 记录环境失败: %s" % exc)
        return scene

    FOOD_PROP_WORDS = ("喝", "奶茶", "咖啡", "饮料", "水", "吃", "饭", "面",
                       "鱼", "外卖", "蛋糕", "火锅", "杯", "零食")

    def _has_food_prop(self, prompt) -> bool:
        text = str(prompt or "")
        return any(word in text for word in self.FOOD_PROP_WORDS)

    #: 常见城市 → IANA 时区。中国城市不逐个列，没命中的按北京时间。
    CITY_TZ = {
        "东京": "Asia/Tokyo", "大阪": "Asia/Tokyo", "首尔": "Asia/Seoul",
        "新加坡": "Asia/Singapore", "曼谷": "Asia/Bangkok", "吉隆坡": "Asia/Kuala_Lumpur",
        "迪拜": "Asia/Dubai", "伦敦": "Europe/London", "巴黎": "Europe/Paris",
        "柏林": "Europe/Berlin", "莫斯科": "Europe/Moscow", "纽约": "America/New_York",
        "洛杉矶": "America/Los_Angeles", "旧金山": "America/Los_Angeles",
        "西雅图": "America/Los_Angeles", "温哥华": "America/Vancouver",
        "多伦多": "America/Toronto", "悉尼": "Australia/Sydney",
        "墨尔本": "Australia/Melbourne", "奥克兰": "Pacific/Auckland",
        "檀香山": "Pacific/Honolulu",
    }
    #: 没有 tzdata 时的固定偏移兜底（够用即可，不追求夏令时）
    TZ_FALLBACK_HOURS = {
        "Asia/Shanghai": 8, "Asia/Tokyo": 9, "Asia/Seoul": 9, "Asia/Singapore": 8,
        "Asia/Bangkok": 7, "Asia/Kuala_Lumpur": 8, "Asia/Dubai": 4, "Europe/London": 0,
        "Europe/Paris": 1, "Europe/Berlin": 1, "Europe/Moscow": 3,
        "America/New_York": -5, "America/Los_Angeles": -8, "America/Vancouver": -8,
        "America/Toronto": -5, "Australia/Sydney": 10, "Australia/Melbourne": 10,
        "Pacific/Auckland": 12, "Pacific/Honolulu": -10,
    }

    def _tz_for_place(self, place: str = ""):
        """她在的地方是哪个时区。**不写死 UTC+8**：
        地方名里命中已知城市就用那个城市的时区，没命中默认北京时间（数据都是国内的）。
        """
        text = str(place or "")
        for name, zone in self.CITY_TZ.items():
            if name and name in text:
                return zone, name
        return "Asia/Shanghai", ""

    def _now_for_place(self, place: str = ""):
        """按她所在地算「现在」。容器是 UTC，直接 datetime.now() 会差 8 小时。"""
        tz_name, city = self._tz_for_place(place)
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz_name)), tz_name, city
        except Exception:
            hours = self.TZ_FALLBACK_HOURS.get(tz_name, 8)
            return datetime.now(timezone(timedelta(hours=hours))), tz_name, city

    def _time_of_day_clause(self, place: str = "") -> str:
        """此刻她所在地的光线与时段。出图最容易漏的就是这个：
        2026-11-20 晚上 19 点，浙江和贵阳都天黑了，照片还是大白天——
        因为提示词里从来没有时刻。
        """
        try:
            now, tz_name, city = self._now_for_place(place)
        except Exception:
            return ""
        hour = now.hour
        if 5 <= hour < 8:
            desc = "清晨，天刚亮，光是柔和的冷调，不要正午的强光"
        elif 8 <= hour < 11:
            desc = "上午，白天自然光，光线清亮"
        elif 11 <= hour < 14:
            desc = "正午到午后，光线明亮偏白"
        elif 14 <= hour < 17:
            desc = "下午，白天自然光，光偏暖"
        elif 17 <= hour < 19:
            desc = "傍晚，夕阳斜照，天色偏暖偏暗，影子拉长"
        elif 19 <= hour < 22:
            desc = "晚上，窗外已经全黑，室内是暖色灯光，脸上有灯下的柔光"
        else:
            desc = "深夜，窗外一片黑，只有室内灯光或路灯，画面整体偏暗"
        label = city or str(place or "")[:14] or tz_name
        where = "（%s，%s）" % (label, tz_name) if city else "（%s）" % label
        return "此刻是她所在地的 %d:%02d %s，%s。画面光线必须符合这个时间，不要画成白天。" % (
            hour, now.minute, where, desc)

    def _final_prompt(self, prompt, context_lines=None, selfie=None,
                      place=None, activity=None, zone=None):
        scheduled = self._scheduled_outfit()
        # 地点/活动由 Amo 给的话就是唯一真相：不再自己读一遍状态，
        # 也不许回落到「上次那张图的场景」（那正是「说在酒店、照片在公园」的来源）。
        explicit = str(place or "").strip()
        place = explicit or self._scene_place()
        zone_key = str(zone or "").strip() or self._scene_zone()
        # 2026-11-26（用户口径）：日程「在路上」= 她坐 A8 后排（老周开），照片就该在车里；
        # 地铁/公交/走路除外。车上不拿吃喝。
        _by_car = (str(zone_key or "").lower() == "road") and not any(
            w in str(place or "") for w in ("地铁", "站台", "公交", "人行道", "走"))
        if _by_car and "车上" not in str(place or ""):
            place = "车上（后排）" + (" " + str(place or "") if str(place or "") else "")
        scene = self._remember_scene(place, strict=bool(explicit), zone=zone_key)
        # 日程/Amo 给了地点时，它就是唯一真相：activity 里顺口一句「公司」，
        # 不能把在家的画面改成办公室（2026-11-21 她在家拍出公司）。
        # 只有压根没地点、或地点识别不出场景时，才用提示词里的地点兜底。
        locked = bool(str(place or "").strip())
        try:
            prompt_scene = place_words_scene(prompt)
        except Exception:
            prompt_scene = ""
        if prompt_scene and prompt_scene != scene and (not locked or not scene):
            logger.info("[amo_image] 场景以提示词为准：%s -> %s"
                        % (place or zone_key or "-", prompt_scene[:12]))
            scene = prompt_scene
        activity_text = str(activity or "").strip() or self._scene_activity()
        # selfie 是 Amo 的明确判定；没给才由我们按提示词推
        selfie_flag = self._is_selfie(prompt, forced=selfie)
        # 2026-11-28（用户：「拍照明明没有提示手拿东西，是不是日程带进去的？」）：
        # 以前只看 _has_food_prop(prompt)：当拍照时用户没说手拿东西，
        # 但 prompt 里拼接了 activity（例如「吃着厨房备好的营养早餐」/「吃着鲍鱼燕窝粥」），
        # 就会命中「吃/早餐/粥」，误将 with_prop 设为 True，生成「一手拿碗/杯」的照片。
        # 修正：只有当原提示词里明确要求「手拿/端着/喝着/吃着/拿着/端/拿/杯/碗」时才允许带道具；
        # 日程里的吃喝文案不能作为手拿道具的依据。
        explicit_prop = any(w in str(prompt or "") for w in ("手里拿", "手拿", "端着", "端", "拿着", "手握", "握着", "拿着杯", "拿着碗", "拿碗", "拿杯"))
        with_prop = explicit_prop and self._has_food_prop(prompt)
        if _by_car:
            with_prop = False   # 在车上不吃不喝，手里也不拿杯子
        # 穿日程那套时，把发型单独带上（_daily_look 里已经带过，避免重复）
        look = scheduled or ("" if self._companion() is not None else self._daily_look())
        hairstyle = (str(self._cfg("character_hairstyle", "") or "").strip()
                     if scheduled else "")
        # 每次出图换一个自拍机位/姿势（同一秒内重复才可能撞），别让每张都像同一张
        style_seed = "%s|%s|%s|%s" % (prompt, place, activity_text, int(time.time()))
        # 他已经指定了姿势（拍照会带「自拍姿势：」）就不再叠自拍池的随机姿势
        pose_text = ("" if "自拍姿势" in str(prompt or "")
                     else pose_clause(selfie_flag, with_prop=with_prop, seed=style_seed))
        if not pose_text:
            # 他已经指定了姿势（「自拍姿势：…」）：不覆盖他的姿势，但仍要
            # 说明参考图只定长相、头别歪——歪头就是从母图抄来的。
            pose_text = "姿势按上面写的来；头部端正，脸正对镜头；" + REF_ONLY_CLAUSE + "。"
        return build_prompt(
            self._appearance(),
            prompt,
            context_lines,
            # 拍照只穿日程那一套：装了 Amo 就不再拿插件自己的保底池顶替
            look=look,
            look_label="此刻穿着：" if scheduled else "今天的样子：",
            hairstyle=hairstyle,
            place=place,
            activity=activity_text,
            gender=self._gender(),
            persona=self._persona(),
            camera=self._camera(prompt, forced=selfie),
            scene=scene_anchor(place, scene, zone=zone_key),
            pose=pose_text,
            lighting=self._time_of_day_clause(place),
            face=self._face_clause(),
            selfie=selfie_flag,
            selfie_text=selfie_directive(style_seed) if selfie_flag else "",
            no_prop=(selfie_flag and not with_prop),
        )

    def _face_clause(self):
        """脸的锁定句。

        模型的「同一个人」靠不住，得把五官拆开点名；首张图生成后还会把当时的
        外观描述冻结下来（`face_lock.json`），以后即使用户改了配置，脸也不跟着变。
        """
        anchor = self._face_anchor()
        parts = [FACE_LOCK]
        if anchor:
            parts.append("既定形象：" + anchor)
        return "。".join(parts)

    def _face_lock_path(self):
        root = self._plugin_data_dir()
        return os.path.join(root, "face_lock.json")

    def _face_anchor(self):
        """首张图定下的外观描述；没有就返回空串。"""
        try:
            with open(self._face_lock_path(), "r", encoding="utf-8") as handle:
                data = json.load(handle)
            return str((data or {}).get("appearance") or "").strip()
        except Exception:
            return ""

    def _freeze_face(self) -> None:
        """第一次成功出图时把外观冻结下来；已经冻结过就不动。"""
        if self._face_anchor():
            return
        try:
            root = self._plugin_data_dir()
            os.makedirs(root, exist_ok=True)
            with open(self._face_lock_path(), "w", encoding="utf-8") as handle:
                json.dump(
                    {
                        "appearance": self._appearance(),
                        "gender": self._gender(),
                        "hairstyle": str(self._cfg("character_hairstyle", "") or ""),
                        "frozen_at": int(time.time()),
                    },
                    handle,
                    ensure_ascii=False,
                    indent=2,
                )
            logger.info("[amo_image] 已冻结基准脸：%s" % self._appearance()[:40])
        except Exception as exc:
            logger.debug("[amo_image] 冻结基准脸失败: %s" % exc)

    async def draw_for(self, umo: str, uid: str = "", prompt: str = "",
                       selfie: bool | None = None, place: str = "",
                       activity: str = "", zone: str = "") -> bytes | None:
        """给别的插件（陪伴）用的公开出图接口：不接事件，直接返回图片字节。

        失败/关闭/空提示词一律返回 None，绝不抛异常——调用方按「没画出来」处理即可。
        """
        chain = Chain("image.draw", logger=logger)
        chain.step("request", umo=umo, uid=uid, selfie=selfie,
                   place=place, zone=zone, chars=len(str(prompt or "")))
        if not self._bool("enable", True):
            chain.fail("boundary", "生图没开")
            return None
        prompt = str(prompt or "").strip()
        if not prompt:
            chain.fail("request", "空提示词")
            return None
        group = self._group_from_umo(umo)
        if not self._safe_text(prompt, group):
            logger.info("[amo_image] draw_for 输入被内容边界拦下")
            chain.fail("boundary", "内容边界拦下", scene="group" if group else "private")
            return None
        chain.step("boundary", scene="group" if group else "private")
        ok, note = self._quota_ok(str(uid or ""), str(umo or ""), group)
        if not ok:
            logger.info("[amo_image] draw_for 跳过：%s" % (note or "quota"))
            chain.fail("quota", note or "额度/冷却")
            return None
        chain.step("quota", scene="group" if group else "private")
        try:
            context_lines = self._clean_context(
                await self._context_lines(str(umo or ""), str(uid or "")), group
            )
            # 2026-11-23：画面里出现的吃喝必须先记账，别让她白喝（用户口径）
            prompt = await self._bill_photo_props(prompt, activity=activity, place=place)
            final_prompt = self._final_prompt(prompt, context_lines, selfie=selfie,
                                             place=place, activity=activity, zone=zone)
            chain.step("prompt", chars=len(final_prompt or ""), place=place, zone=zone)
            data = await self._generate(final_prompt)
        except Exception as exc:
            logger.warning("[amo_image] draw_for 失败: %s" % exc)
            chain.fail("generate", str(exc))
            return None
        if data:
            # 主动分享算群额度，但不占用户的下一次冷却
            self._mark_call(str(uid or ""), str(umo or ""), group, cooldown=False)
            self._record(uid or "share", prompt, True, 0, len(data))
            self._record_memory(prompt, final_prompt)
            self._archive_self_photo(data, final_prompt, prompt,
                                     selfie=selfie, place=place, activity=activity)
            self._freeze_face()
            chain.step("receipt", bytes=len(data), scene="group" if group else "private")
            chain.done(image_bytes=len(data))
        else:
            chain.fail("generate", "后端没返回图片")
        return data or None

    async def _bill_photo_props(self, prompt: str, activity: str = "", place: str = "") -> str:
        """画面里出现的吃喝先记账；买到了把「刚在哪买的什么、多少钱」写进提示词。

        2026-11-23 用户口径：照片里她手里有奶茶，账上就得有这笔钱。买不起就不画那杯，
        改成「已经喝完、手上空着」——宁可少一样道具，也不要账和照片对不上。
        """
        text = "%s %s %s" % (prompt or "", activity or "", place or "")
        if not self._has_food_prop(text):
            return prompt
        companion = self._companion()
        biller = getattr(companion, "photo_prop_bill", None) if companion is not None else None
        if not callable(biller):
            return prompt
        try:
            info = await biller(text)
        except Exception as exc:
            logger.debug("[amo_image] 照片道具记账失败: %s" % exc)
            return prompt
        body = str(prompt or "").rstrip("。，, ")
        if isinstance(info, dict) and info.get("ok"):
            line = str(info.get("line") or "").strip()
            logger.info("[amo_image] 照片道具已记账：%s" % (info.get("item") or ""))
            return (body + "，" + line) if line else body
        code = str((info or {}).get("code") or "") if isinstance(info, dict) else ""
        if code and code != "no_prop":
            logger.info("[amo_image] 照片里的吃喝没买成（%s），按空着手画" % code)
            return body + "，手里那份已经喝完吃完，杯子和包装都已经扔掉，手上空着"
        return prompt

    # ---------- 面板照片：世界页那张（自拍 / 一寸证件照 / 上次那张） ----------
    # 2026-11-15 从终端 main.py 搬过来：照片状态、缓存与提示词归生图，
    # 终端只留一条代理，「相片」从此不是终端的业务引擎。

    ID_PHOTO_PROMPT = (
        "一寸证件照，正面免冠，纯白背景，端正坐姿，表情自然，"
        "标准证件照构图，光线均匀，高清"
    )
    # 证件照必须和本人一致：脸、五官、身材都不动，只换衣服
    ID_PHOTO_CONSISTENCY = "保持同一个人：脸型、五官、眼睛、发型、身材比例完全不变，只更换服装"

    def _photo_dir(self) -> str:
        path = os.path.join(self._plugin_data_dir(), "photo_cache")
        try:
            os.makedirs(path, exist_ok=True)
        except Exception as exc:
            logger.debug("[amo_image] 建照片目录失败: %s" % exc)
        return path

    def _photo_file(self) -> str:
        return os.path.join(self._photo_dir(), "panel_last.jpg")

    def _photo_tasks(self) -> dict:
        jobs = getattr(self, "_photo_jobs", None)
        if not isinstance(jobs, dict):
            jobs = {}
            self._photo_jobs = jobs
        cutoff = time.time() - 900
        for key in [k for k, v in jobs.items() if float(v.get("ts") or 0) < cutoff]:
            jobs.pop(key, None)
        return jobs

    def _photo_start(self, kind: str, coro) -> str:
        """后台跑出图任务，接口立刻返回 job id，避免面板请求超时。"""
        jobs = self._photo_tasks()
        job_id = "%s-%d" % (kind, int(time.time() * 1000))
        jobs[job_id] = {"status": "running", "kind": kind, "ts": time.time(),
                        "data": None, "msg": ""}

        async def runner():
            try:
                data = await coro
                jobs[job_id].update(status="done", data=data)
                logger.info("[amo_image] 照片任务完成(%s): %d 字符" % (kind, len(str((data or {}).get("image") or ""))))
            except Exception as exc:
                logger.warning("[amo_image] 照片任务失败(%s): %s" % (kind, exc))
                jobs[job_id].update(status="error", msg=str(exc))

        try:
            asyncio.create_task(runner())
        except RuntimeError:
            try:
                coro.close()
            except Exception:
                pass
            jobs[job_id].update(status="error", msg="事件循环不可用")
        return job_id

    def _id_photo_prompt(self, clothes: str = "") -> str:
        clothes = str(clothes or "").strip()[:60] or "白衬衫"
        return "，".join([self.ID_PHOTO_PROMPT, "穿着" + clothes, self.ID_PHOTO_CONSISTENCY])

    def _selfie_prompt(self, outfit: str = "", place: str = "", activity: str = "") -> str:
        parts = ["自拍"]
        if outfit:
            parts.append("穿着" + outfit)
        if place:
            parts.append("在" + place)
        if activity:
            parts.append(str(activity)[:30])
        parts.extend(["自然光", "手机前置摄像头", "生活感"])
        return "，".join(parts)

    def _photo_scene(self) -> dict:
        """此刻在哪/在干嘛/穿什么：从陪伴读；读不到就空着，不编地点。"""
        state = self._companion_state() or {}
        activity = state.get("activity") or {}
        if not isinstance(activity, dict):
            activity = {}
        return {
            "place": str(activity.get("place") or "").strip(),
            "activity": str(activity.get("activity") or "").strip(),
            "outfit": str(activity.get("outfit") or "").strip(),
            "zone": str(activity.get("zone") or "").strip(),
        }

    @staticmethod
    def _photo_bytes_to_url(data: bytes) -> str:
        raw = data or b""
        mime = "image/png" if raw[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"
        return "data:" + mime + ";base64," + base64.b64encode(raw).decode()

    def _save_photo(self, data_url: str) -> int:
        text = str(data_url or "")
        if text.startswith("data:") and "," in text:
            text = text.split(",", 1)[1]
        if not text:
            return 0
        raw = base64.b64decode(text)
        path = self._photo_file()
        tmp = path + ".tmp"
        with open(tmp, "wb") as handle:
            handle.write(raw)
        os.replace(tmp, path)
        return len(raw)

    def _photo_data_url(self) -> str:
        try:
            with open(self._photo_file(), "rb") as handle:
                raw = handle.read()
        except Exception:
            return ""
        return self._photo_bytes_to_url(raw) if raw else ""

    def _record_photo_memory(self, kind: str, clothes: str, prompt: str = "") -> None:
        """拍完记一条：她得记得自己拍过。记忆写入交给终端（它是记忆的入口）。"""
        companion = self._companion()
        remember = getattr(companion, "_remember_photo", None) if companion is not None else None
        label = "证件照" if str(kind) == "id" else "自拍"
        if callable(remember):
            try:
                asyncio.get_running_loop().create_task(
                    remember("", prompt, {"outfit": clothes}, label)
                )
                return
            except RuntimeError:
                pass
            except Exception as exc:
                logger.debug("[amo_image] 记照片失败: %s" % exc)
        self._record_memory(prompt, "拍了一张" + label)

    # ---------- 自我形象档案（self_face.py） ----------
    # 位置很关键：聊天出图、面板照片、主动分享都从 draw_for 出去，
    # 所以存档只挂在这一处，任何一条路径都不会漏。

    def _archive_self_photo(self, raw, final_prompt="", prompt="", selfie=False,
                            place="", activity=""):
        """出图即永久存档：他以后把这张发回来，她要认得。

        注意：元数据（穿搭）取不到就留空，绝不能因为一个名字写错整张图都不进档案
        ——2026-11-15 就因为这里写了不存在的 `_outfit_now()`，四张图一张都没存下来。
        """
        if not raw:
            return None
        outfit = ""
        for name in ("_scheduled_outfit", "_outfit_now"):
            getter = getattr(self, name, None)
            if not callable(getter):
                continue
            try:
                outfit = str(getter() or "").strip()
            except Exception as exc:
                logger.debug("[amo_image] 取穿搭失败（%s）: %s" % (name, exc))
                outfit = ""
            if outfit:
                break
        try:
            row = self_face.archive(
                self,
                raw,
                prompt=final_prompt or prompt,
                place=str(place or ""),
                activity=str(activity or ""),
                outfit=outfit,
                label="自拍" if selfie else "照片",
                kind="self" if selfie else "photo",
            )
            if row:
                logger.info("[amo_image] 自我形象存档 #%s %s %s"
                            % (row.get("id"), row.get("date"), row.get("outfit") or ""))
            return row
        except Exception as exc:
            import traceback
            logger.warning("[amo_image] 自我形象存档失败: %s\n%s"
                           % (exc, traceback.format_exc()[-800:]))
            return None

    def self_face_match(self, source, max_distance=0) -> dict:
        """终端调用：他发来的这张图，是不是她自己拍过的那张。"""
        try:
            raw = self_face.image_bytes_from_any(source)
            if not raw:
                return {}
            row = self_face.match(self, raw, max_distance=max_distance)
            if row:
                logger.info("[amo_image] 认出来了：这张是 #%s（%s，距离 %s）"
                            % (row.get("id"), row.get("date"), row.get("distance")))
            return row
        except Exception as exc:
            logger.debug("[amo_image] 自我形象比对失败: %s" % exc)
            return {}

    def self_face_recent(self, count=4) -> list:
        """终端调用：最近拍过的几张（认不出时给她时间/穿搭线索）。"""
        try:
            rows = self_face.recent(self, count)
        except Exception:
            return []
        out = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            out.append({
                "date": row.get("date") or "",
                "age": self_face.age_text(row.get("ts")),
                "outfit": row.get("outfit") or "",
                "place": row.get("place") or "",
                "label": row.get("label") or "",
                "id": row.get("id") or "",
            })
        return out

    def self_face_identity(self) -> str:
        """终端调用：注入用的「我是谁 / 我长什么样」。"""
        try:
            return self_face.identity_clause(self)
        except Exception:
            return ""

    def self_face_remember(self, row) -> str:
        """终端调用：认出之后的事实句。"""
        try:
            return self_face.remember_clause(row, self)
        except Exception:
            return ""

    async def photo_self(self, payload=None) -> dict:
        """拍一张：kind=self 自拍 / kind=id 一寸证件照。返回 job id。"""
        payload = payload if isinstance(payload, dict) else {}
        kind = str(payload.get("kind") or "self").strip().lower()
        if kind not in ("self", "id"):
            kind = "self"
        clothes = str(payload.get("clothes") or "").strip()
        scene = self._photo_scene()
        prompt = (self._id_photo_prompt(clothes) if kind == "id"
                  else self._selfie_prompt(scene["outfit"], scene["place"], scene["activity"]))
        chain = Chain("image.photo", logger=logger)
        chain.step("request", kind=kind, clothes=clothes, place=scene["place"])

        async def build():
            data = await self.draw_for("", "", prompt, selfie=(kind == "self"),
                                       place=scene["place"], activity=scene["activity"],
                                       zone=scene["zone"])
            if not data:
                chain.fail("generate", "没出图（后端报错或额度不够）")
                raise RuntimeError("没出图（后端报错或额度不够）")
            url = self._photo_bytes_to_url(data)
            size = 0
            try:
                size = self._save_photo(url)
            except Exception as exc:
                logger.debug("[amo_image] 存面板照片失败: %s" % exc)
            chain.step("receipt", bytes=size if size else len(url), kind=kind)
            self._record_photo_memory(kind, clothes, prompt)
            chain.done(kind=kind, bytes=len(data))
            return {"kind": kind, "prompt": prompt, "image": url}

        return {"code": 0, "data": {"job": self._photo_start("self_" + kind, build())}}

    def photo_job(self, job_id) -> dict:
        job = self._photo_tasks().get(str(job_id or ""))
        if not job:
            return {"code": 1, "msg": "任务不存在（插件可能重载过，重新生成一次）"}
        return {"code": 0, "data": {
            "id": job_id, "status": job.get("status"), "kind": job.get("kind"),
            "msg": job.get("msg") or "", "data": job.get("data"),
        }}

    def photo_last(self) -> dict:
        image = self._photo_data_url()
        return {"code": 0, "data": {"image": image, "bytes": len(image)}}

    def photo_clear(self) -> dict:
        removed = False
        try:
            os.remove(self._photo_file())
            removed = True
        except Exception:
            removed = False
        logger.info("[amo_image] 面板照片已清除: %s" % ("是" if removed else "本来就没有"))
        return {"code": 0, "data": {"removed": removed}}

    async def _read_body(self) -> dict:
        if web_request is None:
            return {}
        try:
            payload = await web_request.json(default={}) or {}
        except Exception:
            payload = {}
        return payload if isinstance(payload, dict) else {}

    async def api_photo_self(self):
        return await self.photo_self(await self._read_body())

    async def api_photo_job(self):
        payload = await self._read_body()
        return self.photo_job(payload.get("id") or "")

    async def api_photo_last(self):
        return self.photo_last()

    async def api_photo_clear(self):
        return self.photo_clear()

    # ---------- 面板 Web API ----------

    def _register_web_apis(self):
        """把媒体面板接口挂到 Terminal 命名空间；注册失败只记日志，不影响生图。"""
        routes = [
            ("/status", self.api_status, ["GET"]),
            ("/health", self.api_health, ["GET"]),
            ("/history", self.api_history, ["GET"]),
            ("/config", self.api_config, ["GET"]),
            ("/config/save", self.api_save_config, ["POST"]),
            ("/presets", self.api_presets, ["GET"]),
            ("/models", self.api_models, ["GET"]),
            ("/persona/extract", self.api_persona_extract, ["POST"]),
            ("/wardrobe", self.api_wardrobe, ["GET", "POST"]),
            ("/wardrobe/save", self.api_wardrobe_save, ["POST"]),
            ("/wardrobe/delete", self.api_wardrobe_delete, ["POST"]),
            ("/wardrobe/wear", self.api_wardrobe_wear, ["POST"]),
            ("/test", self.api_test, ["POST"]),
            ("/photo/self", self.api_photo_self, ["GET", "POST"]),
            ("/photo/job", self.api_photo_job, ["GET", "POST"]),
            ("/photo/last", self.api_photo_last, ["GET", "POST"]),
            ("/photo/clear", self.api_photo_clear, ["GET", "POST"]),
        ]
        for path, handler, methods in routes:
            try:
                self.context.register_web_api("/" + PLUGIN_NAME + path, handler, methods, path)
            except TypeError:
                try:
                    self.context.register_web_api("/" + PLUGIN_NAME + path, methods, path, handler)
                except Exception as exc:
                    logger.warning("[amo_image] 面板接口 %s 兼容注册失败: %s" % (path, exc))
            except Exception as exc:
                logger.warning("[amo_image] 面板接口 %s 注册失败: %s" % (path, exc))

    @staticmethod
    def _json(payload):
        if json_response is not None:
            try:
                return json_response(payload)
            except Exception:
                pass
        return payload

    @staticmethod
    def _fail(message):
        if error_response is not None:
            try:
                return error_response(message)
            except Exception:
                pass
        return {"code": 1, "message": message}

    def _mask_key(self) -> str:
        key = str(self._cfg("api_key", "") or "")
        if not key:
            return ""
        if len(key) <= 10:
            return "已配置"
        return key[:4] + "…" + key[-4:]

    def _today_used(self) -> int:
        today = time.strftime("%Y-%m-%d")
        total = 0
        for record in self._daily.values():
            if isinstance(record, list) and len(record) == 2 and record[0] == today:
                total += int(record[1])
        return total

    def _today_group_used(self) -> int:
        today = time.strftime("%Y-%m-%d")
        total = 0
        for record in self._daily_group.values():
            if isinstance(record, list) and len(record) == 2 and record[0] == today:
                total += int(record[1])
        return total

    def _sync_config(self) -> None:
        """AstrBot 原生设置页改完，把配置文件的新值并进内存（面板与接口立刻一致）。"""
        try:
            _config_watch.reload_if_changed(self.config, logger)
        except Exception as exc:
            logger.debug("[config] 同步配置文件失败: %s" % exc)

    def _sync_config_throttled(self) -> None:
        """每 1 秒最多查一次配置文件 mtime，变了就并进内存。

        2026-11-18 事故：用户在原生设置页把 api_base 换成桥站，插件内存里还留着
        旧站地址，draw_for 一直连 api.syuan.org（`Cannot connect to host`），
        看起来像「明明填了桥站却默认连渊」。原来只有面板接口才会 _sync_config，
        聊天/出图/额度这些路径根本不读配置文件，所以必须在这里兜住。
        """
        now = time.time()
        if now - getattr(self, "_cfg_sync_at", 0.0) < 1.0:
            return
        self._cfg_sync_at = now
        try:
            _config_watch.reload_if_changed(self.config, logger)
        except Exception:
            pass

    async def api_health(self):
        """我自己连没连上终端/记忆库。面板顶部那一行就看这个。"""
        self._sync_config()
        return self._json({"code": 0, "data": _link_probe(self)})

    async def api_status(self):
        self._sync_config()
        return self._json({
            "code": 0,
            "data": {
                "link": _link_probe(self),
                "name": PLUGIN_NAME,
                "version": PLUGIN_VERSION,
                "enabled": self._bool("enable", True),
                "api_base": str(self._cfg("api_base", "") or ""),
                "api_key_masked": self._mask_key(),
                "provider": self._provider().name,
                "model": str(self._cfg("model", "") or ""),
                "size": str(self._cfg("size", "") or ""),
                "allow_private": self._bool("allow_private", True),
                "allow_group": self._bool("allow_group", True),
                "cooldown_seconds": self._int("cooldown_seconds", 30),
                "private_daily_limit": self._int("private_daily_limit", 0),
                "group_daily_limit": self._int("group_daily_limit", 20),
                "safe_mode": self._bool("safe_mode", True),
                "users_today": self._today_used(),
                "groups_today": self._today_group_used(),
                "calls_total": self._calls_total,
                "history_size": len(self._history),
                "look": self._scheduled_outfit() or self._daily_look(),
                "uptime_seconds": int(time.time() - self._started_at),
            },
        })

    async def api_history(self):
        return self._json({"code": 0, "data": {"items": list(self._history)}})

    async def api_config(self):
        self._sync_config()
        keys = [
            "provider", "enable", "api_base", "model", "size", "n", "quality", "style",
            "timeout", "request_style", "negative_prompt", "aspect_ratio", "chat_modalities",
            "custom_url", "custom_body", "custom_response_path",
            "character_appearance", "use_memory_context", "memory_context_limit",
            "allow_private", "allow_group", "require_at_in_group", "quote_in_group",
            "keywords", "photo_keywords", "photo_default_prompt", "cooldown_seconds",
            "private_daily_limit", "group_daily_limit",
            "safe_mode", "blocked_reply", "reply_prefix", "error_reply", "batch_max",
            "character_hairstyle", "character_outfits", "character_gender",
            "character_persona", "camera_mode", "outfit_change_keywords",
            "outfit_change_cooldown_minutes", "lock_scene_to_schedule",
        ]
        data = {k: self._cfg(k, None) for k in keys}
        data["provider"] = str(self._cfg("provider", "openai") or "openai")
        data["character_gender"] = str(self._cfg("character_gender", "自动") or "自动")
        # 面板只回掩码；真密钥不经过前端，避免误存/误传
        data["api_key"] = ""
        data["api_key_masked"] = self._mask_key()
        return self._json({"code": 0, "data": data})

    @staticmethod
    def _collect_models(payload):
        """从各家 /models 响应里收集模型名：data[].id、models[].name、纯字符串数组。"""
        items = []
        if isinstance(payload, dict):
            for key in ("data", "models", "result", "items"):
                value = payload.get(key)
                if isinstance(value, list):
                    items = value
                    break
        elif isinstance(payload, list):
            items = payload
        names = []
        for item in items:
            if isinstance(item, str):
                name = item
            elif isinstance(item, dict):
                name = item.get("id") or item.get("name") or item.get("model") or ""
                if isinstance(name, str) and name.startswith("models/"):
                    name = name.split("/", 1)[1]
            else:
                continue
            name = str(name or "").strip()
            if name and name not in names:
                names.append(name)
        return names

    # ---------- 原生设置页：把后端的模型列表写进 _conf_schema.json ----------
    # AstrBot 的配置页只认插件加载时读进内存的 schema（dashboard/services/config_service.py
    # get_plugin_config -> plugin_md.config.schema），框架没有「渲染时远程拉候选」的钩子，
    # 所以 model 只能靠这里：启动后拉一次 /models，把图片模型写进 model.options，
    # 重载/重启后原生设置页那一格就是下拉。手打模型名的下场见 2026-11-18：换了站点
    # 还留着旧模型名，出图全部 503。
    async def _sync_model_options(self) -> None:
        try:
            provider = self._provider().name
        except Exception:
            return
        if provider == "custom":
            return
        try:
            base = self._api_root()
        except Exception:
            return
        key = str(self._cfg("api_key", "") or "").strip()
        try:
            if provider == "gemini":
                headers = {"x-goog-api-key": key} if key else {}
                payload = await self._get_json(base + "/models", headers)
            else:
                payload = await self._get_json(base + "/models", self._headers())
            names = [n for n in self._collect_models(payload) if n]
        except Exception as exc:
            logger.warning("[amo_image] 拉模型列表失败（原生设置页下拉保持原样）: %s" % exc)
            return
        if not names:
            return
        image_re = re.compile(r"image|dall|flux|kolors|sd|draw|wanx|cogview", re.I)
        image_names = [n for n in names if image_re.search(n)]
        picked = list(image_names or names)
        current = str(self._cfg("model", "") or "").strip()
        if current and current not in picked:
            logger.warning("[amo_image] 当前配置的模型 %s 不在后端列表里（共 %d 个），"
                           "原生设置页里请重新选一个" % (current, len(names)))
        wanted = ([current] if current else []) + picked
        seen = set()
        ordered = []
        for name in wanted:
            if name and name not in seen:
                seen.add(name)
                ordered.append(name)
        path = os.path.join(self.plugin_dir, "_conf_schema.json")
        try:
            with open(path, encoding="utf-8-sig") as handle:
                schema = json.load(handle)
        except Exception as exc:
            logger.debug("[amo_image] 读 _conf_schema.json 失败: %s" % exc)
            return
        if not isinstance(schema, dict):
            return
        item = schema.get("model")
        if not isinstance(item, dict):
            return
        if item.get("options") == ordered:
            return
        item["options"] = ordered
        tmp = path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump(schema, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(tmp, path)
        except Exception as exc:
            logger.warning("[amo_image] 写 _conf_schema.json 失败: %s" % exc)
            return
        logger.info("[amo_image] 已把后端 %d 个模型写进 _conf_schema.json；"
                    "重载插件后原生设置页「生图模型」就是下拉" % len(ordered))

    _amo_loaded_hook = getattr(filter, "on_astrbot_loaded", None)

    if _amo_loaded_hook is not None:
        @_amo_loaded_hook()
        async def on_astrbot_loaded(self):
            """所有插件加载完：顺手把模型下拉的文件刷新一遍。"""
            try:
                await self._sync_model_options()
            except Exception as exc:
                logger.debug("[amo_image] 同步模型下拉失败: %s" % exc)

    async def api_models(self):
        """拉当前后端的模型列表，面板里只让选、不让手填。"""
        provider = self._provider().name
        try:
            base = self._api_root()
        except Exception:
            base = ""
        key = str(self._cfg("api_key", "") or "").strip()
        if provider == "custom":
            return self._json({"code": 1, "message": "自定义后端没有模型列表，请在配置里手填 model"})
        if not base:
            return self._json({"code": 1, "message": "先填 api_base"})
        try:
            if provider == "gemini":
                url = base + "/models"
                headers = {"x-goog-api-key": key} if key else {}
                payload = await self._get_json(url, headers)
                names = [name for name in self._collect_models(payload) if "image" in name.lower()]
                if not names:
                    names = self._collect_models(payload)
            else:
                url = base + "/models"
                headers = self._headers()
                payload = await self._get_json(url, headers)
                names = self._collect_models(payload)
            current = str(self._cfg("model", "") or "").strip()
            if current and current not in names:
                names.insert(0, current)
            return self._json({"code": 0, "data": {
                "provider": provider, "models": names,
                "current": current, "count": len(names)}})
        except Exception as exc:
            logger.warning("[amo_image] 拉模型列表失败: %s" % exc)
            return self._json({"code": 1, "message": "拉取失败：%s" % exc})

    async def api_presets(self):
        """面板里的后端预设，只填 base/model，不动密钥。"""
        return self._json({"code": 0, "data": {"items": list(PROVIDER_PRESETS)}})

    # 外观线索词：命中这些词的分句才像「长什么样」，不是性格/说话风格
    _LOOK_WORDS = (
        "头发", "长发", "短发", "发色", "蓝发", "银发", "黑发", "金发",
        "眼睛", "眼眸", "瞳孔", "耳朵", "兽耳", "鳍耳", "尾巴",
        "皮肤", "身高", "体型", "脸型", "酒窝", "虎牙", "刘海",
    )
    _LOOK_KEYS = (
        "外貌", "长相", "样子", "发色", "发型", "瞳色", "眼睛",
        "体型", "体型特征", "特征", "穿着", "服装", "皮肤",
        # 身高体重年龄也算人物设定的一部分：模型不看数字，但「25岁 / 155cm / 娇小」
        # 这类描述能帮它定住年龄感和体型，别每次画成不同的人
        "年龄", "身高", "身高体重", "体重",
    )
    # 这些词说明是行为/性格，不是长相
    _BEHAVIOR_WORDS = (
        "会", "喜欢", "被", "抱", "亲", "撒娇", "怼", "回", "说",
        "觉得", "认为", "习惯", "总", "得意", "开心", "生气", "委屈",
        "哭", "笑", "叫", "喊", "缠", "粘",
    )
    _MINOR_WORDS = ("萝莉", "loli", "幼女", "未成年", "正太")

    @classmethod
    def _look_clauses(cls, text):
        """从人格文本里挑出描述长相的分句；挑不到就返回空。

        人格常是「姓名：… / 体型特征：… / 爱好：…」这种条目，优先读长相相关的 key；
        读不到再扫分句，但要把「被夸了会翘尾巴」这种行为描写排除掉。
        """
        out = []

        def take(clause):
            clause = clause.strip()
            if not clause or len(clause) > 24:
                return
            if any(word in clause for word in cls._BEHAVIOR_WORDS):
                return
            if any(word in clause for word in cls._MINOR_WORDS):
                return
            clause = clause.replace(" / ", "，").replace("/", "，").strip("， ")
            if clause and clause not in out:
                out.append(clause)

        for line in str(text or "").splitlines():
            line = line.strip()
            if not line:
                continue
            key, value = "", line
            for sep in ("：", ":"):
                if sep in line:
                    key, value = [part.strip() for part in line.split(sep, 1)]
                    break
            clauses = [part.strip() for part in re.split(r"[，,。；;]", value) if part.strip()]
            if key in cls._LOOK_KEYS:
                for clause in clauses:
                    take(clause)
                    if len(out) >= 3:
                        return out
                continue
            for clause in clauses:
                if any(word in clause for word in cls._LOOK_WORDS):
                    take(clause)
                    if len(out) >= 3:
                        return out
        return out

    @staticmethod
    def _guess_gender(text):
        raw = str(text or "")
        female = sum(raw.count(word) for word in ("女孩", "女生", "少女", "女性", "姑娘", "妻子", "老婆", "她"))
        male = sum(raw.count(word) for word in ("男孩", "男生", "少年", "男性"))
        return "男" if male > female else "女"

    async def _persona_text(self):
        """读陪伴的人格设定；读不到返回空串。"""
        companion = self._companion()
        llm = getattr(companion, "llm", None)
        reader = getattr(llm, "persona", None) if llm is not None else None
        if callable(reader):
            try:
                text = await reader("")
                if text:
                    return str(text)
            except Exception as exc:
                logger.debug("[amo_image] 读人格失败: %s" % exc)
        try:
            manager = getattr(self.context, "persona_manager", None)
            if manager is not None:
                persona = await manager.get_default_persona_v3(None)
                if isinstance(persona, dict):
                    return str(persona.get("prompt") or "")
                return str(getattr(persona, "prompt", "") or "")
        except Exception as exc:
            logger.debug("[amo_image] 读 AstrBot 人格失败: %s" % exc)
        return ""

    def _persona_name(self):
        companion = self._companion()
        name = str(getattr(companion, "persona_name", "") or "").strip()
        if not name:
            conf = getattr(companion, "config", None) or {}
            name = str(conf.get("persona_name") or conf.get("bot_name") or "").strip()
        return name

    # ---------- 服装库（数据在陪伴插件，这里只做面板代理）----------

    async def _companion_call(self, name, payload=None):
        """调陪伴插件上的同名接口；没装就直接说清楚。"""
        companion = self._companion()
        handler = getattr(companion, name, None) if companion is not None else None
        if not callable(handler):
            return self._fail("没装陪伴插件（Astrbot_Amo_forever），服装库在它那边")
        try:
            result = await handler()
        except Exception as exc:
            logger.warning("[amo_image] 转发 %s 失败: %s" % (name, exc))
            return self._fail("陪伴插件处理失败：%s" % exc)
        return result if isinstance(result, (dict, list)) else self._fail("陪伴插件返回异常")

    def _wardrobe_payload(self, payload):
        """面板已经把 body 交给陪伴的 _body()，这里只做兜底。"""
        return payload if isinstance(payload, dict) else {}

    async def api_wardrobe(self):
        return await self._companion_call("api_wardrobe")

    async def api_wardrobe_save(self):
        return await self._companion_call("api_wardrobe_save")

    async def api_wardrobe_delete(self):
        return await self._companion_call("api_wardrobe_delete")

    async def api_wardrobe_wear(self):
        return await self._companion_call("api_wardrobe_wear")

    async def api_persona_extract(self):
        """从人格设定里提取性别/外观/角色名，填进面板。"""
        text = await self._persona_text()
        clauses = self._look_clauses(text)
        appearance = "，".join(clauses)[:160]
        source = "人格"
        if not text:
            source = "默认"
        return self._json({
            "code": 0,
            "data": {
                "gender": self._guess_gender(text),
                "appearance": appearance,
                "persona": self._persona_name(),
                "source": source,
                "raw": str(text or "").strip()[:160],
            },
        })

    def _to_bool(self, value):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in ("1", "true", "yes", "on", "是", "开")

    async def api_save_config(self):
        """面板保存配置：只认白名单字段，密钥留空/掩码不覆盖。"""
        payload = {}
        if web_request is not None:
            try:
                payload = await web_request.json(default={}) or {}
            except Exception:
                payload = {}
        if not isinstance(payload, dict):
            return self._fail("配置格式不对")
        data = {}
        for key in WEB_EDITABLE:
            if key not in payload:
                continue
            value = payload[key]
            try:
                if key in WEB_BOOL_KEYS:
                    value = self._to_bool(value)
                elif key in WEB_INT_KEYS:
                    value = int(float(value))
                elif key in WEB_LIST_KEYS:
                    if isinstance(value, str):
                        text = value.replace("，", "\n").replace(",", "\n")
                        value = [line.strip() for line in text.splitlines()]
                    value = [str(item).strip() for item in (value or []) if str(item).strip()]
                else:
                    value = str("" if value is None else value)
            except Exception:
                continue
            data[key] = value
        # 密钥：留空 / 回传掩码都不覆盖
        key_value = str(data.get("api_key", "") or "")
        if not key_value or "…" in key_value or key_value == self._mask_key():
            data.pop("api_key", None)
        if not data:
            return self._fail("没有要保存的字段")
        try:
            if hasattr(self.config, "update"):
                self.config.update(data)
            else:
                self.config = dict(self.config or {})
                self.config.update(data)
        except Exception as exc:
            return self._fail("保存失败：%s" % exc)
        # 换后端/地址/模型后，旧的参数风格结论不再作数
        if any(name in data for name in ("provider", "api_base", "model", "request_style")):
            self._style_cache.clear()
            self._negative_ok.clear()
        saved = await self._persist_config()
        return self._json({"code": 0, "data": {"saved": bool(saved), "applied": sorted(data)}})

    async def _persist_config(self):
        """把配置写回 AstrBot；配置对象不支持保存时只留内存，不报错。"""
        cfg = self.config
        saver = getattr(cfg, "save_config_async", None)
        if callable(saver):
            try:
                return bool(await saver())
            except Exception as exc:
                logger.warning("[amo_image] 配置落盘失败: %s" % exc)
        saver = getattr(cfg, "save_config", None)
        if callable(saver):
            try:
                await asyncio.to_thread(saver)
                return True
            except Exception as exc:
                logger.warning("[amo_image] 配置落盘失败: %s" % exc)
        return False

    async def api_test(self):
        """面板里试画一张：返回 data:image/png;base64，前端直接 <img>。"""
        payload = {}
        if web_request is not None:
            try:
                payload = await web_request.json(default={})
            except Exception:
                payload = {}
        prompt = str((payload or {}).get("prompt") or "").strip() or "窗边的猫，午后阳光"
        final_prompt = self._final_prompt(prompt, [])
        started = time.time()
        try:
            data = await self._generate(final_prompt)
        except Exception as exc:
            self._record("panel", prompt, False, int((time.time() - started) * 1000), 0)
            return self._fail("生图失败：%s" % exc)
        if not data:
            self._record("panel", prompt, False, int((time.time() - started) * 1000), 0)
            return self._fail("后端返回空")
        self._record("panel", prompt, True, int((time.time() - started) * 1000), len(data))
        self._freeze_face()
        return self._json({
            "code": 0,
            "data": {
                "image": "data:image/png;base64," + base64.b64encode(data).decode(),
                "bytes": len(data),
                "ms": int((time.time() - started) * 1000),
                "prompt": final_prompt,
            },
        })

    def _record(self, uid, prompt, ok, ms, size):
        self._calls_total += 1
        try:
            self._history.append({
                "ts": int(time.time()),
                "time": time.strftime("%m-%d %H:%M:%S"),
                "uid": str(uid or ""),
                "prompt": str(prompt or "")[:80],
                "ok": bool(ok),
                "ms": int(ms),
                "bytes": int(size),
            })
        except Exception:
            pass

    def _record_memory(self, prompt, detail=""):
        """把「画了一张图」写进记忆库的记录页；找不到终端/记忆就静默跳过。"""
        companion = self._companion()
        record = getattr(companion, "_record", None)
        if not callable(record):
            return
        try:
            text = str(prompt or "").strip()
            title = "画了一张图" + ("：" + text[:40] if text else "")
            record("draw", title, str(detail or text)[:300], "", 0)
        except Exception as exc:
            logger.debug("[amo_image] 写记忆记录失败: %s" % exc)

    # ---------- 发送 ----------

    def _result(self, event, data: bytes, prefix: str = ""):
        """优先 chain_result（一句话 + 图），失败退回临时文件 + image_result。"""
        text = str(prefix or "").strip()
        try:
            chain = []
            if self._bool("quote_in_group", True) and self._is_group(event):
                mid = getattr(getattr(event, "message_obj", None), "message_id", None)
                if mid:
                    chain.append(Reply(id=mid))
            if text:
                chain.append(Plain(text=text))
            chain.append(Image.fromBytes(data))
            return event.chain_result(chain)
        except Exception as exc:
            logger.debug("[amo_image] chain_result 不可用，改用临时文件: %s" % exc)
        handle, path = tempfile.mkstemp(prefix="amo_image_", suffix=".png")
        try:
            os.write(handle, data)
        finally:
            os.close(handle)
        return event.image_result(path)

