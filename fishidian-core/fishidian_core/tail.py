# -*- coding: utf-8 -*-
"""fishidian_core.tail —— 去我执（γ_ego）+ 长尾保护（重要低频保底）"""
from __future__ import annotations

from . import config as C


def de_ego(emotion_contribution: float, abs_valence: float) -> float:
    """去我执：|v| ≥ 9.0 的极端记忆，情绪加成 ×(1-γ_ego)——不被单一执念拽走。"""
    if abs_valence >= 9.0:
        return emotion_contribution * (1 - C.GAMMA_EGO)
    return emotion_contribution


class TailGuard:
    """长尾保护：重要性 ≥ TAIL_IMP 的记忆，即使很久没人提起，衰减也不低于 TAIL_FLOOR。
    对应"肾藏志"——重要低频事件（如亲人生病）1200h 后仍 active。"""

    def protect(self, importance: float, age_h: float, r_decayed: float) -> float:
        if importance >= C.TAIL_IMP:
            return max(r_decayed, C.TAIL_FLOOR)
        return r_decayed
