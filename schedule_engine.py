# -*- coding: utf-8 -*-
"""日程主干生成引擎。

设计目标（对应 5.1.0 重构）：

1. 每天只生成一次“主干”：24 个整点槽位，每个槽位都有
   start/end/activity/place/zone/category/transit/vehicle/mood。
2. 主干先由确定性规则保证物理连贯（不能瞬移、不能情绪突变），
   再让大模型只改写“这一小时在做什么”，不允许改时间、地点和类别。
3. 三级 10 分钟细分彻底废弃；点击二级卡片时，由 main.py 调用
   generate_diary() 实时生成这一小时的第一人称小日记。
4. 休息日天气好时优先读取 scenic_spots.json 里的贵阳/贵州景区；
   周末开车出行固定绑定角色资产（黑色奔驰 C 级），并带堵车/找车位细节。
5. 突发事件：
   - 休息日：老板临时叫去公司改 Bug / 朋友临时叫出去聚餐；
   - 工作日：被公司外派到插件内置的随机省份。
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING
if TYPE_CHECKING:  # 只给类型检查看：包内相对导入
    from .amo_observability import note as _note_swallowed
else:  # 运行时：包模式优先，按文件直接加载时退回绝对导入
    try:
        from .amo_observability import note as _note_swallowed
    except ImportError:  # 直接按文件加载时
        from amo_observability import note as _note_swallowed

import asyncio
import hashlib
import json
import random
import re
from datetime import date, datetime, timedelta

from astrbot.api import logger

try:
    from .schedule_holiday import (
        is_long_holiday,
        pick_amusement_spot,
        pick_holiday_plan,
    )
    from .schedule_segments import (
        amusement_segments,
        homebody_segments,
        shopping_segments,
    )
    from .schedule_scenic import scenic_segments
    from .schedule_day_segments import (
        indoor_rest_segments,
        outing_segments,
        workday_segments,
    )
    from .schedule_rest_segments import (
        business_trip_segments,
        overtime_segments,
        period_rest_segments,
        sick_rest_segments,
    )
    from .schedule_social_segments import friend_dinner_segments
    from .schedule_swim import swim_segments
except ImportError:  # 直接按文件加载时
    from schedule_holiday import (
        is_long_holiday,
        pick_amusement_spot,
        pick_holiday_plan,
    )
    from schedule_segments import (
        amusement_segments,
        homebody_segments,
        shopping_segments,
    )
    from schedule_scenic import scenic_segments
    from schedule_day_segments import (
        indoor_rest_segments,
        outing_segments,
        workday_segments,
    )
    from schedule_rest_segments import (
        business_trip_segments,
        overtime_segments,
        period_rest_segments,
        sick_rest_segments,
    )
    from schedule_social_segments import friend_dinner_segments
    from schedule_swim import swim_segments

# 统一时区：日程的 generated_at / 跨天日期按配置时区算，不吃服务器本地时区。
if TYPE_CHECKING:  # 只给类型检查看：包内相对导入
    from .clock import now as _clock_now, today as _clock_today
else:  # 运行时：包模式优先，按文件直接加载时退回绝对导入
    try:
        from .clock import now as _clock_now, today as _clock_today
    except Exception:
        try:
            from clock import now as _clock_now, today as _clock_today
        except Exception:
            def _clock_now(*args, **kwargs):
                return datetime.now()

            def _clock_today(*args, **kwargs):
                return date.today()

#: 日程内部平滑用的向量——就是七情六欲本身（不是第二套心情）。
#: 2026-11-18：原来这里是十维（开心/平静/郁闷/生气/…），和心流并行、互相打架，
#: 已经整组删除。日程只是在**内存里**把心流按小时推一遍，用来给每一格写一个
#: 心情词（item["mood"]）和情绪值（item["mood_valence"]），不落盘。
FEEL_KEYS = (
    "joy", "anger", "sadness", "fear", "love", "disgust", "surprise",
    "desire_eye", "desire_ear", "desire_nose", "desire_tongue", "desire_body",
    "desire_mind", "hunger", "energy",
)
FEEL_BASE = {key: 34.0 for key in FEEL_KEYS}
FEEL_BASE["hunger"] = 35.0
FEEL_BASE["energy"] = 65.0

# 外派省份：全部写在插件里，按日期种子随机，不依赖任何外部接口。
PROVINCE_CITIES = {
    "四川省": "成都",
    "云南省": "昆明",
    "湖南省": "长沙",
    "广西壮族自治区": "南宁",
    "广东省": "广州",
    "湖北省": "武汉",
    "陕西省": "西安",
    "浙江省": "杭州",
    "江苏省": "南京",
    "福建省": "福州",
    "江西省": "南昌",
    "安徽省": "合肥",
    "河南省": "郑州",
    "山东省": "济南",
    "河北省": "石家庄",
    "山西省": "太原",
    "辽宁省": "沈阳",
    "吉林省": "长春",
    "黑龙江省": "哈尔滨",
    "甘肃省": "兰州",
    "青海省": "西宁",
    "海南省": "海口",
    "新疆维吾尔自治区": "乌鲁木齐",
    "内蒙古自治区": "呼和浩特",
    "宁夏回族自治区": "银川",
    "西藏自治区": "拉萨",
}

POSITIVE_LABELS = ("开心", "兴奋", "黏人")
def _city_of(ctx):
    """当前城市；没配城市就是空串（不再兜底写死某个城市）。"""
    return str((ctx or {}).get("city") or "").strip()


def _with_city(ctx, text):
    """把词尾拼在城市后面；没有城市就只留这个词（北站/车站这类）。"""
    city = _city_of(ctx)
    text = str(text or "")
    return (city + text) if city else text


def _place_of(ctx, name):
    """「城市·地点」；没有城市就只写地点，避免出现「·饭店」这种半截字符串。"""
    city = _city_of(ctx)
    name = str(name or "").strip()
    if not name:
        return city
    return (city + "·" + name) if city else name


CITY_POOL = [
    "贵阳", "上海", "杭州", "成都", "重庆", "长沙", "昆明", "广州",
    "深圳", "南京", "武汉", "西安", "北京", "苏州", "天津", "青岛",
]
DISTRICT_MAP = {
    "贵阳": ["观山湖区", "云岩区", "南明区", "花溪区", "乌当区"],
    "上海": ["徐汇区", "静安区", "浦东新区", "长宁区", "杨浦区"],
    "杭州": ["西湖区", "滨江区", "拱墅区", "余杭区"],
    "成都": ["武侯区", "锦江区", "高新区", "成华区"],
    "重庆": ["渝中区", "江北区", "南岸区", "渝北区"],
    "长沙": ["岳麓区", "芙蓉区", "天心区", "开福区"],
    "昆明": ["五华区", "盘龙区", "西山区", "官渡区"],
    "广州": ["天河区", "越秀区", "海珠区", "番禺区"],
    "深圳": ["南山区", "福田区", "罗湖区", "宝安区"],
    "南京": ["鼓楼区", "玄武区", "建邺区", "江宁区"],
    "武汉": ["武昌区", "洪山区", "江汉区", "汉阳区"],
    "西安": ["雁塔区", "碑林区", "莲湖区", "高新区"],
}
HOME_STYLES = ["小窝", "公寓", "出租屋", "家"]
COMPANY_POOL = ["互联网公司", "设计工作室", "广告公司", "贸易公司", "医院", "学校", "书店", "咖啡店"]
CAR_POOL = [
    "黑色奔驰C级", "白色大众高尔夫", "银色特斯拉Model 3",
    "红色Mini Cooper", "深灰色奥迪A4L", "蓝色比亚迪海豹",
    "白色丰田凯美瑞", "黑色沃尔沃S60",
]
CAR_BRANDS = ["奔驰", "宝马", "奥迪", "特斯拉", "比亚迪", "大众", "本田", "丰田", "Mini", "保时捷", "路虎", "沃尔沃", "吉利", "蔚来"]

NEGATIVE_LABELS = ("低落", "烦躁", "委屈", "焦虑", "疲惫")

#: 从人格里抠公司名时要跳过的词：这些是时间副词/泛指，不是公司。
WORK_NAME_BAD_WORDS = ("平时", "一般", "通常", "经常", "每天", "每天都会", "白天",
                       "上班时", "上班后", "周末", "有时", "偶尔", "总是", "有时候",
                       "早上", "晚上", "夜里", "下午", "上午", "中午", "平常")

#: 日程/日记里不许出现他（8.8.0 的规则，12.7.0 照搬同事引擎后补回）：只有聊天里能提到他。
#: 具体怎么称呼（阿墨？哥哥？）由 amo_core/his_names 在运行时按「关系=相恋」的人灌进来，
#: 这里只留通用称呼 —— 换号、换恋人都不用手改代码。
try:
    from .amo_core import his_names as _his_names
except Exception:
    try:
        from amo_core import his_names as _his_names
    except Exception:
        _his_names = None

HIS_WORDS = ("老公", "主人")
_SENTENCE_END_RE = re.compile(r"(?<=[。！？!?；;\n])")


def _his_re():
    if _his_names is not None:
        return _his_names.text_re()
    return re.compile(r"老公|主人|(?<![其吉])他(?!们|人|处|时|乡|俩)")


def has_him(text) -> bool:
    return bool(_his_re().search(str(text or "")))


def solo_text(text, fallback="") -> str:
    """删掉提到他的整句；删空了就用兜底句。"""
    body = str(text or "")
    if not body:
        return fallback
    _re = _his_re()
    kept = [part for part in _SENTENCE_END_RE.split(body)
            if part and not _re.search(part)]
    out = re.sub(r"\s+", " ", "".join(kept)).strip()
    return out if len(out) >= 12 else fallback


def solo_world(world) -> dict:
    """给日程用的世界观副本：去掉提到他的句子（日程只写她一个人）。

    原对象绝不能被改：聊天那边还要用完整的人设（含他）。
    """
    data = dict(world or {})
    for key in ("personality", "daily_life", "world_rules", "summary"):
        value = str(data.get(key) or "")
        if value and has_him(value):
            data[key] = solo_text(value, "")
    hobbies = data.get("hobbies")
    if isinstance(hobbies, list):
        data["hobbies"] = [item for item in hobbies if not has_him(item)]
    return data


try:  # 包内导入（AstrBot 加载插件时走这条）
    from .amo_enums import DayPart, DAY_PART_SPANS, normalize_schedule_item
except Exception:  # 单文件跑测试时走这条
    from amo_enums import DayPart, DAY_PART_SPANS, normalize_schedule_item


#: 每类活动一小时会把七情六欲推多少（日程排版用，真正落库的是 main 那边的心流）。
CATEGORY_FEEL = {
    "sleep": {"energy": 1.4, "fear": -0.8, "anger": -0.8},
    "work": {"energy": -1.1, "fear": 0.7, "joy": -0.2},
    "study": {"energy": -0.7, "fear": 0.5},
    "commute": {"energy": -0.7, "anger": 0.5, "joy": -0.3},
    "meal": {"joy": 0.9, "energy": 0.6, "desire_tongue": -1.0},
    "rest": {"energy": 0.7, "fear": -0.4, "anger": -0.3},
    "play": {"joy": 1.2, "surprise": 0.6, "energy": -0.4},
    "social": {"joy": 1.5, "love": 0.8, "energy": -0.3},
    "life": {"energy": -0.2, "joy": 0.2},
}

TECH_WORK_BANK = [
    "开电脑看邮件", "写代码改需求", "开会对齐方案", "改 Bug",
    "回消息处理需求", "摸鱼喝咖啡", "整理文档", "和同事讨论接口",
]
OFFICE_WORK_BANK = [
    "开电脑看邮件", "整理文档", "开会过方案", "回消息处理事情",
    "做表格对数据", "和同事讨论事情", "泡杯咖啡续命", "写周报",
]
STUDENT_BANK = [
    "上课记笔记", "在图书馆自习", "赶作业", "做实验", "准备考试",
    "在教室听讲座", "小组讨论", "背单词",
]
TEACHER_BANK = [
    "备课", "上课讲题", "批作业", "开教研会", "找学生谈话",
    "整理课件", "监考",
]
MED_BANK = [
    "查房", "写病历", "上门诊", "交接班", "看检查结果", "处理医嘱",
]
SALES_BANK = [
    "给客户打电话", "整理报价", "跑客户", "开销售会", "回客户消息",
    "准备方案", "跟进合同",
]
CREATIVE_BANK = [
    "改稿", "画图", "写文案", "对需求", "找参考", "调细节",
    "和甲方沟通", "导出终稿",
]
SERVICE_BANK = [
    "备餐", "接待客人", "收拾台面", "盘点库存", "交接班",
    "处理订单", "擦桌子",
]
ADMIN_BANK = [
    "整理文件", "做报表", "开会", "写材料", "对接部门",
    "核对数据", "回复邮件",
]

# 职业关键词 -> 工作活动库；匹配不到的走通用办公（不再默认程序员）
OCCUPATION_BANKS = (
    (("程序员", "开发", "架构", "运维", "测试", "技术", "科技", "算法", "前端", "后端", "软件"), TECH_WORK_BANK),
    (("学生", "研究生", "大学生", "高中生", "初中生", "考研"), STUDENT_BANK),
    (("老师", "教师", "教授", "讲师", "教练", "园长"), TEACHER_BANK),
    (("医生", "护士", "医师", "药师", "医护", "牙医"), MED_BANK),
    (("销售", "商务", "市场", "采购", "客户经理", "业务员", "公关"), SALES_BANK),
    (("设计", "文案", "编辑", "作者", "画师", "摄影师", "剪辑", "自媒体", "编剧"), CREATIVE_BANK),
    (("厨师", "餐饮", "店长", "服务员", "咖啡师", "店员", "收银"), SERVICE_BANK),
    (("会计", "财务", "行政", "人事", "公务员", "文员", "法务", "律师", "hr"), ADMIN_BANK),
)

# 会出差/跑外勤的职业
TRAVEL_KEYWORDS = ("销售", "商务", "市场", "采购", "项目经理", "顾问", "客户", "出差", "外勤")


def work_bank_for(world):
    """按职业挑工作活动库；认不出来就用通用办公，不再默认「写代码/改 Bug」。"""
    world = world or {}
    text = (str(world.get("occupation") or "") + " " + str(world.get("workplace") or "")).lower()
    for keywords, bank in OCCUPATION_BANKS:
        for keyword in keywords:
            if keyword in text:
                return bank
    return OFFICE_WORK_BANK


def travels_for_work(world):
    text = (str((world or {}).get("occupation") or "") + " " + str((world or {}).get("workplace") or "")).lower()
    return any(keyword in text for keyword in TRAVEL_KEYWORDS)


def occupation_kind(world):
    """粗分类，用来决定突发事件文案。"""
    world = world or {}
    text = (str(world.get("occupation") or "") + " " + str(world.get("workplace") or "")).lower()
    for keywords, kind in (
        (("学生", "研究生", "大学生", "高中生", "初中生", "考研"), "student"),
        (("老师", "教师", "教授", "讲师", "教练", "园长"), "teacher"),
        (("医生", "护士", "医师", "药师", "医护", "牙医"), "med"),
        (("程序员", "开发", "架构", "运维", "测试", "技术", "科技", "算法", "前端", "后端", "软件"), "tech"),
    ):
        for keyword in keywords:
            if keyword in text:
                return kind
    return "office"


#: 活动里有这些词，就说明这一小时在吃/在买吃的。
_FOOD_ACTIVITY_WORDS = (
    "便利店", "买饭", "买啥", "买东西", "买杯", "买点", "吃", "饭", "外卖",
    "扒两口", "垫两口", "点单", "点餐", "餐",
)
#: 细节里有这些词，就说明这一小时在工作/开会。
_MEETING_DETAIL_WORDS = ("会议", "开会", "过方案", "对齐方案")
#: 活动是睡觉/刚醒。
_SLEEP_ACTIVITY_WORDS = ("睡觉", "睡着了", "睡沉", "赖床", "被窝", "眯", "躺")
#: 工作类细节（和「在睡觉」对不上）。
_WORK_DETAIL_WORDS = ("周报", "需求", "改稿", "数据", "邮件", "咖啡续", "会议", "开会", "第三版")


def detail_conflicts(activity, detail):
    """这一小时的「细节」和「活动」明显不是一回事时返回 True。

    真机案例（2026-11-10 11:00）：activity 被模型润色成「在便利店纠结买啥」，
    但 detail 还是按 zone=office/category=work 随机挑的「被拉进临时会议」；
    小时日记和面板于是同时出现「在便利店」和「被拉进临时会议」两套剧情。
    """
    activity = str(activity or "")
    detail = str(detail or "")
    if not activity or not detail:
        return False
    if any(word in activity for word in _FOOD_ACTIVITY_WORDS) and any(
        word in detail for word in _MEETING_DETAIL_WORDS
    ):
        return True
    if any(word in activity for word in _SLEEP_ACTIVITY_WORDS) and any(
        word in detail for word in _WORK_DETAIL_WORDS
    ):
        return True
    return False

COMMUTE_BANK = [
    "挤地铁去公司", "在车上听歌", "等红灯", "换乘", "堵在路上",
    "刷手机看路况", "快步往公司走",
]
#: 自己有车时的通勤（黑色奔驰 C 级）
DRIVE_COMMUTE_BANK = [
    "老周开车送她去公司，高架上堵了一段", "老周绕开了最堵那条路",
    "老周在楼下找了两圈车位", "在车里听完一首歌才下车",
    "路上被加塞，老周按了两下喇叭", "车停好后她走到电梯口",
]
LUNCH_BANK = [
    "下楼吃牛肉粉", "和同事拼饭", "点外卖", "吃碗牛肉面",
    "去便利店随便对付一口", "边吃边刷手机",
]
BREAKFAST_BANK = [
    "煎个蛋配牛奶", "豆浆配油条", "楼下吃碗粉", "煮点速冻饺子",
    "面包配咖啡", "随便对付一口",
]
REST_BANK = [
    "瘫在沙发上", "刷手机", "追剧", "发呆", "看短视频",
    "窝着不想动", "听歌",
]
DINNER_BANK = [
    "煮面", "点外卖", "炒两个菜", "下楼吃小馆子", "喝碗热汤",
]
HOME_LIFE_BANK = [
    "刷牙洗脸", "煎蛋热牛奶", "收拾包", "换衣服", "洗衣服",
    "扫地", "洗澡", "吹头发", "护肤", "收拾明天要带的东西",
]
#: 晚上/睡前那一小时，不应该出现「煎蛋热牛奶 / 收拾包」。
NIGHT_LIFE_BANK = [
    "洗澡", "吹头发", "护肤", "敷面膜", "换睡衣", "刷牙",
]
SCENIC_BANK = [
    "排队买票", "拍照", "慢慢逛", "找地方坐一会儿", "买奶茶",
    "看路边的小摊", "跟着人群往前走",
]
#: 休息日偶尔去玩水（不是每周都去）：游泳馆 / 海边 / 水上乐园 随机挑一个
SWIM_PLACES = (
    ("游泳馆", "在泳池里游了几圈", "水有点凉，游一会儿就上岸歇"),
    ("海边", "在海边踩浪、玩水", "浪打过来，裤子湿了一截"),
    ("水上乐园", "在水上乐园排队玩滑道", "排队排了好久，滑下来那一下特别爽"),
)
SWIM_DETAILS = (
    "水有点凉，下去那一下打了个激灵", "游了几圈就喘，趴在池边歇",
    "被晒得有点晕，赶紧补防晒", "人比想象中多，等了好久才轮到",
)
ROAD_BANK = [
    "老周开车去景区", "堵在路上", "找停车位", "导航绕路", "等红绿灯",
]
TAXI_BANK = [
    "打车", "在网约车后排刷手机", "看着窗外的街景", "催司机快一点",
]
STATION_BANK = [
    "进站候车", "检票上车", "在候车厅买水", "看大屏找检票口",
]
HOTEL_BANK = [
    "在酒店整理资料", "躺床上刷手机", "洗澡", "给手机充电", "看明天的安排",
]
INDOOR_BANK = [
    "逛展", "看电影", "逛街", "在咖啡店坐着", "看橱窗",
]


def clamp(value, low=0.0, high=100.0):
    try:
        value = float(value)
    except Exception as _amo_exc:
        _note_swallowed("schedule_engine.clamp", _amo_exc)
        return float(low)
    return max(float(low), min(float(high), value))


def md5_int(text):
    return int(hashlib.md5(str(text).encode("utf-8")).hexdigest()[:8], 16)


def parse_hhmm(value, default=0):
    try:
        parts = str(value).strip().split(":")
        return int(parts[0]) * 60 + int(parts[1])
    except Exception as _amo_exc:
        _note_swallowed("schedule_engine.parse_hhmm", _amo_exc)
        return default


def fmt_hhmm(minutes):
    """把分钟格式化成 HH:MM；1440 输出 24:00（用于 23:00-24:00 闭环）。"""
    try:
        minutes = int(minutes)
    except Exception as _amo_exc:
        _note_swallowed("schedule_engine.fmt_hhmm", _amo_exc)
        minutes = 0
    if minutes >= 24 * 60:
        return "24:00"
    if minutes < 0:
        minutes = 0
    return "%02d:%02d" % (minutes // 60, minutes % 60)


SAFE_EVENT = {"event": "日常发呆", "location": "家", "cost": 0}


def _strip_fences(text):
    """去掉 ```json / ``` 包裹、BOM、零宽字符。"""
    text = str(text or "").replace("\ufeff", "").replace("\u200b", "").replace("\u200c", "")
    text = re.sub(r"```[a-zA-Z0-9_-]*", "", text)
    return text.replace("```", "").strip()


def _balanced(text, opener, closer):
    """从第一个 opener 开始做括号配对，返回最外层完整片段（忽略字符串里的括号）。"""
    start = text.find(opener)
    if start < 0:
        return ""
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return ""


def json_extract(raw, fallback=None):
    """从模型输出里抠 JSON：去 Markdown、去掉前后废话、容忍尾逗号；失败返回 fallback，绝不抛异常。"""
    text = _strip_fences(raw)
    if not text:
        return fallback
    candidates = []
    for opener, closer in (("{", "}"), ("[", "]")):
        chunk = _balanced(text, opener, closer)
        if chunk:
            candidates.append(chunk)
    candidates.append(text)
    for chunk in candidates:
        chunk = chunk.strip()
        if not chunk:
            continue
        cleaned = re.sub(r",\s*([}\]])", r"\1", chunk)
        cleaned = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", cleaned)
        for attempt in (cleaned, re.sub(r"'([^']*)'", r'"\1"', cleaned)):
            try:
                return json.loads(attempt)
            except Exception:
                continue
    logger.warning("[JSON_PARSE] 模型返回的不是合法 JSON（已降级为兜底）：%s", text[:120])
    return fallback


def diary_presence_rules(together=False):
    """小日记的第 7/8 条：约会这一小时不许把老公写成“微信上的网友”。"""
    if together:
        return (
            "【物理场景事实·最高优先级】这一小时你们在一起：老公就在你对面，面对面坐在一起；"
            "这不是网恋、不是异地。聊天记录只是你们当面说的话，不能拿来判断“人在不在”。\n"
            "7. 只能写面对面的细节（他给你夹菜、你抬头看他、一起走一起回家）；"
            "严禁写「他在微信上跟我说」「他不在我身边」「我一个人吃」。\n"
            "8. 面对面的互动（他抱我、他来看我、他给我夹菜）是事实，可以照写；素材里没有的动作不要编。\n"
        )
    return (
        "7. 素材包里没写他出现，就不能写他出现；严禁虚构打电话/拥抱/送药/来陪你；\n"
        "8. 可以写「想他/想被抱抱」，但不能写成「他抱了我/他打电话来」；"
        "线上聊天只能写「在微信/飞书上聊了几句」；\n"
    )


class ScheduleEngine:
    """把“状态 -> 主干 -> 可选润色 -> 动态日记”拆开。"""

    def __init__(self, state):
        self.state = state
        self.p = state.p

    # ------------------------------------------------------------------
    # 0. 角色位置/资产：配置优先，其次人格提示词/世界观，最后自动随机
    # ------------------------------------------------------------------
    def resolve_profile(self, world, persona="", seed=""):
        """把“城市/住址/公司/车”解析出来，并在缺失时自动生成一套稳定值。"""
        world = world or {}
        text = "\n".join([
            str(persona or ""),
            str(world.get("city") or ""),
            str(world.get("workplace") or ""),
            str(world.get("daily_life") or ""),
            str(world.get("world_rules") or ""),
            str(world.get("summary") or ""),
        ])
        cached: dict[Any, Any] = {}
        try:
            cached = self.state.db.kv_get("schedule_profile", {}) or {}
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.ScheduleEngine.resolve_profile", _amo_exc)
            cached = {}
        if not isinstance(cached, dict):
            cached = {}
        city = str(self.p.cfg_str("schedule_city", "") or "").strip()
        if not city:
            city = self._extract_city(text)
        if not city:
            city = str(world.get("city") or "").strip()
        if not city or city in ("城市", "未知", "某市"):
            # 配置/人格/世界观都没有城市就留空：日程骨架走「不写具体城市」的分支，
            # 不再从 CITY_POOL 随机编一个；旧档案里的城市也不沿用（否则「清空城市」清不掉）
            city = ""
        if cached.get("city") and cached.get("city") != city:
            cached = {}

        home = str(self.p.cfg_str("schedule_home", "") or "").strip()
        if not home:
            home = self._extract_home(text)
        if not home:
            home = str(cached.get("home") or "").strip()
        if not home:
            home = self._random_home(city, seed)

        workplace = str(self.p.cfg_str("schedule_workplace", "") or "").strip()
        if not workplace:
            workplace = self._extract_work(text)
        if not workplace:
            # 世界观里的单位常写成「中国计算智脑集团（贵阳），观山湖区」：地点只留公司名那一段，
            # 否则日程和自拍提示词都会变成「在中国计算智脑集团（贵阳），观山湖区」。
            world_work = str(world.get("workplace") or "").strip()
            world_work = re.split(r"[，,、;；/|]", world_work)[0].strip() if world_work else ""
            if world_work and world_work not in ("公司", "单位", "工作地点", "上班"):
                workplace = world_work
        if not workplace:
            workplace = str(cached.get("workplace") or "").strip()
        if not workplace:
            workplace = self._random_workplace(city, seed)

        # 角色资产：一个字段同时认车/房/奢侈品。车用来开，房用来住，其余当"他送的东西"。
        assets_cfg = str(self.p.cfg_str("schedule_car", "") or "").strip()
        cfg_car, cfg_home, cfg_assets = self._split_assets(assets_cfg)
        car = cfg_car
        if not car:
            car = self._extract_car(text)
        if not car:
            car = str(cached.get("car") or "").strip()
        if not car:
            car = CAR_POOL[md5_int(str(world.get("name") or "") + "|car") % len(CAR_POOL)]
        if cfg_home:
            home = cfg_home

        base = {
            "city": city,
            "home": home,
            "workplace": workplace,
            "car": car,
        }
        try:
            if cached != base:
                self.state.db.kv_set("schedule_profile", base)
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.ScheduleEngine.resolve_profile", _amo_exc)
        profile = dict(base)
        # 2026-11-25（用户口径：从人格提取）：人格里写着「有台黑色奔驰」，
        # 那就按有车排日程（通勤有司机老周开），不再因为「没送过车」就天天挤地铁。
        profile["has_gift_car"] = bool(str(profile.get("car") or "").strip())
        profile["has_gift_home"] = False
        try:
            gift = getattr(self.p, "gift", None)
            if gift is not None:
                car_gift = gift.asset_override("vehicle")
                if car_gift:
                    profile["car"] = car_gift
                    profile["has_gift_car"] = True
                home_gift = gift.asset_override("home")
                if home_gift:
                    profile["has_gift_home"] = True
                    profile["home"] = (home_gift if str(home_gift) not in ("房", "房子", "住宅", "楼", "小区")
                                       else "新家")
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.ScheduleEngine.resolve_profile", _amo_exc)
        return profile

    @staticmethod
    def _split_assets(value):
        """把「角色资产」拆成 车 / 房 / 其他；支持顿号、逗号、分号分隔。"""
        text = str(value or "").strip()
        if not text:
            return "", "", ""
        parts = [p.strip() for p in re.split(r"[、,，;；/|]+", text) if p.strip()]
        car_words = ("奔驰", "宝马", "奥迪", "大众", "丰田", "本田", "保时捷", "特斯拉",
                     "比亚迪", "凯迪拉克", "沃尔沃", "路虎", "捷豹", "雷克萨斯", "蔚来",
                     "理想", "小鹏", "吉利", "五菱", "车")
        home_words = ("房", "别墅", "公寓", "住宅", "大平层", "洋房", "小区", "楼")
        cars, homes, others = [], [], []
        for part in parts:
            if any(word in part for word in home_words):
                homes.append(part)
            elif any(word in part for word in car_words):
                cars.append(part)
            else:
                others.append(part)
        return "、".join(cars), "、".join(homes), "、".join(others)

    @staticmethod
    def _extract_city(text):
        text = str(text or "")
        for city in CITY_POOL:
            if city in text:
                return city
        return ""

    @staticmethod
    def _extract_home(text):
        text = str(text or "")
        patterns = (
            r"(?:住在|家住在|家在|住址在|家在)([^，。；\n]{2,20})",
            r"(?:我家在|我住在)([^，。；\n]{2,20})",
        )
        for pattern in patterns:
            matched = re.search(pattern, text)
            if not matched:
                continue
            value = str(matched.group(1) or "").strip(" 的了是在")
            if value and "公司" not in value and "上班" not in value:
                return value[:20]
        return ""

    @staticmethod
    def _extract_work(text):
        text = str(text or "")
        patterns = (
            r"(?:在|就职于|任职于|工作在)([^，。；：（）「」“”\n]{2,24})(?:上班|工作|任职|实习)",
            r"([^，。；：（）「」“”\n]{2,24})(?:上班|工作)",
        )
        for pattern in patterns:
            matched = re.search(pattern, text)
            if not matched:
                continue
            # 全角空格（U+3000）按空白处理：人格里「　　上班」以前会被抓成公司名，
            # 日程就成了「在　　」。顺手拒掉没有任何可见字符的结果。
            value = str(matched.group(1) or "").replace("\u3000", " ").strip()
            value = value.strip(" 的了是在")
            if not re.search(r"[\w\u4e00-\u9fff]", value):
                continue
            # 「平时上班 / 一般上班 / 通常上班」这种是时间副词，不是公司名：
            # 以前直接抓成公司，日程就出现「在平时上班」「平时附近吃午饭」。
            if any(word in value for word in WORK_NAME_BAD_WORDS):
                continue
            if value and "家" not in value and "住" not in value:
                return value[:24]
        return ""

    @staticmethod
    def _extract_car(text):
        text = str(text or "")
        for brand in CAR_BRANDS:
            if brand in text:
                return brand
        return ""

    @staticmethod
    def _random_home(city, seed):
        rng = random.Random(md5_int(str(city or "") + "|home|" + str(seed or "")))
        if not str(city or "").strip():
            return rng.choice(HOME_STYLES)
        districts = DISTRICT_MAP.get(str(city or "")) or ["市区"]
        return rng.choice(districts) + "·" + rng.choice(HOME_STYLES)

    @staticmethod
    def _random_workplace(city, seed):
        rng = random.Random(md5_int(str(city or "") + "|work|" + str(seed or "")))
        if not str(city or "").strip():
            return rng.choice(COMPANY_POOL)
        return rng.choice(COMPANY_POOL) + "（" + str(city or "市区") + "）"

    # ------------------------------------------------------------------
    # 1. 当天上下文
    # ------------------------------------------------------------------
    def build_context(self, day, meta, weather, world, feel, period, health, persona="", salt=""):
        seed_text = "%s|%s" % (day, salt)
        seed = md5_int(seed_text)
        profile = self.resolve_profile(world, persona, seed=str(seed))
        city = profile["city"]
        home = profile["home"]
        workplace = profile["workplace"]
        car = profile["car"]
        _, _, cfg_assets = self._split_assets(self.p.cfg_str("schedule_car", "") or "")
        yesterday = self.yesterday_summary(day)
        good_weather = self._good_weather(weather)
        event = self._pick_event(day, meta, weather, health, period, seed, world)
        holiday_plan = self._pick_holiday_plan(
            day, meta, weather, health, period, event, good_weather, seed, city,
        )
        if holiday_plan is not None:
            scenic = holiday_plan.get("scenic")
            swim = holiday_plan.get("swim")
        else:
            scenic = self._pick_scenic(day, meta, weather, health, period, event,
                                       good_weather, seed, city)
            swim = None
            if not scenic:
                # 一天只安排一件事：去景区就不去玩水，反之亦然
                swim = self._pick_swim(day, meta, weather, health, period, event,
                                       good_weather, seed, city)

        feel_now = {key: clamp(feel.get(key, FEEL_BASE[key])) for key in FEEL_KEYS}
        return {
            "version": "backbone-v5",
            "day": day,
            "meta": dict(meta or {}),
            "weather": dict(weather or {}),
            "world": dict(world or {}),
            "city": city,
            "home": home,
            "workplace": workplace,
            "car": car,
            "has_gift_car": bool(profile.get("has_gift_car")),
            "has_gift_home": bool(profile.get("has_gift_home")),
            "assets": self._gift_assets(cfg_assets),
            "worn": self._gift_worn(),
            "gift_log": self._gift_log(),
            "feel": feel_now,
            "period": dict(period or {}),
            "health": dict(health or {}),
            "yesterday": yesterday,
            "good_weather": good_weather,
            "event": event,
            "holiday_plan": holiday_plan,
            "scenic": scenic,
            "swim": swim,
            "profile": profile,
            "location": (event.get("where") if event.get("kind") == "business_trip" else city),
            "seed": seed,
            "generated_at": _clock_now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _gift_assets(self, extra=""):
        """他送的大件（车/房/贵重）+ 配置里的角色资产，写进日程上下文。"""
        items = []
        extra = str(extra or "").strip()
        if extra:
            items.append(extra)
        try:
            gift = getattr(self.p, "gift", None)
            if gift is not None:
                text = gift.asset_text()
                if text:
                    items.append(text)
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.ScheduleEngine._gift_assets", _amo_exc)
        return "、".join([item for item in items if item])

    def _gift_worn(self):
        """他送的小件里能穿戴的（手表/围巾/包/口红），写进日程上下文。"""
        try:
            gift = getattr(self.p, "gift", None)
            if gift is not None:
                return gift.worn_text()
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.ScheduleEngine._gift_worn", _amo_exc)
        return ""

    @staticmethod
    def _gift_mention_hours(ctx):
        """每天最多两个整点允许在日记里提他送的礼物。

        按日期固定，避免每小时都在写"捏着挂件/戴着围巾"，把礼物写成了强迫症。
        """
        day = str((ctx or {}).get("day") or "")
        seed = str((ctx or {}).get("seed") or "")
        rnd = random.Random("%s|%s" % (day, seed))
        pool = list(range(9, 22))
        first = rnd.choice(pool)
        second = rnd.choice([h for h in pool if abs(h - first) >= 2] or pool)
        return {first, second}

    @staticmethod
    def _use_gift_today(ctx, label):
        """同一天同一件东西固定选择：六成用他送的，四成用自己的。"""
        day = str(ctx.get("day") or "")
        if not day:
            return True
        return md5_int(day + "|wear|" + label) % 10 < 6

    @staticmethod
    def _wear_phrase(label, gifted):
        if label == "包":
            return "背着包（他送的）" if gifted else "背着包"
        return ("戴了%s（他送的）" if gifted else "戴了%s") % label

    def _apply_gift_effects(self, items, ctx):
        """出门时写穿戴：他送的标「他送的」；自己的只写通用名。"""
        temp = (ctx.get("weather") or {}).get("temp")
        labels = []
        gift = getattr(self.p, "gift", None)
        if gift is not None:
            try:
                labels = gift.wear_labels(temp)
            except Exception as _amo_exc:
                _note_swallowed("schedule_engine.ScheduleEngine._apply_gift_effects", _amo_exc)
                labels = []
        try:
            temp_value = float(temp) if temp is not None else None
        except (TypeError, ValueError):
            # 和风缺字段/旧 kv 里的 "N/A" 会让 float() 抛错，整个主干生成失败、
            # 退回兜底日程（当天活动/地点/穿戴全废）
            temp_value = None
        own = ["围巾"] if temp_value is not None and temp_value <= 20 else []
        if not labels and not own:
            return items
        extras = []
        for label in labels:
            extras.append(self._wear_phrase(label, self._use_gift_today(ctx, label)))
        for label in own:
            if label not in labels:
                extras.append(self._wear_phrase(label, False))
        suffix = "；".join(extras)
        for item in items:
            if item.get("category") not in ("commute", "play"):
                continue
            place = str(item.get("place") or "")
            if not place or place == "家" or place.startswith("家"):
                continue
            detail = str(item.get("detail") or "").strip()
            if suffix and suffix not in detail:
                item["detail"] = (detail + "；" + suffix).strip("；")
        return items

    def _gift_log(self):
        """带日期的礼物记录，让日程日记有迹可查。"""
        try:
            gift = getattr(self.p, "gift", None)
            if gift is not None:
                return gift.gift_log_text()
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.ScheduleEngine._gift_log", _amo_exc)
        return ""

    def yesterday_summary(self, day):
        """读取昨日遗留：熬夜、睡眠不足、生病，今天必须疲惫。"""
        try:
            target = date.fromisoformat(str(day))
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.ScheduleEngine.yesterday_summary", _amo_exc)
            target = _clock_today()
        prev_day = (target - timedelta(days=1)).isoformat()
        items: list[Any] = []
        try:
            items = self.state.schedule.get(prev_day) or self.state.db.get_schedule(prev_day) or []
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.ScheduleEngine.yesterday_summary", _amo_exc)
            items = []
        if not isinstance(items, list):
            items = []
        sleep_hours = 0
        late_night = False
        for item in items:
            if not isinstance(item, dict):
                continue
            category = str(item.get("category") or "")
            activity = str(item.get("activity") or "")
            if category == "sleep":
                sleep_hours += 1
            start = parse_hhmm(item.get("start"), 0)
            if 0 <= start < 4 * 60 and category not in ("sleep", ""):
                late_night = True
            if any(word in activity for word in ("熬夜", "通宵", "失眠", "加班到")):
                late_night = True
        if items and sleep_hours and sleep_hours < 6:
            late_night = True
        note = ""
        if late_night:
            note = "昨晚熬到很晚，今天一整天都容易累、注意力不集中"
        elif sleep_hours and sleep_hours <= 6:
            note = "昨晚睡得不太够，今天起床有点费劲"
        return {
            "day": prev_day,
            "late_night": late_night,
            "sleep_hours": sleep_hours,
            "note": note,
        }

    def _good_weather(self, weather):
        weather = weather or {}
        tag = str(weather.get("tag") or "").lower()
        text = str(weather.get("text") or "")
        if tag in ("rain", "storm", "snow", "thunder", "fog"):
            return False
        if any(word in text for word in ("雨", "雪", "雷", "雾", "沙尘")):
            return False
        try:
            temp = float(weather.get("temp", 20))
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.ScheduleEngine._good_weather", _amo_exc)
            temp = 20.0
        return 5.0 <= temp <= 34.0

    # 各职业的「临时加班」文案
    OVERTIME_NOTES = {
        "tech": ("临时加班", "线上出问题了，被叫去公司处理"),
        "student": ("临时加课", "老师临时加了两节课，晚上才回"),
        "teacher": ("临时代课", "学校临时安排代课/监考，走不开"),
        "med": ("临时排班", "科室临时排了班，得顶上去"),
        "office": ("临时加班", "公司临时有事，被叫过去帮忙"),
    }

    def _pick_event(self, day, meta, weather, health, period, seed, world=None):
        """按日期种子决定突发事件，保证同一天多次读取结果一致。"""
        prob = clamp(self.p.cfg_float("schedule_event_prob", 0.28), 0.0, 0.9)
        rng = random.Random(seed ^ 0x5F3759DF)
        if rng.random() > prob:
            return {"kind": "none"}
        rest = bool((meta or {}).get("rest"))
        if self._is_long_holiday(meta):
            # 长假由 holiday_plan 安排，不再随机塞加班/出差。
            return {"kind": "none"}
        kind = occupation_kind(world)
        if not rest:
            # 只有会跑外勤的职业才出差；其他人是加班/加课/排班
            if travels_for_work(world) and rng.random() < 0.55:
                provinces = sorted(PROVINCE_CITIES.keys())
                province = provinces[rng.randrange(len(provinces))]
                city = PROVINCE_CITIES[province]
                return {
                    "kind": "business_trip",
                    "title": "临时外派",
                    "province": province,
                    "city": city,
                    "where": "%s·%s" % (province, city),
                    "note": "早上接到通知，被派去%s出差，当天回不来" % city,
                    "task": "处理外派的事",
                    "effects": {"energy": -10, "fear": 10, "joy": -6, "anger": 3},
                    "soothe": False,
                }
            title, note = self.OVERTIME_NOTES.get(kind, self.OVERTIME_NOTES["office"])
            return {
                "kind": "overtime",
                "title": title,
                "note": "早上" + note + "，今天回不去了",
                "task": "处理临时的事",
                "effects": {"energy": -12, "fear": 8, "anger": 10, "joy": -8},
                "soothe": False,
            }
        # 休息日：临时加班 / 朋友聚餐。
        if rng.random() < 0.55:
            title, note = self.OVERTIME_NOTES.get(kind, self.OVERTIME_NOTES["office"])
            return {
                "kind": "overtime",
                "title": title,
                "note": "上午接到电话，" + note + "，休息日也泡汤了",
                "task": "处理临时的事",
                "effects": {"anger": 16, "fear": 12, "joy": -12, "energy": -6},
                "soothe": False,
            }
        return {
            "kind": "friend_dinner",
            "title": "朋友聚餐",
            "note": "下午朋友突然发消息，说好久没见了，晚上一起吃饭",
            "effects": {"joy": 14, "love": 8, "surprise": 6, "energy": 4},
            "soothe": True,
        }

    def _is_long_holiday(self, meta):
        return is_long_holiday(self.p, meta)

    def _pick_amusement_spot(self, city, seed):
        return pick_amusement_spot(self.p, city, seed)

    def _pick_holiday_plan(self, day, meta, weather, health, period, event,
                           good_weather, seed, city):
        return pick_holiday_plan(
            self, day, meta, weather, health, period, event,
            good_weather, seed, city,
        )

    def _pick_scenic(self, day, meta, weather, health, period, event, good_weather, seed, city):
        if not (meta or {}).get("rest"):
            return None
        if event.get("kind") == "overtime":
            return None
        if (health or {}).get("sick"):
            return None
        if int((period or {}).get("pain") or 0) >= 8:
            return None
        try:
            spots = self.p.scenic_spots() or []
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.ScheduleEngine._pick_scenic", _amo_exc)
            spots = []
        spots = [item for item in spots if isinstance(item, dict) and item.get("name")]
        _city = str(city or "").strip()
        if not _city:
            # 没配城市：不挑任何城市的景点，给一个不写城市的通用公园
            return {
                "name": "人民公园", "city": "", "province": "",
                "area": "", "projects": ["慢慢逛", "找个地方坐会儿", "拍几张照"],
                "duration": "3-4小时", "indoor": False,
            }
        _local = [item for item in spots if _city and _city in str(item.get("city") or "")]
        # 「省内」这一档以前根本没实现：周末只挑同城，长假才出城。
        # 2026-11-22 用户口径：双休在省内（贵阳 → 凯里/安顺/遵义…），长假才出省。
        _home_prov = ""
        for item in _local or spots:
            prov = str(item.get("province") or "").strip()
            if prov:
                _home_prov = _prov_stem(prov)
                break
        _same_prov = [
            item for item in spots
            if _home_prov
            and _prov_stem(item.get("province")) == _home_prov
            and _city not in str(item.get("city") or "")
        ]
        _out_prov = [
            item for item in spots
            if str(item.get("province") or "").strip()
            and (not _home_prov or _prov_stem(item.get("province")) != _home_prov)
        ]
        _long = ScheduleEngine._is_long_holiday(self, meta)
        if _city and not _local and not _same_prov and not _long:
            return None
        if not spots:
            return {
                "name": "人民公园", "city": _city, "province": "",
                "area": "", "projects": ["慢慢逛", "找个地方坐会儿", "拍几张照"],
                "duration": "3-4小时", "indoor": False,
            }
        # 以前这里写死「贵阳/贵州」：非贵阳城市 guiyang/guizhou 恒为空 →
        # 下雨时 pool=[] 又回退成全部景点（含户外），文案还说「找个室内的地方」。
        # 现在按 spots 自己的 indoor 标记选，和城市无关。
        if not good_weather:
            indoor = [item for item in (_local or _same_prov or spots) if item.get("indoor")]
            pool = indoor or list(_local or _same_prov or spots)
        elif _long:
            # 长假出省：先挑别的省，其次省内他市，最后才本市
            pool = _out_prov or _same_prov or _local or list(spots)
        else:
            # 双休小旅行：省内其他城市与本市按日期种子对半分，
            # 同一天刷新多少次结果都一样（seed 就是日期）。
            if _same_prov and int(seed) % 2 == 0:
                pool = _same_prov
            else:
                pool = _local or _same_prov or list(spots)
        if good_weather:
            outdoor = [item for item in pool if not item.get("indoor")]
            if outdoor:
                pool = outdoor
        longer = [item for item in pool if not str(item.get("duration") or "").startswith("1")]
        if longer:
            pool = longer
        pool = sorted(pool, key=lambda item: str(item.get("name") or ""))
        if not pool:
            pool = sorted(spots, key=lambda item: str(item.get("name") or ""))
        chosen = dict(pool[seed % len(pool)])
        chosen["why"] = "天气不错，想出去走走" if good_weather else "天气一般，找个室内的地方待着"
        chosen["from_city"] = city
        return chosen

    # ------------------------------------------------------------------
    # 2. 主干骨架
    # ------------------------------------------------------------------
    def _pick_swim(self, day, meta, weather, health, period, event, good_weather, seed, city):
        """休息日偶尔去玩水：游泳馆 / 海边 / 水上乐园，随机一个。

        规则（用户 2026-11-12）：
        - 不是每周都去，也不是每个休息日都去；一周最多一次；
        - 冬天（温度低于 ``schedule_swim_min_temp``）或天气不好不去；
        - 这一周已经去过一次，就整周不再安排（旅游时例外）；
        - 三个地方随机挑，去了哪个就记在 kv 里，同一周不重复。
        """
        if not (meta or {}).get("rest"):
            return None
        if (event or {}).get("kind") in ("overtime", "business_trip"):
            return None
        if (health or {}).get("sick") or int((period or {}).get("pain") or 0) >= 8:
            return None
        try:
            temp = float((weather or {}).get("temp") or 0)
        except (TypeError, ValueError):
            temp = 0.0
        min_temp = 22.0
        try:
            min_temp = self.p.cfg_float("schedule_swim_min_temp", 22.0)
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.ScheduleEngine._pick_swim.temp", _amo_exc)
        if not good_weather or temp < float(min_temp):
            return None
        try:
            iso = date.fromisoformat(str(day)).isocalendar()
            weekday = date.fromisoformat(str(day)).weekday()
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.ScheduleEngine._pick_swim.day", _amo_exc)
            return None
        week_key = "swim_week:%04d-%02d" % (iso[0], iso[1])
        used = ""
        try:
            used = str(self.p.db.kv_get(week_key, "") or "")
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.ScheduleEngine._pick_swim.kv", _amo_exc)
            used = ""
        used_kind, _, used_day = used.partition("|")
        traveling = ScheduleEngine._is_long_holiday(self, meta)
        if used_kind and traveling and used_day != str(day):
            # 旅游期间不受「这周已经去过」的限制
            used_kind, used_day = "", ""
        if used_day and used_day != str(day) and not traveling:
            return None
        rng = random.Random("amo-swim:" + week_key)
        preferred = rng.choice([5, 6])
        if used_day != str(day) and not traveling and weekday != preferred:
            return None
        if not used_kind:
            chance = 0.32
            try:
                chance = clamp(self.p.cfg_float("schedule_swim_prob", 0.32), 0.0, 1.0)
            except Exception as _amo_exc:
                _note_swallowed("schedule_engine.ScheduleEngine._pick_swim.prob", _amo_exc)
            if rng.random() > chance:
                return None
            place, activity, detail = SWIM_PLACES[rng.randrange(len(SWIM_PLACES))]
        else:
            match = [item for item in SWIM_PLACES if item[0] == used_kind]
            place, activity, detail = match[0] if match else SWIM_PLACES[0]
        where = ("%s·%s" % (str(city or "").strip(), place)).strip("·")
        try:
            if not used_kind:
                self.p.db.kv_set(week_key, place + "|" + str(day))
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.ScheduleEngine._pick_swim.save", _amo_exc)
        return {
            "place": where,
            "spot": place,
            "activity": activity,
            "detail": detail,
            "zone": "scenic",
            "why": "天气挺热，想去玩水",
        }

    def _swim_segments(self, ctx):
        return swim_segments(ctx, self._seg, self._choose, SWIM_DETAILS)

    def _outing_segments(self, ctx):
        return outing_segments(ctx, self._seg)

    def build_skeleton(self, ctx):
        event_kind = (ctx.get("event") or {}).get("kind")
        meta = ctx.get("meta") or {}
        day_id = str(((ctx or {}).get("day_type") or {}).get("id") or "")
        # 日历闸：日子类型是抽出来的，日历是死的。休息日不许走上班骨架，
        # 工作日也不许走宅家/外出骨架（2026-11-23：周一抽到宅家日，骨架全天在家，
        # 文案却写着在公司上班，照片就成了家里的一张自拍）。
        rest_day = bool(meta.get("rest"))
        if not rest_day and day_id in ("restday", "outing", "homebody"):
            logger.debug("[amo] 日历是工作日，%s 改按上班日排骨架" % day_id)
            day_id = "workday"
        elif rest_day and day_id in ("workday", "overtime", "slacking"):
            logger.debug("[amo] 日历是休息日，%s 改按休息日排骨架" % day_id)
            day_id = "restday"
        sick = bool((ctx.get("health") or {}).get("sick"))
        sick_leave = sick and str(ctx.get("sick_action") or "") == "take_sick_leave"
        good_weather = bool(ctx.get("good_weather", True))
        holiday = ctx.get("holiday_plan") or {}
        if sick_leave and not meta.get("rest"):
            segments = self._sick_rest_segments(ctx)
        elif event_kind == "business_trip" and not meta.get("rest"):
            segments = self._business_trip_segments(ctx)
        elif holiday:
            kind = str(holiday.get("kind") or "")
            if kind == "beach":
                segments = self._swim_segments(ctx)
            elif kind == "shopping":
                segments = self._shopping_segments(ctx)
            elif kind == "amusement":
                segments = self._amusement_segments(ctx)
            else:
                segments = self._scenic_segments(ctx)
        elif ctx.get("swim") and not sick and good_weather:
            # 去游泳/海边/水上乐园：整天按玩水安排，衣柜会自动换泳装
            segments = self._swim_segments(ctx)
        elif day_id == "outing":
            # 生病、天气不好就别硬出门，按宅家过
            segments = self._outing_segments(ctx) if (good_weather and not sick) else self._rest_segments(ctx)
        elif day_id == "homebody":
            # 宅家日真的待在家，不再复用“去商场”的室内休息骨架。
            segments = self._homebody_segments(ctx)
        elif meta.get("rest"):
            # 法定节假日/周末优先于加班日，避免节假日小概率还排上班。
            segments = self._rest_segments(ctx)
        elif day_id == "overtime":
            segments = self._workday_segments(ctx, overtime=True)
        else:
            # 工作日的「临时加班」以前只改文案、不改骨架：突发事件写着「今天回不去了」，
            # 日程却还是 18:00 下班回家。这里让骨架真的晚走。
            segments = self._workday_segments(ctx, overtime=(event_kind == "overtime"))
        items = self._expand(segments, ctx)
        items = self._fill_activities(items, ctx)
        items = self._smooth_moods(items, ctx)
        items = self._apply_gift_effects(items, ctx)
        items = self._apply_travel(items, ctx)
        items = self._validate(items, ctx)
        return items

    def _seg(self, start, end, activity, place, zone, category,
             transit="", vehicle="", detail="", effects=None,
             event="", spot="", soothe=False, swim=False, cost_cents=0):
        # 所有骨架格子都必须走 `normalize_schedule_item(strict=True)`：
        # category/zone 拼错一个字母（"Sleep"、"景区"）就当场报错，不会再出现
        # 「日程写着睡觉、她却不睡」这种静默错分支——那正是记忆幻视的来源之一。
        return normalize_schedule_item({
            "start": start, "end": end, "activity": activity, "place": place,
            "zone": zone, "category": category, "transit": transit,
            "vehicle": vehicle, "detail": detail, "effects": effects or {},
            "event": event, "spot": spot, "soothe": soothe,
            "swim": True if swim else False,
            "cost_cents": max(0, int(cost_cents or 0)),
        }, strict=True)

    def _workday_segments(self, ctx, overtime=False):
        return workday_segments(ctx, self._seg, overtime=overtime)

    def _business_trip_segments(self, ctx):
        return business_trip_segments(ctx, self._seg, _with_city)

    def _rest_segments(self, ctx):
        event_kind = (ctx.get("event") or {}).get("kind")
        health = ctx.get("health") or {}
        period = ctx.get("period") or {}
        if health.get("sick"):
            return self._sick_rest_segments(ctx)
        # 痛经是痛经，不是发烧：以前 pain>=8 也走「吃药、量体温、捂汗」，每个月都被写成病号。
        if int(period.get("pain") or 0) >= 8:
            return self._period_rest_segments(ctx)
        # 只有「加班日」才走加班骨架。休息日抽到一个加班事件，不能让整天变成
        # 上班（2026-11-21：周六排了休息日，却因为一个 overtime 事件写满公司）。
        _day_id = str(((ctx.get("day_type") or {}) if isinstance(ctx.get("day_type"), dict) else {}).get("id") or "")
        if (event_kind == "overtime" and _day_id == "overtime"
                and not (ctx.get("meta") or {}).get("rest")):
            return self._overtime_segments(ctx)
        if event_kind == "friend_dinner":
            return self._friend_dinner_segments(ctx)
        if ctx.get("scenic") and ctx.get("good_weather"):
            return self._scenic_segments(ctx)
        return self._indoor_rest_segments(ctx)

    def _scenic_segments(self, ctx):
        return scenic_segments(
            ctx, self._seg, _place_of, _city_of,
            long_holiday=self._is_long_holiday((ctx or {}).get("meta")),
        )

    def _shopping_segments(self, ctx):
        return shopping_segments(ctx, self._seg)

    def _amusement_segments(self, ctx):
        return amusement_segments(ctx, self._seg)

    def _homebody_segments(self, ctx):
        return homebody_segments(ctx, self._seg)

    def _indoor_rest_segments(self, ctx):
        return indoor_rest_segments(ctx, self._seg, _place_of)

    def _sick_rest_segments(self, ctx):
        return sick_rest_segments(ctx, self._seg)

    def _period_rest_segments(self, ctx):
        return period_rest_segments(ctx, self._seg)

    def _overtime_segments(self, ctx):
        return overtime_segments(ctx, self._seg)

    def _friend_dinner_segments(self, ctx):
        return friend_dinner_segments(ctx, self._seg, _place_of)

    # ------------------------------------------------------------------
    # 3. 展开成 24 个整点
    # ------------------------------------------------------------------
    # ------------------------------------------------------------------
    # 3.5 时间因果：地点一变就必须有车程（2026-11-26）
    # ------------------------------------------------------------------
    #: 这些地名尾巴不改变「人在同一处」的判断（会议室/门口/附近…）
    _SPOT_TAIL = ("会议室", "会客室", "门口", "附近", "楼下", "工位", "前台", "食堂",
                  "走廊", "洗手间", "车库", "停车场", "小区门口", "路边")

    @classmethod
    def _same_spot(cls, a, b):
        """两个地点写法是不是同一个地方：公司 vs 公司会议室、家门口 vs 家。"""
        x = str(a or "").strip()
        y = str(b or "").strip()
        if not x or not y:
            return True
        if x == y or x in y or y in x:
            return True
        for tail in cls._SPOT_TAIL:
            if x.endswith(tail):
                x = x[:-len(tail)]
            if y.endswith(tail):
                y = y[:-len(tail)]
        x, y = x.strip("·/ "), y.strip("·/ ")
        if not x or not y:
            return True
        if x == y or x in y or y in x:
            return True
        # 同名前缀够长（比如「贵阳观山湖中国计算智脑集团总部」和「…总部会议室」）
        n = 0
        for c1, c2 in zip(x, y):
            if c1 != c2:
                break
            n += 1
        return n >= 8

    def _travel_item(self, start, end, origin, dest, minutes, km, ctx):
        """一格车程。"""
        driving = bool(ctx.get("has_gift_car"))
        text = ("老周开车带她去%s" if driving else "打车去%s") % dest
        tail = "路上约 %d 分钟" % int(minutes)
        if km:
            tail += "，%.0f 公里" % km
        return {
            "start": fmt_hhmm(start), "end": fmt_hhmm(end),
            "activity": text, "place": "路上", "zone": "road",
            "category": "commute",
            "transit": "drive" if driving else "taxi",
            "vehicle": str(ctx.get("car") or "") if driving else "",
            "detail": "%s → %s，%s" % (origin, dest, tail),
            "spot": "", "swim": False, "soothe": False, "event": "",
            "mood": "平静", "mood_valence": 50.0, "effects": {},
        }

    def _apply_travel(self, items, ctx):
        """相邻两格地点变了却没车程 → 按真实车程插一格（从出发格尾部切）。

        2026-11-26 用户口径：「从 A 去 B 视察要花 X，从 B 回 A 又要多久——要有时间因果」。
        车程一律来自 ``route_time.drive_minutes``（内置表/缓存/估算，不阻塞）。
        """
        try:
            from .route_time import drive_minutes
        except ImportError:
            try:
                from route_time import drive_minutes
            except Exception:
                return items
        city = str(ctx.get("city") or "")
        out = [dict(i) for i in items]
        index = 1
        guard = 0
        while index < len(out) and guard < 40:
            guard += 1
            prev, cur = out[index - 1], out[index]
            if str(prev.get("zone") or "") == "road" or str(cur.get("zone") or "") == "road":
                index += 1
                continue
            a = str(prev.get("place") or "").strip()
            b = str(cur.get("place") or "").strip()
            if self._same_spot(a, b):
                index += 1
                continue
            minutes, km = drive_minutes(a, b, city=city)
            minutes = int(round(minutes or 0))
            if minutes < 15:            # 同一个片区，走两步就到，不占一格
                index += 1
                continue
            p_start, p_end = parse_hhmm(prev.get("start")), parse_hhmm(prev.get("end"))
            c_start, c_end = parse_hhmm(cur.get("start")), parse_hhmm(cur.get("end"))
            if p_end - p_start > minutes + 15:
                trip = self._travel_item(p_end - minutes, p_end, a, b, minutes, km, ctx)
                prev["end"] = fmt_hhmm(p_end - minutes)
                out.insert(index, trip)
            elif c_end - c_start > minutes + 15:
                trip = self._travel_item(p_end, p_end + minutes, a, b, minutes, km, ctx)
                cur["start"] = fmt_hhmm(p_end + minutes)
                out.insert(index, trip)
            else:
                # 两格都挤不出车程：这一格直接就是在路上，下一格再到位
                trip = self._travel_item(c_start, c_end, a, b, minutes, km, ctx)
                trip["activity"] = "在路上（%s → %s）" % (a, b)
                cur.clear()
                cur.update(trip)
                index += 1
                continue
            logger.debug("[amo] 补车程：%s → %s %d 分钟" % (a, b, minutes))
            index += 2
        return out

    def _expand(self, segments, ctx):
        """按段的真实起止时间铺格子。

        2026-11-26（用户口径：任何事都要有时间逻辑）：不再强制整点 24 格——
        车程、视察这种按分钟占位（15:57-16:42），回程才算得出来。
        重叠的段以前面的为准（裁掉已过去的部分），空档按夜里睡觉/白天歇着补。
        """
        slots = []
        for seg in segments:
            start = parse_hhmm(seg.get("start"), 0)
            end = parse_hhmm(seg.get("end"), start + 60)
            if end <= start:
                end = start + 60
            start = max(0, min(24 * 60, start))
            end = max(start, min(24 * 60, end))
            slots.append({
                "start": fmt_hhmm(start),
                "end": fmt_hhmm(end),
                "activity": str(seg.get("activity") or "休息"),
                "place": str(seg.get("place") or ctx["home"]),
                "zone": str(seg.get("zone") or "home"),
                "category": str(seg.get("category") or "rest"),
                "transit": str(seg.get("transit") or ""),
                "vehicle": str(seg.get("vehicle") or ""),
                "detail": str(seg.get("detail") or ""),
                "spot": str(seg.get("spot") or ""),
                "swim": bool(seg.get("swim")),
                "soothe": bool(seg.get("soothe")),
                "event": str(seg.get("event") or ""),
                "effects": dict(seg.get("effects") or {}),
            })
        slots.sort(key=lambda it: parse_hhmm(it.get("start")))
        result = []
        cursor = 0
        for item in slots:
            start = parse_hhmm(item.get("start"))
            end = parse_hhmm(item.get("end"))
            if start < cursor:
                start = cursor
            if end <= start:
                continue
            if start > cursor:
                result.append(self._filler_item(cursor, start, ctx))
            item["start"] = fmt_hhmm(start)
            item["end"] = fmt_hhmm(end)
            result.append(item)
            cursor = end
        if cursor < 24 * 60:
            result.append(self._filler_item(cursor, 24 * 60, ctx))
        return result

    @staticmethod
    def _filler_item(start, end, ctx):
        """空档：夜里算睡觉，白天算歇着。"""
        hour = int(start) // 60
        sleep = hour < 7 or hour >= 23
        return {
            "start": fmt_hhmm(start), "end": fmt_hhmm(end),
            "activity": "睡觉" if sleep else "歇着，没安排事",
            "place": ctx["home"], "zone": "home",
            "category": "sleep" if sleep else "rest",
            "transit": "", "vehicle": "", "detail": "", "spot": "",
            "swim": False, "soothe": False, "event": "", "effects": {},
        }

    # ------------------------------------------------------------------
    # 4. 活动文案（LLM 不可用时的真人化兜底）
    # ------------------------------------------------------------------
    def _fill_activities(self, items, ctx):
        rng = random.Random(int(ctx.get("seed") or 0) ^ 0x9E3779B9)
        prev = ""
        for item in items:
            hour = parse_hhmm(item.get("start")) // 60
            activity = self._activity_for(item, ctx, hour, rng, prev)
            if activity and activity != prev:
                item["activity"] = activity
            if not item.get("detail"):
                item["detail"] = self._detail_for(item, ctx, hour, rng)
            prev = item.get("activity", "")
        return items

    def _activity_for(self, item, ctx, hour, rng, prev):
        zone = str(item.get("zone") or "")
        category = str(item.get("category") or "")
        transit = str(item.get("transit") or "")
        spot = str(item.get("spot") or "")
        base = str(item.get("activity") or "")
        generic = base in ("上班", "休息", "吃午饭", "吃晚饭", "睡觉", "起床吃早餐", "洗澡护肤")
        if not generic:
            return base
        if category == "sleep":
            if hour == 7 and (ctx.get("yesterday") or {}).get("late_night"):
                return "赖床、起不来"
            return "睡觉"
        if zone == "road":
            if transit == "drive":
                bank = ROAD_BANK
            elif transit == "taxi":
                bank = TAXI_BANK
            elif transit == "train":
                return "坐高铁去" + str((ctx.get("event") or {}).get("city") or "外地")
            elif transit == "subway":
                # 2026-11-26（用户口径）：她是大小姐，通勤是老周开车、她坐后排；限行才地铁。
                # 把 transit 也改成 drive，出门这张照片才会是车里/路面，不是车厢。
                bank = COMMUTE_BANK
                bank = COMMUTE_BANK
            else:
                bank = ["在路上"]
            return self._choose(bank, rng, prev)
        if zone == "station":
            return self._choose(STATION_BANK, rng, prev)
        if zone == "hotel":
            return self._choose(HOTEL_BANK, rng, prev)
        if zone == "office":
            # 按类别挑，而不是白名单小时：加班到 18-21 点时也要是「上班」，
            # 不能再落到 REST_BANK 的「瘫在沙发上」。
            if category == "work":
                return self._choose(work_bank_for(ctx.get("world")), rng, prev)
            return "午休" if hour == 13 else self._choose(REST_BANK, rng, prev)
        if zone == "scenic":
            if spot:
                projects = [str(x) for x in ((ctx.get("scenic") or {}).get("projects") or []) if str(x)]
                if projects:
                    project = projects[hour % len(projects)]
                    return "逛" + spot + "：" + project
            return self._choose(SCENIC_BANK, rng, prev)
        if zone == "restaurant":
            if category == "meal":
                bank = self._meal_bank(hour)
                return self._choose(bank, rng, prev)
            return self._choose(["喝杯东西", "坐着歇脚", "刷手机"], rng, prev)
        if zone == "mall":
            return self._choose(INDOOR_BANK, rng, prev)
        if zone == "home":
            if category == "meal":
                # 在家吃 = 厨房做（庄园有厨师/帮厨/管家），不下楼、不点外卖。
                # 2026-11-28 用户口径：「不应该是老周开车、佣人准备饭吗」。
                bank = ()
                try:
                    try:
                        from .household import meal_bank as _home_bank
                    except ImportError:
                        from household import meal_bank as _home_bank  # type: ignore
                    bank, _is_home = _home_bank(hour, home=True)
                except Exception:
                    bank = ()
                if not bank:
                    bank = self._meal_bank(hour)
                return self._choose(list(bank), rng, prev)
            if category == "work":
                return self._choose(work_bank_for(ctx.get("world")), rng, prev)
            if category == "rest":
                return self._choose(REST_BANK, rng, prev)
            if category == "life":
                bank = NIGHT_LIFE_BANK if hour >= 20 else HOME_LIFE_BANK
                return self._choose(bank, rng, prev)
        return base or self._choose(REST_BANK, rng, prev)

    @staticmethod
    def _meal_bank(hour):
        """早饭/午饭/晚饭分开：08:00 不该「下楼吃小馆子」，22:00 也不该吃早餐库。"""
        if hour < 10:
            return BREAKFAST_BANK
        if 10 <= hour < 15:
            return LUNCH_BANK
        return DINNER_BANK

    def _detail_for(self, item, ctx, hour, rng):
        zone = str(item.get("zone") or "")
        category = str(item.get("category") or "")
        activity = str(item.get("activity") or "")

        def pick(bank):
            # 细节只是点缀，不能和这一小时的活动对着干（便利店却说被拉进会议）。
            bank = [word for word in bank if word and not detail_conflicts(activity, word)]
            return self._choose(bank, rng, "")

        if zone == "scenic":
            text = str(item.get("place") or "") + " " + activity
            if any(word in text for word in ("游泳", "泳池", "海边", "沙滩", "水上乐园",
                                             "水世界", "玩水")):
                return pick(list(SWIM_DETAILS))
            return pick([
                "看到猴子抢游客的水", "排队买奶茶排了二十分钟", "停车位找了半小时",
                "拍照拍到手机快没电", "被路边小吃香得走不动",
            ])
        if zone == "road":
            if item.get("vehicle"):
                return pick([
                    "导航一路飘红", "停车场绕了三圈", "被加塞了", "堵在市区路上",
                ])
            return pick(["车上人很多", "差点坐过站", "一路小跑"])
        if zone == "playground":
            return pick(["排队排到腿酸", "过山车下来嗓子都喊哑了", "气球差点飞走",
                         "巡游队伍太热闹了", "买了个发箍戴上"])
        if zone == "office" and category == "work":
            return pick(["改到第三版", "需求又变了", "咖啡续了一杯", "被拉进临时会议"])
        if zone == "restaurant":
            return pick(["多放了点辣", "辣得直吸气", "吃到一半才想起拍照"])
        if zone == "home" and category == "rest":
            return pick(["沙发太舒服了", "剧追到停不下来", "刷到一个好笑的视频"])
        return ""

    def _repair_details(self, items, ctx):
        """模型润色完 activity 之后，把和它对不上的 detail 重新挑一个。

        `build_skeleton()` 里 detail 是按 zone/category 选的，随后 `enrich()`
        会用模型重写 activity；重写后两者可能打架（见 detail_conflicts）。
        这里在润色之后统一兜一次底，保证存下来的骨架自洽。
        """
        rng = random.Random(int(ctx.get("seed") or 0) ^ 0x5EED5)
        for item in items:
            detail = str(item.get("detail") or "").strip()
            if not detail or not detail_conflicts(item.get("activity"), detail):
                continue
            hour = parse_hhmm(item.get("start")) // 60
            item["detail"] = self._detail_for(item, ctx, hour, rng)
        return items


    @staticmethod
    def _choose(bank, rng, prev):
        bank = [item for item in bank if item and item != prev]
        if not bank:
            return ""
        return bank[rng.randrange(len(bank))]

    # ------------------------------------------------------------------
    # 5. 情绪连贯
    # ------------------------------------------------------------------
    def _smooth_moods(self, items, ctx):
        """把七情六欲按小时推一遍，给每一格写心情词和情绪值。

        向量只在内存里平滑，源头和落点都是心流；2026-11-18 之前这里是一套
        独立的十维心情（自己漂移、自己衰减），跟心流两套打架，已整组删除。
        """
        vector = {key: clamp((ctx.get("feel") or {}).get(key, FEEL_BASE[key]))
                  for key in FEEL_KEYS}
        yesterday = ctx.get("yesterday") or {}
        health = ctx.get("health") or {}
        period = ctx.get("period") or {}
        if yesterday.get("late_night"):
            vector["energy"] = min(clamp(vector["energy"] - 16), 38.0)
            vector["joy"] = clamp(vector["joy"] - 6)
            vector["anger"] = clamp(vector["anger"] + 3)
        if health.get("sick"):
            vector["energy"] = clamp(vector["energy"] - 10)
            vector["joy"] = clamp(vector["joy"] - 5)
        if int(period.get("pain") or 0) >= 7:
            vector["energy"] = clamp(vector["energy"] - 8)
            vector["sadness"] = clamp(vector["sadness"] + 5)
        prev_label = ""
        for item in items:
            hour = parse_hhmm(item.get("start")) // 60
            before = dict(vector)
            # 缓慢回落到常态，避免一条直线
            for key in FEEL_KEYS:
                vector[key] = vector[key] + (FEEL_BASE[key] - vector[key]) * 0.05
            if 0 <= hour < 6:
                vector["energy"] = vector["energy"] - 2
            elif 6 <= hour < 9:
                vector["energy"] = vector["energy"] + 2
                vector["joy"] = vector["joy"] + 1
            elif 12 <= hour < 14:
                vector["joy"] = vector["joy"] + 1
            elif 22 <= hour < 24:
                vector["energy"] = vector["energy"] - 2
                vector["love"] = vector["love"] + 1
            for key, delta in (CATEGORY_FEEL.get(item.get("category"), {}) or {}).items():
                if key in vector:
                    vector[key] = vector[key] + delta
            effects = item.get("effects") or {}
            if effects:
                for key, delta in effects.items():
                    if key in vector:
                        try:
                            vector[key] = vector[key] + float(delta)
                        except (TypeError, ValueError):
                            continue
            # 单小时最多变化 8 点；突发事件允许 22 点。
            cap = 22.0 if effects else 8.0
            for key in FEEL_KEYS:
                vector[key] = clamp(vector[key], before[key] - cap, before[key] + cap)
                vector[key] = clamp(vector[key])
            if yesterday.get("late_night") and hour < 18:
                vector["energy"] = min(vector["energy"], 36.0)
            label = self._mood_label(vector)
            if prev_label and not item.get("soothe") and not effects:
                if prev_label in NEGATIVE_LABELS and label in POSITIVE_LABELS:
                    label = prev_label
                elif prev_label in POSITIVE_LABELS and label in NEGATIVE_LABELS:
                    label = prev_label
            item["mood"] = label
            item["mood_valence"] = round(self._mood_valence(vector), 1)
            prev_label = label
        return items

    @staticmethod
    def _mood_label(vector):
        """从七情六欲挑一个词当这一格的心情（词表沿用原来的，方便提示词读）。"""

        def dev(key):
            return float(vector.get(key, FEEL_BASE[key])) - FEEL_BASE[key]

        if dev("anger") >= 16:
            return "烦躁"
        if dev("sadness") >= 15:
            return "委屈" if dev("love") > 6 else "低落"
        if float(vector.get("energy", 65.0)) <= 30:
            return "疲惫"
        if dev("fear") >= 14:
            return "焦虑"
        if dev("joy") >= 12 or dev("surprise") >= 14:
            return "开心"
        if dev("love") >= 14:
            return "黏人"
        return "平静"

    @staticmethod
    def _mood_valence(vector):
        positive = (float(vector.get("joy", 34.0)) + float(vector.get("surprise", 34.0))
                    + float(vector.get("love", 34.0))) / 3.0
        negative = (float(vector.get("anger", 34.0)) + float(vector.get("sadness", 34.0))
                    + float(vector.get("fear", 34.0))) / 3.0
        return clamp(50 + (positive - negative) * 1.2)

    # ------------------------------------------------------------------
    # 6. 物理校验：时间连续 + 不瞬移
    # ------------------------------------------------------------------
    def _validate(self, items, ctx):
        for item in items:
            item.pop("segments", None)
            item["start"] = fmt_hhmm(parse_hhmm(item.get("start"), 0))
            item["end"] = fmt_hhmm(parse_hhmm(item.get("end"), parse_hhmm(item.get("start"), 0) + 60))
            if parse_hhmm(item["end"]) <= parse_hhmm(item["start"]):
                item["end"] = fmt_hhmm(parse_hhmm(item["start"]) + 60)
        # 时间按实际粒度对齐：整点格（24 条）和 30 分钟细格（48 条）都成立。
        # 以前这里按 index*60 硬排，细格会被压回整点、尾部叠成一堆 24:00。
        for index in range(len(items) - 1):
            items[index]["end"] = items[index + 1]["start"]
        # 最后一条必须是 24:00 闭环，不能留 23:59。
        if items:
            items[-1]["end"] = "24:00"

        direct_ok = {
            ("office", "restaurant"), ("restaurant", "office"),
            ("office", "mall"), ("mall", "office"),
            ("scenic", "restaurant"), ("restaurant", "scenic"),
            ("restaurant", "hotel"), ("hotel", "restaurant"),
            ("restaurant", "home"), ("home", "restaurant"),
            ("home", "hospital"), ("hospital", "home"), ("hospital", "hospital"),
            ("mall", "restaurant"), ("restaurant", "mall"),
            ("station", "restaurant"), ("restaurant", "station"),
            ("home", "home"), ("office", "office"), ("scenic", "scenic"),
            ("restaurant", "restaurant"), ("mall", "mall"), ("playground", "playground"),
            ("playground", "restaurant"), ("restaurant", "playground"),
        }
        for index in range(1, len(items)):
            prev = items[index - 1]
            cur = items[index]
            prev_zone = str(prev.get("zone") or "")
            zone = str(cur.get("zone") or "")
            if not zone or not prev_zone or zone == prev_zone:
                continue
            if prev_zone == "road" or zone == "road":
                continue
            if (prev_zone, zone) in direct_ok:
                continue
            # 2026-11-26：两处其实在同一片区（机房 → 隔壁工地），就别硬改成「在路上」，
            # 车程由 _apply_travel 按真实分钟补；只有真的隔了一段路才拦。
            try:
                if self._same_spot(prev.get("place"), cur.get("place")):
                    continue
                try:
                    from .route_time import drive_minutes as _drive_minutes
                except ImportError:
                    from route_time import drive_minutes as _drive_minutes
                _mins = _drive_minutes(str(prev.get("place") or ""),
                                      str(cur.get("place") or ""),
                                      city=str(ctx.get("city") or ""))[0]
                if _mins < 15:
                    continue
            except Exception:
                pass
            # 兜底修复：把当前小时改成“在路上”，下一小时再到达。
            original_place = str(cur.get("place") or "")
            cur["activity"] = "从%s赶去%s" % (prev.get("place") or "上一个地方", original_place)
            cur["place"] = "路上"
            cur["zone"] = "road"
            cur["category"] = "commute"
            cur["transit"] = cur.get("transit") or ("drive" if ctx.get("car") else "taxi")
            cur["vehicle"] = cur.get("vehicle") or (ctx.get("car") if cur["transit"] == "drive" else "")
            cur["detail"] = "上一小时还在%s，这一小时在路上" % (prev.get("place") or "别处")
            cur["effects"] = {}
        # 短途往返：两头在同一个地方（比如公司在同一栋楼），中间那一格不该是"在路上"。
        # 现实里就是下楼吃个饭，不画成"上一秒公司、下一秒街上"。
        for index in range(1, len(items) - 1):
            cur = items[index]
            if str(cur.get("zone") or "") != "road":
                continue
            prev_place = str(items[index - 1].get("place") or "").strip()
            next_place = str(items[index + 1].get("place") or "").strip()
            if not prev_place or prev_place != next_place:
                continue
            next_zone = str(items[index + 1].get("zone") or "")
            if next_zone not in ("restaurant", "office", "mall", "home"):
                continue
            cur["zone"] = next_zone
            cur["place"] = next_place
            cur["category"] = items[index + 1].get("category") or cur.get("category") or "work"
            cur["activity"] = ("在公司附近吃口饭" if next_zone == "restaurant"
                               else "回工位接着忙")
            cur["detail"] = "就在同一处附近，没走远"
            cur["transit"] = ""
            cur["vehicle"] = ""

        # 文案说人已经到家（洗漱/睡衣/被窝），那就不是"在路上"。
        # 否则会出现「她说在家换睡衣，照片背景是地铁站」。
        home_words = ("到家", "在家", "进屋", "洗漱", "睡衣", "被窝", "躺下", "回到小窝")
        home_place = str(ctx.get("home") or "").strip()
        for item in items:
            if str(item.get("zone") or "") != "road":
                continue
            text = str(item.get("activity") or "") + str(item.get("detail") or "")
            if not any(word in text for word in home_words):
                continue
            item["zone"] = "home"
            if home_place:
                item["place"] = home_place
            item["category"] = "rest"
            item["transit"] = ""
            item["vehicle"] = ""

        # 文案在吃饭/喝东西，那就不是"在路上"：路上那一格只该有通勤。
        eat_words = ("吃", "喝", "饭", "面", "汤", "外卖", "奶茶", "咖啡", "粉")
        for item in items:
            if str(item.get("zone") or "") != "road":
                continue
            text = str(item.get("activity") or "") + str(item.get("detail") or "")
            if not any(word in text for word in eat_words):
                continue
            if any(word in text for word in ("地铁", "公交", "车厢", "站台", "打车", "开车")):
                continue
            item["zone"] = "restaurant"
            item["category"] = "meal"
            item["transit"] = ""
            item["vehicle"] = ""

        # 周末景区必须体现资产绑定：开车、堵车、找停车位。
        if (ctx.get("meta") or {}).get("rest") and ctx.get("scenic") and ctx.get("good_weather"):
            scenic_items = [item for item in items if item.get("zone") == "scenic"]
            if scenic_items:
                first = scenic_items[0]
                if not first.get("vehicle"):
                    first["vehicle"] = ctx.get("car") or ""
                if "停车" not in str(first.get("detail") or ""):
                    first["detail"] = (str(first.get("detail") or "") + "；老周开车来的，停车位找了很久").strip("；")
        return items

    #: 文案里出现这些词 = 人在路上，区域必须是 road
    TRAVEL_WORDS = (
        "地铁", "公交", "车厢", "车上", "车站", "站台", "打车", "出租车", "开车",
        "骑车", "骑行", "路上", "通勤", "换乘", "高铁", "火车", "飞机", "赶去", "赶往",
    )
    #: 「到家 / 在家」这类不是“在路上”，别误判
    AT_HOME_WORDS = ("到家", "在家", "家里", "进门", "躺沙发", "被窝")

    @staticmethod
    def _guess_transit(text):
        body = str(text or "")
        if "地铁" in body:
            return "subway"
        if "公交" in body:
            return "bus"
        if "打车" in body or "出租车" in body:
            return "taxi"
        if "开车" in body:
            return "drive"
        if "高铁" in body or "火车" in body:
            return "train"
        if "飞机" in body:
            return "plane"
        return "walk"

    @classmethod
    def _align_zone_with_activity(cls, items):
        """文案和区域对齐：她说“在地铁上”，生图取景就必须是车厢/路面，不能是办公室。

        LLM 只被允许改 activity（骨架的 zone/place 不让它动），所以它写出
        「地铁上听着歌晃回家」时 zone 还停在 office —— 照片就成了办公室。
        """
        for item in items or []:
            zone = str(item.get("zone") or "")
            place = str(item.get("place") or "")
            act = str(item.get("activity") or "")
            if zone == "road":
                # 区域是“路上”，地点也统一成“路上”，别出现“地铁上 / 写字楼”并存
                if place and place != "路上":
                    item["place"] = "路上"
                if not item.get("transit"):
                    item["transit"] = cls._guess_transit(act)

                # 文案写“在工位/在家/沙发/看电视”但区域是路上：改成真正的通勤文案。
                # “下班回家/到家/路上”这类本来就是路上，不误伤。
                if (str(item.get("category") or "") == "commute"
                        and any(w in act for w in ("工位", "公司", "办公室", "沙发", "床", "电视", "厨房", "被窝", "家"))
                        and not any(w in act for w in ("回家", "到家", "路上", "地铁", "公交", "开车", "打车", "走", "车厢", "等车"))):
                    transit = str(item.get("transit") or "")
                    item["activity"] = {
                        "subway": "挤地铁去公司", "drive": "老周开车送她去公司",
                        "bus": "坐公交去公司", "walk": "走路去公司",
                        "taxi": "打车去公司",
                    }.get(transit) or "赶路去公司"
                    item["detail"] = ""
                continue
            if zone in ("home", "hospital"):
                continue
            if not any(word in act for word in cls.TRAVEL_WORDS):
                continue
            if any(word in act for word in cls.AT_HOME_WORDS):
                continue
            item["place"] = "路上"
            item["zone"] = "road"
            item["transit"] = item.get("transit") or cls._guess_transit(act)
            item["vehicle"] = item.get("vehicle") or ("地铁" if item["transit"] == "subway" else "")
            item["effects"] = {}
        return items

    # ------------------------------------------------------------------
    # 7. 让模型只改写 activity，不改物理骨架
    # ------------------------------------------------------------------
    async def enrich(self, umo, ctx, items, llm):
        if not items or llm is None or not self.p.cfg_bool("schedule_llm_backbone", True):
            return items
        lines = []
        for item in items:
            lines.append("%s-%s｜%s｜%s｜%s｜%s" % (
                item.get("start"), item.get("end"), item.get("place"),
                item.get("category"), item.get("zone"), item.get("activity"),
            ))
        event = ctx.get("event") or {}
        scenic = ctx.get("scenic") or {}
        day_type = ctx.get("day_type") or {}
        day_fact = ""
        meta_info = ctx.get("meta") or {}
        rest_day = bool(meta_info.get("rest"))
        try:
            day_obj = date.fromisoformat(str(ctx.get("day") or "")[:10])
            weekday_label = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")[day_obj.weekday()]
            # 「上不上班」只按日历说，不再按星期几自己推：
            # 以前周中一律说「法定工作日，她需要上班」，宅家日/节假日的骨架就被写歪了。
            if rest_day:
                holiday_name = str(meta_info.get("holiday") or "").strip()
                day_kind = ("日历上是休息日（%s），放假，不上班" % holiday_name) if holiday_name \
                    else "日历上是休息日，不用上班"
            else:
                day_kind = "日历上是工作日，她要上班（调休补班也算工作日）"
            day_fact = "【绝对事实】今天是%s，%s。\n" % (weekday_label, day_kind)
        except Exception:
            day_fact = ""
        day_type_line = ""
        if str(day_type.get("guide") or "").strip():
            day_type_line = "今天是「%s」：%s\n" % (
                str(day_type.get("name") or "普通一天"), str(day_type["guide"]).strip(),
            )
        # 文案必须跟着骨架的 zone 走：骨架里没有公司，就不许写公司/工位/开会，
        # 否则日程写着上班、place/zone 写在家，出图就成了在家拍的（2026-11-23）。
        has_work_slot = any(
            str(item.get("zone") or "") in ("office", "work")
            or str(item.get("category") or "") == "work"
            for item in items
        )
        if has_work_slot:
            zone_rule = ("5. 按骨架的 zone 写：zone=office 写公司/工位上的事，"
                         "zone=road 写通勤路上，zone=home 写家里的事，不许跨区；\n")
        else:
            zone_rule = ("5. 今天骨架里没有公司，全部按骨架的 zone 写（home 写家里的事、"
                         "road 写路上），不许出现公司、工位、办公室、开会、同事、加班、通勤这些词；\n")
        system = "你是角色的日程文案助手。只输出 JSON 数组，不要输出解释。"
        prompt = (
            "角色设定：\n" + _brief_world(ctx.get("world") or {}) + "\n"
            "今天：%s，%s；天气：%s。\n"
            "%s"
            "%s"
            "情绪：%s；生理期：%s；身体：%s；昨日：%s\n"
            "突发事件：%s\n"
            "景区：%s\n"
            "下面是已经固定好的 24 个整点骨架（时间｜地点｜类别｜区域｜当前文案）：\n%s\n"
            "请为每个小时写一句更真实、更有生活感的 activity（8-22字），"
            "输出要求：\n"
            "1. 顺序对应，正好 24 个字符串；\n"
            "2. 时间、地点、类别按骨架原样保留；睡觉就写睡觉，在路上就写在路上；\n"
            "3. 在景区要写具体项目；写清是老周开车（她坐后排），路上堵车/找停车位；\n"
            "3b. 她不用自己开车、不挤地铁：出门一律老周开车（她坐后排），到家/到公司下车即可；\n"
            "3c. 在家吃的饭一律由厨房做（郑师傅掌勺、李姐帮厨、陈姨安排），"
            "不写她下楼吃、点外卖、自己下厨；在外面吃才写餐馆；\n"
            "4. 相邻两小时用不同的句子；写生活本身，不写“日程”“AI”“模型”这些词；\n"
            "%s"
            "6. 只输出 JSON 数组，例如 [\"...\",\"...\"]。"
        ) % (
            ctx.get("day"), (ctx.get("meta") or {}).get("label") or "普通一天",
            _weather_text(ctx.get("weather") or {}),
            day_type_line,
            day_fact,
            _mood_text(ctx.get("feel") or {}),
            (ctx.get("period") or {}).get("phase", ""),
            (ctx.get("health") or {}).get("status", "健康"),
            (ctx.get("yesterday") or {}).get("note") or "正常",
            event.get("note") or "无",
            _scenic_text(scenic),
            "\n".join(lines),
            zone_rule,
        )
        data = await self.llm_json(llm, umo, system, prompt, timeout=15)
        if isinstance(data, dict):
            data = data.get("activities") or data.get("items") or data.get("schedule")
        if not isinstance(data, list) or len(data) != len(items):
            # JSON 不合法：保留冷数据，空 activity 用中性事实兜底，不抛异常
            for item in items:
                if not str(item.get("activity") or "").strip():
                    item["activity"] = str(SAFE_EVENT.get("event") or "日常发呆")
                    item.setdefault("category", "rest")
            return items
        for item, value in zip(items, data):
            text = ""
            detail = ""
            if isinstance(value, dict):
                text = str(value.get("activity") or "").strip()
                detail = str(value.get("detail") or "").strip()
            else:
                text = str(value or "").strip()
            text = re.sub(r"\s+", " ", text)
            if 2 <= len(text) <= 30:
                item["activity"] = text
            if detail and len(detail) <= 40:
                item["detail"] = detail
        # activity 被改写过，detail 可能已经和它对不上，统一按新活动重新挑。
        self._align_zone_with_activity(items)
        return self._repair_details(items, ctx)

    @staticmethod
    def _fix_home_diary(text):
        """物理边界：他不在现场，绝不能把手机聊天改写成“当面”。保留原文。"""
        return str(text or "")

    @staticmethod
    def _interaction_material(lines):
        """把「他：/我：」聊天行整理成自然读的互动素材，空列表返回空串。"""
        try:
            rows = []
            for line in lines or []:
                text = str(line or "").strip()
                if not text or "：" not in text:
                    continue
                who, said = text.split("：", 1)
                said = said.strip().strip('"“”')
                if not said:
                    continue
                rows.append(("他" if who.strip() != "我" else "我", said))
            if not rows:
                return ""
            sentences = []
            index = 0
            while index < len(rows) and len(sentences) < 8:
                who, said = rows[index]
                if who == "他":
                    nxt = rows[index + 1] if index + 1 < len(rows) else None
                    if nxt and nxt[0] == "我":
                        sentences.append('老公对你说：“%s”。你回复了：“%s”。' % (said, nxt[1]))
                        index += 2
                        continue
                    sentences.append('老公说：“%s”。' % said)
                else:
                    sentences.append('你说：“%s”。' % said)
                index += 1
            return "在约会期间，" + "".join(sentences[-6:])
        except Exception:
            return ""

    @staticmethod
    def _fix_date_diary(text):
        """约会这一小时：把「隔着手机/一个人」的穿帮措辞改回面对面。"""
        body = str(text or "")
        for old, new in (
            ("在微信上跟老公聊了几句", "跟他面对面聊了几句"),
            ("微信上跟老公聊", "当面跟他聊"),
            ("在微信上", "面对面"),
            ("微信里", "当面"),
            ("隔着屏幕", "面对面"),
            ("我一个人", "我们"),
            ("一个人点了", "我们点了"),
            ("一个人点", "我们点"),
            ("一个人吃", "我们一起吃"),
            ("一个人", "我"),
            ("等他回来", "他就在我对面"),
        ):
            body = body.replace(old, new)
        return body

    async def llm_json(self, llm, umo, system, prompt, fallback=None, timeout=20):
        """大模型返回 JSON：解析失败→严格重试一次→仍失败返回 fallback，绝不抛异常。"""
        raw = ""
        try:
            raw = await asyncio.wait_for(llm.chat_raw(umo, system, prompt), timeout=timeout)
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.llm_json.first", _amo_exc)
        data = json_extract(raw)
        if data is not None:
            return data
        logger.warning("[JSON_PARSE] 首次 JSON 解析失败，触发严格重试")
        try:
            strict = prompt + "\n\n刚才格式错了，请严格只输出 JSON，不要任何其他文字！"
            raw = await asyncio.wait_for(llm.chat_raw(umo, system, strict), timeout=timeout)
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.llm_json.retry", _amo_exc)
            return fallback
        data = json_extract(raw, fallback)
        if data is None:
            logger.warning("[JSON_PARSE] 严格重试仍失败，使用安全兜底")
        return data

    # ------------------------------------------------------------------
    # 8. 动态日记
    # ------------------------------------------------------------------
    @staticmethod
    def _diary_contradicts(prev_diary, diary):
        """粗校验：上一小时已经写他进门/在家，这一小时不能又写他还没回来。"""
        prev = str(prev_diary or "")
        cur = str(diary or "")
        if not prev or not cur:
            return False
        at_home = (
            bool(_his_re().search(prev))
            and any(word in prev for word in ("进门", "在家", "回来", "到家", "身边", "陪你", "坐在"))
        )
        alone = any(word in cur for word in ("还没回来", "不在家", "没回来", "一个人", "等他回来"))
        return bool(at_home and alone)

    async def generate_diary(self, umo, ctx, item, prev_item, next_item, llm, prev_diary=""):
        if llm is None:
            return {
                "diary": self.fallback_diary(ctx, item, prev_item),
                "mood": item.get("mood") or "平静",
                "place": item.get("place") or "",
                "activity": item.get("activity") or "",
            }

        def _parse(raw):
            text = ""
            data = json_extract(raw)
            if isinstance(data, dict):
                text = str(data.get("diary") or data.get("text") or "").strip()
            elif isinstance(data, str):
                text = data.strip()
            if not text:
                text = str(raw or "").strip()
            return self._clean_diary(text)

        system = "你就是这个角色本人。你在写只给自己看的第一人称小日记，只输出 JSON。"
        # 约会这一小时只可能是「老公」：模型偶尔会把名单里的别人串进来，先挡掉
        if "老公" in str(item.get("activity") or ""):
            _others = ("柳如烟", "白凝冰", "季博达", "方圆", "沈幼微")
            _orig_parse = _parse

            def _parse(raw):
                text = _orig_parse(raw)
                for other in _others:
                    text = text.replace(other, "老公")
                return text
        _act = str(item.get("activity") or "")
        is_date = (str(item.get("category") or "") == "social"
                   and ("老公" in _act or "约会" in _act))
        prompt = self._diary_prompt(ctx, item, prev_item, next_item, prev_diary,
                                    together=is_date)
        _chat_hour = [str(x) for x in (ctx.get("chat_lines_hour") or []) if str(x).strip()]
        _material = self._interaction_material(_chat_hour)
        if _material:
            prompt += ("\n\n【互动素材】" + _material + "\n"
                       "请结合你们的真实聊天记录和物理场景，以第一人称写小日记。"
                       "严禁凭空捏造没说过的话，情感必须基于这些原话；聊天只能当素材，不要逐句复述。\n")
        else:
            prompt += ("\n\n【互动素材】这一小时你们没怎么发消息，可能只是在默默吃饭/待着。"
                       "不要编造对话，只写物理场景和情绪（比如「虽然没怎么说话，但一起吃饭很安心」）。\n")
        if not is_date:
            prompt += ("\n\n【物理边界·最高优先级】他此刻不在你身边、不在这个房间里。"
                       "必须至少写一次“一个人/手机屏幕/微信/语音”这类独处细节，让读者看出你是一个人；"
                       "严禁写他翻身、抱你、坐在旁边、屋里两个人。"
                       "想他可以写想，但不能写成他就在现场。\n")
        if is_date:
            prompt += (
                "\n\n【这一小时你们在一起】你和老公正在约会，他就在你对面/身边。"
                "只能写面对面的细节（给他夹菜、看他吃、一起说话）。"
                "严禁出现「微信/手机/视频/隔着屏幕/一个人/等他回来」这类措辞，"
                "你们不是隔着手机聊天。\n"
            )
        raw = ""
        try:
            raw = await asyncio.wait_for(llm.chat_raw(umo, system, prompt), timeout=60)
            # 下一小时的关键词漏进这一小时：直接截断，绝不把两段拼成一段
            _text = _parse(raw)
            _next_act = str((next_item or {}).get("activity") or "")
            _cur_act = str(item.get("activity") or "")
            for _kw in ("火锅", "逛街", "喜酒", "聚餐", "电影", "商场", "医院", "景区", "火锅店"):
                if _kw in _next_act and _kw not in _cur_act and _kw in _text:
                    _idx = _text.find(_kw)
                    _cut = max(_text.rfind("。", 0, _idx), _text.rfind("，", 0, _idx))
                    if _cut > 20:
                        raw = _text[:_cut + 1]
                        if raw.endswith("，"):
                            raw = raw[:-1] + "。"
                    break
        except Exception as _amo_exc:
            _note_swallowed("schedule_engine.ScheduleEngine.generate_diary", _amo_exc)
            raw = ""
        diary = _parse(raw)
        # 防幻视最后一道闸：日程/小日记里不许出现他（8.8.0 规则）。约会那种
        # 「两个人在一块」的格子例外——那一格本来就写他在场。
        if not is_date and diary:
            diary = solo_text(diary, diary)
            if has_him(diary):
                diary = self.fallback_diary(ctx, item, prev_item)
        if is_date:
            diary = self._fix_date_diary(diary)
        elif (any(w in str(item.get("place") or "") for w in ("家", "卧室", "客厅", "沙发", "床"))
              or any(w in diary for w in ("到家", "沙发", "睡衣", "卧室", "被窝"))):
            diary = self._fix_home_diary(diary)
        if len(diary) < 20:
            # JSON 崩了/被截断：严格重试一次，再不行走本地兜底，绝不让这一小时空白
            try:
                strict = prompt + "\n\n刚才格式错了，请严格只输出 JSON，不要任何其他文字！"
                raw = await asyncio.wait_for(llm.chat_raw(umo, system, strict), timeout=30)
                diary = _parse(raw)
            except Exception as _amo_exc:
                _note_swallowed("schedule_engine.generate_diary.retry", _amo_exc)
        if len(diary) < 20:
            diary = self.fallback_diary(ctx, item, prev_item)
        facts = ctx.get("fact_pool") or []
        if facts:
            diary = self._sanitize_hour_diary(diary, facts)
            if not await self._audit_hour_diary(diary, facts, llm, umo):
                strict = (prompt + "\n【审计失败】上一版写了事实列表之外的事，必须严格只写白名单里的事件。\n")
                try:
                    raw = await asyncio.wait_for(llm.chat_raw(umo, system, strict), timeout=60)
                    diary = self._sanitize_hour_diary(_parse(raw), facts)
                except Exception as _amo_exc:
                    _note_swallowed("schedule_engine.ScheduleEngine.generate_diary.audit", _amo_exc)
        if prev_diary and self._diary_contradicts(prev_diary, diary):
            strict = (
                prompt
                + "\n【硬性续写】上一小时日记里他已经进门/在家/在陪你。"
                + "这一小时必须承接这个事实，不能写他还没回来、不在家、你一个人。"
            )
            try:
                raw = await asyncio.wait_for(llm.chat_raw(umo, system, strict), timeout=60)
            except Exception as _amo_exc:
                _note_swallowed("schedule_engine.ScheduleEngine.generate_diary", _amo_exc)
                raw = ""
            retried = _parse(raw)
            if retried and len(retried) >= 20 and not self._diary_contradicts(prev_diary, retried):
                diary = retried
            else:
                diary = self.fallback_diary(ctx, item, prev_item)
        return {
            "diary": diary,
            "mood": item.get("mood") or "平静",
            "place": item.get("place") or "",
            "activity": item.get("activity") or "",
        }

    def diary_presence_rules(self, together=False):
        return diary_presence_rules(together)

    def _diary_prompt(self, ctx, item, prev_item, next_item, prev_diary="", together=False):
        event = ctx.get("event") or {}
        scenic = ctx.get("scenic") or {}
        (prev_text, next_text, prev_diary_text, car_line,
         asset_line, worn_line, gift_line, outfit_line) = _diary_material_lines(
            self, ctx, item, prev_item, next_item, prev_diary)
        try:
            from .amo_immersion_guard import diary_prompt_block as _immersion_block
        except ImportError:
            from amo_immersion_guard import diary_prompt_block as _immersion_block
        _immersion_extra = _immersion_block(item)
        try:
            from .amo_diary_guard import fact_rules
        except ImportError:
            from amo_diary_guard import fact_rules
        _base = (
            fact_rules(together) + "\n"
            + _immersion_extra + "\n"
            + diary_presence_rules(together)
            + "角色设定：\n" + _brief_world(ctx.get("world") or {}) + "\n"
            "今天：%s，%s；天气：%s；所在地：%s。\n"
            "身体：%s；生理期：%s；昨日：%s。\n"
            "此刻十维情绪：%s。\n"
            "上一小时：%s\n"
            "上一小时已经写下的小日记（必须承接，不能矛盾）：\n%s\n"
            "这一小时：%s-%s，%s，在%s（%s），心情%s。\n"
            "【事实唯一·最高优先级】这一小时只发生这一件事：地点=%s、动作=%s。"
            "如果这条日程刚被约会/新事件覆盖，之前写过、想过的一切作废，"
            "绝不许把旧场景（比如在家做饭、屋里香不香）和现在的地点动作拼在一起；"
            "地点和动作只能有一个，冲突时以后者为准。\n"
            "下一小时：%s\n"
            "【时间边界·必须遵守】这一小时只写到本段结束（%s）为止；之后发生的事、下一小时的日程，"
            "一个字都不能写进来，哪怕只隔几分钟，也不能把两段拼成一段。\n"
            "突发事件：%s\n"
            "景区信息：%s\n"
            "%s\n"
            "%s\n"
            "%s\n"
            "%s\n"
            "%s\n"
            "请写一段 120-260 字的第一人称小日记，要求：\n"
            "1. 只写这一小时；\n"
            "2. 写清交通方式（老周开车/打车/走路）、具体干了什么、吃了什么、遇到什么趣事；\n"
            "2b. 在家吃饭一律写厨房做的（郑师傅/李姐/陈姨），不写下楼吃、点外卖；"
            "她不会自己开车；\n"
            "3. 情绪从上一小时自然延续（郁闷/生气不会无缘无故变成开心/兴奋）；\n"
            "4. 如果是周末开车出去玩，要提到车、堵车、停车位；\n"
            "5. 口语化、生动，像真人发朋友圈，不写旁白，也不提日程/AI/模型；\n"
            "6. 承接上一小时日记：上一小时出现的人、地点、动作保持一致；\n"
            "9. 只写这一小时的新细节，不重复上一小时说过的整段；\n"
            "10. 只写这一小时（今天）：不许写明天、不许把昨天的事当今天；"
            "这一小时只有给出的日程是事实，不能添加电话/见面/新买衣服；\n"
            "11. 聊天只能间接转述（“他提醒我多喝水”），不许主客体反转；"
            "这一小时素材没有的互动不能写，平台名统一写“微信”；\n"
            "12. 这一小时只写当下：可以写体感/即时情绪，禁止跨时空想念（吃包子突然好想老公）、"
            "禁止虚构不在场的人（想让他送热水但他没来）、禁止总结句（今天真倒霉）；\n"
            "13. 这一小时无事发生就写“发呆、放空、刷剧”或留空，不要没话找话；\n"
            "14. 睡眠时段（23:30-07:00）不写小时日记；\n"
            "15. 允许复合情绪（发工资开心但感冒难受），别把情绪写扁平；\n"
            "16. 不许把账本金额抄进日记：基本/奖金/扣款/实发/余额的具体数字一律不写，"
            "只写“发工资了”“余额多了一点”这种感受；\n"
            "17. 这一小时日程里只有你一个人：不要出现你的恋人/老公/他，也不要写他来陪你、"
            "他打电话来、他抱着你——想他可以，但不能写成他在现场；\n"
            "18. 只输出 JSON：{\"diary\":\"...\"}。"
        ) % (
            ctx.get("day"), (ctx.get("meta") or {}).get("label") or "普通一天",
            _weather_text(ctx.get("weather") or {}), ctx.get("location") or _city_of(ctx) or "未设置",
            (ctx.get("health") or {}).get("status", "健康"),
            (ctx.get("period") or {}).get("phase", ""),
            (ctx.get("yesterday") or {}).get("note") or "正常",
            _mood_text(ctx.get("feel") or {}),
            prev_text,
            prev_diary_text,
            item.get("start"), item.get("end"), item.get("activity"),
            item.get("place"), item.get("zone"), item.get("mood") or "平静",
            item.get("place"), item.get("activity"),
            next_text,
            item.get("end"),
            event.get("note") or "无",
            _scenic_text(scenic),
            car_line,
            asset_line,
            worn_line,
            gift_line,
            outfit_line,
        )
        facts = ctx.get("fact_pool") or []
        if facts:
            lines = []
            for idx, fact in enumerate(facts[:40], 1):
                if isinstance(fact, dict):
                    type_text = str(fact.get("type") or "事实")
                    detail = str(fact.get("detail") or "")
                    ledger_like = (any(key in type_text for key in ("收入", "支出", "账单"))
                                   or "发工资" in detail)
                    if ledger_like:
                        # 账本金额不进日记：只留一句人话，情绪让模型自己写
                        if "工资" in detail:
                            detail = "发工资了，账户里多了一笔钱"
                        elif "支出" in type_text:
                            detail = "花了一笔钱（具体吃什么、买什么看日程）"
                        else:
                            detail = "有一笔进出账"
                        type_text = "账本"
                    lines.append("%d. [%s] %s%s" % (
                        idx, type_text,
                        (str(fact.get("time")) + " ") if fact.get("time") and type_text != "账本" else "",
                        detail))
            _base += ("\n【今天真实发生的事件（白名单）】\n" + "\n".join(lines)
                      + "\n你只能扩写上面的内容。上面没写的电话、见面、去公司、聊天，一律不能写。\n")
        return _base

    @staticmethod
    def _sanitize_hour_diary(text, facts):
        value = str(text or "")
        joined = " ".join(str(f.get("detail") or "") for f in facts if isinstance(f, dict))
        has_phone = any(w in joined for w in ("电话", "通话", "语音"))
        has_meet = any(w in joined for w in ("见面", "约会", "来家里", "一起吃饭"))
        has_chat = any(w in joined for w in ("聊天", "微信", "飞书"))
        location = ""
        for f in facts:
            if isinstance(f, dict) and f.get("type") == "状态" and "现在在" in str(f.get("detail") or ""):
                location = str(f.get("detail") or "")
        home = "家" in location
        sentences = re.split(r"(?<=[。！？!?\n])", value)
        kept = []
        for sentence in sentences:
            s = sentence.strip()
            if not s:
                continue
            if not has_phone and any(w in s for w in ("打电话", "通电话", "听见他声音", "视频通话")):
                continue
            if not has_meet and any(w in s for w in ("他抱我", "他摸我头", "他来找我", "一起吃饭")):
                continue
            if not has_chat and any(w in s for w in ("微信", "飞书")) and any(
                    w in s for w in ("聊", "回", "消息", "说")):
                continue
            if home and any(w in s for w in ("工位", "公司", "地铁")):
                continue
            kept.append(s)
        return "".join(kept)[:600]

    async def _audit_hour_diary(self, text, facts, llm, umo):
        if not facts or llm is None:
            return True
        lines = "\n".join(str(f.get("detail") or "") for f in facts if isinstance(f, dict))[:2500]
        prompt = ("事实列表：\n%s\n\n日记：\n%s\n\n日记里有没有事实列表之外的动作或事件？"
                  "只输出 True 或 False。" % (lines, text))
        try:
            answer = await asyncio.wait_for(
                llm.chat_raw(umo, "你是事实审计员，只输出 True/False。", prompt), timeout=25)
            return "false" not in str(answer or "").lower()
        except Exception:
            return True

    @staticmethod
    def _clean_diary(text):
        text = str(text or "").strip()
        if text.startswith("{"):
            _data = json_extract(text)
            if isinstance(_data, dict):
                text = str(_data.get("diary") or _data.get("text") or "").strip()
            if text.startswith("{"):
                _m = re.search(r'"diary"\s*:\s*"(.*)"\s*}\s*$', text, re.S)
                if _m:
                    text = _m.group(1)
            text = text.strip().strip('"').strip("“”").strip()
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
        text = re.sub(r"\s*```$", "", text)
        text = text.strip().strip('"').strip("“”").strip()
        for prefix in ("小日记：", "日记：", "今天的日记：", "今天："):
            if text.startswith(prefix):
                text = text[len(prefix):].strip()
        text = re.sub(r"[ \t]+", " ", text)
        text = text.replace("\r", "").strip()
        return text[:600]

    def fallback_diary(self, ctx, item, prev_item=None):
        """模型不可用时的兜底日记，仍然保证交通、地点、心情和趣事。"""
        place = str(item.get("place") or "家")
        activity = str(item.get("activity") or "待着")
        mood = str(item.get("mood") or "平静")
        weather = _weather_text(ctx.get("weather") or {})
        detail = str(item.get("detail") or "").strip()
        zone = str(item.get("zone") or "")
        car = str(item.get("vehicle") or "")
        event = ctx.get("event") or {}
        parts = []
        if zone == "road":
            if car:
                parts.append("这小时我开着%s在路上，%s。" % (car, detail or "堵得我有点烦"))
            elif item.get("transit") == "train":
                parts.append("这小时我在高铁上，%s。" % (detail or "看着窗外的田发呆"))
            else:
                parts.append("这小时我在路上，%s。" % (detail or "挤得脚都没地方放"))
        elif zone == "scenic":
            parts.append("这小时我在%s，%s。" % (place, activity))
            if detail:
                parts.append(detail + "。")
        elif zone == "office":
            parts.append("这小时我在%s，%s。" % (place, activity))
        elif zone == "home" and item.get("category") == "sleep":
            parts.append("这小时我睡得迷迷糊糊的，连梦都做得断断续续。")
        else:
            parts.append("这小时我在%s，%s。" % (place, activity))
        if event.get("kind") != "none" and (item.get("event") or item.get("effects")):
            parts.append("今天这事来得太突然了，%s。" % (event.get("note") or ""))
        parts.append("外面%s，我心情%s，%s。" % (
            weather, mood, detail or "只想安安静静待一会儿",
        ))
        return "".join(parts)[:600]


def _brief_world(world):
    world = world or {}
    hobbies = world.get("hobbies") or []
    if isinstance(hobbies, list):
        hobbies = "、".join([str(item) for item in hobbies])
    return "\n".join([
        "名字：%s；年龄：%s；城市：%s；职业：%s；任职：%s" % (
            world.get("name", ""), world.get("age", ""), world.get("city", ""),
            world.get("occupation", ""), world.get("workplace", ""),
        ),
        "性格：%s；爱好：%s；日常：%s" % (
            world.get("personality", ""), hobbies, world.get("daily_life", ""),
        ),
    ])


def _weather_text(weather):
    weather = weather or {}
    city = str(weather.get("city") or "").strip()
    prefix = (city + " ") if city else ""
    return "%s%s %s℃" % (prefix, weather.get("text", ""), weather.get("temp", ""))


def _mood_text(feel):
    """给提示词用的一行七情六欲（不再是十个中文维度的裸数字）。"""
    feel = feel or {}

    def value(key):
        try:
            return int(round(float(feel.get(key, FEEL_BASE.get(key, 34.0)) or 0)))
        except (TypeError, ValueError):
            return int(round(FEEL_BASE.get(key, 34.0)))

    return ("喜%d 怒%d 哀%d 惧%d 爱%d 精力%d 饿%d"
            % (value("joy"), value("anger"), value("sadness"), value("fear"),
               value("love"), value("energy"), value("hunger")))


def _prov_stem(text) -> str:
    """省份归一：贵州 / 贵州省 → 贵州，广西壮族自治区 → 广西。"""
    name = str(text or "").strip()
    for suffix in ("维吾尔自治区", "壮族自治区", "回族自治区", "特别行政区",
                   "自治区", "省", "市"):
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return name


def _scenic_text(scenic):
    if not scenic:
        return "无"
    projects = scenic.get("projects") or []
    if isinstance(projects, list):
        projects = "、".join([str(item) for item in projects])
    return "%s（%s·%s，%s）：%s" % (
        scenic.get("name", ""), scenic.get("city", ""), scenic.get("area", ""),
        scenic.get("duration", ""), projects,
    )


JIT_HOURS = (8, 12, 15, 19, 23)


def jit_plan(hour, hunger, cash_cents, sick=False, mood_word="", stock_pnl=0, weekday=None, sick_action=None,
             mood_value=0):
    """到点即时决策：只给一个当前动作，不排未来。"""
    hour = int(hour)
    hunger = float(hunger)
    cash_cents = int(cash_cents)
    is_workday = weekday is not None and int(weekday) < 5
    if sick and sick_action == "go_to_work_sick":
        if hour == 7:
            return {"action": "硬撑着洗漱，量了体温还是烧", "place": "家", "zone": "home",
                    "category": "life", "cost_cents": 0, "diary": "烧还没退，可今天得去上班。"}
        if hour == 8:
            return {"action": "戴着口罩去挤地铁，咳得嗓子疼", "place": "路上", "zone": "road",
                    "category": "commute", "cost_cents": 0, "diary": "带病通勤，只想快点到公司。"}
        if hour == 9:
            return {"action": "到公司先趴一会儿，头昏昏沉沉", "place": "公司", "zone": "office",
                    "category": "work", "cost_cents": 0, "diary": "撑着坐到工位，先缓缓。"}
        if 10 <= hour <= 17 and hour != 12:
            return {"action": "在工位上昏昏沉沉，时不时咳嗽", "place": "公司", "zone": "office",
                    "category": "work", "cost_cents": 0, "diary": "带病上班，效率低得可怜。"}
        if hour == 12:
            return {"action": "没胃口，在工位上趴了一会儿", "place": "公司", "zone": "office",
                    "category": "meal", "cost_cents": 0, "diary": "午饭吃不下，只想闭眼。"}
        if hour == 18:
            return {"action": "下班回家，路上走得慢吞吞", "place": "路上", "zone": "road",
                    "category": "commute", "cost_cents": 0, "diary": "终于下班了，浑身发软。"}
        if hour == 19:
            return {"action": "到家瘫在沙发上，连饭都不想做", "place": "家", "zone": "home",
                    "category": "rest", "cost_cents": 0, "diary": "带病上一天班，回家只想躺着。"}
    if sick:
        if hour in (8, 12, 19):
            if cash_cents >= 1000:
                return {"action": "喝白粥、吃药休息", "place": "家", "zone": "home",
                        "category": "life", "cost_cents": 1000,
                        "diary": "生病了只能喝粥，好想吃火锅。"}
            return {"action": "裹着被子躺着，没胃口", "place": "家", "zone": "home",
                    "category": "rest", "cost_cents": 0, "diary": "生病又没钱，只能躺着。"}
        if is_workday and 7 <= hour <= 18:
            return {"action": "请假在家休息", "place": "家", "zone": "home",
                    "category": "rest", "cost_cents": 0, "diary": "今天请假，在家养病。"}
    # 心情优先于日历类型：情绪到极端时，工作日也会摸鱼发呆、周末也会突然想大扫除。
    # 以前这条心情支写在「工作日 / 周末」分支后面，工作日和周末都被前面拦掉，永远是死代码。
    if hour == 15 and float(mood_value or 0) >= 60:
        mood_text = str(mood_word or "")
        if "郁闷" in mood_text or "低落" in mood_text or "委屈" in mood_text:
            if is_workday:
                return {"action": "在工位上发呆，手头的事一点也不想动", "place": "公司", "zone": "office",
                        "category": "rest", "cost_cents": 0, "diary": "下午情绪很低，坐在工位上发呆。"}
            return {"action": "窝着发呆，不太想动", "place": "家", "zone": "home",
                    "category": "rest", "cost_cents": 0, "diary": "下午有点丧，什么都不想做。"}
        if "开心" in mood_text or "兴奋" in mood_text:
            if is_workday:
                return {"action": "心情很好，偷偷摸鱼刷了会儿手机", "place": "公司", "zone": "office",
                        "category": "life", "cost_cents": 0, "diary": "下午心情不错，偷偷摸了会儿鱼。"}
            return {"action": "忽然有兴致，把家里彻底打扫了一遍", "place": "家", "zone": "home",
                    "category": "life", "cost_cents": 0, "diary": "心情好，难得想搞大扫除。"}
    if is_workday:
        # 工作日法则：07-09 必须出门/通勤，09-18 物理位置默认公司，不能在家发呆。
        if hour == 7:
            return {"action": "急急忙忙洗漱，准备出门", "place": "家", "zone": "home",
                    "category": "life", "cost_cents": 0, "diary": "周一早上，得赶紧出门。"}
        if hour == 8:
            return {"action": "下楼买早餐，边走边吃去地铁站", "place": "路上", "zone": "road",
                    "category": "commute", "cost_cents": 0, "diary": "边赶路边吃，别迟到。"}
        if hour == 9:
            return {"action": "到公司，先泡杯咖啡", "place": "公司", "zone": "office",
                    "category": "work", "cost_cents": 0, "diary": "到工位了，先缓一口气。"}
        if 10 <= hour <= 17 and hour != 12:
            return {"action": "在工位上忙工作", "place": "公司", "zone": "office",
                    "category": "work", "cost_cents": 0, "diary": "手头的事一件接一件。"}
        if hour == 12:
            return {"action": "在公司食堂吃午饭", "place": "公司", "zone": "office",
                    "category": "meal", "cost_cents": 0, "diary": "中午在食堂随便吃点。"}
        if hour == 18:
            return {"action": "下班回家", "place": "路上", "zone": "road",
                    "category": "commute", "cost_cents": 0, "diary": "终于下班了。"}
        if hour == 19:
            return {"action": "到家先歇一会儿，准备晚饭", "place": "家", "zone": "home",
                    "category": "life", "cost_cents": 0, "diary": "到家了，先坐一会儿。"}
    if weekday is not None and int(weekday) >= 5 and hour in (8, 12, 15, 19):
        if hour == 15:
            return {"action": "窝在沙发上刷手机，没什么安排", "place": "家", "zone": "home",
                    "category": "rest", "cost_cents": 0, "diary": "周末下午，慢慢过。"}
        return {"action": "在家收拾屋子，看看剧", "place": "家", "zone": "home",
                "category": "life", "cost_cents": 0, "diary": "周末在家，不着急。"}
    if hour in (8, 12, 19) and hunger < 80:
        if cash_cents >= 1500:
            if hour == 12:
                food, cost = "楼下吃碗牛肉面", 1500
            elif hour == 8:
                food, cost = "买个包子和豆浆", 800
            else:
                food, cost = "随便吃点家常菜", 2000
            return {"action": "正在" + food, "place": "楼下小馆", "zone": "restaurant",
                    "category": "meal", "cost_cents": cost,
                    "diary": "有点饿，花了 %d 块%s。" % (cost // 100, food)}
        if cash_cents >= 500:
            return {"action": "在吃泡面", "place": "家", "zone": "home", "category": "meal",
                    "cost_cents": 500, "diary": "没什么钱，泡面凑合一下。"}
        return {"action": "饿着肚子喝水", "place": "家", "zone": "home", "category": "rest",
                "cost_cents": 0, "diary": "肚子好饿，可是连泡面都买不起了。"}
    if hour == 15:
        # 心情支已经挪到最前面（心情优先于日历类型）；这里只剩「日历不明」时的普通下午。
        return {"action": "在忙手头的事，偶尔刷手机", "place": "", "zone": "home",
                "category": "life", "cost_cents": 0, "diary": "下午慢慢过。"}
    if hour == 23:
        return {"action": "洗漱完准备睡了", "place": "家", "zone": "home",
                "category": "sleep", "cost_cents": 0, "diary": "今天就这样吧，睡觉。"}
    return {"action": "在忙自己的事", "place": "", "zone": "home",
            "category": "life", "cost_cents": 0, "diary": ""}


def _diary_material_lines(self, ctx, item, prev_item, next_item, prev_diary=""):
    """小日记提示词里的素材行：上/下一小时、车、礼物、穿着。模块级函数，假 self 也能直接调。"""
    prev_text = "无"
    if prev_item:
        prev_text = "%s-%s 在%s，%s，心情%s" % (
            prev_item.get("start"), prev_item.get("end"), prev_item.get("place"),
            prev_item.get("activity"), prev_item.get("mood") or "平静",
        )
    next_text = "无"
    if next_item:
        next_text = "%s-%s 去%s，%s" % (
            next_item.get("start"), next_item.get("end"), next_item.get("place"),
            next_item.get("activity"),
        )
    prev_diary_text = str(prev_diary or "").strip()[:500] or "（还没有生成上一小时日记）"
    car_line = ""
    if item.get("vehicle"):
        car_line = "这一小时是开%s；必须写清堵车、找停车位或路上的细节。" % item.get("vehicle")
    if item.get("detail"):
        car_line = (car_line + " 可以用的细节：%s。" % item.get("detail")).strip()
    asset_line = ""
    assets = str(ctx.get("assets") or "").strip()
    if assets:
        asset_line = ("他送你的东西：%s。写这一小时时可以自然戴/用/开，"
                      "但不要每段都提，也不要写你还想要更大的。" % assets)
    allow_gift = False
    try:
        hour = int(str(item.get("start") or "")[:2])
        allow_gift = hour in self._gift_mention_hours(ctx)
    except (TypeError, ValueError):
        allow_gift = False
    worn_line = ""
    worn = str(ctx.get("worn") or "").strip()
    if worn:
        if allow_gift:
            worn_line = "你今天身上/包里有：%s（他送的）。这一小时可以自然带一句，只提一句，别写成交代行踪。" % worn
        else:
            worn_line = "这一小时不要主动提他送的东西（今天已经提过了）；除非上一小时写了、这一小时要承接。"
    outfit_line = ""
    outfit = str(ctx.get("outfit") or "").strip()
    if outfit:
        outfit_line = ("你今天穿的是：%s（今天锁定的这一套，日记里写到衣服只能写它，不能另编）。" % outfit)
    gift_line = ""
    gift_log = str(ctx.get("gift_log") or "").strip()
    if gift_log and allow_gift:
        gift_line = ("他送过你的东西（日期）：%s。这一小时可以自然带一句；"
                     "日期不是今天的，不要写成今天送的。" % gift_log)
    return prev_text, next_text, prev_diary_text, car_line, asset_line, worn_line, gift_line, outfit_line

