# -*- coding: utf-8 -*-
"""fishidian_core.mask —— 出站脱敏（R30 / D-027 §12.5「云端调用前本地脱敏」）。

为什么只做在出站侧：
- 库里存原文，她"记得"你住在哪、手机多少，是记忆本身，不该被删；
- 但每一轮注入的文本会随 prompt 一起发给模型（云端），原文出站 = 每轮泄漏一次。
所以：**写入存真值，注入出假值**。`/记忆` 命令读库，看到的仍是原文。

脱敏不追求"识别所有 PII"，只处理能正则确定、误伤率低的四类 + 门牌串。
认不出来的一律原样（宁可少脱，不可乱改——把"2026 年"打成"尾号 2026"更糟）。
"""
from __future__ import annotations

import re

# 手机号：1[3-9] + 9 位，前后不能紧贴数字（避免从长串里切一段出来）
RE_PHONE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
# 身份证：17 位数字 + 1 位校验位（数字或 X）
RE_IDCARD = re.compile(r"(?<!\d)(\d{6})(\d{8})(\d{3}[\dXx])(?!\d)")
# 银行卡：16–19 位连续数字（排除已按身份证命中的）
RE_BANK = re.compile(r"(?<!\d)(\d{12,19})(?!\d)")
# 邮箱
RE_EMAIL = re.compile(r"([A-Za-z0-9._%+-]{1,64})@([A-Za-z0-9.-]{1,64}\.[A-Za-z]{2,8})")
# 门牌串：至少两段"数字+号/栋/幢/单元/室/楼/层"才算地址（单段太容易误伤"3 号楼"这种普通说法之外的东西）
RE_ADDR = re.compile(r"((?:\d{1,5}(?:号|栋|幢|单元|室|楼|层)|\d{1,5}[路街道巷])){2,}")


def _phone(m):
    s = m.group(1)
    return s[:3] + "****" + s[7:]


def _idcard(m):
    return m.group(1) + "******" + m.group(3)


def _bank(m):
    s = m.group(1)
    if len(s) < 12:
        return s
    return "尾号" + s[-4:]


def _email(m):
    u, dom = m.group(1), m.group(2)
    return (u[:1] + "***" if len(u) > 1 else "***") + "@" + dom


def _addr(m):
    return "某地址"


def mask(text, hit=None):
    """返回脱敏后的文本。hit 若传入 list，会把命中的类别名 append 进去（供审计计数）。"""
    if not text:
        return text
    t = str(text)
    n = [0]

    def sub(regex, fn, name):
        nonlocal t

        def repl(m):
            n[0] += 1
            if hit is not None:
                hit.append(name)
            return fn(m)

        t = regex.sub(repl, t)

    # 顺序要紧：身份证最长且含 18 位数字，先做，否则会被银行卡规则吃掉
    sub(RE_IDCARD, _idcard, "idcard")
    sub(RE_PHONE, _phone, "phone")
    sub(RE_BANK, _bank, "bank")
    sub(RE_EMAIL, _email, "email")
    sub(RE_ADDR, _addr, "addr")
    return t


def masked_count(text) -> int:
    """只数命中次数（不产生文本），给审计用。"""
    h = []
    mask(text, hit=h)
    return len(h)
