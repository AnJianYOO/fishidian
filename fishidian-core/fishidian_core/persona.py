# -*- coding: utf-8 -*-
"""fishidian_core.persona —— 体质画像 P：慢演化、边界钳位、极端输入熔断保护"""
from __future__ import annotations

from . import config as C


class Persona:
    """P 四维：{髓海系数, 五志权重, 情志耦合度, 蓄泄节律}。
    全局一个（她是同一个人）；只随时间/长期证据慢演化，不被单次对话带跑。"""

    def __init__(self, store, ns="__global__"):
        self.store = store
        self.ns = ns
        raw = store.get_kv(f"persona:{ns}")
        if raw:
            vals = [float(x) for x in raw.split(",")]
            self.p = tuple(vals)
        else:
            self.p = C.P_INIT
            store.set_kv(f"persona:{ns}", ",".join(str(x) for x in self.p))

    @property
    def vector(self):
        return self.p

    def update(self, delta_p, at=None):
        """P 慢演化：p += LR_P·delta_p，边界钳位 [P_BOUNDS]。"""
        lo, hi = C.P_BOUNDS
        nxt = tuple(max(lo, min(hi, x + C.LR_P * d)) for x, d in zip(self.p, delta_p))
        self.p = nxt
        self.store.set_kv(f"persona:{self.ns}", ",".join(str(x) for x in nxt))

    def emotion_cap(self):
        """情绪敏感上限（对极端记忆的响应系数）：随 P 五志权重轻微浮动，不越 EMO_CAP。"""
        cap = C.EMO_CAP + 0.05 * self.p[1]
        return max(0.0, min(1.0, cap))

    def suggest_profile(self):
        """按 P 距离给出最近体质原型（平和/感性/理性）。"""
        d_peace = sum((a - b) ** 2 for a, b in zip(self.p, C.P_INIT))
        d_sens = sum((a - b) ** 2 for a, b in zip(self.p, C.P_SENS))
        d_ratio = sum((a - b) ** 2 for a, b in zip(self.p, C.P_RATIO))
        best = min([("平和", d_peace), ("感性", d_sens), ("理性", d_ratio)], key=lambda t: t[1])
        return best[0]
