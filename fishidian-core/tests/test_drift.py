# -*- coding: utf-8 -*-
"""偏移自动检测 / 逆体质纠偏 / 承诺到期检查（2026-11-11 第二批）

跑法：
    python -X utf8 tests\test_drift.py

这里最要紧的是几条**负例**：基线本来就低的人不该被判偏，本来就话少的
角色不该被判"不想说话"。如果这几条挂了，说明实现退回了"拿绝对值阈值管她"
——那正是 011 §5.3 明令禁止的东西。
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fishidian_core import Store, Governor  # noqa: E402
from fishidian_core import config as C  # noqa: E402
from fishidian_core.drift import (  # noqa: E402
    _med, _slope, detect,
    judge_tone, judge_silence, judge_expression, judge_proactive,
    DriftTracker,
)
from fishidian_core.regulate import suggest_stance  # noqa: E402
from fishidian_core.guard import register_promise  # noqa: E402
from fishidian_core.brief import StateSnapshot, compile_brief  # noqa: E402


def sig(vals=None, lens=None, aros=None):
    """把三个序列拼成 tracker 吃的信号列表（短的那个补 None）。"""
    vals = vals or []
    lens = lens or []
    aros = aros or []
    n = max(len(vals), len(lens), len(aros))
    out = []
    for i in range(n):
        out.append({
            "at": 1700000000 + i,
            "val": vals[i] if i < len(vals) else None,
            "aro": aros[i] if i < len(aros) else None,
            "len": lens[i] if i < len(lens) else None,
        })
    return out


def tmp_gov():
    tmp = tempfile.mkdtemp()
    return Governor("ns_drift", store=Store(os.path.join(tmp, "d.db")))


# ---------------------------------------------------------------- 轨迹统计

class TestTrajectoryStats(unittest.TestCase):

    def test_median_odd(self):
        self.assertEqual(_med([3, 1, 2]), 2.0)

    def test_median_even(self):
        self.assertEqual(_med([1, 2, 3, 4]), 2.5)

    def test_median_beats_mean_on_outlier(self):
        # 一条 -1.0 的极端冲突不该把"平时 +0.5"的基线拉走
        self.assertGreater(_med([0.5] * 9 + [-9.0]), 0.0)

    def test_slope_negative(self):
        self.assertLess(_slope([10, 8, 6, 4, 2]), 0)

    def test_slope_flat(self):
        self.assertEqual(round(_slope([5, 5, 5]), 6), 0.0)


# ---------------------------------------------------------------- 四个判据

class TestJudgeTone(unittest.TestCase):

    def test_hits_when_all_recent_cold(self):
        s = sig(vals=[0.2] * 14 + [-0.2] * 6, lens=[20] * 20, aros=[0.5] * 20)
        h = judge_tone(s)
        self.assertIsNotNone(h)
        self.assertEqual(h["dim"], "tone")
        self.assertEqual(h["level"], "notable")
        self.assertLess(h["delta"], 0)

    def test_negative_low_baseline_is_normal(self):
        """负例：她本来就在 -0.5，一直 -0.5 不该判偏（否则就退回绝对值阈值了）。"""
        s = sig(vals=[-0.5] * 20, lens=[20] * 20, aros=[0.5] * 20)
        self.assertIsNone(judge_tone(s))

    def test_short_window_is_silent(self):
        s = sig(vals=[0.2, -0.9], lens=[20, 20], aros=[0.5, 0.5])
        self.assertIsNone(judge_tone(s))

    def test_evidence_is_attached(self):
        s = sig(vals=[0.2] * 14 + [-0.2] * 6, lens=[20] * 20, aros=[0.5] * 20)
        h = judge_tone(s)
        self.assertEqual(len(h["evidence"]), C.DRIFT_TONE_LIMIT)
        self.assertIn("val", h["evidence"][0])


class TestJudgeSilence(unittest.TestCase):

    def test_hits_when_shorter_than_both(self):
        s = sig(vals=[0.0] * 14, lens=[30] * 10 + [5] * 4, aros=[0.5] * 14)
        h = judge_silence(s)
        self.assertIsNotNone(h)
        self.assertEqual(h["dim"], "silence")

    def test_negative_always_short_is_normal(self):
        """负例：一个天生话就不超过 5 字的角色，连续 4 轮 5 字不该被判"不想说话"。"""
        s = sig(vals=[0.0] * 14, lens=[5] * 14, aros=[0.5] * 14)
        self.assertIsNone(judge_silence(s))


class TestJudgeExpression(unittest.TestCase):

    def test_hits_when_both_drop(self):
        s = sig(vals=[0.0] * 16, lens=[30] * 10 + [10] * 6, aros=[0.6] * 10 + [0.1] * 6)
        h = judge_expression(s)
        self.assertIsNotNone(h)
        self.assertEqual(h["dim"], "expression")

    def test_only_one_drop_is_normal(self):
        # 只变短了但情绪强度没掉 → 不判（只掉一个说明不了是"淡"，可能只是忙）
        s = sig(vals=[0.0] * 16, lens=[30] * 10 + [10] * 6, aros=[0.6] * 16)
        self.assertIsNone(judge_expression(s))


class TestJudgeProactive(unittest.TestCase):

    def test_over_cap(self):
        self.assertIsNotNone(judge_proactive(C.DRIFT_PROACTIVE_CAP + 1))

    def test_at_cap_is_normal(self):
        self.assertIsNone(judge_proactive(C.DRIFT_PROACTIVE_CAP))

    def test_none_is_normal(self):
        self.assertIsNone(judge_proactive(None))


class TestDetect(unittest.TestCase):

    def test_needs_base_window(self):
        s = sig(vals=[-0.9] * 5, lens=[2] * 5, aros=[0.1] * 5)
        self.assertEqual(detect(s), [])

    def test_collects_hits(self):
        s = sig(vals=[0.2] * 14 + [-0.2] * 6, lens=[30] * 14 + [3] * 6,
                aros=[0.6] * 14 + [0.1] * 6)
        dims = {h["dim"] for h in detect(s)}
        self.assertIn("tone", dims)
        self.assertIn("silence", dims)


# ---------------------------------------------------------------- 状态机

class TestTracker(unittest.TestCase):

    def setUp(self):
        self.g = tmp_gov()

    def _feed(self, n, val, aro=0.5, ln=30):
        last = None
        for i in range(n):
            last = self.g.drift.observe(val=val, aro=aro, reply_len=ln,
                                        at=1700000000 + i, daily_count=0)
        return last

    def test_enter_once_then_silent(self):
        self.assertIsNone(self._feed(20, 0.2))
        ev = self._feed(6, -0.2)   # 第 6 轮才凑满"连续 6 轮"
        self.assertIsNotNone(ev)
        self.assertEqual(ev["event"], "enter")
        self.assertEqual(ev["dim"], "tone")
        # 持续期间刻意不重复记录——否则简报每轮都在说"你今天话有点冲"
        self.assertIsNone(self._feed(3, -0.2))

    def test_recover_after_clean_streak(self):
        self._feed(20, 0.2)
        self._feed(6, -0.2)
        ev = None
        for i in range(8):
            ev = self.g.drift.observe(val=0.2, aro=0.5, reply_len=30,
                                      at=1700000100 + i, daily_count=0)
            if ev and ev["event"] == "recover":
                break
        self.assertIsNotNone(ev)
        self.assertEqual(ev["event"], "recover")
        self.assertEqual(ev["dim"], "tone")

    def test_no_judgement_before_base_window(self):
        self.assertIsNone(self._feed(5, -0.9))

    def test_drift_lands_in_event_table(self):
        self.g.register_promise("回头陪他去看海")
        self._feed(20, 0.2)
        self._feed(6, -0.2)
        rows = self.g.store.recent_events(self.g.ns, "drift", limit=5)
        self.assertTrue(rows)
        self.assertIn("tone", rows[0]["payload"])


# ---------------------------------------------------------------- 逆体质纠偏

class TestStance(unittest.TestCase):

    def test_over_urges_to_hold_back(self):
        r = suggest_stance({"木": 0.9, "火": 0.3, "土": 0.2, "金": 0.1, "水": 0.1})
        self.assertEqual(r["dim"], "木")
        self.assertEqual(r["level"], "over")
        self.assertEqual(r["stance"], "缓一缓")

    def test_deep_low_does_not_cheer_up(self):
        """修正设计稿：重低落时"往亮处带"就是 toxic positivity，只该承接。"""
        r = suggest_stance({"金": 0.05, "木": 0.5, "火": 0.5, "土": 0.5, "水": 0.5},
                           arousal=0.1)
        self.assertEqual(r["level"], "xu_deep")
        self.assertEqual(r["stance"], "只接住")

    def test_light_low_may_cheer_up(self):
        r = suggest_stance({"金": 0.05, "木": 0.5, "火": 0.5, "土": 0.5, "水": 0.5},
                           arousal=0.6)
        self.assertEqual(r["level"], "xu")
        self.assertEqual(r["stance"], "松一点")

    def test_balanced_has_no_stance(self):
        self.assertIsNone(suggest_stance({k: 0.5 for k in "木火土金水"}))

    def test_empty_has_no_stance(self):
        self.assertIsNone(suggest_stance({}))


# ---------------------------------------------------------------- 承诺到期

class TestPromiseDue(unittest.TestCase):

    def setUp(self):
        self.g = tmp_gov()

    def test_string_due_raises(self):
        """存个"明天"进去会让到期检查永远判不过期，而且静默 —— 必须直接拒。"""
        with self.assertRaises(ValueError):
            register_promise("明天陪他去看海", due="明天")

    def test_bool_due_raises(self):
        with self.assertRaises(ValueError):
            register_promise("陪他去看海", due=True)

    def test_numeric_due_ok(self):
        p = register_promise("陪他去看海", due=1800000000.0)
        self.assertEqual(p["due"], 1800000000.0)
        self.assertEqual(p["created_at"], None)   # 纯函数不读时钟

    def test_governor_fills_created_at(self):
        p = self.g.register_promise("陪他去看海")
        self.assertIsInstance(p["created_at"], float)

    def test_overdue_by_due(self):
        now = time.time()
        self.g.register_promise("陪他去看海", due=now - 3600)
        dues = self.g.due_promises(now=now)
        self.assertEqual(len(dues), 1)
        self.assertGreater(dues[0]["overdue_h"], 0)

    def test_not_yet_due_is_quiet(self):
        now = time.time()
        self.g.register_promise("陪他去看海", due=now + 3600)
        self.assertEqual(self.g.due_promises(now=now), [])

    def test_vague_overdue_by_age(self):
        now = time.time()
        p = self.g.register_promise("回头帮他修电脑")
        # 把它"变老"：直接改事件里的 created_at 不现实，改用 forgive 小时数为 0 判
        dues = self.g.due_promises(now=now + C.PROMISE_FORGIVE_H * 3600.0 + 60)
        self.assertEqual(len(dues), 1)
        self.assertIsNone(dues[0]["due"])

    def test_vague_still_fresh_is_quiet(self):
        self.g.register_promise("回头帮他修电脑")
        self.assertEqual(self.g.due_promises(), [])

    def test_kept_promise_drops_out(self):
        """兑现之后就不该再提——判据是"这件还算不算欠着"，不是"表里有几条 open"。"""
        now = time.time()
        self.g.register_promise("陪他去看海", due=now - 60)
        self.assertEqual(len(self.g.due_promises(now=now)), 1)
        r = self.g.resolve_promise("看海", kept=True)
        self.assertTrue(r["ok"])
        self.assertEqual(self.g.due_promises(now=now), [])

    def test_broken_promise_drops_out(self):
        now = time.time()
        self.g.register_promise("陪他去看海", due=now - 60)
        self.g.resolve_promise("看海", kept=False)
        self.assertEqual(self.g.due_promises(now=now), [])

    def test_resolve_without_open_is_not_an_error(self):
        """没有待处理的承诺是正常结果，**不能**带 error 键。

        cli.py 只要看到 "error" 就 exit 2，运维脚本和插件会把它当失败。
        """
        r = self.g.resolve_promise()
        self.assertFalse(r["ok"])
        self.assertNotIn("error", r)

    def test_duplicate_registration_counts_once(self):
        """同一句话登记两次，不该被她当成两件欠着的事。"""
        now = time.time()
        self.g.register_promise("陪他去看海", due=now - 60)
        self.g.register_promise("陪他去看海", due=now - 60)
        self.assertEqual(len(self.g.due_promises(now=now)), 1)
        self.assertEqual(self.g.resolve_promise("看海")["ok"], True)


# ---------------------------------------------------------------- 简报接线段

class TestBriefPromise(unittest.TestCase):

    def test_due_sentence_appears(self):
        s = StateSnapshot(should_reach=False, promise_due="due")
        self.assertIn("还欠着", compile_brief(s))

    def test_vague_sentence_differs(self):
        s = StateSnapshot(should_reach=False, promise_due="vague")
        out = compile_brief(s)
        self.assertIn("一直没给他", out)
        self.assertNotIn("还欠着", out)

    def test_no_promise_no_sentence(self):
        s = StateSnapshot(should_reach=False)
        out = compile_brief(s)
        self.assertNotIn("欠着", out)
        self.assertNotIn("答应", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
