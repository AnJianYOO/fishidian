# -*- coding: utf-8 -*-
"""fishidian_core.governor —— 治理层统一 API（DSH 插件唯一入口）。
recall / build_injection / observe_turn / sweep / state / forget / 管理命令
（17 号 §12.8 起：五行引擎 / 先天锚 / 冷战状态机 / 主动性 已并入 observe_turn 与 state）"""
from __future__ import annotations

import json
import os
import re
import time

from . import config as C
from . import env as Env
from .mask import mask
from .persona import Persona
from .pools import Pools, compute_r, tier_of, overlap
from .safety import Fuse
from .scoring import score_text, neg_strength, Embed
from .store import Store
from .tail import de_ego
from .throttle import Throttle, omega_at
from .wuxing import WuXingEngine, HasCause, tag_of_text, tag_detail
from .coldwar import ColdWar, is_heal
from .proactive import Proactive
from .expression import Expression
from .drift import DriftTracker


class Governor:
    """一个实例服务一个 ns；全局 P 共享（store 级 kv）。

    关键纪律（来自治理层，不允许在插件里退化）：
    - 召回 ≠ 强化：recall 只 touch，只有 observe_turn 里 adopt 才 +DELTA_R。
    - 注入不覆盖人格：build_injection 输出带 marker，插件只能在 marker 内追加。
    - 群聊不注入私聊记忆：recall 按 ns+visibility 过滤。
    """

    def __init__(self, ns: str, store: Store = None, backend: str = "bow", bge_fn=None):
        self.ns = ns
        self.store = store or Store()
        self.embed = Embed(backend, bge_fn)
        self.pools = Pools(self.store)
        self.persona = Persona(self.store)
        self.fuse = Fuse(self.store, ns)
        self.throttle = Throttle(self.store, ns)
        # 17 号 §12.8 人格涌现层：五行引擎 / 有因判定 / 冷战 / 主动性
        self.wuxing_mode = os.environ.get("FISHIDIAN_WUXING_MODE", "B").upper()
        if self.wuxing_mode not in ("A", "A+", "B"):
            self.wuxing_mode = "B"
        self.wuxing_ymd = None
        try:
            raw = os.environ.get("FISHIDIAN_WUXING_YMD", "")
            if raw:
                y, m, d = raw.split("-")
                self.wuxing_ymd = (int(y), int(m), int(d))
        except Exception:
            self.wuxing_ymd = None
        self.wuxing_city = os.environ.get("FISHIDIAN_WUXING_CITY", "")
        if not self.wuxing_city:
            # 部署地没显式配 → 用情报层记住的城市（通用抽取，认不出就留空，方位按"中"）
            try:
                from .intel import get_city
                self.wuxing_city = get_city(self.store, ns) or ""
            except Exception:
                self.wuxing_city = ""
        self.wuxing = WuXingEngine(self.store, ns, mode=self.wuxing_mode,
                                   w_base=[0.2] * 5)
        self.has_cause = HasCause(self.store, ns)
        self.coldwar = ColdWar(self.store, ns)
        self.proactive = Proactive(self.store, ns)
        # 17 号 §12.8 表达涌现：倾向层 + 表达记忆池 + 波动/情境
        self.expr = Expression(self.store, ns)
        # 011 §5.3 偏移自动检测：每轮喂信号，越阈值才落一条 drift 事件
        self.drift = DriftTracker(self.store, ns)
        # 失败留痕：所有"坏了就静默"的接点都往这里记一笔。
        # 存在的理由是本项目最贵的一类故障——try/except 吞掉之后，她只是
        # "不那么像人"，332 个测试照样全绿，没人知道哪根线断了。
        self._fails = {}

    def _note_fail(self, key: str, err: BaseException):
        """记一次静默失败。只放内存：进程重启本身就是干净起点。"""
        import time as _t
        r = self._fails.get(key) or {"n": 0, "last": 0.0, "err": ""}
        r["n"] = int(r.get("n") or 0) + 1
        r["last"] = _t.time()
        r["err"] = "%s: %s" % (type(err).__name__, str(err)[:90])
        self._fails[key] = r

    def health(self) -> dict:
        """静默失败台账。空 dict = 本次进程启动以来没有任何接点出过错。

        看到某一项非零，第一件事是去看它的 err 和出现时间——那一项当时
        没有干活，但也没有任何地方会报出来。
        """
        out = {}
        for k, v in self._fails.items():
            out[k] = dict(v)
            if v.get("last"):
                out[k]["last_ago_min"] = round((self._now_hack() - v["last"]) / 60.0, 1)
        return out

    @staticmethod
    def _now_hack() -> float:
        import time as _t
        return _t.time()

    # ---------- 安慰决策（018 §六 / comfort.py） ----------
    def comfort_decide(self, query: str = "", now=None) -> dict:
        """算这一轮该不该“接住他”。不发送，只出决定 + 记账。

        `query` 是对方这一句话，只用来认“别管我”这类明确拒绝。
        不拿它判情绪——情绪走 drift 的日聚合，一句不算数。
        """
        import time as _t
        from .comfort import should_comfort, detect_stop
        now = _t.time() if now is None else float(now)

        hist = None
        try:
            hist = self.drift.daily_mood(days=14, now=now)
        except Exception as e:
            self._note_fail("comfort.hist", e)

        cw = False
        try:
            cw = bool((self.coldwar.snapshot() or {}).get("cold"))
        except Exception as e:
            self._note_fail("comfort.coldwar", e)

        silent_h = None
        try:
            from .intel import social_context
            silent_h = (social_context(self.store, self.ns) or {}).get("gap_hours")
        except Exception as e:
            self._note_fail("comfort.gap", e)

        # 账本：store.get_kv 是 (key, default)，**不带 ns**，所以 ns 和日期都要
        # 自己拼进键里。cnt 必须带日期——否则第二天起永远 >= CAP，comfort 永久关闭。
        day = _t.strftime("%Y%m%d", _t.localtime(now))
        k_stop = "comfort:%s:stop_at" % self.ns
        k_last = "comfort:%s:last" % self.ns
        k_cnt = "comfort:%s:cnt:%s" % (self.ns, day)

        stop_at, last, cnt = None, None, 0
        try:
            stop_at = self.store.get_kv(k_stop)
            last = self.store.get_kv(k_last)
            cnt = int(self.store.get_kv(k_cnt) or 0)
        except Exception as e:
            self._note_fail("comfort.book", e)

        stop_hit = detect_stop(query)
        if stop_hit:
            # 他说了想一个人 → 记一个尊重期。不回应那句“别管我”本身，
            # 因为回应它就是在管他。
            try:
                self.store.set_kv(k_stop, now + C.COMFORT_STOP_H * 3600.0)
            except Exception as e:
                self._note_fail("comfort.book", e)

        d = should_comfort(mood_hist=hist, cold_war=cw, silent_h=silent_h,
                           stop_hit=stop_hit, stop_at=stop_at,
                           last_comfort_at=last, today_count=cnt, now=now)
        d["hist"] = hist
        return d

    def comfort_mark(self, now=None):
        """她真做了之后记一笔。只在 mode 落成 hold 时调。

        `cnt` 键带日期，跨天自动从 0 起——它代表“今天接住过几次”。
        """
        import time as _t
        now = _t.time() if now is None else float(now)
        day = _t.strftime("%Y%m%d", _t.localtime(now))
        k_last = "comfort:%s:last" % self.ns
        k_cnt = "comfort:%s:cnt:%s" % (self.ns, day)
        try:
            self.store.set_kv(k_last, now)
            self.store.set_kv(k_cnt, int(self.store.get_kv(k_cnt) or 0) + 1)
        except Exception as e:
            self._note_fail("comfort.mark", e)

    # ---------- 召回 ----------
    def recall(self, query: str, k: int = 6, visibility: str = None):
        """五路融合 + 层级过滤（只召回督脉与高 R 孕育）+ 当位门控（按相似度裁决采纳）。
        返回 [(mem, sim), ...] 已排序。只 touch，不涨 R。"""
        mems = self.store.query_active(self.ns)
        if visibility:
            mems = [m for m in mems if m["visibility"] == visibility]
        omega = omega_at(time.localtime().tm_hour, self.embed.backend)
        scored = []
        for m in mems:
            sim = self.embed.similarity(query, m["text"])
            imp_n = m["importance"] / 10.0
            age_h = max(0.0, (time.time() - m["last_at"]) / 3600.0)
            rec = (C.W_SEM * sim + C.W_IMP * imp_n
                   + C.W_TIME * max(0.0, 1.0 - age_h / 720.0)
                   + C.W_SIM * (0.5 if m["cluster"] else 0.0))
            # 层级偏好：督脉 > 孕育 > 血海（身份主线优先）
            tier_bonus = {"du": 0.25, "yun": 0.12, "blood": 0.0}.get(m["tier"], 0.0)
            rec += tier_bonus
            adopt = sim >= omega
            scored.append((m, round(rec, 4), round(sim, 4), adopt))
            self.pools.on_recall_touch(m["id"])
        scored.sort(key=lambda t: t[1], reverse=True)
        return scored[:k]

    # ---------- 分级召回（020）：沉底区 ----------
    # 印象档给的不是原文，是一句反应。模型看到它知道"聊过但不能编"，
    # 看到原文反而会自己补细节——给碎片不如什么都不给。
    _FAINT_SENSE_TEXT = "这个话题你有点似曾相识，但想不起具体是什么。"
    _FAINT_HALF_CAP = 2
    _FAINT_SENSE_CAP = 1

    def _recall_faint(self, query: str, omega: float):
        """扫沉底区分「一半」「印象」两档，返回 [(mem, sim, kind)]，kind∈{"half","sense"}。

        三条硬约束（020 §4）：
        ① 只读——query_archived 只 SELECT，不改 status、不改 r；
        ② 不 touch——否则 last_hit_at 更新、R 被推高，它借「被想起」复活，血海上限失效；
        ③ 不抢位——调用方只在情境层没占满时补位，且两档各有上限。

        门槛 = max(INJECT_MIN_SIM, FAINT_HALF_SIM, omega)，三路取最大：
        bow 下 0.46 生效、bge 下 omega 0.65 自动接管，不必另配一套数。
        0.46 是在 60 条不同事件的真实多样语料上扫出来的——库内话题最低 0.500、
        库外话题最高 0.374，真空带就是 0.374~0.500。
        """
        if not C.FAINT_ON or not query:
            return []
        hi = max(C.INJECT_MIN_SIM, C.FAINT_HALF_SIM, omega)
        lo = hi - C.FAINT_SENSE_GAP
        cands = []
        for m in self.store.query_archived(self.ns):
            sim = self.embed.similarity(query, m["text"])
            if sim >= hi:
                cands.append((sim, m, "half"))
            elif sim >= lo:
                cands.append((sim, m, "sense"))
        cands.sort(key=lambda t: t[0], reverse=True)
        out, n_half, n_sense = [], 0, 0
        for sim, m, kind in cands:
            if kind == "half":
                if n_half >= self._FAINT_HALF_CAP:
                    continue
                n_half += 1
            else:
                if n_sense >= self._FAINT_SENSE_CAP:
                    continue
                n_sense += 1
            out.append((m, round(sim, 4), kind))
        return out

    @staticmethod
    def _faint_cut(text: str, limit: int = None):
        """一半档的残句：切到 limit 字，尽量在标点处收住，避免跨事件拼接。"""
        limit = limit or C.FAINT_HALF_CHARS
        t = (text or "").strip()
        if len(t) <= limit:
            return t
        head = t[:limit]
        for p in ("，", "。", "；", "、", "！", "？", ",", ".", ";", "!", "?"):
            i = head.rfind(p)
            if i >= limit // 2:
                return head[:i + 1]
        return head + "…"

    # ---------- 注入前三道闸（R34 / D-028） ----------
    def _gate_item(self, m, sim, adopt, picked, layer, faint=None):
        """进 prompt 之前的过滤。返回 (ok, reason)；reason 只用于审计计数。

        为什么必须在这儿：recall() 只把 adopt 变成标签里的两个字（"采纳"/"参考"），
        两种都照样进 prompt —— "她记错事"就出在这层没有闸。
        三道分别是：与这句话无关（low_sim）、与已入选的重（dup）、只依稀记得又不重要（suspect）。
        """
        # ① 有效闸：情境层里「不是当位命中」且相似度低于地板 → 与这句话没关系，不占预算
        #    faint 条目例外：它的门槛已在 _recall_faint 里判过（印象档本来就在地板以下，
        #    那一档给的不是原文而是反应，靠 ③ 存疑闸限量，不靠这道闸）。
        if layer == "情境" and sim is not None and not adopt and faint is None:
            if float(sim) < C.INJECT_MIN_SIM:
                return False, "low_sim"
        # ② 重复闸：与已入选条目高度重复 → 只留先入选的那条（身份层先入，天然留下高价值的）
        for p in picked:
            if p["id"] == m["id"]:
                continue
            a = p.get("_raw") or ""
            b = (m["text"] or "")[:C.INJECT_TEXT_CAP]
            if overlap(a, b) >= C.INJECT_DUP_JAC:
                return False, "dup"
            if len(self._lcs(a, b)) >= C.INJECT_DUP_LCS:
                la, lb = len(a), len(b)
                # 长句包含短句不算重复：后者往往信息更多
                if la and lb and min(la, lb) / max(la, lb) >= 0.7:
                    return False, "dup"
        # ③ 存疑闸：不是"丢掉"，是"限量"，而且只管**情境层**。
        #    她只依稀记得有这回事（细节不可靠）本身是有价值的信息，比完全不记得更真；
        #    但一次进三条，整段注入就变成"好像…好像…不太确定…"，反而像装的 → 最多留 1 条。
        #    兜底层（最近 2 条）不受限制：刚说的话即使 R 还低（没被引用过），也是当下对话的一部分，
        #    不是"捕风捉影的旧记忆"，挡掉等于把她刚听见的扔了。
        #    faint 条目也不受限制：沉底条目 R 必然低、必然判「存疑」，
        #    但它已经自带限量（一半 2 条 / 印象 1 条），再叠一道会永远进不来。
        if layer == "情境" and faint is None and self._conf_of(m) == "存疑":
            if len((m["text"] or "").strip()) < 4:
                return False, "noise"
            if sum(1 for p in picked if p.get("conf") == "存疑") >= C.INJECT_SUSPECT_MAX:
                return False, "suspect"
        return True, ""

    # ---------- 注入 ----------
    def build_injection(self, items, budget: int = None) -> str:
        """拼注入块（≤ budget 字符，带 marker）。无条目时返回 None（宿主侧不注入）。"""
        budget = budget or C.INJECT_BUDGET
        lines = []
        used = 0
        picked, gated, masked_n = [], {}, [0]
        for m, rec, sim, adopt in items:
            ok, why = self._gate_item(m, sim, adopt, picked, "情境")
            if not ok:
                gated[why] = gated.get(why, 0) + 1
                continue
            tag = "采纳" if adopt else "参考"
            raw = (m["text"] or "")[:60]
            hits = []
            safe = mask(raw, hit=hits)
            if hits:
                masked_n[0] += len(hits)
            line = f"- [R{m['r']:.1f}|{m['tier']}|{tag}] {safe}"
            if used + len(line) > budget:
                break
            lines.append(line)
            picked.append({"id": m["id"], "text": safe, "_raw": raw,
                           "conf": self._conf_of(m)})
            used += len(line)
        try:
            if gated or masked_n[0]:
                self.store.log_event(self.ns, "inject_gate",
                                     {"kept": len(picked), "gated": gated,
                                      "masked": masked_n[0]})
        except Exception:
            pass
        # 情报段：已知城市时附一句真实天气（不占记忆预算，失败就少一行；
        # 没有记忆命中时也照样注入，否则"今天冷不冷"会答不出）
        wl = None
        try:
            from .intel import weather_line
            wl = weather_line(self.store, self.ns)
        except Exception:
            wl = None
        if not lines and not wl:
            return None
        body = "\n".join(lines)
        if wl:
            body = (body + "\n- [intel] " + wl) if body else ("- [intel] " + wl)
        return ("<!-- fishidian:memory:start -->\n"
                "以下是“她”记得的与你相关的事（只作参考，不影响人格设定）：\n"
                + body +
                "\n<!-- fishidian:memory:end -->")

    # ---------- 一轮上下文（单次进程：分层记忆 + 状态 + 时间 + 表达） ----------
    @staticmethod
    def _ago_text(at, now=None):
        """记忆时间的口语标注（与插件 agoOf 同口径，单一真源搬到内核）。"""
        now = now if now is not None else time.time()
        s = max(0.0, now - float(at or 0))
        if s <= 60:
            return "刚刚"
        if s < 3600:
            return f"{int(s // 60)}分钟前"
        if s < 86400:
            return f"{int(s // 3600)}小时前"
        if s < 172800:
            return "昨天"
        if s < 604800:
            return f"{int(s // 86400)}天前"
        return "很久以前"

    @staticmethod
    def _conf_of(m):
        """置信三档（B6 弃权）：身份=督脉 R≥8（确证）/ 经历=孕育或血海 R≥2 / 存疑=R<2 的短句噪声。"""
        r = float(m["r"])
        if m["tier"] == "du" and r >= C.THETA_DU:
            return "身份"
        if r < C.R_UNRIPE:
            return "存疑"
        return "经历"

    # ---------- 状态简报（010）：她自己的体感 ----------
    def _brief_text(self, kept, now=None):
        """把当前状态编译成一段她自己的话。失败返回 ""，绝不影响注入。

        和执行体里那行「（小鱼当前状态：情绪基调 X，关系温度 Y）」的分工：
        那行是给模型的**标签**，这行是给她自己的**话**——前者陈述，后者有身体感。
        两者都留着：标签管准确，这句话管像不像人。
        """
        try:
            from .brief import StateSnapshot, compile_brief
            from .wuxing import WUXING
            from .intel import social_context

            ws = self.wuxing.state()
            # 用 E（五志情绪池）而不是 W：
            #   W 是主行隔离后的**权重**，主行固定在入场值、其余重新分配，
            #   所以"火旺"不会让 W[火] 升高，拿它当强度永远看不出谁旺。
            #   E 才是"这一脏当下有多少情绪"，也正是 brief 要说的身体感来源。
            e = ws.get("E") or {}
            vals = []
            for k in WUXING:
                try:
                    vals.append(float(e.get(k, 0.0)))
                except (TypeError, ValueError):
                    vals.append(0.0)
            organs = {}
            if len(vals) == 5:
                mean = sum(vals) / 5.0
                dev = [v - mean for v in vals]
                mx = max((abs(d) for d in dev), default=0.0)
                # 无明显偏离就什么都不报（安静的时候不该硬说她哪不舒服）
                if mx > 0.05:
                    organs = {k: max(0.0, min(1.0, 0.5 + 0.5 * d / mx))
                              for k, d in zip(WUXING, dev)}

            cw = self.coldwar.snapshot()
            temp = cw.get("temperature") or "亲近"
            dist = {"亲近": 0.25, "缓和": 0.55, "疏离": 0.85}.get(temp)

            # 摩擦：有过不愉快但还没冷到"冷战"那一步。
            # 冷战时简报只说"还在冷着"——brief.py 里两者是互斥的，
            # 这里给 None 更省事，也避免同一件事说两遍。
            friction = None
            if not cw.get("cold"):
                try:
                    friction = float(cw.get("score") or 0) > 0
                except (TypeError, ValueError):
                    friction = None

            scene = [p for p in kept if p.get("layer") == "情境"]
            # 简报里说的「想起了什么」只要清楚档的——一半/印象档说了等于没说，
            # 真拿它当 recall_text，她就会把自己的含糊当事实复述。
            solid = [p for p in scene if not p.get("faint")]
            rt = solid[0].get("text") if solid else None
            rw = solid[0].get("ago") if solid else None

            gap = None
            try:
                gap = social_context(self.store, self.ns).get("gap_hours")
            except Exception:
                gap = None

            now_ts = now if now else time.time()

            # 主动性：只读不写（deliver=None 零副作用）。
            # 010 §6 原本写"简报产出 should_reach 交给 proactive"，实际只能反过来——
            # should_reach 要由主动性打分算出来，简报再去算就是循环依赖。
            # 所以这里消费 proactive 的判定，两边口径因此一致。
            should_reach = None
            hold = None
            try:
                pc = self.proactive.check(self, deliver=None)
                should_reach = bool(pc.get("should_act"))
                q = pc.get("quota") or {}
                if should_reach:
                    if pc.get("quiet"):
                        hold = "刚才聊得有点多"
                    elif q.get("cap_ok") is False:
                        hold = "今天已经找过他一次了"
                    elif q.get("gap_ok") is False:
                        hold = "刚说过话"
                elif cw.get("cold"):
                    hold = "还在冷着"
            except Exception:
                should_reach, hold = None, None

            # 偏移（011）：落在事件表，近 24 小时有 notable/over 才出"自觉"段
            drift_dim = drift_level = drift_since = None
            try:
                for ev in self.store.recent_events(self.ns, "drift", limit=1,
                                                   since=(now_ts - 86400.0)):
                    raw = ev.get("payload")
                    d = json.loads(raw) if isinstance(raw, str) else (raw or {})
                    lv = d.get("level")
                    if lv in ("notable", "over"):
                        drift_dim = d.get("dim")
                        drift_level = lv
                        drift_since = d.get("since") or "刚才"
            except Exception as e:
                self._note_fail("brief.drift", e)

            # 欠着的事（011 §3 条款三第二句）：扫事件表，只取欠得最久的一条。
            # 一条就够——同时提三件会变成讨债信，她不是催收的。
            # "due" 和 "vague" 要分开：说好了哪天但没做，跟没定日子一直拖着，
            # 不是同一件事，措辞也不能一样。
            promise_due = None
            try:
                dues = self.due_promises(now=now_ts)
                if dues:
                    first = dues[0]
                    promise_due = "due" if first.get("due") is not None else "vague"
            except Exception as e:
                self._note_fail("brief.promise", e)
                promise_due = None

            hour = time.localtime(now_ts).tm_hour

            s = StateSnapshot(
                organs=organs,
                relation_distance=dist,
                relation_friction=friction,
                cold_war=bool(cw.get("cold")),
                recall_text=rt, recall_when=rw,
                recall_score=(1.0 if rt else None),
                silence_hours=gap,
                hour_of_day=hour,
                should_reach=should_reach,
                hold_reason=hold,
                drift_dim=drift_dim,
                drift_level=drift_level,
                drift_since=drift_since,
                promise_due=promise_due,
            )
            txt = compile_brief(s)
            if not txt:
                return ""
            return txt.replace("【你现在的状态】\n", "").strip()
        except Exception as e:
            self._note_fail("brief", e)
            return ""

    def build_context(self, query: str = "", budget: int = None, ask_weather: bool = False):
        """一轮注入的全部上下文，按"分层配额"取记忆（P0-1/A1 的最终版）：
          ① 身份层：督脉 R 前 3 常驻（她是谁、你俩什么关系）
          ② 情境层：按这句话召回最多 4 条（这句话该想起什么）
          ③ 兜底层：最近 2 条（刚聊的，防召回漏）
        返回 items（带 conf/ago）+ 可直接拼进 prompt 的 injection 文本。
        天气只由调用方（插件里的 WEATHER_RE）决定要不要，内核不判正则。"""
        budget = budget or C.INJECT_BUDGET
        now = time.time()
        # 开场先补一次"久未见"结算。不能只靠 daemon：tick 是 10 分钟一次，
        # 用户关机三天后打开就说第一句，完全可能还没轮到 tick —— 那样她会是
        # "完全没感觉"的，v0.1.0 的验收标准（能说出"你这几天没来"）当场就废了。
        # 幂等：<3h 不结算，结算过的不再算，所以每轮都调也不会重复难过。
        try:
            self.settle_gap(now=now)
        except Exception as e:
            self._note_fail("build_context.settle", e)
        active = self.store.query_active(self.ns)
        picked, seen = [], set()
        gated, masked_n = {}, [0]

        def take(m, layer, sim=None, adopt=None, faint=None):
            mid = m["id"]
            if mid in seen:
                return
            ok, why = self._gate_item(m, sim, adopt, picked, layer, faint)
            if not ok:
                gated[why] = gated.get(why, 0) + 1
                return
            seen.add(mid)
            raw = (m["text"] or "")[:C.INJECT_TEXT_CAP]
            hits = []
            safe = mask(raw, hit=hits)   # R30：出站脱敏，库里仍是原文
            if hits:
                masked_n[0] += len(hits)
            # 分级召回（020）：一半给残句、印象一个字都不给。
            # 印象档若也摘 6-8 字，中文已能说出事件主体，两档就糊在一起了；
            # 给碎片还会诱发模型自己补细节（编）——宁可什么都不给。
            if faint == "half":
                safe = self._faint_cut(safe)
            elif faint == "sense":
                safe = self._FAINT_SENSE_TEXT
            picked.append({
                "id": mid, "text": safe,
                "r": round(float(m["r"]), 2), "tier": m["tier"],
                "conf": self._conf_of(m), "ago": self._ago_text(m["born_at"], now),
                "layer": layer, "_raw": raw, "faint": faint,
            })

        for m in sorted([x for x in active if x["tier"] == "du"],
                        key=lambda x: -float(x["r"]))[:3]:
            take(m, "身份")
        if query:
            scene_n = 0
            for m, rec, sim, ad in self.recall(query, k=6):
                take(m, "情境", sim, ad)
                scene_n = sum(1 for p in picked if p["layer"] == "情境")
                if scene_n >= 4:
                    break
            # 补位（020）：活着的没占满，才去沉底区捞「一半」「印象」。
            # 顺序必须是先 active 后沉底——沉底条目永不抢位，血海 72 上限才不被绕过。
            if scene_n < 4:
                omega = omega_at(time.localtime().tm_hour, self.embed.backend)
                for m, sim, kind in self._recall_faint(query, omega):
                    take(m, "情境", sim, None, kind)
                    scene_n = sum(1 for p in picked if p["layer"] == "情境")
                    if scene_n >= 4:
                        break
        for m in sorted(active, key=lambda x: -float(x["born_at"] or 0))[:2]:
            take(m, "最近")

        kept, used = [], 0
        for p in picked:
            ln = len(p["text"]) + 26
            if used + ln > budget:
                break
            kept.append(p)
            used += ln

        ex = self.expr.derive(self)
        emotion = ex.get("dominant") or "平和"
        temp = ex.get("temperature") or "亲近"
        lines = []
        for p in kept:
            if p.get("faint") == "half":
                lines.append(f"- （{p['ago']}）[一半] {p['text']}")
            elif p.get("faint") == "sense":
                lines.append(f"- （{p['ago']}）[印象] {p['text']}")
            else:
                lines.append(f"- （{p['ago']}）[{p['conf']}] {p['text']}")
        body = "\n".join(lines)
        head = "（你脑子里关于对方的事，能对上就说，对不上就别硬编：）\n"
        conf_note = ("（[身份]=她确定的事，可当事实说；[经历]=记得但细节未必准，别补编；"
                     "[存疑]=只依稀记得，说“好像/记得你提过”就好，别当事实）")
        # 分级召回（020）：中间两档必须各自一句，否则模型会把「一半」也当全文说
        if any(p.get("faint") == "half" for p in kept):
            conf_note += "\n（[一半]=只记得这事的前半截，别把后半补出来）"
        if any(p.get("faint") == "sense" for p in kept):
            conf_note += "\n（[印象]=只记得聊过这个话题，具体内容已经忘了，别编任何细节）"
        inj = (head + body if body else "") + (("\n" + conf_note) if body else "")
        # R2 遗忘的表达：真有不牢靠的记忆时，才加这一句（没有就不啰嗦）
        if any(p["conf"] == "存疑" for p in kept):
            inj += "\n（对方问到你只依稀记得的事，就说记不太清了，别为了圆场补细节。）"
        inj += f"\n（小鱼当前状态：情绪基调 {emotion}，关系温度 {temp}）"
        # 状态简报（010）：标签上面那行管准确，这句管像人。失败就不加，不阻塞注入。
        bt = self._brief_text(kept, now)
        if bt:
            inj += "\n（你自己这会儿：" + bt + "）"
        # 逆体质纠偏（「01_理论设计」§6.2 第四道保险）
        # 简报那段的 organs 是"相对偏离归一化"（0.5±0.5d/mx），那是给人读的感觉；
        # 这里要判"真过亢/真亏虚"，必须用 E/cap 的**绝对强度**，两套口径不能混用
        # ——混了就会出现"她明明很平稳，却因为五行彼此有差被判定为某行亏虚"。
        stance = None
        try:
            from .regulate import suggest_stance
            e_raw = (self.wuxing.state() or {}).get("E") or {}
            org = {}
            for k, v in e_raw.items():
                if k in ("木", "火", "土", "金", "水"):
                    try:
                        org[k] = min(1.0, float(v) / float(C.WUXING_CAP))
                    except (TypeError, ValueError):
                        pass
            # 用上一轮的强度判轻重：这一轮对方的话还没进来。
            aro_now = None
            try:
                w = self.drift.window()
                if w:
                    aro_now = w[-1].get("aro")
            except Exception as e:
                self._note_fail("stance.arousal", e)
                aro_now = None
            stance = suggest_stance(org, arousal=aro_now)
            if stance:
                inj += ("\n（这会儿说话的倾向：" + stance["stance"] + "，"
                        + stance["reason"]
                        + "。这是你自己的劲儿，不是台词，别把它念出来。）")
        except Exception as e:
            self._note_fail("stance", e)
            stance = None
        # 安慰决策（018 §六 / comfort.py）：他这几天一直不对时，只接住，不往亮处带。
        # 这条跟上面的 stance 是两件事：stance 管"她自己什么劲"，这条管"他需要什么"。
        comfort = {"mode": "none", "reason": "未判定"}
        try:
            from .comfort import hold_line
            comfort = self.comfort_decide(query=query)
            if comfort.get("mode") == "hold":
                inj += "\n" + hold_line()
                self.comfort_mark()
        except Exception as e:
            self._note_fail("comfort", e)

        # 人格底线（011）：写在注入里才是真约束——审核只能记账，管不住嘴。
        # 四条对着 guard.py 的判据来：底线词 / 疼处词 / 不确定硬断言 / 装记得。
        inj += ("\n（有几件事你从来不干：咒对方去死、拿身材长相戳对方、"
                "替对方下“你很确定”的判断、装记得其实没记住的事。"
                "真记不清就直说忘了，别圆——圆一次往后就不可信了。）")
        # 时间行（纯本地）：时刻/时辰干支/节气 + 距上次对话 + 对方活跃时段
        try:
            from .intel import social_context, time_context
            tc = time_context()
            sc = social_context(self.store, self.ns)
            tl = "（现在：" + tc["line"]
            if sc.get("gap_text"):
                tl += "；你俩" + sc["gap_text"]
            if sc.get("active_text"):
                tl += "；对方通常 " + sc["active_text"] + " 活跃"
            inj += "\n" + tl + "）"
        except Exception:
            pass
        # 天气：只在对方这轮聊到天气/冷暖/穿衣/带伞时才给（不主动当话题）
        wl = None
        if ask_weather:
            try:
                from .intel import weather_line
                wl = weather_line(self.store, self.ns)
            except Exception:
                wl = None
            if wl:
                inj += ("\n（背景：你那边" + wl +
                        "——只在对方问天气/冷暖/穿衣/带伞时拿来答，别主动拿它当话题，也别反复提）")
        # 冷战里她想先递个话（02 §14.2）：等够了 + 概率判中才给倾向；给过就记冷却
        cold_offer = False
        try:
            if self.coldwar.should_offer():
                self.coldwar.mark_offer()
                cold_offer = True
                inj += ("\n（这会儿你其实不太想绷着了：可以主动递个话——一句、短、"
                        "别提旧事、留个对方能接的话头。对方还沉着脸就别追问第二句。）")
        except Exception:
            cold_offer = False
        # 注入审计（评审 §二"已上线"的证据来源）：每轮留一条痕，之后可查库证明
        # "新注入路径真的在线上跑过"，而不是只靠单测通过。异常不影响注入。
        try:
            n_ident = sum(1 for p in kept if p["layer"] == "身份")
            n_scene = sum(1 for p in kept if p["layer"] == "情境")
            n_recent = len(kept) - n_ident - n_scene
            self.store.log_event(self.ns, "inject_context", {
                "n": len(kept), "chars": len(inj),
                "ids": [p["id"] for p in kept],
                "layers": {"身份": n_ident, "情境": n_scene, "最近": n_recent},
                "gated": gated,          # R34：本轮被三道闸挡掉的条数与原因
                "masked": masked_n[0],   # R30：本轮出站前脱敏的处数
                "q_len": len(query or ""),
                "cold_offer": cold_offer,
                "brief_len": len(locals().get("bt") or ""),
            })
        except Exception:
            pass
        # _raw 只在闸内比对用，不出内核（出站的 text 已脱敏）
        items_out = [{k: v for k, v in p.items() if k != "_raw"} for p in kept]
        return {"items": items_out, "injection": inj, "expr_hint": ex.get("hint"),
                "mood": emotion, "temperature": temp, "weather": wl,
                "cold_offer": cold_offer, "brief": (bt or None),
                "stance": stance}

    # ---------- 真引用判定（P0-2） ----------
    _CITE_STOP = ("我们", "你们", "他们", "这个", "那个", "什么", "怎么", "就是",
                  "可以", "一个", "时候", "现在", "今天", "明天", "昨天", "自己",
                  "觉得", "知道", "不是", "没有", "这么", "那么", "一样", "这样")

    @staticmethod
    def _lcs(a: str, b: str) -> str:
        """最长公共子串（滚动行 DP），文本都短，代价可忽略。"""
        if len(a) > len(b):
            a, b = b, a
        prev = [0] * (len(b) + 1)
        best, end = 0, 0
        for i in range(1, len(a) + 1):
            cur = [0] * (len(b) + 1)
            ai = a[i - 1]
            for j in range(1, len(b) + 1):
                if ai == b[j - 1]:
                    cur[j] = prev[j - 1] + 1
                    if cur[j] > best:
                        best, end = cur[j], i
            prev = cur
        return a[end - best:end] if best else ""

    @classmethod
    def _cite_evidence(cls, mem_text: str, reply: str) -> str:
        """回复里真的出现了这条记忆的实体/数字 → 返回证据串，否则 ""。
        比"整条回复与记忆的余弦相似度"保守：泛泛而谈不会把记忆加成。"""
        # 比对窗口与注入窗口是同一个常量：注入里没露出来的部分，不能要求她说出来
        mt, rt = (mem_text or "")[:C.INJECT_TEXT_CAP], (reply or "")[:600]
        if not mt or not rt:
            return ""
        lcs = cls._lcs(mt, rt)
        if len(lcs) >= C.CITE_MIN_LCS and not any(w in lcs for w in cls._CITE_STOP):
            return lcs
        # 数字/日期硬证据（两位以上数字，或明确的日期词）
        for d in re.findall(r"\d{2,}", mt):
            if d in rt:
                return d
        for d in re.findall(r"周[一二三四五六日天]|下周[一二三四五六日天]?|明天|后天|下个月", mt):
            if d in rt:
                return d
        return ""

    # ---------- 每轮观察（回写） ----------
    def observe_turn(self, user_text: str, assistant_text: str,
                     cited_ids: list = None, at=None):
        """一轮对话后回写（12.8.6 次序）：
        ① has_cause 判定 → ② 负面强度进熔断窗口 → ③ pass 轮新记忆入血海 + 五行 E 吸收
        → ④ 有因负面冲突 → 冷战状态机；用户道歉/关心 → 和解减分。"""
        at = at if at is not None else time.time()
        # R38：QQ 连发收成一轮时，user_text 是多行合并的（每个换行 = 用户的一条消息）。
        # 情绪/熔断按整轮只算一次（"一口气读完五句话"只该波动一次），但记忆必须按行各记一条，
        # 否则五句话会被压成一段 200 字的怪文本，"约了3点"这类短事实也再检索不到。
        parts = [x.strip() for x in str(user_text or "").split("\n") if x.strip()] or [str(user_text or "")]
        imp, aro, val, cluster = score_text(user_text)
        ns_neg = neg_strength(user_text)
        cause_id = self.has_cause.decide(user_text)          # ① 有因判定
        action = self.fuse.observe(ns_neg)                    # ② 熔断窗口
        # 记录最近用户回合（主动性·久未联络因子）
        self.store.set_kv(f"ns:last_user:{self.ns}", f"{at:.3f}")
        # ③a 城市自动识别：用户说到北京/成都这类地名就跟着走，不用他先配置
        try:
            from .intel import extract_city, set_city, get_city
            c = extract_city(user_text)
            if c and c != get_city(self.store, self.ns):
                set_city(self.store, self.ns, c)
        except Exception:
            pass
        # ③ 新记忆入血海（极端负面话不加剧 P，只记录审计）
        new_id = None
        # 五志 tag 先算出来：词表命中就用，没命中按 arousal/valence 兜一个弱 tag
        tag, inten, tag_src = tag_detail(user_text)
        if not tag:
            from .wuxing import weak_tag
            tag, inten, tag_src = weak_tag(aro, val)
        if action == "pass":
            if len(parts) > 1:
                for pt in parts:
                    pimp, paro, pval, pcl = score_text(pt)
                    m = self.pools.place_new(self.ns, pt[:200], pimp, paro, pval, pcl,
                                             source="user", at=at, wuxing_tag=tag)
                    if m and new_id is None:
                        new_id = m
            else:
                m = self.pools.place_new(self.ns, user_text[:200], imp, aro, val, cluster,
                                         source="user", at=at, wuxing_tag=tag)
                new_id = m if m else None
            # ③b 五行事件吸收：tag 绑到这条记忆上，事件里带 mid（否则库里查不到它属于谁）
            if tag:
                self.wuxing.on_event(tag, inten, has_cause=(cause_id is not None))
                self.store.log_event(self.ns, "wuxing_tag",
                                     {"tag": tag, "i": round(inten, 2), "src": tag_src,
                                      "mid": new_id})
            # ④ 有因负面冲突 → 冷战；和解词 → 减分
            if is_heal(user_text):
                self.coldwar.on_heal(at=at)
            elif val < 0 and cause_id is not None:
                harm = C.COLD_HARM_BASE + abs(val)
                is_deep = imp >= C.COLD_DEEP_IMP or ns_neg >= C.COLD_DEEP_IMP
                self.coldwar.on_conflict(harm, True, is_deep=is_deep, at=at)
        else:
            self.store.log_event(self.ns, "fuse_suspend_turn", {"text": user_text[:80]})
            # 熔断轮不写记忆（安全优先），但 tag 仍留痕 —— 否则"这一轮是什么情绪"
            # 永远查不到，等于审计也有洞（02 §14.3 第 3 条）。
            if tag:
                self.store.log_event(self.ns, "wuxing_tag",
                                     {"tag": tag, "i": round(inten, 2), "src": tag_src,
                                      "mid": None, "skipped": "fuse"})
        # assistant 引用记忆 → adopt（P0-2 真引用）：
        # 只认"回复里真出现了该条的实体/数字"（_cite_evidence），不再用整条余弦相似度；
        # 同一轮最多加一条，同一 id 6 小时内不重复加（治"体检 ×2 双双升督脉"）。
        cited = cited_ids or []
        if cited and assistant_text:
            best_mid, best_ev, best_score = None, "", 0
            for mid in cited:
                m = self.store.get_memory(mid)
                if not m or m["status"] != "active":
                    continue
                ev = self._cite_evidence(m["text"], assistant_text)
                if not ev:
                    continue
                score = len(ev) + (3 if re.search(r"\d", ev) else 0)
                if score > best_score:
                    best_mid, best_ev, best_score = mid, ev, score
            if best_mid is not None:
                last = self.store.get_kv(f"cite:last:{self.ns}")
                if last:
                    try:
                        lid, lat = last.split("|")
                        if lid == str(best_mid) and (time.time() - float(lat)) < C.CITE_COOLDOWN_H * 3600.0:
                            best_mid = None
                    except Exception:
                        pass
            if best_mid is not None:
                m = self.pools.on_hit(self.ns, best_mid, at)
                if m:
                    self.store.log_event(self.ns, "adopt",
                                         {"id": best_mid, "r": round(m["r"], 3),
                                          "ev": best_ev[:20]})
                    self.store.set_kv(f"cite:last:{self.ns}", f"{best_mid}|{time.time():.0f}")
        # ⑤ 表达信号回写（17 §12.8 表达涌现）：纠正降温 / 夸奖吸收碎片 / 示范种子
        self.expr.observe_signals(user_text, assistant_text or "", at)
        # ⑥ 人格条款审计（011）：回复这时候已经发出去了，这里只记账、不改写。
        # 真约束在注入层的底线段（build_context）——源头管住比事后补救有效，
        # 这里留着是为了"出过事能查到"，不是指望它兜住。
        if assistant_text:
            try:
                from .guard import check_reply
                mems = [m["text"] for m in self.store.query_active(self.ns)][:20]
                hits = check_reply(assistant_text, memories=mems)
                if hits:
                    self.store.log_event(self.ns, "guard_hit", {
                        "n": len(hits),
                        "rules": [h["rule"] for h in hits],
                        "levels": [h["level"] for h in hits],
                        "text": assistant_text[:60],
                    })
            except Exception:
                pass
        # ⑦ 偏移自动检测（011 §5.3）
        # 信号全在手上，不另采一套：val/aro 上面已经算了，长度就是回复字数，
        # 主动性配额从 proactive 现读。所以这一步不额外算任何东西。
        # 落库不在这里——DriftTracker 自己判断、自己留证（011 §7 证据闸：
        # 调用方漏接一次，这条偏移就永远查不到了）。这里只喂信号。
        try:
            daily = getattr(self.proactive, "daily_count", None)
            self.drift.observe(val=val, aro=aro,
                               reply_len=len(assistant_text or ""),
                               at=at, daily_count=daily)
        except Exception as e:
            self._note_fail("drift.observe", e)
        return {"action": action, "new_memory_id": new_id,
                "neg_strength": round(ns_neg, 3),
                "cause_id": cause_id,
                # 日配额 / 去重 / 闸门都会让这条"没进库"，但 action 仍然是 pass。
                # 只看 action 会以为写成功了——压力测试里 3000 条只入库 200 条、
                # 调用方毫无察觉，这个洞就是这么来的。new_id 为空即"没存"。
                "stored": new_id is not None}

    # ---------- 输出治理 ----------
    def govern_output(self, assistant_text: str, emotion_contributions: list = None,
                      t_hour: float = 12.0, wuxing_boost: float = None):
        """输出治理：中庸节流（单条封顶/累计节泄）→ 安全熔断（钳制 boost）→ 去我执。
        五行 emotion_boost（12.8.7）作为贡献之一并入治理链（五行层先于治理层，治理层最后闸门）。
        返回 {text, throttle, boost, omega}。"""
        contribs = list(emotion_contributions or [0.0])
        if wuxing_boost is not None:
            contribs.append(wuxing_boost)
        capped = [max(-C.THETA_JIE, min(c, C.THETA_JIE)) for c in contribs]
        total = sum(capped)
        if total > C.THETA_HE:
            total = C.THETA_HE + (total - C.THETA_HE) * 0.5
        # 去我执：|v|≥9 的贡献衰减
        contribs = [de_ego(c, 9.5) for c in contribs]
        boost = self.fuse.boost(min(total, 1.0))
        return {"text": assistant_text, "throttle_total": round(total, 4),
                "boost": round(boost, 4),
                "omega": round(omega_at(t_hour, self.embed.backend), 4)}

    # ---------- 离线巡检 ----------
    def sweep(self):
        return self.pools.sweep(self.ns)

    # ---------- 心跳 / 环境输入（021 / 022，v0.1.0） ----------
    def _cached_weather(self, city, now):
        """沿用 intel 的天气缓存（TTL 内不打网络）；过期才拉，失败沿用旧值。"""
        key = "intel:weather:%s" % self.ns
        d = None
        try:
            raw = self.store.get_kv(key)
            if raw:
                d = json.loads(raw)
        except Exception:
            d = None
        if d and d.get("city") == city and now - d.get("at", 0) < C.INTEL_WEATHER_TTL:
            return d
        try:
            from .intel import fetch_weather
            w = fetch_weather(city)
            if w and w.get("temp_c") is not None:
                w["at"] = now
                try:
                    self.store.set_kv(key, json.dumps(w, ensure_ascii=False))
                except Exception:
                    pass
                return w
        except Exception:
            pass
        return d if (d and d.get("city") == city) else None

    def _sample_env(self, now):
        """采一次环境快照。任何一步失败都降级（天气没了只是少一个源），不抛。"""
        city = ""
        try:
            from .intel import get_city
            city = get_city(self.store, self.ns) or ""
        except Exception:
            city = ""
        weather = self._cached_weather(city, now) if city else None
        pref = None
        try:
            raw = self.store.get_kv("pref:env:%s" % self.ns)
            pref = json.loads(raw) if raw else None
        except Exception:
            pref = None
        return Env.sample(now=now, city=city, weather=weather, pref=pref)

    def _write_env_memory(self, snap):
        """写一条 source='env' 的环境记忆。带日限额，防止极端天气刷库。

        没有天气数据时不写：只剩「申时 · 立冬」这种，信息量不够占一条记忆
        （用户翻起旧记忆看到"11 月 13 日申时"会觉得莫名其妙）。
        """
        if snap.get("w") in (None, "", "unknown") and snap.get("t") is None:
            return None
        day = time.strftime("%Y-%m-%d", time.localtime(snap.get("ts") or time.time()))
        key = "env:mem_day:%s" % self.ns
        cnt = 0
        try:
            raw = self.store.get_kv(key) or ""
            if raw.startswith(day + ":"):
                cnt = int(raw.split(":", 1)[1])
        except Exception:
            cnt = 0
        if cnt >= C.ENV_MEM_DAILY_CAP:
            return None
        text = Env.snapshot_text(snap)
        if not text:
            return None
        mid = self.pools.place_new(
            self.ns, text, C.ENVMEM_IMPORTANCE, C.ENVMEM_AROUSAL,
            Env.env_value(snap.get("w")), "环境",
            source=C.ENVMEM_SOURCE, at=snap.get("ts"),
            env_json=Env.to_json(snap))
        if mid:
            try:
                self.store.set_kv(key, "%s:%d" % (day, cnt + 1))
            except Exception:
                pass
        return mid

    def tick(self, now=None, force=False):
        """一步心跳：采环境 → 比对上次快照 → 注入 → 需要时写环境记忆。

        每 10 分钟一次。环境没变就只补衰减、不产出事件——这是整个机制最省的地方：
        144 次/天里真正注入的通常只有十几次。
        绝不抛异常：daemon 靠它活着，一次失败不能让它退出。
        """
        now = time.time() if now is None else now
        rep = {"at": int(now), "events": [], "memory": None, "gap": None, "err": None}
        if not C.TICK_ENABLED:
            rep["err"] = "disabled"
            return rep
        try:
            # 先结算"上次说话到现在"的缺口，再走环境。顺序不能反：
            # 否则 tick 会先把 last_at 推到 now，虽然注入仍生效，
            # 但库里再也看不出"她是刚醒过来才想起你三天没来"这件事。
            gap = self.settle_gap(now=now)
            if gap:
                rep["gap"] = [{"tag": t, "i": i, "src": s} for t, i, s in gap]
            cur = self._sample_env(now)
            prev = Env.from_json(self.store.get_kv("env:last:%s" % self.ns))
            if force:
                evs = [(cur.get("sc_wx") or "土", C.ENV_P_HOUR, "force")]
            else:
                evs = Env.to_events(cur, prev)
            for tag, it, src in evs:
                self.wuxing.tick(now=now, tag=tag, intensity=it)
                rep["events"].append({"tag": tag, "i": round(it, 4), "src": src})
            if not evs:
                self.wuxing.tick(now=now)        # 只补衰减，保证 last_at 真的推进
            if force or Env.significant(cur, prev):
                rep["memory"] = self._write_env_memory(cur)
            self.store.set_kv("env:last:%s" % self.ns, Env.to_json(cur))
            self.store.set_kv("tick:last:%s" % self.ns, "%.3f" % now)
        except Exception as e:
            self._note_fail("tick", e)
            rep["err"] = str(e)[:160]
        return rep

    def settle_gap(self, now=None):
        """重逢结算入口。CLI / daemon 直接调；引擎内部保证只结算一次。"""
        try:
            return self.wuxing.settle_gap(now=now)
        except Exception as e:
            self._note_fail("settle_gap", e)
            return []

    # ---------- 状态 / 管理 ----------
    def state(self) -> dict:
        mems = self.store.query_active(self.ns)
        by_tier = {"blood": 0, "yun": 0, "du": 0}
        for m in mems:
            by_tier[m["tier"]] = by_tier.get(m["tier"], 0) + 1
        # 五志标签覆盖率：有 tag 的记忆 / 全部记忆（02 §14.3 之后才有意义）
        all_m = self.store.query_all(self.ns)
        tagged = sum(1 for m in all_m if m.get("wuxing_tag"))
        cov = round(tagged / len(all_m), 3) if all_m else 0.0
        # 天气（30 分钟缓存，命中时不打网络）——宿主每轮本来就要拿 state，不额外起进程
        wx = None
        try:
            from .intel import weather_line
            wx = weather_line(self.store, self.ns)
        except Exception:
            wx = None
        # 偏移 / 欠着的承诺（011）：宿主每轮本来就拿 state，顺手带上就不用另开进程
        try:
            drift_state = self.drift.state()
        except Exception as e:
            self._note_fail("state.drift", e)
            drift_state = None
        try:
            du = self.due_promises()
            promise_state = {"overdue": len(du),
                             "first": (du[0]["text"] if du else None),
                             "overdue_h": (du[0]["overdue_h"] if du else None)}
        except Exception as e:
            self._note_fail("state.promise", e)
            promise_state = {"overdue": 0, "first": None, "overdue_h": None}
        return {
            "ns": self.ns,
            "pools": by_tier,
            "total_active": len(mems),
            "weather": wx,
            "persona": {"p": list(self.persona.vector),
                        "profile": self.persona.suggest_profile(),
                        "emotion_cap": round(self.persona.emotion_cap(), 3)},
            "fuse": self.fuse.status,
            "wuxing": self.wuxing.state(),
            "wuxing_tag_cov": cov,
            "coldwar": self.coldwar.snapshot(),
            "cold_offer": self.coldwar.offer_state(),
            "expression": self.expr.derive(self, noise=False),
            "drift": drift_state,
            "promises": promise_state,
            "health": self.health(),
            "backend": self.embed.backend,
        }

    # ---------- 人格涌现层查询（17 号 §12.8 / §5 / §6） ----------
    def wuxing_state(self) -> dict:
        return self.wuxing.state()

    def coldwar_state(self) -> dict:
        return self.coldwar.snapshot()

    def register_promise(self, text: str, due=None) -> dict:
        """承诺落库（011）：走 store 的事件表，**不建新表**。
        表结构迁移的风险（老库升级、迁移失败丢记忆）比"多一张表"的收益大，
        事件表已经能按 kind 查、能按时间统计，够用。

        `created_at` 在这里补：guard 的纯函数不读时钟，留空；但如果这里也不填，
        到期检查就只能拿事件的 `at` 兜底——两条来源不一致，早晚出事。
        """
        from .guard import register_promise as _rp
        p = _rp(text, due=due)
        p["created_at"] = time.time()
        try:
            self.store.log_event(self.ns, "promise", p)
        except Exception:
            pass
        return p

    def due_promises(self, now=None) -> list:
        """到期检查（011 §3 条款三**第二句**）

        规格原文是"所有'答应'必须落成可查记录、**到期未兑现时必须有一条主动说明**"。
        第一句早就有（没登记就 block），第二句一直空着：`register_promise` 存了 due，
        但没有任何代码拿它和 now 比，所以"到期"这件事在系统里永远不发生。

        三种情况判为欠着：
          - 有明确 due 且 due < now      → 已过期
          - due 是 None（"回头""过两天"）→ 从 created_at 起满 PROMISE_FORGIVE_H 小时
          - 其余（未到、已兑现）          → 不算

        按欠得最久的排前面。**调用方只取一条**——同时提三件就变成讨债信了。

        同一件承诺会有多条事件（登记一条、兑现/作废一条）。这里按 `text` 归组、
        **只认最新那条**（`recent_events` 是新→旧）：否则早就兑现的那件会因为
        旧的 open 记录还躺在表里，一直被当成"欠着"。
        """
        now = time.time() if now is None else float(now)
        out = []
        try:
            rows = self.store.recent_events(self.ns, "promise", limit=200,
                                            since=now - 90 * 86400.0)
        except Exception:
            return out
        seen = set()
        for ev in rows:
            try:
                raw = ev.get("payload")
                d = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            text = d.get("text")
            key = text.strip() if isinstance(text, str) and text.strip() else None
            if key:
                if key in seen:
                    continue      # 这件承诺已经有更新的一条了，旧记录不再重复算
                seen.add(key)     # 先占位：最新那条即使已是 kept，也要把旧的 open 挡掉
            if d.get("status") != "open":
                continue
            due = d.get("due")
            born = d.get("created_at") or ev.get("at")
            overdue = None
            if isinstance(due, (int, float)) and not isinstance(due, bool):
                if due < now:
                    overdue = now - float(due)
            elif born:
                try:
                    if (now - float(born)) >= C.PROMISE_FORGIVE_H * 3600.0:
                        overdue = now - float(born)
                except Exception:
                    overdue = None
            if overdue is None:
                continue
            out.append({
                "text": d.get("text"),
                "due": due,
                "overdue_h": round(overdue / 3600.0, 1),
                "at": ev.get("at"),
            })
        out.sort(key=lambda x: x["overdue_h"], reverse=True)
        return out

    def resolve_promise(self, text=None, kept=True, note=None) -> dict:
        """把一件承诺标成兑现（kept）或没做到（broken）。

        没有这个出口，"到期检查"会变成一个只涨不退的讨债清单：
        `register_promise` 永远写 `status="open"`，全库没有任何代码把它改掉，
        于是每件承诺过了限期都永久算"欠着"——包括早就做到的那些，
        简报会一直说「上次答应他的那件事，还欠着」。

        事件表只追加：这里不改旧记录，而是写一条同 `text` 的新事件，
        `due_promises` 按 text 取最新那条，自然就把它排除了。

        `text` 省略时取最近一条还 open 的（日常只有一件在等）。
        """
        now = time.time()
        try:
            rows = self.store.recent_events(self.ns, "promise", limit=50)
        except Exception:
            return {"ok": False, "error": "read failed"}
        target = None
        seen = set()
        for ev in rows:
            try:
                raw = ev.get("payload")
                d = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except Exception:
                continue
            if not isinstance(d, dict):
                continue
            t = d.get("text")
            key = t.strip() if isinstance(t, str) and t.strip() else None
            if key:
                if key in seen:
                    continue
                seen.add(key)
            if d.get("status") != "open":
                continue
            if text and text not in (t or ""):
                continue
            target = d
            break
        if not target:
            # 注意别用 "error" 键：cli.py 只要看到 error 就 exit 2，
            # "没有待处理的承诺"是正常的业务结果，不是失败。
            return {"ok": False, "reason": "没有待处理的承诺"}
        new = dict(target)
        new["status"] = "kept" if kept else "broken"
        new["kept"] = bool(kept)
        new["resolved_at"] = now
        if note:
            new["note"] = note
        try:
            self.store.log_event(self.ns, "promise", new)
        except Exception as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "text": new.get("text"),
                "status": new["status"], "at": now}

    def record_drift(self, dim: str, level: str, since=None, note=None,
                     evidence=None, baseline=None) -> dict:
        """偏移落库（011）：同一条路子，事件表。

        `evidence` / `baseline` 只有自动检测才带——011 §7 的证据闸要求
        "任何偏移声明必须能指到一条记录"，手工记的没有证据，自动记的有。
        """
        from .guard import record_drift as _rd
        d = _rd(dim, level, since=since, note=note)
        if evidence is not None:
            d["evidence"] = evidence
        if baseline is not None:
            d["baseline"] = baseline
        try:
            self.store.log_event(self.ns, "drift", d)
        except Exception:
            pass
        return d

    def proactive_check(self, deliver=None) -> dict:
        """主动性判定（§6）：状态驱动，无外部配额。deliver 见 Proactive.check 的记账语义。"""
        return self.proactive.check(self, deliver=deliver)

    def expression_state(self) -> dict:
        """表达风格状态（§12.8 表达涌现）：倾向 + 口癖 + 软措辞 hint。"""
        return self.expr.derive(self)

    def list_memories(self, keyword: str = "", limit: int = 20):
        mems = self.store.query_all(self.ns, limit=200)
        if keyword:
            mems = [m for m in mems if keyword in m["text"]]
        return mems[:limit]

    def forget(self, memory_id: int) -> bool:
        m = self.store.get_memory(memory_id)
        if not m or m["ns"] != self.ns:
            return False
        self.store.forget(memory_id)
        self.store.log_event(self.ns, "manual_forget", {"id": memory_id})
        return True

    def export(self):
        return {"ns": self.ns, "memories": self.store.query_all(self.ns),
                "fuse_log": self.store.recent_fuse(self.ns, 50),
                "persona": list(self.persona.vector)}

    def manual_fuse_release(self):
        return self.fuse.manual_release()
