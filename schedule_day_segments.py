# -*- coding: utf-8 -*-
"""工作日/外出/室内休息骨架：纯函数，seg/place_of 由 engine 注入。"""
from __future__ import annotations


def workday_segments(ctx, seg, overtime=False):
    """总裁的工作日：会议、批红、见人、偶尔应酬。不再是朝九晚五的工位。

    2026-11-25（用户口径）：她把职业改成中国计算智脑集团总裁，日程要跟着换。
    """
    import time as _time

    home = ctx["home"]
    office = ctx.get("workplace") or "中国计算智脑集团"
    late = bool((ctx.get("yesterday") or {}).get("late_night"))
    sick = bool((ctx.get("health") or {}).get("sick"))
    sick_work = sick and str(ctx.get("sick_action") or "") == "go_to_work_sick"
    has_car = bool(ctx.get("has_gift_car"))
    car = ctx.get("car") or ""

    try:
        dow = int(_time.strftime("%w"))
    except Exception:
        dow = 1
    social = dow in (2, 4)          # 周二、周四晚上有应酬

    def drive(detail=""):
        return dict(transit="drive", vehicle=car, detail=detail) if has_car else \
            dict(transit="subway", detail=detail)

    if sick_work:
        morning = "量了体温还是低烧，照样出门——今天有会推不掉"
    elif late:
        morning = "昨晚睡得晚，起来灌了杯咖啡"
    else:
        morning = "起来洗漱，顺手翻了翻昨晚的晨报"

    work_morning = seg("09:20", "10:30", "开高管例会，各条线的数摆一桌",
                       "%s会议室" % office, "office", "work")
    if sick_work:
        work_morning = seg("09:20", "10:30", "强撑着开完高管例会，声音都哑了",
                           "%s会议室" % office, "office", "work")

    if overtime:
        evening = [
            seg("18:30", "19:30", "出岔子了，留在办公室处理", office, "office", "work"),
            seg("19:30", "20:30", "让人送了两份便当上来", office, "office", "meal"),
            seg("20:30", "21:30", "事情压下去了，收尾签字", office, "office", "work"),
            seg("21:30", "22:00", "老周开车送她回去", "路上", "road", "commute", **drive("夜里路空，老周开得稳")),
            seg("22:00", "23:00", "到家先冲个澡", home, "home", "life"),
            seg("23:00", "24:00", "睡觉", home, "home", "sleep"),
        ]
    elif social and not sick:
        evening = [
            seg("18:30", "20:30", "在饭局上应酬，敬酒、听人讲话、点头",
                "观山湖的酒楼", "restaurant", "work"),
            seg("20:30", "21:30", "散场，把两个客人送上车", "门口", "road", "work"),
            seg("21:30", "22:00", "老周开车送她回家", "路上", "road", "commute", **drive("老周开车，她靠在后排眯一会儿")),
            seg("22:00", "23:00", "回家卸妆、换掉一身烟味", home, "home", "life"),
            seg("23:00", "24:00", "睡觉", home, "home", "sleep"),
        ]
    else:
        evening = [
            seg("18:30", "19:00", "收拾桌面，最后回一遍邮件", office, "office", "work"),
            seg("19:00", "19:30", "老周开车送她回家", "路上", "road", "commute", **drive("错峰，路上不堵")),
            seg("19:30", "20:30", "在家里吃晚饭", home, "home", "meal"),
            seg("20:30", "22:00", "窝在沙发上，不想再动脑子", home, "home", "rest"),
            seg("22:00", "23:00", "洗澡、敷面膜", home, "home", "life"),
            seg("23:00", "24:00", "睡觉", home, "home", "sleep"),
        ]

    # ---- 下午去看现场：车程按真实分钟排，回不回、玩不玩由时间决定 ----
    # 2026-11-26 用户口径：要有时间因果——A→B 花 X，B 待 Y，回程 Z；
    # 视察完够时间就近透一圈，不够就直接回办公室。
    try:
        from .route_time import drive_minutes
    except ImportError:      # 单独 import 这个文件做测试时走绝对导入
        from route_time import drive_minutes

    def hhmm(mins):
        mins = int(max(0, min(24 * 60, mins)))
        return "24:00" if mins >= 24 * 60 else "%02d:%02d" % (mins // 60, mins % 60)

    city = str(ctx.get("city") or "")
    site_place = "贵安机房"
    yard_place = "贵安园区工地"
    out_min = int(round(drive_minutes(office, site_place, city=city)[0] or 27))
    back_min = int(round(drive_minutes(yard_place, office, city=city)[0] or out_min))
    leave = 15 * 60 + 30
    arrive = leave + out_min
    check_done = arrive + 45          # 蹲下查线缆
    yard_done = check_done + 25       # 隔壁园区工地走一圈
    play_min = 30
    want_play = ((int(ctx.get("seed") or 0) // 11) % 2 == 0)
    # 18:40 前得坐回办公室：回程、就近玩、再回程，都塞得进去才玩
    can_play = (yard_done + play_min + 10) <= (18 * 60 + 40 - back_min)
    visit = [
        seg(hhmm(leave), hhmm(arrive), "出门去贵安看机房，园区外环在修路",
            "路上", "road", "commute", **drive("老周开车，路上约 %d 分钟" % out_min)),
        seg(hhmm(arrive), hhmm(check_done), "在贵安机房蹲下来查线缆，一排排看过去",
            site_place, "office", "work"),
        seg(hhmm(check_done), hhmm(yard_done), "顺路到隔壁园区工地转一圈，风把头发吹乱",
            yard_place, "scenic", "work"),
    ]
    if can_play and want_play:
        visit.append(seg(hhmm(yard_done), hhmm(yard_done + play_min),
                         "看完了不急着走，就近在贵安园区走了走，站路边吹了会儿风",
                         "贵安园区", "park", "rest"))
        yard_done += play_min
    visit.append(seg(hhmm(yard_done), hhmm(yard_done + back_min),
                     "老周开车回办公室，赶在晚高峰前走", "路上", "road", "commute",
                     **drive("路上约 %d 分钟" % back_min)))
    visit.append(seg(hhmm(yard_done + back_min), "18:30",
                     "回到办公室，把今天的字签完", office, "office", "work"))

    return [
        seg("00:00", "06:40", "睡觉", home, "home", "sleep"),
        seg("06:40", "07:20", morning, home, "home", "life",
            detail="昨晚没睡好" if late else ""),
        seg("07:20", "08:00", "在家吃早饭，边吃边看今天的安排", home, "home", "meal"),
        seg("08:00", "08:40", "出门去集团总部" if has_car else "出门去集团总部",
            "路上", "road", "commute", **drive("早高峰有点堵" if has_car else "")),
        seg("08:40", "09:20", "到办公室，总办已经把今天的材料摆在桌上",
            office, "office", "work"),
        work_morning,
        seg("10:30", "11:40", "批红：一份一份看，该签的签，该驳的驳",
            office, "office", "work"),
        seg("11:40", "12:30", "见人——客户、机构、或者省里来的",
            "%s会客室" % office, "office", "work"),
        seg("12:30", "13:30", "吃午饭，跟高管在食堂坐一桌" if not sick_work else "没胃口，喝了点粥",
            office, "restaurant", "meal"),
        seg("13:30", "15:00", "评审会：算力扩建、产品路线、预算",
            "%s会议室" % office, "office", "work"),
        seg("15:00", "15:30", "在走廊上被两个人拦住，边走边说",
            office, "office", "work"),
        *visit,

    ] + evening


def outing_segments(ctx, seg):
    """外出日骨架：早上出门，白天在外面玩，傍晚回家。"""
    ctx = dict(ctx or {})
    home = ctx.get("home") or "家"
    city = ctx.get("city") or "城里"
    spot = ctx.get("scenic") or {}
    where = str(spot.get("name") or "").strip() or ("%s的街上" % city)
    zone = "scenic" if str(spot.get("name") or "").strip() else "mall"
    return [
        seg("00:00", "08:00", "睡觉", home, "home", "sleep"),
        seg("08:00", "09:00", "起床收拾，翻衣柜挑今天要穿的衣服", home, "home", "life"),
        seg("09:00", "10:00", "出门，坐车去%s" % where, "路上", "road", "commute",
            transit="在路上", vehicle="地铁"),
        seg("10:00", "12:00", "在%s慢慢逛" % where, where, zone, "play"),
        seg("12:00", "13:00", "找了家小店吃饭", "%s附近" % where, "restaurant", "meal"),
        seg("13:00", "16:00", "接着逛，走走停停", where, zone, "play"),
        seg("16:00", "17:00", "找个地方坐下歇一会儿，喝点东西", where, zone, "rest"),
        seg("17:00", "18:00", "往回走，路上有点累", "路上", "road", "commute",
            transit="在路上", vehicle="地铁"),
        seg("18:00", "19:00", "到家先洗把脸缓一缓", home, "home", "life"),
        seg("19:00", "20:00", "到家附近吃晚饭", home, "home", "meal"),
        seg("20:00", "22:00", "洗完澡窝在沙发上，翻今天拍的照片", home, "home", "rest"),
        seg("22:00", "24:00", "睡觉", home, "home", "sleep"),
    ]


def indoor_rest_segments(ctx, seg, place_of):
    home = ctx["home"]
    spot = ctx.get("scenic") or {}
    name = str(spot.get("name") or "商场")
    place = place_of(ctx, name)
    car = ctx["car"]
    return [
        seg("00:00", "08:00", "睡觉", home, "home", "sleep"),
        seg("08:00", "09:00", "起床吃早餐", home, "home", "meal"),
        seg("09:00", "10:00", "收拾屋子、洗衣服", home, "home", "life"),
        seg("10:00", "11:00", "老周开车带她去" + name, "路上", "road", "commute",
            transit="drive", vehicle=car, detail="下雨天路滑，开得慢"),
        seg("11:00", "13:00", "逛" + name, place,
            "mall" if not spot.get("indoor") else "scenic", "play", vehicle=car, spot=name),
        seg("13:00", "14:00", "吃午饭", place + "·餐厅", "restaurant", "meal"),
        seg("14:00", "16:00", "继续逛、找地方坐着", place, "mall", "play"),
        seg("16:00", "17:00", "喝杯热饮", place + "·咖啡店", "restaurant", "rest"),
        seg("17:00", "18:00", "老周开车送她回家", "路上", "road", "commute",
            transit="drive", vehicle=car),
        seg("18:00", "19:00", "到家缓一会儿", home, "home", "rest"),
        seg("19:00", "20:00", "吃晚饭", home, "home", "meal"),
        seg("20:00", "22:00", "追剧、刷手机", home, "home", "rest"),
        seg("22:00", "23:00", "洗澡护肤", home, "home", "life"),
        seg("23:00", "24:00", "睡觉", home, "home", "sleep"),
    ]
