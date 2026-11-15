# -*- coding: utf-8 -*-
"""fishidian_core.noise —— 入库前噪声过滤（系统注入文本不是记忆）。

为什么要在内核层做：插件侧过滤依赖调用方自觉，任何新入口（CLI / 桥 / 主动情报）
漏一次就写进库。放在 Pools.place_new 入口，一处生效，全链路受益。

判定口径：**贴系统标记或系统句式**才拦，不按长度/语言猜，避免误伤正常短句。
"""
from __future__ import annotations

# 系统句式前缀（宿主每轮自动拼进 prompt 的运行时内容）
NOISE_PREFIXES = (
    "Current runtime context",
    "Time sampled",
    "The working directory changed",
    "working directory changed",
    "A skill is a reusable",
    "Environment ID:",
    "Runtime: ",
    "# Tools",
    "# Available Skills",
)
# 系统标记（出现即视为注入文本）
NOISE_MARKERS = (
    "<system-reminder>",
    "<available_skills>",
    "<user_query>",
    "fishidian:memory",
    "<!-- fishidian:",
)
# 纯技能清单话术（"A skill is a reusable ..." 的变体，偶发不带标签）
NOISE_CONTAINS = (
    "is a reusable capability",
    "agent_mode/workspace/.skills",
)


def is_noise(text) -> bool:
    """True = 系统注入文本，不该当记忆。空串也算（不该入库）。"""
    t = str(text or "").strip()
    if not t:
        return True
    for p in NOISE_PREFIXES:
        if t.startswith(p):
            return True
    for m in NOISE_MARKERS:
        if m in t:
            return True
    for c in NOISE_CONTAINS:
        if c in t:
            return True
    return False
