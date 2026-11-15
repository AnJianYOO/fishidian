# -*- coding: utf-8 -*-
"""功能登记簿校验：features.json -> FEATURES.md 的表，以及"登记 vs 现实"对账。

用法：
    python -X utf8 tools/feature_check.py            # 校验（表过期/落点缺失/编号不存在都会失败）
    python -X utf8 tools/feature_check.py --write-md  # 用 features.json 重写 FEATURES.md 的表区
    python -X utf8 tools/feature_check.py --table     # 只打印表格

设计意图：功能清单只有一处真源（features.json）。人读的表是生成物，所以"文档漂移"能被脚本抓到，
而不是靠人记得去改两份。
"""
from __future__ import annotations

import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JSON_PATH = os.path.join(ROOT, "features.json")
MD_PATH = os.path.join(ROOT, "FEATURES.md")

BEGIN = "<!-- AUTO-TABLE:BEGIN -->"
END = "<!-- AUTO-TABLE:END -->"
STATUS_CN = {
    "planned": "规划中",
    "designed": "已设计",
    "shipped": "已落地",
    "suspended": "挂起",
    "rejected": "否决",
}


def load() -> dict:
    with open(JSON_PATH, encoding="utf-8") as fh:
        return json.load(fh)


def render_table(features: list) -> str:
    rows = [
        "| ID | 功能 | 状态 | 优先级 | 发布版本 | 决策 | 路线图 | 主要落点 |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for f in sorted(features, key=lambda x: x["id"]):
        st = STATUS_CN.get(f["status"], f["status"])
        lands = f.get("lands") or []
        code = "、".join(os.path.basename(l["path"]) for l in lands[:2]) or "—"
        rows.append(
            f"| {f['id']} | {f['name']} | {st} | {f.get('priority') or '—'} "
            f"| {f.get('release') or '—'} | {f.get('decision') or '—'} "
            f"| {f.get('roadmap') or '—'} | {code} |"
        )
    return "\n".join(rows)


def write_md(table: str) -> int:
    with open(MD_PATH, encoding="utf-8") as fh:
        text = fh.read()
    if BEGIN not in text or END not in text:
        print(f"[失败] {os.path.basename(MD_PATH)} 里没有 {BEGIN} / {END} 标记，无法写入")
        return 1
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    new = f"{head}{BEGIN}\n{table}\n{END}{tail}"
    with open(MD_PATH, "w", encoding="utf-8") as fh:
        fh.write(new)
    print(f"[写入] {os.path.basename(MD_PATH)} 表区已按 features.json 重写（{len(table.splitlines()) - 2} 条）")
    return 0


def read_md_table() -> str | None:
    with open(MD_PATH, encoding="utf-8") as fh:
        text = fh.read()
    if BEGIN not in text or END not in text:
        return None
    return text.split(BEGIN, 1)[1].split(END, 1)[0].strip()


def main() -> int:
    args = set(sys.argv[1:])
    data = load()
    feats = data["features"]
    table = render_table(feats)

    if "--table" in args:
        print(table)
        return 0
    if "--write-md" in args:
        return write_md(table)

    problems: list[str] = []
    ids = [f["id"] for f in feats]
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        problems.append(f"ID 重复：{', '.join(dup)}")

    decisions_text = open(os.path.join(ROOT, "DECISIONS.md"), encoding="utf-8").read()
    roadmap_text = open(os.path.join(ROOT, "ROADMAP.md"), encoding="utf-8").read()
    changelog_text = open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8").read()

    for f in feats:
        tag = f"{f['id']} {f['name']}"
        if not re.fullmatch(r"F-\d{3}", f["id"]):
            problems.append(f"{tag}：ID 必须形如 F-001")
        if f["status"] not in data["statuses"]:
            problems.append(f"{tag}：状态 {f['status']} 不在 {data['statuses']}")

        if f["status"] == "shipped":
            if not f.get("release"):
                problems.append(f"{tag}：已落地但没有 release 版本")
            if not (f.get("tests") or f.get("check")):
                problems.append(f"{tag}：已落地但没有测试也没有校验命令（无验收不能标 shipped）")

        if f["status"] in ("planned", "designed") and not (f.get("roadmap") or f.get("decision")):
            problems.append(f"{tag}：规划项必须挂 roadmap 或 decision")
        if f["status"] in ("rejected", "suspended") and not f.get("decision"):
            problems.append(f"{tag}：否决/挂起必须挂 decision")

        for l in (f.get("lands") or []):
            p = os.path.join(ROOT, l["path"])
            if not os.path.exists(p):
                problems.append(f"{tag}：落点文件不存在 {l['path']}")
                continue
            sym = l.get("symbol")
            if sym:
                with open(p, encoding="utf-8", errors="ignore") as fh:
                    if sym not in fh.read():
                        problems.append(f"{tag}：{l['path']} 里找不到符号「{sym}」")

        for t in (f.get("tests") or []):
            if not os.path.exists(os.path.join(ROOT, t)):
                problems.append(f"{tag}：测试文件不存在 {t}")
        for c in (f.get("check") or []):
            cmd = c.split("::")[0].strip()
            if not os.path.exists(os.path.join(ROOT, cmd)):
                problems.append(f"{tag}：校验脚本不存在 {cmd}")
        for d in (f.get("docs") or []):
            if not os.path.exists(os.path.join(ROOT, d)):
                problems.append(f"{tag}：文档不存在 {d}")
        if not f.get("docs"):
            problems.append(f"{tag}：没登记任何文档出处")

        dec = f.get("decision")
        if dec and not re.search(rf"## {re.escape(dec)}\b", decisions_text):
            problems.append(f"{tag}：DECISIONS.md 里没有 {dec}")
        rm = f.get("roadmap")
        if rm:
            in_roadmap = bool(re.search(rf"\| {re.escape(rm)} \|", roadmap_text))
            in_changelog = bool(re.search(rf"\b{re.escape(rm)}\b", changelog_text))
            if in_roadmap:
                pass  # 表里还留着（没做完，或刚落地还没清理）
            elif in_changelog:
                pass  # 按 ROADMAP 的规矩"做完就删"，但 CHANGELOG 留了痕 —— 这才是要的终态
            else:
                problems.append(
                    f"{tag}：ROADMAP.md 与 CHANGELOG.md 里都找不到 {rm}"
                    f"（落地项删表前必须先写 CHANGELOG，否则等于没发生过）")

    md_table = read_md_table()
    if md_table is None:
        problems.append("FEATURES.md 缺 AUTO-TABLE 标记")
    elif md_table != table.strip():
        problems.append("FEATURES.md 的表与 features.json 不一致（跑 --write-md）")

    counts = {k: 0 for k in data["statuses"]}
    for f in feats:
        counts[f["status"]] = counts.get(f["status"], 0) + 1

    print("=== 功能登记 ===")
    print("  " + " / ".join(f"{STATUS_CN[k]} {counts[k]}" for k in data["statuses"]))
    print(f"  合计 {len(feats)} 条")

    if problems:
        print("\n[失败]")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\n[通过] 登记与现实一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
