# -*- coding: utf-8 -*-
"""fishidian_core.wuxing —— 五行情绪引擎 + 先天五行锚 + 文本→五志 + 有因判定（17 号 §12.8）。
公式口径 = 早期原型那版虚拟测试修正过的写法（已验证）：
  主行隔离归一化 / 克我 KE（情志相胜）/ 温度 τ 软化 / softmax 数值稳定 / 相生补母 / 相胜克我 / clamp
持久化按 ns 存 kv（W / E / count / 亏虚周期 / 锚定信息），重启接续。
"""
from __future__ import annotations

import math
import time

from . import config as C
from .scoring import bow, cos_vec, score_text

# ---------------- 查表 ----------------
WUXING = C.WUXING_WORDS  # ["木","火","土","金","水"]
IDX = {k: i for i, k in enumerate(WUXING)}
# 克我行（情志相胜）：悲胜怒=金胜木 → KE[木]=金；怒胜思=木胜土 → KE[土]=木；思胜恐=土胜水 → KE[水]=土；
# 恐胜喜=水胜火 → KE[火]=水；喜胜悲=火胜金 → KE[金]=火
KE = {"木": "金", "火": "水", "土": "木", "金": "火", "水": "土"}
SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}  # 我生


def 母行(k):
    """生 k 的行（虚则补其母）。"""
    for a, b in SHENG.items():
        if b == k:
            return a
    return None


def normalize(w):
    s = sum(w)
    return [x / s for x in w] if s > 0 else [1.0 / len(w)] * len(w)


def softmax(x):
    m = max(x)
    e = [math.exp(v - m) for v in x]
    s = sum(e)
    return [v / s for v in e]


def smooth(c):
    return [v + 1.0 for v in c]


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


# ---------------- 文本 → 五志 tag ----------------
# 五行 → 五志（《素问》：木怒 / 火喜 / 土思 / 金悲 / 水恐）→ 情绪触发词
WUXING_LEX = {
    "木": ["生气", "愤怒", "发火", "气死", "气炸", "恼火", "恨", "烦", "烦死", "委屈", "恼",
           "火大", "怒了", "气人", "离谱", "无语", "受不了", "凭什么", "讨厌", "不爽",
           "闹心", "恶心", "服了", "骂", "吵", "急死", "爆炸", "烦人",
           # 口语/网络式（高置信，不会误伤日常陈述）
           "破防", "麻了", "搞心态", "膈应", "憋屈", "炸毛", "上火", "火气", "嫌"],
    "火": ["开心", "高兴", "喜欢", "爱", "太好了", "成功", "幸福", "感动", "温暖", "兴奋",
           "激动", "满意", "通过", "拿到", "庆祝", "哈哈", "哈哈哈", "笑死", "爽", "舒服",
           "满足", "棒", "牛", "不错", "好耶", "谢谢", "嘿嘿", "好玩", "绝了", "可爱",
           "上头", "美滋滋", "开森", "乐呵", "妙啊", "爽到"],
    "土": ["担心", "操心", "焦虑", "纠结", "犹豫", "想太多", "压力", "累", "思", "惦记",
           "挂念", "困", "忙", "加班", "熬", "琢磨", "放不下",
           "发愁", "想不通", "纠结死", "顾虑", "挂心", "顾不上"],
    "金": ["难过", "伤心", "痛苦", "悲伤", "失望", "哭", "崩溃", "绝望", "孤独", "难受",
           "郁闷", "心碎", "没意思", "emo", "心疼", "低落", "丧", "空落落", "想哭",
           "心累", "好累", "累死", "摆烂", "没劲", "失落", "蔫", "闷得慌"],
    "水": ["害怕", "恐惧", "怕", "慌", "紧张", "惊吓", "不安", "担心出", "吓", "不敢",
           "焦虑不安", "发慌", "怵",
           "忐忑", "心慌", "没底", "发怵", "慌神", "悬着", "压力大"],
}

# emoji → 五志（通用情绪符号，不绑定个人习惯；权重高于文字，因为它更直接）
EMOJI_WUXING = {
    "😄": "火", "😊": "火", "😆": "火", "😁": "火", "🥰": "火", "❤": "火", "😂": "火",
    "😭": "金", "😢": "金", "💔": "金", "🥲": "金", "😔": "金", "😞": "金",
    "😡": "木", "😠": "木", "🤬": "木", "😤": "木", "🙄": "木",
    "😰": "水", "😨": "水", "😱": "水", "😖": "水",
}

# 同分裁决：负向情绪按"悲 > 怒 > 恐 > 思"，正向归"喜"
_NEG_ORDER = {"金": 0, "木": 1, "水": 2, "土": 3}


def tag_detail(text: str):
    """文本 → (五志 tag, 强度 0.25~1.0, 来源)。无命中返回 (None, 0.0, "")。

    强度不再用 arousal/10（aro 常为 1.5 → 0.15，涨不到阈值），
    改为"命中条数 + 感叹号 + emoji"的合成：短促但真情绪也能推动气机。
    """
    if not text:
        return None, 0.0, ""
    scores = {}
    for k, words in WUXING_LEX.items():
        n = sum(text.count(w) for w in words if w in text)
        if n:
            scores[k] = scores.get(k, 0) + n
    for e, k in EMOJI_WUXING.items():
        n = text.count(e)
        if n:
            scores[k] = scores.get(k, 0) + n * 1.2
    if not scores:
        return None, 0.0, ""
    _, _, val, _ = score_text(text)
    top = max(scores.values())
    tied = [k for k, v in scores.items() if v == top]
    if len(tied) > 1:
        if val < 0:
            tied.sort(key=lambda k: _NEG_ORDER.get(k, 9))
        elif val > 0 and "火" in tied:
            tied = ["火"] + [k for k in tied if k != "火"]
    tag = tied[0]
    bang = min(3, text.count("!") + text.count("！"))
    inten = clamp(0.25 + 0.15 * scores[tag] + 0.08 * bang, 0.25, 1.0)
    return tag, inten, "lex+emoji"


def tag_of_text(text: str):
    """文本 → 五志 tag（兼容旧调用）。无命中返回 None。"""
    return tag_detail(text)[0]


def weak_tag(aro, val):
    """词表没命中时，用 valence/arousal 推一个弱 tag（强度 0.25，来源 weak）。

    为什么需要：不贴标签的记忆永远无法回答"这条当时是什么情绪"，
    覆盖率会长期塌在个位数；但也不能把每句日常闲聊都染成"思"。
    所以只在这句话本身有情绪信号时兜底，中性闲聊（val≈0 且 aro 不高）不贴。

    阈值依据 score_text 的量纲：aro = |val| + 0.5，中性话 aro≈1.5。
    """
    try:
        v = float(val or 0.0)
        a = float(aro or 0.0)
    except Exception:
        return None, 0.0, ""
    if v <= -4.0:
        return "木", 0.25, "weak"     # 强负面 → 怒
    if v <= -0.35:
        return "金", 0.25, "weak"    # 低强度负面 → 悲
    if v >= 0.35:
        return "火", 0.25, "weak"    # 正面 → 喜
    if a >= 3.0:
        return "土", 0.25, "weak"    # 唤醒高但词表没命中 → 思/急
    return None, 0.0, ""


# ---------------- 先天五行锚（12.7 / 12.9.1） ----------------
# 天干五行：甲乙木 丙丁火 戊己土 庚辛金 壬癸水
TIANGAN_WUXING = ["木", "木", "火", "火", "土", "土", "金", "金", "水", "水"]
# 地支五行：子水 丑土 寅木 卯木 辰土 巳火 午火 未土 申金 酉金 戌土 亥水
DIZHI_WUXING = ["水", "土", "木", "木", "土", "火", "火", "土", "金", "金", "土", "水"]
# 方位 → 五行（部署地·补行）：东木 南火 中土 西金 北水
DIR_WUXING = {"东": "木", "南": "火", "中": "土", "西": "金", "北": "水"}

# 简易城市 → 方位（v1；未命中默认"中"=土）
CITY_DIR = {
    "北京": "北", "天津": "北", "哈尔滨": "北", "沈阳": "北", "长春": "北",
    "上海": "东", "南京": "东", "杭州": "东", "苏州": "东", "青岛": "东", "济南": "东", "合肥": "东", "福州": "东",
    "广州": "南", "深圳": "南", "厦门": "南", "长沙": "南", "南昌": "南", "南宁": "南", "海口": "南", "昆明": "南", "贵阳": "南",
    "武汉": "中", "郑州": "中", "西安": "中", "太原": "中", "石家庄": "中", "重庆": "中", "成都": "中",
    "兰州": "西", "西宁": "西", "乌鲁木齐": "西", "银川": "西",
}

_J2000 = 36524.5  # 儒略世纪（未用，保留占位）


def _jdn(ymd):
    """公历 (y,m,d) → 儒略日数（Fliegel–Van Flandern，整数版）。"""
    y, m, d = ymd
    a = (14 - m) // 12
    y2 = y + 4800 - a
    m2 = m + 12 * a - 3
    return d + (153 * m2 + 2) // 5 + 365 * y2 + y2 // 4 - y2 // 100 + y2 // 400 - 32045


def ganzhi_day(ymd):
    """公历 (y,m,d) → 日干支索引（0=甲子）。基准：1900-01-01 = 甲戌（索引 10），JDN=2415021。"""
    return (_jdn(ymd) - 2415011) % 60


def ganzhi_hour(day_index, hour):
    """日干 → 时干支索引（五鼠遁）。hour 取整小时（0-23）。
    日干 = day_index % 10；甲(0)己(5)→子时起甲(0)，乙(1)庚(6)→丙(2)，丙(2)辛(7)→戊(4)，
    丁(3)壬(8)→庚(6)，戊(4)癸(9)→壬(8)。"""
    stem = day_index % 10
    start = {0: 0, 5: 0, 1: 2, 6: 2, 2: 4, 7: 4, 3: 6, 8: 6, 4: 8, 9: 8}[stem]
    zhi = ((hour + 1) // 2) % 12  # 子(23-1)→0，丑(1-3)→1 ...
    return (start + zhi) % 60


def wuxing_of_gan(index60):
    return TIANGAN_WUXING[index60 % 10]


def wuxing_of_zhi(index60):
    return DIZHI_WUXING[index60 % 12]


def dir_of_city(city):
    if not city:
        return "中"
    for k in CITY_DIR:
        if k in city:
            return CITY_DIR[k]
    return "中"


def build_anchor(mode: str, ymd=None, hour=None, city=None, w_base=None):
    """先天锚 W_anchor（12.9.1 三档）：
    A  单日：仅出生/安装日干五行（主行）
    A+ 天地人：日（主）× 时（次）× 地（补）
    B  纯记忆涌现：无先天，W_anchor = 主人格基线（均匀）
    返回 (W_anchor, meta_dict)。"""
    wb = w_base or [0.2] * 5
    if mode == "B":
        return list(wb), {"mode": "B"}
    now = time.localtime()
    ymd = ymd or (now.tm_year, now.tm_mon, now.tm_mday)
    hour = hour if hour is not None else now.tm_hour
    city = city or ""
    day_i = ganzhi_day(ymd)
    main = wuxing_of_gan(day_i)
    if mode == "A":
        D = [0.05] * 5
        D[IDX[main]] += C.WUXING_ANCHOR_W[0]
        meta = {"mode": "A", "main": main, "ymd": ymd}
    else:  # A+
        hour_i = ganzhi_hour(day_i, hour)
        sub = wuxing_of_zhi(hour_i)
        di = dir_of_city(city)
        bu = DIR_WUXING[di]
        D = [0.05] * 5
        D[IDX[main]] += C.WUXING_ANCHOR_W[0]
        D[IDX[sub]] += C.WUXING_ANCHOR_W[1]
        D[IDX[bu]] += C.WUXING_ANCHOR_W[2]
        meta = {"mode": "A+", "main": main, "sub": sub, "bu": bu, "dir": di,
                "ymd": ymd, "hour": hour, "city": city}
    anchor = normalize([wb[i] * D[i] for i in range(5)])
    return anchor, meta


# ---------------- 五行引擎（持久化） ----------------
class WuXingEngine:
    """按 ns 持久化的五行情绪引擎。严格实现 12.8.2 公式①~⑦（vtest 修正口径）。"""

    def __init__(self, store, ns, mode="B", w_base=None):
        self.store = store
        self.ns = ns
        self.mode = mode
        self._load(mode, w_base)

    # ---- 持久化 ----
    def _load(self, mode, w_base):
        raw_w = self.store.get_kv(f"wuxing:W:{self.ns}")
        raw_e = self.store.get_kv(f"wuxing:E:{self.ns}")
        raw_c = self.store.get_kv(f"wuxing:count:{self.ns}")
        raw_d = self.store.get_kv(f"wuxing:deficit:{self.ns}")
        raw_m = self.store.get_kv(f"wuxing:meta:{self.ns}")
        raw_a = self.store.get_kv(f"wuxing:anchor:{self.ns}")
        raw_l = self.store.get_kv(f"wuxing:last_at:{self.ns}")
        # 上次事件时刻：E 的自然消退靠它算。老库没这一项时按"从现在开始计"，
        # 这样升级后不会因为 last_at=0 而永远不衰减。
        try:
            self.last_at = float(raw_l) if raw_l else time.time()
        except ValueError:
            self.last_at = time.time()
        if raw_m:
            self.mode = raw_m
        if raw_w:
            self.W = [float(x) for x in raw_w.split(",")]
            self.anchor = [float(x) for x in raw_a.split(",")] if raw_a else list(self.W)
        else:
            anchor, meta = build_anchor(self.mode, w_base=w_base)
            self.anchor = anchor
            self.W = list(anchor)
            self._save_meta(meta)
        self.E = {k: float(v) for k, v in zip(WUXING, raw_e.split(","))} if raw_e else {k: 0.0 for k in WUXING}
        self.count = {k: int(v) for k, v in zip(WUXING, raw_c.split(","))} if raw_c else {k: 0 for k in WUXING}
        self.deficit = {k: int(v) for k, v in zip(WUXING, raw_d.split(","))} if raw_d else {k: 0 for k in WUXING}
        # 锚定主行（A/A+ 模式锚死）
        self.main = IDX[max(WUXING, key=lambda k: self.anchor[IDX[k]])]
        if self.mode == "B":
            self.main = None  # B 模式无锚定行，全行可动
        # 首次落地（W 或 E 缺键）→ 立即落盘。否则在 on_event 之前，
        # 库里的 E 永远是"无键"，/五行 和可视化读到全 0，看起来像"引擎没接线"。
        # last_at 缺键同样要落盘：否则每次进程启动都把它重设成"现在"，衰减永远算成 0。
        if not raw_w or not raw_e or not raw_l:
            self._save()

    def _save_meta(self, meta):
        self.store.set_kv(f"wuxing:meta:{self.ns}", ",".join(f"{k}={v}" for k, v in meta.items()))

    def _save(self):
        self.store.set_kv(f"wuxing:W:{self.ns}", ",".join(f"{x:.8f}" for x in self.W))
        self.store.set_kv(f"wuxing:E:{self.ns}", ",".join(f"{self.E[k]:.6f}" for k in WUXING))
        self.store.set_kv(f"wuxing:count:{self.ns}", ",".join(str(self.count[k]) for k in WUXING))
        self.store.set_kv(f"wuxing:deficit:{self.ns}", ",".join(str(self.deficit[k]) for k in WUXING))
        self.store.set_kv(f"wuxing:anchor:{self.ns}", ",".join(f"{x:.8f}" for x in self.anchor))
        self.store.set_kv(f"wuxing:last_at:{self.ns}", f"{self.last_at:.0f}")

    def _decay_elapsed(self, now):
        """把 E 按"距上次事件过了多久"消退一层，返回衰减系数。
        半衰 WUXING_EMO_HALF_H 小时：12h 剩一半，24h 剩四分之一。
        这是"情绪自己会过去"的唯一实现点 —— 原来只有 on_event 里那层，
        没人说话时 E 冻住，判定就会把旧情绪当成此刻的情绪。"""
        half = C.WUXING_EMO_HALF_H
        if half <= 0 or self.last_at <= 0 or now <= self.last_at:
            return 1.0
        factor = 0.5 ** (((now - self.last_at) / 3600.0) / half)
        for k in WUXING:
            self.E[k] *= factor
        return factor

    def effective_E(self, now=None):
        """此刻的 E（只读，不写库）：把存储值按经过时间再消退一次。
        判定与展示要用"现在的情绪"；存储值由 on_event 负责补衰减。"""
        now = time.time() if now is None else now
        out = dict(self.E)
        half = C.WUXING_EMO_HALF_H
        if half > 0 and self.last_at > 0 and now > self.last_at:
            factor = 0.5 ** (((now - self.last_at) / 3600.0) / half)
            for k in WUXING:
                out[k] *= factor
        return out

    # ---- 核心 ----
    def _annealed_alpha(self, tag):
        """学习率：α(t)=α0/(1+g·t)；A/A+ 锚定主行=0。t = 累计事件数。"""
        t = sum(self.count.values())
        a0 = C.WUXING_ALPHA_BASE
        if self.main is not None and IDX[tag] == self.main:
            return 0.0
        return a0 / (1.0 + C.WUXING_ANNEAL_G * t)

    def scale(self, k):
        """情绪涨增益：clamp(主行强度/0.2, 0.5, 1.5)——防极端、不防差异。"""
        return clamp(C.WUXING_GAIN * (self.W[IDX[k]] / 0.2), 0.5, 1.5)

    def _趋近(self):
        """W 趋近 W_target（12.8.2 ①）：主行隔离归一化 + 温度 τ。"""
        m = self.main
        if m is None:
            m = IDX[max(WUXING, key=lambda k: self.count[k])] if any(self.count.values()) else 0
        wm = self.W[m]
        cnt = [self.count[k] for k in WUXING]
        sm = smooth(cnt)
        ssum = sum(sm)
        p = [v / ssum for v in sm]
        self.W_target = softmax([p[i] / C.WUXING_TAU for i in range(5)])
        for i in range(5):
            if i != m:
                tag = WUXING[i]
                a = self._annealed_alpha(tag)
                self.W[i] += a * (self.W_target[i] - self.W[i])
        rest = sum(self.W[i] for i in range(5) if i != m)
        for i in range(5):
            if i != m:
                self.W[i] *= (1.0 - wm) / rest if rest > 0 else 0.0
        self.W[m] = wm

    def on_event(self, tag, intensity, has_cause):
        """五行事件（12.8.2 ④⑤⑥⑦）：涨→衰→相胜（有因过极）/熔断计数（无因过极）→相生→趋近。"""
        if tag not in IDX:
            return
        # 先补上"距上次事件已经过去的时间"造成的消退，再走本事件的逻辑。
        # 否则 E 只在有事件时才淡，没人在说话时一直冻在旧值上。
        now = time.time()
        self._decay_elapsed(now)
        self.last_at = now
        # ④ 涨（行强涨得快）
        self.E[tag] += intensity * self.scale(tag)
        self.count[tag] += 1
        # ④ 衰（行弱衰得快）
        for k in WUXING:
            self.E[k] -= C.WUXING_LAM * (1.0 - self.W[IDX[k]]) * self.E[k]
        # ⑤ 相胜（有因过极 → 克我中和；无因过极 → 熔断计数，治理层接管）
        if self.E[tag] > C.WUXING_TH_OVER * C.WUXING_CAP:
            if has_cause:
                j = KE[tag]
                d = C.WUXING_BETA_SHENG * (self.E[tag] - C.WUXING_TH_JIE * C.WUXING_CAP)
                self.E[tag] -= d
                self.E[j] += d * 0.5
                self.store.log_event(self.ns, "wuxing_xiangsheng",
                                     {"tag": tag, "ke": j, "d": round(d, 4)})
            else:
                self.store.log_event(self.ns, "wuxing_fuse", {"tag": tag, "E": round(self.E[tag], 3)})
        # ⑥ 相生（长期亏虚 → 母行滋养）
        for k in WUXING:
            if self.E[k] < C.WUXING_TH_XU * C.WUXING_CAP:
                self.deficit[k] += 1
                if self.deficit[k] >= C.WUXING_N:
                    mom = 母行(k)
                    if mom:
                        self.E[k] += C.WUXING_BETA_SI * self.W[IDX[mom]] * (C.WUXING_TH_XU * C.WUXING_CAP - self.E[k])
                        self.store.log_event(self.ns, "wuxing_xiangsheng_bu",
                                             {"k": k, "mom": mom, "E": round(self.E[k], 4)})
            else:
                self.deficit[k] = 0
        # ① W 趋近适合值
        self._趋近()
        # 非负钳制
        for k in WUXING:
            self.E[k] = max(0.0, self.E[k])
        self._save()

    # ---- 心跳与外部输入（021 / 022，V1） ----
    def tick(self, now=None, tag=None, intensity=0.0):
        """心跳一步：补衰减 + 可选的单源注入。**不碰 count，也不趋近 W。**

        为什么不直接调 on_event：on_event 里有 `count[tag] += 1` 和 `_趋近()`。
        时辰如果走 count，一个月下来 W 的趋近目标会变成"时辰分布"而不是
        "你和她说的话"——她的性格会被钟点改写。所以心跳走独立轻量路径：
        只做"时间流逝"和"外部源加法"，W 一个字不动（022 §一 铁律）。

        参数：
          now        当前时间（默认取系统时间）
          tag        要注入的五行（None 表示只补衰减）
          intensity  注入量（已是最终值，不在这里乘 scale ——
                     外部源不该被她自己的体质放大，否则火旺的人永远更火）

        返回：本步的衰减系数与注入量，供 CLI / daemon 打日志。
        """
        now = time.time() if now is None else now
        factor = self._decay_elapsed(now)
        self.last_at = now
        added = 0.0
        if tag and tag in IDX and intensity > 0:
            added = float(intensity)
            self.E[tag] += added
        for k in WUXING:
            if self.E[k] < 0.0:
                self.E[k] = 0.0
        self._save()
        return {
            "decayed": round(factor, 6),
            "tag": tag,
            "added": round(added, 4),
            "E": {k: round(self.E[k], 4) for k in WUXING},
            "last_at": int(self.last_at),
        }

    def profile_gain(self, tag):
        """体质偏向系数：W 加权后的"她对这个情绪有多敏感"。1.0 = 常人。

        用加权平均而不是"取主导行"——W 很平时（全 0.2）算出来接近 1.0，
        天然无偏向；W 尖时才明显。避免"主导行"那种离散判断在边界处跳变。
        """
        if tag not in IDX:
            return 1.0
        col = IDX[tag]
        sw = sum(self.W) or 1.0
        g = sum(self.W[i] * C.PROFILE_MATRIX[i][col] for i in range(5)) / sw
        g = clamp(g, C.PROFILE_GAIN_MIN, C.PROFILE_GAIN_MAX)
        return 1.0 + C.PROFILE_BLEND * (g - 1.0)

    # 重逢的基础向量：(gap 上界小时, [(五行, 强度)])，按顺序取第一个命中。
    # 语义层说"思/忧/恼"，落到引擎一律五行（土=思、金=忧、木=恼）。
    _GAP_VEC = (
        (12.0,  (("土", 0.05),)),
        (24.0,  (("金", 0.10), ("土", 0.06))),
        (48.0,  (("金", 0.14), ("土", 0.08))),
        (168.0, (("金", 0.20), ("木", 0.08))),
        (None,  (("金", 0.26), ("木", 0.10))),
    )

    def settle_gap(self, now=None):
        """重逢结算：把"多久没见"换成情绪。

        这是衰减的反面。`_decay_elapsed` 只会把她清空到"很平静"，
        清空不等于想念——72h = 0.5^12，E 从 1.8 掉到 0.0004，她算出的是
        "我这三天没什么感觉"，不是"我这三天很想你"。所以必须在每轮
        开场补一次加法（022 §3.4）。

        三个坑的落点：
          只结算一次   → 写 gap:last_settle，且 last_user_at 由调用方负责更新
          关机不算冷落 → 缺口内没有 tick 记录时按 GAP_SLEEP_DISCOUNT 打折
          见面要化开   → 不在这里处理。用户首句产生的火自然相克冲淡金，
                        额外写"瞬间清零"会把真实感做没

        V1 未接：散场方式（需要 coldwar 状态），先用 1.0。见 022 §八。
        """
        now = time.time() if now is None else now
        try:
            raw = self.store.get_kv("ns:last_user:%s" % self.ns)
            last = float(raw) if raw else 0.0
        except Exception:
            last = 0.0
        if last <= 0 or now <= last:
            return []
        gap_h = (now - last) / 3600.0
        if gap_h < C.GAP_SETTLE_MIN_H:
            return []

        if C.GAP_SETTLE_ONCE:
            try:
                done = float(self.store.get_kv("gap:last_settle:%s" % self.ns) or 0)
            except Exception:
                done = 0.0
            if done >= last:
                return []       # 这段缺口已经结算过，别再难过一次

        # 关机折扣：缺口内一次 tick 都没跑过 = 她睡着了，不是被无视。
        # 用 <= last + 一个 tick 周期 判断：tick:last 恰好等于 last_user 时，
        # 说明上次说话那次刚好刚 tick 过、之后就没再跑，也该算睡。
        discount = 1.0
        try:
            tlast = float(self.store.get_kv("tick:last:%s" % self.ns) or 0)
        except Exception:
            tlast = 0.0
        if tlast <= last + C.TICK_INTERVAL_S:
            discount = C.GAP_SLEEP_DISCOUNT

        vec = self._GAP_VEC[-1][1]
        for upper, items in self._GAP_VEC:
            if upper is None or gap_h < upper:
                vec = items
                break

        total = sum(self.count.values())
        depth = clamp(0.5 + total / (2.0 * C.GAP_DEPTH_BASE),
                      C.GAP_DEPTH_MIN, C.GAP_DEPTH_MAX)

        out = []
        for tag, base in vec:
            it = base * self.profile_gain(tag) * depth * discount
            it = clamp(it, 0.0, C.GAP_MAX_INTENSITY)
            if it > 0:
                out.append((tag, round(it, 4), "absence:%.1fh" % gap_h))

        for tag, it, _src in out:
            self.tick(now=now, tag=tag, intensity=it)

        if C.GAP_SETTLE_ONCE:
            try:
                self.store.set_kv("gap:last_settle:%s" % self.ns, "%.3f" % last)
            except Exception:
                pass
        try:
            self.store.log_event(self.ns, "gap_settle", {
                "gap_h": round(gap_h, 2),
                "asleep": discount < 1.0,
                "depth": round(depth, 3),
                "items": out,
            })
        except Exception:
            pass
        return out

    # ---- 对外接口（12.8.7 单向映射） ----
    def emotion_boost(self):
        """emotion_boost = clamp(Σ(E_k·W_k)/cap − 0.5, −0.2, +0.5)。治理层最后闸门。"""
        s = sum(self.E[k] * self.W[IDX[k]] for k in WUXING) / C.WUXING_CAP
        return clamp(s - 0.5, C.WUXING_BOOST_LO, C.WUXING_BOOST_HI)

    def state(self):
        return {
            "mode": self.mode,
            "W": [round(x, 4) for x in self.W],
            "anchor": [round(x, 4) for x in self.anchor],
            "main": WUXING[self.main] if self.main is not None else "记忆牵引中",
            "E": {k: round(v, 4) for k, v in self.E.items()},
            "count": dict(self.count),
            "W_target": [round(x, 4) for x in getattr(self, "W_target", [0.2] * 5)],
            "emotion_boost": round(self.emotion_boost(), 4),
        }


# ---------------- 有因判定器（12.8.6 v1 规则） ----------------
# 单字级 bow 的假相似来自高频功能字（了/我/很/都…），有因判定前先过滤停用字；
# 实体/主题重叠：内容 bigram（两端非停用字、非时间词）共现 ≥1 即主题命中，
# 或内容单字共现 ≥3（整句引用级强相关）。"拿不准一律按无因"（安全优先）。
import re as _re

STOP_WORDS = set("的了我你他她它是在有和就都很也这那不 要会还么吧啊吗呢去来上下中小个们把被让给对从到说但且又于与及或并其而更最只虽则若因为")
TIME_BIGRAMS = {"今天", "明天", "昨天", "前天", "后天", "早上", "上午", "中午", "下午",
                "晚上", "凌晨", "刚才", "马上", "现在", "已经", "正在", "以后", "以前"}


class HasCause:
    """v1：本轮文本与近期候选记忆做内容 token 共现判定 → 命中 cause_id。
    同一轮内缓存判定结果。"""

    def __init__(self, store, ns, engine_embed=None):
        self.store = store
        self.ns = ns
        self.cache = {}

    @staticmethod
    def _content_tokens(text):
        chars = _re.findall(r"[\u4e00-\u9fff]", str(text).lower())
        singles = {c for c in chars if c not in STOP_WORDS}
        bigs = {
            chars[i] + chars[i + 1]
            for i in range(len(chars) - 1)
            if chars[i] not in STOP_WORDS and chars[i + 1] not in STOP_WORDS
            and chars[i] + chars[i + 1] not in TIME_BIGRAMS
        }
        return singles, bigs

    def _candidates(self, at=None):
        at = at if at is not None else time.time()
        win = C.WUXING_CAUSE_WIN_H * 3600.0
        mems = self.store.query_all(self.ns, limit=200)
        return [m for m in mems if m["status"] == "active" and at - m["born_at"] <= win]

    def decide(self, text):
        """返回 cause_id（str|None）。"""
        if not text:
            return None
        if text in self.cache:
            return self.cache[text]
        cause = None
        s1, b1 = self._content_tokens(text)
        for m in self._candidates():
            s2, b2 = self._content_tokens(m["text"])
            if len(s1 & s2) >= 3 or len(b1 & b2) >= 1:
                cause = str(m["id"])
                break
        self.cache[text] = cause
        return cause
