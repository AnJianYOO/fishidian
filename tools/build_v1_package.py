#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小鱼 v0.1.0 安装包构建器

包内形态 = 实际装出来的样子：内核 + 插件 + 皮肤 + QQ 桥 + 独立窗口 + 二维码服务。
装完从桌面双击就能开出一个单独的小鱼窗口，不碰工作 DSH。

用法：
    python -X utf8 tools/build_v0.1.0_package.py

为什么 node_modules 不带：桥的 node_modules 是 pnpm 的 junction 森林
（实测 1286 个 ReparsePoint），拷到别的机器全是死链。桥只依赖 ws 一个包，
装的时候 pnpm install 顺手就装了，比带一份假的更快也更对。
"""

import os
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOOLS = ROOT / "tools"
PACKDOCS = TOOLS / "packdocs"
REL = ROOT / "_release"
OUT = REL / "fishidian-v0.1.0"
PAYLOAD = OUT / "payload"

CORE_SRC = ROOT / "fishidian-core"
FISH_SRC = ROOT / "dsh-fishidian"
SKIN_SRC = ROOT / "dsh-client-ui-fatfish"
BRIDGE_SRC = ROOT / "dsh-qq-onebot-bridge"
WIN_SRC = ROOT / "fatfish-window"

BAK_PAT = re.compile(r".*\.bak.*$", re.IGNORECASE)
SKIP_SUFFIX = (".pyc", ".db", ".db-wal", ".db-shm", ".log")

# 各源各自的排除目录
CORE_SKIP_DIRS = {"tests", "test", "eval", "data", "__pycache__", ".git", ".vscode"}
FISH_SKIP_DIRS = {"test", "tests", "__pycache__", ".git", ".vscode", "node_modules"}
SKIN_SKIP_DIRS = {"test", "tests", "__pycache__", ".git", ".vscode", "node_modules"}
BRIDGE_SKIP_DIRS = {"test", "tests", "docs", "examples", "__pycache__", ".git", ".github", ".vscode", "node_modules"}
# 窗口模板里的 data\ 是空骨架，不能当"运行数据"排掉
WIN_SKIP_DIRS = {"__pycache__", ".git", ".vscode"}

warns = []


def reset():
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    PAYLOAD.mkdir(parents=True)


def cp(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(src), str(dst))


def cp_tree(src: Path, dst: Path, skip_dirs):
    if not src.exists():
        warns.append(f"源不存在，跳过：{src}")
        return 0, 0
    n_files = 0
    n_bytes = 0
    for root, dirs, files in os.walk(src):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        rel = Path(root).relative_to(src)
        tgt = dst / rel
        tgt.mkdir(parents=True, exist_ok=True)
        for f in files:
            if BAK_PAT.match(f):
                continue
            if f.endswith(SKIP_SUFFIX):
                continue
            s = Path(root) / f
            try:
                sz = s.stat().st_size
            except OSError:
                continue
            shutil.copy2(str(s), str(tgt / f))
            n_files += 1
            n_bytes += sz
    return n_files, n_bytes


def build_core():
    """内核：源码 + cli/daemon + README，不带测试、不带任何 .db"""
    dst = PAYLOAD / "fishidian-core"
    dst.mkdir(parents=True, exist_ok=True)
    files, size = cp_tree(CORE_SRC / "fishidian_core", dst / "fishidian_core", CORE_SKIP_DIRS)
    for name in ("cli.py", "daemon.py", "README.md"):
        p = CORE_SRC / name
        if p.exists():
            cp(p, dst / name)
    return files + 3, size


def build_plugin():
    """小鱼插件本体（D 盘为源；C 盘那份有一堆 .bak 和旧版本）"""
    dst = PAYLOAD / "dsh-fishidian"
    files, size = cp_tree(FISH_SRC, dst, FISH_SKIP_DIRS)
    return files, size


def build_skin():
    dst = PAYLOAD / "dsh-client-ui-fatfish"
    files, size = cp_tree(SKIN_SRC, dst, SKIN_SKIP_DIRS)
    return files, size


def build_bridge():
    """QQ 桥（第三方开源 MIT）。代码全带，node_modules 不带 —— 理由见文件头。"""
    dst = PAYLOAD / "dsh-qq-onebot-bridge"
    files, size = cp_tree(BRIDGE_SRC, dst, BRIDGE_SKIP_DIRS)
    return files, size


def build_window():
    """窗口模板：home-template 骨架 + cordis.patch.yml 占位符模板"""
    dst = PAYLOAD / "fatfish-window"
    files, size = cp_tree(WIN_SRC / "home-template", dst / "home-template", WIN_SKIP_DIRS)
    p = WIN_SRC / "cordis.patch.yml"
    if p.exists():
        cp(p, dst / "cordis.patch.yml")
        files += 1
        size += p.stat().st_size
    else:
        warns.append("fatfish-window\\cordis.patch.yml 不存在，安装包会装不出窗口")
    return files, size


def build_tools():
    """二维码服务"""
    dst = PAYLOAD / "tools"
    dst.mkdir(parents=True, exist_ok=True)
    n = 0
    size = 0
    p = TOOLS / "qq-qrcode-server.js"
    if p.exists():
        cp(p, dst / "qq-qrcode-server.js")
        n += 1
        size += p.stat().st_size
    else:
        warns.append("tools\\qq-qrcode-server.js 不存在，窗口里的「连 QQ」会拿不到码")
    return n, size


def build_scripts():
    """安装器 / 启动器 / NapCat 体检 / 装完验证，放包根（install.cmd 同级）"""
    n = 0
    size = 0
    for name in ("install_v0.1.0.ps1", "launch.ps1", "check_napcat.ps1", "verify_install.ps1"):
        p = TOOLS / name
        if p.exists():
            cp(p, OUT / name)
            n += 1
            size += p.stat().st_size
        else:
            warns.append(f"tools\\{name} 不存在")
    return n, size


def build_docs():
    n = 0
    size = 0
    for name in ("README.md", "START-HERE.md", "FOR-AI.md", "VERSION.txt", "QQ桥怎么用.md"):
        p = PACKDOCS / name
        if p.exists():
            cp(p, OUT / name)
            n += 1
            size += p.stat().st_size
        else:
            warns.append(f"packdocs\\{name} 不存在，包里会缺这份文档")
    return n, size


def build_install_cmd():
    """双击入口。纯 ASCII —— chcp 之前出现中文必然乱码。"""
    body = (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "setlocal\r\n"
        "cd /d \"%~dp0\"\r\n"
        "echo.\r\n"
        "echo  ==========================================\r\n"
        "echo    Fishidian v0.1.0 installer\r\n"
        "echo  ==========================================\r\n"
        "echo.\r\n"
        "echo  Read START-HERE.md first if you are a person.\r\n"
        "echo  Read FOR-AI.md first if you are an AI assistant.\r\n"
        "echo.\r\n"
        "echo  Press Ctrl+C to cancel, or press Enter to start.\r\n"
        "pause >nul\r\n"
        "powershell.exe -NoProfile -ExecutionPolicy Bypass -File \"%~dp0install_v0.1.0.ps1\"\r\n"
        "if errorlevel 1 (\r\n"
        "  echo.\r\n"
        "  echo  Install failed. Read the message above, then see START-HERE.md troubleshooting.\r\n"
        "  pause\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        "echo.\r\n"
        "echo  Done. A shortcut named BigFish was created on your Desktop.\r\n"
        "pause\r\n"
    )
    p = OUT / "install.cmd"
    # cmd 文件必须无 BOM，否则第一行 @echo off 会被当成命令的一部分
    p.write_bytes(body.replace("\r\n", "\r\n").encode("ascii", "strict"))
    return 1, p.stat().st_size


def make_zip(stamp: str):
    zpath = REL / f"fishidian-v0.1.0-{stamp}.zip"
    if zpath.exists():
        zpath.unlink()
    with zipfile.ZipFile(str(zpath), "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for root, dirs, files in os.walk(OUT):
            dirs[:] = [d for d in dirs if d != "__pycache__"]
            rel_root = Path(root).relative_to(OUT)
            # 空目录也写一条，否则解压后 home-template 的 backup\daily 这些骨架会消失
            if not files and not dirs and str(rel_root) != ".":
                z.write(str(Path(root)), str(rel_root).replace("\\", "/") + "/")
            for f in files:
                full = Path(root) / f
                rel = full.relative_to(OUT)
                # zip 内路径一律正斜杠，Windows 资源管理器才认
                z.write(str(full), str(rel).replace("\\", "/"))
    return zpath


def main():
    stamp = datetime.now().strftime("%Y%m%d")
    print("")
    print("=" * 52)
    print("  小鱼 v0.1.0 构建")
    print("=" * 52)
    print(f"  输出目录 : {OUT}")

    reset()

    rows = []
    rows.append(("fishidian-core", *build_core()))
    rows.append(("dsh-fishidian", *build_plugin()))
    rows.append(("dsh-client-ui-fatfish", *build_skin()))
    rows.append(("dsh-qq-onebot-bridge", *build_bridge()))
    rows.append(("fatfish-window", *build_window()))
    rows.append(("tools/qq-qrcode-server.js", *build_tools()))
    rows.append(("安装脚本", *build_scripts()))
    rows.append(("文档", *build_docs()))
    rows.append(("install.cmd", *build_install_cmd()))

    print("")
    print("  内容                      文件数      体积")
    print("  " + "-" * 48)
    total_files = 0
    total_bytes = 0
    for name, n, b in rows:
        kb = b / 1024.0
        print(f"  {name:<24} {n:>6}   {kb:>9.1f} KB")
        total_files += n
        total_bytes += b

    print("  " + "-" * 48)
    print(f"  {'合计':<24} {total_files:>6}   {total_bytes/1024.0:>9.1f} KB")

    zp = make_zip(stamp)
    zkb = zp.stat().st_size / 1024.0

    # 根层清单，便于核对"包里到底有几份文档"
    print("")
    print("  包根文件：")
    for p in sorted(OUT.iterdir()):
        if p.is_file():
            print(f"    {p.name:<24} {p.stat().st_size:>8} B")
    print("")
    print(f"  zip : {zp}")
    print(f"        {zkb:.1f} KB")

    if warns:
        print("")
        print("  警告：")
        for w in warns:
            print(f"    - {w}")

    print("")
    print("  下一步自检：")
    print("    powershell -File tools\\verify_v0.1.0_package.ps1")
    print("")
    return 0


if __name__ == "__main__":
    sys.exit(main())
