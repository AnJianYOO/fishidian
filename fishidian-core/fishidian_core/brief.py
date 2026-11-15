# -*- coding: utf-8 -*-
"""fishidian_core.brief —— 010 状态简报编译器

设计约束（全部来自 010）：
1. 纯函数：compile_brief(snapshot) -> str，不读时钟、不读数据库、不调模型
2. 输入是 StateSnapshot，字段缺失一律 None，不补默认值
3. 输出 ≤200 字，三段：状态 / 打算 / 自觉（自觉段可省）
4. 输出里不许出现数字、参数名、"我的状态是"这类自证句式
5. 每句话必须能指回 snapshot 的某个字段

2026-11-11 修掉三处实测出来的缺陷：
  a. 器官句语义冲突 —— 旺和弱各说一句时可能说同一件事（水旺"发沉"+火弱"没劲头"）
     改为一个快照只说一个器官，取偏离中线最远的
  b. 摩擦与冷战说两遍 —— 冷战本就是摩擦的加重，改为互斥
  c. 模板拼接露缝 —— recall 存了"说周末想去看海"，模板又加"他说过："
     改为先剥引导语再拼
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional, Dict

MAX_CHARS = 200
ORGAN_DOMINANT = 0.30    # 器官偏离超过这个量，就用身体感压过情绪词（避免三句说同一件事）


# ---------------------------------------------------------------- 输入结构

@dataclass
class StateSnapshot:
    """状态快照。任何字段都可以是 None，表示"没算出来"。"""
    valence: Optional[float] = None          # -1.0 ~ 1.0，愉快度
    arousal: Optional[float] = None          # 0.0 ~ 1.0，唤醒度
    organs: Dict[str, float] = field(default_factory=dict)   # {"木":0.72,...} 五行能量
    relation_distance: Optional[float] = None   # 0.0 ~ 1.0，越近越小
    relation_friction: Optional[bool] = None    # 最近有没有摩擦
    cold_war: Optional[bool] = None             # 是否在冷战
    recall_text: Optional[str] = None           # 召回到的第一条记忆（一句话）
    recall_when: Optional[str] = None           # 那件事是什么时候（"昨晚"/"上周"）
    recall_score: Optional[float] = None        # 召回分，>=0.15 才写
    silence_hours: Optional[float] = None       # 距上次对话几小时
    hour_of_day: Optional[int] = None           # 0-23
    should_reach: Optional[bool] = None         # 想不想找他
    hold_reason: Optional[str] = None           # 想找但压住了的原因
    drift_dim: Optional[str] = None             # 偏移维度：tone/proactive/expression/silence
    drift_level: Optional[str] = None           # normal/notable/over
    drift_since: Optional[str] = None           # "今天下午"
    promise_due: Optional[str] = None           # "due"(明确到期未兑现) / "vague"(没给时间但拖久了)


# ---------------------------------------------------------------- 措辞表
# 全部集中在这里，改措辞只改这一段。每个 key 都对应 snapshot 的一个字段。

VALENCE_WORD = [
    (-0.60, "今天挺沉的"),
    (-0.25, "有点沉"),
    (0.25, "没什么起伏"),
    (0.60, "心情还行"),
    (9.99, "今天挺亮"),
]

AROUSAL_WORD = [
    (0.30, "提不起劲"),
    (0.70, "还算稳"),
    (9.99, "有点上头"),
]

# 五行旺 -> 身体感。注意：不写"木旺"，写身体。
ORGAN_HIGH = {
    "木": "有点憋着，没处说",
    "火": "心里发烫，容易急",
    "土": "闷闷的，不想动",
    "金": "绷着，放松不下来",
    "水": "有点发沉，提不起神",
}
ORGAN_LOW = {
    "木": "心里空落落的",
    "火": "没什么劲头",
    "土": "提不起力气",
    "金": "有点钝，反应慢",
    "水": "不太想动",
}

DISTANCE_WORD = [
    (0.25, "你们挺近的"),
    (0.55, "你们还行，不算远"),
    (0.80, "你们最近有点远，但没到生分"),
    (9.99, "你们之间挺僵的"),
]

DRIFT_WORD = {
    "tone": "你今天话有点冲",
    "proactive": "你今天想找他的次数有点多",
    "expression": "你今天情绪起伏比平常大",
    "silence": "你今天有点不想说话",
}

# 欠着的事（011 §3 条款三第二句）：到期未兑现要有主动说明。
# 两种措辞分开：一个是说好了哪天，一个是没定日子但一直没做——后者不该被说成"到期"。
PROMISE_WORD = {
    "due": "上次答应他的那件事，还欠着",
    "vague": "有件事答应过，一直没给他",
}


# ---------------------------------------------------------------- 工具

def _pick(table, value):
    """按阈值表选词。表格式：[(上限, 词), ...]，最后一项上限写大数。"""
    for limit, word in table:
        if value < limit:
            return word
    return table[-1][1]


def _deviation_organ(organs):
    """取偏离中线最远的那个脏腑。返回 (名字, "high"/"low", 偏离量)。

    修的是原实现的缺陷：旺和弱各说一句时，两句话可能在讲同一件事
    （水旺"有点发沉"+火弱"没什么劲头"都是提不起精神），读起来像重复。
    所以一个快照只说一个器官，取 |v-0.5| 最大的那个；并列时取旺的那侧，
    因为"旺"是当下更明显的感觉。
    """
    if not organs:
        return None, None, 0.0
    items = []
    for k, v in organs.items():
        f = _positive(v)
        if f is None:
            continue
        items.append((k, f))
    if len(items) < 2:
        return None, None, 0.0

    k, v = max(items, key=lambda kv: (abs(kv[1] - 0.5), kv[1]))
    return k, ("high" if v >= 0.5 else "low"), abs(v - 0.5)


# 她说「他说：……」时带的引导语，拼模板前要剥掉，否则会出现
# "他说过：说周末想去看海"这种叠字
_LEAD = re.compile(r"^(他说|她说|我说|说)[:：,，\s]*")


def _strip_lead(text):
    if not text:
        return ""
    return _LEAD.sub("", str(text).strip()).strip()


def _positive(v, lo=0.0, hi=1.0):
    """数值入参做合法区间收敛，防止 NaN/inf 混进文案。"""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return max(lo, min(hi, f))


# ---------------------------------------------------------------- 主体

def compile_brief(s: StateSnapshot) -> str:
    """把状态快照编译成一段给她自己看的话。最多三段，≤200 字。"""

    # ---- 第一段：状态
    parts = []

    organ, side, dev = _deviation_organ(s.organs)

    # 器官偏离明显时只说她身体上的感觉。理由：一句"没什么劲头"，
    # 比"有点沉 + 提不起劲 + 没什么劲头"三连更像人说话，后者是三个指标各出一句。
    if organ and dev >= ORGAN_DOMINANT:
        parts.append((ORGAN_HIGH if side == "high" else ORGAN_LOW).get(organ, ""))
    else:
        v = _positive(s.valence, -1.0, 1.0)
        if v is not None:
            parts.append(_pick(VALENCE_WORD, v))

        a = _positive(s.arousal)
        if a is not None:
            # 只在唤醒度明显偏离中段时才补一句，避免每句都加
            if a < 0.30 or a > 0.70:
                parts.append(_pick(AROUSAL_WORD, a))

    # 冷战本身已经说明关系状态，再叠一句距离就是同一件事说两遍
    if s.cold_war is not True:
        d = _positive(s.relation_distance)
        if d is not None:
            parts.append(_pick(DISTANCE_WORD, d))

    # 冷战和"还没过去"是同一件事的强弱两档，不能并列说两遍
    if s.cold_war is True:
        parts.append("你们还在冷着")
    elif s.relation_friction is True:
        parts.append("上次那点不愉快还没完全过去")

    body_recall = _strip_lead(s.recall_text)
    if body_recall and (s.recall_score is None or s.recall_score >= 0.15):
        when = s.recall_when or "之前"
        parts.append(f"{when}他说过：{body_recall}。你记着了")

    if s.silence_hours is not None and s.silence_hours >= 8:
        parts.append("你们挺久没说话了")

    if s.hour_of_day is not None and (s.hour_of_day >= 23 or s.hour_of_day < 6):
        parts.append("现在是夜里")

    text_state = "，".join(p for p in parts if p)
    if text_state:
        text_state = text_state + "。"

    # ---- 第二段：打算
    intent = ""
    if s.should_reach is True:
        intent = "你想找他，但别一上来就问一堆。"
        if s.hold_reason:
            intent = f"你想找他，不过{s.hold_reason}，先压着。"
    elif s.should_reach is False and s.hold_reason:
        intent = f"你有点想找他，但{s.hold_reason}，先不打扰。"
    elif s.should_reach is False:
        intent = "这会儿不打算开口，先放一放。"

    # ---- 第三段：自觉（只有偏移记录在时才出现）
    aware = ""
    if s.drift_dim in DRIFT_WORD and s.drift_level in ("notable", "over"):
        since = s.drift_since or "刚才"
        aware = f"{DRIFT_WORD[s.drift_dim]}，{since}你自己也感觉到了。"

    # ---- 欠着的（只有承诺到期检查真的扫到一条时才出现）
    # 放在打算段之后：它是一件"待办"，但不是她现在的心情。
    # 刻意只说一句、不带数字（010 §5 不许出现数值），也不带催促的口吻。
    owe = ""
    if s.promise_due in PROMISE_WORD:
        owe = f"{PROMISE_WORD[s.promise_due]}。"

    # ---- 组装
    blocks = [text_state, intent, owe, aware]
    body = "".join(b for b in blocks if b)

    if not body:
        return ""

    head = "【你现在的状态】\n"
    full = head + body
    if len(full) > MAX_CHARS:
        raise ValueError(f"简报超长 {len(full)} 字，上限 {MAX_CHARS}：{full}")
    return full
