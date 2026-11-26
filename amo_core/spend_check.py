# -*- coding: utf-8 -*-
"""报价校验：她写 SPEND 时，金额得落在合理区间里。

不囤商品、不查接口——只按品类给一个宽区间，防止「一杯奶茶 3800」这种事。
区间是价格带的上下限（元），中间值是兜底估值。
"""

from __future__ import annotations

RANGES = [
    ("饮品", ("奶茶", "咖啡", "可乐", "矿泉水", "果汁", "豆浆", "啤酒", "酒"), 3, 200),
    ("小吃", ("薯片", "饼干", "巧克力", "辣条", "坚果", "冰淇淋", "果冻", "包子", "煎饼"), 3, 120),
    ("一餐", ("饭", "面", "粉", "火锅", "烧烤", "外卖", "快餐", "套餐", "食堂", "聚餐"), 8, 600),
    ("生鲜", ("菜", "肉", "鸡蛋", "水果", "苹果", "香蕉", "车厘子", "草莓", "榴莲"), 3, 500),
    ("日用", ("纸", "洗衣液", "洗发水", "牙膏", "沐浴露", "垃圾袋", "拖把", "毛巾"), 5, 400),
    ("用药", ("药", "感冒", "退烧", "创可贴", "布洛芬", "维生素"), 5, 800),
    ("衣服", ("裙", "衬衫", "卫衣", "裤", "外套", "毛衣", "大衣", "T恤", "袜", "鞋"), 30, 8000),
    ("首饰", ("项链", "手镯", "耳钉", "戒指", "发圈"), 20, 20000),
    ("美妆", ("口红", "面膜", "香水", "粉底", "防晒"), 20, 3000),
    ("数码", ("手机", "电脑", "键盘", "鼠标", "耳机", "显示器", "相机", "平板"), 50, 30000),
    ("家电", ("电饭煲", "吹风机", "冰箱", "洗衣机", "空调", "电视"), 80, 20000),
    ("出行", ("打车", "高铁", "机票", "地铁", "停车", "加油", "代驾"), 2, 5000),
    ("住宿", ("酒店", "民宿", "房费"), 80, 5000),
    ("房租", ("房租", "物业", "水电", "燃气", "宽带"), 20, 20000),
]

DEFAULT = ("其他", 1, 20000)


def _band(desc: str):
    text = str(desc or "")
    for name, words, lo, hi in RANGES:
        if any(w in text for w in words):
            return name, lo, hi
    return DEFAULT


def check(desc: str, amount: float) -> dict:
    """返回 {ok, band, lo, hi, mid, reason}。"""
    name, lo, hi = _band(desc)
    try:
        value = float(amount or 0)
    except Exception:
        value = 0.0
    mid = round((lo + hi * 3) / 4.0, 2)      # 偏下四分位，别报太高
    if value <= 0:
        return {"ok": False, "band": name, "lo": lo, "hi": hi, "mid": mid,
                "reason": "金额不对"}
    if value < lo:
        return {"ok": False, "band": name, "lo": lo, "hi": hi, "mid": mid,
                "reason": "%s 报 %.2f 太低（这一类一般 %d~%d）" % (name, value, lo, hi)}
    if value > hi:
        return {"ok": False, "band": name, "lo": lo, "hi": hi, "mid": mid,
                "reason": "%s 报 %.2f 太高（这一类一般 %d~%d）" % (name, value, lo, hi)}
    return {"ok": True, "band": name, "lo": lo, "hi": hi, "mid": mid, "reason": ""}
