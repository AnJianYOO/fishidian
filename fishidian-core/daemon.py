# -*- coding: utf-8 -*-
"""fishidian_daemon —— 独立心跳进程（v0.1.0）

**为什么需要它**：插件里那四个定时器（sweep / vault / backup / proactive）全长在
DSH 的 `index.js` 里，靠 DSH 的 ctx 活着。DSH 窗口一关，tick 也停 —— 那"关机三天
她还在过日子"就是假的。所以 v0.1.0 的门槛不在五行，在于有这么一个不依赖 DSH 的进程。

**它做什么**（与 index.js 对齐，但只做 v0.1.0 需要的）：
    tick      10 分钟   心跳：结算缺口 + 采环境 + 注入
    sweep     10 分钟   离线巡检（降温/迁移/归档）
    backup    24 小时   整库快照（sqlite backup API，不能用 copyfile）
    proactive 不做      主动发消息要 DSH 的 webhook；v0.1.0 只让她"状态对"，不主动发

**怎么起**：
    pythonw.exe daemon.py --ns dsh:desktop --db "<库路径>"
    pythonw.exe daemon.py --ns dsh:desktop --db "<库路径>" --once     # 跑一轮就退（测试用）

pythonw 没有控制台窗口，日志只落文件。

**开机自启**：不在这里做。用任务计划程序注册（见 docs 的安装说明），
`-WindowStyle Hidden`，这样用户看不见一个黑框。
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sqlite3
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from fishidian_core import config as C
from fishidian_core.governor import Governor
from fishidian_core.store import Store

_STOP = {"flag": False}


def _on_signal(signum, frame):
    _STOP["flag"] = True


def _log(path, msg):
    """日志只落文件。pythonw 没有 stdout，print 会静默失败。"""
    line = time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg
    if path:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass
        return
    try:
        print(line)
    except Exception:
        pass


def _backup(db_path, out_dir, keep=7):
    """整库快照。必须走 sqlite backup API —— copyfile 会漏掉 WAL 里的写入且不报错。"""
    try:
        os.makedirs(out_dir, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        dst = os.path.join(out_dir, "dfy-%s.db" % stamp)
        src = sqlite3.connect(db_path)
        d = sqlite3.connect(dst)
        try:
            src.backup(d)
        finally:
            d.close()
            src.close()
        files = sorted(f for f in os.listdir(out_dir) if f.endswith(".db"))
        for f in files[:-keep]:
            try:
                os.remove(os.path.join(out_dir, f))
            except Exception:
                pass
        return dst
    except Exception:
        return None


def _checkpoint(store, log_path):
    """WAL 定期落盘，避免 -wal 无限涨。失败只是日志，不影响主循环。"""
    try:
        store._db.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except Exception as e:
        _log(log_path, "checkpoint skip: %s" % str(e)[:80])


def run(ns, db, log_path, backup_dir, once=False, interval=None):
    interval = C.TICK_INTERVAL_S if interval is None else interval
    store = Store(db)
    g = Governor(ns, store=store)
    _log(log_path, "daemon up | ns=%s | db=%s | tick=%ss" % (ns, db, interval))

    now0 = time.time()
    nxt_tick = now0
    nxt_sweep = now0 + interval
    nxt_backup = now0 + 86400

    while not _STOP["flag"]:
        now = time.time()

        if now >= nxt_tick:
            try:
                rep = g.tick(now=now)
                # 只在真有内容时落日志，否则一天 144 行全是噪音
                if rep.get("gap") or rep.get("events") or rep.get("memory") or rep.get("err"):
                    _log(log_path, "tick " + json.dumps(rep, ensure_ascii=False))
            except Exception:
                _log(log_path, "tick FAIL\n" + traceback.format_exc()[-500:])
            nxt_tick = now + interval

        if now >= nxt_sweep:
            try:
                r = g.sweep()
                _log(log_path, "sweep " + json.dumps(r, ensure_ascii=False)[:220])
            except Exception:
                _log(log_path, "sweep FAIL\n" + traceback.format_exc()[-400:])
            _checkpoint(store, log_path)
            nxt_sweep = now + interval

        if now >= nxt_backup:
            p = _backup(db, backup_dir)
            _log(log_path, "backup " + ("ok " + p if p else "FAIL"))
            nxt_backup = now + 86400

        if once:
            break
        # 1 秒粒度：睡 600 秒会因为进程调度漂移，越跑越偏
        time.sleep(1.0)

    _log(log_path, "daemon down")
    try:
        store.close()
    except Exception:
        pass
    return 0


def _acquire_lock(path):
    """常驻单实例：同一个库只允许一个心跳在跑。

    重装不会杀旧进程时（用户手动双击、开机自启和装完的常驻撞上），两个 daemon 会同时
    tick 同一个库：tick/衰减/备份都双计，日志还互相覆盖。这里用文件排他锁挡住第二个。
    拿不到锁返回 None，调用方记日志后退出，不抛异常（不能把安装器搞成堆栈报错）。
    """
    try:
        fh = open(path, "a+")
    except OSError:
        return None
    try:
        import msvcrt
        msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
    except ImportError:
        pass                      # 非 Windows：没有 msvcrt，退化为不做互斥
    except OSError:
        fh.close()
        return None
    return fh


def main():
    ap = argparse.ArgumentParser(description="fishidian 独立心跳进程")
    ap.add_argument("--ns", default="dsh:desktop")
    ap.add_argument("--db", required=True)
    ap.add_argument("--log", default="")
    ap.add_argument("--backup-dir", default="")
    ap.add_argument("--interval", type=int, default=0)
    ap.add_argument("--once", action="store_true", help="跑一轮就退出（测试用）")
    a = ap.parse_args()

    log_path = a.log
    if not log_path:
        log_path = os.path.join(os.path.dirname(os.path.abspath(a.db)), "daemon.log")
    backup_dir = a.backup_dir or os.path.join(os.path.dirname(os.path.abspath(a.db)), "_backup")

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _on_signal)
        except Exception:
            pass

    # 只给常驻模式上锁：安装器 [5/6] 的 --once 必须能在常驻进程活着时跑完，
    # 否则重装会被自己挡住，报"首轮心跳没跑起来"。
    lock_fh = None
    if not a.once:
        lock_fh = _acquire_lock(os.path.abspath(a.db) + ".lock")
        if lock_fh is None:
            _log(log_path, "daemon skip | 已有心跳持有 %s.lock，本进程退出（exit 3）"
                          % os.path.basename(a.db))
            return 3

    try:
        return run(a.ns, a.db, log_path, backup_dir,
                   once=a.once, interval=(a.interval or None))
    finally:
        try:
            if lock_fh is not None:
                lock_fh.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
