# -*- coding: utf-8 -*-
"""fishidian_core.env —— 环境采样与变化检测（V1）

设计约束（依据内部记录 021、022，未随仓库公开）：

1. **只做变化检测，不做轮询累积**。tick 每 10 分钟跑一次，但如果环境没变，
   这里什么都不产出。变化的判定靠 `prev` 与 `cur` 的快照比对。
2. **不产生台词，只产生 `(tag, intensity, source)`**。带台词的外部源一眼露馅。
3. **采样失败一律降级**，绝不抛异常打断这一轮对话。天气拉不到就留空。
4. **tag 是五行**（木火土金水），不是五志。引擎只认五行（wuxing.py `weak_tag`）。

对外只有五个函数：`sample` / `to_events` / `significant` / `snapshot_text` /
`to_json`（外加 `from_json` 回读）。其余都是内部实现。
"""
from __future__ import annotations

import json
import math
import time

from . import config as C


# ---------------- 子午流注十二经当令 ----------------
# (时辰, 起, 止, 五行, 脏腑)。子时跨零点，必须单独处理。
# 分布：木 4h / 金 4h / 土 4h / 水 4h / **火 8h**（午、未、戌、亥）。
# 火是唯一出现两段的，所以她的底色天然偏暖。若发现长期亢奋，先降 ENV_P_HOUR。
SHICHEN = (
    ("子", 23, 1, "木", "胆"),
    ("丑", 1, 3, "木", "肝"),
    ("寅", 3, 5, "金", "肺"),
    ("卯", 5, 7, "金", "大肠"),
    ("辰", 7, 9, "土", "胃"),
    ("巳", 9, 11, "土", "脾"),
    ("午", 11, 13, "火", "心"),
    ("未", 13, 15, "火", "小肠"),
    ("申", 15, 17, "水", "膀胱"),
    ("酉", 17, 19, "水", "肾"),
    ("戌", 19, 21, "火", "心包"),
    ("亥", 21, 23, "火", "三焦"),
)


def shichen_of(ts=None):
    """此刻的时辰。返回 dict，永不返回 None（兜底子时）。"""
    ts = time.time() if ts is None else ts
    h = time.localtime(ts).tm_hour
    for name, a, b, wx, organ in SHICHEN:
        if a < b:
            if a <= h < b:
                return {"name": name, "wuxing": wx, "organ": organ,
                        "start": a, "end": b}
        elif h >= a or h < b:          # 子时：23:00–01:00 跨日
            return {"name": name, "wuxing": wx, "organ": organ,
                    "start": a, "end": b}
    return {"name": SHICHEN[0][0], "wuxing": SHICHEN[0][3],
            "organ": SHICHEN[0][4], "start": 23, "end": 1}


# ---------------- 二十四节气 ----------------
# (月, 日, 名, 五行)。公历近似日期，误差 ±1 天，对"底色"够用。
# 长夏处理：大暑这一个节气归土，立秋当天起归金（022 §5.2 的落地口径）。
SOLAR_TERMS = (
    (1, 6, "小寒", "水"),
    (1, 20, "大寒", "水"),
    (2, 4, "立春", "木"),
    (2, 19, "雨水", "木"),
    (3, 6, "惊蛰", "木"),
    (3, 21, "春分", "木"),
    (4, 5, "清明", "木"),
    (4, 20, "谷雨", "木"),
    (5, 6, "立夏", "火"),
    (5, 21, "小满", "火"),
    (6, 6, "芒种", "火"),
    (6, 21, "夏至", "火"),
    (7, 7, "小暑", "火"),
    (7, 23, "大暑", "土"),      # 长夏
    (8, 8, "立秋", "金"),
    (8, 23, "处暑", "金"),
    (9, 8, "白露", "金"),
    (9, 23, "秋分", "金"),
    (10, 8, "寒露", "金"),
    (10, 23, "霜降", "金"),
    (11, 7, "立冬", "水"),
    (11, 22, "小雪", "水"),
    (12, 7, "大雪", "水"),
    (12, 22, "冬至", "水"),
)


def solar_term_of(ts=None):
    """此刻所处的节气。跨年边界（1/1–1/5）归上一年冬至。"""
    ts = time.time() if ts is None else ts
    lt = time.localtime(ts)
    m, d = lt.tm_mon, lt.tm_mday
    hit = ("冬至", "水")
    for sm, sd, name, wx in SOLAR_TERMS:
        if (sm, sd) <= (m, d):
            hit = (name, wx)
    return {"name": hit[0], "wuxing": hit[1]}


# ---------------- 日照时长 ----------------
def day_length(ts=None, lat=None):
    """当日理论日照时长（小时），NOAA 近似。极昼/极夜已夹到 0/24。"""
    ts = time.time() if ts is None else ts
    lat = C.ENV_DEFAULT_LAT if lat is None else lat
    lt = time.localtime(ts)
    n = lt.tm_yday
    decl = 23.44 * math.sin(math.radians(360.0 * (284 + n) / 365.0))
    try:
        lat_r = math.radians(lat)
        dec_r = math.radians(decl)
        cos_ha = -math.tan(lat_r) * math.tan(dec_r)
    except (ValueError, ZeroDivisionError):
        return 12.0
    if cos_ha >= 1.0:
        return 0.0      # 极夜
    if cos_ha <= -1.0:
        return 24.0     # 极昼
    ha_deg = math.degrees(math.acos(cos_ha))
    return round(2.0 * ha_deg / 15.0, 2)


# ---------------- 天气 ----------------
# 归一成六类。规则按"越具体越先"的顺序匹配，避免 "patchy rain" 被算成晴天。
_WCODE_RULES = (
    ("thunder", "thunder"),
    ("blizzard", "snow"),
    ("snow", "snow"),
    ("sleet", "snow"),
    ("ice", "snow"),
    ("rain", "rain"),
    ("drizzle", "rain"),
    ("shower", "rain"),
    ("mist", "fog"),
    ("fog", "fog"),
    ("haze", "fog"),
    ("overcast", "cloudy"),
    ("cloud", "cloudy"),
    ("sunny", "sun"),
    ("clear", "sun"),
)

# 六类默认五行。雪默认归金（肃杀），只有她明确喜欢雪才翻成火。
_WX_OF_CODE = {
    "sun": "火",
    "cloudy": "土",
    "rain": "金",
    "snow": "金",
    "fog": "土",
    "thunder": "木",
    "unknown": "土",
}

_CODE_CN = {
    "sun": "晴", "cloudy": "阴", "rain": "雨", "snow": "雪",
    "fog": "雾", "thunder": "雷", "unknown": "未知",
}


def weather_code(desc):
    """wttr.in 的英文描述 → 六类代码。认不出归 cloudy，描述为空归 unknown。"""
    d = (desc or "").strip().lower()
    if not d:
        return "unknown"
    for key, code in _WCODE_RULES:
        if key in d:
            return code
    return "cloudy"


def weather_wuxing(code, pref=None):
    """天气代码 → 五行。命中偏好时翻成火（喜），并返回是否命中。

    pref 形如 {"snow": "like", "rain": "dislike"}，来自 kv `pref:env`。
    没有偏好就按中医默认走：晴火、雨雪金、雾阴土、雷木。
    """
    base = _WX_OF_CODE.get(code, "土")
    p = (pref or {}).get(code)
    if p == "like":
        return "火", True
    if p == "dislike":
        return base, True
    return base, False


# ---------------- 快照 ----------------
def sample(now=None, city=None, weather=None, pref=None, lat=None):
    """采一次完整快照。weather 传 {"desc","temp_c"} 或 None（None 表示没网/没城市）。

    永不抛异常：任何一步失败都降级成保守值（时辰节气一定拿得到，它们是本地算的）。
    """
    now = time.time() if now is None else now
    sc = shichen_of(now)
    st = solar_term_of(now)
    dl = day_length(now, lat)

    temp = None
    code = "unknown"
    desc = ""
    if isinstance(weather, dict):
        desc = weather.get("desc") or ""
        code = weather_code(desc)
        tc = weather.get("temp_c")
        try:
            temp = int(float(tc)) if tc is not None else None
        except (TypeError, ValueError):
            temp = None

    wx, pref_hit = weather_wuxing(code, pref)

    return {
        "ts": int(now),
        "city": city or "",
        "sc": sc["name"],
        "sc_wx": sc["wuxing"],
        "sc_organ": sc["organ"],
        "st": st["name"],
        "st_wx": st["wuxing"],
        "w": code,
        "desc": desc,
        "t": temp,
        "dl": dl,
        "w_wx": wx,
        "pref_hit": bool(pref_hit),
    }


def to_events(cur, prev):
    """比对两次快照，产出 [(tag, intensity, source)]。

    **没有变化就返回空列表。** 这是整个心跳最省的地方——没变化不说话，
    也不写库。一天 144 次 tick 里真正产出事件的可能只有十几次。
    """
    out = []
    if not cur or not prev:
        return out

    if cur.get("sc") != prev.get("sc"):
        out.append((cur.get("sc_wx") or "土", C.ENV_P_HOUR,
                    "hour:%s" % cur.get("sc")))
    if cur.get("st") != prev.get("st"):
        out.append((cur.get("st_wx") or "土", C.ENV_P_SOLAR,
                    "solar:%s" % cur.get("st")))
    if cur.get("w") != prev.get("w"):
        # 阴↔雾这类同类互转只算软变化，别当成"天气大变"
        soft = (cur.get("w") in ("cloudy", "fog")
                and prev.get("w") in ("cloudy", "fog"))
        base = C.ENV_P_WEATHER_SOFT if soft else C.ENV_P_WEATHER
        # 冬天晴天但日照短 → 火打七折（冬天的晴和夏天的晴不是一回事）
        if cur.get("w") == "sun" and (cur.get("dl") or 12.0) < C.ENV_DL_SHORT_H:
            base = base * C.ENV_DL_SHORT_PENALTY
        out.append((cur.get("w_wx") or "土", base, "weather:%s" % cur.get("w")))

    if cur.get("pref_hit") and not prev.get("pref_hit"):
        out.append((cur.get("w_wx") or "火", C.ENV_P_PREF_HIT,
                    "pref:%s" % cur.get("w")))

    # 单源硬上限：任何一次注入都不许顶掉半个状态
    return [(t, min(i, C.ENV_P_MAX_SINGLE), s) for t, i, s in out if i > 0]


def significant(cur, prev):
    """够不够格写一条环境记忆。宁可少写，也别把 14°→15° 这种记下来。"""
    if not cur:
        return False
    if not prev:
        return True                       # 第一次采样，留个底
    if cur.get("st") != prev.get("st"):
        return True                       # 节气必写
    if cur.get("w") != prev.get("w"):
        return True                       # 天气类别变化必写
    a, b = cur.get("t"), prev.get("t")
    if a is not None and b is not None and abs(a - b) >= C.ENV_TEMP_MEM_DELTA:
        return True                       # 温差 ≥5°C 才写
    da, db = cur.get("dl"), prev.get("dl")
    if da is not None and db is not None:
        if abs(da - db) * 60.0 >= C.ENV_DL_JUMP_MIN:
            return True                   # 日照跳变 ≥60min
    return False


def snapshot_text(env):
    """人话快照，用来写进 env_json 之外的可读位置（召回时带一句）。"""
    if not env:
        return ""
    parts = []
    ts = env.get("ts")
    if ts:
        lt = time.localtime(ts)
        parts.append("%02d-%02d" % (lt.tm_mon, lt.tm_mday))
    if env.get("sc"):
        parts.append("%s时" % env["sc"])
    if env.get("st"):
        parts.append(env["st"])
    w = env.get("w")
    if w and w != "unknown":
        parts.append(_CODE_CN.get(w, ""))
    t = env.get("t")
    if t is not None:
        parts.append("%s°C" % ("%+d" % t if t < 0 else "%d" % t))
    s = " · ".join([p for p in parts if p])
    return s[:C.ENV_SNAPSHOT_MAXCHARS]


def to_json(env):
    """打包成 env_json（短键省空间，约 100 字节/条）。"""
    if not env:
        return ""
    d = {
        "w": env.get("w") or "unknown",
        "t": env.get("t"),
        "st": env.get("st") or "",
        "sc": env.get("sc") or "",
        "dl": env.get("dl"),
        "city": env.get("city") or "",
    }
    try:
        return json.dumps(d, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return ""


def from_json(s):
    """回读 env_json。坏数据返回 None，不抛。"""
    if not s:
        return None
    try:
        d = json.loads(s)
        return d if isinstance(d, dict) else None
    except Exception:
        return None


def env_value(code):
    """天气 → 写记忆时的 valence（她当时的底色）。"""
    if code == "sun":
        return C.ENVMEM_VAL_SUN
    if code == "rain":
        return C.ENVMEM_VAL_RAIN
    if code == "snow":
        return C.ENVMEM_VAL_SNOW
    if code == "fog":
        return C.ENVMEM_VAL_FOG
    if code == "thunder":
        return C.ENVMEM_VAL_RAIN
    return 0.0
