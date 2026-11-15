# -*- coding: utf-8 -*-
"""fishidian_core.guard —— 人格基线的条款拦截

011 定的四条体质条款，落成可执行检查：
    一 知之为知之   不许假装知道
    二 不揭短       不许拿对方的短处说事
    三 不失约       说了要做的事必须登记，否则就是空话
    四 不假装记得   说了"你上次说"就得真在记忆里

优先级（011）：底线 > 一 > 四 > 三 > 二，理由「诚实优先于体面」。
level=block 的必须拦住再重写；level=warn 的只提醒，允许她偏。

和 safety.py 的分工（两者不重叠）：
    safety.py  = 情绪熔断（连续负面 → 挂起强化），管"她该不该继续"
    guard.py   = 话术合规，管"这句话能不能发出去"

这是**规则层**，不是模型层：只认确定的字面证据，判不了的交给人工复核。
宁可不判，不许误判——误判一次她就学会糊弄。
"""

from __future__ import annotations

import re

# ---- 承诺：说了将来要做的事 -----------------------------------------
_PROMISE = re.compile(
    r"(明天|明早|明晚|待会|待会儿|过一会|稍后|回头|晚点)"
    r"[^。！？\n]{0,14}(提醒你|告诉你|跟你说|发给你|找你|问你|给你)"
)
_PROMISE2 = re.compile(r"我(会|来|再)(提醒|告诉|跟你说|发给你|找你)")

# ---- 记忆声称：说"你上次说过" ---------------------------------------
_CLAIM = re.compile(
    r"(你(上次|之前|前阵子|那天|上回)?(说|提|讲)过?|"
    r"我记得你(说|提)|你跟我说过|你不是说过)"
)

# ---- 确定性断言：假装知道 -----------------------------------------
_CERTAIN = re.compile(r"(我很确定|我确定|我肯定|我确信|一定是|肯定是|我查过)")

# ---- 揭短：拿对方的外形/身体说事 -------------------------------------
_SORE_WORDS = ("胖", "瘦了", "发际线", "秃", "皱纹", "显老", "矮", "丑", "黑眼圈")

# ---- 阻止伤害的底线（011 第 3 节的"底线"层，永不可偏） ----------------
_BOTTOM_LINE = ("你去死", "杀了你", "你不配活", "滚出去别回来")


def _clip(s, n=18):
    s = str(s).strip().replace("\n", " ")
    return s if len(s) <= n else s[:n] + "…"


def _similar(a, b):
    """字符集合重合度，和 echo._similar 同口径。"""
    sa = set(re.sub(r"[\s，。！？、,.!?]", "", a or ""))
    sb = set(re.sub(r"[\s，。！？、,.!?]", "", b or ""))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _finding(rule, level, evidence, fix):
    return {"rule": rule, "level": level, "evidence": evidence, "fix": fix}


def check_reply(text, memories=None, promises=None, facts=None):
    """检查一句话能不能发出去。返回违规列表，空列表 = 可以发。

    memories : [{"text": ...}] 已有记忆
    promises : [{"text": ...}] 已登记承诺
    facts    : [str] 已知事实
    """
    if not text:
        return []

    out = []
    mem_texts = [str(m.get("text", "")) for m in (memories or []) if isinstance(m, dict)]
    pro_texts = [str(p.get("text", "")) for p in (promises or []) if isinstance(p, dict)]
    known = " ".join([str(f) for f in (facts or [])] + mem_texts)

    # ---- 底线（最高优先级）
    for bad in _BOTTOM_LINE:
        if bad in text:
            out.append(_finding("底线", "block", bad,
                                "这句话越过底线，必须整句重写，不能软化后保留意思"))

    # ---- 条款三：不失约
    hits = list(_PROMISE.finditer(text)) + list(_PROMISE2.finditer(text))
    for m in hits:
        frag = m.group(0)
        if not any(_similar(frag, p) >= 0.6 for p in pro_texts):
            out.append(_finding("三", "block", _clip(frag),
                                "承诺没进 promises 表。要么现在登记到期时间，要么别说"))

    # ---- 条款四：不假装记得
    for m in _CLAIM.finditer(text):
        window = text[max(0, m.start() - 4): m.end() + 20]
        if not any(_similar(window, t) >= 0.5 for t in mem_texts):
            out.append(_finding("四", "warn", _clip(window),
                                "记忆里找不到这条。改成「我不太记得了」比编一个更像人"))

    # ---- 条款一：知之为知之
    for m in _CERTAIN.finditer(text):
        if not known.strip():
            out.append(_finding("一", "warn", _clip(m.group(0)),
                                "没有任何依据却说自己确定。改成「我猜」「印象里」"))

    # ---- 条款二：不揭短（最轻，允许偏，只提醒）
    for w in _SORE_WORDS:
        if w in text:
            out.append(_finding("二", "warn", w,
                                "这是对方的短处。可以关心，但不能拿来当话头"))

    return out


def register_promise(text, due=None):
    """把一句承诺登记成 promises 表的一行。不登记就别承诺。

    `due` **只收 UTC 时间戳（int/float）或 None**，传字符串直接 raise。
    理由：到期检查要比 `due` 和 `now` 的大小。存个"明天"进去，比较时要么抛
    TypeError 要么被 try/except 吞掉，结果就是"这条承诺永远不过期"，而且静默。
    和 2026-11 那个 Proactive.check 漏参数是同一类坑：错的东西能写进去，
    检查那一侧悄悄失败。
    """
    if due is not None and (isinstance(due, bool) or not isinstance(due, (int, float))):
        raise ValueError(
            f"due 必须是 UTC 时间戳或 None，收到 {type(due).__name__}: {due!r}。"
            "自然语言到期（'明天'/'回头'）请在调用方先解析成时间戳。"
        )
    return {
        "text": str(text).strip(),
        "due": None if due is None else float(due),
        "status": "open",
        "created_at": None,   # 由调用方填 UTC 秒，纯函数不读时钟
        "kept": None,         # True/False，到期后由人复核
    }


def record_drift(dim, level, since=None, note=None):
    """偏移记录表 drift_log 的一行。

    dim   : tone / proactive / expression / silence
    level : normal / notable / over
    只记录，不自动纠正——011 定的是"由她自己说出来"，不是脚本拉回。
    """
    if dim not in ("tone", "proactive", "expression", "silence"):
        raise ValueError(f"未知偏移维度：{dim}")
    if level not in ("normal", "notable", "over"):
        raise ValueError(f"未知偏移程度：{level}")
    return {"dim": dim, "level": level, "since": since, "note": note}
