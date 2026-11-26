# -*- coding: utf-8 -*-
"""扩展工具（2026-11-26 用 AST 精确剥出）：族谱、经营台、银行。

main.py 已经 4600+ 行，新工具别再往里塞；以后都加到这里的 ExtToolsMixin。
"""

from __future__ import annotations

import os

from astrbot.api import logger
from astrbot.api.event import filter


class ExtToolsMixin:
    def _net_quote(self):
        """网络报价函数（Market/net_price.py），按包内导入，失败再按文件路径兜底。"""
        try:
            from .net_price import quote as _q  # type: ignore
            return _q
        except Exception:
            pass
        try:
            import os as _os
            import importlib.util as _ilu
            path = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                                 "net_price.py")
            cands = [path,
                     _os.path.join(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                                   "DeepSeek_Harness_Amo_Market", "net_price.py")]
            for p in cands:
                if not _os.path.exists(p):
                    continue
                spec = _ilu.spec_from_file_location("amo_net_price", p)
                mod = _ilu.module_from_spec(spec)
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
                return mod.quote
        except Exception as exc:
            logger.debug("[amo] 网络报价加载失败: %s" % exc)
        return None
    def _bank_mod(self):
        """银行数据层（Finance/bank.py）。"""
        try:
            import importlib.util as _ilu
            here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(here, "DeepSeek_Harness_Amo_Finance", "bank.py")
            spec = _ilu.spec_from_file_location("amo_bank_mod", path)
            mod = _ilu.module_from_spec(spec)
            spec.loader.exec_module(mod)  # type: ignore[union-attr]
            return mod
        except Exception as exc:
            logger.debug("[amo] 银行模块加载失败: %s" % exc)
            return None
    @filter.llm_tool(name="amo_bank")
    async def amo_bank(self, event, action: str = "profile", amount: float = 0,
                       months: int = 12, kind: str = "流动资金贷款") -> str:
        """看自家的银行（贵州发展银行）：架构、利率、产品，或者试算一笔企业贷款。

        妈妈江馥宁是这家银行的行长，集团是它的前三大对公客户。

        Args:
            action(string): profile 看银行 / products 看产品 / rates 看利率 /
                            credit 试算企业贷 / buy 买股票 / sell 卖股票 / stocks 看持仓
            amount(number): 贷款金额（万元），credit 时填
            months(number): 期限（月），credit 时填
            kind(string): 产品名：流动资金贷款 / 固定资产贷款 / 科创信用贷 / 供应链融资 / 银行承兑汇票 / 履约保函 / 并购贷款；
                         买/卖股票时填股票名（茅台、宁德、中芯、比亚迪、招行、讯飞）
        """
        mod = self._bank_mod()
        if mod is None:
            return "银行那边的数据读不到，等会儿再说。"
        action = str(action or "profile").strip().lower()
        try:
            if action == "rates":
                r = mod.rates()
                keys = ["LPR1Y", "LPR5Y", "企业流贷", "科创信用贷", "存款一年", "个人房贷", "消费贷"]
                return "利率（年化）：" + "；".join("%s %.2f%%" % (k, float(r.get(k, 0))) for k in keys if k in r)
            if action == "products":
                rows = mod.products()
                head = rows[:6]
                return "产品：\n" + "\n".join(
                    "· %s（%s，%s，%s）" % (x["name"], x["limit"], x["term"], x["rate"]) for x in head)
            if action in ("buy", "sell", "stocks"):
                fin = self._finance() if hasattr(self, "_finance") else None
                if fin is None:
                    return "银行没连上，动不了股票。"
                if action == "stocks":
                    book = fin._load_book()
                    rows = fin._stocks_data(book)
                    held = [r for r in rows if int(r.get("shares") or 0) > 0]
                    if not held:
                        return "现在没有持仓。"
                    return "持仓：" + "；".join(
                        "%s %d 股（市值 %.0f）" % (r["name"], r["shares"], r["value"]) for r in held)
                code = str(kind or target or "").strip()
                if not code:
                    return "要买卖哪只？茅台、宁德、中芯、比亚迪、招行、讯飞。"
                shares = int(float(amount or 100)) if amount else 100
                res = fin._trade(code, shares, "buy" if action == "buy" else "sell")
                return str(res.get("msg") or ("办好了" if res.get("ok") else "没成"))

            if action == "credit":
                res = mod.credit_apply(float(amount or 0), int(months or 12), kind)
                plan = res.get("plan") or {}
                lines = ["%s：%s %.0f 万，%s 个月，年化 %.2f%%。" % (
                    res.get("product"), res.get("verdict"), float(res.get("amount") or 0),
                    int(plan.get("months") or 0), float(res.get("rate") or 0))]
                lines.append("月供 %.2f 万（约 %.0f 元），总利息 %.2f 万。" % (
                    float(plan.get("monthly") or 0),
                    float(plan.get("monthly") or 0) * 10000.0,
                    float(plan.get("interest") or 0)))
                for why in (res.get("reasons") or []):
                    lines.append("· " + str(why))
                return "\n".join(lines)
            b = mod.profile()
            return ("%s（%s，%d 年）：资产 %.0f 亿，存款 %.0f 亿，贷款 %.0f 亿，不良率 %.2f%%，"
                    "网点 %d 个，%d 人。\n董事长 %s，行长 %s。\n集团授信 %.0f 万，已用 %.0f 万。" % (
                        b["name"], b["type"], int(b["since"]), float(b["assets"]),
                        float(b["deposits"]), float(b["loans"]), float(b["npl"]),
                        int(b["branches"]), int(b["staff"]), b["chair"], b["president"],
                        float(mod.GROUP_CREDIT["line"]), float(mod.GROUP_CREDIT["used"])))
        except Exception as exc:
            logger.debug("[amo] amo_bank 失败: %s" % exc)
            return "这一下没查成，等会儿再说。"
    @filter.llm_tool(name="amo_office")
    async def amo_office(self, event, action: str = "brief", target: str = "", note: str = "") -> str:
        """处理公司的事：看今天要批什么、批或驳文件、定大方向、绩效 D 清退、补招、看幻方。

        你只管三件事：批红、定大方向、定人事政策（发奖金还是降本增效）。
        开除和招聘由人力部按规矩办，不用你一个个点；批了就是真扣钱，驳了就留痕。
        每天至少看一次 brief。

        Args:
            action(string): brief 看今天 / approve 批 / reject 驳 / direction 定方向 /
                            policy 定人事政策（target 填 bonus 或 cut）/ quant 看幻方
            target(string): 文件编号或标题、方向名（算力先行/模型降本/行业深耕/量化反哺）、
                            bonus（发奖金）或 cut（降本增效）；看的时候可以留空
            note(string): 备注或理由，可以留空
        """
        plugin = self._market_plugin()
        if plugin is None or not hasattr(plugin, "office"):
            return "经营台没连上（世态插件不在），这会儿批不了。"
        try:
            res = plugin.office(action, target, note) or {}
        except Exception as exc:
            logger.debug("[amo] office 调用失败: %s" % exc)
            return "这一下没办成，等会儿再说。"
        if not res.get("ok", True) and res.get("msg"):
            return str(res.get("msg"))

        if action in ("brief", "today", ""):
            b = res.get("brief") or {}
            lines = ["今天要你拍板的："]
            for d in (b.get("docs") or []):
                lines.append("· [%s] %s（%s，%.0f 万，限 %d 天）"
                             % (d.get("id"), d.get("title"), d.get("from"),
                                float(d.get("amount") or 0), int(d.get("days") or 3)))
            gaps = b.get("gaps") or []
            if gaps:
                lines.append("待补的位子 %d 个：%s" % (len(gaps), "、".join(g.get("post", "") for g in gaps[:4])))
            st = b.get("strategy")
            lines.append("大方向：" + (st["name"] + "——" + st["line"] if st else "还没定，先定一个"))
            pol = b.get("policy")
            lines.append("人事政策：" + (pol["name"] + "——" + pol["line"] if pol else "还没定：发奖金（bonus）还是降本增效（cut）"))
            hr = b.get("hr") or {}
            if hr.get("summary"):
                lines.append("人力部今天：" + str(hr["summary"]))
            lines.append(b.get("line") or "")
            return "\n".join([x for x in lines if x])

        if action == "quant":
            sm = res.get("summary") or {}
            pnl = res.get("pnl") or {}
            return ("幻方这边：规模 %.0f 亿（自营 %.0f／资管 %.0f），%d 人，今年 %.1f%%。\n"
                    "今天组合 %+.2f%%，盈亏 %.0f 万；给集团用算力 %s。"
                    % (float(sm.get("aum") or 0), float(sm.get("aum_own") or 0),
                       float(sm.get("aum_fund") or 0), int(sm.get("staff") or 0),
                       float(sm.get("ytd") or 0), float(pnl.get("ret_pct") or 0),
                       float(pnl.get("pnl") or 0), sm.get("share_to_group") or "—"))

        if action in ("fire_d",):
            return str(res.get("msg") or "清退完了")
        if action in ("fill_gap", "fill"):
            return str(res.get("msg") or "补上了")
        return str(res.get("msg") or "办好了")
    @filter.llm_tool(name="family_view")
    async def family_view(self, event, name: str = "", relation: str = "", gen: int = 0) -> str:
        """查沈氏族谱。你是沈家第三代，族里四代人都在谱上。

        别人问起你家里的谁、或者你自己要确认某个亲戚的职务、生日、八字，就来查谱。
        不要凭印象编名字和关系——谱上没有的，就说没这个人。

        Args:
            name(string): 姓名，或名字里的字（如 斯羽、砚）；留空表示不限。
            relation(string): 关系称谓，如 爷爷/姑姑/表姐/舅舅/外甥女；留空表示不限。
            gen(number): 第几代，1=振字辈 2=卫国辈 3=你这一辈 4=第四代；0 表示不限。
        """
        import json as _json
        try:
            raw = self.db.kv_get("family_tree", None)
            tree = _json.loads(raw) if isinstance(raw, str) else (raw or {})
        except Exception:
            tree = {}
        members = tree.get("members") or []
        if not members:
            return "族谱没读到（库里的 family_tree 是空的）。"
        name = str(name or "").strip()
        relation = str(relation or "").strip()
        try:
            gen = int(gen or 0)
        except Exception:
            gen = 0
        hits = []
        for m in members:
            if gen and int(m.get("gen") or 0) != gen:
                continue
            blob = "%s %s %s" % (m.get("name", ""), m.get("relation", ""), m.get("post", ""))
            if name and name not in blob:
                continue
            if relation and relation not in blob:
                continue
            hits.append(m)
        if not hits:
            return "谱上没有这个（%s）。换个说法，或者说姓名里的一个字。" % (" ".join(x for x in (name, relation) if x) or "空查询")
        if not (name or relation or gen):
            out = ["沈氏族谱（%d 人）：" % len(members)]
            for g in tree.get("generations") or []:
                who = [m["name"] for m in members if m.get("gen") == g.get("gen")]
                if who:
                    out.append("%s：%s" % (g.get("label", "第%s代" % g.get("gen")), "、".join(who)))
            if tree.get("motto"):
                out.append("家训：%s" % tree["motto"])
            if tree.get("assets"):
                a = tree["assets"]
                out.append("家里产业：%s（%s）" % ((a.get("产业") or {}).get("name", ""), (a.get("产业") or {}).get("scope", "")))
            out.append("要查哪个人的职务、生日、八字，说名字或称谓。")
            return "\n".join(out)
        lines = []
        for m in hits[:8]:
            lines.append("%s（%s·%s，第%s代）｜%s 生｜八字 %s｜%s" % (
                m.get("name", ""), m.get("relation", ""), m.get("post", ""),
                m.get("gen", ""), m.get("birth", ""), m.get("bazi", ""), m.get("note", "")))
        if len(hits) > 8:
            lines.append("（还有 %d 人，说细一点我再找）" % (len(hits) - 8))
        return "\n".join(lines)
