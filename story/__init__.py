# -*- coding: utf-8 -*-
"""沈家资料库：族谱、家训、产业、宅邸班组。

她是「家里的事自己心里有数」，但几十号人不能塞人格（每轮都要付 token）。
这里当库存：context.py 只在消息提到家人时按关键词查一次，只取命中的那几行。
改名字、加人、调职务，只改 lineage.py。
"""

try:
    from .lineage import (ASSETS, FAMILY, MOTTO, STAFF, find, overview,
                          staff_find, staff_overview)
except Exception:  # 按文件路径加载时的兜底
    from lineage import (ASSETS, FAMILY, MOTTO, STAFF, find, overview,
                         staff_find, staff_overview)

__all__ = ["FAMILY", "STAFF", "MOTTO", "ASSETS",
           "find", "overview", "staff_find", "staff_overview"]
