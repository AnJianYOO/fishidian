# -*- coding: utf-8 -*-
"""E4 召回评测基线（默认跑冻结快照，不随活库漂移）。

评审点出的问题：以前这个脚本拷"活库"，题目期望的却是写死的 id。库从 58 条长到 61 条，
top3 排序就变了 —— 于是同一套题昨天 50%、今天 55%，改机制前后的分数根本没可比性。

现在默认跑 `eval/frozen_2026-11-06.db`（写死的一份快照）：
  · 改检索前跑一次 = 对照基线
  · 改检索后再跑一次 = 同一批输入、同一批期望，分数差就是机制差
活库只在需要看"此刻真实表现"时用，通过参数显式指定。

用法：
    python -X utf8 tests/eval_recall_baseline.py                    # 冻结快照
    python -X utf8 tests/eval_recall_baseline.py <库路径> [ns]       # 指定库
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fishidian_core import Governor, Store  # noqa: E402

_HERE = os.path.dirname(os.path.abspath(__file__))
FROZEN_DB = os.path.join(os.path.dirname(_HERE), "eval", "frozen_2026-11-06.db")
DEFAULT_DB = os.path.join(os.path.expanduser("~"), ".dsh", "dafeiyu-memory", "dfy.db")

# (用户这句话, 期望想起的记忆 id 集合——任一出现在 top3 即算命中)
PROBES = [
    ("我下周一要干什么来着", {14, 17}),
    ("那个黑曜石笔记里存了啥", {29}),
    ("我是不是教过你查天气", {45}),
    ("今天我中午吃的什么", {20, 50}),
    ("我下班了没", {53, 54}),
    ("公司最近活多不多", {23}),
    ("客户那边出什么事了", {24}),
    ("今天天气咋样", {21, 44, 3}),
    ("我昨晚几点睡的", {40, 59, 58}),
    ("那个插件最后装上没有", {17}),
    ("我怎么让你能一次发好几条的", {48, 39}),
    ("你说我像我妈那事儿", {55}),
    ("下午还得干活吗", {51}),
    ("你现在在不在", {7}),
    ("我说话是不是有点生分", {19}),
    ("那个路径我是从哪发给你的", {30}),
    ("Dsh 那边数据跟你互通吗", {33}),
    ("你那套情绪系统有啥指令", {35}),
    ("我说算了不弄了那件事", {34}),
    ("今天累不累", {5}),
]


def main():
    db_path = sys.argv[1] if len(sys.argv) > 1 else FROZEN_DB
    ns = sys.argv[2] if len(sys.argv) > 2 else "dsh:desktop"
    if not os.path.exists(db_path):
        raise SystemExit(f"库不存在：{db_path}\n（快照应放在 {FROZEN_DB}，见 eval/README 说明）")
    tag = "冻结快照" if os.path.abspath(db_path) == os.path.abspath(FROZEN_DB) else "活库/指定库"
    tmp = os.path.join(tempfile.mkdtemp(prefix="fishidian_eval_"), "copy.db")
    shutil.copyfile(db_path, tmp)          # 只读副本：recall 会 touch，不能直接跑在源库上
    g = Governor(ns, store=Store(tmp))

    hit, details = 0, []
    for q, want in PROBES:
        got = [m["id"] for m, _, _, _ in g.recall(q, k=3)]
        ok = bool(want & set(got))
        hit += ok
        details.append((q, sorted(want), got, ok))

    for q, want, got, ok in details:
        print(("  ✔ " if ok else "  ✘ ") + f"{q}  期望{want} 得到{got}")
    total = len(PROBES)
    print(f"\n召回命中 {hit}/{total} = {hit / total:.0%}   （{tag}：{db_path} ns={ns}）")
    print("基线记录：这正是 A2（bge+BM25+RRF）要超过的数；当前后端 %s" % g.embed.backend)
    print("比较规则：改机制前后都用冻结快照跑，分数差才是机制差；换库=换尺子，不可比。")


if __name__ == "__main__":
    main()
