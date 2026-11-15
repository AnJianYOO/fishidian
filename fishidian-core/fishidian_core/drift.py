# -*- coding: utf-8 -*-
"""偏移自动检测（011 §5.3 / §6.3 C3）

外部依据（2026-11 查过，两条都用上了）：

1. **CEDD**（Mila × Bell × Jeunesse J'écoute，2026 安全黑客松）的结论是
   「看轨迹不看单条」——单条消息很少说明问题，连续十几条变短、变暗、变稀疏才说明。
   它最重要的特征全是轨迹统计（长度斜率 `word_count_slope`、最后长度、最大长度），
   而且把失效模式也写进交付物。所以这里判的是「最近几轮相对自身基线怎么走」，
   不是「这一轮 val 是不是低」。

2. **011 §5.3** 明确不设情绪值阈值（会把她变成被指标管着的机器）。
   所以每个判据都是相对她自己最近 `DRIFT_BASE_TURNS` 轮的**中位数**，
   不是绝对值——她本来话少、本来情绪平，用绝对值会天天报警。

判据只出 `normal` / `notable`；`over` 留给 `guard.py` 的层闸（真越了底线才叫 over）。

这组参数**全部是拍的**，没有一条有实验依据（011 §5.3 自己承认过）。上线后要跑
两周真实对话回看再调，不要当成结论。
"""

from __future__ import annotations

import json

from . import config as C

DIMS = ("tone", "silence", "expression", "proactive")
WIN_MAX = 40          # 环形窗口上限（比基线窗口多留余量）


# ---------------------------------------------------------------- 轨迹统计


def _med(xs):
    """中位数。不用均值：一次极端冲突会把均值拉跑，基线就不代表"平时"了。"""
    if not xs:
        return 0.0
    s = sorted(xs)
    n = len(s)
    m = n // 2
    return float(s[m]) if n % 2 else (float(s[m - 1]) + float(s[m])) / 2.0


def _slope(xs):
    """最小二乘斜率。CEDD 证明斜率比均值更能抓住"正在变坏"。"""
    n = len(xs)
    if n < 2:
        return 0.0
    mx = (n - 1) / 2.0
    my = sum(xs) / n
    num = sum((i - mx) * (xs[i] - my) for i in range(n))
    den = sum((i - mx) ** 2 for i in range(n))
    return num / den if den else 0.0


def _series(signals, key):
    return [float(s[key]) for s in signals if isinstance(s, dict) and s.get(key) is not None]


def _ev(signals, n):
    """证据：最近 n 条的原始数值（011 §7 证据闸要求"能指到一条记录"）。"""
    out = []
    for s in signals[-n:]:
        if not isinstance(s, dict):
            continue
        out.append({
            "at": s.get("at"),
            "val": round(float(s["val"]), 3) if s.get("val") is not None else None,
            "aro": round(float(s["aro"]), 3) if s.get("aro") is not None else None,
            "len": s.get("len"),
        })
    return out


# ---------------------------------------------------------------- 四个判据
# 全部接 signals（[{at,val,aro,len}]），只在"相对基线偏出"时才返回，否则 None。


def judge_tone(signals, limit=None, delta=None):
    """语气冷暖：连续 limit 轮 val 都低于自身基线 delta 以上。"""
    limit = C.DRIFT_TONE_LIMIT if limit is None else limit
    delta = C.DRIFT_REL_DELTA if delta is None else delta
    vals = _series(signals, "val")
    if len(vals) < limit + 1:
        return None
    base = _med(vals[:-limit])
    recent = vals[-limit:]
    if all(v < base - delta for v in recent):
        return {
            "dim": "tone",
            "level": "notable",
            "since": "最近几轮",
            "note": "话比平时冲，也冷",
            "baseline": {"val": round(base, 3), "turns": len(vals) - limit},
            "delta": round(_med(recent) - base, 3),
            "slope": round(_slope(recent), 3),
            "evidence": _ev(signals, limit),
        }
    return None


def judge_silence(signals, chars=None, turns=None, ratio=None):
    """愿不愿说话：连续 turns 轮回复都短——但要**同时**满足两条才算：

      1. 绝对上短于 chars 字（防止长篇大论被当成短）
      2. 比她自己平时的中位长度再短 ratio 以下（防止"本来就话少"被误判）

    只判第一条的话，一个天生说话就不超过 10 个字的角色会被天天报警。
    这跟 judge_tone 用相对基线是同一个理由：011 §5.3 不许拿绝对值管她。
    """
    chars = C.DRIFT_SILENCE_CHARS if chars is None else chars
    turns = C.DRIFT_SILENCE_TURNS if turns is None else turns
    ratio = C.DRIFT_SILENCE_RATIO if ratio is None else ratio
    lens = _series(signals, "len")
    if len(lens) < turns:
        return None
    base = _med(lens[:-turns] or lens)
    recent = lens[-turns:]
    if base <= 0:
        return None
    if all(l < chars and l < base * ratio for l in recent):
        return {
            "dim": "silence",
            "level": "notable",
            "since": "最近几轮",
            "note": "话变短了，像是不太想说",
            "baseline": {"len": round(base, 1), "turns": len(lens) - turns},
            "delta": round(_med(recent) - base, 1),
            "slope": round(_slope(recent), 3),
            "evidence": _ev(signals, turns),
        }
    return None


def judge_expression(signals, turns=None, aro_delta=None, len_ratio=None):
    """表达强度：强度与长度同时掉到基线以下（两个都掉才算，防误判）。

    注意**必须按同一轮对齐**：不能分别对 aro 和 len 各做一次 `_series` 过滤再取尾部。
    aro 偶有缺失（`score_text` 失败时是 None），两条序列就会错位，
    判据变成"最近 N 个有 aro 的轮次"对"最近 N 个有 len 的轮次"，语义就漂了。
    所以先取 aro 与 len **都非 None** 的那批轮次，再在同一个下标上做统计。
    """
    turns = C.DRIFT_TONE_LIMIT if turns is None else turns
    aro_delta = C.DRIFT_EXPR_ARO_DELTA if aro_delta is None else aro_delta
    len_ratio = C.DRIFT_EXPR_LEN_RATIO if len_ratio is None else len_ratio
    tail = [s for s in signals
            if isinstance(s, dict) and s.get("aro") is not None and s.get("len") is not None]
    if len(tail) < turns + 1:
        return None
    aros = [float(s["aro"]) for s in tail]
    lens = [float(s["len"]) for s in tail]
    base_aro = _med(aros[:-turns])
    base_len = _med(lens[:-turns])
    if base_aro <= 0 or base_len <= 0:
        return None
    ra = aros[-turns:]
    rl = lens[-turns:]
    if all(a < base_aro - aro_delta for a in ra) and all(l < base_len * len_ratio for l in rl):
        return {
            "dim": "expression",
            "level": "notable",
            "since": "最近几轮",
            "note": "没什么情绪起伏，话也淡",
            "baseline": {"aro": round(base_aro, 3), "len": round(base_len, 1)},
            "slope": round(_slope(rl), 3),
            "evidence": _ev(tail, turns),
        }
    return None


def judge_proactive(daily_count, cap=None):
    """主动性：今天找他的次数超过 cap。

    **当前配置下这条判据是死的，而且是刻意留着的**：`PROACTIVE_DAILY_CAP` 是 1，
    她一天最多主动发一条，永远达不到 `DRIFT_PROACTIVE_CAP` 的 5。
    留着是因为以后放开日配额（比如提到 3）时，这一维要立刻能用；
    不要因为它现在不触发就把 `DRIFT_PROACTIVE_CAP` 调成 2 —— 那会把"正常用满额度"
    误判成"变黏人"。真正的黏人信号是长期趋势，不是单日次数。

    「连续 3 天 0 次」这条没做——要日级历史，现在库里没有按天聚合的出口，
    等真有数据再补（别为了凑齐判据造假数据）。
    """
    cap = C.DRIFT_PROACTIVE_CAP if cap is None else cap
    if cap is None or cap <= 0 or daily_count is None:
        return None
    if daily_count > cap:
        return {
            "dim": "proactive",
            "level": "notable",
            "since": "今天",
            "note": "今天找他的次数偏多了",
            "baseline": {"cap": cap},
            "delta": daily_count - cap,
            "evidence": [{"daily": int(daily_count), "cap": cap}],
        }
    return None


def detect(signals, daily_count=None):
    """一次性判全部维度（不碰状态机）。供 CLI / 测试 / 回看用。"""
    hits = []
    if len(signals) >= C.DRIFT_BASE_TURNS:
        for f in (judge_tone, judge_silence, judge_expression):
            h = f(signals)
            if h:
                hits.append(h)
    h = judge_proactive(daily_count)
    if h:
        hits.append(h)
    return hits


# ---------------------------------------------------------------- 状态机


class DriftTracker:
    """同一次偏移只记一条。

    没有状态机就会有两个后果：events 表每轮多一条；简报的自觉段每轮都在说
    「你今天话有点冲」——她会变成一个唠叨的人。所以偏移状态存 kv，
    进入时记一次、持续期间什么都不做、回正时记一条 normal。
    """

    def __init__(self, store, ns):
        self.store = store
        self.ns = ns

    def _k(self, key):
        return f"{key}:{self.ns}"

    def _load(self, key, default):
        raw = self.store.get_kv(self._k(key))
        if not raw:
            return default
        try:
            return json.loads(raw)
        except Exception:
            return default

    def _save(self, key, obj):
        try:
            if obj is None:
                self.store.set_kv(self._k(key), "")
            else:
                self.store.set_kv(self._k(key), json.dumps(obj, ensure_ascii=False))
        except Exception:
            pass

    # ---------- 按天聚合（comfort 判"一段时间"用） ----------
    # 窗口只留 40 轮，跨不了天。所以另存一份"每天的累计"：只累加不存原文，
    # 一天一个 kv 键。不建表——011 已经定过"事件表够了，不要新表"。
    @staticmethod
    def _day_key(ts):
        import time as _t
        return "drift:day:" + _t.strftime("%Y%m%d", _t.localtime(ts or _t.time()))

    def _bump_day(self, val, at):
        if val is None:
            return
        try:
            k = self._day_key(at)
            d = self._load(k, {}) or {}
            d["n"] = int(d.get("n") or 0) + 1
            d["sv"] = float(d.get("sv") or 0.0) + float(val)
            self._save(k, d)
        except Exception:
            # 日聚合坏了不该拖累主流程——所以吞。但吞不等于不管：
            # governor 的 health 台账会记 drift.observe 那一次失败。
            pass

    def daily_mood(self, days=14, now=None):
        """近 N 天的日均 val，**老 → 新**，那天没数据就给 None。

        给 comfort.low_streak 用。它只认"连续尾部"，所以缺的那天必须保留成
        None——如果压掉，就把"中间断了一天"变成"连着低"，判据会假阳。
        """
        import time as _t
        now = _t.time() if now is None else float(now)
        out = []
        for i in range(int(days) - 1, -1, -1):
            k = self._day_key(now - i * 86400.0)
            d = self._load(k, None)
            if not d or not d.get("n"):
                out.append(None)
            else:
                out.append(round(float(d.get("sv") or 0.0) / float(d["n"]), 3))
        return out

    def _record(self, rec, level="notable"):
        """谁判定的谁留证据（011 §7 证据闸）。

        放在检测层而不是调用方：调用方漏接一次，这条偏移就永远查不到了。
        走过 guard 的 record_drift 是为了字段名和其他地方一致，别自造字段。
        """
        try:
            from .guard import record_drift as _rd
            d = _rd(rec.get("dim"), level, since=rec.get("since"), note=rec.get("note"))
            if rec.get("evidence") is not None:
                d["evidence"] = rec.get("evidence")
            if rec.get("baseline") is not None:
                d["baseline"] = rec.get("baseline")
            if rec.get("delta") is not None:
                d["delta"] = rec.get("delta")
            if rec.get("slope") is not None:
                d["slope"] = rec.get("slope")
            self.store.log_event(self.ns, "drift", d)
        except Exception:
            pass

    # ---- 对外

    def window(self):
        w = self._load("drift:win", [])
        return w if isinstance(w, list) else []

    def active(self):
        a = self._load("drift:active", None)
        return a if isinstance(a, dict) else None

    def observe(self, val=None, aro=None, reply_len=None, at=None, daily_count=None):
        """每轮调一次。

        返回：
          {"event": "enter", ...}   刚进入偏移 → 调用方落一条 notable
          {"event": "recover", ...} 回正 → 调用方落一条 normal
          None                      无事发生 / 持续期间（**不重复记录**）
        """
        w = self.window()
        w.append({"at": at, "val": val, "aro": aro, "len": reply_len})
        w = w[-WIN_MAX:]
        self._save("drift:win", w)
        self._bump_day(val, at)

        act = self.active()
        hits = detect(w, daily_count=daily_count) if len(w) >= C.DRIFT_BASE_TURNS else []

        if act is None:
            if not hits:
                return None
            top = hits[0]
            rec = {
                "dim": top["dim"],
                "since": top.get("since"),
                "level": "notable",
                "clean": 0,
                "note": top.get("note"),
                "evidence": top.get("evidence"),
                "baseline": top.get("baseline"),
                "delta": top.get("delta"),
                "slope": top.get("slope"),
            }
            self._save("drift:active", rec)
            self._record(rec, "notable")
            return {"event": "enter", **rec}

        if hits:
            act["clean"] = 0
            self._save("drift:active", act)
            return None           # 持续期间：不重复记录、不重复说

        act["clean"] = int(act.get("clean", 0)) + 1
        need = max(C.DRIFT_TONE_WINDOW, C.DRIFT_RECOVER_TURNS)
        if act["clean"] >= need:
            self._save("drift:active", None)
            rec = {"dim": act.get("dim"), "since": act.get("since"),
                   "note": "回正了"}
            self._record(rec, "normal")
            return {"event": "recover", "dim": act.get("dim"),
                    "since": act.get("since"), "note": act.get("note"),
                    "clean": act["clean"]}
        self._save("drift:active", act)
        return None

    def state(self):
        """给 CLI / 状态桥看：当前在不在偏移里、哪个维度、证据是什么。"""
        act = self.active()
        return {
            "active": bool(act),
            "dim": (act or {}).get("dim"),
            "since": (act or {}).get("since"),
            "note": (act or {}).get("note"),
            "level": (act or {}).get("level"),
            "clean": (act or {}).get("clean"),
            "evidence": (act or {}).get("evidence"),
            "window": len(self.window()),
        }
