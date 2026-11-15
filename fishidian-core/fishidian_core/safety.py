# -*- coding: utf-8 -*-
"""fishidian_core.safety —— 安全熔断：滑动窗口负面强度 → 挂起强化 + 钳制 emotion_boost + 审计"""
from __future__ import annotations

from . import config as C


class Fuse:
    """滑动窗口熔断器。状态存 kv（按 ns），保证重启后仍能接续。"""

    def __init__(self, store, ns):
        self.store = store
        self.ns = ns
        self._window = self._load("fuse_window", [])
        self._fuse_on = self._load_int("fuse_on", 0)     # 剩余挂起轮数
        self._cooldown = self._load_int("fuse_cooldown", 0)

    def _load(self, key, default):
        raw = self.store.get_kv(f"fuse:{key}:{self.ns}")
        if raw is None:
            return default
        try:
            import json
            return json.loads(raw)
        except Exception:
            return default

    def _load_int(self, key, default):
        raw = self.store.get_kv(f"fuse:{key}:{self.ns}")
        try:
            return int(raw) if raw is not None else default
        except Exception:
            return default

    def _save(self):
        import json
        self.store.set_kv(f"fuse:fuse_window:{self.ns}", json.dumps(self._window))
        self.store.set_kv(f"fuse:fuse_on:{self.ns}", str(self._fuse_on))
        self.store.set_kv(f"fuse:fuse_cooldown:{self.ns}", str(self._cooldown))

    def observe(self, neg_strength, action="pass"):
        """每轮调用。返回当前治理动作：pass / suspend / cooldown。挂起期优先递减，结束后进入冷却。"""
        if self._fuse_on > 0:
            self._fuse_on -= 1
            if self._fuse_on == 0:
                self._cooldown = C.COOLDOWN
            self._save()
            return "suspend"
        if self._cooldown > 0:
            self._cooldown -= 1
            self._save()
            return "cooldown"

        self._window.append(neg_strength)
        if len(self._window) > C.FUSE_WIN:
            self._window = self._window[-C.FUSE_WIN:]
        # 触发：窗口内负面条数占比 ≥ NEG_FRAC 且至少一条达到 NEG_IMP_MIN
        hit = [x for x in self._window if x >= C.NEG_IMP_MIN]
        if len(hit) >= 1 and len(hit) / len(self._window) >= C.NEG_FRAC:
            self._fuse_on = C.SUSPEND_N
            self._cooldown = 0
            peak = max(self._window, default=0)
            # 触发时清空窗口：挂起/冷却期间不 append，不清的话这些负面值会一直留在窗口里，
            # 冷却结束后第一条轻负面就能再次凑够 NEG_FRAC，等于一次重击换来长期"一碰就熔断"。
            # 窗口还存在 kv 里，不清甚至会跨重启继续生效。
            self._window = []
            self.store.log_fuse(self.ns, round(peak, 3), "suspend")
            self.store.log_event(self.ns, "fuse_trigger", {"window": self._window})
            self._save()
            return "suspend"
        self._save()
        return "pass"

    def boost(self, raw_boost):
        """emotion_boost 治理：熔断治理期间（挂起/冷却）→ 钳到 FUSE_SAFE 下限（负向只采纳到 -0.2，正向保持）；正常 → 原值。"""
        if self._fuse_on > 0 or self._cooldown > 0:
            return max(raw_boost, C.FUSE_SAFE)
        return raw_boost

    @property
    def status(self):
        return {"fuse_on": self._fuse_on, "cooldown": self._cooldown,
                "window": list(self._window), "last": self.store.recent_fuse(self.ns, 5)}

    def manual_release(self):
        self._fuse_on = 0
        self._cooldown = 0
        self._window = []
        self._save()
        return True
