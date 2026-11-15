# -*- coding: utf-8 -*-
"""020 验收：记忆四档分级召回。

护住五条：
  ① 四档判据：active 高 sim=清楚 / archived 高 sim=一半 / archived 中 sim=印象 / 低 sim=忘；
  ② 一半档给残句（≤25 字，尽量在标点收住），印象档一个字原文都不给；
  ③ 沉底条目只读：不 touch（last_hit_at 不动）、不复活（status 仍是 archived）、不涨 R；
  ④ 不抢位：情境层第一条永远是清楚档，沉底只补位；
  ⑤ 开关关掉即退回二值召回。

负例是核心：'印象档不给原文' 和 '沉底不 touch' 这两条一旦破了，
四档就退化成'全忘了 / 全记得'，也就是这轮要修掉的二值问题本身。
"""
from __future__ import annotations

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fishidian_core import Governor, Store  # noqa: E402
from fishidian_core import config as C  # noqa: E402

PASS = []

# 三个 query 与文本的 sim 都按 bow 逐字词袋算过（门槛 FAINT_HALF_SIM=0.46、印象下界 0.38）：
#   alive   "我下周一要去医院体检"（含 体/检）→ 0.60+   清楚档
#   half    "去年体检的时候医生说我血脂高，今年单位组织体检排在周四下午三点"
#           （含 体×2 检×2，31 字）→ ≈0.478            一半档
#   sense   "体检的时候医生说没事"（含 体/检×1，9 字）→ ≈0.4472   印象档
#   gone    "今天股票又跌了心情很差"（无 体/检）→ 0.0       忘档
ALIVE = "我下周一要去医院体检"
HALF = "去年体检的时候医生说我血脂高，今年单位组织体检排在周四下午三点"
SENSE = "体检的时候医生说没事"
GONE = "今天股票又跌了心情很差"


def check(name, cond, detail=""):
    PASS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))


def make_gov(ns):
    tmp = tempfile.mkdtemp(prefix="fishidian_faint_")
    return Governor(ns, store=Store(os.path.join(tmp, "f.db")))


def seed(g, text, imp=1.0, archived=False):
    mid = g.pools.place_new(g.ns, text, imp, 1.0, 0.0, None)
    if archived:
        g.store.forget(mid)          # 走真实沉底路径，不手写 status
    return mid


def mem_of(g, mid):
    return [m for m in g.store.query_all(g.ns) if m["id"] == mid][0]


def main():
    # ---- 1) 四档判据 ----
    g = make_gov("f1")
    alive = seed(g, ALIVE)
    half = seed(g, HALF, archived=True)
    sense = seed(g, SENSE, archived=True)
    gone = seed(g, GONE, archived=True)

    cx = g.build_context("体检", budget=600)
    by_id = {p["id"]: p for p in cx["items"]}

    check("清楚档：active 条目进情境层且给全文",
          alive in by_id and by_id[alive]["faint"] is None
          and "体检" in by_id[alive]["text"], f"items={[p['id'] for p in cx['items']]}")
    check("一半档：沉底条目进情境层，标记为 half",
          half in by_id and by_id[half]["faint"] == "half",
          f"faint={by_id.get(half, {}).get('faint')}")
    check("一半档：残句 ≤ FAINT_HALF_CHARS",
          half in by_id and len(by_id[half]["text"]) <= C.FAINT_HALF_CHARS,
          f"len={len(by_id.get(half, {}).get('text', ''))}")
    check("一半档：不给后半截（后半的「周四下午三点」不出现）",
          half in by_id and "周四下午三点" not in by_id[half]["text"],
          f"text={by_id.get(half, {}).get('text')}")
    check("印象档：标记为 sense 且一个原文片段都不给",
          sense in by_id and by_id[sense]["faint"] == "sense"
          and "体检" not in by_id[sense]["text"] and "医生" not in by_id[sense]["text"]
          and "没事" not in by_id[sense]["text"],
          f"text={by_id.get(sense, {}).get('text')}")
    check("忘档：sim 低于地板，一条都不进",
          gone not in by_id, f"items={[p['id'] for p in cx['items']]}")

    # ---- 2) 注入文本里三档标签各自在场 ----
    inj = cx.get("injection") or ""
    check("注入文本带 [一半] 标签", "[一半]" in inj, inj[:300])
    check("注入文本带 [印象] 标签", "[印象]" in inj, inj[:300])
    check("注入文本提示一半档别补后半", "别把后半补出来" in inj, inj[:300])
    check("注入文本提示印象档别编细节", "别编任何细节" in inj, inj[:300])

    # ---- 3) 沉底只读：不 touch、不复活、不涨 R ----
    before = mem_of(g, half)
    g.build_context("体检", budget=600)
    after = mem_of(g, half)
    check("沉底不 touch：last_hit_at 未变",
          (before.get("last_hit_at") or 0) == (after.get("last_hit_at") or 0),
          f"{before.get('last_hit_at')} -> {after.get('last_hit_at')}")
    check("沉底不复活：status 仍是 archived", after["status"] == "archived", after["status"])
    check("沉底不涨 R：r 未变", float(before["r"]) == float(after["r"]),
          f"{before['r']} -> {after['r']}")

    # ---- 4) 不抢位：情境层第一条永远是清楚档 ----
    g2 = make_gov("f2")
    seed(g2, ALIVE)
    deep = seed(g2, HALF, archived=True)
    cx2 = g2.build_context("体检", budget=600)
    scene2 = [p for p in cx2["items"] if p["layer"] == "情境"]
    check("不抢位：情境层第一条是清楚档，沉底排在它后面",
          scene2 and scene2[0]["faint"] is None,
          f"scene={[(p['faint'], p['text'][:12]) for p in scene2]}")

    # ---- 5) 开关关掉即退回二值 ----
    old = C.FAINT_ON
    try:
        C.FAINT_ON = False
        g3 = make_gov("f3")
        seed(g3, HALF, archived=True)
        cx3 = g3.build_context("体检", budget=600)
        check("FAINT_ON=False：沉底条目完全不参与召回",
              all(p["faint"] is None for p in cx3["items"]),
              f"items={[(p['id'], p['faint']) for p in cx3['items']]}")
    finally:
        C.FAINT_ON = old

    # ---- 6) 残句切分：标点收住 / 无标点补省略号 / 短句原样 ----
    long_p = "今天加班到十点，地铁上站着睡着了，回家就躺下了，第二天还头疼"
    check("残句：有标点就在标点处收，不跨事件",
          Governor._faint_cut(long_p) == "今天加班到十点，地铁上站着睡着了，回家就躺下了，",
          Governor._faint_cut(long_p))
    long_np = "地铁上站着睡着了再走上楼买水回家洗澡躺下第二天还要上班"
    check("残句：没标点就补省略号",
          Governor._faint_cut(long_np).endswith("…")
          and len(Governor._faint_cut(long_np)) == C.FAINT_HALF_CHARS + 1,
          Governor._faint_cut(long_np))
    check("残句：本来就短就原样返回", Governor._faint_cut("累了") == "累了")

    # ---- 7) 门槛口径：一半门槛 = max(INJECT_MIN_SIM, FAINT_HALF_SIM, omega) ----
    g4 = make_gov("f4")
    seed(g4, HALF, archived=True)
    got = g4._recall_faint("体检", omega=0.15)
    check("bow：omega 低于地板时门槛取 0.46，这条算一半",
          bool(got) and got[0][2] == "half", f"got={got[:1]}")
    check("bge：omega 抬到 0.65 时这条不再够一半（门槛跟着抬）",
          not g4._recall_faint("体检", omega=0.65),
          f"got={g4._recall_faint('体检', omega=0.65)[:1]}")

    # ---- 8) 库外话题不能越过门槛（真实语料里 0.374 的那条是最难挡的）----
    g5 = make_gov("f5")
    seed(g5, "今天傍晚，把养了三年的多肉浇死了，心疼在面馆里。", archived=True)
    far = "今天股票又跌了，心情很差"
    check("库外话题：与「多肉浇死了」只共享两个字，挡在门槛外",
          not g5._recall_faint(far, omega=0.15),
          f"got={g5._recall_faint(far, omega=0.15)[:1]}")

    # ---- 9) 沉底区只增不减，候选池的 limit 不能沿用 query_all 的 5000 ----
    # 实测 8000 条库里沉底 7801 条，limit=5000 会让 2801 条永远进不了候选池，
    # 而且 ORDER BY r DESC 在 r 只有少数几档时同档内顺序不确定——丢哪批不可预测。
    import inspect
    dflt = inspect.signature(Store.query_archived).parameters["limit"].default
    check("query_archived 默认 limit 已越过 5000 的旧口径",
          dflt > 5000, f"limit={dflt}")
    check("query_archived 的 limit 形参真的生效",
          len(g.store.query_archived(g.ns, limit=2)) == 2,
          f"n={len(g.store.query_archived(g.ns, limit=2))}")

    ok = sum(1 for _, c, _ in PASS if c)
    total = len(PASS)
    print(f"\n{ok}/{total} passed")
    return 0 if ok == total else 1


if __name__ == "__main__":
    sys.exit(main())
