# -*- coding: utf-8 -*-
"""fishidian_core.intel —— 通用外部情报层（17 号 §16 主动情报）。

设计原则：**通用、由记忆驱动、不绑定个人**。
- 关注主题从每个 ns 自己的记忆里推导（高频主题词 / 城市名 / 五志 tag），不写死任何个人画像；
- 外部源（天气 / 节日 / 新闻）按该 ns 的兴趣关键词过滤，产出"主动话题候选"；
- 所有网络调用带超时 + try/except，无网时自动降级（只用记忆 + 本地公历节日），绝不抛错阻塞聊天。

调用形态：`python cli.py <ns> <db> intel [--no-net]`（stdout JSON）。
"""
from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
import urllib.error

from . import config as C

# ---------- 通用主题词表（用于从记忆统计兴趣；可配置扩展） ----------
TOPICS = [
    "工作", "健康", "游戏", "天气", "旅行", "家人", "朋友", "感情",
    "学习", "赚钱", "美食", "运动", "宠物", "技术", "房子", "车子",
]
# 通用中国地名表（用于两件事：① 从记忆统计兴趣城市；② 从任意口语里识出城市名）。
# 只放"地名"本身，不含任何个人偏好——不绑定某个用户住哪。
CITY_BASE = [
    # 直辖市
    "北京", "上海", "天津", "重庆",
    # 省会 / 首府
    "石家庄", "太原", "呼和浩特", "沈阳", "长春", "哈尔滨", "南京", "杭州", "合肥",
    "福州", "南昌", "济南", "郑州", "武汉", "长沙", "广州", "南宁", "海口", "成都", "贵阳",
    "昆明", "拉萨", "西安", "兰州", "西宁", "银川", "乌鲁木齐",
    # 计划单列 / 经济重镇
    "深圳", "厦门", "宁波", "青岛", "大连", "苏州", "无锡", "温州", "佛山", "东莞",
    "珠海", "中山", "惠州", "汕头", "泉州", "常州", "南通", "徐州", "扬州", "绍兴",
    "嘉兴", "金华", "台州", "烟台", "潍坊", "淄博", "临沂", "洛阳", "开封", "唐山",
    "保定", "廊坊", "秦皇岛", "邯郸", "大同", "包头", "鄂尔多斯", "鞍山", "吉林市",
    "大庆", "齐齐哈尔", "芜湖", "蚌埠", "马鞍山", "赣州", "九江", "宜昌", "襄阳",
    "荆州", "十堰", "黄石", "孝感", "岳阳", "株洲", "湘潭", "衡阳", "常德", "郴州",
    "桂林", "柳州", "北海", "三亚", "绵阳", "德阳", "宜宾", "泸州", "南充", "遵义",
    "曲靖", "大理", "丽江", "西双版纳", "延安", "宝鸡", "咸阳", "天水", "酒泉",
    "喀什", "伊犁", "延边", "廊坊", "沧州", "邢台", "承德", "张家口", "衡水",
    "丹东", "锦州", "营口", "抚顺", "本溪", "盘锦", "四平", "通化", "延吉", "牡丹江",
    "佳木斯", "绥化", "连云港", "淮安", "盐城", "泰州", "镇江", "宿迁", "湖州",
    "衢州", "舟山", "丽水", "安庆", "黄山", "滁州", "阜阳", "宿州", "六安", "莆田",
    "三明", "漳州", "龙岩", "宁德", "景德镇", "萍乡", "上饶", "抚州", "宜春", "吉安",
    "聊城", "德州", "东营", "泰安", "济宁", "枣庄", "日照", "威海", "菏泽", "莱芜",
    "新乡", "安阳", "焦作", "许昌", "平顶山", "南阳", "信阳", "商丘", "周口", "驻马店",
    "三门峡", "漯河", "濮阳", "鹤壁", "随州", "荆门", "鄂州", "黄冈", "咸宁", "恩施",
    "邵阳", "益阳", "娄底", "怀化", "永州", "张家界", "湘西", "肇庆", "江门", "湛江",
    "茂名", "揭阳", "梅州", "清远", "韶关", "阳江", "河源", "云浮", "汕尾", "潮州",
    "梧州", "钦州", "贵港", "玉林", "百色", "河池", "贺州", "来宾", "崇左", "防城港",
    "儋州", "琼海", "文昌", "自贡", "攀枝花", "广元", "遂宁", "内江", "乐山", "眉山",
    "雅安", "资阳", "达州", "广安", "巴中", "凉山", "甘孜", "阿坝", "六盘水", "安顺",
    "毕节", "铜仁", "黔东南", "黔南", "黔西南", "玉溪", "保山", "昭通", "普洱", "临沧",
    "楚雄", "红河", "文山", "德宏", "怒江", "迪庆", "铜川", "渭南", "汉中", "安康",
    "商洛", "榆林", "平凉", "庆阳", "定西", "陇南", "武威", "张掖", "金昌", "嘉峪关",
    "白银", "临夏", "甘南", "海东", "海西", "格尔木", "石嘴山", "吴忠", "固原", "中卫",
    "克拉玛依", "吐鲁番", "哈密", "阿克苏", "和田", "巴音郭楞", "昌吉", "博尔塔拉",
    "香港", "澳门", "台北", "高雄", "台中",
]
# 省 / 自治区（排在具体城市之后匹配，避免"湖南/长沙"抢位）
PROVINCES = [
    "河北", "山西", "辽宁", "吉林", "黑龙江", "江苏", "浙江", "安徽", "福建", "江西",
    "山东", "河南", "湖北", "湖南", "广东", "海南", "四川", "贵州", "云南", "陕西",
    "甘肃", "青海", "台湾", "内蒙古", "广西", "西藏", "宁夏", "新疆",
]
# 最长优先；同长时具体城市优先于省名
_CITY_ALL = (sorted([c for c in dict.fromkeys(CITY_BASE) if c not in PROVINCES], key=len, reverse=True)
             + sorted(PROVINCES, key=len, reverse=True))

CITY_HINTS = CITY_BASE  # 兼容旧名（derive_interests 用它统计）
# 本地公历节日（无网降级用）；农历节日走 timor.tech 网络源
SOLAR_HOLIDAYS = [
    ("01-01", "元旦"), ("02-14", "情人节"), ("03-08", "妇女节"),
    ("04-05", "清明"), ("05-01", "劳动节"), ("06-01", "儿童节"),
    ("09-10", "教师节"), ("10-01", "国庆节"), ("12-25", "圣诞节"),
]

_TOPIC_RE = re.compile(r"[\u4e00-\u9fa5A-Za-z0-9]+")
# 简单停用词（助词/常见无信息量词）
_STOP = set("的了我你他她它是这那和也都不就在有说想什么一下一个我们你们他们可以吗吧呢啊的过会要能没".strip())


def derive_interests(mems, top=None):
    """从记忆文本统计兴趣主题 / 城市 / 五志 tag，返回 {topics, city}。

    mems: 每条含 'text' 的 dict 列表（query_all/export 均可）。
    纯本地、零依赖、不绑定个人。"""
    top = top if top is not None else C.INTEL_TOPIC_TOP
    topic_count = {t: 0 for t in TOPICS}
    city_count = {}
    for m in mems or []:
        text = str(m.get("text") or "")
        for t in TOPICS:
            if t in text:
                topic_count[t] += 1
        for c in CITY_HINTS:
            if c in text:
                city_count[c] = city_count.get(c, 0) + 1
    topics = sorted((t for t, c in topic_count.items() if c > 0),
                    key=lambda t: -topic_count[t])[:top]
    city = max(city_count, key=city_count.get) if city_count else ""
    return {"topics": topics, "city": city}


def relevance(text, keywords):
    """文本与兴趣关键词的相关性（词重叠 / 长度归一 → 0~1）。纯本地。"""
    text = str(text or "")
    if not text or not keywords:
        return 0.0
    hits = sum(1 for k in keywords if k and k in text)
    if hits == 0:
        return 0.0
    base = hits / len(keywords)
    # 标题越短命中越多 → 相关度越高（粗 BM25 感）
    return min(1.0, base * (1.0 + 1.0 / (1.0 + len(text) / 60.0)))


# ---------- 网络获取（带超时，失败返回 None，绝不抛） ----------
def fetch(url, timeout=5):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except Exception:
        return None, None


def _parse_feed(xml):
    """解析 RSS XML → [{title, link}]。纯标准库。"""
    import xml.etree.ElementTree as ET
    items = []
    if not xml:
        return items
    try:
        root = ET.fromstring(xml)
        for it in root.iter("item"):
            title = it.findtext("title") or ""
            link = it.findtext("link") or ""
            if title.strip():
                items.append({"title": title.strip(), "link": link.strip()})
    except Exception:
        pass
    return items


def _city_key(ns):
    """城市键按 ns 隔离（与 fuse / proactive / wuxing 等键同一约定）。"""
    return f"{C.INTEL_WEATHER_CITY_KEY}:{ns}"


# 口语里裹在地名外面的虚词（从左剥、从右剥）
_LEAD_JUNK = ("现在就在", "现在在", "目前就在", "目前", "现在", "就在", "我在", "人也", "人在",
              "我家在", "家在", "已经", "刚搬来", "搬来", "暂时", "最近在", "我一直", "在")
_TAIL_JUNK = ("这边", "那边", "这里", "那里", "这儿", "那儿", "附近", "上班", "工作", "出差",
              "旅游", "玩", "住", "生活", "呆着", "天气")
_STOP = ("了", "啦", "呢", "吗", "吧", "啊", "呀", "哦", "嘛", "的", "哈", "哎", "诶")


def _clean_frag(frag):
    """把口语片段削成候选地名（"现在在武汉待着" → "武汉"）。"""
    f = str(frag or "").strip().strip("，。！？、,.!?：:；; 　")
    for p in _LEAD_JUNK:
        if f.startswith(p):
            f = f[len(p):]
            break
    for s in _TAIL_JUNK:
        if f.endswith(s) and len(f) > len(s):
            f = f[: -len(s)]
            break
    changed = True
    while changed and f:
        changed = False
        for s in _STOP:
            if f.endswith(s) and len(f) > 2:
                f = f[:-1]
                changed = True
    return f.strip()


def extract_city(text):
    """从任意自然语言里识出城市名 → 标准地名；识不出返回 None。

    通用性：不要求固定句式（"我在武汉""现在在武汉""武汉今天冷吗""下周去北京出差"
    都能认），也不绑定任何人——只依赖通用地名表，可随时扩充 CITY_BASE。
    """
    t = " ".join(str(text or "").split()).strip()
    if not t:
        return None
    # ① 地名表最长匹配：句子里出现地名即认（"现在在武汉"里的"武汉"也能命中，顺带自愈脏值）
    for c in _CITY_ALL:
        if c in t:
            return c
    # ② "在/到/去/回/住 + 片段" 里可能是表外小地名：取片段，削虚词后再核一遍
    m = re.search(r"(?:在|到|去|回|住|从)[\u4e00-\u9fa5]{2,6}", t)
    if m:
        frag = _clean_frag(m.group(0)[1:])
        if 2 <= len(frag) <= 6:
            for c in _CITY_ALL:
                if c in frag:
                    return c
            if frag[-1] in "市区县" and 2 <= len(frag) <= 5:
                return frag[:-1]
    # ③ 整串就是地名（可带"市/区/县/省"后缀）
    frag = _clean_frag(t)
    if 2 <= len(frag) <= 6:
        if frag.endswith(("市", "区", "县", "省")) and len(frag) <= 5:
            return frag[:-1]
        if frag in _CITY_ALL:
            return frag
    return None


def set_city(store, ns, city):
    """记住用户所在/关心的城市（通用：不硬编码任何城市，首次由用户回答写入）。

    整句也能进：先抽地名再存（"我现在在武汉上班" → "武汉"）。
    返回写入成功的城市字符串；抽不出地名或为空 → None（不写、不清旧值）。
    """
    raw = " ".join(str(city or "").split()).strip()
    if not raw:
        return None
    c = extract_city(raw)
    if not c:
        return None
    store.set_kv(_city_key(ns), c)
    # 顺手同步五行上下文里的 city 字段（两处口径别打架；没有该键就跳过）
    try:
        meta_key = f"wuxing:meta:{ns}"
        meta = store.get_kv(meta_key)
        if meta and "city=" in meta:
            store.set_kv(meta_key, re.sub(r"city=[^,]*(?=,|$)", f"city={c}", meta))
    except Exception:
        pass
    return c


def get_city(store, ns):
    """读已记住的城市：先取本 ns，再回退部署级全局键（显式配置优先）。

    读到的旧脏值（如"现在在武汉"）就地清洗并回写标准名——不改语义，只去包装词。
    """
    raw = (store.get_kv(_city_key(ns)) or store.get_kv(C.INTEL_WEATHER_CITY_KEY) or "").strip()
    if not raw:
        return ""
    c = extract_city(raw)
    if not c:
        return raw  # 认不出就原样返回，别把用户配置弄丢
    if c != raw:
        try:
            store.set_kv(_city_key(ns), c)
        except Exception:
            pass
    return c


def fetch_weather(city):
    """按城市拉天气（wttr.in 免 key）。失败返回 None。"""
    if not city:
        return None
    try:
        url = C.INTEL_WEATHER_URL.format(city=urllib.parse.quote(city))
    except Exception:
        return None
    st, body = fetch(url)
    if st != 200 or not body or not body.lstrip().startswith("{"):
        return None
    try:
        j = json.loads(body)
        cur = (j.get("current_condition") or [{}])[0]
        desc = ((cur.get("weatherDesc") or [{}])[0].get("value")) or ""
        return {"city": city, "temp_c": cur.get("temp_C"), "desc": desc.strip()}
    except Exception:
        return None


def weather_line(store, ns, ttl=None):
    """给注入用的天气一句话：已知城市才能出，带 30 分钟缓存，失败时回退旧值。

    通用之处：城市来自 get_city（用户自己说的，不写死）；无网/超时只是少一行，
    绝不影响注入本身。城市变了缓存自动失效（比对 cached["city"]）。
    """
    ttl = C.INTEL_WEATHER_TTL if ttl is None else ttl
    city = get_city(store, ns)
    if not city:
        return None
    key = f"intel:weather:{ns}"
    cached = None
    try:
        raw = store.get_kv(key)
        if raw:
            cached = json.loads(raw)
    except Exception:
        cached = None
    now = time.time()
    if cached and cached.get("city") == city and now - cached.get("at", 0) < ttl:
        return _fmt_weather(cached, stale=False)
    w = fetch_weather(city)
    if w and w.get("temp_c") is not None:
        w["at"] = now
        try:
            store.set_kv(key, json.dumps(w, ensure_ascii=False))
        except Exception:
            pass
        return _fmt_weather(w, stale=False)
    if cached and cached.get("city") == city:
        return _fmt_weather(cached, stale=True)
    return None


_WDESC_CN = {
    "sunny": "晴", "clear": "晴", "partly cloudy": "多云", "cloudy": "多云", "overcast": "阴",
    "light drizzle": "毛毛雨", "light rain": "小雨", "moderate rain": "中雨", "heavy rain": "大雨",
    "light rain shower": "阵雨", "patchy rain possible": "零星小雨", "patchy rain nearby": "周边有雨",
    "thundery outbreaks possible": "可能有雷阵雨", "light snow": "小雪", "moderate snow": "中雪",
    "heavy snow": "大雪", "patchy snow possible": "零星雪", "mist": "薄雾", "fog": "雾",
    "freezing fog": "冻雾", "smog": "雾霾", "haze": "霾",
}


def cn_desc(desc):
    """天气描述转中文：先精确查表，再按关键词兜底（wttr.in 的描述是有限的英文短语）。

    作用：模型和用户看到的都是中文，不依赖某个固定城市或固定译文表。
    """
    d = " ".join(str(desc or "").split()).strip()
    if not d:
        return "未知"
    low = d.lower()
    if low in _WDESC_CN:
        return _WDESC_CN[low]
    for kw, cn in (("thunder", "雷阵雨"), ("snow", "雪"), ("drizzle", "毛毛雨"), ("rain", "雨"),
                   ("smog", "雾霾"), ("haze", "霾"), ("fog", "雾"), ("mist", "雾"),
                   ("overcast", "阴"), ("cloud", "多云"), ("sunny", "晴"), ("clear", "晴")):
        if kw in low:
            return cn
    return d


def _fmt_weather(w, stale=False):
    hm = time.strftime("%m-%d %H:%M", time.localtime(w.get("at") or 0))
    s = f"{w.get('city')} · {cn_desc(w.get('desc'))} · {w.get('temp_c')}°C"
    return ("上次查到：" + s + "（" + hm + "）") if stale else (s + "（" + hm + " 更新）")


# ---------- 时间感知（纯本地，零网络） ----------
# 天干 / 地支 / 星期（中文）
_GAN = "甲乙丙丁戊己庚辛壬癸"
_ZHI = "子丑寅卯辰巳午未申酉戌亥"
_WEEK_CN = "一二三四五六日"

# 24 节气近似公历日期（(月, 日) 每年浮动 ±1 天，对"现在处在哪个节气"够用）
JIEQI_AT = [
    (1, 6, "小寒"), (1, 20, "大寒"), (2, 4, "立春"), (2, 19, "雨水"),
    (3, 6, "惊蛰"), (3, 21, "春分"), (4, 5, "清明"), (4, 20, "谷雨"),
    (5, 6, "立夏"), (5, 21, "小满"), (6, 6, "芒种"), (6, 21, "夏至"),
    (7, 7, "小暑"), (7, 23, "大暑"), (8, 8, "立秋"), (8, 23, "处暑"),
    (9, 8, "白露"), (9, 23, "秋分"), (10, 8, "寒露"), (10, 23, "霜降"),
    (11, 7, "立冬"), (11, 22, "小雪"), (12, 7, "大雪"), (12, 22, "冬至"),
]


def _phase_of(hour):
    """小时 → 时段词（中文口语的"现在"。23–5 深夜，按作息分段）。"""
    if hour < 5:
        return "深夜"
    if hour < 7:
        return "清晨"
    if hour < 9:
        return "早晨"
    if hour < 11:
        return "上午"
    if hour < 13:
        return "中午"
    if hour < 17:
        return "下午"
    if hour < 19:
        return "傍晚"
    if hour < 23:
        return "晚上"
    return "深夜"


def _jieqi_span(ymd):
    """当前节气区间 → (上一个节气, 下一个节气, 距下一个还有几天)。跨年自动处理。"""
    import datetime as _dt
    y, mo, d = ymd
    today = _dt.date(y, mo, d)
    cands = []
    for yy in (y - 1, y, y + 1):
        for (m, dd, name) in JIEQI_AT:
            try:
                cands.append((_dt.date(yy, m, dd), name))
            except ValueError:
                continue
    pre = max((c for c in cands if c[0] <= today), default=None, key=lambda x: x[0])
    nxt = min((c for c in cands if c[0] > today), default=None, key=lambda x: x[0])
    if not pre or not nxt:
        return None, None, None
    return pre[1], nxt[1], (nxt[0] - today).days


def _gap_text(hours):
    """对话间隔 → 口语（人不会说"3.47 小时前"）。"""
    if hours is None:
        return "还没有对话记录"
    if hours < 1:
        return "刚刚还在聊"
    if hours < 6:
        return f"几小时前聊过（约{int(hours)}小时）"
    if hours < 24:
        return f"{int(hours)}小时前聊过"
    if hours < 48:
        return "昨天聊过"
    d = int(hours // 24)
    if d < 7:
        return f"{d}天前聊过"
    return "有一阵没聊过了"


def _active_window(hist, min_share=0.5):
    """小时直方图 → 通常活跃的连续时段 [start, end]（end 为闭区间后一格，可跨零点）。

    min_share：相邻小时计数达到峰值的多少算"也在场"（默认 0.5，避免噪声小时被拉进窗口）。
    """
    peak = max(hist) if hist else 0
    if peak <= 0:
        return None
    peak_h = hist.index(peak)
    th = max(1, int(peak * min_share))
    start = peak_h
    for _ in range(12):
        p = (start - 1) % 24
        if hist[p] >= th:
            start = p
        else:
            break
    end = peak_h
    for _ in range(12):
        n = (end + 1) % 24
        if hist[n] >= th:
            end = n
        else:
            break
    return start, (end + 1) % 24  # end 用"下一小时"表示，便于显示 22–02


def _win_text(win):
    if not win:
        return ""
    s, e = win
    e_last = e - 1 if e > s else (e - 1) % 24
    if e_last == s:
        return f"{s} 点前后"
    return f"{s} 点到 {e_last} 点之间"


def social_context(store, ns):
    """对话间隔 + 对方活跃时段（纯本地统计，零网络）。

    数据源：该 ns 全部记忆的 born_at（记忆写入 ≈ 对方发言时刻）。
    给注入用：让她知道"多久没聊了""对方一般什么时候在线"——这是拟人感知，
    不写任何"要主动联系"的指令，只陈述事实。
    """
    mems = []
    try:
        mems = store.query_all(ns, limit=500) or []
    except Exception:
        mems = []
    now = time.time()
    latest = 0.0
    hist = [0] * 24
    for m in mems:
        try:
            b = float(m.get("born_at") or 0)
        except Exception:
            continue
        if b <= 0:
            continue
        h = time.localtime(b).tm_hour
        hist[h] += 1
        if b > latest:
            latest = b
    gap_h = (now - latest) / 3600.0 if latest else None
    win = _active_window(hist)
    return {
        "gap_hours": round(gap_h, 2) if gap_h is not None else None,
        "gap_text": _gap_text(gap_h),
        "active_window": list(win) if win else None,
        "active_text": _win_text(win),
    }


def time_context(t=None):
    """当前时间画像（纯本地）：时刻/星期/时段/时辰干支/日干支/节气。

    给注入用的一行自然语言：她是"活在什么时候的人"，不是报时器——
    深夜/清晨这类时刻会自然影响说话节奏与长度，由模型自己体会，不写指令。
    不做任何网络调用，永不抛（异常各段独立降级）。
    """
    lt = t or time.localtime()
    y, mo, d = lt.tm_year, lt.tm_mon, lt.tm_mday
    hour, minute = lt.tm_hour, lt.tm_min
    week = "周" + _WEEK_CN[lt.tm_wday % 7]  # tm_wday: 0=周一
    phase = _phase_of(hour)
    zhi_idx = ((hour + 1) // 2) % 12  # 子(23-1)→0，丑(1-3)→1 ...
    shichen = _ZHI[zhi_idx] + "时"
    day_gz = ""
    hour_gz = ""
    try:
        from .wuxing import ganzhi_day, ganzhi_hour
        day_i = ganzhi_day((y, mo, d))
        hour_i = ganzhi_hour(day_i, hour)
        day_gz = _GAN[day_i % 10] + _ZHI[day_i % 12]
        hour_gz = _GAN[hour_i % 10] + _ZHI[hour_i % 12]
    except Exception:
        pass
    try:
        pre_jq, next_jq, next_days = _jieqi_span((y, mo, d))
    except Exception:
        pre_jq, next_jq, next_days = None, None, None

    line = f"{mo}月{d}日 {week} {phase}{hour:02d}:{minute:02d}，{shichen}"
    if day_gz:
        line += f"（{day_gz}日 {hour_gz}时）"
    if pre_jq and next_jq:
        line += f"；节气：{pre_jq}后，{next_jq}还有{next_days}天"
    return {
        "ymd": f"{y:04d}-{mo:02d}-{d:02d}",
        "hm": f"{hour:02d}:{minute:02d}",
        "week": week,
        "phase": phase,
        "shichen": shichen,
        "day_ganzhi": day_gz,
        "hour_ganzhi": hour_gz,
        "jieqi_prev": pre_jq,
        "jieqi_next": next_jq,
        "jieqi_days": next_days,
        "line": line,
    }


def fetch_holidays(year):
    """拉全年节假日（timor.tech 免 key）。失败返回空 dict。"""
    st, body = fetch(C.INTEL_HOLIDAY_URL.format(year=year))
    if st != 200 or not body:
        return {}
    try:
        j = json.loads(body)
        return j.get("holiday") or {}
    except Exception:
        return {}


def solar_today(mm_dd):
    """本地公历节日（无网降级）：返回 (date, name) 或 None。"""
    for d, name in SOLAR_HOLIDAYS:
        if d == mm_dd:
            return d, name
    return None


class Intel:
    """一次主动情报收集：兴趣 → 外部源 → 相关话题候选（无网降级不抛）。"""

    def __init__(self, store, ns, no_net=False):
        self.store = store
        self.ns = ns
        self.no_net = no_net
        # 通用：城市由用户自己说（每个 ns 各记一份；也兼容部署级全局键）
        self.city = get_city(store, ns) or None

    def collect(self, mems):
        """返回 {interests, city, weather, holidays, news, candidate}。"""
        interests = derive_interests(mems)
        city = self.city or interests.get("city") or ""
        weather = None
        news = []
        holidays = []
        if not self.no_net:
            weather = fetch_weather(city) if city else None
            try:
                news = self._relevant_news(interests.get("topics") or [])
            except Exception:
                news = []
            try:
                holidays = self._nearby_holidays()
            except Exception:
                holidays = []
        # 本地公历节日（始终尝试，无网也能给）
        try:
            today = time.strftime("%m-%d")
            solar = solar_today(today)
            if solar and not any(h.get("date") == solar[0] for h in holidays):
                holidays.insert(0, {"date": solar[0], "name": solar[1], "type": "公历"})
        except Exception:
            pass
        candidate = self._compose(interests, weather, holidays, news)
        return {
            "interests": interests,
            "city": city,
            "weather": weather,
            "holidays": holidays[:6],
            "news": news[:C.INTEL_MAX_ITEMS],
            "candidate": candidate,
        }

    def _relevant_news(self, topics):
        out = []
        for feed in C.INTEL_FEEDS:
            st, xml = fetch(feed.get("url", ""))
            if st != 200 or not xml:
                continue
            for item in _parse_feed(xml)[:C.INTEL_MAX_ITEMS]:
                score = relevance(item.get("title", ""), topics)
                if score >= C.INTEL_MIN_SCORE:
                    out.append({**item, "score": round(score, 3)})
        out.sort(key=lambda x: -x["score"])
        return out[:C.INTEL_MAX_ITEMS]

    def _nearby_holidays(self):
        year = time.strftime("%Y")
        data = fetch_holidays(year)
        out = []
        today = time.strftime("%m-%d")
        # 今天的节假日（官方口径）
        if today in data:
            h = data[today]
            out.append({"date": today, "name": h.get("name", "节日"), "type": "节日"})
        return out

    def _compose(self, interests, weather, holidays, news):
        """合成一句"主动话题"文本（供发送）。无任何命中 → 空串（不打扰）。

        天气不参与主动话题：对方没问就提天气，就变成每天一条天气播报，不像人。
        天气只走被动注入（对方这轮聊到冷暖/穿衣时才给她一句背景）。
        """
        parts = []
        for h in holidays:
            parts.append(f"今天是{h.get('name')}")
        for n in news:
            parts.append(f"看到一条和你关心的「{n.get('title', '')[:40]}」有关的消息")
        return " ".join(parts) if parts else ""
