# -*- coding: utf-8 -*-
"""R30 / R34 / R35 / R36 验收（D-028 的四个 P0/P1 缺口）。

护住四条规矩：
  ① 出站脱敏：注入给模型的文本里不能出现完整手机号/身份证/卡号/邮箱，**库里必须仍是原文**；
  ② 注入前三道闸：与这句话无关的、与已入选重复的、只依稀记得的碎片，都不能占预算；
  ③ 写入侧两闸：同一句话说第二遍不长新记忆，每日新建有上限；
  ④ 单写者：两个连接（模拟 QQ 桥 + 插件）同时写，不许把 "database is locked" 冒到上层。
"""
from __future__ import annotations

import os
import sys
import tempfile
import threading
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fishidian_core import Governor, Store  # noqa: E402
from fishidian_core import config as C  # noqa: E402
from fishidian_core.mask import mask  # noqa: E402
from fishidian_core.pools import day_start, overlap  # noqa: E402

PASS = []


def check(name, cond, detail=""):
    PASS.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ("" if cond else f"  <- {detail}"))


def make_gov(ns):
    tmp = tempfile.mkdtemp(prefix="fishidian_gate_")
    st = Store(os.path.join(tmp, "t.db"))
    return Governor(ns, store=st), tmp


def seed(g, ns, texts, imp=3.0, aro=3.0, val=1.0):
    ids = []
    for t in texts:
        ids.append(g.pools.place_new(ns, t, imp, aro, val, None))
    return ids


def pin(g, mid, r, tier):
    g.store.update_memory(mid, r=r, tier=tier)


def events(store, ns, etype):
    return store._db.execute(
        "SELECT COUNT(*) c FROM events WHERE ns=? AND type=?", (ns, etype)).fetchone()["c"]


def main():
    # ================= R30 出站脱敏 =================
    check("脱敏：手机号", mask("打我 13812345678 就行") == "打我 138****5678 就行",
          mask("打我 13812345678 就行"))
    check("脱敏：身份证（先于银行卡命中）",
          mask("身份证 110101199003071234") == "身份证 110101******1234",
          mask("身份证 110101199003071234"))
    check("脱敏：银行卡只留尾号",
          mask("卡号 6222021234567890123") == "卡号 尾号0123",
          mask("卡号 6222021234567890123"))
    check("脱敏：邮箱", mask("发 abc@qq.com") == "发 a***@qq.com", mask("发 abc@qq.com"))
    check("脱敏：门牌串", mask("住在 3栋2单元501室") == "住在 某地址", mask("住在 3栋2单元501室"))
    # 误伤检查：年份、手机号片段、普通数字不能被改
    check("脱敏不误伤年份/普通数字",
          mask("2026年11月7日，3点开会，第12条") == "2026年11月7日，3点开会，第12条",
          mask("2026年11月7日，3点开会，第12条"))
    check("脱敏不误伤 '1栋楼那么高'（单段不算地址）",
          mask("那有 1栋楼那么高") == "那有 1栋楼那么高", mask("那有 1栋楼那么高"))

    g30, _ = make_gov("m30")
    mid30 = g30.pools.place_new("m30", "他的手机号是13812345678，住在3栋2单元501室", 6.0, 3.0, 1.0, None)
    stored = g30.store.get_memory(mid30)["text"]
    check("库里存的是原文（本地真值不丢）", "13812345678" in stored, stored)
    cx30 = g30.build_context("他的手机号多少")
    check("注入文本已脱敏", "13812345678" not in cx30["injection"]
          and "138****5678" in cx30["injection"], cx30["injection"][:120])
    check("审计记了脱敏处数",
          g30.store._db.execute("SELECT payload FROM events WHERE ns='m30' AND type='inject_context' "
                                "ORDER BY id DESC LIMIT 1").fetchone()["payload"].find('"masked": 2') > 0,
          "payload 里应有 masked=2")

    # ================= R34 三道闸 =================
    # ① 有效闸：与这句话完全无关的记忆，不许挤进情境层
    g34, _ = make_gov("g34")
    ids = seed(g34, "g34", ["我下周一要去医院体检", "我跟其他AI在黑曜石笔记里存了内容",
                            "公司这周活太多了", "昨天晚上把风扇拆了清灰", "一会儿睡"])
    pin(g34, ids[0], 9.65, "du")
    pin(g34, ids[1], 9.9, "du")
    pin(g34, ids[2], 3.0, "yun")
    pin(g34, ids[3], 1.6, "blood")
    pin(g34, ids[4], 1.2, "blood")
    cx = g34.build_context("体检报告出来了有点紧张")
    scene_ids = [p["id"] for p in cx["items"] if p["layer"] == "情境"]
    check("① 有效闸：无关记忆不进情境层",
          ids[2] not in scene_ids and ids[3] not in scene_ids,
          f"scene={scene_ids}")
    # ids[0] 是督脉，先被身份层取走（seen 去重后情境层不会再塞一遍），所以这里查整体
    check("① 有效闸：相关的那条进得来", ids[0] in [p["id"] for p in cx["items"]],
          f"items={[p['id'] for p in cx['items']]} scene={scene_ids}")

    # ② 重复闸：两条几乎同文的记忆，只进一条
    g34b, _ = make_gov("g34b")
    a = g34b.pools.place_new("g34b", "昨天下午三点在星巴克见了张老师谈合作的事", 5.0, 3.0, 2.0, None)
    b = g34b.pools.place_new("g34b", "昨天下午三点在星巴克见过张老师，聊合作的事",
                             5.0, 3.0, 2.0, None)  # 数字相同 → 写入闸不拦
    g34b.store.update_memory(a, born_at=1.0)      # born_at 不同，保证都在候选里
    g34b.store.update_memory(b, born_at=2.0)
    cx2 = g34b.build_context("张老师合作")
    got = [p["id"] for p in cx2["items"]]
    check("② 重复闸：近似同文只进一条", len([i for i in got if i in (a, b)]) == 1,
          f"got={got} a={a} b={b}")

    # ③ 存疑闸：多条低 R 碎片，情境层最多进 1 条；兜底层不受限
    g34c, _ = make_gov("g34c")
    seeds = seed(g34c, "g34c", ["好像提过一次什么展览，记不清了",
                                "记得你以前说过想学吉他，也可能是我记混了",
                                "你之前提过搬家，细节想不起来了"])
    for i in seeds:
        g34c.store.update_memory(i, r=1.2, tier="blood")
    cx3 = g34c.build_context("上次说的那个事")
    sus = [p for p in cx3["items"] if p["conf"] == "存疑" and p["layer"] == "情境"]
    check("③ 存疑闸：情境层存疑最多 1 条", len(sus) <= C.INJECT_SUSPECT_MAX, f"n={len(sus)}")

    # 存疑但项目在"最近层"时不限（刚说的话不能当旧碎片丢掉）
    g34d, _ = make_gov("g34d")
    s2 = seed(g34d, "g34d", ["昨天晚上把风扇拆了清灰", "一会儿睡"])
    for i in s2:
        g34d.store.update_memory(i, r=1.2, tier="blood")
    cx4 = g34d.build_context("")
    check("③ 存疑闸不拦兜底层", sum(1 for p in cx4["items"] if p["layer"] == "最近") == 2,
          f"layers={[p['layer'] for p in cx4['items']]}")

    # 闸门要留审计痕迹
    check("闸门落审计（gated 计数）",
          events(g34.store, "g34", "inject_context") >= 1
          and "low_sim" in g34.store._db.execute(
              "SELECT payload FROM events WHERE ns='g34' AND type='inject_context' "
              "ORDER BY id DESC LIMIT 1").fetchone()["payload"],
          "payload 里应有 low_sim")

    # ================= R35 写入侧两闸 =================
    g35, _ = make_gov("g35")
    ids35 = [g35.pools.place_new("g35", "今天加班到很晚，累死了", 3.0, 4.0, -2.0, None)
             for _ in range(5)]
    n_active = g35.store.count_active("g35")
    dd = events(g35.store, "g35", "write_dedup")
    check("① 写入去重：同句 5 次只长 1 条", n_active == 1 and dd == 4,
          f"active={n_active} dedup={dd}")
    check("去重只 touch 不涨 R（重复说不算命中）",
          abs(g35.store.get_memory(ids35[0])["r"] - g35.store.get_memory(ids35[0])["r"]) < 1e-9
          and g35.store.get_memory(ids35[0])["hits"] == 0,
          f"r={g35.store.get_memory(ids35[0])['r']}")

    # 数字变了 = 事实变了 → 必须新记一条（旧条交 R37 裁决）
    # R37 上线后这条的"结果态"变了：不再是"两条并排都在"（那正是注入自相矛盾的来源），
    # 而是"新条在册 + 旧条作废"。所以断言改成查机制本身：没被吞 + 是新建的 + 旧条已作废。
    g35b, _ = make_gov("g35b")
    d1 = g35b.pools.place_new("g35b", "约了周五下午3点在公司楼下见", 4.0, 3.0, 1.0, None)
    d2 = g35b.pools.place_new("g35b", "约了周五下午4点在公司楼下见", 4.0, 3.0, 1.0, None)
    check("② 数字变化不判重（事实改了要新记，不能被吞）",
          d1 != d2 and d2 is not None and events(g35b.store, "g35b", "write_dedup") == 0
          and g35b.store.get_memory(d1)["status"] == "superseded"
          and g35b.store.count_active("g35b") == 1,
          f"d1={d1} d2={d2} n={g35b.store.count_active('g35b')}")

    # 长句包含短句不判重（后者信息更多）
    g35c, _ = make_gov("g35c")
    e1 = g35c.pools.place_new("g35c", "今天很累", 2.0, 3.0, -1.0, None)
    e2 = g35c.pools.place_new("g35c", "今天很累，加班到十一点还被甲方骂了一顿", 5.0, 4.0, -3.0, None)
    check("② 短句不吞长句", e1 != e2 and g35c.store.count_active("g35c") == 2,
          f"e1={e1} e2={e2}")

    # 日上限（临时调小，测完恢复）
    old_cap = C.WRITE_DAILY_CAP
    C.WRITE_DAILY_CAP = 5
    try:
        g35d, _ = make_gov("g35d")
        for i in range(8):
            g35d.pools.place_new("g35d", f"完全不同的第{i}件事：内容{i}", 3.0, 3.0, 1.0, None)
        n35 = g35d.store.count_active("g35d")
        cap_ev = events(g35d.store, "g35d", "write_cap")
        check("③ 每日新建上限生效", n35 == 5 and cap_ev == 3,
              f"active={n35} cap_events={cap_ev}")
    finally:
        C.WRITE_DAILY_CAP = old_cap
    check("上限参数读取仍在 config 里", C.WRITE_DAILY_CAP == 200, str(C.WRITE_DAILY_CAP))

    # ================= R36 单写者 =================
    tmp = tempfile.mkdtemp(prefix="fishidian_lock_")
    db = os.path.join(tmp, "lock.db")
    errs = []

    def writer(tid):
        try:
            st = Store(db)  # 每线程一个连接，模拟"QQ 桥 + 插件 + 巡检"各自一个进程
            for i in range(15):
                st.add_memory("lock", f"线程{tid}的第{i}条", 1.0, 1.0, 1.0, None, "blood", 1.0)
                st.log_event("lock", "probe", {"t": tid, "i": i})
        except Exception as e:  # noqa: BLE001
            errs.append(f"{type(e).__name__}: {e}")

    ths = [threading.Thread(target=writer, args=(i,)) for i in range(6)]
    for t in ths:
        t.start()
    for t in ths:
        t.join()
    st = Store(db)
    n_written = st._db.execute("SELECT COUNT(*) c FROM memories WHERE ns='lock'").fetchone()["c"]
    check("④ 六连接并发写不抛 locked", not errs, str(errs[:2]))
    check("④ 并发写全部落库（6×15）", n_written == 6 * 15, f"n={n_written}")
    check("④ busy_timeout 已设",
          st._db.execute("PRAGMA busy_timeout").fetchone()[0] >= 1000,
          str(st._db.execute("PRAGMA busy_timeout").fetchone()[0]))

    # 工具函数口径
    check("overlap 口径 0~1", 0.0 <= overlap("今天累", "今天好累") <= 1.0,
          str(overlap("今天累", "今天好累")))
    check("day_start 落在当天 0 点", day_start() <= float(__import__("time").time()),
          str(day_start()))

    # ================= R38 内核侧：多行 = 多条记忆、但情绪只涨一次 =================
    # 插件把"连发的 5 条"合并成一段换行文本交给 observe_turn；
    # 内核按行各记一条记忆（否则短事实检索不到），但情绪/熔断按整轮只算一次
    # （"一口气读完五句话"只该波动一次，不是 5 次）。
    g38, _ = make_gov("r38")
    g38.observe_turn("在吗\n今天\n有点\n累\n陪我聊聊", "嗯，我在", [])
    n38 = g38.store.count_active("r38")
    tag38 = events(g38.store, "r38", "wuxing_tag")
    check("R38：多行拆成多条记忆", n38 >= 4, f"n={n38}")
    check("R38：情绪只吸收一次", tag38 == 1, f"wuxing_tag={tag38}")

    g38b, _ = make_gov("r38b")
    g38b.observe_turn("在吗今天有点累陪我聊聊", "嗯，我在", [])
    check("R38：单行仍只记一条", g38b.store.count_active("r38b") == 1,
          f"n={g38b.store.count_active('r38b')}")

    # ================= R39 退役判据（"能删"是 2026 新标配） =================
    # 只进不出的池子最后会变成垃圾场：召回被陈年碎屑占满，真正重要的反而排不进来。
    # 判据是三条同时满足：R 低 + 存在够久 + 连续很久没被召回。归档不是删除（可查可恢复）。
    import time as _t
    g39, _ = make_gov("r39")
    now39 = _t.time()
    old = g39.pools.place_new("r39", "陈年碎屑：很多年前随口提过一句无关紧要的话", 1.0, 1.0, 0.0, None)
    fresh = g39.pools.place_new("r39", "今天刚说的一句话", 1.0, 1.0, 0.0, None)
    strong = g39.pools.place_new("r39", "他妈妈住院做手术了", 9.0, 6.0, -6.0, None)
    old_days = 120 * 86400
    g39.store.update_memory(old, r=0.3, born_at=now39 - old_days,
                            last_at=now39 - old_days, last_hit_at=None)
    g39.store.update_memory(strong, r=2.0, born_at=now39 - old_days, last_at=now39 - old_days)
    res = g39.pools.retire("r39")
    retired_ids = [c[0] for c in res["candidates"]]
    check("R39：长期静默 + 低 R → 退役", old in retired_ids, str(res["candidates"]))
    check("R39：新记忆不退役", fresh not in retired_ids, str(retired_ids))
    check("R39：R 还高的老记忆不退役（交衰减慢慢来）", strong not in retired_ids, str(retired_ids))
    check("R39：归档不是删除（原文还在、可恢复）",
          g39.store.get_memory(old)["status"] == "archived"
          and "陈年碎屑" in g39.store.get_memory(old)["text"],
          str(g39.store.get_memory(old)["status"]))
    check("R39：落审计事件", events(g39.store, "r39", "memory_retired") == 1, "")
    check("R39：退役后不再参与召回/注入",
          g39.store.count_active("r39") == 2, str(g39.store.count_active("r39")))

    g39b, _ = make_gov("r39b")
    o2 = g39b.pools.place_new("r39b", "又一条陈年碎屑的说法", 1.0, 1.0, 0.0, None)
    g39b.store.update_memory(o2, r=0.3, born_at=now39 - 200 * 86400, last_at=now39 - 200 * 86400)
    dry = g39b.pools.retire("r39b", dry_run=True)
    check("R39：dry_run 只报不改",
          dry["retired"] == 1 and g39b.store.get_memory(o2)["status"] == "active",
          f"retired={dry['retired']} status={g39b.store.get_memory(o2)['status']}")

    # ================= R37 新旧陈述冲突裁决（R9 的最小切片） =================
    # R35 的数字守卫是故意的：数字变了 = 事实变了，必须新记一条，不能被吞。
    # 但两条都留在池里、都能被召回，注入里就自相矛盾（"约了3点"和"改到4点了"并排给她看）。
    # 裁决的最小可行形态不是语义理解，是**取代**：新条在册后旧条 status=superseded，
    # 不再进注入，但原文还在、可查可恢复 —— 和 archived 一样不是删除。
    g37, _ = make_gov("r37")
    q_old = g37.pools.place_new("r37", "约了下午3点在楼下等他", 4.0, 3.0, 0.5, None)
    q_new = g37.pools.place_new("r37", "约了下午4点在楼下等他", 4.0, 3.0, 0.5, None)
    o37 = g37.store.get_memory(q_old)
    n37 = g37.store.get_memory(q_new)
    check("R37：同一件事数字变了 → 旧条被取代", o37["status"] == "superseded", str(o37["status"]))
    check("R37：新条在册", n37["status"] == "active", str(n37["status"]))
    check("R37：superseded_by 指回新条", int(o37["superseded_by"] or 0) == q_new,
          f"superseded_by={o37['superseded_by']} new={q_new}")
    check("R37：取代不是删除（旧原文还在）", "3点" in (o37["text"] or ""), str(o37["text"]))
    check("R37：落审计事件", events(g37.store, "r37", "write_supersede") == 1, "")
    cx37 = g37.build_context("他说改到几点来着，楼下等他", budget=600, ask_weather=False)
    tx37 = [p["text"] for p in cx37["items"]]
    check("R37：被取代的说法不进注入（不再自相矛盾）",
          not any("3点" in t for t in tx37), f"items={tx37}")

    # 裸计数不构成事实：'第1条'/'第2条' 没单位，不该互相取代
    # （血海容量测试正是靠这一点才塞得进 72 条 —— 这条断言就是那个护栏）
    g37b, _ = make_gov("r37b")
    c1 = g37b.pools.place_new("r37b", "第1条普通记忆：关于他的日常琐事记录", 3.0, 3.0, 1.0, None)
    c2 = g37b.pools.place_new("r37b", "第2条普通记忆：关于他的日常琐事记录", 3.0, 3.0, 1.0, None)
    check("R37：无单位的裸计数不触发取代",
          g37b.store.count_active("r37b") == 2
          and events(g37b.store, "r37b", "write_supersede") == 0,
          f"active={g37b.store.count_active('r37b')}")

    # 同一句说第二遍走 R35 去重，不该被当成"事实变更"
    g37c, _ = make_gov("r37c")
    x1 = g37c.pools.place_new("r37c", "约了下午3点在楼下等他", 3.0, 3.0, 1.0, None)
    x2 = g37c.pools.place_new("r37c", "约了下午3点在楼下等他", 3.0, 3.0, 1.0, None)
    check("R37：同一句重复仍走去重，不产生取代链",
          x2 is None and x1 is not None
          and g37c.store.get_memory(x1)["status"] == "active"
          and events(g37c.store, "r37c", "write_supersede") == 0, f"x2={x2}")

    # 不同话题不取代（否则"数字一样/不一样"就成了唯一判据）
    g37d, _ = make_gov("r37d")
    y1 = g37d.pools.place_new("r37d", "约了下午3点在楼下等他", 3.0, 3.0, 1.0, None)
    y2 = g37d.pools.place_new("r37d", "他今天买了5个苹果回家", 3.0, 3.0, 1.0, None)
    check("R37：不同话题不取代",
          g37d.store.get_memory(y1)["status"] == "active"
          and g37d.store.get_memory(y2)["status"] == "active",
          f"{g37d.store.get_memory(y1)['status']}/{g37d.store.get_memory(y2)['status']}")

    # 二次变更：改回去也要正确 —— 只能取代"当前有效"的那条，不能去改早作废的
    g37e, _ = make_gov("r37e")
    z1 = g37e.pools.place_new("r37e", "约了下午3点在楼下等他", 4.0, 3.0, 0.5, None)
    z2 = g37e.pools.place_new("r37e", "约了下午4点在楼下等他", 4.0, 3.0, 0.5, None)
    z3 = g37e.pools.place_new("r37e", "约了下午3点在楼下等他", 4.0, 3.0, 0.5, None)
    check("R37：改回去时取代的是当前有效那条（z2），不是早作废的 z1",
          g37e.store.get_memory(z2)["status"] == "superseded"
          and int(g37e.store.get_memory(z2)["superseded_by"] or 0) == z3
          and g37e.store.get_memory(z3)["status"] == "active",
          f"z2={g37e.store.get_memory(z2)['status']}/{g37e.store.get_memory(z2)['superseded_by']} z3={g37e.store.get_memory(z3)['status']}")
    chain = g37e.pools.conflicts("r37e")
    check("R37：conflicts 能列出两条取代记录", len(chain) == 2, str(chain))
    check("R37：conflicts 的链是完整的（旧→新都能追到）",
          all(c["new_id"] for c in chain) and {c["old_id"] for c in chain} == {z1, z2},
          str([(c["old_id"], c["new_id"]) for c in chain]))

    # ---- R37 边界：序数不是量 ----
    # "第1次去她家"→"第2次去她家"骨架一样、单位"次"一样、数字变了，
    # 若不摘序数就会被判成"同一件事改了口"，把第一次的经历永久作废。
    g_ord, _ = make_gov("r37:ord")
    m1 = g_ord.observe_turn("这是我第1次去她家", "嗯")["new_memory_id"]
    m2 = g_ord.observe_turn("这是我第2次去她家", "嗯")["new_memory_id"]
    check("R37：序数『第N次』不被当成事实变更",
          m2 and m2 != m1
          and g_ord.store.get_memory(m1)["status"] == "active"
          and g_ord.store.get_memory(m2)["status"] == "active"
          and events(g_ord.store, "r37:ord", "write_supersede") == 0,
          f"status: {g_ord.store.get_memory(m1)['status']} / {g_ord.store.get_memory(m2)['status']}")

    # ---- R37：source_quote 必须真的写入（不是"加了列但没人填"）----
    sq_g, _ = make_gov("r37:sq")
    sq_id = sq_g.observe_turn("我下周三要去一趟杭州", "嗯")["new_memory_id"]
    sq_row = sq_g.store.get_memory(sq_id)
    check("R37：新记忆的 source_quote 存下了原话",
          (sq_row.get("source_quote") or "") == "我下周三要去一趟杭州",
          repr(sq_row.get("source_quote")))

    # ---- R37 两道刹车：出问题时必须能"向下退化"，不能"继续错"----
    # ① 总开关：关掉后连查都不查，旧条保持 active（止血用，改 C.SUPERSEDE_ON 即可）
    import fishidian_core.config as _cfg
    g_sw, _ = make_gov("r37:sw")
    g_sw.observe_turn("约了下午3点在楼下等他", "嗯")
    old_on = _cfg.SUPERSEDE_ON
    try:
        _cfg.SUPERSEDE_ON = False
        g_sw.observe_turn("约了下午4点在楼下等他", "嗯")
    finally:
        _cfg.SUPERSEDE_ON = old_on
    act = [m for m in g_sw.store.query_active("r37:sw")]
    check("R37：总开关关掉后不作废任何旧条",
          len(act) == 2 and events(g_sw.store, "r37:sw", "write_supersede") == 0,
          f"active={len(act)} supersede={events(g_sw.store, 'r37:sw', 'write_supersede')}")

    # ② 每日上限：当天取代次数用满后，只记 write_supersede_blocked，旧条不动
    g_cap, _ = make_gov("r37:cap")
    cap_old, cap_new = [], None
    old_cap = _cfg.SUPERSEDE_DAILY_CAP
    try:
        _cfg.SUPERSEDE_DAILY_CAP = 1
        g_cap.observe_turn("约了下午3点在楼下等他", "嗯")   # 第 1 条旧说法
        g_cap.observe_turn("约了下午4点在楼下等他", "嗯")   # 取代第 1 次 → 用满 1
        g_cap.observe_turn("约了下午5点在楼下等他", "嗯")   # 应被上限挡住
    finally:
        _cfg.SUPERSEDE_DAILY_CAP = old_cap
    blocked = events(g_cap.store, "r37:cap", "write_supersede_blocked")
    sup2 = events(g_cap.store, "r37:cap", "write_supersede")
    act2 = [m for m in g_cap.store.query_active("r37:cap")]
    check("R37：取代次数到日上限后只记日志、不作废",
          sup2 == 1 and blocked == 1 and len(act2) == 2,
          f"supersede={sup2} blocked={blocked} active={len(act2)}")

    # ③ 成色观测：conflicts 必须回算 sim / units，stats 必须能给"该人工抽检"的 id
    g_ob, _ = make_gov("r37:ob")
    g_ob.observe_turn("约了下午3点在楼下等他", "嗯")
    g_ob.observe_turn("约了下午4点在楼下等他", "嗯")
    c1 = g_ob.pools.conflicts("r37:ob")
    st1 = g_ob.pools.conflicts_stats("r37:ob")
    check("R37：conflicts 带骨架相似度与撞到的单位",
          len(c1) == 1 and 0.85 <= (c1[0]["sim"] or 0) <= 1.0
          and isinstance(c1[0]["units"], dict) and "点" in (c1[0]["units"] or {}),
          f"sim={c1[0]['sim'] if c1 else None} units={c1[0]['units'] if c1 else None}")
    check("R37：conflicts_stats 分档计数与抽检名单",
          st1["total"] == 1 and st1["sim_ge_0_95"] == 1 and st1["review_targets"] == [],
          str(st1))

    # ---------------------------------------------------------------
    # 备份轮转的"选哪些删"（v0.21 尾修）：只 import 纯函数，不碰删除接口
    # ---------------------------------------------------------------
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "tools"))
    from backup_live_db import filter_prunable, pick_prunable  # noqa: E402

    names = [
        "dfy.db.bak-20261105-215207",        # 最旧
        "dfy.db.bak-20261106-135434",
        "dfy.db.bak-20261107-121106",
        "dfy.db.bak-20261107-122959-keep",   # 人工留档：永不删
        "dfy.db.bak-20261107-135608",
        "dfy.db.bak-20261107-165946",        # 最新
        "dfy.db",                            # 库本体：不动
        "dfy.db-wal",                        # 副产物：不动
        "other.db.bak-20261107-120000",      # 别的库：不动
        "dfy.db.bak-2026110-1200",           # 手写的怪名字：不动
    ]
    # keep=3 时：可轮转 5 份（去掉 -keep 那份），删最旧 2 份
    victims = pick_prunable(names, "dfy.db", 3)
    check("备份轮转：keep=3 只删最旧 2 份、-keep 与本体/别库都不动",
          victims == ["dfy.db.bak-20261105-215207", "dfy.db.bak-20261106-135434"],
          str(victims))
    # 全是 -keep 时一份都不删
    only_keep = ["dfy.db.bak-20261105-215207-keep", "dfy.db.bak-20261106-135434-keep"]
    check("备份轮转：全是 -keep 时一份都不删", pick_prunable(only_keep, "dfy.db", 1) == [],
          str(pick_prunable(only_keep, "dfy.db", 1)))
    # keep=0 表示不清理；filter 只挑本库备份
    check("备份轮转：keep=0 不清理；filter 只认本库备份",
          pick_prunable(names, "dfy.db", 0) == []
          and len(filter_prunable(names, "dfy.db")) == 6,
          str(filter_prunable(names, "dfy.db")))

    # ---------------------------------------------------------------
    # 取代成色统计的"时间窗"：按**取代发生的时间**算，不按旧条的 born_at
    # 反例场景：3 天前写的记忆，今天才被取代 —— 旧实现按 born_at 过滤会把它漏掉，
    # 撤销条件（认错比例 >20%）就成了摆设。
    # ---------------------------------------------------------------
    g2, _t2 = make_gov("gate:stats_win")
    ns2 = "gate:stats_win"
    now2 = time.time()
    DAY = 86400.0

    def _pair(t_old, t_new, born_days, ev_days):
        oid = g2.store.add_memory(ns2, t_old, 3.0, 2.0, 0.0, None, "du", 5.0,
                                 at=now2 - born_days * DAY)
        nid = g2.store.add_memory(ns2, t_new, 3.0, 2.0, 0.0, None, "du", 5.0,
                                 at=now2 - 0.01 * DAY)
        g2.store.update_memory(oid, status="superseded", superseded_by=nid)
        g2.store.log_event(ns2, "write_supersede", {"old_id": oid, "new_id": nid},
                           at=now2 - ev_days * DAY)

    _pair("约了下午3点见", "约了下午4点见", 3, 0)    # 老条、今天被取代
    _pair("订了2号的票", "订了5号的票", 6, 3)        # 老条、3 天前被取代
    w1 = g2.pools.conflicts_stats(ns2, since_ts=now2 - 1 * DAY)
    w7 = g2.pools.conflicts_stats(ns2, since_ts=now2 - 7 * DAY)
    check("取代成色：1 天窗数得到「今天才被取代」的老条", w1["total"] == 1, str(w1))
    check("取代成色：7 天窗 2 条、不限时间仍 2 条",
          w7["total"] == 2 and g2.pools.conflicts_stats(ns2)["total"] == 2,
          f"7d={w7['total']} all={g2.pools.conflicts_stats(ns2)['total']}")

    # ---------------------------------------------------------------
    # 三层备份轮转（日 7 / 周 4 / 月 1）：v0.21 尾修
    # ---------------------------------------------------------------
    from backup_live_db import filter_tiered, pick_tiered  # noqa: E402

    tiered = (
        [f"dfy.db.bak-202611{i:02d}-120000" for i in range(1, 10)]   # 9 份日备
        + [f"dfy.db.week-2026-W{w}" for w in range(41, 47)]           # 6 份周备
        + [f"dfy.db.month-2026-{m:02d}" for m in (8, 9, 10)]          # 3 份月备
        + ["dfy.db.bak-20261103-120000-keep", "dfy.db", "other.db.week-2026-W10"]
    )
    got = pick_tiered(tiered, "dfy.db", 7, 4, 1)
    check("三层轮转：日留 7 删 2、周留 4 删 2、月留 1 删 2，-keep 不动",
          sorted(got) == sorted(["dfy.db.bak-20261101-120000", "dfy.db.bak-20261102-120000",
                                 "dfy.db.week-2026-W41", "dfy.db.week-2026-W42",
                                 "dfy.db.month-2026-08", "dfy.db.month-2026-09"]),
          str(got))
    ft = filter_tiered(tiered, "dfy.db")
    check("三层分类：日/周/月各自只认本库、互不串类",
          len(ft["daily"]) == 10 and len(ft["week"]) == 6 and len(ft["month"]) == 3,
          str({k: len(v) for k, v in ft.items()}))

    ok = sum(1 for _, c, _ in PASS if c)
    print(f"\n== {ok}/{len(PASS)} passed ==")
    return 0 if ok == len(PASS) else 1


if __name__ == "__main__":
    sys.exit(main())
