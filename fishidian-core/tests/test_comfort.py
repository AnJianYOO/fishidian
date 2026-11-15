# -*- coding: utf-8 -*-
"""安慰决策（comfort.py）纯函数断言。

重心在**负例**：一个总是想安慰人的系统比不安慰更糟——它会把“我一难过她
就来哄我”变成客服感。所以这里大半在测“什么都不做”。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fishidian_core.comfort import should_comfort, low_streak, detect_stop
import fishidian_core.config as C

P = 0
F = []


def ok(name, cond):
    global P
    if cond:
        P += 1
    else:
        F.append(name)


NOW = 1_700_000_000.0
H = 3600.0
D = 86400.0

# ---------- detect_stop ----------
ok("detect_stop 命中", detect_stop("你别管我行吗") == "别管我")
ok("detect_stop 未命中", detect_stop("今天天气不错") is None)
ok("detect_stop 空串", detect_stop("") is None)
ok("detect_stop None", detect_stop(None) is None)

# ---------- low_streak ----------
ok("连续2天低算成立", low_streak([0.1, -0.4, -0.3]) is True)
ok("只有1天低不算", low_streak([0.1, 0.2, -0.4]) is False)
ok("中间正常不算", low_streak([-0.4, 0.3, -0.3]) is False)
ok("缺天在尾部之外不影响", low_streak([None, -0.4, -0.3]) is True)
ok("尾部缺天不算连续", low_streak([-0.4, None, -0.3]) is False)
ok("样本不足不判", low_streak([-0.5]) is False)
ok("空列表不判", low_streak([]) is False)

# ---------- should_comfort 负例 ----------
ok("冷战：不碰", should_comfort(mood_hist=[-0.4, -0.3], cold_war=True, now=NOW)["mode"] == "none")
ok("说了别管我：不碰",
   should_comfort(mood_hist=[-0.4, -0.3], stop_at=NOW + 10 * H, now=NOW)["mode"] == "none")
ok("别管我已过期：可以碰",
   should_comfort(mood_hist=[-0.4, -0.3], stop_at=NOW - H, now=NOW, last_comfort_at=None)["mode"] != "none")
ok("今天配额用完：不碰",
   should_comfort(mood_hist=[-0.4, -0.3], today_count=C.COMFORT_DAILY_CAP, now=NOW)["mode"] == "none")
ok("冷却中：不碰",
   should_comfort(mood_hist=[-0.4, -0.3], last_comfort_at=NOW - H, now=NOW)["mode"] == "none")
ok("只低落一天：不碰",
   should_comfort(mood_hist=[0.2, 0.1, -0.4], now=NOW)["mode"] == "none")
ok("他其实不低：不碰",
   should_comfort(mood_hist=[0.2, 0.3, -0.1], now=NOW)["mode"] == "none")
ok("没有历史：不碰", should_comfort(mood_hist=None, now=NOW)["mode"] == "none")
ok("空历史：不碰", should_comfort(mood_hist=[], now=NOW)["mode"] == "none")

# ---------- should_comfort 正例 ----------
ok("连续低 + 在说话：hold",
   should_comfort(mood_hist=[-0.4, -0.3], silent_h=2.0, now=NOW)["mode"] == "hold")
ok("连续低 + 沉默很久：touch",
   should_comfort(mood_hist=[-0.4, -0.3], silent_h=C.COMFORT_SILENT_H + 1, now=NOW)["mode"] == "touch")
ok("silent_h 缺失也能 hold",
   should_comfort(mood_hist=[-0.4, -0.3], silent_h=None, now=NOW)["mode"] == "hold")

# ---------- 最低在场：能突破配额和冷却 ----------
r = should_comfort(mood_hist=[-0.4, -0.3],
                   last_comfort_at=NOW - (C.COMFORT_FLOOR_DAYS + 1) * D,
                   today_count=C.COMFORT_DAILY_CAP, now=NOW)
ok("最低在场突破配额", r["mode"] == "touch" and r.get("floor") is True)

r2 = should_comfort(mood_hist=[-0.4, -0.3],
                    last_comfort_at=NOW - (C.COMFORT_FLOOR_DAYS + 1) * D,
                    now=NOW)
ok("最低在场也突破冷却", r2["mode"] == "touch")

r3 = should_comfort(mood_hist=[0.3, 0.2],
                    last_comfort_at=NOW - (C.COMFORT_FLOOR_DAYS + 1) * D,
                    now=NOW)
ok("最低在场只管低落的人，不低不扰", r3["mode"] == "none")

# ---------- 优先级：冷战 > 最低在场 ----------
r4 = should_comfort(mood_hist=[-0.4, -0.3], cold_war=True,
                    last_comfort_at=NOW - 10 * D, now=NOW)
ok("冷战优先级高于最低在场", r4["mode"] == "none")

# ---------- 每种结果都带 reason ----------
for args in ({"mood_hist": [-0.4, -0.3]}, {"mood_hist": None}, {"cold_war": True}):
    ok("reason 非空 %s" % list(args), bool(should_comfort(now=NOW, **args).get("reason")))

# ---------- 参数可注入（不读时钟） ----------
a = should_comfort(mood_hist=[-0.4, -0.3], now=NOW)
b = should_comfort(mood_hist=[-0.4, -0.3], now=NOW)
ok("同输入同输出", a == b)

print("== %d/%d passed ==" % (P, P + len(F)))
if F:
    for n in F:
        print("  FAIL:", n)
    sys.exit(1)
