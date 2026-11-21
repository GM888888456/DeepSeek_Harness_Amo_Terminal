# -*- coding: utf-8 -*-
"""日程穿搭：给每一段日程配一套衣服。

规则很短：

- 优先从服装库挑（他在面板里添的衣服），库是空的才用内置兜底；
- 按角色性别挑衣服（`outfit_gender`：自动 / 女 / 男，自动时从人格判断）；
- 按场景挑：睡觉/居家/上班/通勤/出门/运动/正式/海边；
- 同一段日程+同一天结果固定（crc32），重启不变，不会一小时换三套；
- **硬约束**：泳装只在海边/泳池/温泉出现，睡衣/家居服不出门；
  场景和服装对不上时退回日常装，宁可普通也不穿泳装去公司。

生成完写进日程条目的 `outfit` 字段，面板、`schedule_view`、生图插件都读它。
"""

from __future__ import annotations

try:
    from astrbot.api import logger
except Exception:  # pragma: no cover
    import logging
    logger = logging.getLogger(__name__)

import random

import re
import time
import zlib

try:  # 固定搭配规则在衣柜里定义
    from .wardrobe import pair_ok
except Exception:  # pragma: no cover - 单文件加载时的兜底
    try:
        from wardrobe import pair_ok
    except Exception:
        def pair_ok(slots):
            return True

# 日程兜底（衣柜读不到、市场也没开门时用）：只保留这三套。
# 用户 2026-11-14 定：睡衣一套、西装（男女通用）一套、休闲服一套。
FALLBACK_SETS = {
    "sleep": "睡衣一套",
    "home": "休闲服一套",
    "work": "西装套装（男女通用）",
    "formal": "西装套装（男女通用）",
    "commute": "休闲服一套",
    "casual": "休闲服一套",
    "out": "休闲服一套",
    "sport": "休闲服一套",
    "beach": "休闲服一套",
}

# 换装时按风格找套系（「换jk」→ JK 那几套，「换汉服」→ 汉服那几套）
STYLE_CAMPS = (
    ("JK", ("jk", "j k", "制服", "水手", "学生装", "百褶", "格裙",
            "白丝", "黑丝", "过膝袜", "中筒袜", "白袜")),
    ("汉服", ("汉服", "古装", "襦裙", "马面", "褙子", "曲裾", "圆领袍", "披帛")),
)
GENERIC_STYLE_WORDS = ("衣服", "一套", "一身", "一件", "换", "随便", "你挑", "都行")

SWIM_WORDS = ("泳装", "泳衣", "泳裤", "比基尼")
HOME_WEAR_WORDS = ("睡衣", "家居服", "睡裙")
BEACH_PLACES = ("海边", "沙滩", "泳池", "游泳馆", "温泉", "海滩", "水上乐园")
BEACH_ACTIVITIES = ("游泳", "泡温泉", "玩水", "潜水", "冲浪")
HOME_PLACE_WORDS = ("家", "小窝", "公寓", "住处", "宿舍", "房间")

#: 回家以后真的换掉外出那套，只认这几件事。
#: 「到家瘫一会儿」「开车回家」不算——2026-11-15 报的 bug：出门 JK，到家/在车上一下变汉服。
HOME_CHANGE_WORDS = ("洗澡", "冲个澡", "换家居服", "换上家居服", "换睡衣", "换上睡衣",
                     "换寝衣", "换上寝衣", "换睡裙", "居家服")


# 贴身穿的 / 睡觉穿的：在外面不能换，换了也不能说
PRIVATE_WEAR_WORDS = (
    "私密", "肚兜", "旗袍睡", "睡衣", "睡裙", "睡袍", "寝衣", "家居服", "内衣", "文胸", "胸罩", "内裤", "吊带",
    "丝袜", "白丝", "比基尼", "泳装", "泳衣", "泳裤", "浴巾", "浴袍",
)

#: 出现在**地点**里就算不在家：私密衣服和私密照一律不许
AWAY_WORDS = ("公司", "办公室", "单位", "工位", "学校", "店里")
HOME_PLACES = ("家", "小窝", "公寓", "住处", "宿舍", "房间", "卧室")


def is_private_wear(name):
    return any(word in str(name or "") for word in PRIVATE_WEAR_WORDS)


def at_home(activity):
    """按日程判断她此刻是不是在家（含卧室/宿舍这类）。"""
    activity = activity or {}
    place = str(activity.get("place") or "")
    zone = str(activity.get("zone") or "")
    if zone in ("home", "bedroom"):
        return True
    return any(word in place for word in HOME_PLACES)


def private_ok(activity):
    """私密衣服/私密照的硬闸：**在家就能穿**，只按地点判。

    2026-11-21 她在家那格写着「公司电话就打来了」，那是叙述不是地点；
    当时按文字判成在公司，结果在家也换不了私密。现在只看 place/zone：
    地点在家 → 能穿；地点是公司/路上/商场 → 不能穿（出门那几格也不写私密）。
    """
    activity = activity or {}
    place = str(activity.get("place") or "")
    if any(word in place for word in AWAY_WORDS):
        return False
    return at_home(activity)


class OutfitEngine:
    """按性别 + 场景 + 日期给日程配衣服。"""

    def __init__(self, plugin):
        self.plugin = plugin

    # ---------- 性别 ----------

    def enabled(self):
        try:
            return bool(self.plugin.cfg_bool("outfit_enable", True))
        except Exception:
            return True

    def gender(self, persona=""):
        value = ""
        try:
            value = str(self.plugin.cfg_str("outfit_gender", "自动") or "自动").strip()
        except Exception:
            value = "自动"
        if value in ("女", "女生", "female"):
            return "女"
        if value in ("男", "男生", "male"):
            return "男"
        return self._guess_gender(persona)

    @staticmethod
    def _guess_gender(text):
        raw = str(text or "")
        female = sum(raw.count(word) for word in
                     ("女孩", "女生", "少女", "女性", "姑娘", "妻子", "老婆", "她"))
        male = sum(raw.count(word) for word in ("男孩", "男生", "少年", "男性"))
        return "男" if male > female else "女"

    # ---------- 场景 ----------

    @staticmethod
    def scene_of(item):
        activity = str(item.get("activity") or "")
        place = str(item.get("place") or "")
        category = str(item.get("category") or "")
        text = activity + place
        # 日程里标了 swim（泳池/海边那种格子）就一定是泳装场景：新引擎的骨架会带这个
        # 布尔值，不看它就会出现「日程在游泳、照片穿西装」。
        if item.get("swim") is True:
            return "beach"
        if category == "sleep" or "睡觉" in activity or "睡衣" in activity or "睡裙" in activity:
            return "sleep"
        if (any(word in place for word in BEACH_PLACES)
                or any(word in activity for word in BEACH_ACTIVITIES)):
            return "beach"
        if category == "sport" or any(word in text for word in ("健身", "跑步", "运动", "瑜伽")):
            return "sport"
        if category == "work" or any(word in text for word in ("上班", "公司", "开会", "办公")):
            return "work"
        if any(word in text for word in ("婚礼", "宴会", "年会", "正式", "面试")):
            return "formal"
        if category in ("play", "social") or any(
                word in text for word in ("逛街", "商场", "旅", "景点", "咖啡", "公园", "约会")):
            return "out"
        if category == "commute" or any(word in text for word in ("通勤", "地铁", "开车去", "回家路上")):
            return "commute"
        if str(item.get("zone") or "") in ("home", "bedroom"):
            return "home"
        # 地点空着不等于在家：出行那格没写地点时，以前会被当成「回家」换上家居服
        if place and any(word in place for word in HOME_PLACE_WORDS):
            return "home"
        return "casual"

    def wardrobe(self):
        return getattr(self.plugin, "wardrobe", None)

    def _pool(self, gender, scene):
        """先看服装库；库空或该场景没衣服，才回落到内置兜底。"""
        store = self.wardrobe()
        if store is not None:
            try:
                names = store.pool(gender, scene)
                if names:
                    return tuple(names)
            except Exception:
                pass
        # 衣柜读不到时只兜这三套，不再随机编现代衣服
        return (FALLBACK_SETS.get(scene) or FALLBACK_SETS["casual"],)

    def _pick(self, gender, scene, day, key=""):
        """同一段（同场景+同活动+同地点）在同一天固定穿同一套，小时展开不会一小时一换。"""
        pool = self._pool(gender, scene)
        seed = ("%s|%s|%s|%s" % (day, scene, key, gender)).encode("utf-8")
        return pool[zlib.crc32(seed) % len(pool)]

    def _whole_set(self, outfit):
        """一套衣服只认整套：只剩一件时按套名补回来。

        2026-11-16：日程里出现「只写着对襟褙子」的一格，出图时模型只能自己补，
        于是前一张交领、后一张抹胸。这里按套名补齐；补不上就原样返回
        （宁可只有一件，也不能编不存在的衣服）。
        """
        text = str(outfit or "").strip()
        if not text:
            return ""
        pieces = [item.strip() for item in re.split(r"[，,]", text) if item.strip()]
        heads = {item.split("｜", 1)[0].strip() for item in pieces if "｜" in item}
        if len(heads) != 1 or len(pieces) >= 3:
            return text
        full = ""
        try:
            full = str(self.compose_set(next(iter(heads))) or "").strip()
        except Exception:
            full = ""
        return full or text

    @staticmethod
    def _safe(outfit, scene):
        """硬约束：泳装只下海，睡衣不出门。"""
        if any(word in outfit for word in SWIM_WORDS) and scene != "beach":
            return ""
        if any(word in outfit for word in HOME_WEAR_WORDS) and scene not in ("sleep", "home"):
            return ""
        return outfit

    CHANGE_WORDS = ("换衣", "换装", "换上", "换一身", "洗澡")
    # 只有这种「不得不换」才算数；普通换衣服不换造型
    EMERGENCY_WORDS = ("淋湿", "打湿", "湿透", "弄脏", "洒了", "糊了", "摔倒",
                       "泥", "雨太大", "淋雨", "脏了")

    def day_scene(self, items):
        """今天的主场景：上班日按上班，出去玩按出门，其余日常。"""
        scenes = []
        for item in items or []:
            scene = self.scene_of(item)
            if scene not in ("sleep",):
                scenes.append(scene)
        for scene in ("work", "formal", "sport", "out", "commute"):
            if scene in scenes:
                return scene
        if scenes and all(scene == "home" for scene in scenes):
            return "home"
        return "casual" if scenes else "home"

    # ---------- 手动换装 ----------

    @staticmethod
    def _override_key(day):
        return "outfit_override:" + str(day)

    def _known_wear(self, name) -> bool:
        """这句穿搭在衣柜里还有吗。

        2026-11-21 事故：她删了「私密」10 套，但 kv 里 `outfit_override:<day>`
        还留着那一整套，`assign()` 最后又把 override 盖回日程，于是重建多少次
        都是「白色肚兜＋内裤」。衣柜读不到（还没加载完 / 数据插件慢）时一律当「还在」，
        宁可保留也不能误清她自己选的。
        """
        text = str(name or "").strip()
        if not text:
            return False
        try:
            rows = list(self.wardrobe().items() or [])
        except Exception:
            return True
        names = {str(row.get("name") or "").strip() for row in rows
                 if str(row.get("name") or "").strip()}
        if not names:
            return True
        pieces = [piece.strip() for piece in re.split(r"[，,]", text) if piece.strip()]
        if any(piece in names for piece in pieces):
            return True
        # 件名写法可能改过：只要「套名」还认得出来就算在
        heads = {piece.split("｜", 1)[0].strip() for piece in pieces if piece}
        known = {item.split("｜", 1)[0].strip() for item in names if "｜" in item}
        return bool(heads & known)

    def override(self, day):
        """他今天让她换的那套：{"name": "...", "from": "18:00"}。

        读的时候先证伪：这套衣服已经不在衣柜里（换了衣柜 / 删了套）就当场清掉，
        不再让它盖回日程。
        """
        try:
            value = self.plugin.db.kv_get(self._override_key(day), {}) or {}
        except Exception:
            value = {}
        if not isinstance(value, dict) or not str(value.get("name") or "").strip():
            return {}
        name = str(value.get("name")).strip()
        if not self._known_wear(name):
            logger.warning("[amo] 手动换装那套已经不在衣柜里，丢弃 override：%s" % name[:50])
            try:
                self.plugin.db.kv_set(self._override_key(day), {})
            except Exception:
                pass
            return {}
        return {"name": name,
                "from": str(value.get("from") or "00:00")[:5],
                "ts": float(value.get("ts") or 0)}

    def change_outfit(self, day, name, from_hour="", note=""):
        """他让她换一套：写进今天，从这一小时开始生效，直到睡觉。

        面板上点的是「套名｜件名」里的一件；这里先按套名补成整套，
        再判私密：私密套只在家能换，外面（含「公司电话」那种家）一律拒绝。
        """
        name = str(name or "").strip()[:200]
        if not name:
            return {}
        set_name = name.split("｜", 1)[0].strip() if "｜" in name else name.strip()
        whole = ""
        try:
            whole = str(self.compose_set(set_name) or "").strip()
        except Exception:
            whole = ""
        if whole:
            name = whole
        if is_private_wear(name):
            try:
                activity = self.plugin.state.current_activity() or {}
            except Exception:
                activity = {}
            if not private_ok(activity):
                return {}
        hour = str(from_hour or time.strftime("%H:00"))[:5]
        if not re.match(r"^\d{2}:\d{2}$", hour):
            hour = time.strftime("%H:00")
        payload = {"name": name, "set": set_name, "from": hour, "ts": time.time(),
                   "note": str(note or "")[:80]}
        try:
            self.plugin.db.kv_set(self._override_key(day), payload)
        except Exception:
            pass
        return payload

    def can_change_to(self, name):
        """能不能现在换成这套。返回 (ok, 原因)。

        贴身衣物 / 睡衣在门外不能换——不然会出现「在公司穿睡衣」这种画面。
        """
        if not is_private_wear(name):
            return True, ""
        try:
            activity = self.plugin.state.current_activity() or {}
        except Exception:
            activity = {}
        if private_ok(activity):
            return True, ""
        place = str(activity.get("place") or "").strip() or "外面"
        return False, place

    def clear_override(self, day):
        try:
            self.plugin.db.kv_set(self._override_key(day), {})
        except Exception:
            pass

    def _apply_override(self, items, day):
        """把手动换的那套写回日程：从那一小时到睡觉前。

        2026-11-21：私密套（肚兜/内裤/白丝…）只写进「在家」的格。
        以前从换衣那一小时起一路盖到睡前，她在家换的私密，出门去商场还穿着。
        """
        data = self.override(day)
        if not data:
            return items
        start = self._minutes(data["from"])
        private = is_private_wear(data["name"])
        for item in items:
            if not isinstance(item, dict):
                continue
            if self.scene_of(item) == "sleep":
                if self._minutes(item.get("start")) >= start:
                    break
                continue
            if self._minutes(item.get("start")) < start:
                continue
            if private and not private_ok(item):
                # 在外面：保留 assign 写好的那套，回家再穿私密
                continue
            item["outfit"] = data["name"]
        return items

    @staticmethod
    def _minutes(text):
        try:
            hour, minute = str(text or "").split(":")[:2]
            return int(hour) * 60 + int(minute)
        except Exception:
            return 0

    def _slot_items(self):
        """衣柜里带 slot 的条目；没有就走旧的整件挑。

        注意这里必须调 `self.wardrobe()`：它是个方法，不是插件上的衣柜对象，
        写成 `self.wardrobe.items()` 一直是空列表（分件配装从来没生效过）。
        """
        try:
            store = self.wardrobe()
            rows = [row for row in (store.items() or [])
                    if row.get("slot") and row.get("enabled", True)]
        except Exception:
            rows = []
        return rows

    @staticmethod
    def _set_of(row):
        """套名：名字「汉服·长安月｜齐胸襦裙」里「｜」前面那段；没有就返回空。"""
        name = str((row or {}).get("name") or "")
        return name.split("｜", 1)[0].strip() if "｜" in name else ""

    # ---------- 套系 / 模糊匹配 ----------

    def sets(self):
        """套名 -> 这一套的所有件；市场买的单件自成一个组。"""
        groups = {}
        for row in self._slot_items():
            set_name = self._set_of(row) or str(row.get("name") or "")
            if not set_name:
                continue
            groups.setdefault(set_name, []).append(row)
        return groups

    @staticmethod
    def camp_of(set_name):
        """套名属于哪种风格：JK / 汉服 / 其他。"""
        head = str(set_name or "")
        if "JK" in head.upper() or any(word in head for word in ("制服", "水手", "学生")):
            return "JK"
        if any(word in head for word in ("汉服", "襦裙", "马面", "褙子", "曲裾", "圆领袍")):
            return "汉服"
        return "其他"

    @staticmethod
    def style_camp(text):
        """这句话说的是哪种风格：JK / 汉服 / 空（「白丝」「格裙」也算 JK）。"""
        low = str(text or "").lower().replace(" ", "")
        if not low:
            return ""
        for camp, words in STYLE_CAMPS:
            if any(str(word).lower().replace(" ", "") in low for word in words):
                return camp
        return ""

    def is_sleep_set(self, set_name):
        """这一套是不是寝衣/睡衣（「换一套衣服」默认跳过它）。"""
        for row in self.sets().get(str(set_name)) or []:
            name = str(row.get("name") or "")
            if any(word in name for word in ("寝衣", "睡裙", "睡衣", "家居服", "睡袍")):
                return True
        return False

    def current_set(self):
        """她现在身上这套的套名；单件/没有就返回空。"""
        try:
            activity = self.plugin.state.current_activity() or {}
        except Exception:
            activity = {}
        outfit = str(activity.get("outfit") or "")
        for piece in re.split(r"[，,]", outfit):
            if "｜" in piece:
                return piece.split("｜", 1)[0].strip()
        return ""

    def remember_camp(self, camp):
        """记住这次换的是哪种风格：下次只说「换一套」就同风格再挑一套。"""
        try:
            self.plugin.db.kv_set("outfit_last_camp", str(camp or ""))
        except Exception:
            pass

    def last_camp(self):
        try:
            return str(self.plugin.db.kv_get("outfit_last_camp", "") or "")
        except Exception:
            return ""

    def find_sets(self, text="", exclude=""):
        """按他说的款式在衣柜里找套系。

        「换jk」→ JK 的几套；「换汉服」→ 汉服的几套；「马面裙」→ 含这件的套；
        不说款式（空 / 换一套 / 衣服）→ 上次那种风格里再挑一套，没有就所有整套。
        """
        body = str(text or "").strip()
        low = body.lower().replace(" ", "")
        groups = self.sets()
        if not groups:
            return []
        names = list(groups)
        wants_sleep = any(word in body for word in ("睡衣", "寝衣", "睡裙", "睡袍", "家居服"))
        real = ([name for name in names if self.is_sleep_set(name)] if wants_sleep
                else [name for name in names if not self.is_sleep_set(name)] or names)
        if wants_sleep and real:
            return [name for name in real if name != str(exclude or "")] or real
        hits = [name for name in real if name in body]
        if not hits:
            hits = [name for name in real
                    if name.split("·", 1)[-1] and name.split("·", 1)[-1] in body]
        if not hits:
            for camp, words in STYLE_CAMPS:
                if any(word in low for word in words):
                    hits = [name for name in real if self.camp_of(name) == camp]
                    break
        if not hits:
            for name in real:
                for row in groups.get(name) or []:
                    piece = str(row.get("name") or "").split("｜")[-1]
                    tokens = [token for token in re.split(r"[，,、\s]+", piece) if len(token) >= 2]
                    if piece and (piece in body or any(token in body for token in tokens)):
                        hits.append(name)
                        break
        if not hits and (not body or any(word in body for word in GENERIC_STYLE_WORDS)):
            camp = self.last_camp()
            if camp:
                hits = [name for name in real if self.camp_of(name) == camp]
            if not hits:
                hits = list(real)
        # 同一套就不用再换了：优先换别的；衣柜里只剩这一套才允许重复
        return [name for name in hits if name != str(exclude or "")] or hits

    def compose_set(self, set_name):
        """整套穿：这一套的所有件拼成一句（上装→裙→袜→鞋→配饰）。"""
        rows = self.sets().get(str(set_name)) or []
        order = ("dress", "jk_shirt", "jk_skirt", "top", "bottom", "socks", "shoes", "accessory")
        by_slot = {}
        for row in rows:
            slot = str(row.get("slot") or "") or "accessory"
            by_slot.setdefault(slot, []).append(str(row.get("name") or ""))
        pieces = []
        for slot in order:
            pieces.extend(name for name in by_slot.pop(slot, []) if name)
        for slot in sorted(by_slot):
            pieces.extend(name for name in by_slot[slot] if name)
        return "，".join(pieces)

    def pick_set(self, text="", exclude="", seed=""):
        """她的意愿：从符合条件的套里挑一套（同一输入结果稳定，不来回跳）。"""
        candidates = self.find_sets(text, exclude=exclude)
        if not candidates:
            return ""
        chooser = random.Random("amo-pick:%s:%s:%s" % (str(text), str(exclude), str(seed)))
        return chooser.choice(candidates)

    def _compose(self, scene: str, day, gender: str) -> str:
        """按套拼一整套：同一套的件一起穿。

        以前只取 dress/top 再加一两个配件，日程里就出现「只穿肚兜」「只穿内裤」
        「汉服只有抹胸+披帛」——这里按槽位把该套的所有件都拼齐。
        """
        rows = self._slot_items()
        if not rows:
            return self._pick(gender, scene, day, "day")
        scene_rows = [row for row in rows if scene in (row.get("scenes") or [])]
        if not scene_rows:
            scene_rows = rows
        groups = {}
        for row in scene_rows:
            groups.setdefault(self._set_of(row) or str(row.get("name") or ""), []).append(row)
        chooser = random.Random("amo-look:%s:%s" % (str(day), scene))
        keys = sorted(groups)
        group = groups[keys[chooser.randrange(len(keys))]]

        # 一套就是一套：该套所有件全穿上（同槽位的两件也一起，比如披帛+发簪）
        order = ("dress", "top", "jk_shirt", "bottom", "jk_skirt", "socks", "shoes", "accessory")

        def rank(slot):
            try:
                return order.index(str(slot))
            except ValueError:
                return len(order)

        members = [row for row in group if row.get("enabled", True)]
        members.sort(key=lambda row: rank(row.get("slot")))
        pieces = [row["name"] for row in members]
        if not pieces:
            return self._pick(gender, scene, day, "day")
        return "，".join(pieces)

    def assign(self, items, day, persona=""):
        """给日程写 `outfit`。

        - 出门在外（上班/通勤/吃饭/逛街）一天一套，上午下午不换；
        - 在家换家居服，睡觉换睡衣；
        - 海边/泳池那几个小时单独泳装；
        - 只有「淋湿/弄脏 + 回家换衣服」才把外出那套换掉。
        """
        if not isinstance(items, list):
            return items
        if not self.enabled():
            return items
        gender = self.gender(persona)
        base_scene = self.day_scene(items)
        pair = self._compose(base_scene, day, gender)
        backup = self._compose(base_scene, "%s-b" % day, gender)
        # 淋湿/弄脏回家换衣服必须真换一套：换到和上午那套不同为止（最多再试 3 次）。
        # 以前只换一个种子，衣柜里同场景只有两套时有一半概率抽回原来那套。
        for suffix in ("-b2", "-b3", "-b4"):
            if backup and backup != pair:
                break
            backup = self._compose(base_scene, "%s%s" % (day, suffix), gender)
        if not backup or backup == pair:
            # 几个种子全抽回同一套时兜底：直接从同场景的池子里换一套（只有一套就换不了）
            others = [name for name in self._pool(gender, base_scene) if name and name != pair]
            if others:
                backup = others[zlib.crc32(("%s|%s" % (day, gender)).encode("utf-8")) % len(others)]
        homewear = self._compose("home", day, gender)
        sleepwear = self._compose("sleep", day, gender)
        variant = 0
        for item in items:
            if not isinstance(item, dict):
                continue
            activity = str(item.get("activity") or "")
            scene = self.scene_of(item)
            if scene == "sleep":
                item["outfit"] = sleepwear
                continue
            if (any(word in activity for word in self.EMERGENCY_WORDS)
                    and any(word in activity for word in self.CHANGE_WORDS)):
                variant += 1
            if scene == "home":
                # 回家不自动换衣服：一天身上是同一套，只有这一格明说洗澡/换家居服才换。
                if any(word in activity for word in HOME_CHANGE_WORDS):
                    item["outfit"] = homewear
                elif self._minutes(item.get("start")) < 7 * 60:
                    # 半夜醒来/起夜还没到「今天穿出去那套」的时候
                    item["outfit"] = homewear
                else:
                    item["outfit"] = self._safe(pair, base_scene) or pair
                continue
            if scene == "beach":
                item["outfit"] = self._pick(gender, "beach", day, "beach")
                continue
            outfit = pair if variant == 0 else backup
            item["outfit"] = self._safe(outfit, base_scene) or self._pick(gender, "casual", day, "day")
        return self._apply_override(items, day)

    def for_activity(self, activity, day, persona=""):
        """给单条活动算一套（current_activity 兜底、面板试算用）。"""
        if not isinstance(activity, dict) or not activity:
            return ""
        if not self.enabled():
            return str(activity.get("outfit") or "")
        day = str(day or "")
        data = self.override(day) if day else {}
        if data and self._minutes(activity.get("start")) >= self._minutes(data["from"]):
            if self.scene_of(activity) != "sleep":
                if not is_private_wear(data["name"]) or private_ok(activity):
                    return data["name"]
        own = str(activity.get("outfit") or "").strip()
        if own:
            return self._whole_set(own)
        scene = self.scene_of(activity)
        # 一天一套：这一格没写衣服，就按今天的主场景算，不按这一格的场景来回换
        if scene not in ("sleep", "beach"):
            try:
                items = self.plugin.state.schedule.get(day) or []
            except Exception:
                items = []
            if items:
                scene = self.day_scene(items)
        key = "%s|%s" % (activity.get("place") or "", scene)
        outfit = self._safe(self._compose(scene, day, self.gender(persona)), scene)
        if not outfit:
            outfit = self._pick(self.gender(persona), scene, day, key)
        return outfit or self._pick(self.gender(persona), "casual", day, key)
