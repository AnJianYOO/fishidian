# -*- coding: utf-8 -*-
"""P0-1 / P0-2 / P0-3 验收：分层召回注入、置信三档、真引用回写。

护住三条规矩：
  ① 注入不再"按 R 取前 12"：身份层常驻 + 按这句话召回 + 最近 2 条兜底，且带置信标签；
  ② 只有回复里真的出现记忆的实体/数字才算引用（泛泛而谈不加分）；
  ③ 同一轮只加一条、同一 id 6 小时内不重复加——治"体检×2 双双升督脉"。
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fishidian_core import Governor, Store  # noqa: E402
from fishidian_core import config as C  # noqa: E402

PASS = []


def check(name, cond, detail=""):
    PASS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))


def make_gov(ns):
    tmp = tempfile.mkdtemp(prefix="fishidian_ctx_")
    return Governor(ns, store=Store(os.path.join(tmp, "c.db")))


def seed(g, texts):
    ids = []
    for t in texts:
        mid = g.pools.place_new(g.ns, t, 5.0, 2.0, 0.0, None)
        ids.append(mid)
    return ids


def pin(g, mid, r, tier):
    g.store.update_memory(mid, r=r, tier=tier)


def main():
    # ---- 1) 分层配额 ----
    g = make_gov("c1")
    ids = seed(g, ["我下周一要去医院体检", "我跟其他AI在黑曜石笔记里存了内容",
                   "公司这周活太多了", "昨天晚上把风扇拆了清灰", "一会儿睡"])
    pin(g, ids[0], 9.65, "du")
    pin(g, ids[1], 9.9, "du")
    pin(g, ids[2], 3.0, "yun")
    pin(g, ids[3], 1.6, "blood")
    pin(g, ids[4], 1.2, "blood")

    cx = g.build_context("", budget=600, ask_weather=False)
    layers = [p["layer"] for p in cx["items"]]
    confs = {p["id"]: p["conf"] for p in cx["items"]}
    check("无 query：督脉进身份层", layers.count("身份") >= 2 and confs.get(ids[0]) == "身份",
          f"layers={layers}")
    check("无 query：最近 2 条兜底", layers.count("最近") >= 2, f"layers={layers}")
    check("孕育层标为经历", Governor._conf_of({"r": 3.0, "tier": "yun"}) == "经历",
          f"yun={Governor._conf_of({'r': 3.0, 'tier': 'yun'})}")
    check("低 R 血海标为存疑", confs.get(ids[4]) == "存疑", f"blood={confs.get(ids[4])}")

    # ---- 2) query 召回进情境层（用不在身份层的相关记忆）----
    g2 = make_gov("c2")
    seed(g2, ["公司这周活太多了", "昨天晚上把风扇拆了清灰", "一会儿睡",
              "下周一要去医院体检", "体检报告放桌上了"])
    cx2 = g2.build_context("体检的事怎么样了", budget=600)
    texts = [p["text"] for p in cx2["items"] if p["layer"] == "情境"]
    check("query 相关记忆进情境层", any("体检" in t for t in texts), f"scene={texts}")

    # ---- 3) 预算 ----
    full = sum(len(p["text"]) + 26 for p in cx["items"])
    check("注入字符不超预算", full <= 600, f"chars={full}")

    # ---- 4) 真引用：真提了才加分 ----
    g4 = make_gov("c4")
    m4 = seed(g4, ["我下周一要去医院体检"])[0]
    pin(g4, m4, 5.0, "blood")
    r_before = float(g4.store.get_memory(m4)["r"])
    g4.observe_turn("在吗", "你不是说下周一要去医院体检吗，我记着呢", cited_ids=[str(m4)])
    r_after = float(g4.store.get_memory(m4)["r"])
    check("回复真提到实体 → adopt 加分", r_after > r_before, f"{r_before} → {r_after}")

    g5 = make_gov("c5")
    m5 = seed(g5, ["我下周一要去医院体检"])[0]
    pin(g5, m5, 5.0, "blood")
    r5a = float(g5.store.get_memory(m5)["r"])
    g5.observe_turn("在吗", "今天天气挺好的，你那边冷不冷", cited_ids=[str(m5)])
    check("泛泛而谈 → 不加分", float(g5.store.get_memory(m5)["r"]) == r5a,
          f"r={g5.store.get_memory(m5)['r']}")

    # ---- 5) 同题材两条，同轮只加一条 ----
    g6 = make_gov("c6")
    a = seed(g6, ["我下周一要去医院体检"])[0]
    b = seed(g6, ["体检这个事是为了测试你真的记住了"])[0]
    pin(g6, a, 8.0, "du")
    pin(g6, b, 9.0, "du")
    ra0, rb0 = float(g6.store.get_memory(a)["r"]), float(g6.store.get_memory(b)["r"])
    g6.observe_turn("嗯", "你不是要去医院体检吗，别糊弄我", cited_ids=[str(a), str(b)])
    ra1, rb1 = float(g6.store.get_memory(a)["r"]), float(g6.store.get_memory(b)["r"])
    check("同轮同题材只加一条", (ra1 > ra0) != (rb1 > rb0) or (ra1 == ra0 and rb1 == rb0),
          f"ra {ra0}→{ra1} rb {rb0}→{rb1}")

    # ---- 6) 冷却：同一条 6 小时内不重复加 ----
    g7 = make_gov("c7")
    m7 = seed(g7, ["我下周一要去医院体检"])[0]
    pin(g7, m7, 5.0, "blood")
    g7.observe_turn("在吗", "你不是要去医院体检吗", cited_ids=[str(m7)])
    r7a = float(g7.store.get_memory(m7)["r"])
    g7.observe_turn("在吗", "医院体检那个事别忘了", cited_ids=[str(m7)])
    check("同一条 6 小时内不重复加", float(g7.store.get_memory(m7)["r"]) == r7a,
          f"r={g7.store.get_memory(m7)['r']} 期待={r7a}")

    # ---- 7) 天气只按需 ----
    g8 = make_gov("c8")
    from fishidian_core import intel as _intel
    real_fetch = _intel.fetch_weather
    g8.store.set_kv("intel:city:c8", "武汉")
    g8.store.set_kv("intel:weather:c8", "")
    _intel.fetch_weather = lambda city: {"city": city, "temp_c": "18", "desc": "多云"}
    cx_no = g8.build_context("今天过得怎么样", ask_weather=False)
    cx_yes = g8.build_context("今天冷吗", ask_weather=True)
    check("没问天气 → 不给天气", cx_no["weather"] is None and "背景" not in cx_no["injection"],
          f"{cx_no['weather']}")
    check("问了天气 → 给天气", bool(cx_yes["weather"]), f"{cx_yes['weather']}")
    _intel.fetch_weather = real_fetch

    # ---- 8) 空库也给时间/状态（不再是"返回空"）----
    g9 = make_gov("c9")
    cx9 = g9.build_context("你好")
    check("空库也有时间与状态行", "（现在：" in cx9["injection"] and "当前状态" in cx9["injection"],
          f"{cx9['injection'][:70]}")

    ok_all = all(ok for _, ok, _ in PASS)
    print(f"\n== {sum(1 for _, o, _ in PASS if o)}/{len(PASS)} passed ==")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
