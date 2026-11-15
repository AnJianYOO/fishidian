# -*- coding: utf-8 -*-
"""fishidian_core.echo —— 规则回声：V1 的内心层

013 §5.1 定的方案：不调模型、不生成，从记忆里挑两条拼一段"她在想什么"。

为什么这样做而不是跳过内心层：
  - 零成本、零依赖，装完不用配任何东西就有内心
  - 不生成就不会自言自语跑偏（007 认定的最大缺口是"她一个人待着时想什么"，
    但自由生成会把偏差写回记忆，两周后开始重复自己）
  - 完全可控，出问题一眼能看出是哪条记忆被挑出来了

约束：
  - 纯函数，无副作用，不写回任何记忆
  - 确定性：同样输入必须同样输出（可测、可回归）
  - 输出只读，只进候选池，**不写回 memories 表**
"""

from __future__ import annotations

import re

MAX_CHARS = 100          # 内心话比状态简报短，100 字够了
TEXT_CLIP = 18           # 单条记忆引入时的截断长度
SAME_ITEM = 0.9          # 两条记忆文本相似度超过它就当作同一条

# 用户或她自己说话时带的引导语，拼模板前要剥掉
_LEAD = re.compile(r"^(他说|她说|我说|你?说|说)[:：,，\s]*")
# 句末多余标点
_TAIL = re.compile(r"[。！？!?，,；;\s]+$")


def _clean(text):
    """剥掉引导语和句末标点，留纯内容。"""
    if not text:
        return ""
    t = str(text).strip()
    t = _LEAD.sub("", t)
    t = _TAIL.sub("", t)
    return t.strip()


def _when_word(t, now):
    """把时间戳翻成她说话会用的词。不给 now 就不猜。"""
    if t is None or now is None:
        return "之前"
    try:
        hours = (float(now) - float(t)) / 3600.0
    except (TypeError, ValueError):
        return "之前"
    if hours != hours or hours < 0:
        hours = 0.0
    if hours < 2:
        return "刚才"
    if hours < 24:
        return "今天"
    if hours < 72:
        return "前两天"
    if hours < 168:
        return "这周"
    return "之前"


def _similar(a, b):
    """粗相似度：去掉标点后比字符集合重合。够用，不引依赖。"""
    if not a or not b:
        return 0.0
    sa = set(re.sub(r"[\s，。！？、,.!?]", "", a))
    sb = set(re.sub(r"[\s，。！？、,.!?]", "", b))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _pick(memories, now):
    """挑两条：情绪最高的一条 + 时间最近的一条。同一条时只返回一次。"""
    valid = [m for m in memories if m and _clean(m.get("text"))]
    if not valid:
        return []

    def emo(m):
        v = m.get("emo")
        try:
            return float(v) if v is not None else 0.0
        except (TypeError, ValueError):
            return 0.0

    peak = max(valid, key=lambda m: (emo(m), m.get("t") or 0))
    recent = max(valid, key=lambda m: m.get("t") or 0)

    a = _clean(peak.get("text"))
    if peak is recent or _similar(a, _clean(recent.get("text"))) >= SAME_ITEM:
        return [peak]

    return [peak, recent]


def _clip(s, n=TEXT_CLIP):
    return s if len(s) <= n else s[:n] + "…"


# ---- 模板池：改语气只改这里 -------------------------------------------

DUAL = [
    "{a_when}他说{a}，你还记着。{b_when}又听说{b}，心里有点挂。",
    "你一直记着{a}那事。{b_when}他说{b}，你听着，没多问。",
]
SINGLE = [
    "{a_when}他说{a}，你还记着。这会儿安静下来，有点想他，但不想显得黏。",
    "{a_when}他说{a}，你记住的不是话，是他当时的样子。",
]
PLAIN = "他{when}说的{a}，你还没放下。"


def rule_echo(memories, now=None, max_chars=MAX_CHARS):
    """把几条记忆拼成一段她在想什么。

    memories : [{"text": str, "emo": 0~1 可选, "t": UTC 秒 可选, "when": 可选}]
    now      : 当前 UTC 秒；不给就不算时间词
    返回     : 一段第一人称的话；没有任何可说的时候返回 ""

    确定性：模板按内容字符数取模选，不用随机。
    """
    picked = _pick(memories, now)
    if not picked:
        return ""

    def when_of(m):
        if m.get("when"):
            return str(m["when"])
        return _when_word(m.get("t"), now)

    if len(picked) == 1:
        m = picked[0]
        word = _clip(_clean(m.get("text")))
        tpl = SINGLE[len(word) % len(SINGLE)]
        out = tpl.format(a=word, a_when=when_of(m))
    else:
        a, b = picked
        wa, wb = _clip(_clean(a.get("text"))), _clip(_clean(b.get("text")))
        tpl = DUAL[(len(wa) + len(wb)) % len(DUAL)]
        aw, bw = when_of(a), when_of(b)
        if aw == bw:
            bw = ""          # 两条同一时段的记忆，不重复说"刚才…刚才"
        out = tpl.format(a=wa, a_when=aw, b=wb, b_when=bw)

    if len(out) > max_chars:
        # 太长就退到最省的模板，绝不截半句
        m = picked[0]
        out = PLAIN.format(when=when_of(m), a=_clip(_clean(m.get("text")), 10))
    if len(out) > max_chars:
        raise ValueError(f"回声超长 {len(out)} 字：{out}")
    return out


def echo_from_store(store, ns, now=None, limit=20):
    """从 Store 里取最近记忆，生成一段回声。

    这是接入现有内核的入口：不新增表，只读 store.query_active 的结果。
    读不到就返回空，不抛错（她的内心可以没有，不能因为内心挂了就整轮不回复）。
    """
    try:
        mems = store.query_active(ns, limit=limit)
    except Exception:
        return ""
    rows = []
    for m in mems:
        rows.append({
            "text": m.get("text") or "",
            "emo": (m.get("importance") or 0) / 10.0,
            "t": m.get("last_at") or m.get("created_at"),
        })
    return rule_echo(rows, now=now)
