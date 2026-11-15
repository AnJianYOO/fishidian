# -*- coding: utf-8 -*-
"""大肥鱼内核压力测试（用户 2026-11-11 追加）

三部分：
  A 规模     —— 200 / 1000 / 3000 条记忆，看各操作的耗时是不是随数据量爆炸
  B 极端输入 —— 超长 / 空 / None / emoji / 引号 / 重复，看会不会崩或静默丢
  C 并发写   —— 4 个进程同时写同一个库，看 SQLite 会不会丢数据或锁死

判据不是“跑得动”，是三条：
  1. 有没有抛异常
  2. 有没有**静默丢数据**（写进去了但查不出来 / 写 1000 条只剩 900）
  3. 耗时是不是随数据量超线性（O(N²) 会在大数据下直接不可用）

用法：python -X utf8 tools/stress_test.py
"""
import json
import multiprocessing as mp
import os
import shutil
import sys
import tempfile
import time
import traceback

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "fishidian-core")
sys.path.insert(0, ROOT)

from fishidian_core.store import Store
from fishidian_core.governor import Governor

TMP = os.path.join(tempfile.gettempdir(), "_fish_stress")
LEVELS = [200, 1000, 3000]
SLOW = {"write_ms": 100.0, "recall_ms": 800.0, "context_ms": 800.0, "brief_ms": 300.0}

SENTENCES = [
    "今天加班到十点，脑子已经不动了",
    "周末想去看海，但是怕下雨",
    "我妈今天打电话问我吃饭没有",
    "这个项目拖了三周还没验收，烦",
    "昨晚没睡好，早上起来头疼",
    "楼下那家面馆换老板了，味道变了",
    "想养只猫，又怕出差没人管",
    "同事借了我的充电器一直没还",
    "突然想吃小时候那种冰棍",
    "体检报告出来，血脂有点高",
]


def fresh_db(tag):
    os.makedirs(TMP, exist_ok=True)
    db = os.path.join(TMP, "s_%s.db" % tag)
    for suf in ("", "-wal", "-shm"):
        p = db + suf
        if os.path.exists(p):
            try:
                os.remove(p)
            except OSError:
                pass
    return db


def ms(t0):
    return round((time.perf_counter() - t0) * 1000.0, 1)


def run_level(n, tag):
    """写 n 条，再量各操作的耗时与正确性。"""
    db = fresh_db(tag)
    g = Governor("stress", store=Store(db))
    row = {"n": n}

    # --- 写入 ---
    # 必须**按天摊开**：WRITE_DAILY_CAP=200 是防刷屏的设计，如果 3000 条全挤在
    # 同一天，2800 条会被日配额直接拒掉，压测量的是空转不是入库。
    # 真实场景是"聊 30 天攒 3000 条"，所以时间戳按 30 天摊。
    t0 = time.perf_counter()
    wrote = 0
    base = time.time() - 31 * 86400.0
    per_day = max(1, int(round(n / 30.0)))
    for i in range(n):
        try:
            at = base + (i // per_day) * 86400.0 + (i % per_day) * 60.0
            g.observe_turn(SENTENCES[i % len(SENTENCES)] + " #%d" % i,
                           "嗯，我听着。" if i % 3 else "那你先歇会儿。",
                           at=at)
            wrote += 1
        except Exception as e:
            row.setdefault("write_errors", []).append("%s: %s" % (type(e).__name__, e))
    row["write_total_ms"] = ms(t0)
    row["write_ms"] = round(row["write_total_ms"] / max(wrote, 1), 2)
    row["wrote"] = wrote

    # --- 静默丢数据检查 ---
    # 注意：query_active 只返回"血池"激活集，上限 CAP_BLOOD=72，**不等于丢数据**。
    # 真正要查的是全量（含归档）。所以两个都记，判定只看全量。
    try:
        row["active_after"] = len(g.store.query_active("stress"))
        row["total_after"] = len(g.store.query_all("stress"))
    except Exception as e:
        row["active_error"] = "%s: %s" % (type(e).__name__, e)

    # --- 各操作耗时 ---
    try:
        t0 = time.perf_counter(); g.recall("今天加班很累"); row["recall_ms"] = ms(t0)
    except Exception as e:
        row["recall_error"] = "%s: %s" % (type(e).__name__, e)

    try:
        t0 = time.perf_counter(); ctx = g.build_context("今天加班很累"); row["context_ms"] = ms(t0)
        row["ctx_keys_ok"] = isinstance(ctx, dict) and "injection" in ctx
    except Exception as e:
        row["context_error"] = "%s: %s" % (type(e).__name__, e)

    try:
        t0 = time.perf_counter(); g.state(); row["state_ms"] = ms(t0)
    except Exception as e:
        row["state_error"] = "%s: %s" % (type(e).__name__, e)

    try:
        t0 = time.perf_counter(); g.comfort_decide("今天加班很累"); row["comfort_ms"] = ms(t0)
    except Exception as e:
        row["comfort_error"] = "%s: %s" % (type(e).__name__, e)

    try:
        t0 = time.perf_counter(); g.drift.daily_mood(14); row["daily_mood_ms"] = ms(t0)
    except Exception as e:
        row["daily_mood_error"] = "%s: %s" % (type(e).__name__, e)

    # --- 健康台账：接点有没有静默失败 ---
    try:
        h = g.health()
        row["health"] = {k: v.get("n") for k, v in h.items()} if h else {}
    except Exception as e:
        row["health_error"] = "%s: %s" % (type(e).__name__, e)

    # --- 库体积 ---
    try:
        row["db_kb"] = os.path.getsize(db) // 1024
    except OSError:
        row["db_kb"] = None

    g.store.close()
    return row


def run_extreme():
    """边界输入：看会不会崩、会不会静默吞掉。"""
    db = fresh_db("ext")
    g = Governor("edge", store=Store(db))
    out = []

    cases = [
        ("超长 10000 字", "啊" * 10000, "嗯。"),
        ("空串", "", ""),
        ("纯空白", "   \n\t  ", "  "),
        ("纯 emoji", "😀😭😡🥲" * 20, "🥺"),
        ("英文长句无空格", "a" * 3000, "b" * 3000),
        ("含引号与反斜杠", '他说"别管我"，还有\\n和\'单引号\'', '好。'),
        ("含 SQL 片段", "'; DROP TABLE items; --", "嘿嘿。"),
        ("超长回复", "今天", "很长很长" * 2000),
    ]
    for name, u, a in cases:
        t0 = time.perf_counter()
        try:
            g.observe_turn(u, a)
            r = g.build_context(u[:200])
            okk = isinstance(r, dict) and "injection" in r
            out.append({"case": name, "ok": okk, "ms": ms(t0), "err": None})
        except Exception as e:
            out.append({"case": name, "ok": False, "ms": ms(t0),
                        "err": "%s: %s" % (type(e).__name__, e)})

    # 重复写入同一条 50 次：去重该吃掉大部分，但不能全丢
    t0 = time.perf_counter()
    for _ in range(50):
        try:
            g.observe_turn("重复测试这句话", "嗯。")
        except Exception as e:
            out.append({"case": "重复写入", "ok": False, "err": str(e)})
    out.append({"case": "重复 50 次", "ok": True, "ms": ms(t0)}
               if not any(o.get("case") == "重复写入" for o in out) else {"case": "重复写入失败"})

    try:
        out.append({"case": "重复后条数", "active": len(g.store.query_active("edge")),
                    "ok": True})
    except Exception as e:
        out.append({"case": "重复后条数", "ok": False, "err": str(e)})

    # 极端时间戳：0 / 未来 / 负数
    for ts in (0, -1, 1e12):
        try:
            g.drift.observe(val=-0.5, aro=0.2, reply_len=10, at=ts)
            out.append({"case": "时间戳 %s" % ts, "ok": True})
        except Exception as e:
            out.append({"case": "时间戳 %s" % ts, "ok": False, "err": str(e)})

    g.store.close()
    return out


def _writer(dbpath, ns, count, q):
    """并发写入的子进程。"""
    errs, wrote = [], 0
    try:
        g = Governor(ns, store=Store(dbpath))
        for i in range(count):
            try:
                g.observe_turn("并发写 %d-%d" % (os.getpid(), i), "嗯。")
                wrote += 1
            except Exception as e:
                errs.append("%s: %s" % (type(e).__name__, e))
        g.store.close()
    except Exception as e:
        errs.append("open: %s: %s" % (type(e).__name__, e))
    q.put({"pid": os.getpid(), "wrote": wrote, "errs": errs})


def run_concurrent(procs=4, per=30):
    db = fresh_db("con")
    q = mp.Queue()
    ps = [mp.Process(target=_writer, args=(db, "con", per, q)) for _ in range(procs)]
    for p in ps:
        p.start()
    for p in ps:
        p.join(120)

    got = []
    while not q.empty():
        got.append(q.get())
    wrote = sum(x["wrote"] for x in got)
    errs = [e for x in got for e in x["errs"]]

    alive = None
    try:
        st = Store(db)
        alive = len(st.query_all("con"))
        # 看有没有半边数据（同一条记录写了一半）
        broken = st.query_all("con")
        st.close()
    except Exception as e:
        errs.append("verify: %s: %s" % (type(e).__name__, e))
        broken = []

    return {
        "procs": procs, "per": per, "expect": procs * per,
        "wrote": wrote, "alive": alive,
        "zombie_procs": [p.pid for p in ps if p.exitcode not in (0, None)],
        "exitcodes": [p.exitcode for p in ps],
        "errs": errs[:12],
        "err_count": len(errs),
        "broken": len([b for b in broken if not b.get("text")]),
    }


def main():
    if not os.path.isdir(TMP):
        os.makedirs(TMP)
    t_all = time.perf_counter()
    report = {"levels": [], "extreme": [], "concurrent": None}

    print("=== A 规模 ===")
    for n in LEVELS:
        r = run_level(n, "n%d" % n)
        report["levels"].append(r)
        print(json.dumps(r, ensure_ascii=False))
        sys.stdout.flush()

    print("=== B 极端输入 ===")
    ex = run_extreme()
    report["extreme"] = ex
    for e in ex:
        print(json.dumps(e, ensure_ascii=False))
    sys.stdout.flush()

    print("=== C 并发写（4 进程 × 30 条） ===")
    cc = run_concurrent()
    report["concurrent"] = cc
    print(json.dumps(cc, ensure_ascii=False))

    report["total_s"] = round(time.perf_counter() - t_all, 1)

    # ---- 结论判定 ----
    verdicts = []
    lv = report["levels"]
    if len(lv) >= 2:
        small, big = lv[0], lv[-1]
        for key in ("recall_ms", "context_ms", "write_ms"):
            if small.get(key) and big.get(key):
                ratio = big[key] / max(small[key], 0.01)
                scale = big["n"] / float(small["n"])
                verdicts.append({
                    "metric": key, "small": small[key], "big": big[key],
                    "scale_x": round(scale, 1), "growth_x": round(ratio, 1),
                    "linear_ok": ratio < scale * 2,
                })
    for l in lv:
        # 全量条目数会少于写入数（合并/取代/去重都正常），但不能少得离谱
        if l.get("total_after") is not None and l["total_after"] <= 0 and l["n"] > 0:
            verdicts.append({"warn": "全量空了 n=%s" % l["n"]})
        if (l.get("total_after") or 0) < l.get("wrote", 0) * 0.3:
            verdicts.append({"warn": "全量只剩 30%% 以下 n=%s" % l["n"],
                             "total_after": l.get("total_after"),
                             "wrote": l.get("wrote")})
        if l.get("health"):
            verdicts.append({"warn": "接点出过错 n=%s" % l["n"], "health": l["health"]})
        for k, th in SLOW.items():
            if l.get(k) and l[k] > th:
                verdicts.append({"warn": "慢 %s=%s ms n=%s" % (k, l[k], l["n"])})
    bad_ext = [e for e in ex if not e.get("ok")]
    if bad_ext:
        verdicts.append({"warn": "极端输入失败", "cases": bad_ext})
    if cc["wrote"] < cc["expect"]:
        verdicts.append({"warn": "并发写入丢 %d 条" % (cc["expect"] - cc["wrote"])})
    if cc["err_count"]:
        verdicts.append({"warn": "并发报错 %d 次" % cc["err_count"]})

    report["verdicts"] = verdicts
    print("\n=== 判定 ===")
    print(json.dumps(verdicts, ensure_ascii=False, indent=1))

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_stress_report.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print("\n报告: %s" % out)
    print("总耗时 %.1fs" % report["total_s"])


if __name__ == "__main__":
    main()
