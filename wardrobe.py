# -*- coding: utf-8 -*-
"""服装库：他自己给她添的衣服。

日程配装不再随机，而是从这份库里按场景挑；库是空的才回落到内置兜底。

**存储归记忆库**（Astr_Amo_data 的 ``wardrobe`` 表，3.0.9 起）：
- 启动时 ``refresh()`` 拉一份到内存快照，读（挑衣服/面板）都走快照，不阻塞；
- 写（买衣服/改/删）是异步落库；记忆库不在就报错，不再退回本地文件（2026-11-15）；
- 搭配规则（场景、JK 硬配对、按天挑）**留在终端**——终端是唯一大脑，记忆库只管存。

每条：id / name / scenes / gender / slot / enabled / note / created。
"""

from __future__ import annotations

import hashlib
import os
import re
import threading
import time
import uuid
import zlib

# 场景标签：和 outfit_engine 的 scene 一一对应
SCENES = ("work", "home", "casual", "out", "formal", "sport", "sleep", "beach")

#: 固定搭配：某些槽位只能和特定的槽位一起出现，别的都不能配
SLOT_EXCLUSIVE = {
    # JK 衬衣只配 JK 格裙，绝不配裤子/裙子
    "jk_shirt": {"jk_skirt"},
    # JK 格裙只配 JK 衬衣，不配普通上衣
    "jk_skirt": {"jk_shirt"},
    # 连衣裙独占，不能叠裤子/上衣（外套另说，现在没有外套槽）
    "dress": set(),
}


def pair_ok(slots) -> bool:
    """判断一套搭配在规则上成不成立（只看槽位，不看具体衣服）。"""
    have = set(str(slot or "") for slot in (slots or []) if slot)
    for slot in list(have):
        need = SLOT_EXCLUSIVE.get(slot)
        if need is None:
            continue
        # 有独占规则：允许的搭档之外，不许出现别的衣服槽位
        allowed = need | {slot}
        extra = {x for x in have if x not in allowed}
        # 袜子/鞋是任何搭配都能穿的，不算冲突
        extra -= {"socks", "shoes", "accessory"}
        if extra:
            return False
    return True

SLOTS = ("top", "bottom", "dress", "jk_skirt", "jk_shirt", "socks", "shoes", "accessory")
SLOT_LABELS = {"top": "上衣", "bottom": "裤子", "dress": "裙子", "jk_skirt": "JK 格裙",
               "jk_shirt": "JK 衬衣", "socks": "袜子", "shoes": "鞋", "accessory": "配饰"}

SCENE_LABELS = {
    "work": "上班",
    "home": "在家",
    "casual": "日常",
    "out": "出门",
    "formal": "正式",
    "sport": "运动",
    "sleep": "睡觉",
    "beach": "海边",
}

# 没有显式标签时按名字猜场景；猜不到就进「日常 + 出门」
SCENE_HINTS = (
    (("睡衣", "睡裙", "家居", "居家", "棉拖"), ("sleep", "home")),
    (("泳", "比基尼"), ("beach",)),
    (("西装", "礼服", "套装", "衬衫配", "正装"), ("work", "formal")),
    (("运动", "速干", "跑鞋", "瑜伽", "健身"), ("sport",)),
    (("卫衣", "牛仔裤", "t恤", "T 恤", "外套", "针织", "毛衣", "开衫", "风衣", "夹克"),
     ("casual", "out")),
    (("连衣裙", "半身裙", "裙", "短裤", "阔腿裤"), ("casual", "out")),
)

MIN_NAME = 2
MAX_NAME = 40
MAX_ITEMS = 200

#: 内置衣柜 30 套：10 汉服（全抹胸）+ 10 JK + 10 私密（白肚兜+白内裤）。
#: 配色只走清透系：桃粉 / 薄荷绿 / 天蓝白 / 月白 / 杏白 / 鹅黄 / 藕荷 / 樱粉，不要青灰重色。
HANFU_JK_SETS = (
    {"set": "汉服·桃夭", "kind": "汉服", "style": "唐制·抹胸·桃花粉",
     "scenes": ('casual', 'out', 'formal'),
     "pieces": (('桃花粉缎面抹胸·淡金滚边', 'top'), ('月白齐胸裙·桃花折枝', 'bottom'), ('樱粉披帛', 'accessory'), ('绣花弓鞋', 'shoes'))},
    {"set": "汉服·薄荷", "kind": "汉服", "style": "宋制·抹胸·薄荷绿",
     "scenes": ('work', 'casual', 'out'),
     "pieces": (('薄荷绿抹胸·银线细边', 'top'), ('月白百迭裙·水波暗花', 'bottom'), ('薄荷薄纱披帛', 'accessory'), ('素缎绣鞋', 'shoes'))},
    {"set": "汉服·晴空", "kind": "汉服", "style": "唐制·抹胸·天蓝白",
     "scenes": ('casual', 'out', 'formal'),
     "pieces": (('天蓝白抹胸·白色滚边', 'top'), ('月白齐胸裙·云纹', 'bottom'), ('浅蓝薄纱披帛', 'accessory'), ('浅蓝绣履', 'shoes'))},
    {"set": "汉服·月白", "kind": "汉服", "style": "宋制·抹胸·月白",
     "scenes": ('work', 'casual', 'out'),
     "pieces": (('月白缎面抹胸·素面', 'top'), ('月白纱裙·折枝梅', 'bottom'), ('同色薄纱披帛', 'accessory'), ('白玉簪', 'accessory'))},
    {"set": "汉服·藕荷", "kind": "汉服", "style": "明制·抹胸·藕荷",
     "scenes": ('casual', 'out', 'formal'),
     "pieces": (('藕荷缎面抹胸', 'top'), ('月白马面裙·暗织花', 'bottom'), ('藕荷披帛', 'accessory'), ('珍珠发簪', 'accessory'))},
    {"set": "汉服·杏白", "kind": "汉服", "style": "唐制·抹胸·杏白",
     "scenes": ('casual', 'out', 'home'),
     "pieces": (('杏白棉麻抹胸', 'top'), ('浅杏细褶裙', 'bottom'), ('米白披帛', 'accessory'), ('木簪', 'accessory'))},
    {"set": "汉服·鹅黄", "kind": "汉服", "style": "唐制·抹胸·鹅黄",
     "scenes": ('casual', 'out', 'formal'),
     "pieces": (('鹅黄抹胸·高腰曳地', 'top'), ('浅杏裙·缠枝杏花', 'bottom'), ('米金薄纱披帛', 'accessory'), ('奶白绣鞋', 'shoes'))},
    {"set": "汉服·樱粉", "kind": "汉服", "style": "宋制·抹胸·樱粉",
     "scenes": ('work', 'casual', 'out'),
     "pieces": (('樱粉暗纹抹胸', 'top'), ('米白细褶裙', 'bottom'), ('樱粉薄纱披帛', 'accessory'), ('珍珠发夹', 'accessory'))},
    {"set": "汉服·水色", "kind": "汉服", "style": "明制·抹胸·水蓝白",
     "scenes": ('casual', 'out', 'formal'),
     "pieces": (('水蓝白抹胸·细银回纹', 'top'), ('白练百迭裙', 'bottom'), ('青白薄纱披帛', 'accessory'), ('银簪', 'accessory'))},
    {"set": "汉服·蜜桃", "kind": "汉服", "style": "唐制·抹胸·蜜桃粉",
     "scenes": ('casual', 'out', 'formal'),
     "pieces": (('蜜桃粉抹胸·银线海棠', 'top'), ('白粉渐变齐胸裙', 'bottom'), ('桃色披帛', 'accessory'), ('金步摇', 'accessory'))},
    {"set": "JK·初雪", "kind": "JK", "style": "水手服·白",
     "scenes": ('casual', 'out'),
     "pieces": (('白衬衫+白水手领·二本淡灰', 'jk_shirt'), ('白色24褶箱褶裙', 'jk_skirt'), ('白短袜', 'socks'), ('白色乐福鞋', 'shoes'), ('淡灰蝴蝶结', 'accessory'))},
    {"set": "JK·樱花", "kind": "JK", "style": "水手服·樱粉",
     "scenes": ('casual', 'out'),
     "pieces": (('粉白衬衫+樱粉水手领·二本白线', 'jk_shirt'), ('樱粉24褶裙', 'jk_skirt'), ('白色中筒袜', 'socks'), ('米色制服鞋', 'shoes'), ('粉领巾', 'accessory'))},
    {"set": "JK·薄荷", "kind": "JK", "style": "水手服·薄荷绿",
     "scenes": ('casual', 'out'),
     "pieces": (('薄荷绿上衣+一本白线', 'jk_shirt'), ('薄荷24褶裙', 'jk_skirt'), ('白短袜', 'socks'), ('白色帆布鞋', 'shoes'), ('薄荷领结', 'accessory'))},
    {"set": "JK·天蓝", "kind": "JK", "style": "水手服·天蓝白",
     "scenes": ('casual', 'out'),
     "pieces": (('天蓝白上衣+二本白线', 'jk_shirt'), ('浅蓝浅格28褶裙', 'jk_skirt'), ('白长袜', 'socks'), ('浅蓝乐福鞋', 'shoes'), ('浅蓝领绳', 'accessory'))},
    {"set": "JK·藕粉", "kind": "JK", "style": "衬衫格裙·藕粉",
     "scenes": ('casual', 'out', 'work'),
     "pieces": (('藕粉衬衫+白领', 'jk_shirt'), ('藕粉格24褶裙', 'jk_skirt'), ('粉白短袜', 'socks'), ('白色乐福鞋', 'shoes'), ('粉色发带', 'accessory'))},
    {"set": "JK·奶油", "kind": "JK", "style": "针织·杏白",
     "scenes": ('casual', 'out', 'work'),
     "pieces": (('杏白针织+奶白水手领', 'jk_shirt'), ('浅杏24褶裙', 'jk_skirt'), ('奶白中筒袜', 'socks'), ('棕色小皮鞋', 'shoes'), ('格纹领巾', 'accessory'))},
    {"set": "JK·柠檬", "kind": "JK", "style": "针织·鹅黄",
     "scenes": ('casual', 'out'),
     "pieces": (('鹅黄针织+奶白水手领·三本', 'jk_shirt'), ('米黄20褶裙', 'jk_skirt'), ('奶白短袜', 'socks'), ('棕色乐福鞋', 'shoes'), ('米黄领结', 'accessory'))},
    {"set": "JK·蜜桃", "kind": "JK", "style": "衬衫格裙·蜜桃粉",
     "scenes": ('casual', 'out'),
     "pieces": (('蜜桃衬衫+白领', 'jk_shirt'), ('蜜桃格20褶裙', 'jk_skirt'), ('米白短袜', 'socks'), ('白色制服鞋', 'shoes'), ('蜜桃领结', 'accessory'))},
    {"set": "JK·海盐", "kind": "JK", "style": "水手服·蓝白",
     "scenes": ('casual', 'out', 'work'),
     "pieces": (('蓝白水手服+二本白线', 'jk_shirt'), ('海盐蓝24褶裙', 'jk_skirt'), ('白中筒袜', 'socks'), ('白帆布鞋', 'shoes'), ('蓝白领巾', 'accessory'))},
    {"set": "JK·樱雪", "kind": "JK", "style": "衬衫格裙·粉白",
     "scenes": ('casual', 'out', 'work'),
     "pieces": (('白衬衫+米白水手领·二本樱线', 'jk_shirt'), ('粉白格24褶裙', 'jk_skirt'), ('白短袜', 'socks'), ('米白乐福鞋', 'shoes'), ('樱粉领带', 'accessory'))},
    {"set": "私密·素衾", "kind": "私密", "style": "白色肚兜·素缎｜内裤·纯棉三角｜白丝·薄透连裤",
     "scenes": ('sleep',),
     "pieces": (('白色肚兜·素缎（系颈系腰·露背）', 'top'), ('白色内裤·纯棉三角', 'bottom'), ('白色丝袜·薄透连裤', 'socks'))},
    {"set": "私密·白绫", "kind": "私密", "style": "白色肚兜·暗纹缎｜内裤·高腰｜白丝·大腿袜",
     "scenes": ('sleep',),
     "pieces": (('白色肚兜·暗纹缎（系颈系腰·露背）', 'top'), ('白色内裤·高腰', 'bottom'), ('白色丝袜·大腿袜·蕾丝口', 'socks'))},
    {"set": "私密·雪团", "kind": "私密", "style": "白色肚兜·绒边｜内裤·蕾丝边｜白丝·中筒",
     "scenes": ('sleep',),
     "pieces": (('白色肚兜·绒边（系颈系腰·露背）', 'top'), ('白色内裤·蕾丝边', 'bottom'), ('白色丝袜·中筒·绒口', 'socks'))},
    {"set": "私密·月魄", "kind": "私密", "style": "白色肚兜·月牙绣｜内裤·三角｜白丝·连裤",
     "scenes": ('sleep',),
     "pieces": (('白色肚兜·月牙绣（系颈系腰·露背）', 'top'), ('白色内裤·三角', 'bottom'), ('白色丝袜·连裤·哑光', 'socks'))},
    {"set": "私密·云孙", "kind": "私密", "style": "白色肚兜·云纹｜内裤·平角｜白丝·踩脚",
     "scenes": ('sleep',),
     "pieces": (('白色肚兜·云纹（系颈系腰·露背）', 'top'), ('白色内裤·平角', 'bottom'), ('白色丝袜·踩脚', 'socks'))},
    {"set": "私密·玉钩", "kind": "私密", "style": "白色肚兜·系带｜内裤·系带｜白丝·吊带",
     "scenes": ('sleep',),
     "pieces": (('白色肚兜·系带（系颈系腰·露背）', 'top'), ('白色内裤·系带', 'bottom'), ('白色丝袜·吊带', 'socks'))},
    {"set": "私密·霜练", "kind": "私密", "style": "白色肚兜·缎面｜内裤·缎面｜白丝·珠光",
     "scenes": ('sleep',),
     "pieces": (('白色肚兜·缎面（系颈系腰·露背）', 'top'), ('白色内裤·缎面', 'bottom'), ('白色丝袜·珠光', 'socks'))},
    {"set": "私密·冰绡", "kind": "私密", "style": "白色肚兜·纱质｜内裤·纱边｜白丝·网纱",
     "scenes": ('sleep',),
     "pieces": (('白色肚兜·纱质（系颈系腰·露背）', 'top'), ('白色内裤·纱边', 'bottom'), ('白色丝袜·网纱', 'socks'))},
    {"set": "私密·雪绡", "kind": "私密", "style": "白色肚兜·绣兰｜内裤·绣兰｜白丝·提花",
     "scenes": ('sleep',),
     "pieces": (('白色肚兜·绣兰（系颈系腰·露背）', 'top'), ('白色内裤·绣兰', 'bottom'), ('白色丝袜·提花', 'socks'))},
    {"set": "私密·素纱", "kind": "私密", "style": "白色肚兜·素纱｜内裤·素纱｜白丝·超薄",
     "scenes": ('sleep',),
     "pieces": (('白色肚兜·素纱（系颈系腰·露背）', 'top'), ('白色内裤·素纱', 'bottom'), ('白色丝袜·超薄', 'socks'))},
)


def hanfu_jk_items() -> list[dict]:
    """内置衣柜条目：汉服 + JK，一套一套的（名字「套名｜件名」，配装按套名归组）。"""
    items = []
    now = time.time()
    for spec in HANFU_JK_SETS:
        for piece, slot in spec["pieces"]:
            name = "%s｜%s" % (spec["set"], piece)
            items.append({
                "id": "w" + hashlib.md5(name.encode("utf-8")).hexdigest()[:9],
                "name": name,
                "slot": slot,
                "scenes": list(spec["scenes"]),
                "gender": "女",
                "enabled": True,
                "note": "%s·%s" % (spec["kind"], spec["style"]),
                "created": now,
            })
            now += 0.001
    return items[:MAX_ITEMS]


def scenes_for_slot(slot: str, style: str = "") -> list[str]:
    """分件 → 适合的场景（JK/裙子偏校园日常，鞋袜配饰全天可用）。"""
    slot = str(slot or "")
    style = str(style or "")
    if slot in ("shoes", "socks", "accessory"):
        return ["work", "home", "casual", "out", "formal", "sport"]
    if slot.startswith("jk") or "校园" in style:
        return ["casual", "out"]
    if slot == "dress":
        return ["out", "formal", "casual"]
    return ["work", "casual", "out", "home"]


def build_items_from_catalog(rows) -> list[dict]:
    """把市场目录的服装行转成衣柜条目（带 slot / scenes）。"""
    items = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = clean_name(row.get("name"))
        slot = str(row.get("slot") or "").strip()
        if not name or slot not in SLOTS:
            continue
        items.append({
            "id": uuid.uuid4().hex[:10],
            "name": name,
            "slot": slot,
            "scenes": scenes_for_slot(slot, row.get("style")),
            "gender": "女",
            "enabled": True,
            "note": "市场目录",
            "created": time.time(),
        })
    return items[:MAX_ITEMS]


def clean_name(text):
    value = re.sub(r"\s+", " ", str(text or "")).strip()
    value = value.strip("，,。.；;：:、!！?？\"'“”‘’")
    return value[:MAX_NAME]


def guess_scenes(name):
    lowered = str(name or "").lower()
    for words, scenes in SCENE_HINTS:
        if any(word in lowered for word in words):
            return list(scenes)
    return ["casual", "out"]


class Wardrobe:
    def __init__(self, plugin):
        self.plugin = plugin
        self._lock = threading.RLock()
        self._items = []
        self._loaded = False
        # 衣柜只存记忆库（wardrobe 表）；本地 wardrobe.json 已废弃（2026-11-15）。

    def _debug(self, text):
        try:
            self.plugin.logger.debug("[amo] %s" % text)
        except Exception:
            pass

    def _error(self, text):
        """衣柜只有记忆库一个存储，写不进去必须吵出来。"""
        try:
            self.plugin.logger.error("[amo] %s" % text)
        except Exception:
            pass

    # ---------- 存储：只有记忆库（旧 JSON 兜底已删） ----------

    @staticmethod
    def _normalize(item):
        """把一条记录洗成内部结构；名字不合法就返回 None。"""
        if not isinstance(item, dict):
            return None
        name = clean_name(item.get("name"))
        if not name:
            return None
        scenes = [scene for scene in (item.get("scenes") or []) if scene in SCENES]
        return {
            "id": str(item.get("id") or ("w" + uuid.uuid4().hex[:10])),
            "name": name,
            "slot": str(item.get("slot") or ""),
            "scenes": scenes or guess_scenes(name),
            "gender": str(item.get("gender") or "通用"),
            "enabled": bool(item.get("enabled", True)),
            "note": str(item.get("note") or "")[:120],
            "created": float(item.get("created") or time.time()),
        }

    def _bot_id(self):
        """衣柜和终端其它数据必须用同一个 bot_id，否则会写成两套孤岛。"""
        try:
            return str(self.plugin._data_bot_id() or "")
        except Exception:
            return ""

    async def _data(self, name, *args):
        """调记忆库；没装/超时返回 None（调用方据此回退）。"""
        func = getattr(self.plugin, "_data_call", None)
        if not callable(func):
            return None
        try:
            return await func(name, *args)
        except Exception as exc:
            self._debug("记忆库 %s 失败: %s" % (name, exc))
            return None

    async def refresh(self, force=False):
        """从记忆库拉一份到内存快照；记忆库是空的就先把旧 JSON 灌过去。"""
        if self._loaded and not force:
            return self._items
        rows = await self._data("wardrobe_rows", self._bot_id(), False)
        if not isinstance(rows, list):
            # 记忆库是这个系统的一部分，读不到就不假装有衣服：留错误日志，下次再拉。
            self._error("衣柜读不到记忆库（wardrobe_rows），本次沿用内存快照 %d 件" % len(self._items))
            return self._items
        items = [item for item in (self._normalize(row) for row in rows) if item]
        if not items:
            # 空 ≠ 已经加载好了：启动时数据插件常还没连上，拉回来就是空的。
            # 以前这里也置 _loaded=True，之后每次 refresh() 都直接返回空列表，
            # 睡觉就只能一直兜底「睡衣一套」——衣柜里明明有汉服寝衣。
            self._error("记忆库衣柜是空的（0 件），下次继续重试")
            with self._lock:
                if not self._items:
                    self._loaded = False
            return self._items
        with self._lock:
            self._items = items
        self._loaded = True
        return self._items

    async def _persist(self, item):
        ok = await self._data("wardrobe_save", self._bot_id(), dict(item))
        if not ok:
            self._error("衣柜写入记忆库失败：%s" % (item.get("name") or ""))

    async def _persist_all(self):
        rows = [dict(item) for item in self._items]
        ok = await self._data("wardrobe_replace_all", self._bot_id(), rows)
        if not ok:
            self._error("衣柜整库写入记忆库失败（%d 件）" % len(rows))

    def _ensure(self):
        """同步读用的是内存快照（refresh() 负责从记忆库拉）。"""
        return self._items

    # ---------- 读（同步，走内存快照） ----------

    def items(self, only_enabled=False):
        with self._lock:
            items = [dict(item) for item in self._ensure()]
        if only_enabled:
            items = [item for item in items if item.get("enabled", True)]
        return items

    def count(self):
        return len(self.items(only_enabled=True))

    def find(self, name):
        target = clean_name(name)
        if not target:
            return {}
        for item in self.items():
            if item["name"] == target:
                return item
        return {}

    # ---------- 写（异步，落记忆库） ----------

    async def replace_all(self, items):
        """整库替换（按市场目录重建衣柜时用）；返回替换后的条数。"""
        rows = []
        for row in items or []:
            item = self._normalize(row)
            if not item:
                continue
            if row.get("gender") is None:
                item["gender"] = "女"
            rows.append(item)
        rows = rows[:MAX_ITEMS]
        with self._lock:
            self._items = rows
            self._loaded = True
        await self._persist_all()
        return len(rows)

    async def add(self, name, scenes=None, gender="通用", note="", slot=""):
        name = clean_name(name)
        if len(name) < MIN_NAME:
            return {}
        scenes = [scene for scene in (scenes or []) if scene in SCENES]
        with self._lock:
            rows = self._ensure()
            for item in rows:
                if item["name"] == name:
                    # 同名直接更新，避免库被同名刷爆
                    if scenes:
                        item["scenes"] = scenes
                    if gender in ("女", "男", "通用"):
                        item["gender"] = gender
                    if note:
                        item["note"] = str(note)[:120]
                    item["enabled"] = True
                    fresh = dict(item)
                    break
            else:
                item = {
                    "id": "w" + uuid.uuid4().hex[:10],
                    "name": name,
                    "slot": str(slot or ""),
                    "scenes": scenes or guess_scenes(name),
                    "gender": gender if gender in ("女", "男", "通用") else "通用",
                    "enabled": True,
                    "note": str(note or "")[:120],
                    "created": time.time(),
                }
                rows.append(item)
                del rows[:-MAX_ITEMS]
                fresh = dict(item)
        await self._persist(fresh)
        return fresh

    async def update(self, item_id, **fields):
        with self._lock:
            fresh = {}
            for item in self._ensure():
                if item["id"] != str(item_id):
                    continue
                if "name" in fields:
                    name = clean_name(fields["name"])
                    if len(name) >= MIN_NAME:
                        item["name"] = name
                if "scenes" in fields:
                    scenes = [scene for scene in (fields["scenes"] or []) if scene in SCENES]
                    if scenes:
                        item["scenes"] = scenes
                if "gender" in fields and fields["gender"] in ("女", "男", "通用"):
                    item["gender"] = fields["gender"]
                if "enabled" in fields:
                    item["enabled"] = bool(fields["enabled"])
                if "note" in fields:
                    item["note"] = str(fields["note"] or "")[:120]
                fresh = dict(item)
                break
        if not fresh:
            return {}
        await self._persist(fresh)
        return fresh

    async def delete(self, item_id):
        with self._lock:
            rows = self._ensure()
            before = len(rows)
            rows[:] = [item for item in rows if item["id"] != str(item_id)]
            removed = len(rows) != before
        if not removed:
            return False
        ok = await self._data("wardrobe_delete", self._bot_id(), str(item_id))
        if not ok:
            self._error("衣柜删除没写进记忆库：%s" % item_id)
        return True

    async def clear(self):
        with self._lock:
            self._items = []
            self._loaded = True
        ok = await self._data("wardrobe_clear", self._bot_id())
        if not ok:
            self._error("衣柜清空没写进记忆库")

    # ---------- 挑选（同步，纯规则） ----------

    def pool(self, gender, scene):
        """这一场景能穿的衣服；性别不符的跳过（通用都算）。"""
        out = []
        for item in self.items(only_enabled=True):
            if item.get("gender") in ("女", "男") and gender in ("女", "男") and item["gender"] != gender:
                continue
            scenes = item.get("scenes") or []
            if scene and scene not in scenes:
                continue
            out.append(item["name"])
        return out

    def pick(self, gender, scene, day, key=""):
        """同一天同一场景固定一套，重启也不变。"""
        pool = self.pool(gender, scene)
        if not pool:
            return ""
        seed = ("%s|%s|%s" % (day, scene, key)).encode("utf-8")
        return pool[zlib.crc32(seed) % len(pool)]

    def match_text(self, text):
        """从一句话里认出「哪件衣服」；库里有才算。"""
        body = str(text or "")
        if not body:
            return {}
        hits = []
        for item in self.items(only_enabled=True):
            name = item["name"]
            if name and name in body:
                hits.append(item)
                continue
            # 「那条红裙子」：按名字里的关键词松匹配
            tokens = [token for token in re.split(r"[，,、\s]+", name) if len(token) >= 2]
            if any(token in body for token in tokens):
                hits.append(item)
        if not hits:
            return {}
        hits.sort(key=lambda item: len(item["name"]), reverse=True)
        return hits[0]

    def panel_data(self):
        items = self.items()
        return {
            "path": "记忆库 wardrobe 表",
            "backend": "记忆库" if self._loaded else "记忆库（未同步）",
            "count": len([item for item in items if item.get("enabled", True)]),
            "items": items,
            "scenes": [{"key": key, "label": SCENE_LABELS[key]} for key in SCENES],
        }
