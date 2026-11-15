# -*- coding: utf-8 -*-
"""fishidian_core.store —— SQLite 持久化（WAL）。表：memories / events / fuse_log / kv"""
from __future__ import annotations

import json
import os
import sqlite3
import time

from . import config as C


def _now() -> float:
    return time.time()


SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
  id INTEGER PRIMARY KEY,
  ns TEXT NOT NULL,
  person_id TEXT,
  text TEXT NOT NULL,
  importance REAL, arousal REAL, valence REAL,
  cluster TEXT,
  tier TEXT,
  r REAL,
  hits INTEGER DEFAULT 0,
  born_at REAL, last_at REAL, last_hit_at REAL,
  status TEXT DEFAULT 'active',
  source TEXT DEFAULT 'user',
  visibility TEXT DEFAULT 'private',
  created_at REAL,
  wuxing_tag TEXT,
  superseded_by INTEGER,
  source_quote TEXT
);
CREATE INDEX IF NOT EXISTS idx_mem_ns ON memories(ns, status, tier);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY,
  ns TEXT, type TEXT, payload TEXT, at REAL
);

CREATE TABLE IF NOT EXISTS fuse_log (
  id INTEGER PRIMARY KEY,
  ns TEXT, at REAL, neg_strength REAL, action TEXT
);

CREATE TABLE IF NOT EXISTS kv (key TEXT PRIMARY KEY, value TEXT);
"""


class Store:
    """按 ns（命名空间：qq:dm:<qq> / qq:group:<gid>）隔离的 SQLite 存储。"""

    def __init__(self, path: str = ""):
        if not path:
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "fishidian.db")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        # check_same_thread=False：插件是多线程/多进程各起一次进程，单进程内也允许跨线程。
        # isolation_level=None：事务由我们自己管（见 _write 的 BEGIN IMMEDIATE），
        # 避免 sqlite3 隐式 DEFERRED 事务在并发下"读锁升级写锁"死等。
        self._db = sqlite3.connect(path, check_same_thread=False,
                                   timeout=C.DB_BUSY_TIMEOUT_MS / 1000.0,
                                   isolation_level=None)
        self._db.row_factory = sqlite3.Row
        # R36：QQ 桥 + 插件 + 巡检可能同时写同一个 db。WAL 允许并发读、单写；
        # busy_timeout 让写请求排队等一下，而不是立刻把 "database is locked" 冒到聊天上。
        self._retry(lambda: self._db.execute("PRAGMA journal_mode=WAL"))
        self._retry(lambda: self._db.execute(
            f"PRAGMA busy_timeout={int(C.DB_BUSY_TIMEOUT_MS)}"))
        self._retry(lambda: self._db.executescript(SCHEMA))
        # 老库补列（新库 SCHEMA 已含，ALTER 会报 duplicate column → 忽略）
        for col in ("wuxing_tag TEXT",
                    # 021/022：写入当轮的环境快照（短键 JSON，约 100 字节）。
                    # 不进 prompt（token 为 0），只在召回命中时带一句「那天初雪夜」。
                    # 老库自动补列，不回填历史（与 D-003 同一条规矩）。
                    "env_json TEXT",
                    # R37：被谁取代（指回新条 id）。null=没被取代过。
                    "superseded_by INTEGER",
                    # R37：原话出处。当前 text 本身就是原句，这一列是给将来"摘要化"留的接口，
                    # 现在写入时一并存原文（写入存真值，注入时才脱敏 —— 与 R30 同一条原则）。
                    "source_quote TEXT"):
            try:
                self._retry(lambda c=col: self._db.execute(
                    f"ALTER TABLE memories ADD COLUMN {c}"))
            except sqlite3.OperationalError:
                pass

    # ---------- 写重试（R36） ----------
    def _retry(self, fn, tries=None):
        """遇锁退避重试；其他 OperationalError 直接抛（别把真 bug 藏起来）。"""
        tries = C.DB_WRITE_RETRY if tries is None else tries
        for i in range(tries + 1):
            try:
                return fn()
            except sqlite3.OperationalError as e:
                msg = str(e).lower()
                if "locked" not in msg and "busy" not in msg:
                    raise
                if i >= tries:
                    raise
                time.sleep(0.05 * (2 ** i))  # 50 / 100 / 200 ms

    def _write(self, sql: str, params=(), tries=None):
        """单条写：BEGIN IMMEDIATE 抢写锁 → 执行 → COMMIT，遇锁整段重试。"""
        def go():
            self._db.execute("BEGIN IMMEDIATE")
            try:
                cur = self._db.execute(sql, params)
                self._db.execute("COMMIT")
                return cur
            except BaseException:
                try:
                    self._db.execute("ROLLBACK")
                except sqlite3.OperationalError:
                    pass
                raise

        return self._retry(go, tries)

    # ---------- memories ----------
    def add_memory(self, ns, text, imp, aro, val, cluster, tier, r,
                   source="user", visibility="private", person_id=None, at=None,
                   status="active", wuxing_tag=None, source_quote=None,
                   env_json=None):
        """status 默认 active；传 'archived' 可直接落成沉底（血海满且新记忆太弱时用）。
        wuxing_tag：写入当轮的五志 tag（可空）。只在写入时绑定，不回填历史（D-003）。
        source_quote：R37 的原话出处。现在与 text 相同（我们不做摘要改写），
                      存下来是为了将来 text 被压缩时"用时还能回看原话"。"""
        at = at if at is not None else _now()
        cur = self._write(
            "INSERT INTO memories(ns,person_id,text,importance,arousal,valence,cluster,tier,r,hits,"
            "born_at,last_at,last_hit_at,status,source,visibility,created_at,wuxing_tag,source_quote,"
            "env_json) "
            "VALUES(?,?,?,?,?,?,?,?,?,0,?,?,NULL,?,?,?,?,?,?,?)",
            (ns, person_id, text, imp, aro, val, cluster, tier, r, at, at,
             status, source, visibility, at, wuxing_tag,
             source_quote if source_quote is not None else text, env_json))
        return cur.lastrowid

    def get_memory(self, mid):
        row = self._db.execute("SELECT * FROM memories WHERE id=?", (mid,)).fetchone()
        return dict(row) if row else None

    def update_memory(self, mid, **fields):
        keys = ",".join(f"{k}=?" for k in fields)
        vals = list(fields.values()) + [mid]
        self._write(f"UPDATE memories SET {keys} WHERE id=?", vals)

    def query_active(self, ns, limit=5000):
        rows = self._db.execute(
            "SELECT * FROM memories WHERE ns=? AND status='active' ORDER BY r DESC LIMIT ?",
            (ns, limit)).fetchall()
        return [dict(r) for r in rows]

    def query_all(self, ns, limit=5000):
        rows = self._db.execute(
            "SELECT * FROM memories WHERE ns=? ORDER BY r DESC LIMIT ?", (ns, limit)).fetchall()
        return [dict(r) for r in rows]

    def query_archived(self, ns, limit=20000):
        """沉底区（status='archived'）。只读：供分级召回用，不 touch、不改 status。

        limit 不能沿用 query_all 的 5000：沉底区只增不减，实际跑一年就会越过去。
        实测 8000 条库里沉底 7801 条，limit=5000 时 2801 条永远进不了候选池，
        而且 ORDER BY r DESC 在 r 只有少数几档时同档内顺序不确定——丢哪批不可预测。
        20000 条约 300ms 全扫，仍在可接受范围；超过这个量级要靠 v0.2 的表内预筛。
        """
        rows = self._db.execute(
            "SELECT * FROM memories WHERE ns=? AND status='archived' ORDER BY r DESC LIMIT ?",
            (ns, limit)).fetchall()
        return [dict(r) for r in rows]

    def forget(self, mid):
        self._write("UPDATE memories SET status='archived' WHERE id=?", (mid,))

    def count_active(self, ns):
        row = self._db.execute(
            "SELECT COUNT(*) c FROM memories WHERE ns=? AND status='active'", (ns,)).fetchone()
        return row["c"]

    def count_new_since(self, ns, since_ts):
        """R35 日上限用：统计某时间点之后「新建」的记忆条数（按 created_at，不看 tiers）。"""
        row = self._db.execute(
            "SELECT COUNT(*) c FROM memories WHERE ns=? AND created_at>=?", (ns, since_ts)).fetchone()
        return row["c"]

    def count_events_since(self, ns, etype, since_ts):
        """R37 每日取代上限用：统计某类审计事件在时间窗内发生了多少次。
        用事件而不是翻 memories：取代发生的次数本身就是审计事实，
        而且被取代的条以后可能被归档，靠状态反推次数并不可靠。"""
        row = self._db.execute(
            "SELECT COUNT(*) c FROM events WHERE ns=? AND type=? AND at>=?",
            (ns, etype, since_ts)).fetchone()
        return row["c"]

    def supersede_at_map(self, ns):
        """old_id → **取代真正发生的时刻**（秒）。

        为什么不能拿旧条的 born_at 当"这件事发生的时间"：一条三个月前写的记忆
        今天才被新说法取代，它的 born_at 是三个月前——按 born_at 过滤窗口，
        今天这次取代会被直接漏掉，观测工具就成了摆设。事件里的 at 才是事实时间。
        v0.21 之前没有这类事件，那些老数据在调用方退化成 born_at。
        """
        out = {}
        rows = self._db.execute(
            "SELECT payload, at FROM events WHERE ns=? AND type='write_supersede'", (ns,)).fetchall()
        for r in rows:
            try:
                p = json.loads(r["payload"] or "{}")
                oid = p.get("old_id")
                if oid is not None:
                    out[int(oid)] = float(r["at"] or 0)
            except (ValueError, TypeError):
                continue
        return out

    def recent_texts(self, ns, since_ts, limit=200):
        """R35 写入去重 / R37 冲突裁决用：回溯窗口内的记忆正文（新→旧）。
        带 status：裁决时只能拿 active 的条当"旧说法"，已 superseded 的要跳过，
        否则"3点→4点→又改回3点"会一直去替换那条早就作废的。"""
        rows = self._db.execute(
            "SELECT id,text,created_at,status,superseded_by FROM memories WHERE ns=? AND created_at>=? "
            "ORDER BY created_at DESC LIMIT ?", (ns, since_ts, limit)).fetchall()
        return [dict(r) for r in rows]

    # ---------- 审计 / 熔断 ----------
    def log_event(self, ns, etype, payload=None, at=None):
        at = at if at is not None else _now()
        self._write("INSERT INTO events(ns,type,payload,at) VALUES(?,?,?,?)",
                    (ns, etype, json.dumps(payload, ensure_ascii=False), at))

    def log_fuse(self, ns, neg_strength, action, at=None):
        at = at if at is not None else _now()
        self._write("INSERT INTO fuse_log(ns,at,neg_strength,action) VALUES(?,?,?,?)",
                    (ns, at, neg_strength, action))

    def recent_fuse(self, ns, limit=20):
        rows = self._db.execute(
            "SELECT * FROM fuse_log WHERE ns=? ORDER BY at DESC LIMIT ?", (ns, limit)).fetchall()
        return [dict(r) for r in rows]

    def recent_events(self, ns, etype=None, limit=20, since=None):
        """最近的事件（新→旧）。payload 原地保留成字符串，解析交给调用方。

        011 的偏移记录、promises 都落在 events 表（不建新表），
        简报的"自觉"段要读它，承诺到期检查也要读它，所以补这个出口。
        """
        if etype and since is not None:
            rows = self._db.execute(
                "SELECT * FROM events WHERE ns=? AND type=? AND at>=? "
                "ORDER BY at DESC LIMIT ?", (ns, etype, since, limit)).fetchall()
        elif etype:
            rows = self._db.execute(
                "SELECT * FROM events WHERE ns=? AND type=? ORDER BY at DESC LIMIT ?",
                (ns, etype, limit)).fetchall()
        elif since is not None:
            rows = self._db.execute(
                "SELECT * FROM events WHERE ns=? AND at>=? ORDER BY at DESC LIMIT ?",
                (ns, since, limit)).fetchall()
        else:
            rows = self._db.execute(
                "SELECT * FROM events WHERE ns=? ORDER BY at DESC LIMIT ?",
                (ns, limit)).fetchall()
        return [dict(r) for r in rows]

    # ---------- kv ----------
    def get_kv(self, key, default=None):
        row = self._db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_kv(self, key, value):
        self._write(
            "INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value))

    def close(self):
        self._db.commit()
        self._db.close()
