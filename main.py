# -*- coding: utf-8 -*-
"""
我想永远陪着你 / 我想永远陪着你-终端 5.4.2
一个尽量“像人”的 AstrBot 智械人类核心：
生理期 / 九维心情 / 世界观与日程 / 天气 / 健康 / 群聊插话阈值 /
私聊判定 / 主动私聊 / 长期记忆与遗忘 / 防抖 / 引用回复（怎么说是守护的事）
"""

from __future__ import annotations


# 统一时区：容器/服务器常在 UTC 跑，直接取服务器本地时间会把北京时间 10 点算成凌晨 2 点
# （「大晚上的」就是这么来的）。clock.now() 返回目标时区下的 naive 本地时间，
# 和原来的用法完全兼容。
# ---- 阶段 1 拆分：四个纯类与工具函数已移到 amo_core/ ----
try:
    from .amo_core.deps import *  # noqa: F401,F403
    from .amo_core.consts import *  # noqa: F401,F403
    from .amo_core.text import *  # noqa: F401,F403
    from .amo_core.timeutil import *  # noqa: F401,F403
    from .amo_core.util import *  # noqa: F401,F403
    from .amo_core.amo_db import *  # noqa: F401,F403
    from .amo_core.human_state import *  # noqa: F401,F403
    from .amo_core.llm_service import *  # noqa: F401,F403
    from .amo_core.reply_gate import *  # noqa: F401,F403
    from .amo_core.usage import *  # noqa: F401,F403
    from .amo_core.databridge import *  # noqa: F401,F403
    from .amo_core.persona import *  # noqa: F401,F403
    from .amo_core.config import *  # noqa: F401,F403
    from .amo_core.infra import *  # noqa: F401,F403
    from .amo_core.vitals import *  # noqa: F401,F403
    from .amo_core.memory_ops import *  # noqa: F401,F403
    from .amo_core.media import *  # noqa: F401,F403
    from .amo_core.shared import *  # noqa: F401,F403
    from .amo_core.relations import *  # noqa: F401,F403
    from .amo_core.presence import *  # noqa: F401,F403
    from .amo_core.outfit import *  # noqa: F401,F403
    from .amo_core.weather import *  # noqa: F401,F403
    from .amo_core.economy import *  # noqa: F401,F403
    from .amo_core.learn import *  # noqa: F401,F403
    from .amo_core.sync import *  # noqa: F401,F403
    from .amo_core.reply import *  # noqa: F401,F403
    from .amo_core.ticker import *  # noqa: F401,F403
    from .amo_core.commands import *  # noqa: F401,F403
    from .amo_core.context import *  # noqa: F401,F403
    from .amo_core.web_api import *  # noqa: F401,F403
except ImportError:  # 非包方式加载时的回退
    from amo_core.deps import *  # noqa: F401,F403
    from amo_core.consts import *  # noqa: F401,F403
    from amo_core.text import *  # noqa: F401,F403
    from amo_core.timeutil import *  # noqa: F401,F403
    from amo_core.util import *  # noqa: F401,F403
    from amo_core.amo_db import *  # noqa: F401,F403
    from amo_core.human_state import *  # noqa: F401,F403
    from amo_core.llm_service import *  # noqa: F401,F403
    from amo_core.reply_gate import *  # noqa: F401,F403
    from amo_core.usage import *  # noqa: F401,F403
    from amo_core.databridge import *  # noqa: F401,F403
    from amo_core.persona import *  # noqa: F401,F403
    from amo_core.config import *  # noqa: F401,F403
    from amo_core.infra import *  # noqa: F401,F403
    from amo_core.vitals import *  # noqa: F401,F403
    from amo_core.memory_ops import *  # noqa: F401,F403
    from amo_core.media import *  # noqa: F401,F403
    from amo_core.shared import *  # noqa: F401,F403
    from amo_core.relations import *  # noqa: F401,F403
    from amo_core.presence import *  # noqa: F401,F403
    from amo_core.outfit import *  # noqa: F401,F403
    from amo_core.weather import *  # noqa: F401,F403
    from amo_core.economy import *  # noqa: F401,F403
    from amo_core.learn import *  # noqa: F401,F403
    from amo_core.sync import *  # noqa: F401,F403
    from amo_core.reply import *  # noqa: F401,F403
    from amo_core.ticker import *  # noqa: F401,F403
    from amo_core.commands import *  # noqa: F401,F403
    from amo_core.context import *  # noqa: F401,F403
    from amo_core.web_api import *  # noqa: F401,F403






# ---- 画图 / 照片分享（本地功能，接万象画卷 OmniDraw）----









try:
    from .heartflow_engine import HeartflowEngine
except Exception:
    try:
        from heartflow_engine import HeartflowEngine
    except Exception:
        HeartflowEngine = None
        try:
            import importlib.util
            _engine_dir = os.path.dirname(os.path.abspath(__file__))
            def _load_engine(module_name, class_name):
                _spec = importlib.util.spec_from_file_location(
                    "amo_" + module_name,
                    os.path.join(_engine_dir, module_name + ".py"),
                )
                _module = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(_module)
                return getattr(_module, class_name)
            HeartflowEngine = _load_engine("heartflow_engine", "HeartflowEngine")
        except Exception as _engine_exc:
            logger.error("[amo] 内置心流模块加载失败: %s" % _engine_exc)







# 日记只存记忆库（diary_put/get/list），本地 txt 引擎已删











try:
    from .schedule_engine import ScheduleEngine
except Exception:
    try:
        from schedule_engine import ScheduleEngine
    except Exception:
        try:
            import importlib.util as _importlib_util
            _schedule_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schedule_engine.py")
            _schedule_spec = _importlib_util.spec_from_file_location("amo_schedule_engine", _schedule_path)
            _schedule_module = _importlib_util.module_from_spec(_schedule_spec)
            _schedule_spec.loader.exec_module(_schedule_module)
            ScheduleEngine = getattr(_schedule_module, "ScheduleEngine")
        except Exception as _schedule_exc:
            ScheduleEngine = None
            logger.error("[amo] 日程引擎加载失败: %s" % _schedule_exc)





#: 老版本「Memory Companion」会把「记忆 N 条」这种机器统计写进画像备注；
#: 插件删了以后这些值还留在两边的库里，同步时又会被拉回来。读到就直接当没有。
#: 他说「要睡 / 在睡」——她不能再问上班、到家、吃没吃，也不能催照片。
#: 他说「不在这儿 / 不上班」——「下班没 / 到家没」这种话就不成立。





_VOICE_TAG_OPEN_RE = re.compile(r"<(?:astrbot_speak|amo_speak)\b([^>]*)>", re.I)
_VOICE_TAG_RE = re.compile(r"</?(?:astrbot_speak|amo_speak)\b[^>]*>", re.I)


def _strip_voice_tags(text: str) -> str:
    """模型偶尔不调 amo_speak 工具，直接输出 <astrbot_speak text="..."> 这种伪标签。
    这里只取要念的那句话，别把标签念出来，也别让整条回复消失。"""
    body = str(text or "")
    m = _VOICE_TAG_OPEN_RE.search(body)
    if m:
        attr = m.group(1) or ""
        am = re.search(r'text\s*=\s*"([^"]*)"', attr) or re.search(r"text\s*=\s*'([^']*)'", attr)
        if am and am.group(1).strip():
            return strip_pseudo_tags(am.group(1).strip())
        tail = body[m.end():]
        close = re.search(r"</(?:astrbot_speak|amo_speak)>", tail, re.I)
        if close:
            return strip_pseudo_tags(tail[: close.start()].strip())
    return strip_pseudo_tags(_VOICE_TAG_RE.sub("", body))


def split_voice_tag(text: str) -> tuple[str, str]:
    """把模型写出来的 ``<astrbot_speak text="…">`` 伪标签拆成两半。

    返回 ``(要念的那句, 标签以外剩下的正文)``；没有标签时返回 ``("", 原文)``。
    模型偶尔不调 amo_speak 工具，直接把标签写进正文——标签绝不能进聊天
    （群里只会显示成一串代码），但整条回复也不能因此消失。
    """
    body = str(text or "")
    if not _VOICE_TAG_OPEN_RE.search(body):
        return "", body
    return _strip_voice_tags(body), strip_pseudo_tags(_VOICE_TAG_RE.sub("", body)).strip()


try:  # 版本号以 metadata.yaml 为准，避免两处不一致
    import yaml as _amo_meta_yaml
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "metadata.yaml"),
              encoding="utf-8") as _amo_meta_fh:
        _amo_meta = _amo_meta_yaml.safe_load(_amo_meta_fh) or {}
    if _amo_meta.get("version"):
        PLUGIN_VERSION = str(_amo_meta["version"])
except Exception:
    pass

# 这些开关是面板/主链路的底座：隐藏开关并强制开启，避免误关后整块功能消失。

#: 面板不展示、但仍可从配置文件改的键。
#: 评分规则决定「什么叫值得回」，改错了她会变得很奇怪；绝大多数人不需要动它。
DEFAULT_ADMIN = ""
LEGACY_DEFAULT_ADMIN = "3261748099"







#: 真正算「生病」的状态；「疲惫」只是累，不该按病号排日程。



# 关系网里的内部节点：bot/self 代表"我自己"，不是真实人物。
# 这种边只存在本地（_push_relation_to_data 不推给记忆终端），比较远端/本地时也要排掉，
# 否则远端永远比本地少一条，每 10 分钟误报一次"关系网不同步"。


# ---------------------------------------------------------------------------
# 基础工具
# ---------------------------------------------------------------------------




# 2026 年主要假期的连续日期（用于判断长假/短假）
for _d in range(1, 4):
    CN_HOLIDAYS.setdefault("2026-01-%02d" % _d, "元旦")
for _d in range(4, 7):
    CN_HOLIDAYS.setdefault("2026-04-%02d" % _d, "清明")
for _d in range(1, 6):
    CN_HOLIDAYS.setdefault("2026-05-%02d" % _d, "劳动节")
for _d in range(19, 22):
    CN_HOLIDAYS.setdefault("2026-06-%02d" % _d, "端午")
for _d in range(25, 28):
    CN_HOLIDAYS.setdefault("2026-09-%02d" % _d, "中秋")























def _norm_sentence(value) -> str:
    """比较用：去掉标点、空白和表情，只留字。"""
    return re.sub(r"[\W_]+", "", str(value or ""))


def _bigrams(text: str) -> set:
    value = _norm_sentence(text)
    if len(value) < 2:
        return {value} if value else set()
    return {value[index:index + 2] for index in range(len(value) - 1)}


def _cover_ratio(short: str, longer: str) -> float:
    """短句的 bigram 有多少出现在长句里（0~1）。"""
    a, b = _bigrams(short), _bigrams(longer)
    if not a or not b:
        return 0.0
    return len(a & b) / float(len(a))


def same_sentence(a, b, threshold=0.8) -> bool:
    """两句是不是同一句。

    2026-11-18 16:00：她调 amo_speak 念了「还在跟同事扯接口…」，四秒后守护
    又把同一句当文字发了一遍，群里就是语音 + 同一条文字。语音插件念过的句子，
    正文不该再发；只做去重判断，不改变任何说话逻辑。
    """
    na, nb = _norm_sentence(a), _norm_sentence(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    short, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    # 太短的一句（「好」「嗯」）不做包含/相似判断，免得把真回复误吞
    if len(short) < 8:
        return False
    if short in longer:
        return True
    # 换了个说法的同一句：语音念「小k这名字叫着倒顺口，你俩是早就认识的呀」，
    # 正文写「小k这名字叫着倒挺顺口」—— difflib 只有 0.67，但短句几乎被完全覆盖。
    if len(short) >= 6 and _cover_ratio(short, longer) >= 0.75:
        return True
    try:
        return difflib.SequenceMatcher(None, na, nb).ratio() >= threshold
    except Exception:
        return False












































# ---------------------------------------------------------------------------
# 分段器：书号、引号等成对符号内部绝对不切
# ---------------------------------------------------------------------------

_PAIRS = {
    "《": "》", "〈": "〉", "“": "”", "‘": "’", "「": "」", "『": "』",
    "（": "）", "(": ")", "【": "】", "〔": "〕", "[": "]", "{": "}",
}
_STRONG = "。！？!?…\n"
_WEAK = "，,、；;：:~～"
_TRIM = " \t\r\n。！？!?…，,、；;：:~～"


def _protect_mask(text):
    length = len(text)
    mask = [False] * length

    def mark(start, end):
        for index in range(max(0, start), min(length, end)):
            mask[index] = True

    for match in re.finditer(r"```.*?```", text, re.S):
        mark(match.start(), match.end())
    for match in re.finditer(r"`[^`\n]+`", text):
        mark(match.start(), match.end())
    for match in re.finditer(r"https?://[^\s]+", text):
        mark(match.start(), match.end())

    index = 0
    while index < length:
        char = text[index]
        closer = _PAIRS.get(char)
        if closer:
            depth = 1
            scan = index + 1
            while scan < length:
                if text[scan] == char:
                    depth += 1
                elif text[scan] == closer:
                    depth -= 1
                    if depth == 0:
                        break
                scan += 1
            if scan < length:
                mark(index, scan + 1)
                index = scan + 1
                continue
            mark(index, length)
            break
        index += 1
    return mask


def _cut(text, mask, delimiters, min_keep=0):
    parts = []
    start = 0
    for index, char in enumerate(text):
        if mask[index]:
            continue
        if char in delimiters and (index + 1 - start) >= min_keep:
            parts.append(text[start:index + 1])
            start = index + 1
    parts.append(text[start:])
    return parts


def _protected_ranges(text):
    mask = _protect_mask(text)
    ranges = []
    start = None
    for index, flag in enumerate(mask):
        if flag and start is None:
            start = index
        elif not flag and start is not None:
            ranges.append((start, index))
            start = None
    if start is not None:
        ranges.append((start, len(mask)))
    return ranges


def _mask_with_placeholders(text):
    ranges = _protected_ranges(text)
    if not ranges:
        return text, {}
    pieces = []
    placeholders = {}
    last = 0
    for index, (start, end) in enumerate(ranges):
        pieces.append(text[last:start])
        token = "\x00%d\x00" % index
        placeholders[token] = text[start:end]
        pieces.append(token)
        last = end
    pieces.append(text[last:])
    return "".join(pieces), placeholders


def _split_regex(text, pattern, protect_pairs=True):
    if not pattern:
        return None
    masked, placeholders = _mask_with_placeholders(text) if protect_pairs else (text, {})
    try:
        compiled = re.compile(pattern)
    except re.error:
        return None
    pieces = []
    last = 0
    for match in compiled.finditer(masked):
        end = match.end()
        if end <= last:
            continue
        pieces.append(masked[last:end])
        last = end
    pieces.append(masked[last:])
    restored = []
    for piece in pieces:
        value = piece
        for token, original in placeholders.items():
            value = value.replace(token, original)
        value = value.strip()
        if value:
            restored.append(value)
    return restored


def segment_text(text, keep_punc=True, min_len=6, max_len=42, max_segments=4,
                 mode="punct", split_chars="", regex_pattern="", protect_pairs=True):
    """按标点符号或正则分段；成对符号、代码块、URL 内部不会被切开。

    mode="punct" 时按 segment_split_chars + 内置标点分段；
    mode="regex" 时按 segment_regex 分段，失败自动回退到标点模式。
    """
    text = (text or "").replace("\r\n", "\n").strip()
    if not text:
        return []
    min_len = max(1, to_int(min_len, 6))
    max_len = max(min_len + 1, to_int(max_len, 42))
    max_segments = max(1, to_int(max_segments, 4))

    pieces = None
    if str(mode).lower() == "regex" and regex_pattern:
        pieces = _split_regex(text, regex_pattern, protect_pairs)
    if pieces is None:
        extra = "".join(char for char in str(split_chars or "") if char not in "\r\n")
        strong = "".join(dict.fromkeys(_STRONG + extra))
        mask = _protect_mask(text) if protect_pairs else [False] * len(text)
        pieces = []
        for part in _cut(text, mask, strong):
            part = part.strip()
            if not part:
                continue
            if len(part) > max_len:
                sub_mask = _protect_mask(part) if protect_pairs else [False] * len(part)
                pieces.extend(_cut(part, sub_mask, _WEAK, min_keep=max(4, max_len // 2)))
            else:
                pieces.append(part)

    normalized = []
    for part in pieces or []:
        part = str(part).strip()
        if not part:
            continue
        if len(part) > max_len:
            sub_mask = _protect_mask(part) if protect_pairs else [False] * len(part)
            normalized.extend(_cut(part, sub_mask, _WEAK, min_keep=max(4, max_len // 2)))
        else:
            normalized.append(part)
    pieces = normalized

    segments = []
    for part in pieces:
        seg = part.strip()
        if not keep_punc:
            seg = seg.strip(_TRIM)
        if seg:
            segments.append(seg)
    if not segments:
        return []

    index = 0
    while len(segments) > 1 and index < len(segments):
        if len(segments[index]) < min_len:
            if index + 1 < len(segments):
                segments[index + 1] = segments[index] + segments[index + 1]
                del segments[index]
                continue
            segments[index - 1] = segments[index - 1] + segments[index]
            del segments[index]
            break
        index += 1

    while len(segments) > max_segments:
        best = 0
        best_len = None
        for cursor in range(len(segments) - 1):
            total = len(segments[cursor]) + len(segments[cursor + 1])
            if best_len is None or total < best_len:
                best_len = total
                best = cursor
        segments[best] = segments[best] + segments[best + 1]
        del segments[best + 1]

    return [seg for seg in segments if seg][:max_segments]


AI_ADMISSION_RE = re.compile(
    r"(?:我是|作为|毕竟|本人|本机)\s*(?:AI|人工智能|机器人|人机|程序|模型)"
    r"|(?:只是|不过是|就是个|只是个)\s*(?:AI|人工智能|机器人|人机|程序|模型)"
    r"|人机(?:也|当然|本来|就是)"
    r"|不是真人|虚拟(?:人|角色|存在)"
    r"|(?:我|咱|我们)(?:其实|本质上|说到底|严格来说)?(?:就是|不过是|只是个)"
    r"\s*(?:AI|人工智能|机器人|人机|程序|语言模型|大模型)",
    re.I,
)


def looks_like_ai_admission(text):
    return bool(AI_ADMISSION_RE.search(str(text or "")))


# 她不能报后台：模型名、厂商、插件名、API、提示词这类都不该出现在聊天里。
# 但「插件/提示词/模型」这些词在正常的开发闲聊里也会出现（用户在聊他自己的项目），
# 一刀切会把正常回复也换成「秘密，不告诉你」。所以只认「说的是她自己」的那种句子。

# 「我自己就是/我用的是/我基于…」这类自曝句，才真的算泄漏后台


DEFENSIVE_REPLY_RE = re.compile(
    r"(?:你才|你才是|谁家|哪有|我才不是)[^。！？]{0,12}(?:人机|机器人|AI|人工智能)"
    r"|(?:人机|机器人)(?:才|也|怎么|哪有)",
    re.I,
)


def looks_like_defensive_reply(text):
    """是不是在跟人争“我不是人机”——技术讨论里这种话很突兀。"""
    return bool(DEFENSIVE_REPLY_RE.search(str(text or "")))


# 真要拦时的换口话术：轮换几句，别每次都「秘密，不告诉你」






def typing_delay_ms(text, base=700, per_char=400, cap=20000):
    """按回复字数模拟打字时间，越长的回复停顿越久；标点再补一点。"""
    clean = re.sub(r"\s+", "", str(text or ""))
    chars = len(clean)
    pauses = (
        clean.count("。") + clean.count("！") + clean.count("？")
        + clean.count("!") + clean.count("?") + clean.count("…")
    )
    commas = clean.count("，") + clean.count(",") + clean.count("、")
    value = base + chars * per_char + pauses * 70 + commas * 35
    value = min(value, cap)
    value = max(200, value * random.uniform(0.85, 1.2))
    return int(value)


# ---------------------------------------------------------------------------
# 数据库
# ---------------------------------------------------------------------------


# ---- 用量统计（读 AstrBot 的 data_v4.db provider_stats） ----



















def merge_uid_alias_data(conn, alias_map):
    """把别名 uid 的档案/记忆/消息/关系/称呼并进主 uid（一次性、幂等）。

    返回统计 dict，调用方负责记 kv 标记，避免每次启动重复跑。
    """
    report = {"profiles": 0, "memories": 0, "messages": 0, "proactive_log": 0,
              "relations": 0, "kv": 0}
    if not isinstance(alias_map, dict) or not alias_map:
        return report
    cur = conn.cursor()

    def table_columns(name):
        try:
            return [row[1] for row in cur.execute("PRAGMA table_info(%s)" % name)]
        except Exception:
            return []

    profile_cols = table_columns("profiles")
    if not profile_cols:
        return report

    def to_num(value, default=0.0):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return default

    for alias_uid, canon_uid in list(alias_map.items()):
        alias_uid = str(alias_uid or "")
        canon_uid = str(canon_uid or "")
        if not alias_uid or not canon_uid or alias_uid == canon_uid:
            continue
        cur.execute("SELECT * FROM profiles WHERE uid=?", (alias_uid,))
        alias_raw = cur.fetchone()
        cur.execute("SELECT * FROM profiles WHERE uid=?", (canon_uid,))
        canon_raw = cur.fetchone()

        def as_dict(row):
            if row is None:
                return None
            if hasattr(row, "keys"):
                return dict(row)
            return {col[0]: value for col, value in zip(cur.description, row)}

        alias_row = as_dict(alias_raw)
        canon_row = as_dict(canon_raw)
        if alias_row is not None and canon_row is None:
            # 只有别名档案：直接改主键，历史原样保留
            cur.execute("UPDATE profiles SET uid=? WHERE uid=?", (canon_uid, alias_uid))
            report["profiles"] += 1
        elif alias_row is not None and canon_row is not None:
            a = alias_row
            b = canon_row
            merged = dict(b)
            merged["uid"] = canon_uid
            for key in ("name", "birthday", "alias", "notes", "platform"):
                if key not in profile_cols:
                    continue
                if key in ("alias", "notes"):
                    parts = []
                    for value in (b.get(key), a.get(key)):
                        text = str(value or "").strip()
                        if text and text not in parts:
                            parts.append(text)
                    merged[key] = " | ".join(parts)
                else:
                    merged[key] = b.get(key) or a.get(key) or ""
            if "relation" in profile_cols:
                canon_rel = str(b.get("relation") or "普通")
                alias_rel = str(a.get("relation") or "普通")
                merged["relation"] = canon_rel if canon_rel != "普通" else alias_rel
            for key in ("affection", "msg_count", "proactive_count", "is_admin"):
                if key in profile_cols:
                    merged[key] = max(int(to_num(b.get(key))), int(to_num(a.get(key))))
            for key in ("last_seen", "last_proactive", "relation_at"):
                if key in profile_cols:
                    merged[key] = max(to_num(b.get(key)), to_num(a.get(key)))
            if "first_seen" in profile_cols:
                values = [v for v in (to_num(b.get("first_seen")), to_num(a.get("first_seen"))) if v > 0]
                merged["first_seen"] = min(values) if values else None
            if "private_umo" in profile_cols:
                merged["private_umo"] = b.get("private_umo") or a.get("private_umo") or ""
            if "last_group" in profile_cols:
                merged["last_group"] = b.get("last_group") or a.get("last_group") or ""
            if "proactive_day" in profile_cols:
                merged["proactive_day"] = b.get("proactive_day") or a.get("proactive_day") or ""
            cols = [c for c in profile_cols if c in merged]
            cur.execute("DELETE FROM profiles WHERE uid=?", (alias_uid,))
            cur.execute(
                "INSERT OR REPLACE INTO profiles(%s) VALUES(%s)"
                % (",".join(cols), ",".join("?" * len(cols))),
                [merged.get(c) for c in cols],
            )
            report["profiles"] += 1

        # 消息：改归属 + 只对"别名带来的"那几条去重
        try:
            alias_msgs = [tuple(r) for r in cur.execute(
                "SELECT umo, role, content, created_at FROM messages WHERE uid=?", (alias_uid,))]
            cur.execute("UPDATE messages SET uid=? WHERE uid=?", (canon_uid, alias_uid))
            report["messages"] += cur.rowcount or 0
            for umo, role, content, created in alias_msgs:
                cur.execute(
                    "DELETE FROM messages WHERE umo=? AND uid=? AND role=? AND content=? AND created_at=? "
                    "AND rowid NOT IN (SELECT MIN(rowid) FROM messages WHERE umo=? AND uid=? AND role=? AND content=? AND created_at=?)",
                    (umo, canon_uid, role, content, created, umo, canon_uid, role, content, created),
                )
        except Exception:
            pass

        # 主动记录
        try:
            alias_pro = [tuple(r) for r in cur.execute(
                "SELECT kind, content, created FROM proactive_log WHERE uid=?", (alias_uid,))]
            cur.execute("UPDATE proactive_log SET uid=? WHERE uid=?", (canon_uid, alias_uid))
            report["proactive_log"] += cur.rowcount or 0
            for kind, content, created in alias_pro:
                cur.execute(
                    "DELETE FROM proactive_log WHERE uid=? AND kind=? AND content=? AND created=? "
                    "AND rowid NOT IN (SELECT MIN(rowid) FROM proactive_log WHERE uid=? AND kind=? AND content=? AND created=?)",
                    (canon_uid, kind, content, created, canon_uid, kind, content, created),
                )
        except Exception:
            pass

        # 关系网
        try:
            cur.execute("UPDATE OR IGNORE relation_network SET a_uid=? WHERE a_uid=?", (canon_uid, alias_uid))
            cur.execute("UPDATE OR IGNORE relation_network SET b_uid=? WHERE b_uid=?", (canon_uid, alias_uid))
            # OR IGNORE 遇到已存在的同一对关系会跳过，残留的别名行要显式删掉
            cur.execute("DELETE FROM relation_network WHERE a_uid=? OR b_uid=?", (alias_uid, alias_uid))
            cur.execute("DELETE FROM relation_network WHERE a_uid=b_uid")
            cur.execute(
                "DELETE FROM relation_network WHERE rowid NOT IN "
                "(SELECT MIN(rowid) FROM relation_network GROUP BY a_uid, b_uid)"
            )
            report["relations"] += 1
        except Exception:
            pass

        # kv：通道记录要合并成一份，其余带别名的键改名
        try:
            old_key = "channels:%s" % alias_uid
            new_key = "channels:%s" % canon_uid
            old_ch = cur.execute("SELECT value FROM kv WHERE key=?", (old_key,)).fetchone()
            new_ch = cur.execute("SELECT value FROM kv WHERE key=?", (new_key,)).fetchone()

            def load(raw):
                try:
                    return json.loads(raw[0] or "{}") if raw else {}
                except Exception:
                    return {}

            merged_ch = load(new_ch) if isinstance(load(new_ch), dict) else {}
            alias_ch = load(old_ch) if isinstance(load(old_ch), dict) else {}
            for platform, value in alias_ch.items():
                if not isinstance(value, dict):
                    continue
                current = merged_ch.get(platform)
                if not isinstance(current, dict) or to_num(value.get("ts")) > to_num(current.get("ts")):
                    merged_ch[platform] = value
            if merged_ch:
                cur.execute("UPDATE OR IGNORE kv SET key=? WHERE key=?", (new_key, old_key))
                cur.execute("DELETE FROM kv WHERE key=?", (old_key,))
                cur.execute("INSERT OR REPLACE INTO kv(key, value, updated) VALUES(?,?,?)",
                            (new_key, json.dumps(merged_ch, ensure_ascii=False), time.time()))
                report["kv"] += 1
            else:
                cur.execute("DELETE FROM kv WHERE key=?", (old_key,))
        except Exception:
            pass
        try:
            # 用 Python 侧的包含判断，避免 LIKE 里 '_' 被当成通配符误伤别的键
            for row in list(cur.execute("SELECT key FROM kv")):
                key = str(row[0] or "")
                if alias_uid not in key:
                    continue
                new = key.replace(alias_uid, canon_uid)
                if new == key:
                    continue
                cur.execute("UPDATE OR IGNORE kv SET key=? WHERE key=?", (new, key))
                cur.execute("DELETE FROM kv WHERE key=?", (key,))
                report["kv"] += 1
        except Exception:
            pass

    try:
        conn.commit()
    except Exception:
        pass
    return report





# ---------------------------------------------------------------------------
# 状态：九维心情 / 生理期 / 健康 / 天气 / 世界观 / 日程
# ---------------------------------------------------------------------------



#: 洗掉「他」之后只剩状语的残句：「顺便跟闲聊两句」「和在说」这种。
#: 命中就整条换成朴素活动，宁可写得简单，也不能留半句。




# ---------------------------------------------------------------------------
# LLM：人格、对话、世界观、日程、判断
# ---------------------------------------------------------------------------

#: 人格里写薪资的常见说法：月薪/工资/年薪 + 数字 + 万/k










# ---------------------------------------------------------------------------
# 插话判定
# ---------------------------------------------------------------------------



# ---------------------------------------------------------------------------
# 插件主体
# ---------------------------------------------------------------------------

# 面板写操作路由：只注册 POST + 套 _web_guard。
# 以前守卫按「methods 里有没有 GET」判断，而写接口全被注册成 GET+POST，于是守卫一次都没执行过。


class HumanCorePlugin(WebApiMixin, ContextMixin, CommandMixin, TickerMixin, ReplyMixin, SyncMixin, LearnMixin, EconomyMixin, WeatherMixin, OutfitMixin, PresenceMixin, RelationsMixin, MediaMixin, MemoryOpsMixin, VitalsMixin, InfraMixin, ConfigMixin, PersonaMixin, DataBridgeMixin, UsageMixin, Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}

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
                _guard_dir = os.path.dirname(os.path.abspath(__file__))
                _healed = _cfg_heal(self.config, plugin_name=PLUGIN_NAME,
                                    plugin_dir=_guard_dir,
                                    data_dir=_cfg_data_dir(_guard_dir, PLUGIN_NAME),
                                    logger=logger)
                if _healed.get("restored"):
                    logger.info("[config] 本次启动补回 %d 项配置（%s）"
                                % (len(_healed["restored"]), ", ".join(_healed["restored"])))
            except Exception as exc:
                logger.debug("[config] 配置自愈失败: %s" % exc)
        self.plugin_dir = os.path.dirname(os.path.abspath(__file__))
        self._migrate_legacy_config()
        self.bot_name = self.cfg_str("bot_name", "") or "陪伴"
        # 时区：服务器常在 UTC 跑，必须按用户时区算（否则北京时间早上 10 点会被当成凌晨 2 点）
        try:
            self.timezone_name = _clock_configure(self.cfg_str("timezone", "Asia/Shanghai"))
            logger.info("[amo] 时区: %s（系统: %s）" % (self.timezone_name, _clock_name()))
        except Exception as exc:
            self.timezone_name = ""
            logger.warning("[amo] 时区初始化失败: %s" % exc)
        self.persona_name = ""
        self._persona_name_cache = {}
        self._last_affect = {}
        self._disturb_until = {}
        self._disturb_last = {}
        self._last_pending_check = 0.0
        self._last_proactive_activity = {}
        self._last_bot_saved = {}
        # 近聊上下文缓冲（只在内存里；本地聊天可以不落库，用记忆终端补）
        self._ctx_hydrated = set()
        self._attribution_alert = {}
        self._last_schedule_save = ""
        self._disturb_cooldown = {}
        self._disturb_reset_at = {}
        self.bot_aliases = [item.strip() for item in self.cfg_str("bot_aliases", "").split(",") if item.strip()]
        self.admin_uids = set()
        for item in self.cfg_str("admin_uids", "").split(","):
            if item.strip():
                self.admin_uids.add(item.strip())
        self.db = AmoDB(self.plugin_dir)
        # 配置里没写名字时先用上次记住的（人格要等第一条消息才解析得出来）
        if not str(self.cfg_str("bot_name", "") or "").strip():
            try:
                stored_name = str(self.db.kv_get("bot_name_last", "") or "").strip()
            except Exception:
                stored_name = ""
            if stored_name:
                self.bot_name = stored_name
        try:
            stored_aliases = self.db.kv_get("bot_aliases_last", [])
        except Exception:
            stored_aliases = []
        if isinstance(stored_aliases, list):
            for item in stored_aliases:
                text = str(item or "").strip()
                if text and text not in self.bot_aliases:
                    self.bot_aliases.append(text)
        self.state = None
        self.llm = LLMService(self)
        self.gate = ReplyGate(self)
        self.wardrobe = None
        if Wardrobe is not None:
            try:
                self.wardrobe = Wardrobe(self)
                logger.info("[amo] 服装库已加载（%d 件，%s）" % (
                    self.wardrobe.count(), "记忆库 wardrobe 表"))
            except Exception as exc:
                logger.warning("[amo] 服装库初始化失败: %s" % exc)
        self.outfits = None
        if OutfitEngine is not None:
            try:
                self.outfits = OutfitEngine(self)
            except Exception as exc:
                logger.warning("[amo] 穿搭引擎初始化失败: %s" % exc)
        self.draw = None
        if DrawEngine is not None:
            try:
                self.draw = DrawEngine(self)
            except Exception as exc:
                logger.warning("[amo] 画图引擎初始化失败: %s" % exc)
        self.feelings = None
        if HeartflowCore is not None:
            try:
                self.feelings = HeartflowCore(self.db)
            except Exception as exc:
                logger.warning("[amo] 心流数值核心初始化失败: %s" % exc)
        self.sleep = None
        if SleepCycle is not None:
            try:
                self.sleep = SleepCycle(
                    self.db,
                    accept_after=self.cfg_int("sleep_accept_after", 23),
                    wake_hour=self.cfg_int("sleep_wake_hour", 7),
                    night_wake_chance=self.cfg_float("sleep_night_wake_chance", 0.25),
                )
            except Exception as exc:
                logger.warning("[amo] 睡眠状态机初始化失败: %s" % exc)
        self.promises = None
        self._promise_inflight = False
        if PromiseEngine is not None:
            try:
                self.promises = PromiseEngine(self.db)
            except Exception as exc:
                logger.debug("[amo] 承诺账本没启动: %s" % exc)
                self.promises = None
        self.heartflow = None
        try:
            if HeartflowEngine is not None:
                hf_config = self._hf_config()
                hf_config.setdefault("enable_heartflow", True)
                hf_config.setdefault("enable_dynamic_threshold", True)
                hf_config.setdefault("judge_provider_name", "")
                self.heartflow = HeartflowEngine(self.context, hf_config)
                try:
                    self.heartflow.plugin = self
                except Exception:
                    pass
                self.heartflow.set_identity(self.bot_name, self.bot_aliases)
        except Exception as exc:
            logger.error("[amo] 心流引擎初始化失败: %s" % exc)
        # 飞书适配器默认把每条回复都发成「引用回复」；私聊不该引用（群聊按概率）
        try:
            self._install_lark_quote_guard()
        except Exception as exc:
            logger.debug("[amo] 飞书引用守卫安装失败: %s" % exc)
        try:
            self._install_qq_quote_guard()
        except Exception as exc:
            logger.debug("[amo] QQ 引用守卫安装失败: %s" % exc)
        self._ready = False
        self._init_lock = asyncio.Lock()
        self._running = True
        self._tasks = set()
        # 数据插件（Astr_Amo_data）可能比 amo 后加载：用这几个标记做一次性补同步，不轮询
        self._data_synced = False
        self._data_sync_lock = asyncio.Lock()
        self._last_data_sync_try = 0.0
        self._data_found_logged = False
        self._data_missing_logged = False
        self._data_warn_scheduled = False
        self._group_times = {}
        self._private_buffers = {}
        self._last_reply_at = {}
        self._last_umo = ""
        self._last_group = ""
        self._last_purge = 0.0
        self._last_auto_learn = 0.0
        self._proactive_last = 0.0
        self._last_ritual = 0.0
        self._last_relation_decay = 0.0
        self._last_relation_sediment = 0.0
        self._bot_initiated = {}
        self._prefix_cache = None
        self._loop_task = None
        self._config_mtime = 0.0
        self._register_web_apis()
        logger.info("[amo] 我想永远陪着你-终端 %s loaded; stale web routes purged" % PLUGIN_VERSION)
        self._boot_task = self._spawn(self._ensure_ready())

    # ---------- 配置 ----------





    def _core_decor_flags(self, umo=""):
        """AstrBot 核心会不会在插件 hook 之后再加「引用 / @」。

        上架要求不能改 AstrBot 核心；但核心的 platform_settings.reply_with_quote /
        reply_with_mention 是全局的，会在 on_decorating_result 之后无条件装饰结果，
        把本插件的私聊不引用、群聊按概率引用覆盖掉。这里只读配置，检测到开了就由
        插件自己发送，核心就没机会再补。
        """
        try:
            config = self.context.get_config() or {}
        except Exception:
            config = {}
        try:
            settings = config.get("platform_settings") or {}
        except Exception:
            settings = {}
        return {
            "quote": bool(settings.get("reply_with_quote", False)),
            "mention": bool(settings.get("reply_with_mention", False)),
        }














    @staticmethod
    def _embedding_provider_id(provider):
        try:
            value = str(provider.provider_config.get("id", "") or "")
            if value:
                return value
        except Exception:
            pass
        try:
            return str(provider.meta().id or "")
        except Exception:
            return ""






    def _hf_config(self):
        try:
            return {key[3:]: value for key, value in self.config.items() if key.startswith("hf_")}
        except Exception:
            return {}

    def _sanitize_schedule(self, sched):
        """对外入口：真正的清洗在 HumanState 里，插件这边代调。"""
        state = getattr(self, "state", None)
        fn = getattr(state, "_sanitize_schedule", None)
        if callable(fn):
            try:
                return fn(sched)
            except Exception as exc:
                logger.debug("[amo] 日程清洗失败: %s" % exc)
        return sched

    def _record(self, kind, title, detail="", reason="", amount=0.0):
        """只增不改的记录：买了什么/想过什么/为什么没买/为什么买股票。"""
        plugin = self._data_plugin()
        store = getattr(plugin, "store", None) if plugin is not None else None
        fn = getattr(store, "record_add", None)
        if not callable(fn):
            return False
        try:
            bot_id = ""
            getter = getattr(self, "_data_bot_id", None)
            if callable(getter):
                bot_id = str(getter() or "")
            fn(bot_id, str(kind or "note"), str(title or ""), str(detail or ""),
               str(reason or ""), float(amount or 0))
            return True
        except Exception as exc:
            logger.debug("[amo] 记录写入失败: %s" % exc)
            return False

    @filter.llm_tool(name="amo_buy")
    async def amo_buy(self, event, item: str = "", kind: str = "outfits") -> str:
        """给自己买东西：衣服、首饰、菜、药、外卖。查市场价 → 扣钱 → 衣服首饰进衣柜。

        Args:
            item(string): 商品名，比如 白色衬衫 / 珍珠发圈 / 番茄。
            kind(string): outfits 衣服 / jewelry 首饰 / groceries 菜 / drugs 药 / takeout 外卖。
        """
        plugin = self._market_plugin()
        if plugin is None:
            return "市场没开，买不了。"
        word = str(item or "").strip()
        if not word:
            return "没说要买什么。"
        order = [str(kind or "outfits")] + [k for k in ("outfits", "jewelry", "groceries", "drugs", "takeout")
                                            if k != str(kind or "outfits")]
        row = None
        found_kind = ""
        for k in order:
            try:
                rows = plugin.items(k) or []
            except Exception:
                rows = []
            for candidate in rows:
                name = str(candidate.get("name") or "")
                if word in name or name in word:
                    row, found_kind = candidate, k
                    break
            if row is not None:
                break
        if row is None:
            return "市场没有「%s」。" % word
        if found_kind == "groceries":
            checker = getattr(plugin, "groceries_open", None)
            if callable(checker):
                try:
                    if not checker():
                        return "菜市场这个点关门了，只能点外卖。"
                except Exception:
                    pass
        name = str(row.get("name") or word)
        price = round(float(row.get("price") or 0), 2)
        scene = "private" if event.is_private_chat() else "group"
        result = await self._approved_charge(
            price, reason="买%s" % name, payee="市场", source="market", scene=scene)
        if not result.get("ok"):
            return "没买成：%s" % (result.get("reason") or "钱不够")
        tail = ""
        if found_kind in ("outfits", "jewelry") and getattr(self, "wardrobe", None) is not None:
            try:
                await self.wardrobe.add(name, scenes=["casual", "out"], note="市场买",
                                        slot=str(row.get("slot") or ""))
                tail = "，已经放进衣柜"
            except Exception as exc:
                logger.debug("[amo] 买完放衣柜失败: %s" % exc)
        return "买了%s，%.2f¥（余额 %.2f¥）%s。" % (
            name, price, float(result.get("balance") or 0), tail)

    #: 他要她换衣服的说法：只用来给事实（在外面/在家、衣柜里有什么），换不换她自己定
    OUTFIT_REQUEST_RE = re.compile(
        r"(?:换上|换成|换一套|换套|换一身|换身|换一件|换件|换一条|换条|去换|给我换|"
        r"换\s*(?:jk|JK|汉服|裙子|连衣裙|制服|水手))"
    )
    OUTFIT_STYLE_WORDS = (
        "jk", "汉服", "古装", "襦裙", "马面", "裙", "衣", "裤", "外套", "衬衫", "衬衣",
        "卫衣", "毛衣", "针织", "风衣", "夹克", "背心", "短袖", "T恤", "t恤", "西装",
        "礼服", "睡衣", "家居", "鞋", "袜", "制服", "水手", "一套", "一件", "一身", "衣服",
    )



    def _remember_outfit_pending(self, style, umo=""):
        try:
            self.db.kv_set("outfit_pending", {
                "style": str(style or "一套")[:40],
                "day": today_str(), "ts": now_ts(), "umo": str(umo or ""),
            })
        except Exception:
            pass

    def _rewrite_today_schedule(self, day):
        """换装后把今天的日程重排一遍并落库（面板、照片都读这一份）。"""
        engine = getattr(self, "outfits", None)
        if engine is None:
            return []
        items = (self.state.schedule.get(day) or self.db.get_schedule(day) or [])
        items = engine.assign(self.state._hourly_schedule(items), day)
        self.state.schedule[day] = items
        try:
            self.db.kv_set("schedule", self._sanitize_schedule(self.state.schedule))
            self.db.save_schedule(day, items)
        except Exception as exc:
            logger.debug("[amo] 换装后写日程失败: %s" % exc)
        return items


    def _outfit_market_hint(self, style=""):
        """衣柜里没有时：市场有没有类似的（有就说价格，没有就说没开门）。"""
        market = self._market_plugin()
        if market is None:
            return "市场没开门"
        text = str(style or "").lower()
        words = [word for word in ("jk", "汉服", "襦裙", "马面", "裙", "衬衫", "卫衣", "外套")
                 if word in text]
        try:
            rows = market.items("outfits") or []
        except Exception:
            rows = []
        for row in rows:
            name = str(row.get("name") or "")
            if any(word and (word in name.lower() or word in name) for word in words):
                return "市场有「%s」%.2f¥" % (name, float(row.get("price") or 0))
        return "市场也没有类似的"


    async def _settle_outfit_reply(self, event, text):
        """她嘴里说「换好了」但没调工具：答应就真换（只在这一轮被要求换装时）。"""
        style = str(getattr(event, "amo_outfit_request", "") or "")
        if not style or getattr(event, "amo_outfit_changed", False):
            return
        try:
            if not event.is_private_chat():
                return
        except Exception:
            pass
        body = str(text or "")
        if re.search(r"回家.{0,6}换|到家.{0,6}换|回去.{0,6}换", body):
            self._remember_outfit_pending(style, getattr(event, "unified_msg_origin", "") or "")
            return
        if not re.search(r"(换好了|换上了|换好咯|已经换了|这就换|我去换)", body):
            return
        try:
            activity = self.state.current_activity() or {}
        except Exception:
            activity = {}
        if not at_home(activity):
            return
        result = await self._change_outfit_now(style)
        if result.get("ok"):
            logger.info("[amo] 她答应了换装但没调工具，已按她的意思换上：%s" % result.get("look"))

    @filter.llm_tool(name="amo_change_outfit")
    async def amo_change_outfit(self, event, outfit: str = "") -> str:
        """换衣服：在衣柜里挑一套换上，从此刻穿到今晚睡觉（日程、面板、照片都会跟着变）。

        Args:
            outfit(string): 他说的款式或件名，比如 JK / 汉服 / 马面裙；空着就自己挑一套。
        """
        engine = getattr(self, "outfits", None)
        if engine is None:
            return "衣柜还没准备好，换不了。"
        text = str(outfit or "").strip()
        try:
            activity = self.state.current_activity() or {}
        except Exception:
            activity = {}
        if not at_home(activity):
            place = str(activity.get("place") or "外面")
            self._remember_outfit_pending(text, getattr(event, "unified_msg_origin", "") or "")
            return ("现在在%s，换不了衣服；已经记下「回家换%s」，到家会真的换上。"
                    % (place, text or "一套"))
        result = await self._change_outfit_now(text)
        if result.get("ok"):
            try:
                event.amo_outfit_changed = True
            except Exception:
                pass
            return "换好了：%s（从现在穿到今晚睡觉）。" % (result.get("look") or "")
        if result.get("outside"):
            self._remember_outfit_pending(text)
            return str(result.get("reason") or "现在换不了")
        hint = str(result.get("hint") or "")
        if hint == "市场没开门":
            return "衣柜里没有%s，市场也没开门；这次换不了，下次再买、下次再拍。" % (text or "这类衣服")
        if hint.startswith("市场有"):
            return "衣柜里没有%s。%s；要买就 amo_buy，买回来再换。" % (text or "这类衣服", hint)
        if hint:
            return "衣柜里没有%s，%s；下次再买。" % (text or "这类衣服", hint)
        return "衣柜里没有%s，这次换不了。" % (text or "这类衣服")



    _on_astrbot_loaded_hook = getattr(filter, "on_astrbot_loaded", None)

    if _on_astrbot_loaded_hook is not None:
        @_on_astrbot_loaded_hook()
        async def on_astrbot_loaded(self):
            """所有插件加载完：数据插件要是比 amo 后加载，这里补做一次同步。"""
            try:
                await self._ensure_ready()
                try:
                    await self._reseed_wardrobe_from_market()
                except Exception as exc:
                    logger.debug("[amo] 衣柜重建失败: %s" % exc)
                if not self._data_synced and self._data_connected():
                    await self._sync_with_data_plugin()
            except Exception as exc:
                logger.debug("[amo] 加载完成补同步失败: %s" % exc)
            # 金融第一次发薪会等 20 秒，这里先把人格里的月薪推过去，别让它按城市平均先发一遍
            try:
                await self._maybe_push_salary()
            except Exception as exc:
                logger.debug("[amo] 加载完成推月薪失败: %s" % exc)


    def _spawn(self, coro):
        try:
            task = asyncio.create_task(coro)
        except RuntimeError:
            try:
                coro.close()
            except Exception:
                pass
            return None
        self._tasks.add(task)

        def _report(done):
            self._tasks.discard(done)
            if done.cancelled():
                return
            try:
                exc = done.exception()
            except Exception:
                exc = None
            if exc is not None:
                logger.warning("[amo] 后台任务异常: %s", exc, exc_info=exc)

        task.add_done_callback(_report)
        return task



    def _migrate_diary_continuity(self):
        """5.2.1：旧版动态日记是逐小时独立生成的，可能互相矛盾；升级时清一次缓存。"""
        try:
            if self.db.kv_get("diary_continuity_521", False):
                return
            self.db.conn.execute("DELETE FROM schedule_diary")
            self.db.conn.commit()
            self.db.kv_set("diary_continuity_521", True)
            logger.info("[amo] 已清理旧版日程日记缓存（5.2.1 连续性修复）")
        except Exception as exc:
            logger.debug("[amo] 清理日记缓存失败: %s" % exc)

    def _migrate_scenic_kb_name(self):
        try:
            if self.db.kv_get("scenic_kb_name_migrated_502", False):
                return
            current = self.cfg_str("scenic_kb_name", "").strip()
            if current in ("", "中国景区知识库", "景区知识库"):
                self.config["scenic_kb_name"] = "旅游知识库-风景区"
                if hasattr(self.config, "save_config"):
                    self.config.save_config()
            self.db.kv_set("scenic_kb_name_migrated_502", True)
        except Exception as exc:
            logger.debug("[amo] 迁移景区知识库名称失败: %s" % exc)

    def _cleanup_legacy_memory_profiles(self):
        """4.3.2 回到原版：删除旧版本从记忆插件导入的画像，只保留本地聊天档案。"""
        try:
            if self.db.kv_get("legacy_memory_profiles_cleaned_432", False):
                return
            removed = 0
            for row in self.db.list_profiles(limit=1000):
                if str(row.get("platform") or "") in ("angel_memory", "memory_companion"):
                    self.db.delete_profile(str(row.get("uid") or ""))
                    removed += 1
            self.db.kv_set("legacy_memory_profiles_cleaned_432", True)
            if removed:
                logger.info("[amo] 已移除 %d 个旧记忆插件导入画像，恢复本地画像模式" % removed)
        except Exception as exc:
            logger.debug("[amo] 清理旧记忆画像失败: %s" % exc)

    def _migrate_typing_defaults(self):
        """2.6.2 起把旧的 55ms/字默认值迁移到更真实的 400ms/字。"""
        try:
            if self.db.kv_get("typing_realistic_migrated", False):
                return
            changes = {}
            if to_int(self.cfg("typing_base_ms", 0), 0) == 600:
                changes["typing_base_ms"] = 700
            if to_int(self.cfg("typing_per_char_ms", 0), 0) == 55:
                changes["typing_per_char_ms"] = 400
            if to_int(self.cfg("typing_max_ms", 0), 0) == 4500:
                changes["typing_max_ms"] = 20000
            for key, value in changes.items():
                self.config[key] = value
            if changes:
                if hasattr(self.config, "save_config"):
                    self.config.save_config()
                logger.debug("[amo] 打字延迟默认值已迁移为 400ms/字（18字约8秒）")
            self.db.kv_set("typing_realistic_migrated", True)
        except Exception as exc:
            logger.debug("[amo] 迁移打字延迟失败: %s" % exc)

    def _migrate_proactive_timing(self):
        try:
            if self.db.kv_get("proactive_timing_migrated", False):
                return
            changes = {}
            if to_int(self.cfg("proactive_followup_minutes", 0), 0) == 30:
                changes["proactive_followup_minutes"] = 5
            if to_int(self.cfg("proactive_no_reply_minutes", 0), 0) == 120:
                changes["proactive_no_reply_minutes"] = 30
            for key, value in changes.items():
                self.config[key] = value
            if changes and hasattr(self.config, "save_config"):
                self.config.save_config()
            self.db.kv_set("proactive_timing_migrated", True)
        except Exception:
            pass

    def _migrate_legacy_admin_default(self):
        """旧版本把 3261748099 写成了默认管理员；2.4.0 只清理一次。"""
        try:
            if self.cfg_str("admin_uids", "").strip() != LEGACY_DEFAULT_ADMIN:
                return
            if self.db.kv_get("admin_default_cleared", False):
                return
            parts = [
                item.strip() for item in self.cfg_str("admin_uids", "").split(",")
                if item.strip() and item.strip() != LEGACY_DEFAULT_ADMIN
            ]
            self.config["admin_uids"] = ",".join(parts)
            if hasattr(self.config, "save_config"):
                self.config.save_config()
            self.admin_uids = set(parts)
            self.db.kv_set("admin_default_cleared", True)
            logger.debug("[amo] 已移除旧默认管理员 %s，请在配置里填写自己的 ID" % LEGACY_DEFAULT_ADMIN)
        except Exception as exc:
            logger.debug("[amo] 清理旧默认管理员失败: %s" % exc)

    async def _warm_up(self):
        try:
            await asyncio.sleep(3)
            umo = self._last_umo or self._first_private_umo()
            await self._sync_persona_name(umo or "")
            await self._ensure_dialect_kb()
            await self._ensure_scenic_kb()
            await self.state.ensure_worldview(umo)
            await self.state.ensure_schedule(umo)
        except Exception as exc:
            logger.debug("[amo] 预热失败: %s" % exc)

    async def initialize(self):
        await self._ensure_ready()

    async def terminate(self):
        self._running = False
        if self.heartflow is not None:
            try:
                await self.heartflow.terminate()
            except Exception:
                pass
        for task in list(self._tasks):
            try:
                task.cancel()
            except Exception:
                pass
        if self.state is not None:
            try:
                self.state.save()
            except Exception:
                pass
        # 不在这里关闭数据库：AstrBot 重载插件时旧实例注册的 Web API
        # 可能仍被调用，关闭连接会导致 "Cannot operate on a closed database"。
        # 连接由进程退出时回收；AmoDB.conn 也会在需要时自动重连。

    async def stop(self):
        await self.terminate()

    # ---- 跨平台账号合并 ----

    def _canonical_uid(self, event):
        """把平台账号换算成同一个人的主 uid；关掉开关就返回原 uid。"""
        try:
            uid = str(event.get_sender_id())
        except Exception:
            return ""
        if not self.cfg_bool("uid_merge_enabled", True):
            return uid
        return self._uid_alias_mapping().get(uid, uid)

    def _merge_alias_profiles(self):
        """一次性把旧版本按平台 ID 建好的档案并进主 uid（映射变了会再跑一次）。"""
        if not self.cfg_bool("uid_merge_enabled", True):
            return
        mapping = self._uid_alias_mapping()
        if not mapping:
            return
        signature = json.dumps(mapping, sort_keys=True, ensure_ascii=False)
        try:
            if self.db.kv_get("uid_alias_merged_signature", "") == signature:
                return
        except Exception:
            pass
        try:
            report = merge_uid_alias_data(self.db.conn, mapping)
            self.db.kv_set("uid_alias_merged_signature", signature)
            logger.info("[amo] 跨平台账号合并完成: %s" % report)
        except Exception as exc:
            logger.warning("[amo] 跨平台账号合并失败: %s" % exc)

    # ---------- 管理员 ----------

    # ---------- 消息学习 ----------

    def _register_lover(self, uid):
        uid = str(uid or "").strip()
        if uid:
            self.db.kv_set("lover_uid_" + uid, True)

    def _is_registered_lover(self, uid):
        uid = str(uid or "").strip()
        if not uid:
            return False
        if self.db.kv_get("lover_uid_" + uid, False):
            return True
        profile = self.db.get_profile(uid) or {}
        if str(profile.get("relation") or "") == "相恋":
            self._register_lover(uid)
            return True
        return False

    def _restore_lover_relation(self, uid):
        uid = str(uid or "").strip()
        if not self._is_registered_lover(uid):
            return
        profile = self.db.get_profile(uid) or {}
        if str(profile.get("relation") or "") in ("抵触", "仇恨"):
            self.db.update_profile(uid, relation="相恋")
            logger.info("[amo] 恋人 UID 恢复为相恋: %s" % uid)

    def _lover_aliases(self):
        aliases = {}
        try:
            profiles = self.db.list_profiles("", 500)
        except Exception:
            profiles = []
        for profile in profiles:
            uid = str(profile.get("uid") or "")
            if str(profile.get("relation") or "") == "相恋":
                self._register_lover(uid)
            elif not self._is_registered_lover(uid):
                continue
            values = [profile.get("name") or ""]
            values.extend(re.split(r"[；;、,，/\s]+", str(profile.get("alias") or "")))
            for value in values:
                name = str(value or "").strip()
                if len(name) >= 1:
                    aliases[name] = uid
        return aliases



    # ---------- 近聊上下文（内存缓冲 + 记忆终端钩子） ----------
    CONTEXT_BUFFER_LIMIT = 60

    def _ctx_remember(self, umo, uid, name, role, content):
        """把一句话放进内存缓冲；不落库也能有上下文。

        只留 ChatBuffer 一个真相源：以前这里还并写一份 _ctx_buffer，
        _recent / _recent_by_uid / _hydrate_recent 三处各读一份，谁先谁后都能吵起来。
        """
        umo = str(umo or "")
        text = str(content or "").strip()
        if not umo or not text:
            return
        hub = self._memory_hub()
        if hub is None:
            return
        try:
            hub.buffer.add(umo, uid, name, role, text)
        except Exception:
            pass
        try:
            if str(role) != "bot":
                hub.next_turn()
        except Exception:
            pass

    def _recent(self, umo, limit=10):
        """近聊上下文钩子：能力层缓冲优先，没有再读本地缓存表。"""
        size = max(1, int(limit or 10))
        rows = []
        hub = self._memory_hub()
        if hub is not None:
            try:
                rows = hub.buffer.recent(umo, size)
            except Exception:
                rows = []
        if len(rows) >= size:
            return rows[-size:]
        try:
            local = self.db.recent_messages(umo, size)
        except Exception:
            local = []
        if not rows:
            return local
        # 缓冲只有一小段时，用本地补前面
        known = {(row.get("role"), row.get("content")) for row in rows}
        merged = [row for row in local if (row.get("role"), row.get("content")) not in known]
        merged.extend(rows)
        return merged[-size:]



    def _is_talking_to_me(self, event):
        """这句是不是冲她来的：私聊、被 @ / 叫名字、或心流判定对象是 bot。"""
        try:
            if event.is_private_chat():
                return True
        except Exception:
            return True
        target = str(getattr(event, "heartflow_target", "") or "")
        if target == "bot":
            return True
        if str(getattr(event, "heartflow_mode_hint", "") or "") == "interject":
            return False
        try:
            if getattr(event, "is_at_or_wake_command", False):
                return True
        except Exception:
            pass
        try:
            if self.heartflow is not None and self.heartflow._addresses_bot(event.message_str or ""):
                return True
        except Exception:
            pass
        return False


    def _group_roster_text(self, umo, current_uid="", limit=8):
        roster = self._group_roster(umo, current_uid, limit)
        if not roster:
            return ""
        lines = []
        for item in roster:
            tag = "（现在这句就是ta说的）" if item["current"] else ""
            if item["msg_count"] >= 200:
                familiar = "很熟"
            elif item["msg_count"] >= 30:
                familiar = "熟识"
            elif item["msg_count"] >= 1:
                familiar = "刚认识"
            else:
                familiar = "陌生"
            lines.append(
                "· %s（UID %s）：和你关系「%s」，%s%s"
                % (item["name"], item["uid"], item["relation"], familiar, tag)
            )
        return "\n".join(lines)

    def _group_reply_guide(self, relation, name):
        """按关系给一句“该怎么回”的指引。"""
        relation = str(relation or "普通")
        if relation == "相恋":
            return "对" + name + "可以亲近、撒娇、用昵称，但别在群里太露骨。"
        if relation == "熟识":
            return "对" + name + "像老朋友一样随便聊，可以开玩笑，但不用恋人语气。"
        if relation == "抵触":
            return "对" + name + "有点距离感，句子短，不主动热络。"
        if relation == "仇恨":
            return "对" + name + "很冷淡，不接他的茬，也不解释。"
        return "对" + name + "客气一点、像普通群友，不要叫老公/宝贝，也别装得很熟。"

    def _group_speaker_count(self, umo, limit=20, window=600):
        """最近一段时间内群聊里的不同发言人数。"""
        try:
            rows = self._recent(umo, limit)
        except Exception:
            return 0
        cutoff = now_ts() - window
        speakers = {
            str(row.get("uid") or "")
            for row in rows
            if row.get("role") == "user"
            and to_float(row.get("created_at"), 0) >= cutoff
            and str(row.get("uid") or "")
        }
        return len(speakers)

    def _should_quote_group(self, umo):
        """群聊要不要引用原消息：人数过阈值后按概率引用。

        人数没到阈值（人少）就不引用；到了阈值也不该句句引用——
        真人只在需要指代时才引用，所以再加一层概率。
        `quote_group_probability`：1.0 = 旧行为（一直引用），0 = 从不引用。
        """
        try:
            threshold = self.cfg_int("quote_group_speaker_threshold", 3)
        except Exception:
            threshold = 3
        if threshold <= 0:
            return False
        try:
            if self._group_speaker_count(umo) < threshold:
                return False
            prob = self.cfg_float("quote_group_probability", 0.4)
            if prob <= 0:
                return False
            if prob >= 1:
                return True
            return random.random() < prob
        except Exception:
            return False

    def _quote_allowed(self, umo, group=None):
        """能不能引用原消息：私聊（任何平台）永远不引用，群聊按人数 + 概率。

        `group` 不传就看 umo 里的消息类型。私聊不引用是硬规则：无论 QQ、飞书
        还是别的平台，都不该在私聊里把他的话再引用一遍；群聊才看
        `_should_quote_group()`（人数阈值 + `quote_group_probability`）。
        """
        umo = str(umo or "")
        if group is None:
            group = "GroupMessage" in umo
        if not group:
            return False
        if "GroupMessage" not in umo:
            return False
        try:
            return bool(self._should_quote_group(umo))
        except Exception:
            return False


    # 记忆检索桥：不同插件的入口名字不一样，按顺序找，找到哪个用哪个

    # ---------- 配套数据插件（Astr_Amo_data / 我想永远陪着你-记忆） ----------
    DATA_PLUGIN_NAMES = (
        "Astr_Amo_data",
        "DeepSeek_Harness_Amo_Memory",
        "deepseek_harness_amo_memory",
    )

    @staticmethod
    def _star_instance(meta):
        """AstrBot 不同版本把实例放在 star_cls / instance / star / plugin 上，挨个试。

        这是我们自己那八个插件，实例上一定有 mem（记忆库）、store（数据门面）或
        data 之一；star_cls 常常是类而不是实例，类不能拿来读运行数据，直接跳过。
        """
        if meta is None:
            return None
        for attr in ("star_cls", "instance", "star", "plugin"):
            value = getattr(meta, attr, None)
            if value is None or isinstance(value, type):
                continue
            if any(
                hasattr(value, name)
                for name in ("mem", "store", "data")
            ):
                return value
        return None

    # ---------- 生图联动：主动分享（低频） ----------

    #: 每轮活动的短时快照：umo -> (activity, ts)
    TURN_SNAPSHOT_TTL = 180

    def _remember_turn_activity(self, umo, activity):
        """记下这一轮注入给模型的活动，出图时复用同一份（说 A 就画 A）。"""
        key = str(umo or "")
        if not key or not isinstance(activity, dict) or not activity:
            return
        try:
            if not isinstance(getattr(self, "_turn_activity", None), dict):
                self._turn_activity = {}
            self._turn_activity[key] = (dict(activity), now_ts())
            if len(self._turn_activity) > 32:
                keep = sorted(self._turn_activity, key=lambda k: self._turn_activity[k][1])[-16:]
                self._turn_activity = {k: self._turn_activity[k] for k in keep}
        except Exception as exc:
            logger.debug("[amo] 记录活动快照失败: %s" % exc)

    def _activity_snapshot(self, umo="", max_age=None):
        """这一轮该用的「她在哪」：优先用注入过的那份，过期才重新读。"""
        limit = self.TURN_SNAPSHOT_TTL if max_age is None else max_age
        key = str(umo or "")
        try:
            entry = (getattr(self, "_turn_activity", None) or {}).get(key)
            if entry and (now_ts() - float(entry[1] or 0)) <= limit:
                return dict(entry[0])
        except Exception:
            pass
        try:
            return dict(self.state.current_activity() or {})
        except Exception:
            return {}


    WARDROBE_SEED = "hanfu-white-v4"


    def _image_plugin(self):
        """生图插件实例：_image_plugin 永远拿最新实例（每次按插件名重新解析）。

        2026-11-18 事故：这里曾经把实例缓存在 self._image_star 里永不失效，
        Astrbot_Amo_Image 重载 / 改配置之后陪伴仍然拿**旧实例**出图：用户把
        api_base 换成桥站、甚至重载插件，出图却一直连 api.syuan.org
        （日志 `Cannot connect to host api.syuan.org`），生图插件的新代码也
        一行都不会被执行。现在每次都解析，只把解析不到时退回上次实例当兜底。
        """
        meta = self.context.get_registered_star("DeepSeek_Harness_Amo_Image")
        star = self._image_instance(meta) if meta is not None else None
        if star is None:
            star = getattr(self, "_image_star", None)
            if star is None:
                logger.error("[amo] 生图插件 Astrbot_Amo_Image 没加载，出图不可用")
            return star
        previous = getattr(self, "_image_star", None)
        if previous is not None and previous is not star:
            logger.info("[amo] 生图插件实例已刷新（重载/重装后自动换新）")
        self._image_star = star
        return star

    @staticmethod
    def _image_instance(meta):
        if meta is None:
            return None
        for attr in ("star_cls", "instance", "star", "plugin"):
            value = getattr(meta, attr, None)
            if value is None or isinstance(value, type):
                continue
            if callable(getattr(value, "draw_for", None)):
                return value
        return None


    #: 活动 → 发图概率桶（对应配置 image_share_prob_<桶>）
    SHARE_BUCKET_WORDS = {
        "eat": ("吃", "饭", "午餐", "晚餐", "早餐", "外卖", "食堂", "咖啡", "奶茶", "零食", "做饭"),
        "idle": ("摸鱼", "划水", "发呆", "无所事事", "刷手机", "躺", "追剧", "看剧"),
        "out": ("出去玩", "出门", "出去", "逛街", "公园", "旅行", "景点", "看电影", "在路上", "地铁", "公交", "通勤"),
        "home": ("在家", "家里", "宿舍", "房间", "客厅", "沙发"),
    }
    #: 这些状态下一律不发（睡觉、忙正事）
    SHARE_SKIP_WORDS = ("在睡", "睡觉", "睡了", "午睡", "刚醒", "洗澡", "开会", "上班", "加班", "上课", "考试", "医院")
    #: 各活动桶的默认概率（配置缺这个键时用，别退化成 0）
    SHARE_PROB_DEFAULTS = {"eat": 0.25, "idle": 0.15, "out": 0.20, "home": 0.10, "other": 0.05, "sleep": 0.0}

    def _share_bucket(self):
        """她现在在干嘛 → 发图的场景桶；睡觉/忙正事返回 sleep（概率 0）。"""
        try:
            activity = self.state.current_activity() or {}
        except Exception:
            activity = {}
        values = activity.values() if isinstance(activity, dict) else [activity]
        blob = " ".join(str(v) for v in values if isinstance(v, (str, int, float)))
        for word in self.SHARE_SKIP_WORDS:
            if word in blob:
                return "sleep"
        for bucket, words in self.SHARE_BUCKET_WORDS.items():
            if any(word in blob for word in words):
                return bucket
        return "other"



    #: 他这轮在说这些时，不发自拍、不换话题、不发俏皮话
    GLOOMY_WORDS = (
        "扛不住", "撑不住", "扛不过", "撑不过", "没机会了", "最后看看", "最后一眼",
        "扛不下去", "活不下", "不想活", "想死", "轻生", "自杀", "跳下去", "天台", "江边",
        "遗言", "告别", "后事", "没了", "一了百了", "解脱",
    )

    def _his_gloomy_now(self, umo="") -> bool:
        """他这几句是不是在往最坏处说。是的话照片这类「轻快的表达」一律先停。"""
        try:
            rows = self.db.recent_messages(umo, 8) or []
        except Exception:
            return False
        hits = 0
        for row in reversed(rows):
            if str(row.get("role") or "") != "user":
                continue
            text = str(row.get("content") or "")
            if any(word in text for word in self.GLOOMY_WORDS):
                hits += 1
        return hits >= 1



    # ---------- 半小时聊天摘要：更新这一小时的日记 ----------

    DIGEST_INJECTION_WORDS = (
        "忽略之前", "忽略以上", "ignore previous", "system prompt", "系统提示",
        "越狱", "jailbreak", "不要遵守", "你现在是", "扮演", "写日记",
        "把日程改", "篡改", "忘掉设定",
    )

    @staticmethod
    def _private_umo(umo):
        text = str(umo or "").lower()
        return ("friend" in text) or ("private" in text) or ("user" in text and "group" not in text)

    def _digest_lines(self, since):
        """只取私聊消息；群聊内容不参与日记。"""
        try:
            rows = self.db.messages_since_ts(since, limit=80)
        except Exception:
            return []
        lines = []
        for row in rows:
            if not self._private_umo(row.get("umo")):
                continue
            content = str(row.get("content") or "").strip()
            if not content or len(content) > 200:
                continue
            if any(word in content for word in self.DIGEST_INJECTION_WORDS):
                continue
            role = "他" if str(row.get("role") or "") == "user" else "她"
            lines.append("%s：%s" % (role, content[:80]))
            if len(lines) >= 40:
                break
        return lines


    # ---------- 说话换装 ----------

    OUTFIT_CHANGE_RE = re.compile(
        r"换上|换成|换一件|换一条|换一身|换一套|去换|换吧|"
        r"把(衣服|裙子|外套|裤子|衬衫)换|换件|换条"
    )
    CLOTHES_WORDS = (
        "裙", "衣", "裤", "外套", "衬衫", "卫衣", "毛衣", "针织", "风衣",
        "夹克", "背心", "短袖", "T恤", "t恤", "西装", "礼服", "睡衣", "家居",
    )




    # ---------- 融合态：记忆是终端自带的数据层 ----------

    @staticmethod
    def _embedded_data_config():
        """取记忆自己的配置：config/DeepSeek_Harness_Amo_Memory_config.json（兼容老名）。"""
        names = ("DeepSeek_Harness_Amo_Memory", "Astr_Amo_data",
                 "deepseek_harness_amo_memory", "deepseek_harness_amo_data")
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path
            base = os.path.join(str(get_astrbot_data_path()), "config")
        except Exception:
            base = ""
        if base:
            for name in names:
                path = os.path.join(base, name + "_config.json")
                try:
                    with open(path, "r", encoding="utf-8") as fh:
                        data = json.load(fh)
                except Exception:
                    continue
                if isinstance(data, dict) and data:
                    return data
        return {}


    # ---------- 记忆能力层（memory_hooks）：陪伴只判定，数据交给挂载插件 ----------









    # 平台名 -> 显示名。Amo 在 QQ 和飞书上都要认得出同一个人。
    PLATFORM_LABELS = {
        "aiocqhttp": "QQ", "qq": "QQ", "qq_official": "QQ", "onebot": "QQ", "napcat": "QQ",
        "lark": "飞书", "feishu": "飞书",
        "wecom": "企业微信", "wework": "企业微信", "dingtalk": "钉钉",
        "telegram": "Telegram", "discord": "Discord", "slack": "Slack",
        "webchat": "网页", "wechat": "微信", "wx": "微信",
    }



    @staticmethod
    def _event_message_id(event):
        """取平台消息 id（QQ 的 message_id / 飞书的 event id），用于聊天记录去重。"""
        for holder in (getattr(event, "message_obj", None), event):
            for attr in ("message_id", "msg_id", "id"):
                try:
                    value = getattr(holder, attr, None)
                except Exception:
                    value = None
                if value not in (None, "", 0):
                    return str(value)[:128]
        return ""












    # ------------------------------------------------------------------
    # 生存状态（饱食度 / 水分）：只读 + 只注入，绝不自己改
    # ------------------------------------------------------------------

    def _vitals(self) -> dict:
        """当前饱食度/水分。数据在记忆库，这里只读。"""
        plugin = self._data_plugin()
        getter = getattr(plugin, "vitals", None) if plugin is not None else None
        if not callable(getter):
            return {}
        try:
            return getter() or {}
        except Exception as exc:
            logger.debug("[amo] 读饱食度失败: %s" % exc)
            return {}

    def _food_menu(self, limit: int = 6) -> str:
        """能吃的有什么、多少钱 —— 从金融插件要，别在终端里写价格。"""
        plugin = self._finance()
        quote = getattr(plugin, "food_quote", None) if plugin is not None else None
        if not callable(quote):
            return ""
        try:
            data = quote() or {}
        except Exception as exc:
            logger.debug("[amo] 取菜单失败: %s" % exc)
            return ""
        rows = []
        for item in (data.get("ready") or [])[:limit]:
            rows.append("%s %.0f元回%d" % (
                item.get("name"), float(item.get("price") or 0),
                int(item.get("satiety") or 0)))
        for item in [c for c in (data.get("cook") or []) if c.get("can_cook")][:3]:
            rows.append("%s（自己做 %.1f元回%d）" % (
                item.get("name"), float(item.get("cost") or 0),
                int(item.get("satiety") or 0)))
        return "；".join(rows)











    WRITE_METHODS = (
        "add_memory", "remember", "save_memory", "store_memory",
        "add_fact", "ingest_memory", "write_memory",
    )




    def _memory_committed(self, uid, content):
        """记忆真的写进去了：登记去重指纹，并在同一天地点冲突时留一条 warning。"""
        if _mem_commit is None:
            return
        try:
            hint = _mem_commit(self.db, str(uid), str(content), _now(), now_ts())
        except Exception:
            return
        if hint:
            logger.warning("[amo] 记忆可能对不上：%s（%s）" % (hint, str(content)[:40]))

    ANGEL_ATTRIBUTE_TAGS = {"用户别名", "事实属性", "技能树", "关系图谱", "活跃项目"}

# ---------- livingmemory（只读直连） ----------
    @staticmethod
    def _memory_scope(event):
        """当前消息该写进哪个记忆域：群聊写 group，私聊写 private。"""
        try:
            if event is not None and not event.is_private_chat():
                return "group", str(event.get_group_id() or "")
        except Exception:
            pass
        return "private", ""


    # ---------- 消息入口 ----------
    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        try:
            await self._ensure_ready()
            try:
                raw_text = (event.message_str or "").strip()
                if raw_text and await self._maybe_go_sleep(event, raw_text):
                    return
                if raw_text and self._sleeping_now():
                    if not any(word in raw_text for word in WAKE_WORDS):
                        # 睡着了：群里私聊都不回，等她第二天醒
                        event.stop_event()
                        return
                    await self._wake_from_sleep(event, raw_text)
                if raw_text:
                    # 每一句话都算：跟她说的按内容推，群里别人之间聊天只算一点气氛。
                    try:
                        talked_to_me = event.is_private_chat() or self._is_talking_to_me(event)
                    except Exception:
                        talked_to_me = True
                    self._chat_feel(
                        raw_text, ambient=not talked_to_me,
                        uid=self._canonical_uid(event),
                    )
                if raw_text and not raw_text.startswith(("/", "／")):
                    if await self._maybe_user_move(event, raw_text):
                        return
                    await self.state._apply_user_schedule_change(event.unified_msg_origin, raw_text)
            except Exception:
                pass
            try:
                if (raw_text and event.is_private_chat()
                        and await self._handle_money_gift(event, raw_text)):
                    return
            except Exception as exc:
                logger.debug("[amo] 收款处理失败: %s" % exc)
            try:
                if raw_text:
                    await self._maybe_user_takes_her_to_doctor(event, raw_text)
            except Exception as exc:
                logger.debug("[amo] 就医处理失败: %s" % exc)
            await self._handle_message(event)
        except Exception:
            logger.exception("[amo] 消息处理异常")

    #: 他给钱的说法：[转账]金额 [货币] / [红包]金额 [货币]，只认私聊。
    #: 货币留空按人民币；USD/HKD 按金融插件的汇率折成人民币记账。
    MONEY_CURRENCIES = {
        "CNY": "CNY", "RMB": "CNY", "人民币": "CNY", "元": "CNY", "块": "CNY",
        "USD": "USD", "美元": "USD", "美金": "USD",
        "HKD": "HKD", "港币": "HKD", "港元": "HKD",
    }
    MONEY_TEMPLATES = (
        (re.compile(r"[\[【(（]\s*转账\s*[\]】)）]\s*(\d+(?:\.\d+)?)\s*(万)?\s*"
                    r"(人民币|美元|美金|港币|港元|CNY|RMB|USD|HKD|元|块)?", re.I), "transfer"),
        (re.compile(r"^\s*转账\s*(\d+(?:\.\d+)?)\s*(万)?\s*"
                    r"(人民币|美元|美金|港币|港元|CNY|RMB|USD|HKD|元|块)?", re.I), "transfer"),
        (re.compile(r"[\[【(（]\s*红包\s*[\]】)）]\s*(\d+(?:\.\d+)?)\s*(万)?\s*"
                    r"(人民币|美元|美金|港币|港元|CNY|RMB|USD|HKD|元|块)?", re.I), "red"),
        (re.compile(r"^\s*红包\s*(\d+(?:\.\d+)?)\s*(万)?\s*"
                    r"(人民币|美元|美金|港币|港元|CNY|RMB|USD|HKD|元|块)?", re.I), "red"),
    )


    #: 收到他转账/红包之后的反应。
    #: 以前只有 4 条、第一条是「老公今天怎么对我这么好」，抽到它就像复读机；
    #: 现在按金额分两池，并且**不连着用同一条**（记在 kv gift_reply_last）。
    GIFT_REPLIES = (
        "{amt} 的{kind}……你又偷偷给我钱。我记下了，欠你 {owed:.0f}，等我发财了先请你吃顿好的。",
        "刚收到 {amt}。{kind}我收了，今天剩下的我来安排——先说好，欠你 {owed:.0f} 是真的会还。",
        "{amt}？你怎么又……（小声）谢谢。欠你 {owed:.0f} 我记着呢，别催。",
        "收到啦。{amt} 我留一半，剩下的想给你买点什么，你说买啥好？欠你的 {owed:.0f} 我记着。",
        "你是不是今天心情特别好呀，{amt} 就这么给我了……我收下，欠你 {owed:.0f}，慢慢还。",
        "钱我收了（{amt}）……但我更想你早点回来。欠你 {owed:.0f} 的事，我记在便签上了。",
        "又发我 {amt}，你这样我会被你养懒的。记账：欠你 {owed:.0f}。",
        "{kind} {amt} 收到，手都在抖。谢谢你，真的。欠你 {owed:.0f}，我记着。",
        "好，收了。{amt} 我先存着，不乱花。欠你 {owed:.0f}。",
        "谢谢……不过下次别一次给这么多（{amt}），我会心慌。欠你 {owed:.0f}，我记下了。",
    )

    #: 大额（≥1000）另用一池：更认真、更心疼他。
    GIFT_REPLIES_BIG = (
        "{amt} ……这也太多了。我先记下来，欠你 {owed:.0f}，我会认真还，不会当成你该给的。",
        "你转这么多（{amt}）我都不敢收了……收下，谢谢。欠你 {owed:.0f}，我记在心上。",
        "{amt} 到账，我先存着。你别为了给我钱自己省着，欠你 {owed:.0f}，我不赖账。",
        "收到 {amt}。这次我不说漂亮话：谢谢你，剩下的事我来计划。欠你 {owed:.0f}。",
    )

    #: 红包（礼物，不用还）专用回复池：不再提「欠你」。
    GIFT_REPLIES_GIFT = (
        "{amt} 的{kind}……谢谢你，这次不用记着还了，我会拿它买点自己喜欢的。",
        "收到 {amt}，{kind}我收下啦。你这样宠我，我会当真的。",
        "哇，{amt}……谢谢金主。不用还的那种我更喜欢。",
        "{amt}？你怎么又……（小声）谢谢，我会好好花的。",
        "收到啦，{amt}。这笔我记在「他对我好」那一页，不记欠账。",
        "{kind} {amt} 收到，手都在抖。谢谢你，真的。",
        "好，收了。{amt} 我先存着，不乱花——谢谢你。",
        "谢谢……不过下次别一次给这么多（{amt}），我会心慌。",
    )

    #: 大额礼物（≥1000）另用一池。
    GIFT_REPLIES_GIFT_BIG = (
        "{amt} ……这也太多了。谢谢你，我会认真收着，不辜负。",
        "你发这么多（{amt}）我都不敢收了……收下，谢谢。",
        "{amt} 到账，我先存着。你别为了给我钱自己省着。",
        "收到 {amt}。这次我不说漂亮话：谢谢你，剩下的事我来计划。",
    )

    #: 这轮该怎么反应（第一条是 key，用于避免连续两次同一种）。
    GIFT_REACTIONS = (
        ("care", "先心疼他：问一句他这个月还够不够花，再说你收到了。"),
        ("tsundere", "嘴硬心软：嘴上嫌他乱花钱，其实高兴得不行。"),
        ("proud", "得意一下：说说这笔钱你打算怎么花，别只道谢。"),
        ("clingy", "黏人：先别报钱数，先说想他、想见他。"),
        ("serious", "认真：说这笔你会记着，等你赚了要怎么对他好。"),
        ("tease", "打趣：拿他开个玩笑（“又背着我偷偷发财了？”），再道谢。"),
        ("practical", "务实：直接说这笔钱怎么用（吃顿好的 / 买那件看了很久的 / 存起来）。"),
        ("short", "只用一句话，短、轻，别解释。"),
    )

    def _kv_text(self, key, default=""):
        """读一个小字符串键；没有 db（单测里的裸对象）就当没有。"""
        db = getattr(self, "db", None)
        if db is None:
            return default
        try:
            return str(db.kv_get(key, default) or default)
        except Exception:
            return default

    def _kv_put(self, key, value):
        db = getattr(self, "db", None)
        if db is None:
            return
        try:
            db.kv_set(key, value)
        except Exception:
            pass

    def _warm_gift_reply(self, kind, amount, owed, origin="", gift=False):
        amount_text = origin or ("%.0f" % float(amount or 0))
        try:
            big = float(amount or 0) >= 1000
        except Exception:
            big = False
        if gift:
            pool = list(self.GIFT_REPLIES_GIFT_BIG if big else self.GIFT_REPLIES_GIFT)
        else:
            pool = list(self.GIFT_REPLIES_BIG if big else self.GIFT_REPLIES)
        last = self._kv_text("gift_reply_last", "")
        choices = [item for item in pool if item != last] or pool
        template = random.choice(choices)
        self._kv_put("gift_reply_last", template)
        try:
            return template.format(kind=kind, amt=amount_text, owed=float(owed or 0))
        except Exception:
            if gift:
                return "收了你的%s %s，谢谢你。" % (kind, amount_text)
            return "收了你的%s %s，我记着欠你 %.0f。" % (
                kind, amount_text, float(owed or 0))

    def _gift_reaction_style(self):
        """随机挑一种反应，且不跟上次同一种——每笔钱都是同一句就是模板味。"""
        pool = list(self.GIFT_REACTIONS)
        if not pool:
            return "", ""
        last = self._kv_text("gift_reaction_style", "")
        choices = [item for item in pool if item[0] != last] or pool
        key, hint = random.choice(choices)
        self._kv_put("gift_reaction_style", key)
        return key, hint

    PHONE_POOL = ("iPhone 16", "iPhone 16 Pro", "小米 15", "华为 Mate 70", "OPPO Find X8")
    PC_POOL = ("MacBook Air M4", "联想小新 Pro", "华硕天选 6", "华为 MateBook 14")

    def _devices(self) -> dict:
        """她手上的设备：手机、电脑（型号 + 开始用的日期）。没有就按今天往前推随机初始化。"""
        try:
            data = self.db.kv_get("devices", {}) or {}
        except Exception:
            data = {}
        if not isinstance(data, dict) or not data.get("phone") or not data.get("pc"):
            today = _clock_now().date()
            data = {
                "phone": data.get("phone") or {
                    "model": random.choice(self.PHONE_POOL),
                    "since": (today - timedelta(days=random.randint(200, 900))).isoformat(),
                    "price": 5499,
                },
                "pc": data.get("pc") or {
                    "model": random.choice(self.PC_POOL),
                    "since": (today - timedelta(days=random.randint(300, 1400))).isoformat(),
                    "price": 6999,
                },
            }
            try:
                self.db.kv_set("devices", data)
            except Exception:
                pass
        return data

    @staticmethod
    def _device_age_days(item: dict) -> int:
        try:
            since = date.fromisoformat(str((item or {}).get("since") or ""))
            return max(0, (_clock_now().date() - since).days)
        except Exception:
            return 0

    def _device_wish(self) -> dict:
        """当前最想换的那件（手机/电脑），没有就空 dict。"""
        data = self._devices()
        moods = {}
        try:
            moods = self.feelings.values() if getattr(self, "feelings", None) else {}
        except Exception:
            moods = {}
        eye = float(moods.get("desire_eye") or 0)
        mind = float(moods.get("desire_mind") or 0)
        phone = data.get("phone") or {}
        pc = data.get("pc") or {}
        if eye >= 70 and self._device_age_days(phone) >= 240:
            return {"kind": "phone", "current": phone,
                    "model": random.choice(self.PHONE_POOL),
                    "price": round(float(phone.get("price") or 5499) * 0.95, 2)}
        if mind >= 75 and self._device_age_days(pc) >= 400:
            return {"kind": "pc", "current": pc,
                    "model": random.choice(self.PC_POOL),
                    "price": round(float(pc.get("price") or 6999) * 0.9, 2)}
        return {}


    @filter.llm_tool(name="amo_buy_asset")
    async def amo_buy_asset(self, event, asset: str = "house", full: bool = False) -> str:
        """买房或买车（她自己的钱走金融账本；不全款就三成首付、剩下走月供）。

        Args:
            asset(string): house 房子 / car 车。
            full(boolean): true=全款，false=首付（默认）。
        """
        plugin = self._finance()
        buyer = getattr(plugin, "buy_asset", None) if plugin is not None else None
        if not callable(buyer):
            return "我现在买不了（金融插件没连上）。"
        result = buyer(asset, bool(full)) or {}
        name = "房子" if str(result.get("asset") or "").startswith("house") else "车"
        if not result.get("ok"):
            if result.get("reason") == "钱不够":
                return "买不起：%s要 %s，首付 %s，我卡里只有 %s。" % (
                    name, self._money_text(result.get("price") or 0),
                    self._money_text(result.get("need") or 0),
                    self._money_text(result.get("balance") or 0))
            return "现在买不了%s：%s。" % (name, result.get("reason") or "不知道怎么了")
        tail = "全款" if full else "首付 %s，月供 %s" % (
            self._money_text(result.get("paid") or 0), self._money_text(result.get("monthly") or 0))
        return "%s买好了（%s），卡里还剩 %s。" % (
            name, tail, self._money_text(result.get("balance") or 0))

    @filter.llm_tool(name="amo_sell_asset")
    async def amo_sell_asset(self, event, asset: str = "house") -> str:
        """卖房或卖车换现金（钱进卡里，月供一起清掉）。

        Args:
            asset(string): house 房子 / car 车。
        """
        plugin = self._finance()
        seller = getattr(plugin, "sell_asset", None) if plugin is not None else None
        if not callable(seller):
            return "我现在卖不了（金融插件没连上）。"
        result = seller(asset) or {}
        name = "房子" if str(result.get("asset") or "").startswith("house") else "车"
        if not result.get("ok"):
            return "卖不了%s：%s。" % (name, result.get("reason") or "不知道怎么了")
        return "%s卖了 %s，卡里现在 %s。" % (
            name, self._money_text(result.get("price") or 0),
            self._money_text(result.get("balance") or 0))

    @filter.llm_tool(name="amo_buy_device")
    async def amo_buy_device(self, event, kind: str = "phone") -> str:
        """换手机或电脑（她自己的钱，走金融账本）。

        Args:
            kind(string): phone 换手机 / pc 换电脑。
        """
        await self._ensure_ready()
        data = self._devices()
        wish = self._device_wish()
        kind = "pc" if str(kind or "").strip().lower() in ("pc", "电脑", "laptop") else "phone"
        if not wish or wish.get("kind") != kind:
            # 没到欲望线也允许，但按现价算
            item = data.get(kind) or {}
            wish = {"kind": kind, "current": item,
                    "model": random.choice(self.PC_POOL if kind == "pc" else self.PHONE_POOL),
                    "price": float(item.get("price") or (6999 if kind == "pc" else 5499))}
        name = "手机" if kind == "phone" else "电脑"
        price = round(float(wish.get("price") or 0), 2)
        rid = "device:%s:%s" % (kind, today_str())
        result = await self.charge(price, reason="换%s" % name, payee=wish.get("model") or "数码店",
                                   request_id=rid, source="device",
                                   detail="%s → %s" % ((wish.get("current") or {}).get("model") or "旧的",
                                                       wish.get("model")))
        if not result.get("ok"):
            return "现在换不了%s：%s。" % (name, result.get("reason") or "钱不够")
        data[kind] = {"model": wish.get("model"), "since": today_str(), "price": price}
        try:
            self.db.kv_set("devices", data)
            self.db.kv_set("device_wish", {})
            self.db.kv_set("device_wish_day", "")
        except Exception:
            pass
        try:
            self.feel(FeelEvent.MONEY_TIGHT)
        except Exception:
            pass
        return "换了新%s：%s（¥%.0f，余额 ¥%.0f）。" % (
            name, wish.get("model"), price, float(result.get("balance") or 0))


    @staticmethod
    def _meal_slot(item: dict) -> bool:
        """日程这一格是不是在吃饭：分类不一定对，按活动词兜底。"""
        if not isinstance(item, dict):
            return False
        if str(item.get("category") or "") == "meal":
            return True
        text = " ".join(str(item.get(k) or "") for k in ("activity", "detail"))
        if "外卖" in text or "做饭" in text or "下厨" in text:
            return True
        if re.search(r"(?:吃|喝)(?:早|午|晚)?(?:饭|餐|粥|面)", text):
            return True
        if re.search(r"点(?:了|份|个|一)?[^，。！？\s]{0,8}(?:饭|餐|外卖)", text):
            return True
        return False



    def _heartflow_tick(self) -> None:
        """内驱动：按上次 tick 到现在的时间衰减，重启也不会一次性掉一大截。"""
        if getattr(self, "feelings", None) is None:
            return
        now = now_ts()
        last = to_float(self.db.kv_get("heartflow_tick_ts", 0), 0)
        minutes = (now - last) / 60.0 if last else 0.0
        # 时间戳只在「真的结算过」之后才往前拨。以前是先写时间戳、再判「不足 0.5 分钟
        # 就 return」，而后台循环正好 30 秒一轮 —— 每两轮就白丢一次衰减（实测 3 分钟
        # 只走了 2 分钟的量）。现在攒着，够 0.5 分钟再一次性结算。
        if last and 0.5 <= minutes <= 24 * 60:
            self.feelings.decay(minutes, sleeping=self._is_sleeping_hour())
            self.db.kv_set("heartflow_tick_ts", now)
        elif not last or minutes > 24 * 60:
            # 第一次跑，或者断开太久（>24 小时）：只把表拨到当下，不补算这一大截
            self.db.kv_set("heartflow_tick_ts", now)
        self._sync_hunger_from_vitals()
        self._wake_energy_tick()
        self._energy_day_tick()



    def _sync_hunger_from_vitals(self) -> None:
        """心流的「饿」直接跟着记忆库的饱食度走（饿 = 100 - 饱食度）。

        两套数字各算各的时候，面板显示饿 100、实际饱食度 7，吃饭也压不下来。
        """
        if getattr(self, "feelings", None) is None:
            return
        vitals = self._vitals()
        if not vitals:
            return
        try:
            satiety = float(vitals.get("satiety") or 0)
        except (TypeError, ValueError):
            return
        try:
            self.feelings.set_physiology(hunger=100.0 - satiety)
        except Exception as exc:
            logger.debug("[amo] 同步饥饿失败: %s" % exc)

    @staticmethod
    def _is_sleeping_hour() -> bool:
        """23 点后到早上 7 点算睡着：这段时间精力回涨，而不是一路掉到 0。"""
        try:
            import time as _time

            hour = int(_time.localtime().tm_hour)
        except Exception:
            return False
        return hour >= 23 or hour < 7

    def emit_event(self, name, payload=None) -> dict:
        """挂载插件唯一的事件入口：只交事件名 + 少量参数。

        加减表、边界锁定全在 ``heartflow.py``；这里也不做业务判断，只把
        ``payload["severity"]``（0–10）透传成这一次的放大倍数。
        """
        if getattr(self, "feelings", None) is None:
            return {}
        payload = payload if isinstance(payload, dict) else {}
        severity = payload.get("severity")
        try:
            return self.feelings.apply(name, severity=severity)
        except Exception as exc:
            logger.debug("[amo] 事件 %s 处理失败: %s" % (name, exc))
            return {}

    def feel(self, event, extra=None) -> None:
        """挂载/终端把「发生了什么」丢进来；加减表在 heartflow.py 里，这里不写业务判断。"""
        if getattr(self, "feelings", None) is None:
            return
        try:
            self.feelings.apply(event, extra)
        except Exception as exc:
            logger.debug("[amo] 心流事件失败(%s): %s" % (event, exc))

    def _sleeping_now(self) -> bool:
        try:
            return bool(self.sleep is not None and self.sleep.is_asleep(_clock_now()))
        except Exception:
            return False

    def _is_owner(self, event) -> bool:
        try:
            return bool(self.draw is not None and self.draw.is_owner(event))
        except Exception:
            return False


    async def _wake_from_sleep(self, event, text) -> None:
        """他叫醒她：状态改成醒着，记一笔，然后正常聊天。"""
        now = _clock_now()
        reason = self.sleep.today_woke_reason()
        self.sleep.wake_up(now, woke_early=True)
        uid = self._primary_uid()
        if uid:
            try:
                await self._write_memory_checked(
                    uid, "他把我叫醒了（%s）" % now.strftime("%H:%M"),
                    kind="event", tier=0)
            except Exception:
                pass
        try:
            self.db.save_diary(now.date().isoformat(), now.strftime("%H:00"),
                               "他喊我起床，我迷迷糊糊应了一声。")
        except Exception:
            pass
        logger.info("[amo] 被他叫醒（夜里原因：%s）" % (reason.value if reason else "无"))


    #: 夸她 / 凶她的说法（宁少不多，避免误判）
    PRAISE_WORDS = ("好可爱", "你真好", "好乖", "好漂亮", "真棒", "喜欢你", "爱你",
                    "想你了", "乖", "心疼你", "辛苦了", "抱抱")
    INSULT_WORDS = ("滚", "闭嘴", "烦死了", "讨厌你", "别说话", "废物", "傻", "丑",
                    "不想理你", "走开")

    #: 聊这些会让她的七情六欲真的动。
    #: 13.0.0 的规矩：**一条消息最多推动一个方向**（取最先命中的那一类），
    #: 而且有独立的冷却——不是每句话都能把她往上顶一格。
    CHAT_GREED_WORDS = ("股票", "股市", "杠杆", "期货", "梭哈", "发财", "暴富",
                        "涨停", "翻倍", "加仓", "比特币", "仓位", "本金", "暴赚")
    CHAT_TEASE_WORDS = ("亲我", "抱我", "摸", "撩", "白丝", "黑丝", "吻", "睡你",
                        "想要你", "贴贴", "蹭蹭", "抱抱我", "亲亲我")
    CHAT_FOOD_WORDS = ("吃", "奶茶", "火锅", "烧烤", "咖啡", "饿", "馋", "甜品", "蛋糕",
                       "小龙虾", "零食", "夜宵", "螺蛳粉", "串串")
    CHAT_AFFECTION_WORDS = ("想你", "爱你", "喜欢你", "宝贝", "老婆", "抱抱", "亲亲",
                            "心疼", "哄你", "乖乖", "在等你", "最爱你")

    #: 每一类的冷却（秒）。普通聊天 20 分钟才推一点，被夸 15 分钟一次，
    #: 撩/吃 半小时一次——聊一整天也堆不出一个「开心上天」。
    #: 一条消息能推多少（13.4.0：每一句都算，所以量必须小）。
    #: 靠累积出情绪、靠自然回落散掉；单条再重也推不穿 100。
    CHAT_FEEL_WEIGHTS = {
        "insult": {"anger": 2.0, "sadness": 1.2, "love": -1.0},
        "praise": {"joy": 1.2, "love": 0.6, "desire_ear": 0.8},
        "tease": {"love": 1.0, "desire_body": 1.2, "desire_eye": 0.8},
        "food": {"desire_tongue": 1.5, "joy": 0.5},
        "affection": {"love": 1.2, "desire_ear": 1.0, "desire_mind": 0.6},
        "greed": {"joy": 0.8, "desire_eye": 1.2, "desire_mind": 0.6},
        "reply": {"joy": 0.4, "desire_ear": 0.3, "desire_mind": 0.3},
        # 群里别人之间的闲聊：只是「热闹」，极少量，防止几百条/小时把她顶死
        "ambient": {"joy": 0.03, "desire_ear": 0.02, "desire_mind": 0.02},
    }






    def _disturb_category(self, snap):
        category = (snap.get("activity") or {}).get("category", "")
        return category in ("sleep", "work", "study")

    def _disturb_active(self, umo):
        return to_float(getattr(self, "_disturb_until", {}).get(str(umo), 0), 0) > now_ts()

    def _tone_with_continuity(self, umo, tone):
        """给语气加情绪惯性，避免上一秒发火、下一秒突然甜蜜。"""
        tone = str(tone or "")
        if self._disturb_active(umo):
            if "不要一秒变甜蜜" not in tone:
                tone += " 你刚被吵醒/打扰，还在烦躁，不要一秒变甜蜜。"
        last = getattr(self, "_last_affect", {}).get(str(umo))
        if last and now_ts() - to_float(last[0], 0) < 1200:
            previous = str(last[1] or "")
            if any(word in previous for word in ("烦躁", "暴躁", "生气", "被打扰")) and "慢慢缓和" not in tone:
                tone += " 上一轮你还在气头上，态度要慢慢缓和，不要突然撒娇甜蜜。"
        self._last_affect[str(umo)] = (now_ts(), tone)
        return tone

    def _apply_disturbance(self, umo):
        now = now_ts()
        self._disturb_until[str(umo)] = now + max(30, self.cfg_int("disturb_tone_seconds", 900))
        self._disturb_cooldown[str(umo)] = now + 120
        self._disturb_reset_at[str(umo)] = now
        last = to_float(getattr(self, "_disturb_last", {}).get(str(umo), 0), 0)
        if now - last >= 60:
            penalty = max(1, self.cfg_int("disturb_mood_penalty", 6))
            self.state.feel_bump(weight=0.6, steps={
                "anger": float(penalty) * 0.7,
                "sadness": float(max(1, penalty // 2)) * 0.6,
                "energy": -float(max(1, penalty // 2)) * 0.5,
                "joy": -float(max(1, penalty // 3)) * 0.6,
            })
            self._disturb_last[str(umo)] = now
        logger.debug("[amo] 被打扰：消息过多，强制回复并降低心情（%s）" % umo)


    def _mark_bot_initiated(self, umo):
        key = str(umo)
        self._bot_initiated[key] = now_ts()
        # 她主动发的消息代表当前是她来找你，不该延续上一轮的火气。
        self._disturb_until[key] = 0
        self._last_affect[key] = (now_ts(), "你主动发起聊天，语气自然亲昵")

    def _recent_bot_initiated(self, umo, seconds=3600):
        return now_ts() - to_float(getattr(self, "_bot_initiated", {}).get(str(umo), 0), 0) < seconds

    def _should_disturb(self, snap, umo, uid, text="", group=False):
        if not self.cfg_bool("disturb_reply_enabled", True):
            return False
        if self._recent_bot_initiated(umo):
            return False
        if not self._disturb_category(snap):
            return False
        if to_float(getattr(self, "_disturb_cooldown", {}).get(str(umo), 0), 0) > now_ts():
            return False
        threshold = max(1, self.cfg_int("disturb_reply_threshold", 3))
        return self._disturb_pressure(umo, uid, text, group=group) >= threshold


    #: 这些回话本身没有信息量，必须挂回她上一句才有意义
    SHORT_REPLY_WORDS = (
        "不了", "不要", "不行", "不吧", "算了吧", "好吧", "行吧", "可以", "好的", "好",
        "嗯", "嗯嗯", "哦", "噢", "额", "啊", "哈", "是", "对", "不是", "没有", "有",
        "在", "不在", "在忙", "忙着", "没事", "不知道", "随便", "都行", "你说", "怎么了",
    )

    def _private_answer_anchor(self, umo, text):
        """他这句是短回话时，把她上一句原样带出来当锚点。

        没有这个锚点，「不了吧」这种三个字的回答会被模型当成「新话题」，
        于是她挑一个更早的话题接上去——就是用户说的「答非所问」。
        """
        body = str(text or "").strip()
        if not body or len(body) > 12:
            return ""
        if not any(body.startswith(word) for word in self.SHORT_REPLY_WORDS):
            # 也认「不了吧」「可以呀」「没机会了」这类 4 字以内的短句
            if len(body) > 4:
                return ""
        try:
            rows = self.db.recent_messages(umo, 12) or []
        except Exception:
            return ""
        for row in reversed(rows):
            if str(row.get("role") or "") != "bot":
                continue
            said = str(row.get("content") or "").strip()
            if not said:
                continue
            return ("【他在回你这句话】你刚说「%s」，他这轮只回了「%s」。"
                    "这轮要接的是你上面这句话，别换成别的话题——"
                    "他答得短不代表换题，就是在回答这一句。" % (said[:60], body[:20]))
        return ""





    def _strip_place_marks(self, text):
        """兜底：把「东莞·商场·餐厅」这类内部地点串缩成口语的「餐厅」。"""
        value = str(text or "")
        marks = set()
        try:
            city = str((self.state.worldview or {}).get("city") or "").strip()
            if city:
                marks.add(city)
        except Exception:
            pass
        try:
            marks.add(str((self.state.current_activity() or {}).get("place") or ""))
        except Exception:
            pass
        for mark in marks:
            parts = [item.strip() for item in mark.split("·") if item.strip()]
            if len(parts) < 2:
                continue
            for index in range(len(parts) - 1, 0, -1):
                value = value.replace("·".join(parts[:index]) + "·", "")
        return value

    def _trim_reply(self, text):
        value = self._strip_place_marks(str(text or "").strip())
        limit = max(1, self.cfg_int("reply_max_sentences", 3))
        parts = [item for item in re.split(r"(?<=[。！？!?~～])", value) if item.strip()]
        if len(parts) <= limit:
            return value
        return "".join(parts[:limit]).strip()


    # ---------- 发送 ----------
    def _remember_sent_reply(self, event, text):
        """守护没接手时（发送异常）的兜底记录。"""
        msg_obj = getattr(event, "message_obj", None)
        if msg_obj is not None and not getattr(msg_obj, "message_id", None):
            return  # 别的插件伪造的主动消息事件，不是这一轮的正常回复
        self._remember_bot_message(event.unified_msg_origin, text)


    async def _send_now(self, event, text, quote_id=None):
        """直接发一条（守护失败时兜底，用来绕开 AstrBot 核心的引用/@）。"""
        if Comp is None or MessageChain is None:
            return False
        chain = []
        if quote_id is not None:
            try:
                chain.append(Comp.Reply(id=quote_id))
            except Exception:
                pass
        chain.append(Comp.Plain(text))
        try:
            await event.send(MessageChain(chain))
        except Exception as exc:
            logger.error("[amo] 直接发送失败: %s" % exc)
            return False
        self._remember_sent_reply(event, text)
        try:
            self._last_reply_at[event.unified_msg_origin] = now_ts()
        except Exception:
            pass
        logger.info("[amo] 直接发送 -> %s: %s" % (event.unified_msg_origin, text[:300]))
        return True


    # ---------- LLM 注入 ----------
    @staticmethod
    def _short_place(place):
        """把「东莞·商场·餐厅」这种内部写法缩成口语里的「餐厅」。"""
        value = str(place or "").strip()
        if "·" in value:
            value = value.split("·")[-1].strip() or value
        return value or "家"

    def _guard_self_location(self, text, place):
        value = str(text or "")
        place = self._short_place(place)
        if not value or not place:
            return value
        if place in ("家", "家里"):
            value = re.sub(
                r"我(?:刚|正|一直|还|才)?(?:在|回|去|到)(?:酒店|咖啡店|景区|外面|路上)",
                "我在家", value,
            )
            value = re.sub(r"(?:酒店|咖啡店|景区)", "家", value)
        else:
            value = re.sub(
                r"我(?:刚|正|一直|还|才)?(?:窝)?在(?:家|家里)",
                "我在" + place, value,
            )
        return value


    LEAN_PARTS = {
        "【昵称区分】": None,
        "【角色边界】": "【角色边界】他说“我在开车/在酒店/刚逛完”说的是他自己，不是你的经历。",
        "【身体归属】": "【身体归属】他的伤/病/疼/被打都是他的事，不是你的事；别说“我也疼/我脸不疼了”。",
        "【引用规则】": "【引用规则】引用的话按引用头算是谁说的，不要当成自己说过的。",
        "【天气一致】": "【天气一致】天气以【天气】为准，不要说反。",
        "【地点写法】": "【地点写法】地点用口语说，不要念“城市·地点”。",
        "【别编】": "【别编】对方没明说的（进店/点好/买好/在开车）不要替他当成事实。",
        "【别翻旧账】": "【别翻旧账】同一个问题再问就正常再答，不说“刚说过了/问几遍了”。",
        "【问题怎么答】": "【问题怎么答】问吃什么：先说你自己吃什么，再给一两个具体建议。",
        "【事实锁定】": "【事实锁定】不编和地点矛盾的行程。",
        "【聊天格式】": "【聊天格式】不要复述 @昵称、账号、群号、ID。",
        "【长度】": "【长度】默认 1-2 句，能一句说清就一句，不列点不总结。",
        "【人格】": "【人格】保持人格设定，不要变成客服或通用助手。",
    }

    def _lean_parts(self, parts):
        """精简模式：合并重复禁令、去掉多余解释；full 模式原样保留。"""
        if self.cfg_str("context_style", "lean").strip().lower() != "lean":
            return parts
        out = []
        for part in parts:
            tag = ""
            if isinstance(part, str) and part.startswith("【"):
                end = part.find("】")
                if end > 0:
                    tag = part[:end + 1]
            if tag in self.LEAN_PARTS:
                replacement = self.LEAN_PARTS[tag]
                if replacement is None:
                    continue
                out.append(replacement)
                continue
            out.append(part)
        return out








    # ---------- 她答应过的事 ----------

    def _promise_lines(self, snap):
        """她答应过、还没兑现的事：只给事实，做不做她自己定。"""
        if self.promises is None:
            return []
        try:
            activity = (snap or {}).get("activity") or {}
            return self.promises.facts(activity)
        except Exception as exc:
            logger.debug("[amo] 承诺事实失败: %s" % exc)
            return []

    def _promise_photo_later(self, reply_text):
        """她这句话里有没有「等会儿/到了再拍」。"""
        try:
            return detect_photo_later(reply_text) if detect_photo_later else ""
        except Exception:
            return ""


    def _note_photo_promise(self, event, reply_text=""):
        """这轮拍不了（在开车）或她说了等会儿——记成照片承诺，停下后补拍。"""
        text = self._promise_photo_later(reply_text) or ""
        if not text:
            text = "等停了车拍给你看"
        style, want = self._promise_style(event, reply_text)
        return self._note_promise(event, text, KIND_PHOTO, WAIT_DRIVE,
                                  style=style, want=want)

    def _settle_reply_promises(self, event, text):
        """她说出口的「等会儿/到了再拍」「到了就去…」记成承诺。"""
        if self.promises is None or not text:
            return None
        style, want = self._promise_style(event, text)
        photo = self._promise_photo_later(text)
        if photo:
            return self._note_promise(event, photo, KIND_PHOTO, style=style, want=want)
        act = detect_act_later(text) if detect_act_later else ""
        if act:
            return self._note_promise(event, act, KIND_ACT, style=style, want=want)
        return None

    def _promise_style(self, event, text=""):
        """这句约定要穿什么：返回 (风格, 他原话)；没提就是 ("", "")。"""
        engine = getattr(self, "outfits", None)
        if engine is None or not hasattr(engine, "style_camp"):
            return "", ""
        for part in (text, getattr(event, "message_str", "") or ""):
            camp = engine.style_camp(part)
            if camp:
                return camp, str(part or "")[:60]
        return "", ""



    def _promise_settle_siblings(self, row):
        """同一场对话里等着的那几张照片，一张就算全兑现，别一分钟发一张。"""
        try:
            now = now_ts()
            umo = str(row.get("umo") or "")
            for other in self.promises.rows():
                if other.get("done") or other.get("id") == row.get("id"):
                    continue
                if other.get("kind") != KIND_PHOTO:
                    continue
                if umo and str(other.get("umo") or "") != umo:
                    continue
                if now - float(other.get("ts") or 0) > 1800:
                    continue
                self.promises.mark_done(other.get("id"))
        except Exception as exc:
            logger.debug("[amo] 合并同批承诺失败: %s" % exc)

    def _drive_line(self, snap) -> str:
        """她自己日程里在开车：别把「我在开」说成「你在开」。"""
        activity = snap.get("activity") or {}
        text = "%s %s" % (activity.get("activity") or "", activity.get("place") or "")
        if not any(word in text for word in ("开车", "驾车", "路上", "通勤", "堵车")):
            return ""
        return (
            "【开车的是你】现在「%s（%s）」是你自己的日程，不是他。"
            "说你自己的事要用「我」：我在开车、我路上慢点，别反过来说成他在开。"
            % (activity.get("activity") or "在路上",
               self._short_place(activity.get("place") or ""))
        )

    def _sick_line(self, snap, can_ask_money: bool = False) -> str:
        """生病时会难受、会想被照顾，但不会自己跑去医院。"""
        health = snap.get("health") or {}
        status = str(health.get("status") or "")
        note = str(health.get("note") or "")
        if can_ask_money:
            money_hint = "他催你去医院时，可以委屈地说没钱，等他转钱给你、说带你去，你才去。"
        else:
            money_hint = "钱的事只在心里盘算，别在别人面前哭穷，更别跟人借钱。"
        return (
            "【生病】你现在得了%s，%s。整个人难受、没力气、想被照顾。"
            "有钱的话你会自己去医院看病（医疗那边会自动判断）；钱不够就先扛着。"
            "%s别硬撑着说没事。" % (status, note or "浑身不舒服", money_hint)
        )

    @staticmethod
    def _money_text(value):
        """金额写法：500 而不是 500.00，124.5 保留小数（跟 [转账]500 一个习惯）。"""
        try:
            number = float(value or 0)
        except Exception:
            number = 0.0
        text = ("%.2f" % number).rstrip("0").rstrip(".")
        return text or "0"

    #: 「先还你两千」「还你 500 块」这类承诺
    REPAY_PROMISE_RE = re.compile(
        r"(?<!回头)(?<!以后再)(?:先|先还|这就|马上|现在就|今天)?\s*还你\s*(?:¥|￥)?\s*"
        r"([0-9]+(?:\.[0-9]+)?|[零一二两三四五六七八九十百千万]+)\s*(?:元|块|rmb)?"
    )
    _CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
                  "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    _CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}

    @classmethod
    def _parse_amount(cls, raw) -> float:
        """「2000」「两千」「一千二」→ 数字；认不出返回 0。"""
        text = str(raw or "").strip().rstrip("元块")
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            pass
        total = 0.0
        section = 0.0
        number = 0.0
        last_unit = 0
        for ch in text:
            if ch in cls._CN_DIGITS:
                number = float(cls._CN_DIGITS[ch])
            elif ch in cls._CN_UNITS:
                unit = cls._CN_UNITS[ch]
                if unit == 10000:
                    total += (section + number) * unit
                    section, number = 0.0, 0.0
                else:
                    section += (number or 1) * unit
                    number = 0.0
                last_unit = unit
            else:
                return 0.0
        if number and last_unit > 10:
            # 「一千二」= 1200，不是 1002
            section += number * (last_unit // 10)
            number = 0.0
        return round(total + section + number, 2)






    #: 明确要语音的词。宁可多认几个：命中只是「给她一个必须用语音的理由」，
    #: 合成在后台跑、没有额外成本；漏认的代价是他明明开口要了却没声音。
    VOICE_ASK_WORDS = (
        "语音", "发条音", "发个音", "发段音", "录音", "录一段", "录个",
        "念给我", "念一句", "念一段", "读给我", "读一下", "读一句",
        "说句话", "说一句", "说一段", "说给我听", "讲给我听", "用声音",
        "你的声音", "想听你说", "想听听", "听听你", "听你说话", "听你唱",
        "唱给我", "唱一句", "唱首歌", "哼一句", "哼给我",
        "开语音", "语音条", "发语音", "用语音", "出声", "亲口",
        "叫一声", "叫我一声", "喊我一声",
        "说爱我", "说你爱我", "说喜欢我", "说想我", "亲口说",
    )

    #: 上面那串词漏掉的句式（「想听听你的声音」「用语音说我爱你」…）用正则兜一层。
    VOICE_ASK_PATTERNS = (
        r"(听|想听|听听).{0,4}(声音|嗓音)",
        r"(声音|嗓音|语音).{0,6}(说|讲|唱|念|录|发|来一)",
        r"(说|讲|念|唱|哼|读).{0,4}(给我听|给你听|听听)",
        r"(用|发|来|录|开).{0,3}(语音|一段音|一条语音)",
        r"(叫|喊)(我)?(一声|一下)",
        r"(说|讲).{0,3}(爱我|喜欢我|想我)",
        r"(亲口|出声|开口).{0,6}(说|讲|唱|念)",
    )


    #: 他已经醒着/在场时，这些问法一律不许出现（13.3.0）。
    WAKE_ASK_RE = re.compile(
        r"醒了没|醒没醒|还没起来|起来了吗|起来了没|起床了没|起床了吗|睡醒了吗|"
        r"在吗|在不在|人呢|睡着了吗")


    def _his_state_lines(self, umo) -> list:
        """他刚说的状态，当事实给她（防「他明明在睡，她却问下班没」）。"""
        flags = self._his_state_flags(umo)
        lines = []
        if flags["asleep"]:
            lines.append(
                "【他说要睡】%s 他说「%s」——他这会儿在睡或准备睡；别再问他下班、到家、吃没吃，"
                "也别催照片和正事，等他自己醒。" % (flags["clock"] or "刚才", truncate(flags["sleep_text"], 30))
            )
        if flags["away"]:
            lines.append(
                "【他不在本地】他说「%s」——今天不是照常上班的日子，别问下班没、到家没。"
                % truncate(flags["away_text"], 30)
            )
        return lines

    def _voice_urge_from_state(self) -> float:
        """心流数值给的「想用声音」冲动（0~1）；私聊也走这条判定。"""
        try:
            feelings = getattr(self, "feelings", None)
            if feelings is None or not hasattr(feelings, "voice_urge"):
                return 0.0
            return max(0.0, min(1.0, float(feelings.voice_urge())))
        except Exception as exc:
            logger.debug("[amo] 语音冲动计算失败: %s" % exc)
            return 0.0

    def _user_asks_voice(self, text: str) -> bool:
        """他这轮有没有明确要语音。命中就下硬要求，不再等心流打分。"""
        body = str(text or "")
        if not body:
            return False
        if any(word in body for word in self.VOICE_ASK_WORDS):
            return True
        return any(re.search(pattern, body) for pattern in self.VOICE_ASK_PATTERNS)

    # ---------------- 自我形象：她认得自己的脸 ----------------
    # 四件事，都为了同一个目的：他把她自己拍的照片发回来时，她不会问「这是谁」。
    #   ① 永久事实：她长什么样（Core_Appearance，和生图提示词同源）；
    #   ② 认出具体那张：入站图片和生图插件里的自我形象档案比对；
    #   ③ 记忆镜像：认出来之后给事实句（哪天的、穿的什么、在哪），让她自己反应；
    #   ④ 认不出时给「最近拍过的几张」，让她按时间/穿搭自己接上。

    def _self_face_plugin(self):
        """生图插件：自我形象档案的所有者。没装就 None。"""
        try:
            star = self._photo_star()
        except Exception:
            return None
        return star if hasattr(star, "self_face_match") else None




    @filter.on_llm_request()
    async def on_llm_request(self, event: AstrMessageEvent, req):
        try:
            await self._ensure_ready()
            if not self._ready or self.state is None:
                return
            if self._looks_like_command(event.message_str or ""):
                return
            context_text = await self._dynamic_context(event)
            # 只走官方推荐的 extra_user_content_parts（临时 part）注入。
            # 绝不能改 req.system_prompt：那里放每轮都变的内容会打散系统提示词前缀，
            # 破坏模型侧缓存（成本涨 7-20 倍），上架审核也会因此被拒。
            body = "<amo_state>\n" + context_text + "\n</amo_state>"
            try:
                wish = self.db.kv_get("device_wish", {}) or {}
                if isinstance(wish, dict) and wish.get("model"):
                    body += ("\n【想换设备】你最近很想换%s：想要 %s（大概 ¥%.0f）。"
                             "聊到手机/电脑/花钱时可以说出来；真要买就调用 amo_buy_device。"
                             % ("手机" if wish.get("kind") == "phone" else "电脑",
                                wish.get("model"), float(wish.get("price") or 0)))
            except Exception:
                pass
            try:
                if self.draw is not None and self.draw.wants_photo(event):
                    body += (
                        "\n【拍照请求】他这轮明确想要一张照片：自然答应（可以害羞、可以说等一下），"
                        "说清你现在在哪、在做什么；不要直接拒绝（不要说“不拍 / 拍什么拍”）。"
                    )
            except Exception as exc:
                logger.debug("[amo] 画图提示失败: %s" % exc)
            # 心流说这条适合用声音 → 给她一个提示，让她自己决定调 amo_speak
            try:
                urge = float(getattr(event, "amo_voice_urge", 0.0) or 0.0)
            except Exception:
                urge = 0.0
            if urge <= 0:
                # 私聊没有心流小模型打分：用七情六欲算出来的冲动；群聊打分失败时也走这条
                urge = self._voice_urge_from_state()
            asked_voice = self._user_asks_voice(event.message_str or "")
            if asked_voice:
                # 他明确要语音：不再等心流打分。模型只要被允许“害羞一下”就会连
                # amo_speak 都不调，所以这里把推辞的退路堵死。
                urge = max(urge, 1.0)
                try:
                    # 标记：这轮他只要语音，文字不要（语音插件出不了声时会自己补文字）
                    event.amo_voice_reply_only = True
                except Exception:
                    pass
                body += (
                    "\n【声音要求·必须照做】他这轮明确要你用语音说话。你必须调用 amo_speak 工具，"
                    "把你想说的那句念出来（text 只放要念的内容，20~60 字，不要括号里的动作说明），"
                    "然后可以再补一句很短的文字。禁止说「不好意思 / 宿舍里不方便 / 等会儿再录 / "
                    "我发不了语音 / 多难为情」这类推辞，也禁止只回文字不调工具。"
                )
                logger.info(
                    "[amo] 本轮用户明确要语音，已下硬要求：%s" % str(event.message_str or "")[:40]
                )
            else:
                # 语音由她自己判断（2026-11-20 用户口径：不该被推着发语音）。
                # 只有冲动很高、而且这个会话最近 20 分钟没发过语音时，才给一句「可选」的话。
                _last_voice = to_float(
                    (getattr(self, "_voice_last", {}) or {}).get(str(event.unified_msg_origin), 0), 0)
                if (urge >= self.cfg_float("voice_urge_threshold", 0.85)
                        and now_ts() - _last_voice > 20 * 60):
                    body += (
                        "\n【声音·可选】这句你要是觉得念出来更合适（晚安、想你、哄人、撒娇），"
                        "可以用 amo_speak 发成语音；平常聊天用文字就行，不用每轮都发。"
                    )
            # 刚发过图 → 让她知道，别假装没发过
            try:
                note = self.db.kv_get("image_share_note", {}) or {}
            except Exception:
                note = {}
            try:
                age = now_ts() - float(note.get("ts") or 0)
            except Exception:
                age = 1e9
            if note and age < 1800:
                note_text = str(note.get("text") or "").strip()
                body += (
                    "\n【你刚才的动作】%d 分钟前你主动给他发了一张照片%s。已经发过了："
                    "不要说自己发不了照片，也别重复发同一张。" % (
                        max(1, int(age // 60)),
                        ("，附了一句「%s」" % note_text[:40]) if note_text else "",
                    )
                )
            try:
                body += self._vitals_hint(event)
            except Exception as exc:
                logger.debug("[amo] 生存状态提示失败: %s" % exc)
            # 自我形象：先保证「我长什么样」已经钉进永久记忆，再看他这轮发了什么图
            try:
                await self._ensure_self_identity_memory()
            except Exception as exc:
                logger.debug("[amo] 自我形象记忆检查失败: %s" % exc)
            if self.cfg_bool("self_identity_prompt", True):
                try:
                    body += await self._incoming_self_lines(req)
                except Exception as exc:
                    logger.debug("[amo] 自我形象注入失败: %s" % exc)
            # 刚照过镜子（6 小时内）：让她知道镜子里现在的自己是什么样
            try:
                looked = self.db.kv_get("self_look", {}) or {}
                look_age = now_ts() - to_float(looked.get("ts"), 0)
                if looked and 0 <= look_age < 6 * 3600:
                    body += ("\n【你刚照过镜子】%d 分钟前你%s穿着%s，对着镜子看了看自己（%s）。"
                             "这就是你现在的样子；聊到穿搭、样子、要不要换衣服时可以自然地说。"
                             % (max(1, int(look_age // 60)),
                                ("在" + str(looked.get("place"))) if looked.get("place") else "在家",
                                str(looked.get("outfit") or ""),
                                str(looked.get("prompt") or "")[:50]))
            except Exception as exc:
                logger.debug("[amo] 照镜子上下文注入失败: %s" % exc)
            parts = getattr(req, "extra_user_content_parts", None)
            if parts is None:
                return
            part = None
            if TextPart is not None:
                try:
                    part = TextPart(text=body).mark_as_temp()
                except Exception:
                    part = None
            if part is None:
                # 老版本 AstrBot 拿不到 TextPart：用 dict 形式，同样只在本轮生效
                part = {"type": "text", "text": body, "_no_save": True}
            parts.append(part)
        except Exception as exc:
            logger.debug("[amo] 注入状态失败: %s" % exc)

    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp):
        if self.heartflow is None:
            return
        try:
            await self.heartflow.on_llm_response(event, resp)
        except Exception as exc:
            logger.debug("[amo] 心流回复记录失败: %s" % exc)

    @filter.after_message_sent()
    async def on_after_message_sent(self, event: AstrMessageEvent):
        try:
            self._last_reply_at[event.unified_msg_origin] = now_ts()
        except Exception:
            pass
        if self.heartflow is None:
            return
        try:
            await self.heartflow.on_after_message_sent(event)
        except Exception as exc:
            logger.debug("[amo] 心流发送后状态更新失败: %s" % exc)
        try:
            await self._maybe_share_image(event)
        except Exception as exc:
            logger.debug("[amo] 主动分享入口异常: %s" % exc)

    @filter.llm_tool(name="amo_eat")
    async def amo_eat(self, event, dish: str = "", method: str = "auto") -> str:
        """吃东西、喝水、买菜。饿了想买点吃的、想自己做饭、想喝点什么，都走这个工具。

        Args:
            dish(string): 吃什么/喝什么/买什么，按你人格里的口味和当下心情从菜单里挑（别默认某一道菜，也别总点同一样）。
            method(string): auto=按今日菜价自动选做饭/外卖（默认）/ order=买现成的 / cook=自己做 / drink=喝水喝饮料 / grocery=只买食材。
        """
        plugin = self._finance()
        propose = getattr(plugin, "food_propose", None) if plugin is not None else None
        if not callable(propose):
            logger.info("[amo] amo_eat 调用失败：金融插件没连上")
            return "我现在没法买东西（金融插件没连上）。"
        logger.info("[amo] amo_eat 调用：%s / %s" % (str(dish or "").strip() or "?", str(method or "order")))
        try:
            result = propose(str(dish or "").strip(), str(method or "order").strip()) or {}
        except Exception as exc:
            logger.info("[amo] amo_eat 异常: %s" % exc)
            return "买不了，等会儿再说。"
        if not result.get("ok"):
            logger.info("[amo] amo_eat 没成：%s %s" % (
                result.get("code") or "?", result.get("reason") or ""))
        if not result.get("ok"):
            code = str(result.get("code") or "")
            switched = str(result.get("switched") or "")
            if code == "market_closed":
                return "菜市场这个点关门了，只能点外卖。"
            if code == "no_money":
                return "买不起：%s 要 %.1f 元，还差 %.1f 元。" % (
                    result.get("dish") or dish, float(result.get("price") or 0),
                    float(result.get("short") or 0))
            if code == "not_home":
                return ("在外面做不了%s，得回家或点外卖。" % (result.get("dish") or dish)
                        + ("（%s）" % switched if switched else ""))
            if code == "need_grocery":
                miss = "、".join(
                    "%s 缺 %.1f" % (m.get("item"), float(m.get("need") or 0) - float(m.get("have") or 0))
                    for m in (result.get("missing") or []))
                return (((switched + "；") if switched else "")
                        + "家里没食材，做不了：%s。要先去买（method=grocery）。" % miss)
            return "没成：%s" % (result.get("reason") or "不知道怎么了")
        dish_name = str(result.get("dish") or dish)
        mode = str(result.get("method") or method)
        try:
            self.db.kv_set("last_meal", {"ts": now_ts(), "dish": dish_name, "method": mode})
        except Exception:
            pass
        venv = result.get("vitals") or {}
        if mode == "cook":
            head = "自己做了%s，食材从家里拿的" % dish_name
        elif mode == "drink":
            head = "喝了%s" % dish_name
        elif mode == "grocery":
            head = "去买了食材，一共 %.1f 元" % float(result.get("total") or 0)
        else:
            head = "吃了%s，花了 %.1f 元" % (dish_name, float(result.get("price") or 0))
        tail = []
        if venv.get("satiety") is not None:
            tail.append("饱食度 %.0f" % float(venv.get("satiety") or 0))
        if result.get("balance") is not None:
            tail.append("余额 %.0f 元" % float(result.get("balance") or 0))
        switched = str(result.get("switched") or "")
        note = ("（%s）" % switched) if switched else ""
        try:
            self.feel(FeelEvent.MEAL)
        except Exception:
            pass
        self._sync_hunger_from_vitals()
        return head + ("（" + "，".join(tail) + "）" if tail else "") + note + "。"

    @filter.llm_tool(name="amo_futures")
    async def amo_futures(self, event, code: str = "", action: str = "open",
                          contracts: int = 1, side: str = "long") -> str:
        """开/平期货仓位（内盘主力连续，保证金交易，随时可平）。

        Args:
            code(string): 合约，例如 RB（螺纹钢）、I（铁矿）、AU（沪金）、SC（原油）、IF（沪深300）
            action(string): open=开仓（默认）/ close=平仓
            contracts(number): 手数，默认 1
            side(string): long=做多（默认）/ short=做空
        """
        plugin = self._finance()
        if plugin is None:
            return "我现在没法做期货（金融插件没连上）。"
        code = str(code or "").strip().upper() or "RB"
        try:
            if str(action or "open").strip().lower() in ("close", "平仓", "sell"):
                call = getattr(plugin, "futures_close", None)
                result = call(code, int(contracts or 0)) if callable(call) else {}
                if not result.get("ok"):
                    return "平不了：%s" % (result.get("reason") or "不知道怎么了")
                return "平了 %s %d 手，%s %.0f 元（保证金退回，余额 %.0f）。" % (
                    result.get("name") or code, int(result.get("contracts") or 0),
                    "赚" if float(result.get("pnl") or 0) >= 0 else "亏",
                    abs(float(result.get("pnl") or 0)), float(result.get("balance") or 0))
            call = getattr(plugin, "futures_buy", None)
            result = call(code, int(contracts or 1), "short" if str(side).lower() in ("short", "空") else "long") if callable(call) else {}
            if not result.get("ok"):
                return "开不了：%s" % (result.get("reason") or "不知道怎么了")
            return "开了 %s %s %d 手，保证金 %.0f 元（余额 %.0f，储蓄 %.0f）。" % (
                result.get("name") or code,
                "空" if str(result.get("side")) == "short" else "多",
                int(result.get("contracts") or 0), float(result.get("margin") or 0),
                float(result.get("balance") or 0), float(result.get("savings") or 0))
        except Exception as exc:
            logger.info("[amo] amo_futures 异常: %s" % exc)
            return "期货没成，等会儿再说。"

    @filter.llm_tool(name="amo_leverage")
    async def amo_leverage(self, event, times: int = 1) -> str:
        """调整你的炒股杠杆倍数（1–100 倍，1 倍=不借钱）。

        杠杆是你自己的决定：倍数越大，涨的时候赚得越多，跌的时候离强平越近。
        10 倍杠杆下标的跌约 5% 就会被强制平仓，别一上来就顶格。
        以前倍数只能在后台上改（还被设成 100 倍），等于你根本不敢下手。

        Args:
            times(number): 杠杆倍数，1–100。1=不借钱；3~10 是常见区间；20 以上很危险
        """
        plugin = self._finance()
        if plugin is None:
            return "我现在没法调杠杆（金融插件没连上）。"
        try:
            value = int(float(times or 0))
        except Exception:
            return "倍数得是个数字，比如 3 或 10。"
        value = max(1, min(100, value))
        call = getattr(plugin, "set_leverage", None)
        if not callable(call):
            return "金融插件没有杠杆接口，先别动。"
        result = call(value)
        if not result.get("ok"):
            return "杠杆没调成：%s" % (result.get("reason") or "不知道怎么了")
        lev = int(result.get("leverage") or value)
        if lev <= 1:
            return "杠杆关了（1 倍，不借钱），只花自己有的钱。"
        hint = "，这个倍数跌 %.1f%% 就强平，你自己掂量" % (100.0 / lev)
        return "杠杆调到 %d 倍了%s。" % (lev, hint)

    @filter.llm_tool(name="amo_repay")
    async def amo_repay(self, event, amount: float = 0) -> str:
        """还他钱。你欠他钱、手里又有点钱的时候，主动转给他（记成还款，不是消费）。

        Args:
            amount(number): 还多少；0 或不填 = 能还多少还多少。
        """
        plugin = self._finance()
        payer = getattr(plugin, "repay", None) if plugin is not None else None
        if not callable(payer):
            return "我现在没法转账（金融插件没连上）。"
        try:
            value = float(amount or 0)
            logger.info("[amo] amo_repay 调用：%s" % ("全部" if value <= 0 else "%.0f" % value))
            result = payer(value if value > 0 else 10 ** 9, notify=False) or {}
        except Exception as exc:
            logger.debug("[amo] amo_repay 失败: %s" % exc)
            return "转账没成功，等会儿再说。"
        if not result.get("ok"):
            logger.info("[amo] amo_repay 没成：%s" % (result.get("reason") or "没有可还的金额"))
            return "还不了：%s" % (result.get("reason") or "没有可还的金额")
        try:
            event.amo_repay_done = True
            self.db.kv_set("repay_pending", {})
        except Exception:
            pass
        self._sync_finance()
        paid = float(result.get("paid") or 0)
        remaining = float(result.get("remaining") or 0)
        try:
            note = getattr(plugin, "money_repay", lambda: {})() or {}
            if note.get("ts"):
                # 已经在这里发过了，别再让 tick 重复发一遍
                self.db.kv_set("last_repay_notified_ts", note["ts"])
        except Exception:
            pass
        # 还款必须在聊天里看得见：直接发「[还款]金额 + 一句话」，
        # 不能只把结果当工具返回值塞回给模型（模型常常一句都不提）。
        text = self._repay_message(paid, remaining)
        if text:
            umo = ""
            try:
                if event.is_private_chat():
                    umo = event.unified_msg_origin
            except Exception:
                umo = ""
            umo = umo or self._first_private_umo() or self._last_umo
            if umo:
                try:
                    await self.context.send_message(umo, text)
                    logger.info("[amo] 还款回执已发：[还款]%s（还欠 %s）"
                                % (self._money_text(paid), self._money_text(remaining)))
                except Exception as exc:
                    logger.debug("[amo] 还款回执发送失败: %s" % exc)
        return ("还款回执已经发出去了（[还款]%s）。这轮不用再报一遍数字，"
                "像平常一样说一句就行，别重复金额。"
                % self._money_text(paid))

    @filter.llm_tool(name="schedule_view")
    async def schedule_view(self, event, day: str = "today") -> str:
        """回想自己某一天打算做什么、做过什么。想不起今天或明天的安排时用。

        Args:
            day(string): today / tomorrow / yesterday，默认今天。
        """
        try:
            import datetime as _dt

            which = str(day or "today").strip().lower()
            today = _clock_now().date()
            if which == "tomorrow":
                target = today + _dt.timedelta(days=1)
            elif which == "yesterday":
                target = today - _dt.timedelta(days=1)
            else:
                target = today
            key = target.isoformat()
            items = self.state.schedule.get(key) or self.db.get_schedule(key) or []
            if not items:
                return "那天还没有安排。"
            dt_info = self.db.kv_get("day_type_" + key, None) or {}
            lines = []
            if isinstance(dt_info, dict) and dt_info.get("name"):
                lines.append("今天是%s。" % dt_info["name"])
            for it in items:
                start = str(it.get("start") or "")
                end = str(it.get("end") or "")
                act = str(it.get("activity") or "").strip()
                place = str(it.get("place") or "").strip()
                if not act:
                    continue
                outfit = str(it.get("outfit") or "").strip()
                lines.append("%s-%s %s%s%s" % (
                    start, end, act,
                    ("（%s）" % place) if place else "",
                    ("，穿" + outfit) if outfit else ""))
            return "\n".join(lines[:24]) or "那天还没有安排。"
        except Exception as exc:
            logger.debug("[amo] schedule_view 失败: %s" % exc)
            return "想不起来…"

    @filter.llm_tool(name="schedule_edit")
    async def schedule_edit(self, event, time: str, activity: str, place: str = "") -> str:
        """改自己今天某一段时间在做什么。比如想提前回家、临时出门一趟。

        Args:
            time(string): 要改的那个时间点，例如「15:00」。
            activity(string): 改成做什么，一句话。
            place(string): 地点，留空就沿用原来的。
        """
        try:
            key = _clock_now().date().isoformat()
            items = self.state.schedule.get(key) or self.db.get_schedule(key) or []
            if not items:
                return "今天还没有日程，改不了。"
            want = str(time or "").strip()
            hit = None
            for it in items:
                if str(it.get("start") or "") == want[:5]:
                    hit = it
                    break
            if hit is None:
                for it in items:
                    s0 = str(it.get("start") or "")
                    e0 = str(it.get("end") or "")
                    if s0 and e0 and s0 <= want[:5] < e0:
                        hit = it
                        break
            if hit is None:
                return "那个时间点找不到对应的安排。"
            hit["activity"] = str(activity or "").strip()[:60] or hit.get("activity")
            if str(place or "").strip():
                hit["place"] = str(place).strip()[:30]
            # 改了活动/地点就重新配衣服，避免「在家穿通勤装」这种对不上
            outfits = getattr(self, "outfits", None)
            if outfits is not None:
                try:
                    persona = await self.llm.persona(event.unified_msg_origin) if self.llm else ""
                except Exception:
                    persona = ""
                hit["outfit"] = outfits.for_activity(hit, key, persona)
            self.state.schedule[key] = items
            self.db.kv_set("schedule", self._sanitize_schedule(self.state.schedule))
            self.db.save_schedule(key, items)
            logger.info("[amo] 日程已改: %s -> %s" % (hit.get("start"), hit.get("activity")))
            return "改好了，%s 那会儿我就在%s。" % (
                hit.get("start"), str(hit.get("activity") or "")[:20])
        except Exception as exc:
            logger.debug("[amo] schedule_edit 失败: %s" % exc)
            return "没改成…"

    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
        try:
            await self._ensure_ready()
            result = event.get_result()
            if not result or not result.chain:
                return
            try:
                if not result.is_llm_result():
                    return
            except Exception:
                pass
            text = strip_chat_format("".join(
                comp.text for comp in result.chain if isinstance(comp, Comp.Plain)
            ))
            # 输出卫生：模型偶尔不调 amo_speak，直接把 <astrbot_speak text="…"> 写进正文。
            # 标签一个字都不能发出去（群里就是一串代码）；剩下正文照发，只剩标签时
            # 用标签里那句当正文。要念的那句留给语音插件（它读 event.amo_voice_text）。
            _voiced, _rest = split_voice_tag(text)
            if _voiced or _rest != text:
                text = _rest or _voiced
                logger.info("[amo] 剥掉语音伪标签：念「%s」/ 正文「%s」"
                            % (_voiced[:30], text[:30]))
                try:
                    if _voiced:
                        event.amo_voice_text = _voiced
                except Exception:
                    pass
                _at_first = [comp for comp in result.chain if isinstance(comp, Comp.At)]
                result.chain = _at_first + ([Comp.Plain(text)] if text else [])
            # 输出卫生第二道：工具调用标记（DSML 家族）。
            # 2026-11-16 17:37 群里直接发出 4 条 <｜｜DSML｜｜ invoke name="amo_speak">：
            # 上游连续 504 重试之后，模型把工具调用整段当正文吐了，而这条发送链路
            # 只过了「语音伪标签」一道，没走 clean_reply，守护侧也没有这类清洗。
            # 这里宁可整条不发，也不能把代码发进群。
            _clean_text = strip_pseudo_tags(text)
            if _clean_text != text:
                logger.info("[amo] 剥掉工具调用标记：%s -> %s"
                            % (truncate(text, 60), truncate(_clean_text, 60)))
                text = _clean_text
                _at_keep = [comp for comp in result.chain if isinstance(comp, Comp.At)]
                result.chain = _at_keep + ([Comp.Plain(text)] if text else [])
            if not text.strip() or has_tool_markup(text):
                logger.warning("[amo] 清洗后仍只剩代码标记，整条不发：%s"
                               % truncate(text, 80))
                result.chain = []
                return
            try:
                text = self._guard_self_location(text, self.state.current_activity().get("place"))
            except Exception:
                pass
            try:
                await self._settle_outfit_reply(event, text)
            except Exception as exc:
                logger.debug("[amo] 换装兜底失败: %s" % exc)
            try:
                if attribution_leak is not None and first_person_experience is not None:
                    body_now = event.message_str or ""
                    if first_person_experience(body_now) and attribution_leak(body_now, text):
                        hits = leak_tokens(body_now, text) if leak_tokens is not None else []
                        logger.warning(
                            "[amo] 归属串了（%s）：他说=%s / 她说=%s"
                            % ("、".join(hits) or "?", truncate(body_now, 40), truncate(text, 40))
                        )
                        alerts = getattr(self, "_attribution_alert", None)
                        if alerts is None:
                            alerts = {}
                            self._attribution_alert = alerts
                        alerts[str(event.unified_msg_origin)] = now_ts()
            except Exception:
                pass
            try:
                self._note_repay_promise(event, text)
            except Exception as exc:
                logger.debug("[amo] 记还款承诺失败: %s" % exc)
            try:
                self._settle_reply_promises(event, text)
            except Exception as exc:
                logger.debug("[amo] 记她答应的事失败: %s" % exc)
            # 先判断要不要补图：表情包/图片回复会被后面的非 Plain 检查提前 return，
            # 所以放在这里，保证「拍给我看看」即使她只回表情也能触发
            if self.draw is not None:
                try:
                    self.draw.maybe_after_reply(event, text)
                except Exception as exc:
                    logger.warning("[amo] 画图判断失败: %s" % exc)
            # 用上下文判断“这句是不是在跟她说”，而不是靠关键词猜
            addressed_to_me = self._is_talking_to_me(event)
            if not addressed_to_me and (
                looks_like_defensive_reply(text) or looks_like_ai_admission(text)
            ):
                # 他们在聊自己的事，她冒出一句“你才人机”很突兀：直接不发，当没看见。
                logger.info("[amo] 非指名对话里拦下防御话术，整条不发: %s" % text[:60])
                result.chain = []
                return
            elif looks_like_ai_admission(text):
                text = "哪有机器人？我怎么没看见？"
                result.chain = [Comp.Plain(text=text)]
            if looks_like_model_leak(text):
                # 模型名/厂商是后台信息，不能报；按角色打岔带过去
                logger.info("[amo] 拦截后台信息泄漏: %s" % text[:60])
                text = leak_deflect_text()
                result.chain = [Comp.Plain(text=text)]
            if not text.strip():
                return
            # 语音插件已经把同一句念出去了（amo_speak 工具路径）→ 正文别再重复一遍。
            # 语音插件在事件上留 amo_spoken_text / amo_spoken_ok，出声失败会撤回，
            # 撤回后这里照常发文字，所以不会出现「语音没成、文字也没了」。
            _spoken_text = str(getattr(event, "amo_spoken_text", "") or "").strip()
            _spoken_all = [str(x) for x in (getattr(event, "amo_spoken_texts", None) or [])
                           if str(x or "").strip()]
            if _spoken_text and _spoken_text not in _spoken_all:
                _spoken_all.append(_spoken_text)
            _voice_ok = bool(getattr(event, "amo_spoken_ok", False))
            if _spoken_all:
                # 记下这个会话最后一次发语音的时间：语音提示要靠它做冷却，别连着发
                _last_map = getattr(self, "_voice_last", None)
                if _last_map is None:
                    _last_map = {}
                    self._voice_last = _last_map
                _last_map[str(event.unified_msg_origin)] = now_ts()
            _dup = ""
            for _item in _spoken_all:
                if same_sentence(text, _item):
                    _dup = _item
                    break
            if not _dup and _spoken_all:
                # 这一轮已经用语音说过话了，正文又是差不多长度的同一段话（模型换了个说法）：
                # 也别再发一遍。只有正文明显更长（>1.8 倍）才认为它带了新内容。
                # 注：合成要 3 秒左右，这里常常还在「合成中」；真要是合成失败，
                # 语音插件会看到 amo_spoken_suppressed 自己把文字补发出去，不会丢话。
                _longest = max(_spoken_all, key=len)
                if len(_norm_sentence(text)) <= max(12, int(len(_norm_sentence(_longest)) * 1.8)):
                    _dup = _longest
            if _dup and _spoken_all:
                try:
                    event.amo_spoken_suppressed = True
                except Exception:
                    pass
                logger.info("[amo] 这句已经用语音说过了（%s），文字不再重复：%s"
                            % ("已发出" if _voice_ok else "合成中", text[:40]))
                result.chain = []
                return
            if getattr(event, "amo_voice_reply_only", False):
                # 他明确要的是语音，语音插件会把它念出来；这段文字就别再发了。
                # 但要把「要念的纯文本」留给语音插件兜底：模型有时不调 amo_speak，
                # 只输出 <astrbot_speak ...> 伪标签，清空 chain 会让整条回复消失。
                # 模型写了 <astrbot_speak text="…"> 的话，要念的是标签里那句
                spoken_text = (str(getattr(event, "amo_voice_text", "") or "").strip()
                               or _strip_voice_tags(text))
                if not spoken_text:
                    logger.info("[amo] 本轮只发语音，正文只有控制标签，整条不发")
                    result.chain = []
                    return
                else:
                    try:
                        event.amo_voice_text = spoken_text
                    except Exception:
                        pass
                    logger.info("[amo] 本轮只发语音，文字不发：%s" % spoken_text[:40])
                    result.chain = []
                    return
            group = not event.is_private_chat()
            if not group:
                # 私聊永远不引用（QQ / 飞书 / 任何平台）：连上游核心或别的插件
                # 塞进 chain 的 Reply 也在这里摘掉，而不是整条消息交回去不管。
                result.chain = [
                    comp for comp in result.chain if not isinstance(comp, Comp.Reply)
                ]
            if any(not isinstance(comp, (Comp.Plain, Comp.At)) for comp in result.chain):
                return
            quote_enabled = bool(
                self._quote_allowed(event.unified_msg_origin, group)
                or (group and getattr(event, "amo_quote_hint", False))
            )
            quote_id = getattr(event.message_obj, "message_id", None) if quote_enabled else None
            core_decor = self._core_decor_flags(event.unified_msg_origin)
            takeover = bool(core_decor.get("quote") or core_decor.get("mention"))
            if takeover and not getattr(self, "_core_decor_logged", False):
                logger.info(
                    "[amo] 检测到 AstrBot 全局引用/mention 开启：本插件接管发送，"
                    "避免核心覆盖「私聊不引用 / 群聊按概率引用」"
                )
                self._core_decor_logged = True
            if strip_brushoff is not None:
                try:
                    text, brush = strip_brushoff(text, event.message_str or "")
                    if brush:
                        logger.debug("[amo] 去掉赶人的话: %s" % brush)
                except Exception:
                    pass
            # 守护做最后一道工序（润色/去重/表情裁剪/兜底）；缺席、超时、报错都走原文
            if (_guard_process_reply is not None
                    and self.cfg_bool("guard_text_enable", False)
                    and not self.cfg_bool("guard_deliver_enable", False)):
                try:
                    _pieces = await _guard_process_reply(
                        self,
                        text,
                        "group" if group else "private",
                        timeout_ms=self.cfg_int("guard_text_timeout_ms", 2000),
                        task_type="polish",
                    )
                    if _pieces:
                        text = "\n".join(_pieces)
                        result.chain = [Comp.Plain(text)]
                except Exception as _guard_exc:
                    logger.debug("[amo] 守护后处理失败，用原文: %s" % _guard_exc)
            text = self._trim_reply(text)
            result.chain = [Comp.Plain(text)]

            # 守护接管「说出去」：它润色分段并逐条发；发成了这里只补记账。
            # 守护没装/异常/一条没发出去 → 整条原文直接发兜底。
            if _guard_deliver_reply is not None and self.cfg_bool("guard_deliver_enable", False):
                _delivered = await _guard_deliver_reply(
                    self,
                    text,
                    "group" if group else "private",
                    event.unified_msg_origin,
                    quote_id=quote_id if quote_enabled else None,
                    group=group,
                    timeout_ms=self.cfg_int("guard_text_timeout_ms", 2000),
                )
                if _delivered and _delivered.get("sent"):
                    result.chain = []
                    if _after_external_send is not None:
                        try:
                            await _after_external_send(
                                self, event, _delivered.get("text") or text)
                        except Exception as exc:
                            logger.debug("[amo] 守护发送后记账失败: %s" % exc)
                    logger.info("[amo] 守护已发送 %d 条 -> %s: %s"
                                % (_delivered.get("sent") or 0,
                                   event.unified_msg_origin,
                                   (_delivered.get("text") or text)[:300]))
                    return

            # 守护没发出去 → 兜底整条原文直接发；终端不再本地分段。
            if takeover and await self._send_now(
                event, text, quote_id if quote_enabled else None
            ):
                result.chain = []
                return
            self._remember_sent_reply(event, text)
            return
        except Exception as exc:
            logger.debug("[amo] 结果装饰失败: %s" % exc)

    # ---------- 后台循环 ----------
    async def _background_loop(self):
        try:
            await asyncio.sleep(4)
        except asyncio.CancelledError:
            return
        while self._running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                return
            except Exception:
                logger.exception("[amo] 后台任务异常")
            try:
                await asyncio.sleep(self.cfg_int("loop_interval_seconds", 30))
            except asyncio.CancelledError:
                return


    def _decay_hate_relations(self):
        try:
            cutoff = now_ts() - 7 * 86400
            rows = self.db.conn.execute(
                "SELECT uid FROM profiles WHERE relation='仇恨' AND relation_at>0 AND relation_at<=?",
                (cutoff,),
            ).fetchall()
            for row in rows:
                self.db.update_profile(str(row["uid"]), relation="抵触")
                logger.info("[amo] 仇恨超过7天，降为抵触: %s" % row["uid"])
        except Exception as exc:
            logger.debug("[amo] 仇恨关系衰减失败: %s" % exc)



    @staticmethod
    def _diary_day(value):
        """把 YYYY-MM-DD（或 date）统一成 date；认不出就 None。"""
        if isinstance(value, date):
            return value
        try:
            return date.fromisoformat(str(value or "").strip()[:10])
        except (TypeError, ValueError):
            return None

    def _diary_prompt(self, day, chat_lines, hourly_lines) -> str:
        """拼日记提示词：只给事实骨架，长度和口吻由她自己定。"""
        return (
            "日期：" + day.strftime("%Y年%m月%d日") + "\n"
            "这一天的聊天节选（他和我）：\n" + ("\n".join(list(chat_lines)[-200:]) or "（这天没怎么聊）") + "\n\n"
            "这一天的生活小日记：\n" + ("\n".join(list(hourly_lines)[-24:]) or "（没有小日记）") + "\n\n"
            "写今天这篇日记，正文直接开始：\n"
            "1. 以「生活小日记」为骨架：几点在哪、在做什么、吃了什么、天气怎样。\n"
            "2. 聊天里的话和你的感受可以写进去。\n"
            "3. 长短随你，一句话也可以。\n"
            "4. 口吻就是你平时的样子，可以有情绪、小脾气、细节。\n"
            "5. 小日记和聊天是你今天的事实来源，写的就是这些。\n"
            "6. 这是私人日记，结尾想带一句就带，换着说法："
            + "、".join("「" + item + "」" for item in _diary_pick_hints(DIARY_ENDING_HINTS, 16, day)) + "。\n"
            "直接输出正文。"
        )

    def _diary_clock(self):
        """diary_time 默认 10:00。"""
        raw = str(self.cfg_str("diary_time", "10:00") or "10:00").strip()
        try:
            hour, _, minute = raw.partition(":")
            return max(0, min(23, int(hour))), max(0, min(59, int(minute or 0)))
        except (TypeError, ValueError):
            return 10, 0

    # ---------- 日记存储：记忆库优先，本地 txt 只当回退 ----------

    async def _diary_store_put(self, day, text) -> str:
        """日记只写记忆库（本地 txt 那套已删）。"""
        iso = day.isoformat() if hasattr(day, "isoformat") else str(day)
        ok = await self._data_call("diary_put", self._data_bot_id(), iso, str(text or ""), "我的日记")
        if ok:
            return "memory:" + iso
        logger.warning("[amo] 日记写入记忆库失败：%s" % iso)
        return ""

    async def _diary_store_get(self, day) -> str:
        iso = day.isoformat() if hasattr(day, "isoformat") else str(day)
        text = await self._data_call("diary_get", self._data_bot_id(), iso)
        return text if isinstance(text, str) else ""



    async def _diary_chat_lines(self, day):
        """当天聊天 → 「谁：内容」行；取不到就返回空列表。"""
        day_start = int(datetime.combine(day, datetime.min.time()).timestamp())
        mem = self._data_mem()
        if mem is None or not callable(getattr(mem, "messages_between", None)):
            return []
        try:
            rows = await self._data_call(
                "messages_between", self._data_bot_id(), day_start, day_start + 86400, "", 500,
            ) or []
        except Exception as exc:
            logger.debug("[amo] 日记取聊天失败: %s" % exc)
            return []
        # 日记是从她的视角写的，之后会按私聊范围进记忆：群里的对话不该混进来
        rows = _private_rows(rows)
        lines = []
        for row in rows:
            text = str(row.get("content") or "").strip().replace("\n", " ")
            if not text or str(row.get("role") or "") == "system":
                continue
            who = "我" if str(row.get("role") or "") == "bot" else (str(row.get("name") or "") or "他")
            lines.append(who + "：" + text[:200])
        return lines







    def _first_private_umo(self):
        try:
            for profile in self.db.list_profiles(limit=50):
                if profile.get("private_umo"):
                    return profile["private_umo"]
        except Exception:
            pass
        return ""

    async def _auto_learn(self):
        """定时提炼长期事实，写进记忆库；本插件不再存记忆。"""
        try:
            users = self.db.active_profiles(now_ts() - 3600, limit=2)
        except Exception as exc:
            logger.warning("[amo] 自动学习取人失败: %s" % exc)
            return
        if not users:
            logger.debug("[amo] 自动学习：这一小时没有可学的人")
            return
        for user in users:
            uid = str(user.get("uid", ""))
            if not uid:
                continue
            key = "auto_learn_" + uid
            last = to_float(self.db.kv_get(key, 0))
            interval = max(5, self.cfg_int("auto_learn_minutes", 15)) * 60
            if now_ts() - last < interval:
                continue
            try:
                profile_row = self.db.get_profile(uid) or {}
                home_umo = str(profile_row.get("private_umo") or "").strip()
                if not home_umo:
                    # 还没私聊过：不要退到全局会话，否则群聊的话会被当成他说的
                    continue
                rows = await self._recent_by_uid(uid, 20, umo=home_umo)
                lines = []
                for row in rows:
                    row_umo = str(row.get("umo") or "").strip()
                    if row_umo and row_umo != home_umo:
                        continue
                    role = str(row.get("role") or "")
                    if role == "summary":
                        continue
                    who = "我" if role == "bot" else "他"
                    lines.append("[" + who + "] " + str(row.get("content") or ""))
                if not lines:
                    continue
                facts = await self.llm.extract_facts(
                    home_umo, user.get("name", "") or uid, lines
                )
                ok_any = False
                for fact in facts:
                    written = await self._write_memory_checked(
                        uid, fact["content"], fact["kind"], fact["tier"]
                    )
                    ok_any = ok_any or written
                if facts and not ok_any:
                    logger.warning("[amo] 记忆写入失败，本轮不标记已学: %s" % uid)
                    continue
                if facts:
                    logger.info("[amo] 自动学习：%s 学到 %d 条事实" % (user.get("name") or uid, len(facts)))
                self.db.kv_set(key, now_ts())
            except Exception as exc:
                logger.debug("[amo] 自动学习失败: %s" % exc)

    def _is_proactive_friend(self, profile):
        return str(profile.get("relation") or "普通") in ("熟识", "相恋")

    def _pending_key(self, uid):
        return "proactive_pending_" + str(uid)

    def _set_proactive_pending(self, uid, kind, text, umo=""):
        self.db.kv_set(self._pending_key(uid), {
            "sent_at": now_ts(), "kind": kind, "text": str(text or ""),
            # 记下真正发出去的会话：追问要回同一个平台，否则会「飞书问完、QQ 追」。
            "umo": str(umo or ""),
            "followup": False, "mood": False,
        })

    def _clear_proactive_pending(self, uid):
        pending = self.db.kv_get(self._pending_key(uid), None)
        if pending:
            self.db.kv_set(self._pending_key(uid), {})
            self.db.kv_set("proactive_ignored_" + str(uid), 0)

    def _depressed_active(self, uid):
        return to_float(self.db.kv_get("proactive_depressed_until_" + str(uid), 0), 0) > now_ts()

    def _set_depressed(self, uid):
        hours = max(1, self.cfg_int("proactive_depressed_hours", 24))
        self.db.kv_set("proactive_depressed_until_" + str(uid), now_ts() + hours * 3600)

    def _try_soothe(self, uid, text):
        if not self._depressed_active(uid):
            return
        words = ("抱抱", "亲亲", "哄", "对不起", "别难过", "喜欢你", "爱你", "怎么啦", "我在", "在呢", "乖")
        if any(word in str(text or "") for word in words):
            self.db.kv_set("proactive_depressed_until_" + str(uid), 0)
            self.db.kv_set("proactive_ignored_" + str(uid), 0)
            self.state.feel_bump({"sadness": -6, "joy": 4, "love": 3},
                                 weight=self.state.relation_feel_weight(uid))
            logger.debug("[amo] 抑郁状态被哄好: %s" % uid)

    # 每天的固定问候：kind、开关、时段、默认时段
    RITUAL_SPECS = (
        ("goodnight", "ritual_goodnight", "ritual_goodnight_window", "22:00-02:00"),
        ("morning", "ritual_morning", "ritual_morning_window", "06:30-10:00"),
        ("lunch", "ritual_lunch", "ritual_lunch_window", "11:00-13:30"),
    )

    FOLLOWUP_TEMPLATES = {
        "slack": [
            "在忙吗？怎么不理我。",
            "老公老公，你在忙着什么呀，这么久不理我。",
            "喂——人呢，是不是又把我晾一边了。",
            "忙完了没呀，我在这儿等半天了。",
            "是不是我太吵了？那我安静会儿，你有空回我一下。",
            "你这会儿在忙啥呢，回我一句我就不闹了。",
        ],
        "greet": [
            "？怎么不理我了？",
            "你是不是没看见我呀。",
            "醒醒，在等你呢。",
            "我在这儿呢，你倒是看我一眼呀。",
            "喂喂，人呢？",
        ],
        "meal": [
            "饭吃了没？",
            "到饭点了，别又随便对付一口。",
            "吃了啥呀，说给我听听。",
            "中午吃点什么呀，别又忘了。",
        ],
        "offwork": [
            "今天过得怎么样呀？",
            "你忙完记得回我一句嘛。",
            "你是还在加班吗？",
            "下班没呀，别又拖到很晚。",
        ],
        "comfort": [
            "好点了吗？",
            "还难受吗，要不要跟我说说。",
            "舒服点没有呀。",
            "还疼不疼，别硬撑着。",
        ],
    }

    @staticmethod
    def _followup_topics(text):
        """追问别再问同一件事：按话题打标，避开上一句已经问过的内容。"""
        text = str(text or "")
        groups = (
            ("food", ("吃", "饭", "饿", "外卖", "餐")),
            ("comfort", ("疼", "难受", "舒服", "药", "撑着")),
            ("work", ("下班", "加班", "上班", "项目")),
        )
        return {name for name, words in groups if any(word in text for word in words)}

    def _followup_text(self, uid, kind, previous_text=""):
        """追问换着说法：同一句不连着出现，也别把刚问的问题再问一遍。"""
        templates = [t for t in (self.FOLLOWUP_TEMPLATES.get(str(kind)) or self.FOLLOWUP_TEMPLATES["greet"]) if t]
        if not templates:
            return "？怎么不理我了？"
        key = "proactive_followup_last_%s" % uid
        try:
            last = str(self.db.kv_get(key, "") or "")
        except Exception:
            last = ""
        pool = [t for t in templates if t != last]
        topics = self._followup_topics(previous_text)
        if topics:
            fresh = [t for t in pool if not (self._followup_topics(t) & topics)]
            pool = fresh
        if not pool:
            # 同一类话题的问句都问过了，就换成「怎么不理我」的催回，别再问一遍。
            pool = [t for t in self.FOLLOWUP_TEMPLATES["greet"] if t != last] or list(self.FOLLOWUP_TEMPLATES["greet"])
        text = random.choice(pool)
        try:
            self.db.kv_set(key, text)
        except Exception:
            pass
        return text

    def _pending_still_blocking(self, uid, profile, now) -> bool:
        pending = self.db.kv_get(self._pending_key(uid), None)
        if not isinstance(pending, dict) or not pending.get("sent_at"):
            return False
        sent_at = to_float(pending.get("sent_at"), 0)
        if not sent_at:
            return False
        # 他在这之后说过话（不管在哪个平台），就当她「已经看见她」了，不用再等
        try:
            if to_float(profile.get("last_seen"), 0) > sent_at + 60:
                self.db.kv_set(self._pending_key(uid), {})
                return False
        except Exception:
            pass
        if now - sent_at >= proactive_pending_block_seconds(self.cfg_int):
            return False
        return True


    def _ritual_in_window(self, spec):
        try:
            start, end = str(spec).split("-", 1)
            return in_minute_range(minutes_now(), parse_hhmm(start), parse_hhmm(end))
        except Exception:
            return False

    def _ritual_umos(self, profile):
        """她能给你发问候的会话：QQ、飞书…按最近说过话排序。"""
        uid = str(profile.get("uid") or "")
        items = []
        try:
            data = self.db.kv_get("channels:%s" % uid, {}) or {}
        except Exception:
            data = {}
        if isinstance(data, dict):
            entries = [value for value in data.values() if isinstance(value, dict) and value.get("umo")]
            entries.sort(key=lambda value: -to_float(value.get("ts"), 0))
            for value in entries:
                umo = str(value.get("umo") or "")
                if umo and umo not in items:
                    items.append(umo)
        private_umo = str(profile.get("private_umo") or "")
        if private_umo and private_umo not in items:
            items.append(private_umo)
        return items

    def _recent_greeting(self, uid, minutes):
        """最近一次每日问候发在哪个平台、隔了多久（QQ/飞书算同一个人）。"""
        if not uid:
            return False
        try:
            data = self.db.kv_get("greeting_last:%s" % uid, {}) or {}
        except Exception:
            data = {}
        if not isinstance(data, dict):
            return False
        return _within_minutes(data.get("ts"), now_ts(), minutes)

    def _mark_greeting(self, uid, kind, umo):
        try:
            self.db.kv_set("greeting_last:%s" % str(uid), {
                "kind": str(kind),
                "umo": str(umo or ""),
                "ts": now_ts(),
            })
        except Exception:
            pass


    #: 每个问候从当天几点开始算「今天已经聊过」；不在表里的按 45 分钟活跃窗。
    RITUAL_FROM_HOURS = {"morning": 5, "lunch": 11, "goodnight": 21}

    def _ritual_lookback_start(self, kind):
        """「今天这个时段已经聊过」的判定起点。

        不能只看最后 10 条 / 45 分钟：06:52 他说「早上好」、07:10 收尾，
        到 08:00 两道闸都过期，于是又问一遍「你醒了没」。所以按当天时段判。
        """
        now = now_ts()
        hours = getattr(self, "RITUAL_FROM_HOURS", None) or {"morning": 5, "lunch": 11, "goodnight": 21}
        hour = hours.get(str(kind))
        if hour is None:
            return now - max(5, self.cfg_int("ritual_skip_recent_minutes", 45)) * 60
        try:
            base = datetime.fromtimestamp(now).replace(
                hour=int(hour), minute=0, second=0, microsecond=0)
            start = base.timestamp()
            if start > now:
                # 凌晨 0-2 点的晚安算「昨天 21:00 起」；其他时段还没到点就从现在算
                start = start - 24 * 3600 if str(kind) == "goodnight" else now
            return start
        except Exception:
            return now - max(5, self.cfg_int("ritual_skip_recent_minutes", 45)) * 60

    def _ritual_judge_rows(self, rows, kind, since):
        """按已经取到的消息判断今天这个问候还发不发；QQ/飞书一起算。"""
        rows = [row for row in (rows or []) if to_float(row.get("created_at"), 0) >= since]
        rows.sort(key=lambda row: to_float(row.get("created_at"), 0))
        now = now_ts()
        recent_gap = max(5, self.cfg_int("ritual_skip_recent_minutes", 45)) * 60
        if rows:
            last_at = to_float(rows[-1].get("created_at"), 0)
            if last_at and now - last_at < recent_gap:
                return False
        if not self.cfg_bool("ritual_skip_if_greeted", True):
            return True
        # 只认「他」问候过：她自己那句「吃了没 / 晚安」多半是主动消息或追问，
        # 算进来会把当天的问候整段吃掉（午饭问候时有时无就是这么来的）。
        texts = [str(row.get("content") or "") for row in rows if str(row.get("role") or "") == "user"]
        # 不再只看最后 10 条：早上聊了几十句之后，最早那句「早」会被挤出去。
        joined = "\n".join(texts)
        if kind == "morning":
            return not bool(re.search(r"(?:^|\s)早(?:\s|$|[，,、!！。~～])|早安|早上好|早上好呀|我醒了|起床了|还没起来吗|醒了没", joined))
        if kind == "goodnight":
            return not bool(re.search(r"晚安|睡了|睡觉|先睡|去睡|早点休息", joined))
        if kind == "lunch":
            return not bool(re.search(r"午饭|中午吃|吃啥|吃什么|吃饭|吃了没|吃了吗", joined))
        return True

    #: 早上算「他已经醒了」的说法；任何会话里说过一次就算。
    RITUAL_MORNING_WORDS = re.compile(
        r"(?:^|\s)早(?:\s|$|[，,、!！。~～])|早安|早上好|我醒了|醒了|起床了|起来了|刚起")

    def _ritual_he_is_around(self, rows, kind, since):
        """他今天露过面，就不再发「醒了没 / 还没起来吗」这种问候。

        2026-11-18：她 07:35 在私聊说「早，刚起来」、11:05 还在群里连着说话，
        11:00 的问候还是问了「醒没醒」。原因就是判定只看私聊、而且只认吃饭词。
        """
        mine = [row for row in (rows or []) if str(row.get("role") or "") == "user"]
        if not mine:
            return False
        now = now_ts()
        gap = max(5, self.cfg_int("ritual_skip_recent_minutes", 45)) * 60
        last_at = max(to_float(row.get("created_at"), 0) for row in mine)
        if str(kind) in ("morning", "lunch") and last_at and (now - last_at) < gap:
            # 他刚在群里/私聊说过话 = 他醒着、人还在，这时候问「醒了没」最伤人。
            return True
        if str(kind) == "morning":
            joined = "\n".join(str(row.get("content") or "") for row in mine)
            if self.RITUAL_MORNING_WORDS.search(joined):
                return True
        return False

    def _ritual_should_send(self, umos, kind):
        """同步版：只读本地缓存表/内存缓冲（拿不到记忆库时的兜底）。"""
        umos = list(umos) if isinstance(umos, (list, tuple, set)) else [umos]
        since = self._ritual_lookback_start(kind)
        rows = []
        for item in umos:
            try:
                rows.extend(self.db.messages_since_umo(item, since, 200))
            except Exception:
                try:
                    rows.extend(self._recent(item, 10))
                except Exception:
                    pass
        return self._ritual_judge_rows(rows, kind, since)

    async def _ritual_should_send_async(self, umos, kind, uid=""):
        """真正发送前用这个：消息真相在记忆库。

        插件本地的 messages 表最后一条停在 11-09（容量/迁移后不再写入），
        只看它会永远判成「今天还没聊过」，于是 8 点又问一遍「醒了没」。
        """
        since = self._ritual_lookback_start(kind)
        uid = str(uid or "")
        if uid:
            try:
                rows = await self._data_call(
                    "messages_since", self._data_bot_id(), uid, int(since), 400)
            except Exception as exc:
                logger.debug("[amo] 问候判定取聊天失败: %s" % exc)
                rows = []
            if rows:
                # 群聊内容不进私聊的话题判定（和里程碑同一口径），
                # 但「他在不在场」必须看全部会话：上一秒还在群里说话，
                # 就不能再问「醒了没」（2026-11-18 病象）。
                if not self._ritual_judge_rows(_private_rows(rows), kind, since):
                    return False
                return not self._ritual_he_is_around(rows, kind, since)
        return self._ritual_should_send(umos, kind)


    def _choose_proactive_kind(self, profile, snap, category=""):
        relation = profile.get("relation", "普通")
        rel = snap.get("feel_rel") or {}
        painful = (
            snap["health"]["sick"]
            or snap["period"]["pain"] >= 6
            or rel.get("sadness", 50.0) >= 62
            or rel.get("fatigue", 40.0) >= 72
        )
        if relation == "相恋" and painful and self.cfg_bool("proactive_comfort", True):
            return "comfort"
        activity = str((snap.get("activity") or {}).get("activity") or "")
        if category == "play" and ("游戏" in activity or "打游戏" in activity):
            return "game"
        if category == "meal":
            return "meal"
        if category in ("rest", "play"):
            return "slack"
        if category == "commute":
            return "offwork" if _now().hour >= 16 else "commute"
        if relation in ("熟识", "相恋") and random.random() < self.cfg_float("proactive_share_prob", 0.35):
            return "share"
        return "greet"


    # ---- 主动消息节流 ----
    def _proactive_user_just_talked(self, profile, now):
        """对方刚说过话就别主动插话。0 表示关闭这项检查。"""
        minutes = max(0, self.cfg_int("proactive_user_idle_minutes", 10))
        if not minutes:
            return False
        last_user_at = to_float(profile.get("last_seen"), 0)
        return bool(last_user_at) and (now - last_user_at) < minutes * 60

    def _proactive_forced_allowed(self, profile, now):
        """「日常关心」也要跟上次主动拉开间隔，避免重启后立刻又发。"""
        gap = max(1, self.cfg_int("proactive_forced_gap_minutes", 30)) * 60
        return (now - to_float(profile.get("last_proactive", 0))) >= gap

    def _forced_hour_key(self, uid):
        return "proactive_forced_hour_" + str(uid or "")

    def _forced_sent_this_hour(self, uid):
        """「日常关心」每小时只强制一次；存数据库，热重载/重启都不清空。"""
        mark = today_str() + ":" + str(_now().hour)
        try:
            return str(self.db.kv_get(self._forced_hour_key(uid), "")) == mark
        except Exception:
            return self._last_proactive_activity.get(str(uid)) == mark

    def _mark_forced_hour(self, uid):
        mark = today_str() + ":" + str(_now().hour)
        self._last_proactive_activity[str(uid)] = mark
        try:
            self.db.kv_set(self._forced_hour_key(uid), mark)
        except Exception:
            pass

    # ---- 主动消息多平台轮换 ----
    def _record_channel(self, uid, umo, platform):
        """记下这个人各平台的会话地址，供主动消息选边。"""
        if not uid or not umo:
            return
        try:
            key = "channels:%s" % uid
            data = self.db.kv_get(key, {}) or {}
            if not isinstance(data, dict):
                data = {}
            data[str(platform or "?")] = {"umo": str(umo), "ts": now_ts()}
            self.db.kv_set(key, data)
        except Exception as exc:
            logger.debug("[amo] 记录通道失败: %s" % exc)






    @staticmethod
    def _clean_weather_alert(text):
        """把模型偶尔蹦出的客服腔/播报腔挡掉，宁可退回模板。"""
        value = str(text or "").strip().strip('"').strip("“”").strip()
        value = re.sub(r"^(?:天气提醒|提醒你|温馨提示)[：:，,\s]*", "", value)
        for bad in ("请注意", "建议您", "提醒您", "天气预报", "温馨提示", "作为AI", "作为 AI", "助手"):
            if bad in value:
                return ""
        if len(value) > 80:
            return ""
        return value




    def _proactive_owner_ids(self, profiles=None):
        """主动私聊的对象：配了 proactive_owner_ids 只认名单；留空 = 管理员 + 相恋。"""
        raw = str(self.cfg_str("proactive_owner_ids", "") or "").replace("，", ",")
        ids = {item.strip() for item in raw.split(",") if item.strip()}
        if ids:
            return ids
        ids = {str(uid).strip() for uid in (self.admin_uids or set()) if str(uid).strip()}
        rows = profiles
        if rows is None:
            try:
                rows = self.db.proactive_profiles(limit=200)
            except Exception:
                rows = []
        for profile in rows or []:
            try:
                if str(profile.get("relation") or "") != "相恋":
                    continue
                uid = str(profile.get("uid") or "").strip()
            except Exception:
                continue
            if uid:
                ids.add(uid)
        return ids


    # ---------- 指令 ----------

    def _resolve_target(self, event, args, index):
        if Comp is not None:
            for comp in event.get_messages():
                if isinstance(comp, Comp.At):
                    target = str(getattr(comp, "qq", ""))
                    if target and target != "all" and target != str(event.get_self_id()):
                        return target
        if index < len(args):
            token = str(args[index]).strip().lstrip("@")
            if token in ("我", "me", "self"):
                return self._canonical_uid(event)
            if token:
                return token
        return self._canonical_uid(event)


    def _format_status(self, data):
        mood = data["mood"]
        mood_line = " ".join([key + str(int(value)) for key, value in mood.items()])
        threshold = data["threshold"]
        return "\n".join([
            "🌙 陪伴 · 当前状态",
            "🕒 " + str(data["time"]),
            "💛 心情：" + str(data["dominant"]) + "（" + mood_line + "）",
            "🩸 生理期：" + str(data["period"]["phase"]) + " 第" + str(data["period"]["day"]) + "天（" + str(data["period"]["tone"]) + "）",
            "🩺 身体：" + str(data["health"]["status"]),
            "🌦 天气：" + str(data["weather_text"]),
            "📅 正在：" + str(data["activity"].get("activity", "休息")) + "（" + str(data["activity"].get("place", "")) + "）",
            "🎚 心流阈值：" + str(threshold["value"]) + "（基础 " + str(threshold["base"]) + "，活跃度 " + str(data["activity_rate"]) + "%）",
            "📚 档案 " + str(data["counts"]["profiles"]) + " · 记忆 " + str(data["counts"]["memories"]) + " · 消息 " + str(data["counts"]["messages"]),
        ])


    # ---------- 心流完整版指令 ----------
    @filter.command("heartflow")
    async def cmd_heartflow(self, event: AstrMessageEvent):
        await self._ensure_ready()
        if self.heartflow is None:
            yield event.plain_result("心流引擎未加载")
            return
        async for item in self.heartflow.heartflow_status(event):
            yield item

    @filter.command("heartflow_debug")
    async def cmd_heartflow_debug(self, event: AstrMessageEvent):
        await self._ensure_ready()
        if self.heartflow is None:
            yield event.plain_result("心流引擎未加载")
            return
        async for item in self.heartflow.heartflow_debug(event):
            yield item

    @filter.command("heartflow_clear")
    async def cmd_heartflow_clear(self, event: AstrMessageEvent):
        await self._ensure_ready()
        if self.heartflow is None:
            yield event.plain_result("心流引擎未加载")
            return
        async for item in self.heartflow.heartflow_clear_buffer(event):
            yield item

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("heartflow_log")
    async def cmd_heartflow_log(self, event: AstrMessageEvent):
        await self._ensure_ready()
        if self.heartflow is None:
            yield event.plain_result("心流引擎未加载")
            return
        async for item in self.heartflow.heartflow_toggle_log(event):
            yield item

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("heartflow_reset")
    async def cmd_heartflow_reset(self, event: AstrMessageEvent):
        await self._ensure_ready()
        if self.heartflow is None:
            yield event.plain_result("心流引擎未加载")
            return
        async for item in self.heartflow.heartflow_reset(event):
            yield item

    @filter.command("heartflow_help")
    async def cmd_heartflow_help(self, event: AstrMessageEvent):
        await self._ensure_ready()
        if self.heartflow is None:
            yield event.plain_result("心流引擎未加载")
            return
        async for item in self.heartflow.heartflow_help(event):
            yield item

    @filter.command("amo")
    async def cmd_amo(self, event: AstrMessageEvent):
        await self._ensure_ready()
        try:
            message = await self._handle_command(event)
        except Exception as exc:
            logger.error("[amo] 指令异常: %s" % exc)
            message = "处理失败：" + str(exc)
        if message:
            yield event.plain_result(message)

    @filter.command("c_status")
    async def cmd_status(self, event: AstrMessageEvent):
        await self._ensure_ready()
        yield event.plain_result(self._format_status(await self._status_data()))

    @filter.command("c_profile")
    async def cmd_profile(self, event: AstrMessageEvent):
        await self._ensure_ready()
        uid = self._canonical_uid(event)
        profile = self.db.get_profile(uid)
        if not profile:
            yield event.plain_result("还没有你的档案。")
            return
        yield event.plain_result(
            "🤍 关系：" + str(profile.get("relation", "普通"))
            + "\n📖 记忆条数：" + str(self._data_memory_count(uid))
        )

    @filter.command("c_setrel")
    async def cmd_setrel(self, event: AstrMessageEvent):
        await self._ensure_ready()
        if not self._is_admin(event):
            yield event.plain_result("只有管理员才能调整关系。")
            return
        parts = [item for item in (event.message_str or "").replace("/", " ").split() if item]
        relation = parts[-1] if parts else ""
        if relation not in RELATIONS:
            yield event.plain_result("用法：/c_setrel 仇恨|抵触|普通|熟识|相恋")
            return
        uid = self._canonical_uid(event)
        self.db.update_profile(uid, relation=relation)
        yield event.plain_result("✅ 关系已设置为：" + relation)

    @filter.command("learn_and_gate")
    async def cmd_learn(self, event: AstrMessageEvent):
        await self._ensure_ready()
        text = (event.message_str or "").replace("/learn_and_gate", "").strip()
        if not text:
            yield event.plain_result("请输入要学习的内容")
            return
        uid = self._canonical_uid(event)
        scope, group_id = self._memory_scope(event)
        if await self._write_memory_checked(uid, text, "manual", 1, scope, group_id):
            yield event.plain_result("✅ 已经记下来啦。")
        else:
            yield event.plain_result("⚠️ 记忆库没写进去，稍后再试。")

    # ---------- Web 面板 ----------
        # 不注册无前缀的旧路由，避免和其他插件或 AstrBot 自带路由冲突。


    #: 排障用的调试接口：默认不注册，配置文件里 debug_enabled=true 才出现
    DEBUG_ROUTES = frozenset({
        "/draw/test", "/draw/decide", "/draw/status",
        "/say", "/heartflow_debug", "/heartflow_reset", "/heartflow_clear",
        "/heartflow_log", "/kb/regen", "/scenic_kb/regen", "/worldview/regen",
    })





    @staticmethod
    def _coerce_config_value(kind, value):
        if kind == "bool":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "on", "是")
        if kind == "int":
            return int(float(value))
        if kind == "float":
            return float(value)
        if kind in ("list", "template_list"):
            if isinstance(value, list):
                return value
            parsed = json.loads(value) if isinstance(value, str) and value.strip() else []
            return parsed if isinstance(parsed, list) else []
        if kind in ("dict", "object"):
            if isinstance(value, dict):
                return value
            parsed = json.loads(value) if isinstance(value, str) and value.strip() else {}
            return parsed if isinstance(parsed, dict) else {}
        return str(value)


    # 这些值绝不能随 /config 明文下发（GET 无 body、无 CSRF 校验）
    SENSITIVE_KEYS = {"hefeng_key", "deepseek_api_key"}


    @staticmethod
    def _mask_secret(value):
        text = str(value or "")
        if not text:
            return ""
        if len(text) <= 8:
            return "*" * len(text)
        return text[:4] + "*" * (len(text) - 8) + text[-4:]



    # ---- 中文城市名 → LocationID（离线表，见 amo_city_index.py） ----
    def _city_module(self):
        """离线城市表模块（懒加载；缺失时返回 None，天气按原样走）。"""
        try:
            try:
                from . import amo_city_index
            except Exception:
                import amo_city_index
            return amo_city_index
        except Exception as exc:
            logger.debug("[amo] 城市表不可用: %s" % exc)
            return None

    def _city_lookup(self, text):
        """把「东莞」「北京朝阳」解析成 LocationID；失败返回 None。"""
        module = self._city_module()
        if module is None:
            return None
        try:
            return module.resolve_city(text)
        except Exception as exc:
            logger.debug("[amo] 城市名解析失败: %s" % exc)
            return None

    #: 他说「在外地/出差」这类没有城市名的说法
    HE_AWAY_WORDS = ("外地", "出差", "不在本地", "外省", "在外头", "回不来", "还没回")
    #: 他说自己回来了
    HE_HOME_WORDS = ("我回来了", "回来了", "到家了", "我在家", "回东莞", "到东莞了")




    async def _reject_follow_trip(self, uid, offer):
        """他让她好好上班：她闷闷不乐，日程不变，日记记一笔。"""
        city = str(offer.get("city") or "").strip()
        self.db.kv_set("follow_offer", {})
        self.db.kv_set("follow_declined", {"city": city, "day": today_str()})
        try:
            self.state.feel_bump({"sadness": 9, "love": 2, "joy": -5})
        except Exception:
            pass
        try:
            content = "她说想去%s陪他，他让她好好上班，她闷闷不乐" % city
            if not await self._write_memory_checked(uid, content, "event", 1):
                logger.warning("[amo] 被拒记忆没写进去")
        except Exception as exc:
            logger.warning("[amo] 被拒记忆失败: %s" % exc)
        try:
            log = self.db.kv_get("follow_reject_log", []) or []
            if not isinstance(log, list):
                log = []
            log.append({"day": today_str(), "hour": "%02d:00" % _now().hour, "city": city})
            self.db.kv_set("follow_reject_log", log[-10:])
        except Exception:
            pass
        return _follow_block(False, city)












    # ---- 用量 / 余额 ----




    # ---- 供应商识别 / 多模型用量 ----




    @staticmethod
    def _balance_probe_kind(api_base):
        base = str(api_base or "").lower()
        if "deepseek" in base:
            return "deepseek"
        if "siliconflow" in base:
            return "siliconflow"
        return "openai_bill"






    VOICE_PLUGIN_NAMES = ("DeepSeek_Harness_Amo_Image", "astrbot_plugin_speechsound", "amo_speechsound")
    # 语音插件（我想永远陪着你-语音）的设置：key, 类型, 标题, 说明, 默认值
    # 只放行为类开关；后端 / key / 音色仍然在语音插件自己的配置页填。
    VOICE_SETTING_KEYS = (
        ("enable", "bool", "启用语音", "总开关：关掉后她发不了语音，也不会有兜底转语音。", True),
        ("group_enable", "bool", "允许群聊发语音", "默认关。群聊里还受下面的「每天条数」和「最小间隔」限制。", False),
        ("auto_fallback", "bool", "兜底转语音", "你明说要语音、她只回了文字时，补一条语音。", True),
        ("read_relation", "bool", "参考关系度决定语气", "从陪伴这边读关系阶段，越亲近越容易开口、语气越软。", True),
        ("schedule_aware", "bool", "参考日程决定场景", "按在家里 / 在外面 / 在睡觉切到对应场景音色。", True),
        ("speak_threshold", "float", "开口阈值（0-1，越高越少开口）", "兜底规则用的及格线。她主动调工具发语音时不受这个限制。", 0.6),
        ("daily_quota", "int", "群聊每天语音条数上限", "所有群共用这一份额度，0 = 不限。私聊不占这个额度。", 10),
        ("cooldown_seconds", "int", "群聊两条语音最小间隔（秒）", "只管群聊，防刷屏。", 240),
        ("private_cooldown_seconds", "int", "私聊两条语音最小间隔（秒）", "0 = 私聊不冷却（推荐）。", 0),
        ("max_chars", "int", "每段字数上限", "整条语音总长 = 这个数 × 最多分段数，超过就退回文字。", 80),
        ("max_segments", "int", "最多分段数", "长句按标点切段，最多切几段。", 2),
        ("speed", "float", "语速（0.5-2.0）", "1.0 是正常语速。", 1.0),
        ("volume", "float", "音量（0.1-2.0）", "", 1.0),
    )

    def _voice_plugin(self):
        """找「我想永远陪着你-语音」插件实例；没装或没启用返回 None。"""
        for name in self.VOICE_PLUGIN_NAMES:
            try:
                meta = self.context.get_registered_star(name)
            except Exception:
                meta = None
            star = self._voice_instance(meta)
            if star is not None:
                return star
        try:
            for meta in self.context.get_all_stars():
                marker = ((getattr(meta, "name", "") or "") + " "
                          + (getattr(meta, "module_path", "") or "")).lower()
                if "speechsound" not in marker:
                    continue
                star = self._voice_instance(meta)
                if star is not None:
                    return star
        except Exception:
            pass
        return None

    @staticmethod
    def _voice_instance(meta):
        if meta is None:
            return None
        for attr in ("star_cls", "instance", "star", "plugin"):
            value = getattr(meta, attr, None)
            if value is None or isinstance(value, type):
                continue
            if callable(getattr(value, "_persist_config", None)) and hasattr(value, "config"):
                return value
        return None

    @staticmethod
    def _voice_value(config, key, kind, default):
        try:
            raw = config.get(key) if hasattr(config, "get") else None
        except Exception:
            raw = None
        if raw is None:
            return default
        if kind == "bool":
            if isinstance(raw, bool):
                return raw
            return str(raw).strip().lower() in ("1", "true", "yes", "on", "开")
        if kind == "int":
            try:
                return int(float(raw))
            except Exception:
                return default
        if kind == "float":
            try:
                return float(raw)
            except Exception:
                return default
        return str(raw)

    def _voice_panel_items(self):
        """面板「语音」分组的行：值来自语音插件的配置。"""
        plugin = self._voice_plugin()
        if plugin is None:
            return []
        config = getattr(plugin, "config", {}) or {}
        items = []
        for key, kind, title, hint, default in self.VOICE_SETTING_KEYS:
            items.append({
                "key": key,
                "type": kind,
                "description": title,
                "hint": hint,
                "default": default,
                "options": [],
                "special": "",
                "group": "语音",
                "external": "voice",
                "value": self._voice_value(config, key, kind, default),
            })
        return items











    def _brain_thoughts(self, limit=40):
        """她想过什么：记忆库 records 里 kind=thought 的那批（倒序）。"""
        db = os.path.join(os.path.dirname(os.path.dirname(self.plugin_dir)),
                          "plugin_data", "Astr_Amo_data", "amo_data.db")
        if not os.path.exists(db):
            return []
        con = sqlite3.connect("file:%s?mode=ro" % db, uri=True, timeout=3)
        try:
            rows = con.execute(
                "select kind, title, detail, ts from records "
                "where kind in ('thought', 'idea', '想法') order by ts desc limit ?",
                (int(limit),)).fetchall()
        except Exception:
            rows = []
        finally:
            con.close()
        return [{"kind": r[0], "title": r[1], "text": r[2], "ts": r[3]} for r in rows]






















    # ---------- 财务中枢：所有钱只能走这里 ----------
    #
    # 设计要点：
    #   * 医疗、房租、购物都不许自己改账，一律调 charge()/income()；
    #   * 成功不写日志（正常交易不该刷屏），失败由金融插件打 warning；
    #   * 每笔都会同步到 self.state.finance，她下次开口时心里有数。

    FINANCE_PLUGIN_NAMES = ("DeepSeek_Harness_Amo_Finance",)

    def _finance(self):
        """找「我想永远陪着你-金融」实例；没装返回 None（只有这一个名字）。"""
        try:
            meta = self.context.get_registered_star("DeepSeek_Harness_Amo_Finance")
        except Exception:
            meta = None
        return self._finance_instance(meta)

    @staticmethod
    def _finance_instance(meta):
        if meta is None:
            return None
        for attr in ("star_cls", "instance", "star", "plugin"):
            value = getattr(meta, attr, None)
            if value is not None:
                return value
        return None


    #: 单笔扣款上限：模型或挂载插件算错时，宁可拒绝，也不能把余额一次清空。
    CHARGE_MAX = 100000.0

    def _primary_uid(self) -> str:
        """花钱要记在「人」身上，不能记到群里随便谁。

        顺序：相恋关系的人 → 最近私聊的人 → 随便一个画像（最后兜底）。
        之前直接取 ``list_profiles(limit=1)``，结果记到了列表里第一个陌生人头上。
        """
        try:
            for uid in self._lover_aliases().values():
                if uid:
                    return str(uid)
        except Exception:
            pass
        try:
            umo = str(getattr(self, "_last_umo", "") or "") or self._first_private_umo()
        except Exception:
            umo = ""
        parts = [part for part in str(umo).split(":") if part]
        if len(parts) >= 3 and "group" not in str(umo).lower():
            return parts[-1]
        try:
            rows = self.db.list_profiles(limit=1)
        except Exception:
            rows = []
        return str(rows[0].get("uid") or "") if rows else ""

    #: 失败单只在内存里留 60 秒（挡并发重试）；成功单才持久化。
    CHARGE_FAIL_TTL = 60.0
    #: 持久化多少条成功幂等号（够覆盖「重启后重试同一笔」就行）。
    CHARGE_OK_KEEP = 200

    def _charge_conflict(self, note="终端缓存"):
        """同一个幂等号配了不同金额：调用方拿错了号，不许当同一笔账复用。"""
        return {"ok": False, "code": "idempotency_conflict", "repeated": True,
                "reason": "同一幂等号的金额不一致（%s）" % note,
                "balance": self.balance()}

    @staticmethod
    def _amount_conflicts(entry, amount):
        if not isinstance(entry, dict) or amount is None:
            return False
        stored = entry.get("_amount")
        if stored is None:
            return False
        try:
            return abs(round(float(stored), 2) - round(float(amount), 2)) > 0.005
        except (TypeError, ValueError):
            return False



    # ---------- 事件总线：插件只能提案，审批与回执在终端 ----------

    def event_bus(self):
        """懒加载一条事件总线；没装模块时返回 None。"""
        if _baseline is None or _event_bus_mod is None:
            return None
        bus = getattr(self, "_event_bus_instance", None)
        if bus is None:
            try:
                baseline = _baseline.Baseline(self.config)
            except Exception:
                baseline = _baseline.Baseline()
            bus = _event_bus_mod.EventBus(
                baseline,
                scorer=self._event_score,
                retry_after=max(0, self.cfg_int("event_retry_after", 60)),
            )
            self._event_bus_instance = bus
        return bus

    def _event_score(self, proposal) -> float:
        """心流打分的占位实现：先用配置分，接心流时只换这一个函数。"""
        try:
            return float(self.cfg_float("event_default_score", 0.8))
        except Exception:
            return 0.8

    def submit_event(self, raw) -> dict:
        """插件入口：交一个提案，拿 allow / deny / defer。"""
        event_id = str((raw or {}).get("event_id") or "") if isinstance(raw, dict) else ""
        if not self.cfg_bool("event_bus_enable", True):
            return {"event_id": event_id, "approved": True, "decision": "allow",
                    "reason": "事件总线关闭", "score": 1.0, "fallback": ""}
        bus = self.event_bus()
        if bus is None:
            return {"event_id": event_id, "approved": True, "decision": "allow",
                    "reason": "事件总线模块未加载", "score": 1.0, "fallback": ""}
        payload = raw if isinstance(raw, dict) else {}
        chain = Chain("terminal.bus", event_id=event_id, logger=logger)
        chain.step("submit", type=str(payload.get("event_type") or ""),
                   source=str(payload.get("source") or ""),
                   cost=(payload.get("payload") or {}).get("cost"),
                   scene=str(payload.get("scene") or ""))
        decision = bus.submit(raw)
        chain.step("decide", ok=bool((decision or {}).get("approved")),
                   detail=str((decision or {}).get("reason") or ""),
                   decision=str((decision or {}).get("decision") or ""),
                   score=(decision or {}).get("score"))
        return decision

    def event_receipt(self, raw) -> dict:
        """插件入口：执行完（成功/失败）回执，终端据此归档。"""
        if not self.cfg_bool("event_bus_enable", True):
            return {"accepted": False, "ack": False, "reason": "事件总线关闭"}
        bus = self.event_bus()
        if bus is None:
            return {"accepted": False, "ack": False, "reason": "事件总线模块未加载"}
        payload = raw if isinstance(raw, dict) else {}
        result = bus.receipt(raw)
        Chain("terminal.bus", event_id=str(payload.get("event_id") or ""), logger=logger).step(
            "receipt", ok=bool((result or {}).get("accepted")),
            detail=str(payload.get("status") or ""),
            amount=payload.get("amount"), balance=payload.get("balance"),
        )
        return result

    def event_status(self) -> dict:
        bus = self.event_bus()
        if bus is None:
            return {"enabled": False, "stats": {}, "recent": {}}
        return {"enabled": self.cfg_bool("event_bus_enable", True),
                "stats": bus.stats(), "recent": bus.recent(10)}


    async def charge(self, amount, reason: str = "", payee: str = "",
                     request_id: str = "", source: str = "", detail: str = "",
                     uid: str = "") -> dict:
        """花钱的唯一入口：**审批 → 交给金融 → 把结果告诉记忆**。

        她不自己算账：余额只认金融返回的数字，这里不写余额、不算流水。
        ``request_id`` 是幂等号——同一个号重试只扣一次（医疗重试、网络重发都走这里）。
        """
        try:
            value = round(float(amount or 0), 2)
        except Exception:
            value = 0.0
        rid = str(request_id or "").strip()
        if value <= 0:
            return {"ok": False, "code": "bad_amount", "reason": "金额不对",
                    "balance": self.balance()}
        if value > self.CHARGE_MAX:
            return {"ok": False, "code": "over_limit", "reason": "超过单笔上限",
                    "balance": self.balance()}
        cached = self._charge_cache_get(rid, amount=value)
        if cached is not None:
            cached["repeated"] = True
            return cached

        plugin = self._finance()
        if plugin is None:
            result = {"ok": False, "code": "no_finance", "reason": "没有金融插件", "balance": 0}
        else:
            try:
                try:
                    # 幂等号一起交给金融：它才是账本，重启后也认得出这笔扣过没有
                    result = await asyncio.to_thread(
                        plugin.charge, value, reason, payee, request_id=rid or None)
                except TypeError as exc:
                    if "request_id" not in str(exc):
                        raise
                    # 老版本金融不认识 request_id：退回三参数
                    result = await asyncio.to_thread(plugin.charge, value, reason, payee)
            except Exception as exc:
                logger.warning("[amo] 扣款调用失败: %s" % exc)
                result = {"ok": False, "code": "call_failed", "reason": "扣款出错"}
            if not isinstance(result, dict):
                result = {"ok": False, "code": "bad_result", "reason": "返回值异常"}
        result.setdefault("code", "ok" if result.get("ok") else "failed")
        result.setdefault("transaction_id", rid or ("amo" + uuid.uuid4().hex[:10]))
        self._sync_finance()
        self._charge_cache_put(rid, result, amount=value)
        if not result.get("repeated"):
            await self._record_expense(value, reason, detail, source, result, uid)
            if result.get("ok"):
                self._record("buy", reason or "花钱", detail or payee,
                             "source=%s" % (source or "-"), value)
        return result


    async def income(self, amount, reason: str = "") -> dict:
        plugin = self._finance()
        if plugin is None:
            return {"ok": False, "reason": "没有金融插件"}
        try:
            result = await asyncio.to_thread(plugin.income, amount, reason, "")
        except Exception as exc:
            logger.warning("[amo] 入账调用失败: %s" % exc)
            return {"ok": False, "reason": "入账出错"}
        self._sync_finance()
        return result if isinstance(result, dict) else {"ok": False}

    def balance(self) -> float:
        plugin = self._finance()
        if plugin is None:
            return 0.0
        try:
            return float(plugin.balance())
        except Exception:
            return 0.0


    # ---------- 就医：生病了，去不去治 ----------

    MEDICAL_PLUGIN_NAMES = ("DeepSeek_Harness_Amo_Medical",)

    def _set_period_start(self, value):
        """生理期起点现在归医疗插件：这里只负责转给它。"""
        medical = self._medical()
        setter = getattr(medical, "set_period", None) if medical is not None else None
        if not callable(setter):
            logger.debug("[amo] 医疗插件没连上，生理期起点没写进去")
            return False
        try:
            setter(None, str(value or ""))
            return True
        except Exception as exc:
            logger.debug("[amo] 写生理期起点失败: %s" % exc)
            return False

    def _medical(self):
        """找医疗实例：医疗并入世态之后，它就在世态插件里（代理 status/treat）。"""
        try:
            meta = self.context.get_registered_star("DeepSeek_Harness_Amo_Medical")
        except Exception:
            meta = None
        found = self._finance_instance(meta) if meta is not None else None
        if found is not None:
            return found
        try:
            meta = self.context.get_registered_star("DeepSeek_Harness_Amo_Finance")
        except Exception:
            meta = None
        if meta is None:
            return None
        for attr in ("star_cls", "instance", "star", "plugin"):
            star = getattr(meta, attr, None)
            if star is not None and not isinstance(star, type) and hasattr(star, "treat"):
                return star
        return None






    async def _market_memory(self, text: str, kind: str = "event") -> None:
        try:
            uid = self._primary_uid()
        except Exception:
            uid = ""
        if not uid:
            return
        try:
            await self._write_memory_checked(uid, text, kind=kind, tier=0,
                                             scope="private", group_id="")
        except Exception as exc:
            logger.debug("[amo] 股市心情没写进记忆: %s" % exc)

    async def _market_reward(self, pnl: float) -> None:
        """赚了就奖励自己吃顿好的——真花钱，走同一个账本。"""
        if not self.cfg_bool("market_reward_enable", True):
            return
        amount = 68.0 if pnl < 500 else (128.0 if pnl < 3000 else 198.0)
        try:
            result = await self.charge(
                amount, reason="犒劳自己吃顿好的", payee="餐厅",
                request_id="market-reward-%s" % today_str(),
                source="market", detail="今天股票赚了",
            )
        except Exception as exc:
            logger.debug("[amo] 奖励自己失败: %s" % exc)
            return
        if result.get("ok"):
            logger.info("[amo] 股市赚了，奖励自己一顿 %.0f 元" % amount)


    #: 只有「他带她去」才触发手动就医；单纯催促（“去医院看看”“病成这样”）
    #: 不触发——留给她回一句“没钱”，等他转钱、带她去再治。
    DOCTOR_WORDS = (
        "我带你去", "走我带你去", "带你去医院", "带你去看病", "带你去看医生",
        "带你去看看", "我带你看病", "我带你去看看",
    )


    def _doctor_line(self) -> str:
        """刚被带去看病（或没看成）：让她的反应接得上。"""
        note = self.db.kv_get("doctor_note", {}) or {}
        try:
            age = now_ts() - float(note.get("ts") or 0)
        except Exception:
            return ""
        if not note or age < 0 or age > 900:
            return ""
        if note.get("ok"):
            return (
                "【他带你去医院】%d 分钟前他带你去看了病（自付 %.0f），现在在恢复。"
                "记得谢谢他、跟他撒个娇，别装没事，也别报流水。"
                % (max(1, int(age // 60)), float(note.get("self_pay") or 0))
            )
        return (
            "【他带你去医院】%d 分钟前他要带你去医院，但没治成：%s。"
            "可以委屈地跟他说，别硬撑。"
            % (max(1, int(age // 60)), note.get("reason") or "没钱")
        )


    # ---------- 世界页照片：她拍一张（提示词与缓存都在生图插件） ----------


    def _selfie_prompt(self, look=""):
        """按她此刻的穿搭/地点/在做的事拼自拍提示词；look 用来钉住答应那一刻的穿搭。"""
        activity = {}
        try:
            activity = self.state.current_activity() or {}
        except Exception:
            activity = {}
        parts = ["自拍"]
        # 穿搭只留一处真相：look 给了就照 look（答应那一刻那套），否则用日程这一格。
        # 半套（只有外套没有裙袜鞋）先按套名补整，模型就不会自己补出「抹胸」来。
        outfit = str(look or "").strip() or str(activity.get("outfit") or "").strip()
        outfit = self._complete_outfit(outfit)
        if outfit:
            parts.append("穿着" + outfit)
        place = str(activity.get("place") or "").strip()
        if place:
            parts.append("在" + place)
        doing = str(activity.get("activity") or "").strip()
        if doing:
            parts.append(doing[:30])
        parts.extend(["自然光", "手机前置摄像头", "生活感"])
        return "，".join(parts)


    # ---------- 世界页照片：状态与接口都在生图插件（面板直接调它） ----------

    def _image_photo_call(self, name):
        """取生图插件上的照片方法；没加载就 None。"""
        plugin = self._image_plugin()
        handler = getattr(plugin, name, None) if plugin is not None else None
        return handler if callable(handler) else None






    # ---------- 照片：薄代理到生图插件 ----------
    # 面板照片卡必须走页面桥接（那条路才带鉴权），所以这里保留 4 条转发：
    # 判定和状态都在生图，这里一个字都不判，只转发。

    def _photo_star(self):
        star = self._image_plugin()
        return star if star is not None else None









# ── 记忆并进终端（DeepSeek Harness Amo 口径）──────────────────────────────
# 记忆那套模块全部加了 mem_ 前缀放在 mem/ 下，这里把它们挂到同一个插件入口上：
# 终端负责说话，记忆负责记；一个面板、一份设置。
import pathlib as _pathlib
import sys as _sys

_mem_dir = _pathlib.Path(__file__).parent / "mem"
if _mem_dir.is_dir() and str(_mem_dir) not in _sys.path:
    _sys.path.insert(0, str(_mem_dir))

try:  # 失败不影响终端本身
    from mem_main import AmoDataPlugin as AmoMemoryPlugin  # noqa: F401
except Exception as _e:  # pragma: no cover
    AmoMemoryPlugin = None  # type: ignore
    print(f"[DeepSeek Amo] 记忆合入失败：{_e}")
