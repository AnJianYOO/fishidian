# -*- coding: utf-8 -*-
"""2026-11-06 四项落地验收：wuxing_tag 落库 / 表达执行补偿 / 冷战递台阶 / 遗忘的表达

对应 02 §14.1–§14.3。这些断言要能证明"机制真的在跑"，
而不只是"改完没把老测试弄挂"。
"""
from __future__ import annotations

import os
import random
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fishidian_core import Governor, Store  # noqa: E402
from fishidian_core import config as C  # noqa: E402
from fishidian_core.wuxing import weak_tag  # noqa: E402

PASS = []


def check(name, cond, detail=""):
    PASS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))


def make_gov(ns):
    tmp = tempfile.mkdtemp(prefix="fishidian_land_")
    return Governor(ns, store=Store(os.path.join(tmp, "t.db"))), tmp


class _R:
    """固定随机源：验证"概率判中就一定递"这一支。"""

    def __init__(self, v):
        self.v = v

    def random(self):
        return self.v


def main():
    # ---------- 1) wuxing_tag 落库 ----------
    g, _ = make_gov("tag")
    # 直接经 place_new 验证 schema/add_memory 这条链路（绕开熔断，测的是落库本身）
    mid = g.pools.place_new("tag", "她说的那句展览名字", 3.0, 2.0, -1.0, None, wuxing_tag="金")
    m = g.store.get_memory(mid)
    check("新记忆带上了 wuxing_tag", bool(m.get("wuxing_tag")), str(m.get("wuxing_tag")))
    check("tag 值在五志词表内", m.get("wuxing_tag") in ("木", "火", "土", "金", "水"),
          m.get("wuxing_tag"))

    # 走真实一轮：无论这轮放行还是熔断，tag 都要在 events 留痕
    g.observe_turn("今天被老板当众骂了一顿，烦死了", "怎么回事，跟我说说。")
    rows = g.store._db.execute(
        "SELECT payload FROM events WHERE type='wuxing_tag'").fetchall()
    payloads = [r["payload"] for r in rows]
    check("真实一轮后 events 里有 tag 痕迹", len(payloads) >= 1, str(payloads[:2]))
    check("放行轮带 memory_id / 熔断轮带 skipped 标记（都能追到归属）",
          any('"mid"' in p and '"mid": null' not in p for p in payloads)
          or any("fuse" in p for p in payloads), str(payloads[:2]))
    check("覆盖率指标可读（state 里有 wuxing_tag_cov）",
          g.state().get("wuxing_tag_cov", 0) > 0, str(g.state().get("wuxing_tag_cov")))

    # 弱 tag：中性闲聊不染色，有情绪信号才兜底
    check("中性闲聊不贴弱 tag", weak_tag(1.5, 0.0)[0] is None)
    check("强负面 → 怒(木)", weak_tag(8.0, -6.0)[0] == "木", str(weak_tag(8.0, -6.0)))
    check("低强度负面 → 悲(金)", weak_tag(1.2, -1.0)[0] == "金", str(weak_tag(1.2, -1.0)))
    check("正面 → 喜(火)", weak_tag(2.0, 1.5)[0] == "火", str(weak_tag(2.0, 1.5)))

    # ---------- 2) 表达执行补偿（κ） ----------
    g2, _ = make_gov("kappa")
    for _ in range(C.EXPR_CAL_EVERY + 3):
        g2.build_context("上班的事")               # 每轮先下发要求，写 expr:lenreq
        g2.observe_turn("上班的事", "嗯，知道了，先这样吧。")   # 13 字，明显短于要求
    check("模型偏短 → κ 上调", g2.expr.kappa > 1.02, f"kappa={g2.expr.kappa:.3f}")
    check("κ 不越上界", g2.expr.kappa <= C.EXPR_KAPPA_MAX + 1e-9)
    rows = g2.store._db.execute(
        "SELECT payload FROM events WHERE type='expr_calibrate'").fetchall()
    check("校准落了一条审计事件", len(rows) >= 1, str(len(rows)))
    ex = g2.expr.derive(g2)
    check("derive 同时给出「她想说」与「下发要求」",
          ex["len_target"] > 0 and abs(ex["len_req"] - ex["len_target"] * ex["kappa"]) < 0.2,
          f"target={ex['len_target']} req={ex['len_req']} k={ex['kappa']}")
    check("hint 给长度区间、不写成单点硬指标",
          "字上下" not in ex["hint"] and "别回回都差不多长" in ex["hint"] and "可以破例" in ex["hint"], ex["hint"][:60])

    # 偏长时 κ 该往下走（双向有效）
    g3, _ = make_gov("kappa_long")
    for _ in range(C.EXPR_CAL_EVERY + 1):
        g3.build_context("聊聊")
        g3.observe_turn("聊聊", "这事儿说来话长，" + "我一句一句跟你讲清楚。" * 6)
    check("模型偏长 → κ 下调", g3.expr.kappa < 1.0, f"kappa={g3.expr.kappa:.3f}")

    # ---------- 3) 冷战递台阶 ----------
    g4, _ = make_gov("cold")
    cw = g4.coldwar
    cw.score = C.COLD_THETA_ENTER + 2.0
    cw.cold = True
    cw.deep = False
    cw.since = time.time() - 20 * 3600
    cw._save()
    st = cw.offer_state()
    check("浅伤 20h：进窗口", st["due"], str(st))
    check("浅伤概率在合理区（<0.35）", 0 < st["p"] < C.COLD_OFFER_P_MAX, str(st["p"]))
    check("rng 判中 → 会递", cw.should_offer(rng=_R(0.0)))
    check("rng 判不中 → 不递（不是每轮都开口）", not cw.should_offer(rng=_R(0.999)))
    cw.mark_offer()
    check("递过之后进冷却", cw.offer_state()["blocked"] == "cooldown")

    # 深层伤：等得更久、概率更低
    cw2 = g4.coldwar
    cw2.score = C.COLD_THETA_ENTER * 2.2
    cw2.cold = True
    cw2.deep = True
    cw2.since = time.time() - 30 * 3600
    cw2.store.set_kv("coldwar:offer_at:cold", "0")
    st2 = cw2.offer_state()
    check("深层伤等待期拉到 18h 档", st2["wait_h"] >= C.COLD_OFFER_WAIT_MAX - 0.5, str(st2["wait_h"]))
    check("深层伤概率被 deep 系数压低",
          st2["p"] < C.COLD_OFFER_P_MAX / (1.0 + 0.5 * (st2["D"] - 1.0)) + 1e-6, str(st2["p"]))

    # 刚进冷战（<6h）不递：不秒怂
    g5, _ = make_gov("cold5")
    g5.coldwar.score = C.COLD_THETA_ENTER + 1.0
    g5.coldwar.cold = True
    g5.coldwar.since = time.time() - 2 * 3600
    g5.coldwar._save()
    check("刚冷战 2h：不递（不秒怂）", g5.coldwar.offer_state()["blocked"] == "wait")

    # 注入层：给过倾向才落 cold_offer，并写进 inject_context 审计
    g6, _ = make_gov("cold6")
    g6.coldwar.score = C.COLD_THETA_ENTER + 2.0
    g6.coldwar.cold = True
    g6.coldwar.since = time.time() - 40 * 3600
    g6.coldwar._save()
    hit = False
    for _ in range(30):
        out = g6.build_context("在吗")
        if out.get("cold_offer"):
            hit = True
            check("递台阶倾向进了注入文本",
                  "不太想绷着" in out["injection"], out["injection"][-80:])
            break
    check("40h 浅伤：30 轮内至少触发一次递台阶", hit)
    if hit:
        rows = g6.store._db.execute(
            "SELECT payload FROM events WHERE type='cold_offer'").fetchall()
        check("递台阶落审计事件", len(rows) >= 1, str(len(rows)))

    # ---------- 4) 遗忘的表达 ----------
    g7, _ = make_gov("forget")
    g7.pools.place_new("forget", "好像提过一次什么展览，记不清了", 1.0, 0.6, 0.1, None)
    out = g7.build_context("上次那个展览到底叫什么")
    check("有存疑记忆 → 注入「记不清就直说」",
          "记不太清" in out["injection"], out["injection"][:120])
    g8, _ = make_gov("noforget")
    out8 = g8.build_context("随便聊聊")
    check("没有存疑记忆 → 不加这句（不啰嗦）", "记不太清" not in out8["injection"])
    check("没吵过架 → 不进递台阶判定", g8.coldwar.offer_state()["blocked"] == "not_cold")

    # ---------- 汇总 ----------
    ok = sum(1 for _, c, _ in PASS if c)
    print(f"\n== {ok}/{len(PASS)} passed ==")
    return 0 if ok == len(PASS) else 1


if __name__ == "__main__":
    sys.exit(main())
