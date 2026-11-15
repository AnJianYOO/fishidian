# -*- coding: utf-8 -*-
"""fishidian_core.expression —— 表达风格层（17 号 §12.8 表达涌现）。

三合一设计（软倾向，非硬规则）：
  ① 倾向层：状态（关系温度 / 五行情绪能量 / 冷战）→ 语气、长度、碎片、emoji、反应度
     五个软参数。只给"倾向"，允许破例；人味负向清单与互惠长度是 prompt 规则（插件注入段承担）。
  ② 表达记忆池：口癖从对话里长出来（观察 → 打分 → 分桶 → 注入 → 降温/归档），
     不预设、不复制"设计者以为的普通人"，与记忆链路同构。
  ③ 波动层：随机抖动（可关，测试确定性）+ 冷战情境修正。

设计纪律（回应"会不会把她限制死"）：
  - 注入的是倾向句 + "可以破例"，不是规则句。
  - 硬性人味靠负向清单（别总结/别列点/别端着/别一次说完），空间留给模型。
  - 口癖走记忆涌现：她说的、你夸的，长成她的习惯；你否定的，降温遗忘。
"""
from __future__ import annotations

import json
import random
import re
import time

from . import config as C

# ---------------- 表达记忆池信号 ----------------
# 夸奖信号（你夸她的某句 → 短句碎片被吸收成候选口癖）
PRAISE_RE = re.compile(r"(这句|这话|笑死|太像|有那味|像你|学你|绝了|哈哈|哈哈哈|有点东西)")
# 纠正信号（你否定的说法 → 池内相似口癖降温）
CORRECT_RE = re.compile(r"(别说|别老|别一直|别这样|少说|不要[^，。]{0,6}(说|这样)|收回|删掉|换一种|正常点|别整|别用)")
# 示范信号（你教她的口头禅 → 弱种子）
DEMO_RE = re.compile(r"(我会说|我常说|我一般说|我无语|我烦|我生气|我开心|口头禅|喜欢说|爱说|惯用语)")
QUOTE_RE = re.compile(r"[“\"]([^”\"]{2,12})[”\"]")

# 纠正常见词（用于定位池内要降温的条目，从用户消息里抽取）
COOL_KEYWORDS = ["好好好", "行行行", "好的好的", "嗯嗯", "哈哈哈", "哦哦", "服了", "无所谓", "随便", "都行", "知道了"]

# 关系温度 → 语气基调（软）
TONE_BY_TEMP = {
    "疏离": ("冷淡简短", 0.10),
    "缓和": ("平和", 0.50),
    "亲近": ("热络放松", 0.80),
}
# 主导情绪 → 语气「维度池」（不是台词表）
# 纪律：这里放的是可以组合、可以破例的倾向词，每轮按强度分档随机取一条；
# 同一状态反复取会得到不同说法，且不构成"她的口头禅"——口头禅只从对话里长（ExprPool）。
TONE_DIM = {
    "木": {"low": ["语气直一点", "有点压着火", "话里带点刺"],
           "high": ["火气上来了", "说话有点冲", "带呛"]},
    "火": {"low": ["轻快了点", "心情不错", "话有点飘"],
           "high": ["热情上头", "话密起来了", "想多说两句"]},
    "土": {"low": ["稳一点", "话不多", "慢半拍"],
           "high": ["絮叨起来", "操心劲儿上来了", "一件事反复说"]},
    "金": {"low": ["低沉些", "话少", "没什么起伏"],
           "high": ["绷着", "低落明显", "提不起劲"]},
    "水": {"low": ["软一点", "有点收着", "话说得轻"],
           "high": ["发虚", "有点慌", "话不敢说满"]},
}
# 强度分档阈值：E_max / WUXING_CAP（低于 1/12 视为没情绪，不加色）
TONE_MIN_E = 0.08
TONE_HIGH_E = 0.45


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


class ExprPool:
    """表达记忆池：kv 持久化 JSON 数组。条目：
    {id, text, emotions:[tag], sticky, hits, born_at, last_at, cooling, status}"""

    KEY = "expr:pool:{}"

    def __init__(self, store, ns):
        self.store = store
        self.ns = ns
        raw = store.get_kv(self.KEY.format(ns))
        self.items = json.loads(raw) if raw else []
        self._seq = max((it["id"] for it in self.items), default=0)

    def _save(self):
        self.store.set_kv(self.KEY.format(self.ns),
                          json.dumps(self.items, ensure_ascii=False))

    def _add(self, text, emotions, sticky, at=None):
        at = at if at is not None else time.time()
        text = (text or "").strip()
        if len(text) < 2 or len(text) > 14:
            return None
        # 相似条目不重复收：同文本直接 +hits/+sticky（强化）
        for it in self.items:
            if it["status"] == "active" and it["text"] == text:
                it["hits"] += 1
                it["sticky"] += sticky
                it["last_at"] = at
                for e in emotions:
                    if e not in it["emotions"]:
                        it["emotions"].append(e)
                self._save()
                return it
        self._seq += 1
        it = {"id": self._seq, "text": text, "emotions": list(emotions),
              "sticky": sticky, "hits": 1, "born_at": at, "last_at": at,
              "cooling": 0, "status": "active"}
        self.items.append(it)
        self._save()
        return it

    def active(self):
        return [it for it in self.items if it["status"] == "active"]

    def recall(self, tag, k=2):
        """按情绪桶检索：tag 命中 → 黏性 top k；无 tag → 全局 top k。"""
        pool = self.active()
        if tag:
            pool = [it for it in pool if tag in it["emotions"]]
        pool.sort(key=lambda it: (it["sticky"], it["hits"]), reverse=True)
        return pool[:k]

    def cool_down(self, user_text, at=None):
        """纠正信号：池内文本被用户否定 → 黏性 ×0.5；连续 COOL_LIMIT 次 → 归档。"""
        at = at if at is not None else time.time()
        targets = [w for w in COOL_KEYWORDS if w in user_text]
        hit_any = False
        for it in self.active():
            if any(w in it["text"] for w in targets) or it["text"] in user_text:
                it["sticky"] *= C.EXPR_COOL_FACTOR
                it["cooling"] += 1
                it["last_at"] = at
                hit_any = True
                if it["cooling"] >= C.EXPR_COOL_LIMIT:
                    it["status"] = "archived"
                    self.store.log_event(self.ns, "expr_archived",
                                         {"text": it["text"], "cooling": it["cooling"]})
        if hit_any:
            self._save()
        return hit_any

    def absorb(self, text, emotions, sticky, at=None):
        return self._add(text, emotions, sticky, at)

    def count(self):
        act = len(self.active())
        return {"active": act, "archived": len(self.items) - act}


class Expression:
    """表达风格层：倾向推导 + 表达记忆池观察/检索 + 波动/情境修正。"""

    def __init__(self, store, ns):
        self.store = store
        self.ns = ns
        self.pool = ExprPool(store, ns)
        self.kappa = self._load_kappa()

    # ---------- 执行补偿系数 κ（02 §14.1） ----------
    def _load_kappa(self):
        try:
            k = float(self.store.get_kv(f"expr:kappa:{self.ns}") or C.EXPR_KAPPA_B)
        except Exception:
            k = C.EXPR_KAPPA_B
        return max(C.EXPR_KAPPA_MIN, min(C.EXPR_KAPPA_MAX, k))

    def _save_kappa(self, k):
        k = max(C.EXPR_KAPPA_MIN, min(C.EXPR_KAPPA_MAX, float(k)))
        self.kappa = k
        self.store.set_kv(f"expr:kappa:{self.ns}", f"{k:.4f}")
        return k

    def _calibrate_kappa(self, ratio):
        """κ ← κ·(1 + η·(1 − 执行率))。执行率<1（模型偏短）→ κ 变大，下发更多；
        执行率>1（偏长）→ κ 变小。改的是下发量，不是内在倾向（人格不动）。"""
        k2 = self._save_kappa(self.kappa * (1.0 + C.EXPR_CAL_ETA * (1.0 - ratio)))
        self.store.log_event(self.ns, "expr_calibrate",
                             {"ratio": round(ratio, 3), "kappa": round(k2, 3)})
        return k2

    # ---------- 观察（并入 observe_turn 回写） ----------
    def observe_signals(self, user_text, assistant_text, at=None):
        """一轮对话后回写表达信号：
        ① 用户纠正 → 池内相似口癖降温/归档
        ② 用户夸奖 + 助手短回复 → 短句碎片吸收为候选口癖（情绪=当次主导）
        ③ 用户示范口头禅（引号）→ 弱种子
        ④ 长度闭环：用这一轮的实际字数反推执行率，攒够 N 轮校准 κ
        返回本次表达事件审计列表。"""
        at = at if at is not None else time.time()
        events = []
        # ① 纠正
        if CORRECT_RE.search(user_text or ""):
            if self.pool.cool_down(user_text, at):
                events.append("expr_cool")
        # ② 夸奖 + 短回复 → 碎片吸收
        tag = None
        if PRAISE_RE.search(user_text or "") and assistant_text and len(assistant_text) <= 120:
            from .wuxing import tag_of_text
            tag = tag_of_text(user_text)
            for frag in re.split(r"[。！？!?…\n]", assistant_text):
                frag = frag.strip()
                if 2 <= len(frag) <= 14:
                    it = self.pool.absorb(frag, [tag] if tag else [], C.EXPR_STICKY_PRAISE, at)
                    if it:
                        events.append({"t": "expr_absorb", "text": frag, "tag": tag})
        # ③ 示范口头禅
        if DEMO_RE.search(user_text or ""):
            for q in QUOTE_RE.findall(user_text):
                it = self.pool.absorb(q, [tag] if tag else [], C.EXPR_STICKY_DEMO, at)
                if it:
                    events.append({"t": "expr_demo", "text": q})
        # ④ 长度闭环（02 §14.1）：实际字数 / 上一轮下发要求 = 执行率
        events.extend(self._observe_length(assistant_text, at))
        return events

    def _observe_length(self, assistant_text, at):
        """攒样本，每 C.EXPR_CAL_EVERY 轮按平均执行率校一次 κ。
        只统计真实下发过字数的轮次（lenreq 缺失就跳过，不凭空算）。"""
        a = (assistant_text or "").strip()
        if not a:
            return []
        try:
            req = float(self.store.get_kv(f"expr:lenreq:{self.ns}") or 0.0)
        except Exception:
            req = 0.0
        if req <= 0:
            return []
        la = len(a)
        try:
            n = int(self.store.get_kv(f"expr:cal_n:{self.ns}") or 0) + 1
            acc = float(self.store.get_kv(f"expr:cal_acc:{self.ns}") or 0.0) + (la / req)
        except Exception:
            n, acc = 1, (la / req)
        if n >= C.EXPR_CAL_EVERY:
            ratio = acc / n
            self.store.set_kv(f"expr:cal_n:{self.ns}", "0")
            self.store.set_kv(f"expr:cal_acc:{self.ns}", "0.0000")
            self.store.log_event(self.ns, "expr_length",
                                 {"len_a": la, "len_req": round(req, 1),
                                  "ratio": round(ratio, 3), "n": n})
            k2 = self._calibrate_kappa(ratio)
            return [{"t": "expr_kappa", "ratio": round(ratio, 3), "kappa": k2, "n": n}]
        self.store.set_kv(f"expr:cal_n:{self.ns}", str(n))
        self.store.set_kv(f"expr:cal_acc:{self.ns}", f"{acc:.4f}")
        return []

    # ---------- 倾向推导 ----------
    def derive(self, gov, noise=True, rng=None):
        """状态 → 五软参数 + 口癖 + 软措辞 hint。

        noise=False 只锁数值参数（长度/碎片/emoji），语气词与口癖仍按权重随机取
        —— 保证"同一状态不吐出同一句台词"，这正是拟人需要的非确定性。
        """
        rnd = rng if rng is not None else random
        w = gov.wuxing
        cw = gov.coldwar.snapshot()
        temp = cw.get("temperature", "亲近")
        temper = TONE_BY_TEMP.get(temp, TONE_BY_TEMP["亲近"])[1]
        mood = 0.0
        if hasattr(w, "E"):
            mood = min(1.0, sum(w.E.values()) / C.WUXING_CAP)
        # 主导情绪行只由 E 决定；E 全 0 = 此刻平静，不给情绪色
        # （不再回退到 W 主行——那等于用命理底色规定语气）
        dominant, inten = None, 0.0
        if hasattr(w, "E") and w.E:
            mx = max(w.E.values())
            if mx > 1e-6:
                inten = min(1.0, mx / C.WUXING_CAP)
                dominant = max(w.E, key=lambda k: (w.E[k], k))
        # 五参数（软倾向基线 + 波动 + 五行偏移）
        # 五行只在有情绪浓度时参与：inten 归零 = 平静，不被命理底色拖着走。
        # 没有这一项时，木和土在同一温度下算出的 fragment 完全相同，
        # 提示词只能手动补一句"平时一句就够"去压——那句就是多余且和参数打架的东西。
        wxf = wxl = wxe = 0.0
        if dominant and inten > 0:
            wxf = C.EXPR_WX_FRAG.get(dominant, 0.0) * inten
            wxl = C.EXPR_WX_LEN.get(dominant, 0.0) * inten
            wxe = C.EXPR_WX_EMOJI.get(dominant, 0.0) * inten
        length = clamp(C.EXPR_LEN_B + C.EXPR_LEN_T * (temper - 0.5) * 2
                       + C.EXPR_LEN_M * (mood - 0.5) * 2 + wxl, 0.10, 0.95)
        fragment = clamp(C.EXPR_FRAG_B + C.EXPR_FRAG_T * (temper - 0.5) * 2
                         + C.EXPR_FRAG_M * (mood - 0.5) * 2 + wxf, 0.05, 0.90)
        emoji = clamp(C.EXPR_EMOJI_B + C.EXPR_EMOJI_T * (temper - 0.5) * 2 + wxe, 0.05, 0.80)
        reactive = clamp(C.EXPR_REACT_B + C.EXPR_REACT_A * mood, 0.20, 0.95)
        # ③ 波动层（随机抖动；可关）
        if noise:
            length += random.uniform(-C.EXPR_NOISE, C.EXPR_NOISE)
            fragment += random.uniform(-C.EXPR_NOISE, C.EXPR_NOISE)
            emoji += random.uniform(-C.EXPR_NOISE, C.EXPR_NOISE)
        # 情境修正：冷战 → 明显收短、收敛碎片、少 emoji
        if cw.get("cold"):
            length *= 0.6
            fragment *= 0.5
            emoji *= 0.45
        length = clamp(length, 0.05, 1.0)
        fragment = clamp(fragment, 0.02, 1.0)
        emoji = clamp(emoji, 0.0, 1.0)
        # 口癖检索（当次主导情绪桶；无情绪则全局），加权随机而非恒定 TopN
        # 执行补偿（02 §14.1）：她想说多少 L* 不动；下发要求 = L*·κ
        len_target = C.EXPR_LEN_MIN + C.EXPR_LEN_SPAN * length
        len_req = len_target * self.kappa
        self.store.set_kv(f"expr:lenreq:{self.ns}", f"{len_req:.1f}")
        quirks = self._pick_quirks(dominant, C.EXPR_QUIRK_MAX, rnd)
        tone = TONE_BY_TEMP.get(temp, TONE_BY_TEMP["亲近"])[0]
        if dominant and inten >= TONE_MIN_E:
            band = "high" if inten >= TONE_HIGH_E else "low"
            tone += "，" + rnd.choice(TONE_DIM[dominant][band])
        # 这轮分几条：必须在**每轮**单独抽，不能只给一个"话碎"形容词。
        # fragment 恒定在 0.61 时，模型会稳定地把它执行成"两刀"——用户原话
        # 「每次都是回两句，很平均」。条数本身要有长尾：多数一条，有时两条，
        # 偶尔三条，碎起来四条，这样上下浮动才看得见。
        if noise:
            p = fragment
            weights = [max(0.22, 1.0 - p * 0.55), max(0.05, p * 0.75),
                       max(0.02, p * 0.30), max(0.01, p * 0.10)]
            pieces = rnd.choices([1, 2, 3, 4], weights=weights)[0]
        else:
            pieces = 1 if fragment < 0.35 else 2
        hint = self._hint(tone, length, fragment, emoji, quirks, len_req, pieces)
        return {
            "tone": tone,
            "temperature": temp,
            "dominant": dominant,
            "length": round(length, 3),
            "len_target": round(len_target, 1),
            "len_req": round(len_req, 1),
            "kappa": round(self.kappa, 3),
            "fragment": round(fragment, 3),
            "pieces": pieces,
            "emoji": round(emoji, 3),
            "reactive": round(reactive, 3),
            "mood_energy": round(mood, 3),
            "quirks": quirks,
            "hint": hint,
            "pool": self.pool.count(),
        }

    def _pick_quirks(self, tag, k, rnd):
        """加权随机取口癖：黏性/hits 高者更容易被选中，但不独占前几名；
        tag 桶为空时退回全局池，避免某类情绪长期没有口癖可用。"""
        pool = self.pool.active()
        if not pool or k <= 0:
            return []
        if tag:
            bucketed = [it for it in pool if tag in it["emotions"]]
            if bucketed:
                pool = bucketed
        cand = sorted(pool, key=lambda it: (it["sticky"], it["hits"]), reverse=True)
        cand = cand[:max(k * 4, 6)]
        weights = [max(0.05, it["sticky"] + 0.2 * it["hits"]) for it in cand]
        picks = []
        for _ in range(min(k, len(cand))):
            it = rnd.choices(cand, weights=weights, k=1)[0]
            i = cand.index(it)
            picks.append(it["text"])
            cand.pop(i)
            weights.pop(i)
        return picks

    @staticmethod
    def _hint(tone, length, fragment, emoji, quirks, len_req=None, pieces=1):
        """软措辞：倾向句 + 口癖"分布" + 可破例。负向清单由插件注入段承担。

        红线：**不把口癖原文写进提示词**。写进去就等于规定她每轮说同一句，
        违背"口癖涌现、不强制规定"——所以这里只告诉她"你有自己的口头习惯，
        数量若干个，偶尔自然冒一个"，具体用哪句由她自己当下决定。

        len_req 是执行补偿后的下发字数（02 §14.1）。**这里给区间不给单点**：
        早先写成"（15 字上下）"，她把它当成了每轮都要逼近的硬指标，于是每条都
        落在同一个窄区间里，读起来"规整得不像人"。真人长度是分布——"嗯""行"
        就是两三个字，真要说开能到二十几字，而且同一轮里不会条条一样长。

        pieces 是**这一轮**的分条数，由 derive 每轮单独抽（带长尾）。早先只给
        一个"话碎"形容词，fragment 恒定在 0.61，她就稳定地执行成"两句"，
        于是每轮看上去一模一样。**只在空行处分段，不写"不准分"这种禁令。**
        """
        length_word = ("偏短，一两句完事" if length < 0.4 else ("适中，两三句" if length < 0.7 else "想多说几句也行，不过还是收着点"))
        n_word = ""
        if len_req:
            lo = max(2, int(round(len_req * 0.55)))
            hi = min(26, max(lo + 4, int(round(len_req * 1.6))))
            n_word = f"（这次大概 {lo}~{hi} 字，短的两三个字就够，真要说开也就二十来字，别回回都差不多长）"
        piece_word = {
            1: "这轮一句说完",
            2: "这轮两句，中间空一行",
            3: "这轮三小段，每段都短，中间空一行",
            4: "这轮碎着来，三四条都行，想到一句发一句",
        }.get(pieces, "这轮一句说完")
        emoji_word = "可以多用 emoji" if emoji > 0.55 else ("少用 emoji" if emoji < 0.3 else "emoji 看情况")
        q = (f"，你有自己的一些口头习惯（手头 {len(quirks)} 个），偶尔自然带一个就行，"
             "别每句都带、更别复读同一句") if quirks else ""
        return (f"此刻语气{tone}；长度{length_word}{n_word}；{piece_word}；{emoji_word}{q}。"
                "以上只是倾向，聊到兴头可以破例。")

    # ---------- 状态 ----------
    def state(self, gov):
        return self.derive(gov)
