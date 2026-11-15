# -*- coding: utf-8 -*-
"""fishidian_core.throttle —— 中庸节流：θ_节（单条封顶）+ θ_和（累计过载）+ 节律 ω 呼吸"""
from __future__ import annotations

import math

from . import config as C


def omega_at(t_hour: float, backend: str = "bow") -> float:
    """当位门控阈值：ω = 基准 × (1 + amp·sin(2π(t-off)/T))。
    波峰收紧（0.165 模拟 / 0.715 bge），波谷放宽（0.135 / 0.585）。"""
    base = C.OMEGA_MIN if backend == "bow" else 0.65
    return base * (1 + C.RHYTHM_AMP * math.sin(2 * math.pi * (t_hour - C.RHYTHM_OFF) / C.RHYTHM_T))


def throttle_single(emotion_contribution: float) -> float:
    """θ_节：单条记忆对情绪响应的贡献封顶（正负双向，负向同样受限）。"""
    return max(-C.THETA_JIE, min(emotion_contribution, C.THETA_JIE))


def throttle_total(accumulated: float, budget: float = 1.0) -> float:
    """θ_和：本轮累计情绪贡献过载 → 节泄（超额砍半），硬顶 budget。"""
    if accumulated <= C.THETA_HE:
        return accumulated
    excess = accumulated - C.THETA_HE
    return C.THETA_HE + excess * 0.5


class Throttle:
    """节流状态机（按 ns 存本轮累计）。"""

    def __init__(self, store, ns):
        self.store = store
        self.ns = ns

    def reset_turn(self):
        self.store.set_kv(f"throttle:turn:{self.ns}", "0")

    def _turn_acc(self):
        try:
            return float(self.store.get_kv(f"throttle:turn:{self.ns}", "0"))
        except Exception:
            return 0.0

    def apply(self, emotion_contributions, t_hour=12.0, backend="bow"):
        """输入：本条被采纳记忆的情绪贡献列表；输出：治理后总贡献 + 单条明细。"""
        self.reset_turn()
        capped = [throttle_single(c) for c in emotion_contributions]
        total = throttle_total(sum(capped))
        self.store.set_kv(f"throttle:turn:{self.ns}", str(total))
        return {"total": round(total, 4), "per_item": [round(c, 4) for c in capped],
                "omega": round(omega_at(t_hour, backend), 4)}
