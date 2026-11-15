# -*- coding: utf-8 -*-
"""文档校验：让"文档和代码不一致"变成一次可见的失败。

用法（在项目根目录下跑）：
    python -X utf8 tools/docs_check.py
    python -X utf8 tools/docs_check.py --root "<项目根>"

检查三件事：
  1. SPEC / PLAN / DECISION 每份顶部都有 "状态：" 行
  2. 00_INDEX 表格里提到的文件都真实存在
  3. 文档里的相对链接没有断的

退出码 0 = 全绿，1 = 有阻断项。
"""
import os
import re
import sys

DEFAULT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NEED_HEADER = ("10_SPEC", "20_PLAN", "30_DECISION")


def parse_args(argv):
    root = DEFAULT_ROOT
    for i, a in enumerate(argv):
        if a == "--root" and i + 1 < len(argv):
            root = argv[i + 1]
    return root


def read_text(path):
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def walk_md(docs_dir):
    """遍历文档，跳过 40_ARCHIVE：归档是历史快照，链接按当年的目录写，
    不该要求它指向现在的文件。"""
    for base, dirs, files in os.walk(docs_dir):
        dirs[:] = [d for d in dirs if d != "40_ARCHIVE"]
        for name in files:
            if name.lower().endswith(".md"):
                yield os.path.join(base, name)


def check_headers(docs_dir):
    """SPEC/PLAN/DECISION 的每份文档顶部十行内要有 '状态：'。"""
    problems = []
    for path in walk_md(docs_dir):
        rel = os.path.relpath(path, docs_dir)
        top_level = rel.split(os.sep)[0]
        if top_level not in NEED_HEADER:
            continue
        head = "\n".join(read_text(path).splitlines()[:10])
        if "状态：" not in head:
            problems.append("缺状态头：{}".format(rel))
    return problems


def check_index(docs_dir):
    """INDEX 里用反引号标出来的 *.md / *.txt 必须存在。"""
    index = os.path.join(docs_dir, "00_INDEX.md")
    if not os.path.exists(index):
        return ["找不到 00_INDEX.md"]
    problems = []
    text = read_text(index)
    for m in re.finditer(r"`([^`]*?\.(?:md|txt))`", text):
        name = m.group(1).strip()
        if "/" in name or "\\" in name:
            continue
        found = False
        for base, _dirs, files in os.walk(docs_dir):
            if name in files:
                found = True
                break
        if not found:
            problems.append("INDEX 提到但不存在：{}".format(name))
    return problems


def check_links(docs_dir):
    """markdown 相对链接目标必须存在。"""
    problems = []
    for path in walk_md(docs_dir):
        rel = os.path.relpath(path, docs_dir)
        text = read_text(path)
        for m in re.finditer(r"\[[^\]]*\]\(([^)]+)\)", text):
            target = m.group(1).strip()
            if not target or target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            target = target.split("#")[0].strip()
            if not target:
                continue
            resolved = os.path.normpath(
                os.path.join(os.path.dirname(path), target.replace("\\", "/"))
            )
            if not os.path.exists(resolved):
                problems.append("断链：{} → {}".format(rel, target))
    return problems


def main():
    root = parse_args(sys.argv[1:])
    docs_dir = os.path.join(root, "docs")
    if not os.path.isdir(docs_dir):
        print("[FAIL] 找不到 docs 目录：{}".format(docs_dir))
        print("       docs 目录不存在。传参给错了？脚本第一个参数是项目根目录。")
        return 1

    groups = [
        ("状态头检查", check_headers(docs_dir)),
        ("INDEX 完整性", check_index(docs_dir)),
        ("链接断链", check_links(docs_dir)),
    ]

    total = 0
    for title, problems in groups:
        if problems:
            print("[FAIL] {}：{} 项".format(title, len(problems)))
            for p in problems[:20]:
                print("       - {}".format(p))
            if len(problems) > 20:
                print("       ... 还有 {} 项".format(len(problems) - 20))
            total += len(problems)
        else:
            print("[OK]   {}".format(title))

    print()
    if total:
        print("结论：{} 项待修。文档和代码已经不一致了。".format(total))
        return 1
    print("结论：全绿。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
