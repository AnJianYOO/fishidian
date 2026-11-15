# -*- coding: utf-8 -*-
"""fishidian-core CLI 桥 —— DSH 插件（dsh-fishidian）通过子进程调用：
    python cli.py <ns> <db_path> <cmd> [args...]   （stdout 输出 JSON）
零常驻进程、无端口；治理层异常时返回 {"error": ...}，插件降级为无记忆回复，不阻塞聊天。"""
from __future__ import annotations

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 强制 stdout 用 UTF-8：Windows 上 python 默认按 GBK 输出，插件（Node spawnSync
# encoding=utf8）按 UTF-8 解码会得到乱码，导致记忆注入的中文不可读。
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from fishidian_core import Governor, Store  # noqa: E402


def _fmt_items(items):
    out = []
    for m, rec, sim, adopt in items:
        out.append({
            "id": m["id"], "text": m["text"], "r": round(m["r"], 3),
            "tier": m["tier"], "importance": m["importance"],
            "arousal": m["arousal"], "valence": m["valence"],
            "recall": rec, "sim": round(sim, 4), "adopt": adopt,
            "born_at": m["born_at"], "last_at": m["last_at"],
        })
    return out


def main():
    args = sys.argv[1:]
    if len(args) < 3:
        print(json.dumps({"error": "usage: cli.py <ns> <db_path> <cmd> ..."}))
        return 1
    ns, db, cmd = args[0], args[1], args[2]
    rest = args[3:]
    g = Governor(ns, store=Store(db))
    out = {}
    try:
        if cmd == "recall":
            q = rest[0] if rest else ""
            k = int(rest[1]) if len(rest) > 1 else 6
            out = {"items": _fmt_items(g.recall(q, k=k))}
        elif cmd == "context":
            # context <user_text> [ask_weather=0|1] [budget]
            # 一轮注入的全部上下文：分层记忆（身份/情境/最近）+ 置信三档 + 状态 + 时间 + 表达
            # —— 一次进程拿齐，插件不再 spawn export/state/time/expression 四次
            q = rest[0] if rest else ""
            ask_w = (rest[1] == "1") if len(rest) > 1 else False
            budget = int(rest[2]) if len(rest) > 2 else None
            out = g.build_context(q, budget=budget, ask_weather=ask_w)
        elif cmd == "inject":
            q = rest[0] if rest else ""
            k = int(rest[1]) if len(rest) > 1 else 6
            budget = int(rest[2]) if len(rest) > 2 else 600
            out = {"injection": g.build_injection(g.recall(q, k=k), budget=budget)}
        elif cmd == "observe":
            user_text = rest[0] if rest else ""
            asst = rest[1] if len(rest) > 1 else ""
            cited = rest[2].split(",") if len(rest) > 2 and rest[2] else None
            out = g.observe_turn(user_text, asst, cited_ids=cited)
        elif cmd == "sweep":
            out = {"report": g.sweep()}
        elif cmd == "retire":
            # retire [dry_run=0|1]：R39 退役判据（归档长期没被召回、R 已掉到地板的记忆）
            dry = (rest[0] == "1") if rest else False
            out = g.pools.retire(ns, dry_run=dry)
        elif cmd == "conflicts":
            # conflicts：R37 取代链（旧说法 → 新说法）。不是删除，随时可查可恢复
            # conflicts stats [天数]：判据成色统计（按骨架相似度分档 + 给出该人工抽检的 id）
            if rest and rest[0] == "stats":
                # 天数参数容错：命令行里传错（写了 7d、或者写了个中文）不该整个命令崩掉，
                # 退化成"不给时间窗"即可 —— CLI 是运维手边的东西，健壮性优先于严格。
                days = None
                if len(rest) > 1:
                    try:
                        days = float(str(rest[1]).rstrip("d"))
                    except ValueError:
                        days = None
                since = (time.time() - days * 86400.0) if days else None
                out = {"conflicts_stats": g.pools.conflicts_stats(ns, since)}
            else:
                out = {"conflicts": g.pools.conflicts(ns)}
        elif cmd == "tick":
            # tick [force=0|1]：走一步心跳。force=1 忽略变化检测，强制注入一次
            force = (rest[0] == "1") if rest else False
            out = g.tick(force=force)
        elif cmd == "env":
            # env：只看当前环境快照（时辰/节气/天气/日照），不写库
            out = g._sample_env(time.time())
        elif cmd == "settle":
            # settle：手动触发重逢结算（测试用；正常由开场自动触发）
            out = {"settled": g.settle_gap()}
        elif cmd == "state":
            out = g.state()
        elif cmd == "list":
            kw = rest[0] if rest else ""
            limit = int(rest[1]) if len(rest) > 1 else 20
            out = {"memories": g.list_memories(kw, limit=limit)}
        elif cmd == "forget":
            out = {"ok": g.forget(int(rest[0]))}
        elif cmd == "export":
            out = g.export()
        elif cmd == "fuse-release":
            out = {"ok": g.manual_fuse_release()}
        elif cmd == "wuxing":
            out = g.wuxing_state()
        elif cmd == "coldwar":
            out = g.coldwar_state()
        elif cmd == "proactive":
            # proactive [deliver]：0=想发但没发（只记 0）1=真发出去了（记成功）省略=只探测不记账
            dv = {"1": True, "0": False}.get(rest[0] if rest else None)
            out = g.proactive_check(deliver=dv)
        elif cmd == "echo":
            # echo → 规则回声：把真实记忆拼成一句她心里的话（主动消息的第二候选）
            # 情报层没话题时用它，比"我在想你最近还好吗"这种模板问候有人味。
            from fishidian_core.echo import echo_from_store
            out = {"echo": echo_from_store(g.store, ns)}
        elif cmd == "promise":
            # promise <text> → 记一条承诺（落事件表，可查可统计）
            out = g.register_promise(" ".join(rest))
        elif cmd == "promise-done":
            # promise-done [关键词] [broken] → 把承诺标成兑现 / 没做到
            # 没有这个命令，承诺永远停在 open，过了限期全部变成"欠着"，
            # 包括早就做到的那些——她会反复提一件已经办完的事。
            kw = rest[0] if rest and rest[0] != "broken" else None
            broken = "broken" in rest
            out = g.resolve_promise(kw, kept=not broken)
        elif cmd == "drift":
            # drift                  → 看自动检测现在在不在偏移里、哪一维、证据是什么
            # drift <dim> <level> .. → 手工补记一次（运维用，自动检测已会自己记）
            if not rest:
                out = g.drift.state()
            elif len(rest) < 2:
                out = {"error": "usage: drift [<dim> <level> [since] [note]]"}
            else:
                out = g.record_drift(rest[0], rest[1],
                                     rest[2] if len(rest) > 2 else None,
                                     " ".join(rest[3:]) if len(rest) > 3 else None)
        elif cmd == "expression":
            out = g.expression_state()
        elif cmd == "intel":
            # intel [--no-net]  → 通用外部情报层：记忆推导兴趣 × 天气/节日/新闻过滤
            from fishidian_core.intel import Intel
            no_net = "--no-net" in rest
            # 兴趣是长期画像：看全部记忆（含归档），而非仅 active
            mems = g.store.query_all(ns, limit=500)
            out = Intel(g.store, ns, no_net=no_net).collect(mems)
        elif cmd == "time":
            # time → 当前时间画像（纯本地：时刻/星期/时段/时辰干支/节气）
            #        + 社交时间（距上次对话、对方活跃时段；从记忆时间戳统计）
            from fishidian_core.intel import social_context, time_context
            out = time_context()
            out.update(social_context(g.store, ns))
        elif cmd == "weather":
            # weather [city] → 查天气：有参数则顺带记住（=用户刚回答的城市）；
            # 无参数用已记住的城市；都没有 → need_city，由桥去问用户。
            from fishidian_core.intel import fetch_weather, get_city, set_city
            city_arg = " ".join(rest).strip()
            if city_arg:
                city = set_city(g.store, ns, city_arg) or city_arg
            else:
                city = get_city(g.store, ns)
            if not city:
                out = {"need_city": True}
            else:
                w = fetch_weather(city)
                out = ({"ok": True, "city": city, "weather": w} if w else
                       {"ok": False, "city": city, "error": "天气源没回数据（网络或城市名识别问题）"})
        elif cmd == "set-city":
            # set-city <city> → 记住城市（“问我在哪 → 用户答 → 记住”的落点）
            from fishidian_core.intel import set_city
            saved = set_city(g.store, ns, " ".join(rest))
            out = {"ok": True, "city": saved} if saved else {"error": "城市名为空或过长"}
        elif cmd == "govern":
            # govern <assistant_text> [contrib0,contrib1,...]  → 输出治理链（自动并入五行 boost）
            text = rest[0] if rest else ""
            contribs = None
            if len(rest) > 1:
                try:
                    contribs = [float(x) for x in rest[1].split(",") if x]
                except Exception:
                    contribs = None
            out = g.govern_output(text, emotion_contributions=contribs,
                                  wuxing_boost=g.wuxing.emotion_boost())
        else:
            out = {"error": "unknown cmd: " + cmd}
    except Exception as e:  # 治理层异常 → 插件降级，不阻塞聊天
        out = {"error": f"{type(e).__name__}: {e}"}
    print(json.dumps(out, ensure_ascii=False))
    return 0 if "error" not in out else 2


if __name__ == "__main__":
    sys.exit(main())
