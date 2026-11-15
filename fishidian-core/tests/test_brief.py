# -*- coding: utf-8 -*-
"""状态简报（010）的验收：基线冻结 + 四条硬约束 + 五处缺陷回归

跑法：
    python -X utf8 tests\test_brief.py
    python -m unittest tests.test_brief -v
"""

from __future__ import annotations

import os
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fishidian_core.brief import StateSnapshot, compile_brief, MAX_CHARS  # noqa: E402


def s1():
    """低落 + 有召回 + 沉默 10 小时 + 想找他但压着。"""
    return StateSnapshot(
        valence=-0.4, arousal=0.25,
        organs={"水": 0.78, "火": 0.18, "木": 0.5, "土": 0.5, "金": 0.5},
        relation_distance=0.35,
        recall_text="说周末想去看海", recall_when="昨晚", recall_score=0.5,
        silence_hours=10, hour_of_day=22,
        should_reach=True, hold_reason="怕打扰他",
    )


def s2():
    """冷战 + 器官偏弱 + 有偏移自觉。"""
    return StateSnapshot(
        valence=0.3, arousal=0.8,
        organs={"木": 0.72, "金": 0.2},
        relation_distance=0.6,
        cold_war=True, relation_friction=True,
        hour_of_day=14,
        should_reach=False,
        drift_dim="tone", drift_level="notable", drift_since="今天下午",
    )


BASE1 = "【你现在的状态】\n没什么劲头，你们还行，不算远，昨晚他说过：周末想去看海。你记着了，你们挺久没说话了。你想找他，不过怕打扰他，先压着。"
BASE2 = "【你现在的状态】\n有点钝，反应慢，你们还在冷着。这会儿不打算开口，先放一放。你今天话有点冲，今天下午你自己也感觉到了。"


class TestBaseline(unittest.TestCase):
    """冻结基线：改措辞是有意为之，先改这里再改代码。"""

    def test_base1_frozen(self):
        self.assertEqual(compile_brief(s1()), BASE1)

    def test_base2_frozen(self):
        self.assertEqual(compile_brief(s2()), BASE2)


class TestHardConstraints(unittest.TestCase):

    def test_no_digits(self):
        """简报里不许出现数字。"""
        for s in (s1(), s2()):
            self.assertIsNone(re.search(r"\d", compile_brief(s)))

    def test_no_param_names(self):
        """不许把参数名漏进给模型看的话里。"""
        out = compile_brief(s1())
        for bad in ("W_", "TAU_", "valence", "arousal", "organ", "score", "ratio"):
            self.assertNotIn(bad, out)

    def test_no_self_proof(self):
        """不许自证：不写"我的状态是……""当前参数……"。"""
        out = compile_brief(s1())
        for bad in ("我的状态是", "当前状态参数", "参数为", "数值", "阈値", "阈值"):
            self.assertNotIn(bad, out)

    def test_deterministic(self):
        self.assertEqual(compile_brief(s1()), compile_brief(s1()))

    def test_length_limit(self):
        for s in (s1(), s2()):
            self.assertLessEqual(len(compile_brief(s)), MAX_CHARS)


class TestDefectRegressions(unittest.TestCase):
    """这五个都是实测跑出来的真缺陷，改了就必须留下回归。"""

    def test_only_one_organ(self):
        """器官句只出一个：旺弱各说一句会说同一件事。"""
        s = StateSnapshot(organs={"水": 0.85, "火": 0.1, "木": 0.5, "土": 0.5, "金": 0.5})
        out = compile_brief(s)
        hits = sum(1 for w in ("发沉", "劲头", "发烫", "憋着", "闷闷", "绷着", "空落", "钝") if w in out)
        self.assertEqual(hits, 1, out)

    def test_no_triple_low_mood(self):
        """低落时不许"有点沉 + 提不起劲 + 没什么劲头"三连。"""
        s = StateSnapshot(valence=-0.5, arousal=0.2, organs={"火": 0.15, "水": 0.85})
        out = compile_brief(s)
        low_words = sum(1 for w in ("有点沉", "提不起劲", "没什么劲头") if w in out)
        self.assertLessEqual(low_words, 1, out)

    def test_coldwar_and_friction_exclusive(self):
        """冷战是摩擦的加重，不能并排说两遍。"""
        s = StateSnapshot(cold_war=True, relation_friction=True)
        out = compile_brief(s)
        self.assertIn("冷着", out)
        self.assertNotIn("不愉快", out)

    def test_coldwar_suppresses_distance(self):
        """"你们有点远"和"还在冷着"是同一件事。"""
        s = StateSnapshot(cold_war=True, relation_distance=0.9)
        out = compile_brief(s)
        self.assertIn("冷着", out)
        self.assertNotIn("僵", out)
        self.assertNotIn("有点远", out)

    def test_lead_stripped(self):
        """记忆自带"说"字时不许拼成"他说过：说……"。"""
        s = StateSnapshot(recall_text="说周末想去看海", recall_when="昨晚")
        out = compile_brief(s)
        self.assertNotIn("：说", out)
        self.assertIn("周末想去看海", out)


class TestBranches(unittest.TestCase):

    def test_empty_snapshot_returns_blank(self):
        self.assertEqual(compile_brief(StateSnapshot()), "")

    def test_all_none_no_crash(self):
        s = StateSnapshot(valence=None, arousal=None, organs={}, relation_distance=None)
        self.assertEqual(compile_brief(s), "")

    def test_nan_inf_safe(self):
        s = StateSnapshot(valence=float("nan"), arousal=float("inf"),
                          organs={"水": float("nan")}, relation_distance=float("-inf"))
        compile_brief(s)   # 只要不抛异常

    def test_recall_below_threshold_hidden(self):
        s = StateSnapshot(recall_text="从前有座山", recall_score=0.05)
        self.assertNotIn("从前有座山", compile_brief(s))

    def test_recall_above_threshold_shown(self):
        s = StateSnapshot(recall_text="从前有座山", recall_score=0.30)
        self.assertIn("从前有座山", compile_brief(s))

    def test_short_silence_not_mentioned(self):
        s = StateSnapshot(silence_hours=2)
        self.assertNotIn("挺久没说话", compile_brief(s))

    def test_long_silence_mentioned(self):
        s = StateSnapshot(silence_hours=20)
        self.assertIn("挺久没说话", compile_brief(s))

    def test_night_flag(self):
        self.assertIn("夜里", compile_brief(StateSnapshot(hour_of_day=2)))
        self.assertNotIn("夜里", compile_brief(StateSnapshot(hour_of_day=15)))

    def test_reach_with_reason(self):
        out = compile_brief(StateSnapshot(should_reach=True, hold_reason="怕打扰他"))
        self.assertIn("怕打扰他", out)

    def test_reach_without_reason(self):
        out = compile_brief(StateSnapshot(should_reach=True))
        self.assertIn("想找他", out)

    def test_not_reach(self):
        out = compile_brief(StateSnapshot(should_reach=False))
        self.assertIn("不打算开口", out)

    def test_drift_notable_shown(self):
        out = compile_brief(StateSnapshot(drift_dim="tone", drift_level="notable"))
        self.assertIn("话有点冲", out)

    def test_drift_normal_hidden(self):
        out = compile_brief(StateSnapshot(drift_dim="tone", drift_level="normal"))
        self.assertNotIn("话有点冲", out)

    def test_drift_unknown_dim_hidden(self):
        out = compile_brief(StateSnapshot(drift_dim="oops", drift_level="notable"))
        self.assertNotIn("oops", out)

    def test_title_fixed(self):
        self.assertTrue(compile_brief(s1()).startswith("【你现在的状态】"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
