# -*- coding: utf-8 -*-
"""回复出口的「鱼八股 / AI 腔」清理（本地规则版，零 LLM 依赖）。

来路：机制抄自 SIiOC/astrbot-plugin-humanizer 的 qc 规则，但规则表换成了
晓沫的实战语料（2026-11-21 她贴的那三十来句），那个仓库里的通用 AI 腔
（客服腔 / 升华句 / 要点列举 / 双破折号）也留了几条高置信的。

做法：按句读把回复切成 clause，命中的整条 clause 删掉，剩下的拼回去。
   · 只删不造字，绝不改写正文；
   · 整条只有一句套话（<= SHORT_DROP_CHARS 字）→ 判定 dropped，换成
     一句「嗯。」这类真人短反应，而不是把「我不拦。」发出去；
   · 剩得下的部分太短（< 原文 35%）而原文并不短 → 回落原文，宁可不拦也不吞话；
   · 纯函数，不 import astrbot，方便单测。

为什么不在这里调模型：这一段在发送链路上，多一次 LLM 调用就是多 1~3 秒
延迟和一次失败点。硬删足够对付「固定的那几十句」，真要改写得另开异步工序。
"""

from __future__ import annotations

import random
import re
from typing import Iterable

# ---------------------------------------------------------------------------
# 分句：句读切分，分隔符跟着前一个 clause 走，拼回去是原文
# ---------------------------------------------------------------------------
_SEP = "，,。．！!？?…；;：:\n"
_CLAUSE_RE = re.compile(r"[^" + re.escape(_SEP) + r"]+[" + re.escape(_SEP) + r"]*")

# 只由这些字符构成的 clause 视为空壳
_BLANK_RE = re.compile(r"^[\s" + re.escape(_SEP) + r"]*$")

# 单条回复短到这个字数、且整条都是套话 → 判定 dropped
SHORT_DROP_CHARS = 24

# 命中率保护：删完不足原文字符数的这个比例，就整条不拦
_MIN_KEEP_RATIO = 0.35

# 整条都是套话时换上的真人短反应（她自己也这么说）
FALLBACK_LINES = ("嗯。", "……", "哦。", "这样啊。", "好。", "知道啦。")

# ---------------------------------------------------------------------------
# 规则表：(标签, 正则)
#   · 按 clause 匹配，匹配前会去掉 clause 尾部的句读标点
#   · 正则一律 re.search，自带 ^ 的按去标点后的 clause 从头匹配
# ---------------------------------------------------------------------------
_RULES: list[tuple[str, re.Pattern]] = [
    # ---- ① 评点他「这句话」本身：她最典型的元话语 ----
    ("评他这句", re.compile(r"(这|那)(句|话)[^。！？\n]{0,8}(稳|重|轻|平|漂亮|不接|接得|收下|留着|记着|记下|认)")),
    ("评他这句", re.compile(r"(这|那)(句|话)(我|咱)?(不|没)?(接|认|留|收|记|掂)")),
    ("评他这句", re.compile(r"没接你(那|这)句")),
    ("评他这句", re.compile(r"(什么|啥)心思都写着[^。！？\n]{0,8}上")),
    ("评他这句", re.compile(r"(这话|这句)[^。！？\n]{0,6}(是|是不是)(ta|他|她)?告诉你的")),
    # ---- ② 比大小式裁定：比之前的都重 / 比刚才轻 ----
    ("比大小", re.compile(r"比(之前|刚才|上次|上一句|前面|别的|谁|谁都)[^。！？\n]{0,5}(都)?(重|轻|稳|强|沉|平|狠|硬|响)")),
    ("比大小", re.compile(r"^[^。！？\n]{0,10}比[^。！？\n]{1,10}(沉|重|轻|稳|平)")),
    # ---- ③ 认 / 记 / 收 / 留 这类裁定短句 ----
    ("认了", re.compile(r"^(行|好|嗯|成|可以)[，,]?\s*我(认|服)(了|下来|这个|你|就是)?")),
    ("认了", re.compile(r"^我?认得?(你|这个|下来|实|死|就是认了)")),
    ("认了", re.compile(r"^我?(记|收)(下来|下|着|住)?了$")),
    ("认了", re.compile(r"^(这个|这账|这笔)[^。！？\n]{0,4}我?(认|记)")),
    ("认了", re.compile(r"^(我)?认(下来|了|这个)$")),
    # ---- ④ 不拦 / 不催 ----
    ("不拦", re.compile(r"我(不拦|不催|不拦你|不催你)")),
    ("不拦", re.compile(r"^(你|想)[^。！？\n]{0,4}就[^。！？\n]{0,4}[，,]?我(不拦|不催|不管)")),
    # ---- ⑤ 守 / 跟 / 睡 这类武侠台词 ----
    ("武侠腔", re.compile(r"^(睡吧?|先睡|你睡)[，,]?\s*我(守着|陪着你)")),
    ("武侠腔", re.compile(r"^你去[，,]?\s*我?跟(着)?(你)?")),
    ("武侠腔", re.compile(r"^我守着(你|呢)?$")),
    ("武侠腔", re.compile(r"(说的比谁都响|收不回去)")),
    # ---- ⑥ 掂量 / 静观 ----
    ("掂量", re.compile(r"(你自己|你|自己)掂量")),
    ("掂量", re.compile(r"(问别人还是问自己|你自己想明白)")),
    # ---- ⑦ 情绪旁白模板：声音没抖，但比刚才稳 ----
    ("旁白", re.compile(r"(声音|语气|手上|指尖)[^。！？\n]{0,6}(没抖|一僵|一顿)[，,][^。！？\n]{0,10}(比|稳|轻|重|平)")),
    # ---- ⑧ 通用 AI 腔（抄自 humanizer 的高置信几条）----
    ("客服腔", re.compile(r"希望(这|以上|这些)?(对你|对你们)?(有所|有)?帮助")),
    ("客服腔", re.compile(r"如果还有(任何)?问题[^。！？\n]{0,8}(随时|尽管)(问|找|联系)")),
    ("客服腔", re.compile(r"有问题(随时|可以随时)(问|找|联系)我")),
    ("客服腔", re.compile(r"^好问题[！!。]|^你说得太对(了)?|^问得(好|不错)[！!。]")),
    ("说教", re.compile(r"^(记住|请注意|听好了|你要知道)[，,：:]")),
    ("说教", re.compile(r"^(总之|总的来说|总而言之|综上所述|综上)[，,。！？]")),
    ("说教", re.compile(r"^首先[，,][^。！？]{0,40}(其次|再者|最后)[，,]")),
    ("升华", re.compile(r"这(不仅|不只是)[^。！？]{0,20}(更是|也是)")),
    ("升华", re.compile(r"让我们(一起)?(共同)?(期待|迈向|迎接)[^。！？]{0,15}(未来|明天)")),
    ("免责", re.compile(r"(研究|科学)(表明|显示)|专家(表示|指出)")),
    ("自称AI", re.compile(r"作为(一个)?(AI|人工智能|语言模型|助手)|我(的)?训练(数据|语料)")),
    # ---- ⑨ 点评人：给别人（含别的群友、别的机器人）下评语 ----
    # 2026-11-21 例：「光说不添乱，你这条鱼还算稳」——像裁判打分，不像人说话。
    # 「挺靠谱 / 挺老实」是真人也会说的正常话，只拦「还算稳」这种打分口气
    ("点评人", re.compile(r"(还算|算是)(稳|靠谱|老实|听话|安分|安生)")),
    ("点评人", re.compile(r"(这条|这个|这头)?(鱼|人|家伙)[^。！？\n]{0,4}(还算|还挺|挺)(稳|乖|靠谱)")),
    ("点评人", re.compile(r"不(添乱|惹事|闹事|给人添麻烦)")),
    ("点评人", re.compile(r"(表现|态度|这波)[^。！？\n]{0,4}(不错|还行|可以|挺好|尚可)")),
    ("点评人", re.compile(r"(合格|及格|过关)了?$")),
    # ---- ⑩ 念设定 / 自我说明这轮怎么回（2026-11-21 19:43 群里那次）----
    ("念设定", re.compile(r"一条(就)?一句")),
    ("念设定", re.compile(r"^(我|也)?(就|先)?不(主动)?(报|说)(自己)?(的)?(日程|行程|安排|活动|地点)(?!了)")),
    ("念设定", re.compile(r"接(这|那)(一)?条(就|就行|就够|就够了)?")),
    ("念设定", re.compile(r"(这轮|这次|眼下)?只(回|答)(这|那|眼下这)(一)?(条|句)")),
    ("念设定", re.compile(r"^(按|照)(规矩|规则|设定|人设|要求)(来|走|办)?")),
    ("念设定", re.compile(r"(收到|明白|懂了)(指令|规则|设定|要求)")),
    ("念设定", re.compile(r"(群聊|聊天)(的)?(规矩|规则|设定)")),
    ("念设定", re.compile(r"^(我)?(的)?(设定|人设)(是|就是)")),
]

# 整条级规则：命中就判定「整条都是套话」，不再逐 clause 判断
_WHOLE_RULES: list[tuple[str, re.Pattern]] = [
    ("武侠腔", re.compile(r"^(睡吧?|先睡|你睡)[，,]?我(守着|陪着你)$")),
    ("武侠腔", re.compile(r"^你去[，,]?我跟(着)?(你)?$")),
    ("认了", re.compile(r"^(行|好|嗯)[，,]?我(认|服)|^(我)?认(下来|了|这个)$")),
    ("不拦", re.compile(r"^我(不拦|不催)(你)?$")),
    ("掂量", re.compile(r"^(你自己|你|自己)掂量$")),
    ("评他这句", re.compile(r"^(这|那)(句|话)[^。！？\n]{0,8}(稳|重|轻|平|漂亮|接得|不接)$")),
]


def _core(clause: str) -> str:
    """去掉 clause 尾部的句读标点与空白，供 ^...$ 规则匹配。"""
    return clause.strip().strip(_SEP + " \t")


def _compile_extra(extra: Iterable[str]) -> list[tuple[str, re.Pattern]]:
    """额外规则：'正则' 或 '关键词'，用于面板/文件里临时加词。"""
    out: list[tuple[str, re.Pattern]] = []
    for raw in extra or ():
        item = str(raw or "").strip()
        if not item:
            continue
        try:
            pat = item[3:].strip() if item.startswith("re:") else re.escape(item)
            out.append(("自定义", re.compile(pat)))
        except re.error:
            continue
    return out


def _hits(core: str, rules: list[tuple[str, re.Pattern]]) -> list[str]:
    labels: list[str] = []
    for label, pat in rules:
        try:
            if pat.search(core):
                labels.append(label)
        except re.error:
            continue
    return labels


def scrub_reply_detailed(
    text: str,
    extra: Iterable[str] = (),
) -> tuple[str, list[str], bool]:
    """清理一条回复。

    返回 ``(新文本, 命中标签列表, dropped)``：
      · 没命中 → 原文，``[]``，False；
      · 命中且剩得下话 → 删掉命中的 clause，其余原样拼回；
      · 整条都是套话且不长 → 换成 FALLBACK_LINES 里一句，dropped=True；
      · 删得只剩边角（< 原文 35%）而已并不短 → 回落原文（宁可不拦，不吞话）。
    """
    raw = str(text or "")
    if not raw.strip():
        return raw, [], False

    rules = _RULES + _compile_extra(extra)
    clauses = _CLAUSE_RE.findall(raw)
    if not clauses:
        return raw, [], False

    # 先看整条级：一句套话 = 这句话本身没有内容
    whole_core = re.sub(r"[\s" + re.escape(_SEP) + r"]+", "", raw)
    whole_hits = _hits(whole_core, _WHOLE_RULES)
    if whole_hits:
        if len(whole_core) <= SHORT_DROP_CHARS:
            return random.choice(FALLBACK_LINES), whole_hits, True
        return raw, whole_hits, False

    kept: list[str] = []
    hit_labels: list[str] = []
    for clause in clauses:
        if _BLANK_RE.match(clause):
            kept.append(clause)
            continue
        found = _hits(_core(clause), rules)
        if found:
            hit_labels.extend(found)
            continue
        kept.append(clause)

    if not hit_labels:
        return raw, [], False

    cleaned = "".join(kept)
    # 连续标点收一收（删句后会留下「，。」这种）
    cleaned = re.sub(r"[，,、]{2,}", "，", cleaned)
    cleaned = re.sub(r"，\s*([。！？!?])", r"\1", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    body = re.sub(r"\s", "", cleaned)
    source = re.sub(r"\s", "", raw)
    if not body:
        # 整条都是被删掉的 clause：短就当这句本来就是纯套话
        if len(source) <= SHORT_DROP_CHARS:
            return random.choice(FALLBACK_LINES), hit_labels, True
        return raw, hit_labels, False
    # 删完只剩半截（「声音没抖，」这种尾巴挂逗号的残句）：
    # 太短（<6 字）就整条换掉；还有正文的，去逗号补句号留着
    if cleaned.endswith(("，", ",", "、", "；", ";")):
        cleaned = cleaned.rstrip("，,、；; ")
        if len(re.sub(r"\s", "", cleaned)) < 6:
            return random.choice(FALLBACK_LINES), hit_labels, True
        cleaned += "。"
        body = re.sub(r"\s", "", cleaned)
    if len(body) < len(source) * _MIN_KEEP_RATIO:
        return raw, hit_labels, False

    return cleaned, hit_labels, False


def scrub_reply(text: str, extra: Iterable[str] = ()) -> tuple[str, list[str]]:
    """两元组版本，供不想处理 dropped 的调用方用（丢弃时返回兜底短句）。"""
    cleaned, hits, _dropped = scrub_reply_detailed(text, extra)
    return cleaned, hits


_FINAL_DOT_RE = re.compile(r"[。．]+\s*$")


def drop_final_dot(text: str, keep_prob: float = 0.15) -> str:
    """去掉句末的「。」——真人 QQ 聊天很少在句尾打句号。

    保留 keep_prob 的比例不动（生气、认真、说正经事时她也会打句号，
    全去掉就成了另一种整齐）。问号、感叹号、省略号一律不碰。
    """
    raw = str(text or "")
    s = raw.strip()
    if not s or not _FINAL_DOT_RE.search(s):
        return raw
    if random.random() < keep_prob:
        return raw
    return _FINAL_DOT_RE.sub("", s)


def polish_generic(text: str) -> str:
    """与八股无关的机械痕迹：多感叹号、双破折号断句、多余空格。

    保守：只在明显滥用时动手，且绝不把文本清空。
    """
    raw = str(text or "")
    if not raw.strip():
        return raw
    out = re.sub(r"[！!]{2,}", "！", raw)
    # 一条消息里出现「——…——」的插入式用法，收敛成逗号
    out = re.sub(r"——(?=[^。！？\n]{1,60}——)", "，", out)
    out = re.sub(r"[ \t]{2,}", " ", out)
    return out if out.strip() else raw


__all__ = ["scrub_reply", "scrub_reply_detailed", "polish_generic",
           "drop_final_dot", "FALLBACK_LINES"]
