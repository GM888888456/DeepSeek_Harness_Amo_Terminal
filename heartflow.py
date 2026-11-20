# -*- coding: utf-8 -*-
"""心流数值核心：基础生理 + 七情 + 六欲，纯加减法。

设计约束（照做，不要往里塞业务）：

- **只做加减法和边界锁定**，0–100；任何「因为她在上班所以…」这种判断都属于
  调用方（终端/挂载事件），这里一概不收。
- **双核驱动**：
  * 内驱动 = ``decay(minutes)``：饥饿随时间涨、精力随时间掉，七情六欲落回它自己此刻的
    基线（见下）；
  * 外驱动 = ``apply(event, extra=…)``：挂载（金融/医疗/社交）只发事件名，这里照表加减。
- **枚举即接口**：``Physiology`` / ``Emotion`` / ``Desire`` / ``HeartflowEvent``；
  拼错的键会当场报错，而不是静默写进一个没人读的字段。

## 情绪不再「一句话拉满」（13.0.0 重做）

老的规则有三个毛病，叠在一起就变成「夸两句她就开心上天、怂恿两句贪欲就拉满」：

1. **增益太大**：一次「被夸」+10 喜，聊吃的 +12 舌，撩一下 +11 身；一天里几十条消息
   就能把每一项顶到 100。
2. **只回基线不回落**：不管当时是什么状态，衰减都只把她往 30 拉，
   情绪高的那一侧每轮都被「拽下来一点」，却没有任何机制让她**在自己的心情里**慢慢平复。
3. **没有回落余地**：从 100 掉到 30 要 15 小时，而聊天每隔两分钟又加回去。

现在改成人该有的样子：

- **基线会走**：``drift_baseline()`` 按一天里的时段给一个此刻「正常水平」
  （早上 38、下午 45、深夜 32…），偶尔还有半天的心情小波动。她不是恒定 30 的机器。
- **回落是分档的**：高得越多落得越快（离基线 40 以上每小时能落 45%），
  并且**一次明显向上的情绪最多维持 1–2 小时**，不会顶着一整天的 100。
- **增幅改小、还看当时状态**：同一个刺激在已经很高兴时加得少（饱和），
  在很低落时加得多（戏剧性），而不是线性往上怼。
- **向下也真的能下去**：负面事件（被凶、被晾）降得比正面更狠，而且不会因为
  「已经在 98」就免疫——情绪有恢复力，但也会真的受伤。

存 kv ``heartflow``，重启不丢。
"""

from __future__ import annotations

import random
from enum import Enum


class _StrEnum(str, Enum):
    def __str__(self) -> str:  # pragma: no cover
        return str(self.value)


class Physiology(_StrEnum):
    HUNGER = "hunger"     # 饱食度：越高越饿
    ENERGY = "energy"     # 精力：越低越累


class Emotion(_StrEnum):
    JOY = "joy"
    ANGER = "anger"
    SADNESS = "sadness"
    FEAR = "fear"
    LOVE = "love"
    DISGUST = "disgust"
    SURPRISE = "surprise"


class Desire(_StrEnum):
    EYE = "desire_eye"        # 眼：想看好看的、想见他
    EAR = "desire_ear"        # 耳：想听好听的、想被哄
    NOSE = "desire_nose"      # 鼻：想闻熟悉的味道
    TONGUE = "desire_tongue"  # 舌：想吃想喝
    BODY = "desire_body"      # 身：想被抱、想亲近
    MIND = "desire_mind"      # 意：想被理解、想有共鸣


class HeartflowEvent(_StrEnum):
    """外部世界发生的事——只有事件名，加减表在本文件底部。"""

    TIME_TICK = "time_tick"             # 内驱动：时间流逝
    CHAT_REPLY = "chat_reply"           # 好好聊了几句
    CHAT_IGNORED = "chat_ignored"       # 被晾着
    CHAT_PRAISE = "chat_praise"         # 被夸
    CHAT_INSULT = "chat_insult"         # 被凶/被骂
    CHAT_GREED = "chat_greed"           # 聊钱/股票/杠杆，勾起贪心
    CHAT_EGO = "chat_ego"               # 他被怂恿/被起哄（她说大话、吹牛）
    CHAT_TEASE = "chat_tease"           # 撩她、说想抱想亲
    CHAT_FOOD = "chat_food"             # 聊吃的喝的
    CHAT_AFFECTION = "chat_affection"   # 说想她、爱她、哄她
    MONEY_GIFT = "money_gift"           # 收到转账/红包
    MONEY_TIP = "money_tip"             # 打赏
    MONEY_TIGHT = "money_tight"         # 余额告急
    PHOTO_SENT = "photo_sent"           # 发了照片
    VOICE_SENT = "voice_sent"           # 说了语音
    MEAL = "meal"                       # 吃饭喝水
    MEDICAL_SICK = "medical_sick"       # 生病
    MEDICAL_TREATED = "medical_treated"  # 治好
    PERIOD_START = "period_start"       # 生理期开始
    PERIOD_END = "period_end"           # 生理期结束
    TRIP_START = "trip_start"           # 出门旅游
    TRIP_END = "trip_end"               # 旅行结束
    WISH_MOVE = "wish_move"             # 她按他说的改了行程
    MIRROR = "mirror"                   # 换好衣服照了照镜子


#: 基线：没有外部刺激时，一切都慢慢回到这里（默认值；真实基线每天每时段会走）
BASELINE = 30.0
LOW = 10.0
HIGH = 70.0

#: 单次事件最多能加多少。热闹也有限度，不会一条消息顶掉一整天。
MAX_GAIN = 10.0
#: 向上饱和：已经越靠近上限，同样的刺激加得越少（不是线性的）
#: 从「常态 + 18」往上开始变钝：情绪每高一分，同样的刺激就更不灵一分。
#: 以前从 65 才开始变钝，等于前面十几次夸奖都是满额加成，加起来自然就上天了。
SATURATE_AT = 48.0


#: 六欲从「被勾起来」回到「平常」的速度（每分钟）。欲望比情绪散得快：
#: 馋过了那阵、被哄够了那股劲，人是会下去的。以前六欲和情绪共用一套回落，
#: 结果「馋」和「想被抱」一旦被聊起来就整天挂在高位。
DESIRE_RELEASE_PER_MINUTE = 0.010      # 约 1.7 小时落掉一半
#: 六欲向上时的硬顶：再被撩也会有「够了」的时候，不会一直贴着 100
DESIRE_CEILING = 92.0


#: 事件 → 加减表（纯数据；正数加、负数减）
#:
#: 13.0.0 全线调小：以前「被夸」+10 喜、「聊吃的」+12 舌、「撩一下」+11 身，
#: 一天几十条消息就把每一项顶到 100。现在单条都在 2–6 之间，靠**累积**才有明显情绪。
EVENT_DELTAS: dict[HeartflowEvent, dict] = {
    HeartflowEvent.CHAT_REPLY: {Emotion.JOY: 2, Desire.EAR: 2, Desire.MIND: 1.5},
    HeartflowEvent.CHAT_IGNORED: {Emotion.SADNESS: 4, Desire.MIND: 4, Emotion.ANGER: 2},
    HeartflowEvent.CHAT_PRAISE: {Emotion.JOY: 4, Emotion.LOVE: 2.5, Desire.EAR: 3},
    HeartflowEvent.CHAT_INSULT: {Emotion.ANGER: 7, Emotion.SADNESS: 5, Emotion.LOVE: -4},
    HeartflowEvent.CHAT_GREED: {Emotion.JOY: 2.5, Desire.EYE: 3.5, Desire.MIND: 2},
    HeartflowEvent.CHAT_TEASE: {Emotion.LOVE: 3, Desire.BODY: 4, Desire.EYE: 3},
    HeartflowEvent.CHAT_FOOD: {Desire.TONGUE: 5, Emotion.JOY: 1.5},
    HeartflowEvent.CHAT_AFFECTION: {Emotion.LOVE: 3.5, Desire.EAR: 3, Desire.MIND: 2},
    HeartflowEvent.MONEY_GIFT: {Emotion.JOY: 5, Desire.MIND: 2, Emotion.LOVE: 2},
    HeartflowEvent.MONEY_TIP: {Emotion.JOY: 3, Emotion.SURPRISE: 4},
    HeartflowEvent.MONEY_TIGHT: {Emotion.ANGER: 4, Emotion.SADNESS: 5, Desire.MIND: 2},
    HeartflowEvent.PHOTO_SENT: {Emotion.JOY: 2.5, Desire.EYE: 2.5},
    HeartflowEvent.VOICE_SENT: {Emotion.JOY: 2.5, Desire.EAR: 3.5},
    HeartflowEvent.MEAL: {Physiology.HUNGER: -25, Emotion.JOY: 2, Desire.TONGUE: -15},
    HeartflowEvent.MEDICAL_SICK: {Physiology.ENERGY: -15, Emotion.SADNESS: 5},
    HeartflowEvent.MEDICAL_TREATED: {Physiology.ENERGY: 10, Emotion.JOY: 3},
    HeartflowEvent.PERIOD_START: {Physiology.ENERGY: -20, Emotion.ANGER: 10, Desire.BODY: 12},
    HeartflowEvent.PERIOD_END: {Physiology.ENERGY: 10, Emotion.ANGER: -6},
    HeartflowEvent.TRIP_START: {Emotion.JOY: 8, Desire.EYE: 8},
    HeartflowEvent.TRIP_END: {Emotion.JOY: -3, Physiology.ENERGY: -8},
    HeartflowEvent.WISH_MOVE: {Emotion.JOY: 2.5, Desire.MIND: 2.5},
    HeartflowEvent.MIRROR: {Emotion.JOY: 2, Desire.EYE: 2},
}

#: 事件 → 给模型看的「为什么」（写进最近的经历里）
EVENT_NOTES = {
    HeartflowEvent.CHAT_REPLY: "他刚好好跟我聊了几句",
    HeartflowEvent.CHAT_IGNORED: "他把我晾着没回",
    HeartflowEvent.CHAT_PRAISE: "他夸我了",
    HeartflowEvent.CHAT_INSULT: "他凶我了",
    HeartflowEvent.CHAT_GREED: "他跟我聊钱、股票、杠杆",
    HeartflowEvent.CHAT_TEASE: "他撩我，说得我心里发热",
    HeartflowEvent.CHAT_FOOD: "他跟我聊吃的，我馋了",
    HeartflowEvent.CHAT_AFFECTION: "他说想我、哄我",
    HeartflowEvent.MONEY_GIFT: "他给我转账了",
    HeartflowEvent.MONEY_TIP: "他打赏我",
    HeartflowEvent.MONEY_TIGHT: "手头有点紧",
    HeartflowEvent.PHOTO_SENT: "我刚给他发了照片",
    HeartflowEvent.MIRROR: "我换好衣服照了照镜子，觉得自己今天挺好看的",
    HeartflowEvent.VOICE_SENT: "我刚给他发了语音",
    HeartflowEvent.MEAL: "我吃了点东西",
    HeartflowEvent.MEDICAL_SICK: "我生病了",
    HeartflowEvent.MEDICAL_TREATED: "看过病了，好一点",
    HeartflowEvent.PERIOD_START: "生理期来了，肚子疼",
    HeartflowEvent.PERIOD_END: "生理期过去了",
    HeartflowEvent.TRIP_START: "出门玩了",
    HeartflowEvent.TRIP_END: "旅行结束回来了",
    HeartflowEvent.WISH_MOVE: "他说了句话，我改了行程",
}


#: 极端值的内心戏（第一人称）；键是 (维度, 方向)
INNER_VOICE = {
    (Emotion.JOY, "high"): "我现在开心得想原地转圈。",
    (Emotion.ANGER, "high"): "我现在火气压不住，谁惹我谁倒霉。",
    (Emotion.SADNESS, "high"): "我现在心里堵得慌，很想哭。",
    (Emotion.FEAR, "high"): "我现在有点怕，想找个人靠着。",
    (Emotion.LOVE, "high"): "我现在整颗心都黏在他身上。",
    (Emotion.DISGUST, "high"): "我现在烦到不想看见任何人。",
    (Emotion.SURPRISE, "high"): "我现在整个人都懵着，还没缓过来。",
    (Desire.EYE, "high"): "我现在特别想见他，想得眼睛都发酸。",
    (Desire.EAR, "high"): "我现在就想听他的声音，哄我两句也好。",
    (Desire.NOSE, "high"): "我现在很想闻到他身上的味道。",
    (Desire.TONGUE, "high"): "我现在馋得不行，想吃点好的。",
    (Desire.BODY, "high"): "我现在特别想被他抱着，贴一会儿就好。",
    (Desire.MIND, "high"): "我现在很想有人懂我，说说话也好。",
    (Physiology.HUNGER, "high"): "我现在饿得胃里发空。",
    (Physiology.ENERGY, "low"): "我现在累得眼睛都睁不开。",
    (Emotion.JOY, "low"): "我现在提不起劲，什么都不想干。",
    (Emotion.LOVE, "low"): "我现在对他有点冷淡，不想理人。",
}

DIMENSIONS = (tuple(Physiology) + tuple(Emotion) + tuple(Desire))

#: 维度名 → 枚举成员（apply 里按名字回查，用来判定「这是情绪还是欲」）
_DIM_BY_NAME = {dim.value: dim for dim in DIMENSIONS}


def _dim_of(name: str):
    return _DIM_BY_NAME.get(str(name or ""))


def clamp(value: float) -> float:
    return max(0.0, min(100.0, float(value)))


class Heartflow:
    """数值仓库 + 纯加减法。调用方负责决定「发生了什么」。"""

    KEY = "heartflow"

    def __init__(self, db):
        self.db = db

    # ---------- 存取 ----------

    def load(self) -> dict:
        try:
            raw = self.db.kv_get(self.KEY, {}) or {}
        except Exception:
            raw = {}
        values = {}
        for dim in DIMENSIONS:
            try:
                value = float((raw or {}).get(dim.value, BASELINE))
            except (TypeError, ValueError):
                value = BASELINE
            values[dim.value] = clamp(value)
        return values

    def save(self, values: dict) -> dict:
        clean = {dim.value: clamp(values.get(dim.value, BASELINE)) for dim in DIMENSIONS}
        try:
            self.db.kv_set(self.KEY, clean)
        except Exception:
            pass
        return clean

    def values(self) -> dict:
        return self.load()

    # ---------- 外驱动 ----------

    LOG_KEY = "heartflow_log"

    def recent(self, limit: int = 6) -> list:
        try:
            rows = self.db.kv_get(self.LOG_KEY, []) or []
        except Exception:
            return []
        return rows[-max(1, int(limit)):] if isinstance(rows, list) else []

    def _remember(self, event, note: str) -> None:
        import time
        rows = self.recent(8)
        rows.append({"ts": time.time(), "event": str(getattr(event, "value", event)),
                     "note": str(note or "")})
        try:
            self.db.kv_set(self.LOG_KEY, rows[-8:])
        except Exception:
            pass

    def apply(self, event, extra: dict | None = None, severity: float | None = None) -> dict:
        """按事件名加减；``severity``（0–10）按比例放大这一次的影响。"""
        values = self.load()
        try:
            key = HeartflowEvent(str(event))
        except ValueError:
            key = None
        if severity is not None:
            try:
                factor = max(0.3, min(1.5, 0.3 + float(severity) / 10.0 * 1.2))
            except (TypeError, ValueError):
                factor = 1.0
        else:
            factor = 1.0
        table = {}
        if key is not None:
            table = {dim: delta * factor for dim, delta in EVENT_DELTAS.get(key, {}).items()}
            note = EVENT_NOTES.get(key, "")
            if key is HeartflowEvent.PERIOD_START and severity is not None:
                note = "生理期来了，痛经 %d 级" % int(severity)
            self._remember(key, note)
        merged: dict[str, float] = {}
        for dim, delta in list(table.items()) + list((extra or {}).items()):
            name = dim.value if isinstance(dim, Enum) else str(dim)
            if name not in values:
                continue
            try:
                step = float(delta)
            except (TypeError, ValueError):
                continue
            # 单次上限：再热闹也有个量，不会一条消息顶掉一整天。
            # 单次增/减各自夹住（负数要单独夹：写成 max(-MAX_GAIN, ...) 会穿过去）
            step = min(MAX_GAIN, step) if step > 0 else max(-MAX_GAIN, step)
            merged[name] = merged.get(name, 0.0) + step
        return self._apply_steps(values, merged)

    def bump(self, steps, note: str = "") -> dict:
        """按维度直接加减，没有「事件」可用时走这里。

        日程的影响、被他哄、被打扰、天气变脸——这些都落到同一套七情六欲上，
        而不是另开一套心情（2026-11-18 删掉十维之后，这里是唯一的心情入口）。
        键就是维度名：joy / anger / sadness / fear / love / energy …
        """
        values = self.load()
        merged: dict[str, float] = {}
        for dim, delta in (steps or {}).items():
            name = dim.value if isinstance(dim, Enum) else str(dim)
            if name not in values:
                continue
            try:
                step = float(delta)
            except (TypeError, ValueError):
                continue
            step = min(MAX_GAIN, step) if step > 0 else max(-MAX_GAIN, step)
            merged[name] = merged.get(name, 0.0) + step
        return self._apply_steps(values, merged)

    def _apply_steps(self, values: dict, merged: dict) -> dict:
        """把一组增量落到数值上：饱和、六欲硬顶、夹边，保存后返回。"""
        for name, step in merged.items():
            current = values[name]
            dim = _dim_of(name)
            if step > 0 and isinstance(dim, Desire):
                # 六欲有硬顶，夹住而不是直接跳过（跳过会让 88 + 4 = 92.5 越顶）
                step = min(step, max(0.0, DESIRE_CEILING - current))
                if step <= 0:
                    continue
            if step > 0 and current > SATURATE_AT:
                # 已经很开心了，同样一句夸奖就没那么灵了（向上饱和）。
                # 负向不受饱和限制：情绪有恢复力，也会真的受伤。
                # 越往上越迟钝：没到 SATURATE_AT 之前满额，之后按「离顶还剩多少」打折，
                # 贴着 100 时只剩三成。连夸十几次能到 75 上下，想更高得靠真的事
                # （礼物、旅行、被哄很久）——这才是「高兴」，不是「被刷起来」。
                room = max(0.0, min(1.0, (100.0 - current) / max(1.0, 100.0 - SATURATE_AT)))
                step *= 0.3 + 0.7 * room
            values[name] = clamp(current + step)
        return self.save(values)

    # ---------- 内驱动 ----------

    #: 自然变化速度（每分钟）。以前是 0.6 / 0.35，一小时就饿 36 点、掉 21 点精力：
    #: 吃一顿才回 25 点，等于刚吃完一小时又饿，而且精力只会一路掉到 0，永远回不来。
    HUNGER_PER_MINUTE = 0.25          # 约 6.7 小时从饱到饿
    ENERGY_PER_MINUTE = 0.12          # 醒着 14 小时耗尽
    SLEEP_ENERGY_PER_MINUTE = 0.8     # 睡着两小时回满

    #: 分档回落：离基线越远，落得越快。以前一律 8%/小时，从 100 落回基线要 15 小时，
    #: 中间聊天又不停往上加，于是情绪就一直顶在天花板上。
    #: 值是「每小时回落掉超出部分的比例」。
    RELEASE_BANDS = (
        (40.0, 0.45),   # 高得离谱：一小时落掉一半多
        (22.0, 0.30),   # 明显偏高：一小时落掉三成
        (10.0, 0.18),   # 有点上头
        (0.0, 0.10),    # 平常的小起伏
    )

    #: 一天里「正常水平」的走向（小时 → 基线）。她不是恒定 30 的机器：
    #: 早上刚醒偏低、下午状态最好、深夜最down。
    BASELINE_BY_HOUR = (
        (5, 26.0), (7, 30.0), (9, 36.0), (12, 42.0), (15, 45.0),
        (18, 42.0), (21, 38.0), (23, 31.0), (24, 27.0),
    )

    def drift_baseline(self, hour: int | None = None) -> float:
        """此刻的「正常水平」：按钟点插值 + 当天固定的一个心情小波动（±4）。

        用日期做种子，所以同一天的基线是稳定的（不会每 5 分钟跳一次），
        但每天不一样——她有自己的心情起落，不是被聊天决定。
        """
        import datetime as _dt
        if hour is None:
            try:
                hour = int(_dt.datetime.now().hour)
            except Exception:
                hour = 12
        hour = max(0, min(24, int(hour)))
        points = self.BASELINE_BY_HOUR
        base = float(points[-1][1])
        for index in range(len(points) - 1):
            h0, v0 = points[index]
            h1, v1 = points[index + 1]
            if h0 <= hour <= h1:
                span = max(1e-6, float(h1 - h0))
                ratio = (hour - h0) / span
                base = v0 + (v1 - v0) * ratio
                break
        try:
            seed = int(_dt.datetime.now().strftime("%Y%m%d"))
        except Exception:
            seed = 0
        rng = random.Random(seed)
        return base + rng.uniform(-4.0, 4.0)

    def decay(self, minutes: float, sleeping: bool = False) -> dict:
        """时间流逝：饿一点；醒着掉精力、睡着回精力；七情六欲分档回落到「此刻的基线」。

        睡着时回落更快（人睡一觉就好了大半），但不会一夜之间从 100 变回 30——
        醒来还带着昨天的一点余味，这才像人。
        """
        try:
            span = max(0.0, float(minutes))
        except (TypeError, ValueError):
            return self.load()
        if span <= 0:
            return self.load()
        hours = span / 60.0
        values = self.load()
        values[Physiology.HUNGER.value] = clamp(
            values[Physiology.HUNGER.value] + self.HUNGER_PER_MINUTE * span)
        rate = self.SLEEP_ENERGY_PER_MINUTE if sleeping else -self.ENERGY_PER_MINUTE
        values[Physiology.ENERGY.value] = clamp(values[Physiology.ENERGY.value] + rate * span)
        # 睡着时不要用固定 30：用「此刻的常态」，只是恢复得更快一点。
        # 以前直接按 BASELINE + 1.6 倍速，睡四小时就把白天所有情绪抹平了。
        base = self.drift_baseline()
        for dim in tuple(Emotion) + tuple(Desire):
            name = dim.value
            current = values[name]
            gap = current - base
            distance = abs(gap)
            if isinstance(dim, Desire) and gap > 0:
                # 欲比情绪散得快：先按自己的速度往下渗一层，再走分档回落。
                values[name] = clamp(current - DESIRE_RELEASE_PER_MINUTE * span)
                current = values[name]
                gap = current - base
                distance = abs(gap)
            ratio = self.RELEASE_BANDS[-1][1]
            for threshold, band_ratio in self.RELEASE_BANDS:
                if distance >= threshold:
                    ratio = band_ratio
                    break
            if sleeping:
                # 睡着时不能用「按比例一次性抹平」：4 小时就归零，醒来像换了个脑子。
                # 改成每小时按同一档比例持续回落，睡满 8 小时能落掉七成左右，
                # 醒来还带着昨天的一点余味（起床气 / 余欢）。
                # 速率：睡着的每一小时按同一档比例回落，但在档位上放大一点
                # （人睡一觉情绪缓得比醒着快）。0.55 → 0.85 是同档里最不明显的一处调整：
                # 睡 4 小时 95 分的怒气能落到 55 上下，睡满 8 小时落掉约八成，
                # 醒来仍有「起床气」的余味，不会像换了个人。
                decayed = gap
                for _ in range(max(1, int(round(hours)))):
                    decayed *= (1.0 - min(0.62, ratio * 0.85))
                values[name] = clamp(current - (gap - decayed))
                continue
            step = min(1.0, ratio * hours)
            values[name] = clamp(current - gap * step)
        return self.save(values)

    def set_physiology(self, hunger=None, energy=None) -> dict:
        """外部（生存系统）校准生理值。

        吃饭/喝水只会改记忆库的饱食度，心流这边要跟着对齐，否则面板和内心戏
        还停在「饿 100」，她吃完也继续喊饿。
        """
        values = self.load()
        try:
            if hunger is not None:
                values[Physiology.HUNGER.value] = clamp(float(hunger))
            if energy is not None:
                values[Physiology.ENERGY.value] = clamp(float(energy))
        except (TypeError, ValueError):
            return values
        return self.save(values)

    # ---------- Prompt ----------

    def voice_urge(self) -> float:
        """想用声音说话的冲动（0~1）：想被哄/爱/想被理解/情绪浓度。

        纯数值推导，不含业务判断；私聊没有小模型打分时，用它当「心流判定」的结果。
        """
        values = self.load()

        def _v(name: str) -> float:
            try:
                return float(values.get(name, BASELINE))
            except (TypeError, ValueError):
                return BASELINE

        # 任何一项情绪/欲望很强，都会想开口；再叠一层整体浓度。
        strong = max(_v("joy"), _v("sadness"), _v("anger"),
                     _v("desire_ear"), _v("love"),
                     _v("desire_body"), _v("desire_mind"))
        average = (_v("desire_ear") + _v("love") + _v("desire_mind")
                   + _v("joy") + _v("sadness") + _v("desire_body")) / 6.0
        raw = 0.55 * strong + 0.45 * average
        return clamp(raw) / 100.0

    def get_prompt_summary(self) -> str:
        """给模型看的一段：常数值 + 极端值的内心戏。"""
        values = self.load()
        parts = []
        parts.append("七情：%s" % "、".join(
            "%s%.0f" % (name_cn(item), values[item.value]) for item in Emotion))
        lines = []
        for dim in DIMENSIONS:
            value = values[dim.value]
            if value > HIGH:
                lines.append(INNER_VOICE.get((dim, "high")) or ("我现在%s很强。" % name_cn(dim)))
            elif value < LOW:
                lines.append(INNER_VOICE.get((dim, "low")) or ("我现在%s几乎没有了。" % name_cn(dim)))
        if lines:
            parts.append("（内心：%s）" % " ".join(lines[:4]))
        # 情绪是流动的：把「此刻的正常水平」也告诉她，她才知道自己现在算偏高还是偏低，
        # 而不是把 95 当成常态、每一轮都表现得像打了鸡血。
        try:
            base = self.drift_baseline()
            parts.append("（此刻心里的常态大约 %.0f 分，偏离常态才是情绪。）" % base)
        except Exception:
            pass
        reasons = [row.get("note") for row in self.recent(3) if str(row.get("note") or "").strip()]
        if reasons:
            parts.append("（最近发生：%s。情绪就是从这些事来的，会慢慢散掉——"
                         "不用一直挂在刚才那件事上。）"
                         % "；".join(reasons[-3:]))
        return "\n".join(parts)


_NAMES = {
    Physiology.HUNGER: "饿", Physiology.ENERGY: "精力",
    Emotion.JOY: "喜", Emotion.ANGER: "怒", Emotion.SADNESS: "哀", Emotion.FEAR: "惧",
    Emotion.LOVE: "爱", Emotion.DISGUST: "恶", Emotion.SURPRISE: "惊",
    Desire.EYE: "眼", Desire.EAR: "耳", Desire.NOSE: "鼻", Desire.TONGUE: "舌",
    Desire.BODY: "身", Desire.MIND: "意",
}


def name_cn(dim) -> str:
    return _NAMES.get(dim, str(getattr(dim, "value", dim)))
