# -*- coding: utf-8 -*-
"""fishidian_core.proactive —— 自由主动性（17 号 §6）。
无外部配额：发不发 / 发什么由记忆 + 状态判定；自我收敛（quiet 态）。
按 ns 持久化（kv）：sent 计数、recent 检查窗口。
"""
from __future__ import annotations

import time

from . import config as C


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


class Proactive:
    def __init__(self, store, ns):
        self.store = store
        self.ns = ns
        raw_sent = self.store.get_kv(f"proactive:sent:{ns}")
        self.sent = int(raw_sent) if raw_sent is not None else 0
        raw_recent = self.store.get_kv(f"proactive:recent:{ns}")
        if raw_recent:
            self.recent = [int(x) for x in raw_recent.split(",")]
        else:
            self.recent = []
        self.quiet = self.store.get_kv(f"proactive:quiet:{ns}") == "1"
        # 日配额与最小间隔（v0.21 尾修）：desire 在阈值上不等于"可以发"。
        # 记「哪一天 + 当天发了几个」与「上次真正发出的时刻」，两者都由 deliver=True 推进。
        raw_daily = self.store.get_kv(f"proactive:daily:{ns}") or ""
        self.daily_day = ""
        self.daily_count = 0
        if raw_daily:
            parts = raw_daily.split()
            if len(parts) == 2:
                self.daily_day = parts[0]
                try:
                    self.daily_count = int(parts[1])
                except ValueError:
                    self.daily_count = 0
        raw_last = self.store.get_kv(f"proactive:last_at:{ns}")
        try:
            self.last_at = float(raw_last) if raw_last else 0.0
        except ValueError:
            self.last_at = 0.0

    def _save(self):
        self.store.set_kv(f"proactive:sent:{self.ns}", str(self.sent))
        self.store.set_kv(f"proactive:recent:{self.ns}", ",".join(str(x) for x in self.recent[-20:]))
        self.store.set_kv(f"proactive:quiet:{self.ns}", "1" if self.quiet else "0")
        self.store.set_kv(f"proactive:daily:{self.ns}", f"{self.daily_day} {self.daily_count}")
        self.store.set_kv(f"proactive:last_at:{self.ns}", f"{self.last_at:.0f}")

    def _quota(self, now):
        """返回 (剩余配额是否还有, 距上次是否够远, 今天已发几次)。跨天自动归零。"""
        day = time.strftime("%Y%m%d", time.localtime(now))
        if day != self.daily_day:
            self.daily_day = day
            self.daily_count = 0
        cap_ok = C.PROACTIVE_DAILY_CAP <= 0 or self.daily_count < C.PROACTIVE_DAILY_CAP
        gap = C.PROACTIVE_MIN_GAP_H * 3600.0
        gap_ok = gap <= 0 or self.last_at <= 0 or (now - self.last_at) >= gap
        return cap_ok, gap_ok

    def _factors(self, gov):
        """三项状态因子（0~1）：
        关切：近期高 importance 记忆条数（最近 7 天）
        久未联络：ns 最近用户回合距现在时长归一（48h 阈值）
        情绪：五行 E 的「情绪显著度」——任一情志强（无论正负/哪种心情）都算显著。
              默认取峰值 max(E)/cap；旧口径 ΣE/cap÷2 由 PROACTIVE_MOOD_PEAK=False 保留。"""
        concern = 0.0
        win = C.PROACTIVE_CONCERN_DAYS * 86400.0
        now = time.time()
        mems = gov.store.query_all(self.ns, limit=200)
        recent_imp = [m for m in mems if m["status"] == "active"
                      and m["importance"] >= C.PROACTIVE_CONCERN_IMP
                      and now - m["born_at"] <= win]
        concern = min(1.0, len(recent_imp) / 2.0)
        absent_h = 0.0
        last = gov.store.get_kv(f"ns:last_user:{self.ns}")
        if last:
            absent_h = (now - float(last)) / 3600.0
        absent = min(1.0, absent_h / C.PROACTIVE_LONG_ABSENT_H)
        mood = 0.0
        if hasattr(gov, "wuxing") and gov.wuxing.E:
            # 用 effective_E（按时间消退后的此刻情绪），而不是存储里的原始累积值。
            # 用原始值等于用"上一次聊天留下的情绪残量"：E 只在 on_event 才衰减，
            # 没人说话时就冻在满值，mood 恒 1.0 → 愿望值恒 ≥ 阈值 → 每小时都判"该发"。
            eff = gov.wuxing.effective_E() if hasattr(gov.wuxing, "effective_E") else gov.wuxing.E
            if C.PROACTIVE_MOOD_PEAK:
                mood = min(1.0, max(eff.values()) / C.WUXING_CAP)
            else:
                s = sum(eff.values()) / C.WUXING_CAP
                mood = min(1.0, s / C.PROACTIVE_MOOD_DIV)
        return concern, absent, mood

    def _familiarity(self, gov):
        """熟悉程度（0~1）：关系温度 + 活跃记忆积累。刚认识低，相处久高。"""
        temp = 0.55
        if hasattr(gov, "coldwar"):
            cw = gov.coldwar.snapshot()
            temp = C.PROACTIVE_FAM_TEMP.get(cw.get("temperature"), 0.55)
        mems = [m for m in gov.store.query_all(self.ns, limit=200)
                if m["status"] == "active"]
        fam_mem = min(1.0, len(mems) / C.PROACTIVE_FAM_MEM_TARGET)
        return clamp(C.PROACTIVE_FAM_BASE
                     + C.PROACTIVE_FAM_TEMP_W * temp
                     + C.PROACTIVE_FAM_MEM_W * fam_mem, 0.0, 1.0)

    def check(self, gov, at=None, deliver=None):
        """主动性判定：desire = W_CONCERN·关切 + W_ABSENT·久未联络 + W_MOOD·情绪显著度；
        quiet 时 ×PROACTIVE_QUIET_MUL。返回 {should_act, desire, factors, quiet, sent}。

        deliver（M1 记账修正）：**判定 ≠ 真的发出去了**。
          None  → 只探测，不推进窗口（CLI/查看用，零副作用）
          True  → 真发出去了 → sent+=1、窗口记 1
          False → 想发但没发（autosend 关 / 发送失败）→ 只记 0，不记"主动成功"
        旧实现不分这两种，autosend=false 时也 self.sent+=1 —— 会把"想发"记成"发过"，
        进而误推 quiet（越判定越沉默）。"""
        at = at if at is not None else time.time()
        concern, absent, mood = self._factors(gov)
        desire = (C.PROACTIVE_W_CONCERN * concern
                  + C.PROACTIVE_W_ABSENT * absent
                  + C.PROACTIVE_W_MOOD * mood)
        if self.quiet:
            desire *= C.PROACTIVE_QUIET_MUL
        # 配额闸：desire 够高 ≠ 可以发。每天最多 PROACTIVE_DAILY_CAP 次、
        # 两次之间至少 PROACTIVE_MIN_GAP_H 小时 —— 否则插件每小时判定一次就发一条，
        # 实际运行中出现过整天反复发同一句问候。
        cap_ok, gap_ok = self._quota(at)
        act = desire >= C.PROACTIVE_THETA and cap_ok and gap_ok
        if deliver is True and act:
            self.sent += 1
            self.recent.append(1)
            self.daily_count += 1
            self.last_at = at
            gov.store.log_event(self.ns, "proactive_act",
                                {"desire": round(desire, 3), "concern": round(concern, 3),
                                 "absent": round(absent, 3), "mood": round(mood, 3),
                                 "daily": self.daily_count})
        elif deliver is not None:
            # 想发却没发成 / 这一轮压根没到阈值：只记 0，绝不记成"主动成功"
            self.recent.append(0)
            if deliver is True:
                gov.store.log_event(self.ns, "proactive_skip",
                                    {"desire": round(desire, 3), "should_act": act})
        # deliver=None：只算不记，窗口不动（探测/命令查看不该污染收敛曲线）
        # 自我收敛：窗口按情绪+熟悉程度动态；最近 cool 次全主动 → quiet；quiet 且最近 <2 次主动 → 解除
        fam = self._familiarity(gov)
        cool = int(round(clamp(C.PROACTIVE_COOL_BASE
                               + C.PROACTIVE_COOL_FAM_W * fam
                               - C.PROACTIVE_COOL_MOOD_W * mood,
                               C.PROACTIVE_COOL_MIN, C.PROACTIVE_COOL_MAX)))
        if len(self.recent) >= cool and sum(self.recent[-cool:]) >= cool:
            self.quiet = True
        elif self.quiet and len(self.recent) >= cool and sum(self.recent[-cool:]) < 2:
            self.quiet = False
        self._save()
        return {
            "should_act": act,
            "desire": round(desire, 3),
            "theta": C.PROACTIVE_THETA,
            "factors": {"concern": round(concern, 3), "absent": round(absent, 3), "mood": round(mood, 3)},
            "familiarity": round(fam, 3),
            "cool": cool,
            "quiet": self.quiet,
            "sent": self.sent,
            "quota": {
                "today": self.daily_count,
                "cap": C.PROACTIVE_DAILY_CAP,
                "cap_ok": cap_ok,
                "gap_ok": gap_ok,
                "gap_h": C.PROACTIVE_MIN_GAP_H,
            },
        }
