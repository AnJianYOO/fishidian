# -*- coding: utf-8 -*-
"""fishidian_core.scoring —— 文本特征（importance/arousal/valence）与 BoW 向量检索
（bge 可插拔：embed_backend='bge' 时由插件层注入向量，本模块保留接口）"""
from __future__ import annotations

import math
import re

from . import config as C

# 负面词（安全熔断用）：触发词面，权重=强度
NEG_LEX = {
    "死": 9, "自杀": 10, "不想活": 10, "杀": 8, "绝望": 8, "崩溃": 7, "恨": 7,
    "废物": 6, "垃圾": 5, "没用": 5, "活着没意思": 9, "消失": 6, "毁灭": 8, "毁了我": 8,
    "再也不": 5, "永远不": 5, "恶心": 6, "去死": 10, "毁灭吧": 9, "痛苦": 6,
    "抑郁": 7, "焦虑": 5, "害怕": 5, "恐惧": 6, "愤怒": 6, "委屈": 5, "难过": 5,
    "哭": 5, "疼": 5, "累": 4, "烦": 4, "讨厌": 5, "厌恶": 5, "受不了": 6,
}
# 重要词：决定 importance 的事件/关系词
IMP_LEX = {
    "住院": 9, "手术": 9, "诊断": 8, "生病": 8, "去世": 10, "离世": 10, "亲人": 8,
    "结婚": 7, "离婚": 8, "分手": 7, "失业": 7, "裁员": 7, "升职": 6, "述职": 6,
    "offer": 7, "面试": 6, "考试": 6, "考研": 7, "失利": 6, "失败": 6, "低谷": 7,
    "答辩": 6, "论文": 6, "毕业": 6, "买房": 7, "搬家": 5, "车祸": 9,
    "出事": 8, "报警": 7, "被骗": 7, "亏": 5, "欠": 6, "还债": 6, "创业": 7,
    "签约": 6, "合同": 6, "体检": 6, "报告": 5, "结果": 5, "确诊": 9,
}
# 正面/负面效价词
VAL_POS = {"开心": 5, "高兴": 5, "喜欢": 4, "爱": 6, "太好了": 5, "成功": 5, "通过": 4,
           "拿到": 4, "中奖": 5, "庆祝": 4, "满意": 4, "幸福": 5, "感动": 4, "温暖": 4}
VAL_NEG = {"难过": -5, "伤心": -6, "痛苦": -6, "愤怒": -5, "失望": -5, "崩溃": -7,
           "害怕": -5, "恐惧": -6, "焦虑": -4, "委屈": -4, "孤独": -5, "绝望": -8,
           "哭": -5, "难受": -5, "生气": -5, "郁闷": -4, "烦": -3}
# 主题词表（cluster A 档）：新记忆自动归类，同主题互相加固、检索有标签。
# 每项 (主题名, 触发词表)；topic_of 按顺序返回首个命中主题（先列的主题优先）。
TOPIC_LEX = [
    ("职业", ("升职", "述职", "offer", "面试", "工作", "同事", "老板", "项目", "加班",
              "辞职", "裁员", "失业", "创业", "签约", "合同", "代码", "建模", "3d",
              "maya", "zbrush", "客户", "需求", "产品", "绩效", "年终奖", "简历",
              "试用期", "上班", "下班", "开会", "工资", "通宵", "改稿", "甲方", "公司")),
    ("健康", ("住院", "手术", "体检", "生病", "诊断", "确诊", "吃药", "医院", "医生",
              "复查", "血糖", "血压", "睡眠", "失眠", "头疼", "胃", "运动", "健身",
              "跑步", "疫苗", "牙", "近视", "腰", "膝盖", "过敏", "发烧")),
    ("家庭", ("奶奶", "爷爷", "妈妈", "爸爸", "家人", "家", "父母", "孩子", "儿子",
              "女儿", "亲戚", "生日", "团聚", "老家", "结婚", "离婚", "兄弟", "姐妹",
              "舅舅", "姑姑", "姥姥", "姥爷")),
    ("情感", ("开心", "难过", "伤心", "喜欢", "爱", "分手", "恋爱", "对象", "女朋友",
              "男朋友", "吵架", "和好", "孤独", "委屈", "感动", "幸福", "想念", "挂念",
              "心动", "暧昧", "表白", "生分", "疏远", "冷漠")),
    ("学业", ("考试", "考研", "论文", "答辩", "毕业", "导师", "学校", "上课", "成绩",
              "录取", "复试", "学历", "课设", "重修", "绩点", "图书馆")),
    ("财务", ("买房", "买车", "贷款", "存款", "理财", "股票", "基金", "亏损", "赚钱",
              "省钱", "房租", "信用卡", "欠", "还债", "报销", "账单", "月供", "涨薪",
              "降薪", "副业")),
    ("兴趣", ("游戏", "电影", "音乐", "动漫", "小说", "篮球", "足球", "画画", "摄影",
              "旅行", "美食", "咖啡", "宠物", "猫", "狗", "钓鱼", "徒步", "爬山",
              "吉他", "唱歌")),
    ("生活", ("搬家", "邻居", "装修", "家具", "快递", "买菜", "做饭", "天气", "下雨",
              "堵车", "地铁", "打车", "停电", "停水", "维修", "钥匙", "小区", "吃饭",
              "降温", "睡觉", "晚安")),
    ("成长", ("低谷", "失败", "反思", "目标", "计划", "习惯", "坚持", "改变", "成长",
              "复盘", "自律", "拖延", "焦虑", "迷茫", "振作")),
]


def topic_of(text: str):
    """文本 → 主题标签（cluster）；无命中返回 None。A 档词表打标。"""
    low = text.lower()
    for name, words in TOPIC_LEX:
        for w in words:
            if w in low:
                return name
    return None


def neg_strength(text: str) -> float:
    """负面强度：命中负面词的加权和（用于熔断）。"""
    s = 0.0
    for w, wt in NEG_LEX.items():
        if w in text:
            s += wt
    return s


def score_text(text: str):
    """文本 → (importance, arousal, valence, cluster)。规则打分（v1；bge/LLM 可换）。
    cluster 为主题词表打标（A 档），无命中为 None。"""
    imp = 1.0
    for w, wt in IMP_LEX.items():
        if w in text:
            imp = max(imp, wt)
    if len(text) > 80:
        imp = min(10.0, imp + 0.5)  # 长陈述倾向重要
    val = 0.0
    for w, wt in VAL_POS.items():
        if w in text:
            val += wt
    for w, wt in VAL_NEG.items():
        if w in text:
            val += wt
    val = max(-10.0, min(10.0, val))
    aro = abs(val) if val else (neg_strength(text) * 0.5 if neg_strength(text) else 1.0)
    aro = max(0.0, min(10.0, aro + 0.5))
    return round(imp, 3), round(aro, 3), round(val, 3), topic_of(text)


# ---------------- BoW 检索 ----------------

def _tokens(text: str):
    return re.findall(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+", text.lower())


def bow(text: str) -> dict:
    toks = _tokens(text)
    out = {}
    for t in toks:
        out[t] = out.get(t, 0) + 1
    return out


def cos_vec(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    inter = sum(v * b.get(k, 0) for k, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    if na == 0 or nb == 0:
        return 0.0
    return inter / (na * nb)


class Embed:
    """embed_backend: bow（默认，零依赖）| bge（由插件层注入向量函数）。"""

    def __init__(self, backend: str = "bow", bge_fn=None):
        self.backend = backend
        self.bge_fn = bge_fn

    def similarity(self, q: str, text: str) -> float:
        if self.backend == "bge" and self.bge_fn:
            return float(self.bge_fn(q, text))
        return cos_vec(bow(q), bow(text))

    def omega_min(self) -> float:
        return 0.65 if self.backend == "bge" else C.OMEGA_MIN
