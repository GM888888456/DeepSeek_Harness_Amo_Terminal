# -*- coding: utf-8 -*-
"""Amo 终端 · deps

从 main.py 平移而来（阶段 1 拆分），函数体与原文逐行一致，不要在这里改行为。
"""
from __future__ import annotations

import asyncio
import difflib
import hashlib
import inspect
import json
import math
import os
import random
import re
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone

_PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

try:
    from astrbot.api import logger
except Exception:  # pragma: no cover
    import logging

    logger = logging.getLogger("amo_terminal")

import asyncio
import difflib
import hashlib
import inspect
import json
import math
import os
import random
import re
import sqlite3
import threading
import time
import uuid
from datetime import date, datetime, timedelta, timezone
try:
    import astrbot.api.message_components as Comp
except Exception:
    Comp = None
from astrbot.api import logger
try:
    from ..chain import Chain
except ImportError:
    from chain import Chain  # type: ignore
try:
    from ..wardrobe import Wardrobe, SCENE_LABELS
    from ..wardrobe import build_items_from_catalog as build_wardrobe_items
    from ..wardrobe import hanfu_jk_items
except Exception:  # 直接按文件加载时
    try:
        from wardrobe import Wardrobe, SCENE_LABELS  # type: ignore
        from wardrobe import build_items_from_catalog as build_wardrobe_items  # type: ignore
    except Exception:
        Wardrobe = None
        build_wardrobe_items = None
        hanfu_jk_items = None
        SCENE_LABELS = {}
try:
    from ..outfit_engine import OutfitEngine, at_home
except Exception:  # 直接按文件加载时
    try:
        from outfit_engine import OutfitEngine, at_home  # type: ignore
    except Exception:
        OutfitEngine = None

        def at_home(activity):
            return True
try:
    from ..promise_engine import (
        KIND_ACT,
        KIND_PHOTO,
        WAIT_DRIVE,
        WAIT_PLACE,
        WAIT_TIME,
        PromiseEngine,
        detect_act_later,
        detect_photo_later,
        detect_place,
        driving,
        his_side,
        place_of,
    )
except Exception:  # 直接按文件加载时
    try:
        from promise_engine import (  # type: ignore
            KIND_ACT,
            KIND_PHOTO,
            WAIT_DRIVE,
            WAIT_PLACE,
            WAIT_TIME,
            PromiseEngine,
            detect_act_later,
            detect_photo_later,
            detect_place,
            driving,
            his_side,
            place_of,
        )
    except Exception:
        PromiseEngine = None
        KIND_PHOTO, KIND_ACT = "photo", "act"
        WAIT_DRIVE, WAIT_PLACE, WAIT_TIME = "drive", "place", "time"
        detect_act_later = detect_photo_later = detect_place = None
        driving = None
        place_of = None

        def his_side(text, *, speaker="", **_kwargs):
            return "her"
try:
    from ..draw_engine import DrawEngine
    from ..sleep_cycle import (
        GO_SLEEP_WORDS,
        WAKE_WORDS,
        SleepAnswer,
        SleepCycle,
        reason_for,
    )
except ImportError:  # 直接按文件加载时
    try:
        from draw_engine import DrawEngine
        try:
            from sleep_cycle import (
                GO_SLEEP_WORDS,
                WAKE_WORDS,
                SleepAnswer,
                SleepCycle,
                reason_for,
            )
        except ImportError:  # pragma: no cover
            SleepCycle = None
    except Exception:  # 没装/导入失败时不影响主脑启动
        DrawEngine = None
try:
    from ..day_types import normalize_day_types, pick_day_type
except Exception:
    try:
        from day_types import normalize_day_types, pick_day_type
    except Exception:
        normalize_day_types = None
        pick_day_type = None
try:
    from ..schedule_change import apply_change as apply_sched_change, detect_schedule_change
except Exception:
    try:
        from schedule_change import apply_change as apply_sched_change, detect_schedule_change
    except Exception:
        detect_schedule_change = None
        apply_sched_change = None
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
try:
    from astrbot.api.event import MessageChain
except Exception:
    try:
        from astrbot.core.message.message_event_result import MessageChain
    except Exception:
        MessageChain = None
try:
    from astrbot.api.web import request as web_request
except Exception:
    try:
        from quart import request as web_request
    except Exception:
        web_request = None
try:
    from astrbot.core.agent.message import TextPart
except Exception:
    TextPart = None
try:
    from ..heartflow_engine import HeartflowEngine
except Exception:
    try:
        from heartflow_engine import HeartflowEngine
    except Exception:
        HeartflowEngine = None
        try:
            import importlib.util
            _engine_dir = _PLUGIN_DIR
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
try:
    from ..send_bookkeeping import after_external_send as _after_external_send
except Exception:
    try:
        from send_bookkeeping import after_external_send as _after_external_send
    except Exception:
        _after_external_send = None
try:
    from ..weather_alert import evaluate as evaluate_weather_alert, parse_daily as parse_weather_daily, next_check_slot, parse_clock, slot_key, is_weather_query, forecast_brief
except Exception:
    try:
        from weather_alert import evaluate as evaluate_weather_alert, parse_daily as parse_weather_daily, next_check_slot, parse_clock, slot_key, is_weather_query, forecast_brief
    except Exception:
        def evaluate_weather_alert(*args, **kwargs):
            return ""
        def parse_weather_daily(*args, **kwargs):
            return []

        # 天气模块没装上时的兜底（原来挂在礼物导入下面，礼物删掉后挪回来）
        def next_check_slot(*args, **kwargs):
            return ""
        def parse_clock(*args, **kwargs):
            return 0
        def slot_key(today, slot):
            return "%s|%s" % (today, slot)
        def is_weather_query(*args, **kwargs):
            return False
        def forecast_brief(*args, **kwargs):
            return ""
try:
    from ..proactive_guard import analyze_rows as _pg_analyze_rows, compose_task as _pg_compose_task, near_duplicate as _pg_near_duplicate
except Exception:
    try:
        from proactive_guard import analyze_rows as _pg_analyze_rows, compose_task as _pg_compose_task, near_duplicate as _pg_near_duplicate
    except Exception:
        _pg_analyze_rows = _pg_compose_task = _pg_near_duplicate = None
try:
    from ..time_recall import looks_like_time_query as _looks_like_time_query, render_time_block as _render_time_block
except Exception:
    try:
        from time_recall import looks_like_time_query as _looks_like_time_query, render_time_block as _render_time_block
    except Exception:
        def _looks_like_time_query(*args, **kwargs):
            return False

        def _render_time_block(*args, **kwargs):
            return ""
try:
    from ..greet_route import greeting_targets as _greeting_targets, within_minutes as _within_minutes
except Exception:
    try:
        from greet_route import greeting_targets as _greeting_targets, within_minutes as _within_minutes
    except Exception:
        logger.warning("[amo] greet_route 载入失败，问候平台随机功能不可用")

        def _greeting_targets(candidates, primary="", randomize=True, rng=None):
            items = []
            for umo in list(candidates or []) + [primary]:
                value = str(umo or "")
                if value and value not in items:
                    items.append(value)
            return items if randomize else ([primary] if primary else [])

        def _within_minutes(last_ts, now, minutes):
            return False
try:
    from ..diary_lines import (
        DIARY_WRITTEN_REPLIES as _DIARY_WRITTEN,
        DIARY_SHOW_REPLIES as _DIARY_SHOW,
        DIARY_ENDING_HINTS,
        pick_hints as _diary_pick_hints,
    )
except Exception:
    try:
        from diary_lines import (
            DIARY_WRITTEN_REPLIES as _DIARY_WRITTEN,
            DIARY_SHOW_REPLIES as _DIARY_SHOW,
            DIARY_ENDING_HINTS,
            pick_hints as _diary_pick_hints,
        )
    except Exception:
        _DIARY_WRITTEN = ["写了", "写了，不给你看", "写了，秘密"]
        _DIARY_SHOW = ["不行，你不能偷看我的日记哦", "那是我的日记，才不给你看", "你想得美"]

        def _diary_pick_hints(items, count=8, seed=""):
            return list(items)[:count]
try:
    from ..milestone import (
        should_archive as _ms_should_archive,
        transcript as _ms_transcript,
        build_prompt as _ms_build_prompt,
        build_content as _ms_build_content,
    )
except Exception:
    try:
        from milestone import (
            should_archive as _ms_should_archive,
            transcript as _ms_transcript,
            build_prompt as _ms_build_prompt,
            build_content as _ms_build_content,
        )
    except Exception:
        def _ms_should_archive(*args, **kwargs):
            return False

        def _ms_transcript(*args, **kwargs):
            return ""

        def _ms_build_prompt(*args, **kwargs):
            return ""

        def _ms_build_content(*args, **kwargs):
            return ""
try:
    from ..wander import (
        assess as _wander_assess,
        ask_limit as _wander_ask_limit,
        detect_agreement as _wander_agree,
        detect_question as _wander_question,
        detect_follow_invite as _follow_invite,
        detect_follow_refuse as _follow_refuse,
        detect_refusal as _wander_refuse,
        follow_agree_text as _wander_follow_agree_text,
        follow_block as _follow_block,
        offer_block as _wander_offer_block,
        offer_text as _wander_offer_text,
        pick_destination as _wander_pick,
        plan_text as _wander_plan_text,
        solo_agree_text as _wander_solo_agree_text,
        solo_block as _wander_solo_block,
        solo_refuse_text as _wander_solo_refuse_text,
        trip_days as _wander_trip_days,
        want_travel as _wander_want,
    )
except Exception:
    try:
        from wander import (
            assess as _wander_assess,
            ask_limit as _wander_ask_limit,
            detect_agreement as _wander_agree,
            detect_question as _wander_question,
            detect_follow_invite as _follow_invite,
            detect_follow_refuse as _follow_refuse,
            detect_refusal as _wander_refuse,
            follow_agree_text as _wander_follow_agree_text,
            follow_block as _follow_block,
            offer_block as _wander_offer_block,
            offer_text as _wander_offer_text,
            pick_destination as _wander_pick,
            plan_text as _wander_plan_text,
            solo_agree_text as _wander_solo_agree_text,
            solo_block as _wander_solo_block,
            solo_refuse_text as _wander_solo_refuse_text,
            trip_days as _wander_trip_days,
            want_travel as _wander_want,
        )
    except Exception:
        def _wander_assess(*args, **kwargs):
            return (False, False)

        def _wander_agree(*args, **kwargs):
            return False

        def _wander_question(*args, **kwargs):
            return False

        def _wander_refuse(*args, **kwargs):
            return False

        def _follow_block(*args, **kwargs):
            return ""

        def _follow_invite(*args, **kwargs):
            return False

        def _follow_refuse(*args, **kwargs):
            return False

        def _wander_follow_agree_text(*args, **kwargs):
            return ""

        def _wander_offer_block(*args, **kwargs):
            return ""

        def _wander_offer_text(*args, **kwargs):
            return ""

        def _wander_pick(*args, **kwargs):
            return ("", [])

        def _wander_plan_text(*args, **kwargs):
            return ""

        def _wander_ask_limit(*args, **kwargs):
            return 1

        def _wander_solo_agree_text(*args, **kwargs):
            return ""

        def _wander_solo_block(*args, **kwargs):
            return ""

        def _wander_solo_refuse_text(*args, **kwargs):
            return ""

        def _wander_trip_days(*args, **kwargs):
            return 1

        def _wander_want(*args, **kwargs):
            return False
try:
    from ..memory_hooks import MemoryHub, render_recent_block
except Exception:
    try:
        from memory_hooks import MemoryHub, render_recent_block
    except Exception:
        MemoryHub = None
        render_recent_block = None
try:
    from ..attribution import first_person_experience, attribution_leak, leak_tokens
except Exception:
    try:
        from attribution import first_person_experience, attribution_leak, leak_tokens
    except Exception:
        first_person_experience = attribution_leak = leak_tokens = None
try:
    from ..brushoff import strip_brushoff
except Exception:
    try:
        from brushoff import strip_brushoff
    except Exception:
        strip_brushoff = None
try:
    from ..relation_learn import parse_relations
except Exception:
    try:
        from relation_learn import parse_relations
    except Exception:
        parse_relations = None
try:
    from ..city_follow import (
        DEFAULT_CITY as _CITY_DEFAULT,
        detect_city as _city_detect,
        compose_block as _city_block,
        travel_block as _city_travel_block,
        travel_events as _city_travel_events,
        travel_action as _city_travel_action,
        travel_to_events as _city_travel_to_events,
        pick_spots as _city_pick_spots,
    )
except Exception:
    try:
        from city_follow import (
            DEFAULT_CITY as _CITY_DEFAULT,
            detect_city as _city_detect,
            compose_block as _city_block,
            travel_block as _city_travel_block,
            travel_events as _city_travel_events,
            travel_action as _city_travel_action,
            travel_to_events as _city_travel_to_events,
            pick_spots as _city_pick_spots,
        )
    except Exception:
        _CITY_DEFAULT = "东莞"

        def _city_pick_spots(*args, **kwargs):
            return []

        def _city_travel_to_events(*args, **kwargs):
            return []

        def _city_travel_action(*args, **kwargs):
            return "none"

        def _city_detect(*args, **kwargs):
            return None

        def _city_block(*args, **kwargs):
            return ""

        def _city_travel_block(*args, **kwargs):
            return ""

        def _city_travel_events(*args, **kwargs):
            return []
try:
    from ..relation_graph import rank_edges as _rank_edges
except Exception:
    try:
        from relation_graph import rank_edges as _rank_edges
    except Exception:
        _rank_edges = None
try:
    from ..relation_sediment import plan_edges as plan_relation_edges
    from ..relation_sediment import guess_person_edges as guess_relation_edges
except Exception:
    try:
        from relation_sediment import plan_edges as plan_relation_edges
        from relation_sediment import guess_person_edges as guess_relation_edges
    except Exception:
        plan_relation_edges = None
        guess_relation_edges = None
try:
    from ..schedule_engine import ScheduleEngine
except Exception:
    try:
        from schedule_engine import ScheduleEngine
    except Exception:
        try:
            import importlib.util as _importlib_util
            _schedule_path = os.path.join(_PLUGIN_DIR, "schedule_engine.py")
            _schedule_spec = _importlib_util.spec_from_file_location("amo_schedule_engine", _schedule_path)
            _schedule_module = _importlib_util.module_from_spec(_schedule_spec)
            _schedule_spec.loader.exec_module(_schedule_module)
            ScheduleEngine = getattr(_schedule_module, "ScheduleEngine")
        except Exception as _schedule_exc:
            ScheduleEngine = None
            logger.error("[amo] 日程引擎加载失败: %s" % _schedule_exc)
try:
    from ..memory_scope import private_rows as _private_rows
except Exception:
    try:
        from memory_scope import private_rows as _private_rows
    except Exception:
        # 模块缺失时退回「不过滤」，别把总结整段停掉
        def _private_rows(rows):
            return list(rows or [])
try:
    from ..amo_enums import (DAY_PART_SPANS, ActivityCategory,
                            SceneZone, normalize_schedule_item, value_of)
except ImportError:  # 直接按文件加载时
    from amo_enums import (DAY_PART_SPANS, ActivityCategory,
                           SceneZone, normalize_schedule_item, value_of)
try:
    from ..heartflow import Heartflow as HeartflowCore, HeartflowEvent as FeelEvent
except ImportError:  # pragma: no cover
    try:
        from heartflow import Heartflow as HeartflowCore, HeartflowEvent as FeelEvent
    except ImportError:
        HeartflowCore = None
        FeelEvent = None
try:
    from ..memory_guard import commit as _mem_commit, prepare as _mem_prepare
except ImportError:  # pragma: no cover
    try:
        from memory_guard import commit as _mem_commit, prepare as _mem_prepare
    except ImportError:
        _mem_prepare = None
        _mem_commit = None
try:
    from ..text_clean import has_tool_markup, strip_pseudo_tags, strip_tool_markup
except ImportError:  # 直接按文件加载时
    from text_clean import has_tool_markup, strip_pseudo_tags, strip_tool_markup
try:
    from ..guard_bridge import process_reply_text as _guard_process_reply
except Exception:
    try:
        from guard_bridge import process_reply_text as _guard_process_reply
    except Exception:  # pragma: no cover
        _guard_process_reply = None
try:
    from .. import label_bus as _label_bus
except Exception:
    try:
        import label_bus as _label_bus
    except Exception:  # pragma: no cover
        _label_bus = None
try:
    from .. import baseline as _baseline
    from .. import event_bus as _event_bus_mod
except Exception:
    try:
        import baseline as _baseline
        import event_bus as _event_bus_mod
    except Exception:  # pragma: no cover
        _baseline = _event_bus_mod = None
try:
    from ..guard_bridge import deliver_reply as _guard_deliver_reply
except Exception:
    try:
        from guard_bridge import deliver_reply as _guard_deliver_reply
    except Exception:  # pragma: no cover
        _guard_deliver_reply = None
import pathlib as _pathlib
import sys as _sys


# 只在运行时按实际定义出来的名字导出：有些名字只在 fallback 分支里才有
__all__ = [n for n in list(globals()) if not n.startswith("__")]
