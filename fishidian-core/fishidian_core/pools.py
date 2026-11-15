# -*- coding: utf-8 -*-
"""fishidian_core.pools —— 血海/孕育/督脉 三池、R 值、蓄泄晋升、衰减、相似合并、归档"""
from __future__ import annotations

import difflib
import math
import re

from . import config as C


def tier_of(r: float) -> str:
    """R 值 → 池层级。"""
    if r >= C.THETA_DU:
        return "du"       # 督脉·身份主线
    if r >= C.THETA_REN:
        return "yun"      # 孕育·任脉
    return "blood"        # 血海·冲脉


def half_life(tier: str) -> float:
    return {"blood": C.HL_BLOOD, "yun": C.HL_YUN, "du": C.HL_DU}.get(tier, C.HL_BLOOD)


def compute_r(imp: float, aro: float, val: float) -> float:
    """R = R_BASE + R_IMP·imp + R_ARO·A + R_VAL·|v|，钳到 [0, MAX_R]。"""
    r = C.R_BASE + C.R_IMP * imp + C.R_ARO * aro + C.R_VAL * abs(val)
    return max(0.0, min(C.MAX_R, r))


def decay(r: float, tier: str, age_h: float) -> float:
    """半衰期衰减：r *= 0.5^(age/hl)。督脉几乎不衰。"""
    hl = half_life(tier)
    return r * (0.5 ** (age_h / hl))


def adopt(r: float) -> float:
    """真命中（adopt）：+DELTA_R，上限 MAX_R。"""
    return min(C.MAX_R, r + C.DELTA_R)


def touch(r: float) -> float:
    """召回只 touch（重算时间权重），不涨 R。"""
    return r


def similar(a: str, b: str) -> bool:
    """相似合并：词集合重叠率（简单实现，bge 模式可换向量相似）。"""
    if not a or not b:
        return False
    wa = set(a.lower().replace(" ", ""))
    wb = set(b.lower().replace(" ", ""))
    if not wa or not wb:
        return False
    inter = len(wa & wb)
    return inter / max(len(wa), len(wb)) >= 0.65


def overlap(a: str, b: str) -> float:
    """字符集重叠率 inter/max(|a|,|b|)，0~1。R35 写入去重与 R34 重复闸共用这一个口径。"""
    wa = set((a or "").lower().replace(" ", ""))
    wb = set((b or "").lower().replace(" ", ""))
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / max(len(wa), len(wb))


def day_start(ts=None) -> float:
    """本地自然日零点（R35 日上限按"每天"算，跨零点重置）。"""
    import time as _t
    lt = _t.localtime(ts if ts is not None else _t.time())
    return _t.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))


def merge_candidates(mems, threshold: float = 0.65):
    """相似记忆合并候选：两两重叠 ≥ 阈值 → 返回 (主, 从) 配对。"""
    out = []
    for i in range(len(mems)):
        for j in range(i + 1, len(mems)):
            if similar(mems[i]["text"], mems[j]["text"]):
                out.append((mems[i], mems[j]))
    return out


class Pools:
    """三池模型：全部读写走 Store；本类只做机制计算与巡检。"""

    def __init__(self, store):
        self.store = store

    def _find_dup(self, ns, text, at):
        """R35：回溯窗口内找高度相似的已有记忆，返回其 id；没有返回 None。
        额外要求两条长度比例 ≥ 0.7 —— 短句被长句包含时不该判重
        （"今天累"和"今天累死了，加班到十一点还被骂"是两回事，后者信息更多）。"""
        try:
            since = at - C.WRITE_DEDUP_WIN_H * 3600.0
            nu = re.findall(r"\d+", str(text or ""))
            for row in self.store.recent_texts(ns, since):
                # 已作废的说法不能当"重复"来挡新记忆（R37 之后才有这类条）
                if row.get("status") != "active":
                    continue
                ov = overlap(row["text"], text)
                if ov < C.DEDUP_SIM:
                    continue
                la, lb = len(row["text"] or ""), len(text or "")
                if min(la, lb) / max(la, lb) < 0.7:
                    continue
                # 数字不一样 → 事实变了（"约到 3 点"改成"约到 4 点"），必须新记一条，
                # 旧条怎么处置是 R37（冲突裁决）的事，不能在这里静默吞掉。
                if re.findall(r"\d+", row["text"] or "") != nu:
                    continue
                return row["id"]
        except Exception:
            return None
        return None

    # ---------- R37 新旧陈述冲突裁决（R9 的最小切片） ----------
    def _quant(self, text):
        """抽"数字 + 单位"的量，返回 {单位: 数值}。没单位就不算量。

        为什么非加这道约束："第 1 条""第二遍"这种裸计数不是事实，数值变了也不代表
        "世界变了"。只有"3 点/2 号/500 元/3 楼"这类带单位的量，才谈得上新旧冲突。

        **序数要先摘掉**（`第1次`→不是量）：中文用阿拉伯数字写序数很常见，
        "这是我第1次去她家"→"第2次"，骨架一样、单位"次"一样、数值变了，
        若不摘就会把"两次不同的经历"判成"同一件事改了口"，旧经历被作废掉。
        """
        s = re.sub(r"第\s*\d+(?:\.\d+)?", "", str(text or ""))
        pairs = re.findall(r"(\d+(?:\.\d+)?)\s*(%s)" % "|".join(C.SUPERSEDE_UNITS), s)
        return {u: v for v, u in pairs}

    def _find_supersede(self, ns, text, at):
        """R37：同一句话只换了数字 → 返回被取代的旧条 id；否则 None。

        **判据故意窄**：同单位上数值变了 + 「去掉数字后的骨架」高度相似（difflib ratio）。
        不做语义理解，所以只认"约了 3 点"→"约了 5 点"这种同一句式改数字；
        "改到 5 点了"这种换了说法的，骨架差太远，**不取代**（两条都在库里，
        但不会同时进注入——R34 的重复闸会挡掉相似的一条）。
        宁可窄，不要错杀：误取代会让旧事实永久消失，漏取代只是偶尔多说一句。

        和 `_find_dup` 的分工：dup 管"同一句说第二遍"（数字也一致才合并，只 touch）；
        这里管"同一句话改了数字"（必须新记一条，然后把旧的作废）。
        """
        try:
            since = at - C.SUPERSEDE_WIN_H * 3600.0
            cur = self._quant(text)
            if not cur:
                return None
            skel = re.sub(r"\d+(?:\.\d+)?", "#", str(text or ""))
            for row in self.store.recent_texts(ns, since):
                if row.get("status") != "active":
                    continue          # 已作废的不再参战（支持"改回去"这种二次变更）
                other = row["text"] or ""
                old = self._quant(other)
                if not old:
                    continue
                changed = [u for u in (set(cur) & set(old)) if cur[u] != old[u]]
                if not changed:
                    continue          # 单位对得上但数值没变 → 不是冲突
                skel_old = re.sub(r"\d+(?:\.\d+)?", "#", other)
                ratio = difflib.SequenceMatcher(None, skel_old, skel).ratio()
                if ratio < C.SUPERSEDE_SIM:
                    continue
                return row["id"]
        except Exception:
            return None
        return None

    def conflicts(self, ns):
        """把取代链列出来（`cli.py conflicts` 用）。取代不是删除，随时能查、能恢复。

        除了"谁被谁取代"，还回算两样东西，用来判断**判据有没有飘**：
        - `sim`：两条去数字骨架的相似度（0.85 是门槛，越贴近门槛越可疑）
        - `units`：撞的是哪个单位、值从几改到几
        没有这两个数，`conflicts` 只能告诉你"发生了取代"，不能告诉你"这次取代像不像"。
        """
        allm = {m["id"]: m for m in self.store.query_all(ns)}
        out = []
        for m in allm.values():
            if m.get("status") != "superseded":
                continue
            nid = m.get("superseded_by")
            n = allm.get(int(nid)) if nid else None
            sim, units = None, None
            if n:
                try:
                    so = re.sub(r"\d+(?:\.\d+)?", "#", str(m["text"] or ""))
                    sn = re.sub(r"\d+(?:\.\d+)?", "#", str(n["text"] or ""))
                    sim = round(difflib.SequenceMatcher(None, so, sn).ratio(), 3)
                    qo, qn = self._quant(m["text"]), self._quant(n["text"])
                    units = {u: [qo.get(u), qn.get(u)] for u in (set(qo) | set(qn))
                             if qo.get(u) != qn.get(u)}
                except Exception:
                    sim, units = None, None
            out.append({"old_id": m["id"], "old_text": m["text"],
                        "old_at": m["born_at"],
                        "new_id": n["id"] if n else None,
                        "new_text": n["text"] if n else None,
                        "new_at": n["born_at"] if n else None,
                        "sim": sim, "units": units})
        return sorted(out, key=lambda x: -(x["old_at"] or 0))

    def conflicts_stats(self, ns, since_ts=None):
        """取代的"成色统计"：按骨架相似度分档，直接指向最该人工抽检的那批。

        为什么要分档：`SUPERSEDE_SIM = 0.85`，命中 0.99 的几乎肯定是"同一句改了数字"，
        命中 0.86 的才是判据最可能认错的地方。只给总数看不出危险，给了分档才知道看哪儿。
        02 号文档写的撤销条件是"判据认错比例 > 20%"，这个函数就是它的观测工具。
        """
        rows = self.conflicts(ns)
        # 窗口按「取代真正发生的时间」算，不按旧条 born_at。
        # 旧条可能是几个月前写的，今天才被改口——按 born_at 算会漏掉这次取代，
        # 而这个函数是 02 §25.5「判据认错比例 > 20%」撤销条件的唯一观测工具，漏了就等于没测。
        try:
            smap = self.store.supersede_at_map(ns)
        except Exception:
            smap = {}
        when = lambda r: smap.get(int(r["old_id"]), r["old_at"] or 0)  # noqa: E731
        if since_ts:
            rows = [r for r in rows if when(r) >= since_ts]
        hi = mid = lo = unk = 0
        for r in rows:
            s = r.get("sim")
            if s is None:
                unk += 1
            elif s >= 0.95:
                hi += 1
            elif s >= 0.90:
                mid += 1
            else:
                lo += 1
        return {"total": len(rows), "sim_ge_0_95": hi, "sim_0_90_0_95": mid,
                "sim_lt_0_90": lo, "unknown": unk,
                "review_targets": [r["old_id"] for r in rows
                                   if r.get("sim") is not None and r["sim"] < 0.90]}

    def retire(self, ns, now=None, dry_run=False):
        """R39 退役判据：长期没被召回 + R 已掉到地板附近的记忆 → 归档。

        为什么需要这条：只进不出的池子最后会变成垃圾场，召回被陈年碎屑淹没。
        "能删"是 2026 年的新标配（Copilot Memory 的 Dreaming、Tamanitomo 的 outbox 都带 remove）。
        注意这是**归档**不是删除：status=archived 仍可查、可恢复，只是不再参与召回与注入。
        三条同时满足才判：R < RETIRE_R、存在 ≥ RETIRE_MIN_AGE_DAYS、连续 RETIRE_QUIET_DAYS 天没被召回。
        """
        now = now if now is not None else time_now()
        cand = []
        for m in self.store.query_active(ns):
            born = float(m["born_at"] or now)
            age_d = (now - born) / 86400.0
            if age_d < C.RETIRE_MIN_AGE_DAYS:
                continue
            if float(m["r"] or 0) >= C.RETIRE_R:
                continue
            last = float(m["last_hit_at"] or m["last_at"] or born)
            quiet_d = (now - last) / 86400.0
            if quiet_d < C.RETIRE_QUIET_DAYS:
                continue
            cand.append((m["id"], round(float(m["r"] or 0), 2),
                         round(age_d, 1), round(quiet_d, 1)))
        if cand and not dry_run:
            for mid, _r, _a, _q in cand:
                self.store.update_memory(mid, status="archived")
            self.store.log_event(ns, "memory_retired", {
                "n": len(cand), "pairs": cand[:20],
                "why": f"R<{C.RETIRE_R} & quiet>{C.RETIRE_QUIET_DAYS}d & age>{C.RETIRE_MIN_AGE_DAYS}d",
            })
        return {"retired": len(cand), "candidates": cand, "dry_run": bool(dry_run)}

    def place_new(self, ns, text, imp, aro, val, cluster, source="user", visibility="private",
                  person_id=None, at=None, wuxing_tag=None, env_json=None):
        """新记忆统一入血海（高频情感脉冲·新记忆落地）；R 按特征算出，adopt 后按 R 迁池。
        血海满（cap）→ 满池泄：最低 R 软降级归档（不硬删）。
        系统注入文本（runtime context / system-reminder 等）在此拦截，不入库。"""
        from . import noise
        if noise.is_noise(text):
            self.store.log_event(ns, "noise_skip", {"text": str(text or "")[:60]})
            return None
        at2 = at if at is not None else time_now()
        # ---- R35 写入侧闸 ①：相似去重 ----
        # 同一件事说第二遍不该再长一条记忆（否则"今天好累"×5 会把血海占满、把别的事挤出去）。
        # 只 touch 已有那条的 last_at，不涨 R —— 重复陈述不是"命中"。
        dup = self._find_dup(ns, text, at2)
        if dup is not None:
            self.store.update_memory(dup, last_at=at2)
            self.store.log_event(ns, "write_dedup",
                                 {"dup_of": dup, "text": str(text or "")[:60],
                                  "ov": round(overlap(self.store.get_memory(dup)["text"], text), 3)})
            return None
        # ---- R35 写入侧闸 ②：每日上限 ----
        try:
            if self.store.count_new_since(ns, day_start(at2)) >= C.WRITE_DAILY_CAP:
                self.store.log_event(ns, "write_cap",
                                     {"cap": C.WRITE_DAILY_CAP,
                                      "text": str(text or "")[:60]})
                return None
        except Exception:
            pass
        # ---- R37 冲突裁决：先找"同一件事的旧说法" ----
        # 只查不改：新条还没确定能否在册（可能被满池挤成沉底），此时作废旧条是没依据的。
        # 总开关关掉时连查都不查：省掉掺和，也让"临时止血"这件事真的干净。
        old_conflict = self._find_supersede(ns, text, at2) if C.SUPERSEDE_ON else None
        r = compute_r(imp, aro, val)
        mems = self.store.query_active(ns)
        status = "active"
        if len(mems) >= C.CAP_BLOOD:
            # 满池：优先淘汰"R 最低且最久没被命中"的那条；但新记忆必须先证明自己比它强 30%，
            # 否则不挤人——新记忆自己沉底。避免等值互换把血海变成 FIFO 滚动窗口。
            low = min(mems, key=lambda m: (m["r"], m["last_hit_at"] or 0))
            if r >= low["r"] * C.OVERFLOW_KEEP:
                self.store.forget(low["id"])
                self.store.log_event(ns, "pool_overflow",
                                     {"victim_id": low["id"], "victim_r": low["r"]})
            else:
                status = "archived"
                self.store.log_event(ns, "weak_sink",
                                     {"r": round(r, 3), "floor_r": low["r"]})
        mid = self.store.add_memory(ns, text, imp, aro, val, cluster, "blood", r,
                                    source=source, visibility=visibility, person_id=person_id,
                                    at=at, status=status, wuxing_tag=wuxing_tag,
                                    source_quote=str(text or ""), env_json=env_json)
        # ---- R37 裁决执行：新条真的在册了，才把旧说法作废 ----
        # 沉底（archived）说明它比池里最弱的还弱，没资格代表"最新事实"，旧条保持原样。
        if old_conflict is not None and status == "active":
            # 第三道刹车：每日上限。判据一旦某个模式出错（同一句式连续改数字），
            # 没有上限就可能一夜之间作废一批真实经历；超限只留审计，不作废。
            used = 0
            try:
                used = self.store.count_events_since(ns, "write_supersede", day_start(at2))
            except Exception:
                used = 0
            if used >= C.SUPERSEDE_DAILY_CAP:
                self.store.log_event(ns, "write_supersede_blocked", {
                    "old_id": old_conflict, "new_id": mid, "used": used,
                    "cap": C.SUPERSEDE_DAILY_CAP,
                    "new_text": str(text or "")[:60],
                })
            else:
                self._supersede(ns, old_conflict, mid, text)
        return mid

    def _supersede(self, ns, old_id, new_id, new_text):
        """把旧条标成「已被取代」并留痕。不是删除：原文还在、状态可查、随时可恢复。"""
        try:
            old = self.store.get_memory(old_id) or {}
            self.store.update_memory(old_id, status="superseded", superseded_by=new_id)
            self.store.log_event(ns, "write_supersede", {
                "old_id": old_id, "new_id": new_id,
                "old_text": str(old.get("text") or "")[:60],
                "new_text": str(new_text or "")[:60],
            })
            return True
        except Exception:
            return False

    def on_hit(self, ns, mid, at=None):
        """真命中：adopt（+DELTA_R），hits+1，按新 R 迁池；返回更新后的记忆。"""
        m = self.store.get_memory(mid)
        if not m or m["status"] != "active":
            return None
        r2 = adopt(m["r"])
        tier2 = tier_of(r2)
        self.store.update_memory(mid, r=r2, tier=tier2, hits=m["hits"] + 1,
                                 last_hit_at=(at if at is not None else time_now()))
        return self.store.get_memory(mid)

    def on_recall_touch(self, mid, at=None):
        """召回 touch：更新 last_at/last_hit_at，不涨 R（Phase3 纪律）。"""
        self.store.update_memory(mid, last_hit_at=(at if at is not None else time_now()))

    def sweep(self, ns, now=None):
        """离线巡检：衰减 → 归档判定 → 久候未熟 → 相似合并 → 长尾保底 → 满池溢出。
        返回巡检报告（dict）。"""
        import time as _t
        now = now if now is not None else _t.time()
        mems = self.store.query_active(ns)
        report = {"decayed": 0, "archived": 0, "unripe": 0, "merged": 0,
                  "tail_saved": 0, "overflow": 0, "cluster_boost": 0}
        from .tail import TailGuard
        tail = TailGuard()

        for m in mems:
            # 时钟回拨 / last_at 被写成未来时间时差为负，0.5^(负天数) 会让 R 翻倍甚至涨停，
            # 而且是写库的，不是只影响排序。挡到 0 即可。
            age_h = max(0.0, (now - m["last_at"]) / 3600.0)
            r2 = decay(m["r"], m["tier"], age_h)
            # 长尾保底：重要低频（imp≥TAIL_IMP）即使久未命中也不低于 floor
            r2 = tail.protect(m["importance"], age_h, r2)
            # 衰减只降温、不再自动归档。
            # 早先这里 r2 < R_ARCHIVE 就 forget：HL_BLOOD=6h 下，任何一天多没被再提的记忆
            # 都会衰到 0.5 以下被清掉——"她失忆"的主因是这条，不是容量小。
            # 现在沉底只由容量溢出（满池 + 弱者自沉）与手动 forget 决定，衰减只影响召回排序。
            if r2 < C.R_ARCHIVE:
                r2 = C.R_ARCHIVE
                report["floored"] = report.get("floored", 0) + 1
            # 久候未熟：孕育里 R<UNRIPE 且年龄 > 21 天 → 归档
            if m["tier"] == "yun" and r2 < C.R_UNRIPE and age_h > C.UNRIPE_H:
                self.store.forget(m["id"])
                self.store.log_event(ns, "unripe", {"id": m["id"]})
                report["unripe"] += 1
                continue
            tier2 = tier_of(r2)
            if tier2 != m["tier"]:
                self.store.log_event(ns, "tier_move", {"id": m["id"], "from": m["tier"], "to": tier2})
            if r2 != m["r"]:
                self.store.update_memory(m["id"], r=r2, tier=tier2, last_at=now)
                report["decayed"] += 1

        # 簇扩散（cluster A 档）：同主题 ≥2 条的记忆互为支撑，巡检时组内各 +δ（封顶 MAX_R）。
        # 孤立簇（组内仅 1 条）不加，避免"自加固"。用衰减后的快照分组，归档/更新的不参与。
        #
        # 上限必须是"这条自己的原生 R"，不是 MAX_R。
        # 原实现 `min(MAX_R, r + δ)` 让簇扩散和衰减赛跑：同一簇每 10 分钟 +0.15，
        # 衰减在 6h 半衰期下每小时只减约 10%，于是 net 为正，R 会被一路抬到 10.00 封顶。
        # 实测（2026-11-07）64 条里已有 4 条停在 10.00，其中多条原生值只有 1.x——
        # 后果是这批条 R 值全等、召回排序失去区分度，注入被"最早的那几条"占满。
        # 改法：簇扩散只用来**抵抗衰减**（把 R 托回到它自己算出来的值），绝不越过它。
        buckets = {}
        for m in mems:
            c = m.get("cluster")
            if c:
                buckets.setdefault(c, []).append(m)
        for c, group in buckets.items():
            if len(group) < 2:
                continue
            for m in group:
                if m["status"] != "active":
                    continue
                cap = min(C.MAX_R, compute_r(m.get("importance") or 0.0,
                                             m.get("arousal") or 0.0,
                                             m.get("valence") or 0.0) * C.CLUSTER_CAP_MULT)
                if m["r"] >= cap:
                    continue   # 已经到（或历史污染超过）自己的上限，不再加
                r3 = min(cap, m["r"] + C.CLUSTER_DELTA)
                if r3 != m["r"]:
                    self.store.update_memory(m["id"], r=r3, tier=tier_of(r3))
                    report["cluster_boost"] += 1

        # 相似合并：血海（短句重复多）用高阈值 0.9，孕育/督脉用 0.65。
        # 早先只对 tier!=blood 跑，导致"今天累了"×3、"Hi"×2 永远清不掉。
        act = [m for m in mems if m["status"] == "active"]
        pairs = (merge_candidates([m for m in act if m["tier"] != "blood"], 0.65) +
                 merge_candidates([m for m in act if m["tier"] == "blood"],
                                  C.MERGE_BLOOD_THETA))
        for a, b in pairs:
            if a["status"] != "active" or b["status"] != "active":
                continue
            main_, sub_ = (a, b) if a["r"] >= b["r"] else (b, a)
            self.store.update_memory(main_["id"], r=min(C.MAX_R, main_["r"] + 0.2))
            self.store.forget(sub_["id"])
            self.store.log_event(ns, "merged", {"main": main_["id"], "sub": sub_["id"],
                                               "tier": main_["tier"]})
            report["merged"] += 1

        return report


def time_now():
    import time
    return time.time()
