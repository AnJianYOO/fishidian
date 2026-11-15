# -*-  coding: utf-8 -*-
"""逆体质纠偏（「情感记忆经络系统/01_理论设计.md」§6.2 第四道保险）

设计稿原话：

> 检测到用户把 AI 拖向单一极端时，**主动注入相克面**（怒极则疏泄/安抚，悲极则提振）。

现在 `wuxing.py` 只落了一半：过亢会把能量泄给「克我」那一行（380-387 行），
亏虚会从母行补（390-399 行）。**但那全是 self.E 的数字加减，没有一个字符串输出。**
也就是说能量平衡了，她说话的方式一点没变。

这个模块补的就是那一层：把「哪一行过亢 / 哪一行亏虚」翻译成**一个倾向**，
交给表达层。给的只是倾向词，不是台词——台词由表达层自己长。

------------------------------------------------------------
**一处必须偏离设计稿的地方（2026-11 外部依据）**

设计稿的处方表写「肺郁·易忧伤 → 提振开怀：温和地把人往亮处带」。
但 ACL 2026 那篇 *Beyond Toxic Positivity: Interpersonal Affect Regulation in
LLM-Based Dialogue Agents* 用 8 周纵向实验证明：用户做**重度自我披露**时，
agent 的轻松乐观会构成 toxic positivity——**否定对方的负面情绪，破坏心理安全感**。
数据显示：带行为抑制的版本 72% 的用户愿意向它倾诉真实焦虑，纯积极的基线只有 22%。

所以这里按情绪**强度**分档：

- 过亢（怒/躁，aro 高）→ 抑制亲密与欢快，收着接住（对应「疏泄」，设计稿对）
- 亏虚 + 强度低（重低落）→ **只承接，不往亮处带**（修正设计稿）
- 亏虚 + 强度中等（轻低落）→ 可以温和往亮处带（设计稿原意，保留）

这不是推翻设计稿，是给它补上「辨轻重」这一维——中医本来也讲「虚则补之」要
「缓补」「峻补」有别，一股脑提神反而伤正。
"""

from __future__ import annotations

from . import config as C

# 与 wuxing 的过/虚阈值同值，保证两边判的是同一件事
OVER = 0.80
XU = 0.20
DEEP_ARO = 0.35     # 低于这个强度 + 亏虚 = 重低落

# 过亢 → 该往哪边收（给倾向，不给句子）
_OVER_STANCE = {
    "木": ("缓一缓", "心里发烫，别跟着冲"),
    "火": ("收着说", "心口跳得快，慢下来"),
    "土": ("给个定数", "思绪太多，帮收一收"),
    "金": ("少抒情", "气憋着，别急着开解"),
    "水": ("托一把", "心里没底，先稳住"),
}

# 亏虚 + 轻 → 可以往亮处带
_XU_LIGHT = {
    "木": ("提点劲", "提不起精神"),
    "火": ("暖一点", "心是凉的"),
    "土": ("踏实点", "有点悬着"),
    "金": ("松一点", "透不过气"),
    "水": ("撑一把", "没底气"),
}

# 亏虚 + 重 → 只承接
_XU_DEEP = {
    "木": ("只接住", "整个人是散的，说什么都轻"),
    "火": ("只接住", "心口是空的，别忙着点亮"),
    "土": ("只接住", "悬着的时候，先别给答案"),
    "金": ("只接住", "沉在里面，别急着往上拉"),
    "水": ("只接住", "底下没着落，先给个稳的"),
}


def suggest_stance(organs, arousal=None):
    """把五行强度翻译成一个倾向。

    organs : {五行: 0~1 强度}，**必须是强度不是 W 权重**
             （W 是主行隔离后的权重，五者和为 1，拿它当强度会把均等状态判成全弱）
    arousal: 这一轮的情绪强度，用来分「重低落」和「轻低落」

    返回 None 或
      {"stance": "缓一缓", "reason": "...", "dim": "木", "level": "over"|"xu"|"xu_deep"}
    """
    if not organs:
        return None

    over = []
    xu = []
    for k, v in organs.items():
        if v is None:
            continue
        try:
            v = float(v)
        except Exception:
            continue
        if v >= OVER:
            over.append((k, v))
        elif v <= XU:
            xu.append((k, v))

    # 过亢优先：高张力时最需要的是先收住，不是补
    if over:
        over.sort(key=lambda t: -t[1])
        k, v = over[0]
        if k in _OVER_STANCE:
            stance, reason = _OVER_STANCE[k]
            return {"stance": stance, "reason": reason, "dim": k,
                    "level": "over", "intensity": round(v, 3)}

    if xu:
        xu.sort(key=lambda t: t[1])
        k, v = xu[0]
        aro = arousal
        try:
            aro = None if aro is None else float(aro)
        except Exception:
            aro = None
        deep = aro is not None and aro < DEEP_ARO
        if deep and k in _XU_DEEP:
            stance, reason = _XU_DEEP[k]
            return {"stance": stance, "reason": reason, "dim": k,
                    "level": "xu_deep", "intensity": round(v, 3),
                    "aro": round(aro, 3)}
        if k in _XU_LIGHT:
            stance, reason = _XU_LIGHT[k]
            return {"stance": stance, "reason": reason, "dim": k,
                    "level": "xu", "intensity": round(v, 3)}

    return None
