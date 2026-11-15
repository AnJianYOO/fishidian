# -*- coding: utf-8 -*-
r"""模拟预演：① 表达执行补偿 ② 冷战递台阶触发。

用真实内核（Governor / Expression / ColdWar / config），数据是模拟的。
跑法：python -X utf8 tools\sim_expression_and_coldwar.py
"""
import os
import random
import statistics
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                "fishidian-core"))

from fishidian_core.store import Store            # noqa: E402
from fishidian_core.governor import Governor      # noqa: E402
from fishidian_core.expression import Expression  # noqa: E402
from fishidian_core.coldwar import ColdWar        # noqa: E402
from fishidian_core import config as C            # noqa: E402

# ---- 待定常量 ----
L_MIN, L_SPAN = 8, 40       # 内在倾向 length 0~1 → 8~48 字（她"想"说多少）
CAL_EVERY = 20
CAL_ETA = 0.15              # κ 学习率
KAPPA_MIN, KAPPA_MAX = 0.6, 1.8
T_WAIT_BASE, T_WAIT_MAX = 6.0, 24.0
P_MAX_BASE = 0.35
LAMBDA_H = 12.0


# ================= ① 表达：内在倾向 vs 执行补偿 =================
def run_expression(bias, calibrate, rounds=200, seed=7):
    """bias = 模型执行率（0.7 = 要求 10 字，实际只写 7 字）。

    关键：内在倾向 L* 是人格，不改；改的是下发给模型的要求 L_req = L*·κ。
    这样"她想说多少"不被模型能力反向篡改。
    """
    rnd = random.Random(seed)
    db = os.path.join(tempfile.gettempdir(), f"sim_expr_{bias}_{calibrate}.db")
    if os.path.exists(db):
        os.remove(db)
    store = Store(db)
    gov = Governor("sim:e", store=store)
    ex = Expression(store, "sim:e")
    kappa = 1.0
    hist = []

    for t in range(rounds):
        tag = rnd.choice(list(gov.wuxing.E.keys()))
        for k in gov.wuxing.E:
            gov.wuxing.E[k] = 0.0
        gov.wuxing.E[tag] = rnd.uniform(0.0, 0.8) * C.WUXING_CAP
        gov.coldwar.cold = rnd.random() < 0.15
        gov.coldwar.score = 60.0 if gov.coldwar.cold else 0.0

        d = ex.derive(gov)
        L_star = L_MIN + L_SPAN * d["length"]      # 她想说多少
        L_req = L_star * kappa                     # 下发要求
        L_a = max(2, round(L_req * bias * rnd.gauss(1.0, 0.18)))   # 模型实际
        hist.append({"L*": L_star, "L_a": L_a, "L_req": L_req, "k": kappa,
                     "len": d["length"]})

        if calibrate and (t + 1) % CAL_EVERY == 0:
            w = hist[-CAL_EVERY:]
            ratio = statistics.mean(x["L_a"] / x["L_req"] for x in w)   # 执行率
            kappa *= (1.0 + CAL_ETA * (1.0 - ratio))
            kappa = max(KAPPA_MIN, min(KAPPA_MAX, kappa))

    tail = hist[-60:]
    dL = statistics.mean(abs(x["L_a"] - x["L*"]) / x["L*"] for x in tail)
    bL = statistics.mean(x["L_a"] - x["L*"] for x in tail)
    return {"dL": dL, "bL": bL, "kappa": hist[-1]["k"], "hist": hist}


def show_expression():
    print("=" * 76)
    print("① 表达：内在倾向 L* = 8 + 40·length（人格，不改）；下发 L_req = L*·κ")
    print("   每 20 轮：κ ← κ·(1 + 0.15·(1 - 执行率))，钳在 0.6~1.8")
    print("=" * 76)
    print(f"{'场景':<28}{'|L_a-L*|/L*':>13}{'同向偏差(字)':>14}{'末次κ':>8}")
    rows = {}
    for bias, cal, name in ((0.70, False, "模型偏短30%·不补偿"),
                            (0.70, True, "模型偏短30%·补偿"),
                            (1.00, True, "模型无偏·补偿"),
                            (1.30, True, "模型偏长30%·补偿")):
        r = run_expression(bias, cal)
        rows[name] = r
        print(f"{name:<26}{r['dL']:>13.3f}{r['bL']:>+14.1f}{r['kappa']:>8.3f}")

    h = rows["模型偏短30%·补偿"]["hist"]
    print("\n补偿收敛轨迹（每 20 轮）：")
    print(f"{'轮次':>6}{'κ':>7}{'她想的L*':>11}{'下发L_req':>11}{'实际L_a':>10}{'差距':>9}")
    for s in range(0, 200, 20):
        w = h[s:s + 20]
        print(f"{s+20:>6}{w[-1]['k']:>7.3f}"
              f"{statistics.mean(x['L*'] for x in w):>11.1f}"
              f"{statistics.mean(x['L_req'] for x in w):>11.1f}"
              f"{statistics.mean(x['L_a'] for x in w):>10.1f}"
              f"{statistics.mean(abs(x['L_a']-x['L*'])/x['L*'] for x in w):>9.3f}")
    return rows


# ================= ② 冷战递台阶 =================
def conflict_count_to_cold(val=-0.8):
    db = os.path.join(tempfile.gettempdir(), "sim_cold_enter.db")
    if os.path.exists(db):
        os.remove(db)
    cw = ColdWar(Store(db), "sim:c")
    harm = C.COLD_HARM_BASE + abs(val)
    n = 0
    while not cw.cold and n < 30:
        n += 1
        cw.on_conflict(harm, True, is_deep=False)
    return n, cw.score


def simulate_offers(n=2000, wait_max=24.0, deep_k=0.5, seed=11):
    rnd = random.Random(seed)
    times, deep_times, shallow_times = [], [], []
    for _ in range(n):
        depth = rnd.uniform(1.0, 3.0)
        deep = rnd.random() < 0.25
        t_wait = T_WAIT_BASE + (wait_max - T_WAIT_BASE) * min(1.0, max(0.0, depth - 1.0))
        p_max = P_MAX_BASE / (1.0 + 0.5 * max(0.0, depth - 1.0))
        if deep and depth >= 2.0:
            p_max *= deep_k
        hit = None
        for h in range(1, 169):
            if h <= t_wait:
                continue
            p = p_max * (1.0 - pow(2.718281828, -(h - t_wait) / LAMBDA_H))
            if rnd.random() < p:
                hit = h
                break
        times.append(hit)
        if hit:
            (deep_times if (deep and depth >= 2.0) else shallow_times).append(hit)
    ok24 = sum(1 for t in times if t and t <= 24) / n
    ok72 = sum(1 for t in times if t and t <= 72) / n
    ok7d = sum(1 for t in times if t) / n
    med = statistics.median([t for t in times if t])
    deep24 = sum(1 for t in deep_times if t <= 24) / len(deep_times) if deep_times else 0.0
    return {"ok24": ok24, "ok72": ok72, "ok7d": ok7d, "med": med,
            "deep24": deep24,
            "shallow24": sum(1 for t in shallow_times if t <= 24) / len(shallow_times)}


def show_coldwar():
    print("\n" + "=" * 76)
    print("② 冷战递台阶：T_wait = 6 + (上限-6)·min(1,D-1)，p_max = 0.35/(1+0.5(D-1))")
    print("=" * 76)
    n, score = conflict_count_to_cold()
    print(f"真实内核：{n} 次有因负面冲突（val=-0.8）进冷战，score={score:.1f}（阈值 {C.COLD_THETA_ENTER:.0f}）")

    print(f"\n{'参数':<34}{'24h内':>8}{'72h内':>8}{'中位':>7}{'浅伤24h':>9}{'深层24h':>9}")
    for name, wm, dk in (("初值 上限24h / 深层×0.5", 24.0, 0.5),
                         ("调参 上限18h / 深层×0.6", 18.0, 0.6),
                         ("更软 上限12h / 深层×0.7", 12.0, 0.7)):
        r = simulate_offers(wait_max=wm, deep_k=dk)
        print(f"{name:<32}{r['ok24']*100:>7.1f}%{r['ok72']*100:>7.1f}%"
              f"{r['med']:>6.0f}h{r['shallow24']*100:>8.1f}%{r['deep24']*100:>8.1f}%")

    print("\n对照（无门控：p 恒 0.35/h，不看伤深）：")
    rnd = random.Random(5)
    first = []
    for _ in range(2000):
        hit = None
        for h in range(1, 169):
            if rnd.random() < 0.35:
                hit = h
                break
        first.append(hit)
    print(f"  24h 内 {sum(1 for t in first if t and t<=24)/2000*100:.1f}% · "
          f"中位 {statistics.median([t for t in first if t]):.0f}h · "
          f"深浅伤无区别 —— 第一次就低头，等于没脾气")


if __name__ == "__main__":
    show_expression()
    show_coldwar()
