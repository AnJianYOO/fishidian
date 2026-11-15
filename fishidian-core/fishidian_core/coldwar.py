# -*- coding: utf-8 -*-
"""fishidian_core.coldwar —— 冷战 / 疏离状态机（17 号 §5）。
有因冲突放行（人味）、无因冲突拒绝（安全）；有上限（衰减）、有出口（和解）。
按 ns 持久化（kv），时间衰减按自然天数。
"""
from __future__ import annotations

import math
import random
import time

from . import config as C


# 和解事件词表（道歉 / 主动关心）
HEAL_LEX = ["对不起", "抱歉", "我错了", "别生气", "是我不好", "请你原谅", "原谅我", "认错",
            "道歉", "哄", "抱抱", "别难过", "想你了", "别不理", "我改", "以后不会", "在乎你"]


def is_heal(text):
    if not text:
        return False
    return any(w in text for w in HEAL_LEX)


class ColdWar:
    """冲突度 score → 冷战态（冷淡、简短、不主动）；退出：和解 / 时间衰减（深层更慢）。"""

    def __init__(self, store, ns):
        self.store = store
        self.ns = ns
        raw = self.store.get_kv(f"coldwar:score:{ns}")
        self.score = float(raw) if raw is not None else 0.0
        self.cold = self.store.get_kv(f"coldwar:cold:{ns}") == "1"
        self.deep = self.store.get_kv(f"coldwar:deep:{ns}") == "1"
        raw_t = self.store.get_kv(f"coldwar:last_tick:{ns}")
        self.last_tick = float(raw_t) if raw_t is not None else time.time()
        raw_s = self.store.get_kv(f"coldwar:since:{ns}")
        self.since = float(raw_s) if raw_s else 0.0        # 本次冷战进入时刻（递台阶计时起点）

    def _save(self):
        self.store.set_kv(f"coldwar:score:{self.ns}", f"{self.score:.4f}")
        self.store.set_kv(f"coldwar:cold:{self.ns}", "1" if self.cold else "0")
        self.store.set_kv(f"coldwar:deep:{self.ns}", "1" if self.deep else "0")
        self.store.set_kv(f"coldwar:last_tick:{self.ns}", f"{self.last_tick:.3f}")
        self.store.set_kv(f"coldwar:since:{self.ns}", f"{self.since:.3f}")

    def _tick(self, at=None):
        """按经过天数做时间衰减（普通 10%/天、深层 2%/天）。"""
        at = at if at is not None else time.time()
        days = max(0.0, (at - self.last_tick) / 86400.0)
        if days <= 0:
            return
        lam = C.COLD_DECAY_DEEP if self.deep else C.COLD_DECAY
        self.score *= (1.0 - lam) ** days
        if self.cold and self.score < C.COLD_THETA_EXIT:
            self.cold = False
            self.since = 0.0
            # deep 必须跟着一起清：否则一次深伤会让衰减永久停在 2%/天，台阶也一直 6 折。
            # 和解分支（on_heal）清了 deep，时间退出这条漏了。
            self.deep = False
            self.store.log_event(self.ns, "coldwar_exit", {"reason": "time", "score": round(self.score, 2)})
        self.last_tick = at

    def on_conflict(self, harm, has_cause, is_deep=False, at=None):
        """冲突事件：无因拒绝（不升分，审计）；有因累积。返回 {state, score}。"""
        at = at if at is not None else time.time()
        self._tick(at)
        if not has_cause:
            self.store.log_event(self.ns, "coldwar_reject", {"harm": round(harm, 2)})
            return self.snapshot()
        self.score += harm
        self.deep = self.deep or is_deep
        if self.score >= C.COLD_THETA_ENTER and not self.cold:
            self.cold = True
            self.since = at if self.since <= 0 else self.since
            self.store.log_event(self.ns, "coldwar_enter",
                                 {"score": round(self.score, 2), "deep": self.deep})
        self._save()
        return self.snapshot()

    def on_heal(self, amt=None, at=None):
        """和解事件：减分；冷战态下 score 跌破出口阈值 → 退出。"""
        at = at if at is not None else time.time()
        self._tick(at)
        self.score -= amt if amt is not None else C.COLD_HEAL
        self.score = max(0.0, self.score)
        exited = False
        if self.cold and self.score < C.COLD_THETA_EXIT:
            self.cold = False
            self.deep = False
            self.since = 0.0
            exited = True
            self.store.log_event(self.ns, "coldwar_exit", {"reason": "heal", "score": round(self.score, 2)})
        self._save()
        return self.snapshot(exited=exited)

    # ---------- 主动递台阶（02 §14.2） ----------
    def offer_state(self, now=None):
        """这一轮她要不要先递个话：等待期 + 概率 + 冷却，任一条不满足就不递。
        D = score / 进冷战阈值；伤越深等得越久、概率越低；deep 且 D≥2 再打折。"""
        now = now if now is not None else time.time()
        d = max(1.0, self.score / C.COLD_THETA_ENTER) if C.COLD_THETA_ENTER else 1.0
        wait_h = C.COLD_OFFER_WAIT_MIN + (C.COLD_OFFER_WAIT_MAX - C.COLD_OFFER_WAIT_MIN) * min(1.0, d - 1.0)
        p_max = C.COLD_OFFER_P_MAX / (1.0 + 0.5 * (d - 1.0))
        if self.deep and d >= 2.0:
            p_max *= C.COLD_OFFER_DEEP_K
        out = {"due": False, "p": 0.0, "D": round(d, 2), "wait_h": round(wait_h, 1),
               "hours": 0.0, "blocked": None}
        if not self.cold:
            out["blocked"] = "not_cold"
            return out
        hours = max(0.0, (now - self.since) / 3600.0) if self.since else 0.0
        out["hours"] = round(hours, 1)
        try:
            last = float(self.store.get_kv(f"coldwar:offer_at:{self.ns}") or 0.0)
        except Exception:
            last = 0.0
        if last and (now - last) < C.COLD_OFFER_COOLDOWN_H * 3600:
            out["blocked"] = "cooldown"
            return out
        if hours <= wait_h:
            out["blocked"] = "wait"
            return out
        p = p_max * (1.0 - math.exp(-(hours - wait_h) / C.COLD_OFFER_LAMBDA_H))
        out["p"] = round(p, 4)
        out["due"] = p > 0
        return out

    def should_offer(self, now=None, rng=None):
        """概率判定（每小时判一次；2000 次模拟口径见 02 §14.2）。"""
        st = self.offer_state(now)
        if not st["due"]:
            return False
        rnd = rng if rng is not None else random
        return rnd.random() < st["p"]

    def mark_offer(self, now=None):
        """已经递过 → 记冷却（24h 内不再递）。"""
        now = now if now is not None else time.time()
        self.store.set_kv(f"coldwar:offer_at:{self.ns}", f"{now:.3f}")
        self.store.log_event(self.ns, "cold_offer",
                             {"score": round(self.score, 2),
                              "since_h": round((now - self.since) / 3600.0, 1) if self.since else 0})
        return {"ok": True}

    def snapshot(self, exited=False):
        """关系温度（§7 画像：疏离 / 缓和 / 亲近 三档）。"""
        if not self.cold:
            if self.score > C.COLD_THETA_EXIT:
                temp = "缓和" if self.score > 0 else "亲近"
            else:
                temp = "亲近" if self.score <= 0 else "缓和"
        else:
            temp = "疏离"
        return {
            "cold": self.cold,
            "score": round(self.score, 2),
            "deep": self.deep,
            "temperature": temp,
            "exited": exited,
        }
