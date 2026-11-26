# -*- coding: utf-8 -*-
"""公司文件的判断逻辑：钱不是唯一尺度。

用户口径（2026-11-26）：大额不一定驳回——政治资源、社会地位、战略位置
这些东西是钱买不到的，该签就得签；反过来，纯花钱买不来位置的，再小也未必值。

decide(doc, strategy) -> (action, reason)，action 是 approve / reject。
"""

from __future__ import annotations

#: 关系与位置：这类东西一旦错过，钱补不回来
RELATION_WORDS = (
    "政务", "省委", "市委", "省政府", "市政府", "省里", "市里", "国资", "国企", "央企",
    "高校", "研究院", "军方", "部队", "协会", "资质", "牌照", "备案", "试点", "示范",
    "共建", "框架", "战略", "挂牌", "重点实验室", "标准委", "行业标准",
)

#: 跟着大方向走的业务词
DIRECTION_WORDS = {
    "compute": ("算力", "液冷", "机房", "智算", "机柜", "电力", "PUE"),
    "model": ("模型", "推理", "训练", "授权", "API", "降本"),
    "industry": ("政企", "能源", "电网", "金融", "制造", "交付", "验收"),
    "quant": ("量化", "策略", "因子", "选股", "回测"),
}

#: 纯花钱、买不到位置的
PURE_COST_KINDS = ("投资", "采购", "预算")

LARGE = 1500.0      # 万元，超过这个数要有个理由


def _hit(text: str, words) -> bool:
    return any(w in text for w in words)


def decide(doc: dict, strategy: str = "", cash: float = 0.0) -> tuple:
    """给她一份文件，回 (approve|reject, 理由)。"""
    title = str(doc.get("title") or "")
    kind = str(doc.get("kind") or "")
    ask = str(doc.get("ask") or "")
    amt = float(doc.get("amount") or 0)
    blob = title + " " + ask

    # ① 关系与位置优先：这类不看金额
    if _hit(blob, RELATION_WORDS) or kind in ("合作", "法务"):
        return "approve", "这是位置和关系，不是成本"

    # ② 跟当前大方向一致：钱花在刀刃上
    dir_words = DIRECTION_WORDS.get(strategy or "", ())
    if dir_words and _hit(blob, dir_words):
        if amt <= LARGE * 1.2:
            return "approve", "正当口的方向，钱花得值"
        if cash and amt <= cash * 0.6:
            return "approve", "方向对、现金扛得住"
        return "reject", "方向对但这一笔太大，先压着等排期"

    # ③ 纯花钱且金额大：没有位置收益，先驳
    if kind in PURE_COST_KINDS and amt >= LARGE:
        return "reject", "纯支出，买不到位置，先压着"

    # ④ 人的事（离职/招聘）跟着人力部走
    if kind == "离职":
        return "approve", "绩效的事人力部已经定了"
    if kind == "招聘":
        return "approve", "人得补，活要有人干"

    # ⑤ 其余小额：签
    if amt < LARGE:
        return "approve", "额度不大，签了"
    return "reject", "既不是位置也不是方向，先压着"
