# -*- coding: utf-8 -*-
"""env / tick / settle_gap 的回归测试（V1 心跳机制）

跑法（在 fishidian-core 目录下）：
    python -X utf8 tests\test_env_tick.py

覆盖四组：
  1. env 纯函数（时辰 12 段、节气跨年、日照、天气归一、偏好翻转）
  2. 变化检测（同状态零事件、单源上限、显著性三档）
  3. tick（不加 count、不碰 W、推进 last_at、注入生效）
  4. settle_gap（门槛、封顶、只结算一次、关机折扣）
  + store 的 env_json 落库
"""
import os
import sys
import tempfile
import shutil
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from fishidian_core import config as C
from fishidian_core import env as E
from fishidian_core.store import Store
from fishidian_core.wuxing import WuXingEngine

_ok = [0]
_fail = [0]
_msgs = []


def chk(cond, name):
    if cond:
        _ok[0] += 1
    else:
        _fail[0] += 1
        _msgs.append(name)
        print("  FAIL: " + name)


def ts_of(y, m, d, h=12):
    return time.mktime((y, m, d, h, 0, 0, 0, 0, -1))


def fresh_db():
    d = tempfile.mkdtemp(prefix="fishidian_tick_")
    return Store(os.path.join(d, "t.db")), d


# ---------------------------------------------------------------- 1. env
def test_env():
    print("[1] env 纯函数")

    # 12 时辰必须全覆盖（24 小时里只有 12 个名字）
    base = ts_of(2026, 11, 13, 0)
    seen = set()
    for h in range(24):
        seen.add(E.shichen_of(base + h * 3600)["name"])
    chk(len(seen) == 12, "24 小时覆盖 12 个时辰")
    chk(E.shichen_of(ts_of(2026, 11, 13, 0))["name"] == "子", "0 点归子时")
    chk(E.shichen_of(ts_of(2026, 11, 13, 23))["name"] == "子", "23 点归子时")

    # 节气：跨年边界 + 长夏
    chk(E.solar_term_of(ts_of(2026, 1, 3))["name"] == "冬至", "1/3 归上一年冬至")
    chk(E.solar_term_of(ts_of(2026, 11, 13))["name"] == "立冬", "11/13 立冬")
    chk(E.solar_term_of(ts_of(2026, 7, 25))["wuxing"] == "土", "大暑归土（长夏）")
    chk(E.solar_term_of(ts_of(2026, 8, 10))["wuxing"] == "金", "立秋后归金")
    count = len(E.SOLAR_TERMS)
    chk(count == 24, "节气表 24 条")

    # 日照：夏至 > 冬至，且都在合法区间
    dl_sum = E.day_length(ts_of(2026, 6, 21), 30.6)
    dl_win = E.day_length(ts_of(2026, 12, 21), 30.6)
    chk(0.0 <= dl_sum <= 24.0 and 0.0 <= dl_win <= 24.0, "日照在 0–24")
    chk(dl_sum > dl_win + 2.0, "夏至比冬至明显长")
    chk(E.day_length(ts_of(2026, 6, 21), 80.0) == 24.0, "极昼夹到 24")

    # 天气归一
    chk(E.weather_code("Light rain") == "rain", "Light rain → rain")
    chk(E.weather_code("Light snow") == "snow", "Light snow → snow")
    chk(E.weather_code("Patchy rain possible") == "rain", "Patchy rain → rain")
    chk(E.weather_code("Thundery outbreaks possible") == "thunder", "雷 → thunder")
    chk(E.weather_code("Overcast") == "cloudy", "阴 → cloudy")
    chk(E.weather_code("Sunny") == "sun", "晴 → sun")
    chk(E.weather_code("") == "unknown", "空 → unknown")

    # 偏好翻转
    tag, hit = E.weather_wuxing("snow", {"snow": "like"})
    chk(tag == "火" and hit, "喜欢雪 → 火")
    tag, hit = E.weather_wuxing("snow", None)
    chk(tag == "金" and not hit, "默认雪 → 金")
    tag, hit = E.weather_wuxing("rain", {"rain": "dislike"})
    chk(tag == "金" and hit, "讨厌雨 → 金但算命中")

    # json 往返
    s = E.sample(now=ts_of(2026, 11, 13), city="武汉",
                 weather={"desc": "Light snow", "temp_c": -2})
    j = E.to_json(s)
    back = E.from_json(j)
    chk(back and back.get("w") == "snow", "env_json 往返")
    chk(len(j.encode("utf-8")) < 140, "env_json < 140 字节")
    chk(E.from_json("{bad") is None, "坏 json 返回 None")
    txt = E.snapshot_text(s)
    chk("雪" in txt and "武汉" not in txt, "快照文本含天气不含城市")


# ------------------------------------------------------- 2. 变化检测
def test_events():
    print("[2] 变化检测")
    t = ts_of(2026, 11, 13, 21)
    a = E.sample(now=t, city="武汉", weather={"desc": "Light snow", "temp_c": -2})
    b = E.sample(now=t, city="武汉", weather={"desc": "Light snow", "temp_c": -2})
    chk(E.to_events(b, a) == [], "同状态零事件")
    chk(E.significant(b, a) is False, "同状态不显著")

    c = E.sample(now=t, city="武汉", weather={"desc": "Sunny", "temp_c": 1})
    evs = E.to_events(c, a)
    tags = [x[0] for x in evs]
    chk("火" in tags, "雪→晴产出火")
    chk(all(x[1] <= C.ENV_P_MAX_SINGLE for x in evs), "单源不超上限")
    chk(E.significant(c, a) is True, "天气类别变 → 显著")

    # 温差：2°C 不记，9°C 记
    d1 = E.sample(now=t, city="武汉", weather={"desc": "Sunny", "temp_c": 1})
    d2 = E.sample(now=t, city="武汉", weather={"desc": "Sunny", "temp_c": 3})
    d3 = E.sample(now=t, city="武汉", weather={"desc": "Sunny", "temp_c": 10})
    chk(E.significant(d2, d1) is False, "温差 2°C 不显著")
    chk(E.significant(d3, d1) is True, "温差 9°C 显著")

    # 阴↔雾只算软变化
    e1 = E.sample(now=t, city="武汉", weather={"desc": "Overcast", "temp_c": 8})
    e2 = E.sample(now=t, city="武汉", weather={"desc": "Mist", "temp_c": 8})
    evs = E.to_events(e2, e1)
    chk(len(evs) == 1 and abs(evs[0][1] - C.ENV_P_WEATHER_SOFT) < 1e-9, "阴→雾是软变化")

    # 冬天晴天日照短 → 火打七折
    w1 = E.sample(now=ts_of(2026, 11, 13, 21), city="武汉",
                  weather={"desc": "Overcast", "temp_c": 5})
    w2 = E.sample(now=ts_of(2026, 11, 13, 21), city="武汉",
                  weather={"desc": "Sunny", "temp_c": 5})
    evs = E.to_events(w2, w1)
    sun = [x for x in evs if x[0] == "火"]
    chk(sun and sun[0][1] < C.ENV_P_WEATHER, "冬天晴的火打了折")


# ------------------------------------------------------------- 3. tick
def test_tick():
    print("[3] tick")
    st, tmp = fresh_db()
    try:
        w = WuXingEngine(st, "test", mode="B")
        cnt0 = sum(w.count.values())
        w0 = list(w.W)
        mid_before = int(w.last_at)

        now = time.time() + 60
        r = w.tick(now=now, tag="火", intensity=0.1)
        chk(abs(r["added"] - 0.1) < 1e-9, "注入量如实返回")
        chk(sum(w.count.values()) == cnt0, "tick 不加 count（关键）")
        chk([round(x, 6) for x in w.W] == [round(x, 6) for x in w0], "tick 不碰 W（关键）")
        chk(int(w.last_at) == int(now), "last_at 推进到本次 now")
        chk(w.E["火"] > 0.0, "火确实涨了")

        # 只补衰减不注入
        w2 = WuXingEngine(st, "test", mode="B")
        e_before = dict(w2.E)
        r2 = w2.tick(now=now + 12 * 3600)
        chk(r2["added"] == 0.0, "无 tag 时只补衰减")
        chk(r2["decayed"] < 1.0, "12h 后衰减系数 < 1")
        chk(sum(w2.E.values()) < sum(e_before.values()) + 1e-9, "E 整体下降")

        # 半衰 6h：12h 应剩约 1/4
        chk(abs(r2["decayed"] - 0.25) < 0.03, "12h 衰减≈0.25（半衰 6h）")

        # 非法 tag 不注入也不崩
        r3 = w2.tick(now=now + 13 * 3600, tag="喜", intensity=0.5)
        chk(r3["added"] == 0.0, "五志 tag 被安全忽略")
    finally:
        try:
            st.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------- 4. settle
def test_settle():
    print("[4] settle_gap")

    # 4.1 门槛：2h 不结算
    st, tmp = fresh_db()
    try:
        w = WuXingEngine(st, "test", mode="B")
        now = time.time()
        st.set_kv("ns:last_user:test", "%.3f" % (now - 2 * 3600))
        st.set_kv("tick:last:test", "%.3f" % (now - 3600))
        chk(w.settle_gap(now=now) == [], "2h 不结算")
    finally:
        try:
            st.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    # 4.2 50h 开机：两个五行、不超上限、只结算一次
    st, tmp = fresh_db()
    try:
        w = WuXingEngine(st, "test", mode="B")
        now = time.time()
        st.set_kv("ns:last_user:test", "%.3f" % (now - 50 * 3600))
        st.set_kv("tick:last:test", "%.3f" % (now - 3600))     # 她活着
        out = w.settle_gap(now=now)
        chk(len(out) == 2, "50h 结算两条")
        chk(set(x[0] for x in out) == {"金", "木"}, "词表是金+木")
        chk(all(x[1] <= C.GAP_MAX_INTENSITY for x in out), "不超硬上限")
        chk(sum(w.E.values()) > 0, "E 真的涨了")
        chk(w.settle_gap(now=now) == [], "同一缺口只结算一次")
    finally:
        try:
            st.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    # 4.3 关机折扣：同样 50h，关机那台明显轻
    alive = {}
    st, tmp = fresh_db()
    try:
        w = WuXingEngine(st, "a", mode="B")
        now = time.time()
        st.set_kv("ns:last_user:a", "%.3f" % (now - 50 * 3600))
        st.set_kv("tick:last:a", "%.3f" % (now - 1800))
        alive = {t: i for t, i, _ in w.settle_gap(now=now)}
    finally:
        try:
            st.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    st, tmp = fresh_db()
    try:
        w = WuXingEngine(st, "b", mode="B")
        now = time.time()
        st.set_kv("ns:last_user:b", "%.3f" % (now - 50 * 3600))
        st.set_kv("tick:last:b", "%.3f" % (now - 50 * 3600))   # 关机
        asleep = {t: i for t, i, _ in w.settle_gap(now=now)}
    finally:
        try:
            st.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)

    chk(alive and asleep, "两种情况都产出情绪")
    chk(all(alive[k] > asleep[k] for k in alive), "关机结算明显更轻")

    # 4.4 封顶：两个月也按 7 天档，不线性放大
    st, tmp = fresh_db()
    try:
        w = WuXingEngine(st, "test", mode="B")
        now = time.time()
        st.set_kv("ns:last_user:test", "%.3f" % (now - 60 * 24 * 3600))
        st.set_kv("tick:last:test", "%.3f" % (now - 3600))
        out = w.settle_gap(now=now)
        chk(all(x[1] <= C.GAP_MAX_INTENSITY for x in out), "60 天仍不超上限")
    finally:
        try:
            st.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------- 5. profile/env_json
def test_misc():
    print("[5] profile_gain / env_json")
    st, tmp = fresh_db()
    try:
        w = WuXingEngine(st, "test", mode="B")
        # W 很平时，任何情绪的敏感度都应接近 1.0
        g_all = [w.profile_gain(k) for k in ("木", "火", "土", "金", "水")]
        chk(all(abs(g - 1.0) < 0.12 for g in g_all), "W 平坦时增益≈1.0")

        # 极端偏向金：金的增益最高
        w.W = [0.01, 0.01, 0.01, 0.96, 0.01]
        chk(w.profile_gain("金") > w.profile_gain("火"), "偏金时金 > 火")
        chk(w.profile_gain("木") != 1.0, "偏金时其他也不等于 1（加权非取主导）")

        # env_json 落库
        mid = st.add_memory("test", "初雪那天", 0.55, 0.3, 0.05, "环境", "blood", 3.0,
                            source="env", env_json='{"w":"snow","t":-2,"st":"小雪"}')
        m = st.get_memory(mid)
        chk(m is not None and m.get("env_json"), "env_json 列落库成功")
        if m:
            chk(E.from_json(m["env_json"]).get("w") == "snow", "读回来还是 snow")
    finally:
        try:
            st.close()
        except Exception:
            pass
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    test_env()
    test_events()
    test_tick()
    test_settle()
    test_misc()
    print("")
    print("PASS %d / FAIL %d" % (_ok[0], _fail[0]))
    if _fail[0]:
        print("failures:")
        for m in _msgs:
            print("  - " + m)
        sys.exit(1)
    print("ALL GREEN")
