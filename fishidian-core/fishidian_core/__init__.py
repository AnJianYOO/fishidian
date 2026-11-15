# -*- coding: utf-8 -*-
"""fishidian_core —— 小鱼情感记忆治理内核（Python，零第三方依赖）。
供 DSH 插件（dsh-fishidian）通过本地服务/子进程调用。
设计来源：早期原型阶段跑通的那套机制与参数。"""
from __future__ import annotations

from . import mask as _mask
from .config import *
from .governor import Governor
from .scoring import score_text, neg_strength
from .store import Store

# v0.1.0 新增件（2026-11-11）：内心层 / 状态简报 / 人格条款 / 归脏
from .brief import StateSnapshot, compile_brief
from .echo import rule_echo, echo_from_store
from .guard import check_reply, register_promise, record_drift
from .organ import assign_organ
# v0.1.0 新增件（2026-11-11 第二批）：偏移自动检测 / 逆体质纠偏
from .drift import DriftTracker, detect, judge_tone, judge_silence, judge_expression, judge_proactive
from .regulate import suggest_stance
# v0.1.0 新增件（2026-11-11 第三批）：安慰决策
from .comfort import should_comfort, low_streak, detect_stop, hold_line
# v0.1.0 新增件（2026-11-12）：四档分级召回（清楚 / 一半 / 印象 / 忘）
# v0.1.0 新增件（2026-11-13）：心跳与环境输入源（env / tick / settle_gap / daemon）

__all__ = ["Governor", "Store", "score_text", "neg_strength", "mask_text",
           "StateSnapshot", "compile_brief",
           "rule_echo", "echo_from_store",
           "check_reply", "register_promise", "record_drift",
           "assign_organ",
           "DriftTracker", "detect", "judge_tone", "judge_silence",
           "judge_expression", "judge_proactive", "suggest_stance",
           "should_comfort", "low_streak", "detect_stop", "hold_line"]
mask_text = _mask.mask
__version__ = "0.1.0"
