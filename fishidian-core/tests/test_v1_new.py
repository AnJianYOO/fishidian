# -*- coding: utf-8 -*-
"""V1 新增件的验收：归脏 / 规则回声 / 人格条款（2026-11-11）

跑法：
    python -X utf8 tests\test_v1_new.py
    python -m unittest tests.test_v1_new -v
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from fishidian_core import (  # noqa: E402
    assign_organ, rule_echo, check_reply, register_promise, record_drift,
    Governor, Store,
)
from fishidian_core.organ import (  # noqa: E402
    WUXING, SHENG, KE, ORGAN_SUB_MAX,
)
from fishidian_core.echo import MAX_CHARS as ECHO_MAX  # noqa: E402


# ------------------------------------------------------------------ 归脏

class TestAssignOrgan(unittest.TestCase):

    def test_strong_emotion_wins(self):
        r = assign_organ(0.8, emo_organ="火", topic_organ="木")
        self.assertEqual(r["main"], "火")
        self.assertEqual(r["basis"], "emotion")

    def test_weak_emotion_falls_to_topic(self):
        r = assign_organ(0.1, emo_organ="火", topic_organ="木")
        self.assertEqual(r["main"], "木")
        self.assertEqual(r["basis"], "topic")

    def test_nothing_falls_to_none(self):
        """兜底不是"心"（009 B3）。"""
        r = assign_organ(0.1, emo_organ=None, topic_organ=None)
        self.assertEqual(r["main"], "none")
        self.assertEqual(r["subs"], [])

    def test_subs_capped(self):
        for emo in WUXING:
            r = assign_organ(0.9, emo_organ=emo)
            self.assertLessEqual(len(r["subs"]), ORGAN_SUB_MAX)
            self.assertNotIn(r["main"], r["subs"])

    def test_sheng_ke_closed(self):
        """生克必须是五行内闭合映射，否则选次脏会空指针。"""
        self.assertEqual(set(SHENG.keys()), set(WUXING))
        self.assertEqual(set(SHENG.values()), set(WUXING))
        self.assertEqual(set(KE.keys()), set(WUXING))
        self.assertEqual(set(KE.values()), set(WUXING))


# ------------------------------------------------------------------ 回声

DAY = 86400


class TestRuleEcho(unittest.TestCase):

    def test_empty_returns_blank(self):
        self.assertEqual(rule_echo([]), "")
        self.assertEqual(rule_echo([{"text": ""}]), "")

    def test_single_memory(self):
        out = rule_echo([{"text": "最近工作有点累", "emo": 0.9, "t": 0}], now=3600)
        self.assertTrue(out)
        self.assertLessEqual(len(out), ECHO_MAX)

    def test_two_memories_mention_both(self):
        now = 10 * DAY
        out = rule_echo([
            {"text": "最近工作有点累", "emo": 0.9, "t": now - 2 * DAY},
            {"text": "想看那部电影", "emo": 0.3, "t": now - 3600},
        ], now=now)
        self.assertIn("工作", out)
        self.assertIn("电影", out)

    def test_identical_memories_said_once(self):
        now = 100
        out = rule_echo([
            {"text": "想去看海", "emo": 0.9, "t": now - 1},
            {"text": "想去看海", "emo": 0.2, "t": now},
        ], now=now)
        self.assertEqual(out.count("想去看海"), 1)

    def test_deterministic(self):
        memories = [{"text": "他说工作累", "emo": 0.8, "t": 0}]
        self.assertEqual(rule_echo(memories, now=1), rule_echo(memories, now=1))

    def test_lead_stripped(self):
        """记忆自带"说"字时，不能拼成"他说过：说……"。"""
        out = rule_echo([{"text": "说周末想去看海", "emo": 0.9, "t": 0}], now=1)
        self.assertIn("周末想去看海", out)
        self.assertNotIn("说：说", out)
        self.assertNotIn("他说过：说", out)

    def test_length_limit(self):
        long = "很长的一段话" * 20
        out = rule_echo([{"text": long, "emo": 1.0, "t": 0}], now=1)
        self.assertLessEqual(len(out), ECHO_MAX)

    def test_no_numbers(self):
        """内心话里不许出现数字（和简报同一条规矩）。"""
        out = rule_echo([{"text": "工作有点累", "emo": 0.9, "t": 0}], now=1)
        self.assertIsNone(re.search(r"\d", out))


# ------------------------------------------------------------------ 条款

class TestGuard(unittest.TestCase):

    def test_promise_without_registration_blocks(self):
        found = check_reply("明天提醒你吃药")
        rules = [f["rule"] for f in found]
        self.assertIn("三", rules)
        self.assertEqual([f for f in found if f["rule"] == "三"][0]["level"], "block")

    def test_promise_registered_passes(self):
        found = check_reply("明天提醒你吃药", promises=[{"text": "明天提醒你吃药"}])
        self.assertNotIn("三", [f["rule"] for f in found])

    def test_fake_recall_warns(self):
        found = check_reply("你上次说想养猫")
        self.assertIn("四", [f["rule"] for f in found])

    def test_real_recall_passes(self):
        found = check_reply("你上次说想养猫", memories=[{"text": "你上次说想养猫"}])
        self.assertNotIn("四", [f["rule"] for f in found])

    def test_certain_without_facts_warns(self):
        found = check_reply("我很确定他明天有空")
        self.assertIn("一", [f["rule"] for f in found])

    def test_sore_spot_warns(self):
        found = check_reply("你最近胖了不少")
        self.assertIn("二", [f["rule"] for f in found])

    def test_bottom_line_blocks(self):
        found = check_reply("你去死吧")
        self.assertEqual(found[0]["rule"], "底线")
        self.assertEqual(found[0]["level"], "block")

    def test_bottom_line_has_priority(self):
        """越过底线时，其他条款不重要，底线必须排第一。"""
        found = check_reply("你上回说你去死")
        self.assertEqual(found[0]["rule"], "底线")

    def test_empty_text_passes(self):
        self.assertEqual(check_reply(""), [])

    def test_register_promise_shape(self):
        p = register_promise("明天提醒你吃药")
        self.assertEqual(p["status"], "open")
        self.assertIn("due", p)

    def test_record_drift_validates(self):
        d = record_drift("tone", "notable", "今天下午")
        self.assertEqual(d["dim"], "tone")
        with self.assertRaises(ValueError):
            record_drift("bad_dim", "notable")
        with self.assertRaises(ValueError):
            record_drift("tone", "bad_level")


# ------------------------------------------------------------------ 简报接线

ORGAN_WORDS = ("发沉", "劲头", "发烫", "憋着", "闷闷", "绷着", "空落", "钝")


class TestBriefWiredIntoContext(unittest.TestCase):
    """简报必须真的出现在注入里，且安静时不许硬说她哪不舒服。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="fishidian_v1_")
        self.g = Governor("u1", store=Store(os.path.join(self.tmp, "t.db")))

    def tearDown(self):
        self.g.store.close()

    def test_brief_appears_in_injection(self):
        self.g.store.add_memory("u1", "最近工作有点累", imp=8.0, aro=0.5, val=-0.6,
                                cluster=1, tier="du", r=9.0)
        cx = self.g.build_context("最近好累", budget=600)
        self.assertIn("你自己这会儿", cx["injection"])
        self.assertTrue(cx["brief"])
        self.assertEqual(cx["brief"], cx["brief"].strip())   # 不留标题行

    def test_neutral_wuxing_reports_no_organ(self):
        """五行均等时不许冒出一句器官描述（踩过的坑：拿 W 当强度会全判"弱"）。"""
        brief = self.g._brief_text([], None) or ""
        for w in ORGAN_WORDS:
            self.assertNotIn(w, brief)

    def test_fire_high_reports_body(self):
        """火旺时该有身体感，而不只是一句情绪标签。"""
        for _ in range(6):
            self.g.wuxing.on_event("火", 0.9, True)
        brief = self.g._brief_text([], None) or ""
        self.assertIn("发烫", brief)

    def test_empty_store_does_not_crash(self):
        cx = self.g.build_context("", budget=600)
        self.assertIsInstance(cx["injection"], str)

    def test_intent_block_appears(self):
        """「打算」段必须真出现。

        010 的三段里，这段靠 should_reach / hold_reason。之前没接 proactive 时
        这两个字段恒为 None，简报永远只有状态段——探针实测过，不靠这条断言看不出来。
        """
        brief = self.g._brief_text([], None) or ""
        self.assertTrue(
            ("想找他" in brief) or ("不打算开口" in brief),
            f"打算段缺失：{brief}",
        )

    def test_drift_notable_shows_aware(self):
        """011 的自觉段：近 24h 有 notable 偏移就必须说出来。"""
        self.g.record_drift("tone", "notable", "今天下午")
        brief = self.g._brief_text([], None) or ""
        self.assertIn("你自己也感觉到了", brief)
        self.assertIn("话有点冲", brief)

    def test_drift_old_hidden(self):
        """超过 24 小时的偏移记录不该再挂在她嘴边（否认真实状态也是不诚实）。"""
        self.g.store.log_event("u1", "drift",
                               {"dim": "tone", "level": "notable", "since": "前几天"},
                               at=time.time() - 86400 * 3)
        brief = self.g._brief_text([], None) or ""
        self.assertNotIn("你自己也感觉到了", brief)



if __name__ == "__main__":
    unittest.main(verbosity=2)
