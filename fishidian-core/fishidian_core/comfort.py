# -*-  coding: utf-8 -*-
"""安慰决策层（018 §六 / 用户 2026-11-11 追加）

## 要解决的问题

他连续几天都低着，她该不该主动做点什么，做多少。

**这里的做法是“加接住”，而不是“加正向反馈”。** 依据是用户已采纳的
ACL 2026《Beyond Toxic Positivity》：重度自我披露的时候，agent 的轻松乐观
构成 toxic positivity——否定对方负面情绪、破坏心理安全感。8 周纵向实验里，
带行为抑制的版本 72% 的人愿意说真实焦虑，纯积极基线只有 22%。

所以“让他开心起来”这个目标本身要拆开：人难过时朋友做的不是逗笑，是
还在那儿。往亮处带是 regulate.py 的 `xu`（轻）分支干的事，`xu_deep` 只接住。

## 三种决定

    hold  —— 只接住，不往亮处带（回复层，交给 regulate 的 xu_deep）
    touch —— 轻触：一条不带问题的消息（主动层，**当前未接，见 TODO**）
    none  —— 什么都不做

## 判据顺序是硬的，先否后肯

冷战 → 他说过“别管我” → 太久没管过（最低在场，让路） → 今天配额用完
→ 冷却中 → 他其实没“一段时间低落” → 才成立

## 参数

全部“拍的”，无实测依据（011 §5.3 已承认过这件事）。

**学习层故意没做**：现在一条真实对话都没有，学了也只是学自己的假设。
接口留在这里——等有 14 天以上真实对话再谈，见 018 §五。
"""

import time

from . import config as C

# 他说“想一个人”的几种说法。命中就到点为止，不做语义推断。
STOP_WORDS = tuple(getattr(C, "COMFORT_STOP_WORDS", (
    "别管我", "别理我", "想静静", "让我一个人", "别烦我",
)))


def detect_stop(text):
    """他是否明确说了“想一个人”。命中返回那个词，否则 None。"""
    if not text:
        return None
    for w in STOP_WORDS:
        if w in text:
            return w
    return None


def low_streak(mood_hist, low_val=None, days=None):
    """近几天是否一直低。

    `mood_hist` 是 [每日日均 val]，越靠后越近。

    只认**连续尾部**：昨天低了但前天正常，那是这一阵子的事，不是“一段时间”。
    样本不足 `days` 天直接判 False——宁可不判，也不拿两天当“一段时间”。
    """
    low_val = C.COMFORT_LOW_VAL if low_val is None else low_val
    days = C.COMFORT_LOW_DAYS if days is None else days
    if not mood_hist or len(mood_hist) < days:
        return False
    tail = list(mood_hist)[-int(days):]
    if any(v is None for v in tail):
        return False
    return all(float(v) < float(low_val) for v in tail)


def should_comfort(user_val=None, mood_hist=None, cold_war=False,
                   silent_h=None, stop_hit=None, stop_at=None,
                   last_comfort_at=None, today_count=0, now=None):
    """返回 {"mode": "hold"|"touch"|"none", "reason": str, ...}

    `user_val` 这一轮不参与判定——判的是“一段时间”，不是这一句。
    保留这个参数是为了调用方不用改签名，也为了将来做“今天特别重”的升级分支。

    全是纯值，不读库不读时钟（`now` 可注入），便于断言。
    """
    now = time.time() if now is None else float(now)

    # ① 冷战：不碰。这不是安慰的时机，是给空间的时机。
    if cold_war:
        return {"mode": "none", "reason": "冷战期间不主动安慰"}

    # ② 他说过“别管我”：尊重，直到到期。他嘴上说想一个人，就真的给一个人。
    if stop_at and float(stop_at) > now:
        left_h = round((float(stop_at) - now) / 3600.0, 1)
        return {"mode": "none", "reason": "他说过想一个人，还在尊重期（剩 %.1f 小时）" % left_h}

    # ③ 最低在场：太久没管过他，配额和冷却都得让路。
    #    这一条是底线，不可关——否则“他越沉默她越不管”，正好反了。
    if last_comfort_at and (now - float(last_comfort_at)) >= C.COMFORT_FLOOR_DAYS * 86400.0:
        if low_streak(mood_hist):
            return {"mode": "touch",
                    "reason": "太久没管过他了，就算今天配额用完了也该冒一次",
                    "floor": True}

    # ④ 今天已经接住过了
    if int(today_count or 0) >= int(C.COMFORT_DAILY_CAP):
        return {"mode": "none", "reason": "今天已经接住过了"}

    # ⑤ 冷却中
    if last_comfort_at and (now - float(last_comfort_at)) < C.COMFORT_COOL_H * 3600.0:
        left_h = round((C.COMFORT_COOL_H * 3600.0 - (now - float(last_comfort_at))) / 3600.0, 1)
        return {"mode": "none", "reason": "还在冷却，剩 %.1f 小时" % left_h}

    # ⑥ 他其实没“一段时间低落”——这一句难过是正常起伏，正常回应就行。
    #    这条挡掉的正是“我一难过她就来哄我”那种客服感。
    if not low_streak(mood_hist):
        return {"mode": "none", "reason": "还没到一段时间，正常回应即可"}

    # ⑦ 成立。再看他在不在说话
    if silent_h is not None and float(silent_h) >= C.COMFORT_SILENT_H:
        return {"mode": "touch",
                "reason": "他好一阵没开口了，轻触一下比追问好",
                "silent_h": round(float(silent_h), 1)}

    return {"mode": "hold", "reason": "他这几天一直不太对，别急着逗他"}


def hold_line(reason: str = None):
    """把 hold 决定翻成一句注入用的话。

    只说“怎么做”，不给台词——跟 regulate.py 同一个原则：倾向层不出句子，
    出了就成了念稿。
    """
    return "（这几天他一直不太对。别急着把他往亮处带，也别问“你怎么了”"
    "——那等于让他再解释一遍。接住就行，实在没话说就陪一句短的。）"


# TODO(touch)：`mode == "touch"` 现在**没有接线**。
# 它需要一条不带问题的主动消息，走 proactive.py 的发送通道。但 proactive
# 已有自己的判据和日配额，两套配额叠在一起会互相打架。在没想清楚“谁让路”
# 之前，不接。所以当前 comfort 实际只产 hold 和 none——touch 只出现在
# 返回值里，供人查，不真的发。这一点写在这里，是为了不让人以为它已经能用。
