# -*- coding: utf-8 -*-
"""版本对账：四个版本源 + 文档页脚 + 已安装的副本，不一致就非零退出。

用法：python -X utf8 tools\version_check.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_doc_version():
    """文档版本也只有一处真源：VERSION.md 的「当前版本」表（不再写死在脚本里）。"""
    p = os.path.join(ROOT, "VERSION.md")
    with open(p, encoding="utf-8") as fh:
        m = re.search(r"\| 文档 doc \| \*\*(v[\d.]+)\*\*", fh.read())
    return m.group(1) if m else "v0.0"


def read_core_version():
    p = os.path.join(ROOT, "fishidian-core", "fishidian_core", "__init__.py")
    with open(p, encoding="utf-8") as fh:
        m = re.search(r'__version__\s*=\s*"([^"]+)"', fh.read())
    return m.group(1) if m else None


def read_pkg_version(rel):
    p = os.path.join(ROOT, rel)
    with open(p, encoding="utf-8") as fh:
        return json.load(fh).get("version")


FOOT_RE = re.compile(r"^\*文档 v[\d.]+\s*｜")


def tail_foot(text):
    """取文档末尾的页脚行——只看最后 3 个非空行，正文里出现的版本串不算数。"""
    lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
    for ln in reversed(lines[-3:]):
        if FOOT_RE.match(ln):
            return ln
    return None


def read_table():
    """从 VERSION.md 的「当前版本」表里取三个程序版本。"""
    p = os.path.join(ROOT, "VERSION.md")
    with open(p, encoding="utf-8") as fh:
        text = fh.read()
    out = {}
    for key, pattern in (
        ("core", r"\| 内核 core \| \*\*(.+?)\*\*"),
        ("plugin", r"\| 插件 plugin \| \*\*(.+?)\*\*"),
        ("bridge", r"\| 桥 bridge \| \*\*(.+?)\*\*"),
    ):
        m = re.search(pattern, text)
        out[key] = m.group(1).strip() if m else None
    return out


def main():
    problems = []
    DOC_VERSION = read_doc_version()

    core = read_core_version()
    plugin = read_pkg_version(os.path.join("dsh-fishidian", "package.json"))
    bridge = read_pkg_version(os.path.join("dsh-qq-onebot-bridge", "package.json"))
    table = read_table()

    print("=== 版本源 ===")
    print(f"  core   : 代码 {core}")
    print(f"  plugin : 代码 {plugin}")
    print(f"  bridge : 代码 {bridge}")
    print(f"  文档   : {DOC_VERSION}")

    print("\n=== VERSION.md 登记 vs 代码 ===")
    for key, actual in (("core", core), ("plugin", plugin), ("bridge", bridge)):
        reg = table.get(key)
        ok = reg == actual
        print(f"  {key:<7}: 登记 {reg} / 代码 {actual}  {'OK' if ok else '不一致'}")
        if not ok:
            problems.append(f"VERSION.md 登记的 {key} 版本（{reg}）与代码（{actual}）不一致")

    # 文档页脚：只认文档末尾那一行，不在全文里找版本号。
    # （2026-11-06 修过的坑：此前用"全文包含 文档 vX"判定，正文一提版本号就算通过，
    #  于是 AGENTS.md 正文写着 v0.6、页脚却停在 v0.5，脚本还报"全部已标"。）
    print("\n=== 文档页脚 ===")
    want = {"文档": DOC_VERSION, "core": core, "plugin": plugin, "bridge": bridge}
    bad = []
    checked = 0
    for name in sorted(os.listdir(ROOT)):
        if not name.lower().endswith(".md") or name.startswith("ARCHIVE_"):
            continue
        with open(os.path.join(ROOT, name), encoding="utf-8") as fh:
            text = fh.read()
        checked += 1
        foot = tail_foot(text)
        if not foot:
            bad.append(f"{name}：末尾没有页脚行")
            continue
        for k, v in want.items():
            if f"{k} {v}" not in foot:
                bad.append(f"{name}：页脚里 {k} 应为 {v}（实际：{foot}）")
    if bad:
        print(f"  {len(bad)} 处不符（共查 {checked} 份）：")
        for b in bad:
            print(f"   - {b}")
        problems.extend(bad)
    else:
        print(f"  全部 {checked} 份文档末尾页脚一致")

    # 已安装的副本
    live_pkg = os.path.expanduser(
        r"~\.dsh\profiles\desktop\node_modules\dsh-fishidian\package.json")
    print("\n=== 已安装的运行时副本 ===")
    if os.path.exists(live_pkg):
        try:
            with open(live_pkg, encoding="utf-8") as fh:
                live = json.load(fh).get("version")
            print(f"  已装 plugin: {live}（项目 {plugin}）")
            if live != plugin:
                print("  ⚠ 已装副本版本落后：需要同步 lib/index.js 与 package.json 后重启 DSH")
        except Exception as e:
            print(f"  ⚠ 读不到：{e}")
    else:
        print("  未找到已装副本（可能没装到 desktop profile）")

    if problems:
        print("\n[失败]")
        for p in problems:
            print(f"  - {p}")
        return 1
    print("\n[通过] 版本源一致")
    return 0


if __name__ == "__main__":
    sys.exit(main())
