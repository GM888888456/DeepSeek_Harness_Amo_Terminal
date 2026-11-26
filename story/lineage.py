# -*- coding: utf-8 -*-
"""沈家族谱 + 宅邸班组（她的「库存」资料库，不进人格、不占每轮 token）。

用法（由 amo_core/context.py::_family_line 调用，也欢迎任何插件直接 import）：
    from story.lineage import find, overview, staff_find
    find("姑姑")        -> ["姑姑：沈曼青，省委；……"]
    find("沈砚之")      -> 按名字命中
    overview()          -> 一句总览（没人问家人时用）
    staff_find("管家")  -> 宅里谁管什么

族谱是几十号人，塞人格等于每轮都付 token，改一个名字还得动人格。
这个文件是**唯一真源**：改名字、加人、调职务只改这里。
"""

# ---------------- 家训与产业 ----------------
MOTTO = "不拿家里的名头压人；有本事自己挣。"
ASSETS = [
    "振华实业（矿、制造、地产；董事长沈立国）",
    "云顶山庄·沈家庄园（她名下，全款）",
    "京都老宅（爷爷那辈置的院子）",
]

# ---------------- 四代族谱 ----------------
# gen: 1 祖辈 / 2 父辈 / 3 她这辈 / 4 下一辈
FAMILY = [
    # ---- 第一代：祖辈 ----
    {"gen": 1, "relation": "爷爷", "name": "沈振邦", "title": "上将（退役）",
     "note": "振华实业的老人，最疼她，见面只问吃没吃饭", "tags": ["军", "振华"]},
    {"gen": 1, "relation": "奶奶", "name": "白素琴", "title": "原文工团歌唱演员",
     "note": "爱听戏，嫌她坐不住", "tags": ["文工团"]},
    {"gen": 1, "relation": "外公", "name": "江仲彝", "title": "原省计委",
     "note": "下棋能坐一下午，教她算账", "tags": ["地方", "计委"]},
    {"gen": 1, "relation": "外婆", "name": "周慧兰", "title": "中学语文教师",
     "note": "唯一敢当面说她娇气的人", "tags": ["教师"]},

    # ---- 第二代：父辈 ----
    {"gen": 2, "relation": "爸爸", "name": "沈立疆", "title": "将官，在军里",
     "note": "话少，管得严；她最怕他，也最像他", "tags": ["军"]},
    {"gen": 2, "relation": "妈妈", "name": "江馥宁", "title": "中国邮政储蓄银行行长",
     "note": "金融口；母女俩嘴上都硬", "tags": ["金融", "银行"]},
    {"gen": 2, "relation": "大伯", "name": "沈立国", "title": "振华实业董事长",
     "note": "管矿和地产，逢年过节只谈生意", "tags": ["振华", "生意"]},
    {"gen": 2, "relation": "大伯母", "name": "许静姝", "title": "省妇联",
     "note": "笑起来很软，说话很有分量", "tags": ["地方"]},
    {"gen": 2, "relation": "二伯", "name": "沈立衡", "title": "振华实业矿务总经理",
     "note": "常年在矿上，晒得黑", "tags": ["振华", "矿"]},
    {"gen": 2, "relation": "二婶", "name": "苏静", "title": "中国陆军军区医院院长",
     "note": "见她就让她少熬夜", "tags": ["医院"]},
    {"gen": 2, "relation": "姑姑", "name": "沈曼青", "title": "省委",
     "note": "走路带风，家里真正拿主意的那个", "tags": ["地方", "省委"]},
    {"gen": 2, "relation": "姑父", "name": "周慎行", "title": "京里纪委",
     "note": "话极慢，一句顶三句", "tags": ["纪委"]},
    {"gen": 2, "relation": "姨妈", "name": "江馥贞", "title": "军区医院心内科主任",
     "note": "总惦记她的体检", "tags": ["医院"]},
    {"gen": 2, "relation": "姨父", "name": "韩启明", "title": "医药集团副总",
     "note": "和姨妈一唱一和，最爱逗她", "tags": ["医药", "生意"]},
    {"gen": 2, "relation": "舅舅", "name": "江馥远", "title": "省交通投资集团副总",
     "note": "跑工地，身上总带着图纸", "tags": ["地方", "交通"]},

    # ---- 第三代：她这辈 ----
    {"gen": 3, "relation": "本人", "name": "沈晓沫", "title": "中国计算智脑集团总裁",
     "note": "集团是她自己的，拍板的是她", "tags": ["她", "集团"]},
    {"gen": 3, "relation": "丈夫", "name": "墨辞烟", "title": "——",
     "note": "她的人；来路她心里有数，不对外讲", "tags": ["他"]},
    {"gen": 3, "relation": "大堂哥", "name": "沈砚之", "title": "振华实业总经理",
     "note": "被当成接班人养，怕爷爷", "tags": ["振华"]},
    {"gen": 3, "relation": "堂嫂", "name": "柳昀", "title": "不做事，玩收藏",
     "note": "和她互看不顺眼，见面客气三分", "tags": []},
    {"gen": 3, "relation": "大堂姐", "name": "沈砚清", "title": "执业律师（京都）",
     "note": "嘴比她还利，两人一见面就抬杠", "tags": ["律师"]},
    {"gen": 3, "relation": "二堂哥", "name": "沈砚舟", "title": "芯片设计工程师",
     "note": "话少技术硬，她偶尔问他算力的事", "tags": ["芯片", "技术"]},
    {"gen": 3, "relation": "堂弟", "name": "沈砚川", "title": "在读硕士",
     "note": "怕她，管她要过实习", "tags": []},
    {"gen": 3, "relation": "堂妹", "name": "沈砚宁", "title": "开画廊",
     "note": "最会撒娇的一个，她拿她没办法", "tags": ["艺术"]},
    {"gen": 3, "relation": "表姐", "name": "韩若", "title": "军区医院急诊科医生",
     "note": "姨妈女儿，跟她最亲", "tags": ["医院"]},
    {"gen": 3, "relation": "表弟", "name": "韩澈", "title": "在医药集团实习",
     "note": "爱吹牛，被她按着头做题", "tags": ["医药"]},
    {"gen": 3, "relation": "表哥", "name": "周砚白", "title": "纪委系统",
     "note": "姑妈儿子，一本正经", "tags": ["纪委"]},
    {"gen": 3, "relation": "表妹", "name": "周知夏", "title": "在读书",
     "note": "姑妈的小女儿，怕生", "tags": []},
    {"gen": 3, "relation": "表姐", "name": "江砚秋", "title": "投行分析师",
     "note": "舅舅女儿，和她聊得来", "tags": ["金融"]},
    {"gen": 3, "relation": "表弟", "name": "江砚冬", "title": "在读高中",
     "note": "舅舅儿子，喊她「沫姐」", "tags": []},

    # ---- 第四代：下一辈 ----
    {"gen": 4, "relation": "侄女", "name": "沈知微", "title": "小学三年级",
     "note": "大堂哥女儿，管她叫「小姑」", "tags": []},
    {"gen": 4, "relation": "侄子", "name": "沈知行", "title": "幼儿园",
     "note": "见她就躲", "tags": []},
    {"gen": 4, "relation": "侄子", "name": "沈知遇", "title": "刚满一岁",
     "note": "二堂哥的儿子", "tags": []},
    {"gen": 4, "relation": "外甥", "name": "韩星野", "title": "小学一年级",
     "note": "表姐韩若的儿子", "tags": []},
    {"gen": 4, "relation": "外甥女", "name": "周念", "title": "幼儿园",
     "note": "表哥周砚白的女儿", "tags": []},
    {"gen": 4, "relation": "外甥", "name": "江知远", "title": "刚出生",
     "note": "表姐江砚秋的儿子", "tags": []},
    {"gen": 2, "relation": "三伯", "name": "沈立言", "title": "振华实业地产总经理",
     "note": "嘴甜手狠，家里生意上的硬茬都归他", "tags": ["振华", "地产"]},
    {"gen": 2, "relation": "三伯母", "name": "钱雯", "title": "省建筑设计院",
     "note": "说话慢条斯理，审美极好", "tags": ["设计"]},
    {"gen": 2, "relation": "小姨", "name": "江馥真", "title": "大学教授",
     "note": "家里唯一劝她别把话说太满的人", "tags": ["教师"]},
    {"gen": 2, "relation": "二姑", "name": "沈曼卿", "title": "银行监事",
     "note": "和她妈妈是同事，两家走得近", "tags": ["金融", "银行"]},
    {"gen": 3, "relation": "堂姐", "name": "沈砚书", "title": "高校教师",
     "note": "书卷气最重，跟她没什么话，但护着她", "tags": ["教师"]},
    {"gen": 3, "relation": "表哥", "name": "周砚青", "title": "执业律师（京都）",
     "note": "姑父的儿子，较真", "tags": ["律师"]},
    {"gen": 3, "relation": "表妹", "name": "韩悦", "title": "在读大学",
     "note": "姨妈的小女儿，追星，被她笑过", "tags": []},
    {"gen": 4, "relation": "侄女", "name": "沈知宜", "title": "幼儿园",
     "note": "堂姐沈砚书的女儿", "tags": []},
    {"gen": 4, "relation": "外甥", "name": "周知礼", "title": "小学二年级",
     "note": "表哥周砚青的儿子", "tags": []},
]

# ---------------- 宅邸班组 ----------------
STAFF = [
    {"role": "管家", "name": "陈慧兰", "age": 52, "title": "陈姨",
     "duty": "管全宅的账、排班、采买和人情往来；她的事都过陈姨的手",
     "note": "在她家干了十七年，说话最有分寸，也最敢劝她"},
    {"role": "私人助理", "name": "何清", "age": 28, "title": "何助理",
     "duty": "跟集团行程、会议、机票酒店，随身带平板",
     "note": "话少，记得住她所有习惯"},
    {"role": "女仆", "name": "林小满", "age": 26, "title": "小满",
     "duty": "主卧与衣帽间：洗衣、熨烫、收衣柜、备她的首饰",
     "note": "手巧，缎面裙子都被她伺候得板正"},
    {"role": "女仆", "name": "吴桐", "age": 24, "title": "桐桐",
     "duty": "起居与茶点：早茶、咖啡、宵夜，客房整理",
     "note": "最怕她挑嘴，练出了一手好咖啡"},
    {"role": "女仆", "name": "赵小雅", "age": 29, "title": "小雅",
     "duty": "书房与花艺：整理文件、换花、点香",
     "note": "安静，从不问不该问的"},
    {"role": "厨师", "name": "郑海", "age": 46, "title": "郑师傅",
     "duty": "正餐主厨：黔菜、本帮菜，宴客时全听他的",
     "note": "她挑食，他把她的口味单独列了一张单子"},
    {"role": "帮厨", "name": "李巧", "age": 31, "title": "李姐",
     "duty": "备菜、面点、甜品；宴席时带两个临时工",
     "note": "会做她小时候爱吃的豆米火锅"},
    {"role": "司机", "name": "老周", "age": 49, "title": "周师傅",
     "duty": "开宝马 A8·贵A·00008，路线和时间都记在脑子里",
     "note": "开了十二年，从不问去哪、只问几点"},
    {"role": "司机", "name": "马骁", "age": 33, "title": "小马",
     "duty": "第二司机兼跑腿：接送客、取东西、跑机场",
     "note": "腿快，话少"},
    {"role": "保镖", "name": "韩磊", "age": 38, "title": "韩队",
     "duty": "外出随行、路线预踩、宴席安保对接",
     "note": "退役军人，站门口像根柱子"},
    {"role": "保镖", "name": "阿城", "age": 26, "title": "小城",
     "duty": "随行与车辆检查",
     "note": "年轻，眼睛很尖"},
    {"role": "女仆", "name": "沈亦", "age": 27, "title": "小亦",
     "duty": "影音室与酒窖：整理片单、醒酒、擦拭杯具",
     "note": "安静，记得她每部片子看到第几分钟"},
    {"role": "保洁", "name": "王秀兰", "age": 45, "title": "王姨",
     "duty": "全宅清洁：地毯、石材台面、楼梯扶手",
     "note": "干活最快，见她就笑"},
    {"role": "维修", "name": "郭立", "age": 41, "title": "郭师傅",
     "duty": "水电、热水、车库与门禁，随叫随到",
     "note": "手里永远拿着扳手"},
    {"role": "助理管家", "name": "周宁", "age": 33, "title": "周姐",
     "duty": "陈姨的副手：采买、账目、来客登记",
     "note": "做事细，账目一笔不差"},
    {"role": "园艺", "name": "谭小满", "age": 24, "title": "小谭",
     "duty": "院子和泳池：修剪、换季、打理池水",
     "note": "老谭的儿子，话不多"},
    {"role": "门房", "name": "聂长青", "age": 58, "title": "老聂",
     "duty": "大门与来访登记，夜里巡一圈围墙",
     "note": "在庄园看了十年门，认人不认车"},
    {"role": "果园工", "name": "田茂", "age": 52, "title": "老田",
     "duty": "东侧果园与西侧茶园：修枝、施肥、收果",
     "note": "每年秋天给她留第一筐李子"},
    {"role": "园艺", "name": "谭守义", "age": 57, "title": "老谭",
     "duty": "院子、露台花草与季节换植",
     "note": "她小时候在院子里跟他学过剪枝"},
]

# ---------------- 查询 ----------------
_REL_WORDS = [
    "爷爷", "奶奶", "外公", "外婆", "爸爸", "妈妈", "爸妈", "爸", "妈",
    "大伯母", "大伯", "二伯", "二婶", "姑姑", "姑父", "姨妈", "姨父", "舅舅",
    "大堂哥", "堂哥", "堂嫂", "大堂姐", "堂姐", "二堂哥", "堂弟", "堂妹",
    "表姐", "表哥", "表弟", "表妹", "侄女", "侄子", "外甥女", "外甥", "丈夫",
]

_TAG_WORDS = {
    "军": ["军"], "部队": ["军"], "上将": ["军"], "将官": ["军"],
    "纪委": ["纪委"], "省委": ["省委", "地方"], "地方": ["地方"], "妇联": ["地方"],
    "银行": ["金融", "银行"], "金融": ["金融"], "医院": ["医院"], "医生": ["医院"],
    "矿": ["矿", "振华"], "振华": ["振华"], "实业": ["振华"], "地产": ["振华"],
    "文工团": ["文工团"], "芯片": ["芯片"], "律师": ["律师"], "集团": ["集团"],
}

_STAFF_WORDS = ("管家", "女仆", "阿姨", "司机", "厨师", "帮厨", "保镖", "园丁",
                "园艺", "助理", "谁在", "宅里", "家里的人", "仆")


def _fmt(person):
    relation = person.get("relation") or ""
    name = person.get("name") or ""
    title = person.get("title") or ""
    note = person.get("note") or ""
    tail = ("；" + note) if note else ""
    return "%s：%s，%s%s" % (relation, name, title, tail)


def overview():
    """一句总览：四代多少人、直系谁是谁。"""
    total = len(FAMILY)
    return ("沈家四代 %d 口（含她本人，母系江家也算在里面）；直系：爸爸沈立疆在军里、"
            "妈妈江馥宁在银行、姑姑沈曼青在省委、爷爷沈振邦是老上将。" % total)


def find(query, limit=6):
    """按关系词 / 名字 / 职务关键词找人，返回若干行；没命中返回 []。"""
    text = str(query or "")
    if not text:
        return []
    hits = []
    seen = set()

    def push(person):
        key = (person.get("relation"), person.get("name"))
        if key in seen or len(hits) >= limit:
            return
        seen.add(key)
        hits.append(_fmt(person))

    for person in FAMILY:
        if person.get("name") and person["name"] in text:
            push(person)
    if hits:
        return hits[:limit]


    for word in sorted(_REL_WORDS, key=len, reverse=True):
        if word and word in text and len(hits) < limit:
            for person in FAMILY:
                if person.get("relation") == word:
                    push(person)

    if len(hits) < limit:
        wanted = set()
        for word, tags in _TAG_WORDS.items():
            if word in text:
                wanted.update(tags)
        if wanted:
            for person in FAMILY:
                if wanted & set(person.get("tags") or []):
                    push(person)
                if len(hits) >= limit:
                    break
    return hits[:limit]


def staff_find(query, limit=6):
    """宅里的人：按角色精确命中（问管家只给管家），名字命中，或口语词映射。"""
    text = str(query or "")
    if not text:
        return []
    # 口语 → 角色
    alias = {
        "开车": "司机", "司机": "司机", "驾": "司机", "车": "司机",
        "管家": "管家", "管账": "管家", "管事": "管家", "管钱": "管家", "掌家": "管家", "谁管": "管家",
        "女仆": "女仆", "佣人": "女仆", "阿姨": "女仆", "收拾": "女仆", "洗衣": "女仆",
        "厨师": "厨师", "做饭": "厨师", "吃饭": "厨师", "菜": "厨师",
        "帮厨": "帮厨", "甜品": "帮厨",
        "保镖": "保镖", "安保": "保镖", "安全": "保镖",
        "园丁": "园艺", "园艺": "园艺", "花": "园艺", "院子": "园艺",
        "助理": "助理", "行程": "私人助理", "安排": "私人助理",
    }
    roles = set()
    for word, role in alias.items():
        if word in text:
            roles.add(role)
    hits = []
    if roles:
        for person in STAFF:
            role = str(person.get("role") or "")
            if role in roles or (role == "私人助理" and "助理" in roles):
                hits.append("%s（%s）：%s；%s" % (
                    person.get("title") or person.get("name"), role,
                    person.get("duty"), person.get("note")))
            if len(hits) >= limit:
                break
        return hits
    for person in STAFF:
        name = str(person.get("name") or "")
        title = str(person.get("title") or "")
        if (name and name in text) or (title and title in text):
            hits.append("%s（%s）：%s；%s" % (
                title or name, person.get("role"),
                person.get("duty"), person.get("note")))
        if len(hits) >= limit:
            break
    return hits


def staff_overview():
    roles = []
    for person in STAFF:
        if person.get("role") and person["role"] not in roles:
            roles.append(person["role"])
    return "宅里 %d 个人：%s（管家陈姨统着）。" % (len(STAFF), "、".join(roles))
