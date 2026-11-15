# -*- coding: utf-8 -*-
"""表达层「非规定性」验收（测试先行）。

要护住的两条底线：
  ① 五行/情绪 → 表达，只能是「分布与强度」，不能是 1:1 的固定台词表；
     同一状态多次取，说法要有变化；情绪能量为 0 时不该硬叠情绪色彩。
  ② 口头禅只能从对话里长出来（夸奖吸收 / 用户示范 / 纠正降温），
     池子初始必须为空；检索不能永远只回同一个 Top1。
"""
from __future__ import annotations

import os
import random
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fishidian_core import Store  # noqa: E402
from fishidian_core import config as C  # noqa: E402
from fishidian_core.expression import Expression, TONE_BY_TEMP  # noqa: E402

try:  # 改造后才有：情绪语气维度池（low / high 两档）
    from fishidian_core.expression import TONE_DIM
except ImportError:  # 改造前是单句文案表 TONE_BY_EMOTION
    TONE_DIM = {}

PASS = []
EMO_KEYS = ("木", "火", "土", "金", "水")

# 情绪语气词的词根（用于判断"平静时是否硬叠情绪色彩"）
EMO_ROOTS = ("火气", "冲", "刺", "不耐烦", "轻快", "热情", "话密", "低沉", "沉",
             "稳", "压下", "软", "发虚", "绷", "低落", "亢奋")


def check(name, cond, detail=""):
    PASS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))


class FakeWuxing:
    def __init__(self, e=None, w=(0.2, 0.2, 0.2, 0.2, 0.2)):
        self.E = e or {k: 0.0 for k in EMO_KEYS}
        self.W = w


class FakeColdWar:
    def __init__(self, temperature="亲近", cold=False):
        self._s = {"temperature": temperature, "cold": cold}

    def snapshot(self):
        return dict(self._s)


class FakeGov:
    def __init__(self, e=None, w=(0.2, 0.2, 0.2, 0.2, 0.2), temperature="亲近", cold=False):
        self.wuxing = FakeWuxing(e, w)
        self.coldwar = FakeColdWar(temperature, cold)


def make_expr(ns):
    tmp = tempfile.mkdtemp(prefix="fishidian_expr_")
    return Expression(Store(os.path.join(tmp, "e.db")), ns)


def main():
    # 1) 池子初始必须为空：口头禅不许预设
    ex = make_expr("e1")
    check("口癖池初始为空（无预设台词）", ex.pool.count()["active"] == 0,
          f"count={ex.pool.count()}")

    # 2) 同一状态反复取语气：表述应有变化（不是一句写死的台词）
    ex2 = make_expr("e2")
    gov2 = FakeGov(e={"木": 0.6, "火": 0.0, "土": 0.0, "金": 0.0, "水": 0.0})
    tones = [ex2.derive(gov2, noise=False)["tone"] for _ in range(20)]
    check("同一状态 20 次取语气，至少出现 3 种表述", len(set(tones)) >= 3,
          f"distinct={len(set(tones))} sample={tones[0]}")

    # 3) 情绪能量为 0（平静）时，不该凭 W 主行硬叠情绪语气
    ex3 = make_expr("e3")
    gov3 = FakeGov(e={k: 0.0 for k in EMO_KEYS},
                   w=(0.023, 0.023, 0.44, 0.023, 0.49))  # 水主行（实际状态）
    calm_tones = [ex3.derive(gov3, noise=False)["tone"] for _ in range(20)]
    hit = [t for t in calm_tones if any(r in t for r in EMO_ROOTS)]
    check("E 全 0 时语气不带五行情绪色", not hit, f"漏={hit[:3]}")

    # 4) 有 TONE_DIM：情绪→语气必须是「维度池」而不是单句表
    check("情绪语气来自可组合的维度池 TONE_DIM", bool(TONE_DIM) and all(k in TONE_DIM for k in EMO_KEYS),
          f"keys={list(TONE_DIM)[:5]}")

    # 5) 强度分档：高能量用 high 档、低能量用 low 档，且两档词不同
    if TONE_DIM:
        hi = set(TONE_DIM["木"].get("high", []))
        lo = set(TONE_DIM["木"].get("low", []))
        check("木行 high/low 两档词没有交集", bool(hi) and bool(lo) and not (hi & lo),
              f"hi={len(hi)} lo={len(lo)} overlap={hi & lo}")

        ex5 = make_expr("e5")
        gov_hi = FakeGov(e={"木": 0.95, "火": 0.0, "土": 0.0, "金": 0.0, "水": 0.0})
        gov_lo = FakeGov(e={"木": 0.15, "火": 0.0, "土": 0.0, "金": 0.0, "水": 0.0})
        t_hi = [ex5.derive(gov_hi, noise=False)["tone"] for _ in range(12)]
        t_lo = [ex5.derive(gov_lo, noise=False)["tone"] for _ in range(12)]
        check("强度高时落到 high 档", any(any(w in t for w in hi) for t in t_hi), f"{t_hi[:2]}")
        check("强度低时落到 low 档", any(any(w in t for w in lo) for t in t_lo), f"{t_lo[:2]}")

    # 6) 口头禅只能从对话长出来：夸奖 + 她自己的短句 → 吸收
    ex6 = make_expr("e6")
    ev = ex6.observe_signals("笑死，这话太像你了", "行吧行吧", at=1000.0)
    texts = [it["text"] for it in ex6.pool.active()]
    check("夸奖 + 短回复 → 长出候选口癖", "行吧行吧" in texts, f"texts={texts} ev={ev}")

    # 7) 用户明确教的示范 → 弱种子入库（不是系统自带的）
    ex6.observe_signals("我的口头禅是“就这吧”", "行", at=1100.0)
    check("用户教的示范 → 入库", "就这吧" in [it["text"] for it in ex6.pool.active()],
          f"texts={[it['text'] for it in ex6.pool.active()]}")

    # 8) 池里有 5 条同桶口癖时，20 次检索不能永远只回同一组
    ex8 = make_expr("e8")
    for i, q in enumerate(["别整那套", "又来这套", "烦死了", "无语", "行行行"]):
        ex8.pool.absorb(q, ["木"], 1.0 - i * 0.05)
    gov8 = FakeGov(e={"木": 0.7, "火": 0.0, "土": 0.0, "金": 0.0, "水": 0.0})
    combos = [tuple(ex8.derive(gov8, noise=False)["quirks"]) for _ in range(20)]
    check("同桶 5 条口癖，20 次检索至少 3 种组合", len(set(combos)) >= 3,
          f"distinct={len(set(combos))} first={combos[0]}")

    # 9) 口癖条数上限仍守住
    check("注入口癖 ≤ 上限", all(len(c) <= C.EXPR_QUIRK_MAX for c in combos),
          f"max={max(len(c) for c in combos)} cap={C.EXPR_QUIRK_MAX}")

    # 9b) 红线：口癖原文不得进提示词——只透出"有几个习惯"，具体说法由她当场决定
    hint9 = ex8.derive(gov8, noise=False)["hint"]
    seeded = ["别整那套", "又来这套", "烦死了", "无语", "行行行"]
    leaked = [s for s in seeded if s in hint9]
    check("hint 不写口癖原文（不规定说法）", not leaked, f"leaked={leaked} hint={hint9}")

    # 10) 纠正 → 降温；连续 3 次 → 归档（口头禅能被你否掉）
    ex10 = make_expr("e10")
    ex10.pool.absorb("绝绝子", ["火"], 1.0)
    drops = ["绝绝子"] * 3
    for _ in range(3):
        ex10.observe_signals("别说绝绝子", "哦", at=2000.0)
    alive = [it for it in ex10.pool.items if it["text"] == "绝绝子"][0]
    check("否定 → 降温归档", alive["status"] == "archived" or alive["sticky"] <= 0.1,
          f"status={alive['status']} sticky={alive['sticky']:.3f}")

    # 11) 软措辞纪律还在：带"可破例"，不写成硬规则
    hint = ex2.derive(gov2, noise=False)["hint"]
    check("hint 保留「可以破例」", "破例" in hint, f"{hint[:40]}")

    # 12) 关系温度仍影响基调（疏离 ≠ 亲近）
    ex12 = make_expr("e12")
    t_cold = ex12.derive(FakeGov(temperature="疏离"), noise=False)["tone"]
    t_warm = ex12.derive(FakeGov(temperature="亲近"), noise=False)["tone"]
    check("关系温度影响基调", TONE_BY_TEMP["疏离"][0] in t_cold and TONE_BY_TEMP["亲近"][0] in t_warm,
          f"cold={t_cold} warm={t_warm}")

    ok_all = all(ok for _, ok, _ in PASS)
    print(f"\n== {sum(1 for _, o, _ in PASS if o)}/{len(PASS)} passed ==")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
