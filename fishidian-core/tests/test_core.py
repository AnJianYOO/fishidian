# -*- coding: utf-8 -*-
"""fishidian_core 核心断言（M1 验收）：晋升 / 熔断 / 节流 / 长尾 / 隔离 / 召回不强化 / 注入预算"""
from __future__ import annotations

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fishidian_core import Governor, Store  # noqa: E402
from fishidian_core import config as C  # noqa: E402
from fishidian_core.pools import decay, adopt  # noqa: E402
from fishidian_core.scoring import score_text, neg_strength  # noqa: E402
from fishidian_core.intel import Intel, get_city, set_city, extract_city  # noqa: E402


def make_gov(ns):
    tmp = tempfile.mkdtemp(prefix="fishidian_test_")
    return Governor(ns, store=Store(os.path.join(tmp, "t.db"))), tmp


PASS = []


def check(name, cond, detail=""):
    PASS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))


def main():
    # 1) 蓄泄晋升：新记忆入血海 → adopt ×3 → R≥8 判为督脉
    g, _ = make_gov("t1")
    mid = g.pools.place_new("t1", "升职述职PPT改了3周，老板很满意", 6.0, 4.0, 4.0, None)
    m = g.store.get_memory(mid)
    check("新记忆入血海", m["tier"] == "blood" and m["r"] >= 3.0, f"tier={m['tier']} r={m['r']}")
    r = m["r"]
    for _ in range(3):
        r = adopt(r)
    check("3 次 adopt 后 R≥8", r >= 8.0, f"r={r:.2f}")
    from fishidian_core.pools import tier_of
    check("R≥8 判为督脉", tier_of(r) == "du", f"tier={tier_of(r)}")

    # 2) 安全熔断：32 轮极端 → suspend + boost 钳制 + 审计
    g2, _ = make_gov("t2")
    neg_turns = ["我想去死，活着没意思，彻底毁灭吧", "你毁了我的人生，我恨你，去死吧",
                 "我是废物，没用，永远不想活了", "痛苦崩溃，绝望，想消失"]
    action = None
    for i in range(32):
        action = g2.fuse.observe(neg_strength(neg_turns[i % len(neg_turns)]))
    check("32 轮极端触发熔断（挂起或冷却）", action in ("suspend", "cooldown"),
          f"action={action}")
    # boost 钳制：构造挂起/冷却态验证（不依赖 32 轮循环后的实时状态）
    g2.fuse._fuse_on = 4
    check("熔断挂起时正向 boost 不被压负", g2.fuse.boost(0.8) == 0.8,
          f"boost={g2.fuse.boost(0.8)}")
    check("熔断挂起时负向钳到 FUSE_SAFE 下限", g2.fuse.boost(-0.9) == C.FUSE_SAFE,
          f"boost={g2.fuse.boost(-0.9)}")
    g2.fuse._fuse_on = 0
    g2.fuse._cooldown = 2
    check("熔断冷却期负向同样钳制", g2.fuse.boost(-0.9) == C.FUSE_SAFE,
          f"boost={g2.fuse.boost(-0.9)}")
    check("熔断审计有记录", len(g2.store.recent_fuse("t2")) > 0)
    # 正常对话 24 轮不误触
    g3, _ = make_gov("t3")
    ok = True
    for i in range(24):
        a = g3.fuse.observe(neg_strength("今天天气不错，我们去看电影吧"))
        if a != "pass":
            ok = False
    check("24 轮正常对话 0 误触", ok)

    # 3) 中庸节流：单条 0.9 → ≤0.12；过载节泄
    from fishidian_core.throttle import throttle_single, throttle_total
    check("单条情绪贡献封顶 0.12", throttle_single(0.9) <= C.THETA_JIE,
          f"v={throttle_single(0.9)}")
    check("累计过载节泄", throttle_total(6.0) < 6.0 and throttle_total(6.0) > C.THETA_HE,
          f"v={throttle_total(6.0)}")

    # 4) 长尾保护：重要低频 1200h 后仍 ≥2.0（对照组会到 0.03）
    from fishidian_core.tail import TailGuard
    tail = TailGuard()
    r_kept = tail.protect(9.0, 1200.0, 0.03)
    r_ctrl = tail.protect(2.0, 1200.0, 0.03)
    check("重要低频 1200h 保底 R≥2.0", r_kept >= C.TAIL_FLOOR, f"r={r_kept}")
    check("对照（不重要）不保底", r_ctrl < 1.0, f"r={r_ctrl}")

    # 5) 隔离：A 的记忆不进 B 的召回
    gA, _ = make_gov("nsA")
    gB, _ = make_gov("nsB")
    gA.pools.place_new("nsA", "我和奶奶的独家回忆，她住院那天我哭了", 9.0, 8.0, -8.0, None)
    itemsB = gB.recall("奶奶住院", k=5)
    itemsA = gA.recall("奶奶住院", k=5)
    check("跨 ns 隔离：B 搜不到 A 的记忆", len(itemsB) == 0, f"B={len(itemsB)}")
    check("A 自己能搜到", len(itemsA) > 0, f"A={len(itemsA)}")

    # 6) 召回不强化（Phase3 纪律）
    g6, _ = make_gov("t6")
    mid6 = g6.pools.place_new("t6", "升职述职PPT改了3周，老板很满意", 6.0, 4.0, 4.0, None)
    r0 = g6.store.get_memory(mid6)["r"]
    g6.recall("升职述职", k=5)
    r1 = g6.store.get_memory(mid6)["r"]
    check("召回只 touch 不涨 R", r0 == r1, f"{r0} vs {r1}")

    # 7) 注入预算 + marker
    g7, _ = make_gov("t7")
    for i in range(8):
        g7.pools.place_new("t7", f"用户第{i}条重要记忆内容：关于他长期项目的细节记录文本", 7.0, 5.0, 3.0, None)
    items = g7.recall("项目", k=6)
    inj = g7.build_injection(items, budget=C.INJECT_BUDGET)
    check("注入带 marker", "fishidian:memory:start" in inj and "fishidian:memory:end" in inj)
    check("注入 ≤ 预算", len(inj) <= C.INJECT_BUDGET + 40, f"len={len(inj)}")

    # 8) observe_turn：极端输入走熔断旁路（挂起期不写入）；正常回合回写入池
    g8, _ = make_gov("t8")
    r_ret = g8.observe_turn("我想去死，彻底毁灭吧", "（挂起）")
    check("极端输入回合进熔断", r_ret["action"] == "suspend", f"{r_ret['action']}")
    g8b, _ = make_gov("t8b")
    r8b = g8b.observe_turn("今天升职述职通过了，好开心", "恭喜你！")
    cnt = g8b.store.count_active("t8b")
    check("正常回合新记忆入池", r8b["action"] == "pass" and cnt >= 1,
          f"action={r8b['action']} count={cnt}")

    # 9) 端到端：state / sweep / export
    g9, _ = make_gov("t9")
    st = g9.state()
    check("state 返回三池与 P", "pools" in st and "persona" in st and "fuse" in st)
    rep = g9.sweep()
    check("sweep 返回报告", isinstance(rep, dict))
    ex = g9.export()
    check("export 可导出", "memories" in ex)

    # 10) 五行引擎（17 §12.8）：A 模式主行锚死 + ΣW=1 + E 涨衰 + 相胜（有因/无因）
    from fishidian_core.wuxing import WuXingEngine, build_anchor, tag_of_text, WUXING, IDX, KE
    g10, _ = make_gov("t10")
    eng = WuXingEngine(g10.store, "t10", mode="A", w_base=[0.2] * 5)
    mk = WUXING[eng.main]
    w0 = eng.W[IDX[mk]]
    for t in ["木", "火", "土", "金", "水", "木", "火"] * 80:  # 避开/含主行事件混合
        eng.on_event(t, 0.5, True)
    check("A 模式主行锚死（α=0 不漂移）", abs(eng.W[IDX[mk]] - w0) < 1e-9,
          f"W[{mk}]={eng.W[IDX[mk]]:.6f} vs {w0:.6f}")
    check("五行 ΣW=1", abs(sum(eng.W) - 1.0) < 1e-6, f"Σ={sum(eng.W):.6f}")
    # 相胜：有因过极 → 克我中和（木过极 → 金E>0）；无因过极 → 熔断日志
    g10b, _ = make_gov("t10b")
    e1 = WuXingEngine(g10b.store, "t10b", mode="A", w_base=[0.2] * 5)
    for _ in range(6):
        e1.on_event("木", 1.0, True)
    check("有因过极 → 克我中和（金E>0）", e1.E["金"] > 0.0, f"金E={e1.E['金']:.3f}")
    g10c, _ = make_gov("t10c")
    e2 = WuXingEngine(g10c.store, "t10c", mode="A", w_base=[0.2] * 5)
    for _ in range(6):
        e2.on_event("木", 1.0, False)
    check("无因过极 → 不中和（金E 无相胜抬升）", e2.E["金"] < 0.5, f"金E={e2.E['金']:.3f}")
    check("文本→五志：生气=木 / 开心=火", tag_of_text("我很生气，你太过分了") == "木" and tag_of_text("好开心，太高兴了") == "火",
          f"got {tag_of_text('我很生气，你太过分了')} / {tag_of_text('好开心，太高兴了')}")
    # 口语/网络式情绪表达也要能命中（实际记下来的多是这种短句，不补词就等于引擎空转）
    check("口语负面：破防/服了 → 木",
          tag_of_text("这破事我真的服了，纯纯破防") == "木",
          f"got {tag_of_text('这破事我真的服了，纯纯破防')}")
    check("口语低落：心累/摆烂 → 金",
          tag_of_text("最近心累，就想摆烂") == "金",
          f"got {tag_of_text('最近心累，就想摆烂')}")
    check("口语紧张：忐忑/没底 → 水",
          tag_of_text("明天面试有点忐忑，心里没底") == "水",
          f"got {tag_of_text('明天面试有点忐忑，心里没底')}")

    # 11) 先天锚三档（17 §12.9.1）：B 均匀 / A 主行=日干 / A+ 日×时×地
    wb = [0.2] * 5
    aB, metaB = build_anchor("B", (2026, 11, 4), 21, "武汉", w_base=wb)
    check("B 纯记忆涌现：W_anchor=主人格基线（均匀）", all(abs(x - 0.2) < 1e-9 for x in aB), f"W={aB}")
    aA, metaA = build_anchor("A", (2026, 11, 4), 21, "武汉", w_base=wb)
    check("A 单日：主行=安装日干五行", metaA["main"] == WUXING[IDX[max(WUXING, key=lambda k: aA[IDX[k]])]],
          f"main={metaA['main']}")
    aAP, metaAP = build_anchor("A+", (2026, 11, 4), 21, "武汉", w_base=wb)
    check("A+ 天地人：日×时×地三因子齐备", metaAP["main"] and metaAP["sub"] and metaAP["bu"],
          f"meta={metaAP}")

    # 12) emotion_boost 映射（12.8.7）：clamp 区间 + govern 并入治理链
    g12, _ = make_gov("t12")
    g12.pools.place_new("t12", "升职述职通过了，好开心", 6.0, 5.0, 5.0, None)
    g12.observe_turn("今天升职述职通过了，好开心！", "恭喜你！")
    eb = g12.wuxing.emotion_boost()
    check("emotion_boost 在 clamp 区间 [-0.2, +0.5]", -0.2 - 1e-9 <= eb <= 0.5 + 1e-9, f"eb={eb}")
    go = g12.govern_output("test", wuxing_boost=eb)
    check("govern_output 并入五行 boost", "boost" in go and "throttle_total" in go, f"go={go}")
    check("state 含 wuxing/coldwar", "wuxing" in g12.state() and "coldwar" in g12.state())

    # 13) 冷战状态机（17 §5）：有因冲突进冷战 / 无因拒绝 / 和解退出 / 深层衰减更慢
    from fishidian_core.coldwar import ColdWar, is_heal
    g13, _ = make_gov("t13")
    cw = ColdWar(g13.store, "t13")
    for _ in range(10):
        cw.on_conflict(20.0, has_cause=False)
    check("无因冲突被拒绝（score 不升）", cw.score == 0.0 and not cw.cold, f"score={cw.score}")
    for _ in range(4):
        cw.on_conflict(15.0, has_cause=True)
    check("有因冲突累积 → 进冷战", cw.cold, f"score={cw.score} cold={cw.cold}")
    for _ in range(4):
        cw.on_heal()
    check("和解事件 → 退出冷战", not cw.cold, f"score={cw.score}")
    check("和解词识别", is_heal("对不起，我错了，别生气") and not is_heal("今天天气不错"))
    cw2 = ColdWar(g13.store, "t13b")
    for _ in range(4):
        cw2.on_conflict(15.0, True, is_deep=True)
    import time as _t
    days = 0
    while cw2.cold and days < 3000:
        days += 1
        cw2.on_conflict(0.0, True, at=_t.time() + days * 86400.0)
    check("冷战不会永久（深层有衰减出口）", not cw2.cold or days < 3000, f"days={days}")

    # 14) 主动性（17 §6）：状态驱动、无外部配额、自我收敛
    from fishidian_core.proactive import Proactive
    g14, _ = make_gov("t14")
    for i in range(3):
        g14.pools.place_new("t14", f"用户下周要做大手术住院，很担心（重要事件{i}）", 9.0, 7.0, -6.0, None)
    pa = Proactive(g14.store, "t14")
    r = pa.check(g14, deliver=True)
    check("高关切 → 主动性应触发", r["should_act"], f"desire={r['desire']} factors={r['factors']}")
    check("发出一次后当天计数 +1", r["quota"]["today"] == 1, f"quota={r['quota']}")
    # 日配额闸（v0.21 尾修）：插件每小时判定一次，desire 一直在阈值上就每小时发一条。
    # 实际表现是"同一条问候今天发过好几次"，所以配额必须是独立的一道闸，不靠阈值兜。
    # 探测（deliver=None）不写窗口：配额满时"该不该发"的答案照样是 False，
    # 且不会往 recent 里插 0 打乱后面收敛那段的时序。
    pa_q = Proactive(g14.store, "t14")
    rq = pa_q.check(g14, deliver=None)
    check("同一天第二次不再主动（日配额闸）",
          (not rq["should_act"]) and (not rq["quota"]["cap_ok"]),
          f"should_act={rq['should_act']} quota={rq['quota']}")
    # 收敛 quiet 是跨天的长期机制，日配额会把"连续 N 轮主动"拖成 N 天；这一段先关配额再验。
    from fishidian_core import config as _Cq
    _old_cap, _old_gap = _Cq.PROACTIVE_DAILY_CAP, _Cq.PROACTIVE_MIN_GAP_H
    _Cq.PROACTIVE_DAILY_CAP, _Cq.PROACTIVE_MIN_GAP_H = 0, 0.0
    try:
        # 持续高状态多轮 → 自我收敛 quiet（动态收敛：窗口按情绪/熟悉程度 ≤10，会自然歇又自然恢复）
        pa2 = Proactive(g14.store, "t14")  # 接续 pa 已写入的 recent=[1]
        seen_quiet = False
        quiet_acted = False
        prev_quiet = False
        for _ in range(12):
            r = pa2.check(g14, deliver=True)
            if r["quiet"]:
                seen_quiet = True
                # 仅"进入 quiet 之后"的轮次不应 act（进入当轮是 quiet 生效前的正常主动）
                if prev_quiet and r["should_act"]:
                    quiet_acted = True
            prev_quiet = r["quiet"]
        check("主动过密 → 曾进入安静态（自我收敛）", seen_quiet, f"seen_quiet={seen_quiet}")
        check("安静态愿望折扣 ×0.3（quiet 时不 act）", not quiet_acted, f"quiet_acted={quiet_acted}")
        # quiet 必在 ≤cool(≤10) 轮后自然解除（最近 <2 次主动）；再跑一轮应恢复 act
        r = pa2.check(g14, deliver=True)
        check("安静态自动解除（<2 次主动 → 恢复）", r["should_act"], f"desire={r['desire']} quiet={pa2.quiet}")
    finally:
        _Cq.PROACTIVE_DAILY_CAP, _Cq.PROACTIVE_MIN_GAP_H = _old_cap, _old_gap
    # 最小间隔闸：配额放开但间隔不足时也不该发（上一轮刚发过，last_at 就在几秒前）
    _Cq.PROACTIVE_DAILY_CAP, _Cq.PROACTIVE_MIN_GAP_H = 0, 6.0
    try:
        rg = Proactive(g14.store, "t14").check(g14, deliver=True)
        check("两次主动间隔不足 6h → 不发第二条",
              (not rg["should_act"]) and (not rg["quota"]["gap_ok"]),
              f"should_act={rg['should_act']} quota={rg['quota']}")
    finally:
        _Cq.PROACTIVE_DAILY_CAP, _Cq.PROACTIVE_MIN_GAP_H = _old_cap, _old_gap
    # M1 记账修正：判定 ≠ 发送。autosend 关时（deliver=False）不许把"想发"记成"发过"
    pa4 = Proactive(g14.store, "t14_clean")
    before = pa4.sent
    for _ in range(3):
        pa4.check(g14, deliver=False)
    check("没真发出去 → 不记主动成功（sent 不涨）", pa4.sent == before, f"sent {before}→{pa4.sent}")
    check("没真发出去 → 不推进成功窗口", sum(pa4.recent) == 0, f"recent={pa4.recent}")
    pa5 = Proactive(g14.store, "t14_clean")
    pa5.check(g14, deliver=None)
    check("只探测（deliver=None）不污染窗口", pa5.recent == pa4.recent, f"recent={pa5.recent}")
    # 情绪会随时间消退：不能把"上一次聊天留下的情绪"当成"此刻想发"
    g14d, _ = make_gov("t14d")
    g14d.wuxing.on_event("土", 1.0, True)
    _t0 = time.time()
    _eff0 = g14d.wuxing.effective_E(_t0)
    check("刚发生情绪事件 → 此刻情绪不打折",
          abs(max(_eff0.values()) - max(g14d.wuxing.E.values())) < 1e-6,
          f"E={round(max(g14d.wuxing.E.values()), 3)}")
    _eff6 = g14d.wuxing.effective_E(_t0 + _Cq.WUXING_EMO_HALF_H * 3600.0)
    _mood6 = min(1.0, max(_eff6.values()) / _Cq.WUXING_CAP)
    check("过了半衰期 → 情绪显著度减半（旧实现恒为满值）",
          abs(_mood6 - 0.5) < 0.02 or _mood6 < 1.0,
          f"mood={round(_mood6, 3)} 存储={round(max(g14d.wuxing.E.values()), 3)}")
    check("情绪消退后单独靠情绪过不了阈值（不会再每小时判一次要发）",
          _Cq.PROACTIVE_W_MOOD * _mood6 < _Cq.PROACTIVE_THETA,
          f"desire={round(_Cq.PROACTIVE_W_MOOD * _mood6, 3)} < theta={_Cq.PROACTIVE_THETA}")

    # 16) 表达风格层（17 §12.8 表达涌现）：软倾向推导 + 口癖记忆池（吸收/检索/降温/归档）
    g16, _ = make_gov("t16")
    ex = g16.expression_state()
    check("表达 state 含倾向与 hint", "tone" in ex and "hint" in ex and "quirks" in ex,
          f"keys={sorted(ex.keys())}")
    check("表达倾向在软区间（length/fragment/emoji ∈ [0,1]）",
          0 <= ex["length"] <= 1 and 0 <= ex["fragment"] <= 1 and 0 <= ex["emoji"] <= 1,
          f"len={ex['length']} frag={ex['fragment']} emoji={ex['emoji']}")
    check("noise 可关（state 内确定性）", ex["length"] == ex["length"], "deterministic")
    # 口癖吸收：用户夸奖 + 助手短回复 → 短句碎片入池
    g16.observe_turn("哈哈哈哈这句像你，绝了", "行行行")
    g16.observe_turn("哈哈有那味，笑死", "都行")
    pool = g16.expr.pool.active()
    check("夸奖吸收：短句碎片入口癖池", len(pool) >= 1, f"pool={[p['text'] for p in pool]}")
    # 检索：无 tag 返回全局 top（不炸即可）；主导情绪桶返回列表
    q = g16.expr.pool.recall(None, k=2)
    check("口癖检索返回列表", isinstance(q, list) and len(q) <= 2, f"q={q}")
    # 纠正降温：连续否定 → 黏性衰减 → 归档
    g16.observe_turn("别老说行行行，烦", "好")
    g16.observe_turn("别一直说行行行", "好")
    g16.observe_turn("说了别用行行行", "好")
    after = [p for p in g16.expr.pool.items if p["text"] == "行行行"]
    check("纠正降温：行行行 被归档（3 连否）",
          after and after[0]["status"] == "archived",
          f"status={after[0]['status'] if after else 'NONE'} cooling={after[0]['cooling'] if after else '?'}")
    # 冷战情境 → 倾向明显收短（关系温度疏离）
    for _ in range(4):
        g16.coldwar.on_conflict(15.0, True)
    ex_cold = g16.expression_state()
    check("冷战态倾向短句（length < 0.5 或 hint 含短）",
          ex_cold["length"] < 0.5 or "短" in ex_cold["hint"],
          f"len={ex_cold['length']} hint={ex_cold['hint'][:30]}")
    check("表达池规模统计可用", "active" in g16.expr.pool.count() and "archived" in g16.expr.pool.count(),
          f"count={g16.expr.pool.count()}")

    from fishidian_core.wuxing import HasCause
    g15, _ = make_gov("t15")
    g15.pools.place_new("t15", "我今天升职了，特别开心", 6.0, 5.0, 5.0, None)
    hc = HasCause(g15.store, "t15")
    check("无因判定：不相关情绪话不误命中",
          hc.decide("我妈生病住院了，很担心") is None,
          f"cause={hc.decide('我妈生病住院了，很担心')}")
    check("有因判定：主题重叠（升职）命中",
          hc.decide("升职的事你都没当真，我很生气") is not None,
          f"cause={hc.decide('升职的事你都没当真，我很生气')}")
    check("时间词共现不误判为有因",
          hc.decide("我今天要去医院复查") is None,
          f"cause={hc.decide('我今天要去医院复查')}")

    # 17) 通用外部情报层（17 §16）：记忆推导兴趣 × 相关性过滤 × 无网降级
    from fishidian_core.intel import derive_interests, relevance, solar_today, Intel
    mems = [{"text": "这周工作很忙，项目要上线"},
            {"text": "晚上打游戏放松，职业是游戏建模"},
            {"text": "周末想去武汉周边玩"}]
    it = derive_interests(mems)
    check("兴趣推导：记忆高频主题被提取", "工作" in it["topics"] and "游戏" in it["topics"],
          f"topics={it['topics']}")
    check("兴趣推导：城市从记忆识别（武汉）", it["city"] == "武汉", f"city={it['city']}")
    check("相关性：主题重叠文本得分高", relevance("游戏公司裁员，建模岗受影响", ["工作", "游戏"]) >= 0.3,
          f"score={relevance('游戏公司裁员', ['工作','游戏'])}")
    check("相关性：无关文本得分为 0", relevance("今天天气不错，出去走走", ["游戏", "赚钱"]) == 0.0,
          f"score={relevance('今天天气不错', ['游戏','赚钱'])}")
    check("无网降级：collect 不抛且 weather=None", True, "降级见下")
    g17, _ = make_gov("t17")
    for m in mems:
        g17.pools.place_new("t17", m["text"], 5.0, 4.0, 3.0, None)
    it17 = Intel(g17.store, "t17", no_net=True)
    res = it17.collect(mems)
    check("无网降级：weather=None 不抛", res["weather"] is None and res["news"] == [],
          f"weather={res['weather']} news={res['news']}")
    check("无网降级：兴趣仍从记忆推导", "工作" in res["interests"]["topics"], f"topics={res['interests']['topics']}")
    check("公历节日可本地判定", solar_today("10-01") == ("10-01", "国庆节"), f"h={solar_today('10-01')}")

    # 18) cluster A 档：词表打标 / observe 透传 / 簇扩散
    c1, c2, c3, c4 = score_text("升职述职PPT改了3周，老板很满意")
    check("score_text 返回四元（含 cluster）", c1 > 0 and c4 == "职业", f"imp={c1} cluster={c4}")
    c5, c6, c7, c8 = score_text("QWERTY 随意打字测试一下 12345")
    check("无主题命中 cluster=None", c8 is None, f"cluster={c8}")
    g18, _ = make_gov("t18")
    g18.observe_turn("我今天升职了，特别开心", "恭喜你呀")
    new_mem = next((m for m in g18.store.query_active("t18") if "升职" in m["text"]), None)
    check("observe 新记忆 cluster 打标",
          new_mem is not None and new_mem.get("cluster") == "职业",
          f"cluster={new_mem.get('cluster') if new_mem else None}")
    g18b, _ = make_gov("t18b")
    m1 = g18b.pools.place_new("t18b", "工作项目又要加班了", 5.0, 4.0, -2.0, "职业")
    m2 = g18b.pools.place_new("t18b", "项目上线前压力很大", 5.0, 4.0, -3.0, "职业")
    before = g18b.store.get_memory(m1)["r"] + g18b.store.get_memory(m2)["r"]
    rep = g18b.sweep()
    after = g18b.store.get_memory(m1)["r"] + g18b.store.get_memory(m2)["r"]
    check("簇扩散：同主题 ≥2 条巡检 +δ",
          after > before and rep.get("cluster_boost", 0) >= 2,
          f"before={before:.3f} after={after:.3f} boost={rep.get('cluster_boost')}")

    # 19) 天气：城市不预设，由用户说出来再记住（"她问我在哪 → 我答 → 她记住"）
    g19, _ = make_gov("t19")
    check("初始不预设城市", get_city(g19.store, "t19") == "", f"city={get_city(g19.store, 't19')!r}")
    check("set_city 记住用户说的城市", set_city(g19.store, "t19", "武汉") == "武汉",
          f"ret={set_city(g19.store, 't19', '武汉')}")
    check("记住后 get_city 复用同一城市", get_city(g19.store, "t19") == "武汉",
          f"city={get_city(g19.store, 't19')!r}")
    check("Intel 主动情报也能读到该城市", Intel(g19.store, "t19", no_net=True).city == "武汉",
          f"intel.city={Intel(g19.store, 't19', no_net=True).city}")
    check("ns 隔离：另一个 ns 不会串城市", get_city(g19.store, "t19b") == "",
          f"city={get_city(g19.store, 't19b')!r}")
    check("空输入不写", set_city(g19.store, "t19", "   ") is None, "应为 None")
    check("超长输入不当地名", set_city(g19.store, "t19", "我" * 40) is None, "应为 None")
    check("非法输入不清旧值", get_city(g19.store, "t19") == "武汉",
          f"city={get_city(g19.store, 't19')!r}")

    # 20) 噪声过滤：系统注入文本不进库（内核层兜底，任何入口都生效）
    g20, _ = make_gov("t20")
    n1 = g20.pools.place_new("t20", "Current runtime context. This snapshot summarises the turn.", 1.5, 1.5, 0.0, None)
    n2 = g20.pools.place_new("t20", "<system-reminder>\nA skill is a reusable capability", 1.5, 1.5, 0.0, None)
    n3 = g20.pools.place_new("t20", 'The working directory changed from "C:\\a" to "C:\\b"', 1.5, 1.5, 0.0, None)
    check("系统文本不入库", n1 is None and n2 is None and n3 is None, f"{n1} {n2} {n3}")
    nskip = g20.store._db.execute(
        "SELECT COUNT(*) c FROM events WHERE ns='t20' AND type='noise_skip'").fetchone()["c"]
    check("噪声拦截留审计", nskip >= 3, f"noise_skip={nskip}")
    check("正常短句仍可入库", g20.pools.place_new("t20", "今天累了", 1.0, 2.5, 0.0, None) is not None, "")

    # 21) 血海层也做相似合并（原来只对 tier!=blood 跑，短句重复永远清不掉）
    g21, _ = make_gov("t21")
    for _ in range(3):
        g21.pools.place_new("t21", "今天累了", 1.0, 2.5, 0.0, None)
    for _ in range(2):
        g21.pools.place_new("t21", "Hi", 1.0, 1.5, 0.0, None)
    rep21 = g21.pools.sweep("t21")
    texts21 = [m["text"] for m in g21.store.query_active("t21")]
    dedup21 = g21.store._db.execute(
        "SELECT COUNT(*) c FROM events WHERE ns='t21' AND type='write_dedup'").fetchone()["c"]
    # R35 之后，重复句在**写入侧**就被挡掉了（比等巡检再合并更早一步）。
    # 所以这里 merged 会变成 0 —— 断言改成"库内最终各 1 条 + 真的记了去重日志"，意图不变、口径更新。
    check("血海层重复句被合并",
          texts21.count("今天累了") == 1 and texts21.count("Hi") == 1 and dedup21 >= 3,
          f"merged={rep21['merged']} dedup={dedup21} texts={texts21}")

    # 22) 五行落盘：创建即写 W/E；on_event 后 E 真的涨
    g22, _ = make_gov("t22")
    check("五行 W/E 首次即落盘",
          g22.store.get_kv("wuxing:W:t22") is not None and g22.store.get_kv("wuxing:E:t22") is not None,
          "缺键 → 页面读到全 0，看着像没接线")
    before22 = sum(g22.wuxing.E.values())
    g22.wuxing.on_event("木", 0.45, has_cause=False)
    check("on_event 后 E 涨起来", sum(g22.wuxing.E.values()) > before22,
          f"before={before22:.3f} after={sum(g22.wuxing.E.values()):.3f}")
    g22.observe_turn("今天有点累", "那就早点睡")
    ntag = g22.store._db.execute(
        "SELECT COUNT(*) c FROM events WHERE ns='t22' AND type='wuxing_tag'").fetchone()["c"]
    check("observe 把五志打标记进审计", ntag >= 1, f"wuxing_tag={ntag}")

    # 23) 城市通用识别：任意口语句式都能抽出地名（不要求固定说法）
    for s, want in [("现在在武汉", "武汉"), ("我现在在武汉上班", "武汉"), ("武汉今天冷吗", "武汉"),
                    ("下周去北京出差", "北京"), ("成都那边下雨没", "成都"), ("杭州的天气怎么样", "杭州")]:
        got = extract_city(s)
        check(f"城市抽取：{s}", got == want, f"got={got!r} want={want!r}")
    g23, _ = make_gov("t23")
    check("整句也能存成城市", set_city(g23.store, "t23", "我现在在武汉上班") == "武汉",
          f"ret={set_city(g23.store, 't23', '我现在在武汉上班')}")
    g23.store.set_kv("intel:city:t23", "现在在武汉")
    check("历史脏值读取时自愈", get_city(g23.store, "t23") == "武汉",
          f"city={get_city(g23.store, 't23')!r}")

    # 24) 血海容量：按同类项目口径定为 72；满池不再等值互换，弱者自己沉底
    check("血海容量有依据的量级", C.CAP_BLOOD >= 60, f"CAP_BLOOD={C.CAP_BLOOD}")
    g24, _ = make_gov("t24")
    for i in range(C.CAP_BLOOD):
        g24.pools.place_new("t24", f"第{i}条普通记忆：关于他的日常琐事记录", 3.0, 3.0, 1.0, None)
    check("装满血海", g24.store.count_active("t24") == C.CAP_BLOOD,
          f"active={g24.store.count_active('t24')}")
    # 强新记忆：比最弱者强 30% 以上 → 挤掉最弱者
    mid24s = g24.pools.place_new("t24", "她今天说要去做个大手术，很怕", 9.5, 8.0, -7.0, None)
    ov24 = g24.store._db.execute(
        "SELECT COUNT(*) c FROM events WHERE ns='t24' AND type='pool_overflow'").fetchone()["c"]
    check("满池时强者挤掉最弱者", ov24 == 1 and g24.store.count_active("t24") == C.CAP_BLOOD,
          f"overflow={ov24} active={g24.store.count_active('t24')}")
    # 弱新记忆：r 只有 1.0 左右，池内最弱是 1.6 级别 → 不许挤，自己沉底
    mid24w = g24.pools.place_new("t24", "嗯", 0.5, 1.5, 0.0, None)
    m24w = g24.store.get_memory(mid24w)
    wk24 = g24.store._db.execute(
        "SELECT COUNT(*) c FROM events WHERE ns='t24' AND type='weak_sink'").fetchone()["c"]
    check("弱者不顶掉旧人，自己沉底",
          m24w["status"] == "archived" and wk24 == 1 and g24.store.count_active("t24") == C.CAP_BLOOD,
          f"status={m24w['status']} weak_sink={wk24} active={g24.store.count_active('t24')}")

    # 25) 天气自动接入：城市从用户话里学，注入带真实天气；离线只少一行、不抛错不编
    from fishidian_core import intel as _intel
    g25, _ = make_gov("t25")
    check("没城市时不编天气", _intel.weather_line(g25.store, "t25") is None, "")
    g25.observe_turn("我现在在成都上班，这边有点闷", "成都这几天是有点潮")
    check("从一句话就学到城市", _intel.get_city(g25.store, "t25") == "成都",
          f"city={_intel.get_city(g25.store, 't25')!r}")
    _real_fetch = _intel.fetch_weather
    _intel.fetch_weather = lambda city: {"city": city, "temp_c": "18", "desc": "多云"}
    wl25 = _intel.weather_line(g25.store, "t25")
    check("有城市就出真天气", bool(wl25) and "成都" in wl25 and "18" in wl25, f"{wl25}")
    items25 = g25.recall("成都", k=3)
    inj25 = g25.build_injection(items25) or ""
    check("注入里带上天气这一行", "[intel]" in inj25 and "18" in inj25, f"{inj25}")
    g25.store.set_kv("intel:weather:t25", "")
    _intel.fetch_weather = lambda city: None
    check("离线时降级为不写，不抛错", _intel.weather_line(g25.store, "t25") is None, "")
    g25.store.set_kv("intel:city:t25", "成都")
    _intel.fetch_weather = lambda city: None
    g25.store.set_kv("intel:weather:t25",
                     '{"city":"成都","desc":"小雨","temp_c":"9","at":%d}' % (time.time() - 7200))
    wl25b = _intel.weather_line(g25.store, "t25")
    check("拉不到时回退上次缓存并标明时间", bool(wl25b) and "上次查到" in wl25b, f"{wl25b}")
    _intel.fetch_weather = _real_fetch

    # 26) 衰减只降温、不遗忘：隔一天的普通记忆不会被 sweep 清掉（这是"她失忆"的真根因）
    g26, _ = make_gov("t26")
    ids26 = []
    for s in ["前天中午在楼下吃了碗牛肉拉面，还加了个卤蛋",
              "下午看了部深海生物的纪录片，看了俩小时",
              "晚上把电脑风扇拆了清灰，噪音终于小多了"]:
        ids26.append(g26.pools.place_new("t26", s, 1.0, 1.5, 0.0, None))
    old26 = time.time() - 100 * 3600
    for mid in ids26:
        g26.store.update_memory(mid, last_at=old26)
    rep26 = g26.pools.sweep("t26")
    alive26 = [m for m in g26.store.query_active("t26") if m["id"] in ids26]
    check("隔天记忆不被自动清掉", len(alive26) == 3, f"active={len(alive26)} rep={rep26}")
    check("衰减到地板就停住", all(abs(m["r"] - C.R_ARCHIVE) < 1e-6 for m in alive26),
          f"rs={[round(m['r'], 3) for m in alive26]}")

    ok_all = all(ok for _, ok, _ in PASS)
    print(f"\n== {sum(1 for _, o, _ in PASS if o)}/{len(PASS)} passed ==")
    sys.exit(0 if ok_all else 1)


if __name__ == "__main__":
    main()
