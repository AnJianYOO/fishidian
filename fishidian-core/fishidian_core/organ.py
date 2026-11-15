# -*- coding: utf-8 -*-
"""fishidian_core.organ —— 归脏：一条记忆归到哪个脏腑

来源：008 第 4 节 + 009 第 1.2 节。
现状（18_状态层落地现状）说"归脏 / 经脉偏置 / 召回四因子"都还没进代码，
这是其中真缺的一块：现有 recall() 只按五行能量排序，没有"这条记忆属于哪个脏"。

规矩（009 第 1.2 节）：
  - 主脏唯一（ORGAN_MAIN_COUNT = 1），不许两个
  - 次脏最多 ORGAN_SUB_MAX = 2
  - 情绪强度 >= EMO_STRENGTH_MIN 走情绪判据，否则走主题
  - 都没有 → FALLBACK_ORGAN = "none"，**兜底不是"心"**（009 B3）

为什么兜底不能是"心"：心对应"喜"，把判不出归属的记忆都归到心，
等于让她对每件想不起来的事都产生正面情绪，比不归脏更假。
"""

from __future__ import annotations

WUXING = ["木", "火", "土", "金", "水"]

# 生：木生火 火生土 土生金 金生水 水生木
SHENG = {"木": "火", "火": "土", "土": "金", "金": "水", "水": "木"}
# 克：木克土 土克水 水克火 火克金 金克木
KE = {"木": "土", "土": "水", "水": "火", "火": "金", "金": "木"}

ORGAN_MAIN_COUNT = 1
ORGAN_SUB_MAX = 2
EMO_STRENGTH_MIN = 0.30
FALLBACK_ORGAN = "none"

# 被谁克（KE 的逆向），用于选次脏
_BE_KE_BY = {v: k for k, v in KE.items()}


def _clamp01(x):
    try:
        f = float(x)
    except (TypeError, ValueError):
        return 0.0
    if f != f or f in (float("inf"), float("-inf")):
        return 0.0
    return max(0.0, min(1.0, f))


def assign_organ(emo_intensity, emo_organ=None, topic_organ=None):
    """一条记忆归到哪个脏腑。

    参数：
      emo_intensity : 这条记忆的情绪强度 0~1（不是情绪值 val，是"有多强"）
      emo_organ     : 情绪指向的脏腑，可为 None
      topic_organ   : 主题指向的脏腑，可为 None

    返回 {"main": str, "subs": [str], "basis": "emotion"|"topic"|"fallback"}
    """
    emo = _clamp01(emo_intensity)

    if emo >= EMO_STRENGTH_MIN and emo_organ in WUXING:
        main, basis = emo_organ, "emotion"
    elif topic_organ in WUXING:
        main, basis = topic_organ, "topic"
    else:
        main, basis = FALLBACK_ORGAN, "fallback"

    subs = []
    if main in WUXING:
        # 次脏取「主行生的」和「克主行的」：这两个方向最能解释连带反应
        # 例如主脏是木 → 木生火（连带发急）、金克木（连带绷紧）
        for cand in (SHENG[main], _BE_KE_BY[main]):
            if cand != main and cand in WUXING and cand not in subs:
                subs.append(cand)
        subs = subs[:ORGAN_SUB_MAX]

    return {"main": main, "subs": subs, "basis": basis}
