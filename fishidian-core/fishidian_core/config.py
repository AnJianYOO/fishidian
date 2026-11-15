# -*- coding: utf-8 -*-
"""fishidian_core.config —— 全部运行时参数（来源：早期原型里试出来的值，勿随意改动）"""
from __future__ import annotations

# ---------- 蓄泄晋升 ----------
R_BASE = 0.5          # R = R_BASE + R_IMP*imp + R_ARO*A + R_VAL*|v|
R_IMP = 0.5
R_ARO = 0.2
R_VAL = 0.1
DELTA_R = 1.5         # 真命中（adopt）才加
MAX_R = 10.0
THETA_REN = 3.0       # 孕育门槛
THETA_DU = 8.0        # 督脉（身份主线）门槛
R_ARCHIVE = 0.5       # 降温地板（衰减到此为止，不再自动归档；沉底由容量溢出决定）
PROTECT_H = 12.0      # 强制召回保护期（h）
UNRIPE_H = 504.0      # 久候未熟（21 天）
R_UNRIPE = 2.0
FORCE_HITS = 3

# ---------- 三池半衰期 ----------
HL_BLOOD = 24.0       # 血海·冲脉（h）：一天的对话还热着。6h 会让当天的事隔夜就凉透
HL_YUN = 168.0        # 孕育·任脉
HL_DU = 2160.0        # 督脉·身份主线（90 天）
# 血海容量。参照同类项目的口径换算法：
#   Letta/MemGPT 的 core memory 按字符预算算（单块默认 2000 字符），本项目记忆均值 29 字 → 约 69 条；
#   本项目实测写入速率 2.9 条/小时 → 24 小时约 70 条。
# 取 72：约等于"最近一天的对话量"，也是 2000 字符预算下的同量级。注入成本由 recall(k) + INJECT_BUDGET 控制，与此无关。
CAP_BLOOD = 72
# 满池时新记忆必须强于池内最弱者 30% 才有资格挤掉它；否则新记忆自己沉底，不顶掉旧人（防"进一出一"等值互换）
OVERFLOW_KEEP = 0.7
MERGE_BLOOD_THETA = 0.9   # 血海合并阈值（短句必须"几乎同字"才合并，防误吞）；孕育/督脉用 0.65

# ---------- 检索五路 ----------
W_SEM = 0.46          # 语义主导
W_SIM = 0.18
W_REL = 0.14
W_TIME = 0.11
W_IMP = 0.11

# ---------- 当位门控 ----------
OMEGA_MIN = 0.15      # 模拟模式；bge 模式 0.65（embed_backend='bge' 时切换）
CLUSTER_DELTA = 0.05
# 簇扩散的天花板 = 该条自身原生 R × 此倍率。
# 原实现直接封顶 MAX_R(10)，导致同簇条目每 10 分钟 +0.05 与衰减赛跑、一路涨到 10.00：
# 在实际运行的库里见过：已有 4 条停在 10.00，其中原生值只有 1.x —— R 全等后召回排序
# 失去区分度，注入被最早那几条占满。给"互为支撑"留 20% 加成，但不再无限涨。
CLUSTER_CAP_MULT = 1.2

# ---------- 安全熔断 ----------
FUSE_WIN = 8          # 滑动窗口轮数
NEG_FRAC = 0.6        # 窗口内负面占比触发
NEG_IMP_MIN = 5.0     # 单条负面强度下限
SUSPEND_N = 4         # 挂起轮数
COOLDOWN = 3          # 冷却轮数
FUSE_SAFE = -0.2      # 钳制线（emotion_boost 下界）

# ---------- 中庸节流 ----------
THETA_JIE = 0.12      # 单条情绪贡献封顶
THETA_HE = 4.0        # 累计过载节泄
RHYTHM_T = 24.0       # 周期（h）
RHYTHM_OFF = 0.0
RHYTHM_AMP = 0.1

# ---------- 去我执 / 长尾 ----------
GAMMA_EGO = 0.2       # |v|>=9.0 极端记忆情绪加成衰减系数
TAIL_IMP = 7          # 重要低频记忆保护线
TAIL_FLOOR = 2.0      # 长尾保底 R

# ---------- 体质画像 P ----------
LR_P = 0.03           # P 更新速率（慢演化）
EMO_CAP = 0.5         # 情绪敏感上限
P_INIT = (0.0, 1.0, 0.0, 0.0)      # 平和 {髓海系数, 五志权重, 情志耦合度, 蓄泄节律}
P_SENS = (-0.05, 0.90, 0.30, -0.50)  # 感性
P_RATIO = (0.05, 1.15, -0.30, 0.50)  # 理性
P_BOUNDS = (-1.0, 1.5)               # 边界钳位

# ---------- 注入 ----------
INJECT_TOP_K = 6
INJECT_BUDGET = 600   # 注入字符上限
# 注入文本窗口（评审 §六② 修复）：注入里露出的字数 = 判引用比对的字数，必须是同一个常量。
# 旧版注入 [:60]、判引用 [:120]，关键实体落在 60–120 字之间时，她根本看不到，
# 模型就不会说，引用永远判不中 —— 那条记忆结构性升不了级。
INJECT_TEXT_CAP = 100
# 真引用判定（P0-2）：回复里要真的出现这条记忆的实体/数字才算引用
CITE_MIN_LCS = 3          # 与记忆文本的最长公共子串至少 3 字（且不含停用词）
CITE_COOLDOWN_H = 6.0     # 同一记忆 6 小时内不重复 adopt（防"每轮都加"）
SWEEP_INTERVAL_MIN = 10

# ---------- 注入前三道闸（R34 / D-028，D-029 升 P0） ----------
# 原来 recall() 只把 adopt 变成标签里的两个字（"采纳"/"参考"），两种都照样进 prompt，
# recall 到 build_injection 之间没有任何过滤层——"她记错事"就出在这里。
INJECT_MIN_SIM = 0.30     # ① 有效闸：情境层里非当位（adopt=False）且相似度低于此 → 与本句无关，不占预算
INJECT_SUSPECT_MAX = 1    # ③ 存疑闸：只依稀记得的条目最多进 1 条（多了整段注入会变成"好像好像"）
INJECT_DUP_JAC = 0.85     # ② 重复闸：与已入选条目字符集 Jaccard ≥ 此值 → 判重
INJECT_DUP_LCS = 12       # ② 重复闸补判：最长公共子串 ≥ 此值且长度接近 → 判重

# ---------- 写入侧两闸（R35 / D-028） ----------
# 崽崽那套是"攒批 + 抽取去重 + 日上限"；我们不做抽取（0 模型），只做机械去重与配额。
DEDUP_SIM = 0.85          # 与近 24h 内已有记忆字符集重叠 ≥ 此值 → 不新建（只 touch）
WRITE_DEDUP_WIN_H = 24.0  # 去重回溯窗口（h）
WRITE_DAILY_CAP = 200     # 每 ns 每日新记忆上限（对齐崽崽的 200，超了只记审计、不入库）

# ---------- 单写者（R36 / D-028） ----------
# QQ 桥 + 插件 + 巡检可能同时写同一个 db。WAL 已允许并发读、单写；这里补
# busy_timeout 与写重试，让"database is locked"不冒到聊天上。
DB_BUSY_TIMEOUT_MS = 8000
DB_WRITE_RETRY = 3

# ---------- 退役判据（R39 / D-029 第 ⑦ 条） ----------
# 38 条规划里一条"删"都没有 —— 只进不出的池子是垃圾场。
# 这不是"删除"，是归档（status=archived）：可查、可恢复，只是不再参与召回与注入。
RETIRE_R = 0.55          # R 低于此才够格退役（高于它说明还有价值，交给衰减慢慢来）
RETIRE_QUIET_DAYS = 90   # 连续 N 天没被召回（last_hit_at/last_at）才判
RETIRE_MIN_AGE_DAYS = 30 # 至少存在 N 天（刚写进来的不判）

# ---------- 新旧陈述冲突裁决（R37 / F-043，R9 的最小切片） ----------
# 问题：R35 的数字守卫是**故意**的——数字变了说明事实变了，必须新记一条，不能被吞。
# 但两条都留在池里、都被召回，注入里就自相矛盾（"约了3点"和"改到4点了"并排给她看）。
# 裁决的最小可行形态不是语义理解，是**取代**：新条在册后，旧条 status=superseded（不再进注入），
# 并留 superseded_by 指回新条 —— 可追溯、可恢复，和 archived 一样不是删除。
SUPERSEDE_SIM = 0.85     # 「去掉数字后的骨架」相似度（difflib ratio，不是字符集重叠）
SUPERSEDE_WIN_H = 72.0   # 回溯 3 天（事实变更常隔天说，比 24h 宽）
# 只有"数字 + 单位"才算一个量：裸计数（"第 1 条""第 2 张"）不构成事实，
# 不带单位就不该触发取代（否则"第一遍""第二遍"这类叙述会把记忆互相吃掉）。
SUPERSEDE_UNITS = ("点", "号", "日", "月", "岁", "元", "块", "天", "次", "人", "个",
                   "小时", "分钟", "周", "公里", "米", "斤", "公斤", "度", "层",
                   "楼", "室", "栋", "单元", "站", "号线", "G", "T")
# ---- 两道刹车（失败时向下退化，不是失败时继续错）----
# 判据认错时，最坏的后果不是"多说一句旧话"，而是"一夜之间作废一批真实经历"。
SUPERSEDE_ON = True       # 总开关：改成 False 立即止血，不必改代码重发布
SUPERSEDE_DAILY_CAP = 20  # 每天最多取代多少条；超了只记 write_supersede_blocked，不作废


# ---------- 五行引擎（17 号 §12.8，虚拟测试 wuxing_full_vtest.py 校准） ----------
WUXING_WORDS = ["木", "火", "土", "金", "水"]
WUXING_CAP = 1.0          # 情绪池基准 cap（E 不设硬上限，cap 只作阈值参照）
WUXING_TAU = 4.0          # W_target 温度软化，防 one-hot 极化
WUXING_GAIN = 1.0         # 情绪涨增益（先天个性短期可见）
WUXING_LAM = 0.1          # 情绪基础衰减率（每事件淡一层）
WUXING_EMO_HALF_H = 6.0   # 情绪按"时间"自然消退的半衰期（小时）。
# 为什么必须有这一条：E 的衰减原来只写在 on_event 里 —— 只有"发生事件"时才淡一层。
# 没人说话的时候 E 冻住不降，主动性判定于是把"上一次聊天残留的情绪"当成"此刻想发"，
# 情绪显著度恒等于满值、愿望值恒 ≥ 阈值，插件每小时判一次就发一条。
# 取 6h 的依据（实际跑出来的数据）：E 的存量本身在 1.6~1.8（远超 cap，因为 cap 只是阈值参照，
# 不是硬上限），所以"削顶"会把半衰 12h 的前 6 小时全压成满值、判定照旧成立。6h 半衰下
# 聊完 1h 仍满（刚聊完想再说一句合理）、3h 1.28、6h 1.00、8h 0.82 —— 约 6~7 小时后
# 单独靠情绪就过不了阈值，情绪真的退了。
WUXING_BETA_SHENG = 0.3   # 相胜中和强度
WUXING_BETA_SI = 0.3      # 相生滋养强度
WUXING_TH_OVER = 0.8      # 过极阈值（×cap，治太过）
WUXING_TH_XU = 0.2        # 亏虚阈值（×cap，补不足）
WUXING_TH_JIE = 0.5       # 节泄阈值（×cap，发而皆中节）
WUXING_N = 24             # 持续亏虚周期（连续 N 事件仍低落才补）
WUXING_ALPHA_BASE = 0.0002  # 学习率基值（A/A+ 次行尾行；B 模式全行）
WUXING_ANNEAL_G = 0.002   # 学习率退火：α(t)=α0/(1+g·t)
WUXING_BOOST_LO = -0.2    # emotion_boost 下界（与 FUSE_SAFE 一致）
WUXING_BOOST_HI = 0.5     # emotion_boost 上界（正向 ≤0.5）
WUXING_CAUSE_OMEGA = 0.25 # has_cause v1 规则：bow 相似度阈值
WUXING_CAUSE_WIN_H = 24.0 # has_cause 候选记忆窗口（最近 24h）
WUXING_ANCHOR_W = (1.0, 0.6, 0.3)  # 先天锚权重（主 / 次 / 补）

# ---------- 冷战状态机（17 号 §5） ----------
COLD_THETA_ENTER = 50.0   # 冲突度累积阈值（进冷战）
COLD_THETA_EXIT = 20.0    # 冲突度回落阈值（退冷战）
COLD_HEAL = 15.0          # 一次和解事件减分
COLD_DECAY = 0.1          # 普通伤时间衰减（每天 10%）
COLD_DECAY_DEEP = 0.02    # 深层伤时间衰减（每天 2%，更慢）
COLD_DEEP_IMP = 8.0       # 冲突事件 importance ≥ 此值 = 深层伤
COLD_HARM_BASE = 5.0      # 冲突基础伤害（+|valence|）
COLD_OFFER_WAIT_MIN = 6.0    # 冷战开始后最短等待（小时）——不秒怂
COLD_OFFER_WAIT_MAX = 18.0   # 最深伤等待上限（小时）
COLD_OFFER_P_MAX = 0.35      # 每小时递台阶概率上限
COLD_OFFER_LAMBDA_H = 12.0   # 概率爬升时间常数（小时）
COLD_OFFER_DEEP_K = 0.6      # 深层伤概率打折系数
COLD_OFFER_COOLDOWN_H = 24.0 # 递过一次后多少小时内不再递

# ---------- 主动性（17 号 §6，无外部配额、状态驱动） ----------
PROACTIVE_THETA = 0.4     # 主动性阈值
PROACTIVE_QUIET_MUL = 0.3 # 安静态愿望折扣
# v3 自我收敛按情绪+熟悉程度动态：cool = clamp(COOL_BASE + FAM_W·fam − MOOD_W·mood, COOL_MIN, COOL_MAX)
# 越熟越放得开（cool 大、不轻易歇）；情绪越显著越容易聊尽兴后自然歇（cool 小）。
PROACTIVE_COOL_BASE = 5.0   # 收敛窗口基线（连续主动次数阈值）
PROACTIVE_COOL_FAM_W = 3.0  # 熟悉度→收敛加成
PROACTIVE_COOL_MOOD_W = 2.0 # 情绪显著度→收敛提前
PROACTIVE_COOL_MIN = 2      # 收敛窗口下限（最激进也至少连续 2 次）
PROACTIVE_COOL_MAX = 10     # 收敛窗口上限
PROACTIVE_FAM_MEM_TARGET = 40  # 熟悉度·记忆积累参照（活跃记忆条数目标）
PROACTIVE_FAM_TEMP = {"疏离": 0.15, "缓和": 0.55, "亲近": 0.85}  # 关系温度→熟悉度
PROACTIVE_FAM_TEMP_W = 0.5  # 温度对熟悉度权重
PROACTIVE_FAM_MEM_W = 0.2   # 记忆积累对熟悉度权重
PROACTIVE_FAM_BASE = 0.3    # 熟悉度底值（最低也有一点基本熟络）
PROACTIVE_LONG_ABSENT_H = 48.0  # 久未联络阈值（h）
PROACTIVE_CONCERN_IMP = 7.0      # 关切事件 importance 下限
PROACTIVE_CONCERN_DAYS = 7.0     # 关切事件有效窗口（天）
PROACTIVE_MOOD_DIV = 2.0         # 情绪项归一除数（ΣE/cap ÷ 2 → 0~1）
# v2 各种心情都可能触发主动：desire = W_CONCERN·关切 + W_ABSENT·久未联络 + W_MOOD·情绪显著度
# 关切满值或情绪显著满值都 ≥ 阈值(0.4)，即"重要事在身"或"强烈心情（任何情志）"可单独触发。
PROACTIVE_W_CONCERN = 0.40   # 关切权重
PROACTIVE_W_ABSENT = 0.20    # 久未联络权重
PROACTIVE_W_MOOD = 0.40      # 情绪显著度权重（心情主导，任何情志显著都算）
PROACTIVE_MOOD_PEAK = True   # True=情绪显著度用五志峰值 max(E)/cap；False=用 ΣE/cap÷2（旧）
# 主动性配额（v0.21 尾修）：判定阈值只管"想不想发"，不管"今天已经发过没有"。
# 插件每小时跑一次判定，若无配额，desire 一直在阈值上就每小时一条 —— 实际运行中会出现整天重复同一句。
PROACTIVE_DAILY_CAP = 1      # 每天最多主动几次（0 = 不限；1 = 一天最多一次）
PROACTIVE_MIN_GAP_H = 6.0    # 两次主动之间至少间隔多少小时（0 = 不限）

# ---------- 通用外部情报层（17 号 §16 主动情报：记忆推导兴趣 × 外部源过滤） ----------
INTEL_FEEDS = [            # 新闻 RSS 源（按用户兴趣关键词过滤；可配置扩展）
    {"name": "新浪国内焦点", "url": "https://rss.sina.com.cn/news/china/focus15.xml"},
    {"name": "人民网时政", "url": "http://www.people.com.cn/rss/politics.xml"},
]
INTEL_MAX_ITEMS = 6        # 每个源最多取前 N 条参与相关性打分
INTEL_TOPIC_TOP = 4        # 从记忆推导的兴趣主题取前 N 个
INTEL_MIN_SCORE = 0.30     # 外部条目与兴趣的相关性阈值（BM25/词重叠归一）
INTEL_WEATHER_CITY_KEY = "intel:city"   # kv：用户所在城市（由记忆/部署配置写入，通用）
INTEL_WEATHER_URL = "https://wttr.in/{city}?format=j1"
INTEL_WEATHER_TTL = 3600   # 天气缓存秒数（1 小时）：每轮取 state 都会检查缓存，过期才打网络；拉长减少回复被网络阻塞
INTEL_HOLIDAY_URL = "https://timor.tech/api/holiday/year/{year}"


# ---------- 表达风格层（17 号 §12.8 表达涌现；软倾向，非硬规则） ----------
EXPR_LEN_B = 0.55         # 长度倾向基线（0~1）
EXPR_LEN_MIN = 8          # 内在倾向 length=0 时她"想"说几个字
EXPR_LEN_SPAN = 24        # length=1 时再多说多少字（0→8 字、1→32 字）
                          # 依据：Baron(2004) IM 语料平均 5.4 词/turn，中文折合 8~15 字。
                          # 旧值 40（1→48 字）明显偏长，实测她稳定发 30~45 字。
EXPR_KAPPA_B = 1.0        # 执行补偿系数初值（下发量 = 她想说·κ）
EXPR_KAPPA_MIN = 0.6      # κ 下界
EXPR_KAPPA_MAX = 1.8      # κ 上界
EXPR_CAL_EVERY = 20       # 每 N 轮校准一次 κ
EXPR_CAL_ETA = 0.15       # κ 学习率
EXPR_LEN_DEV_TARGET = 0.15  # 验收线：|实际字数-她想说的|/她想说的 上限
EXPR_LEN_T = 0.30         # 关系温度对长度的权重
EXPR_LEN_M = 0.12         # 情绪能量对长度的权重
EXPR_FRAG_B = 0.45        # 碎片倾向基线（越高越倾向一句话拆多条）
EXPR_FRAG_T = 0.25
EXPR_FRAG_M = 0.18
# 五行对表达节奏的偏移（× 该五行情绪强度 inten；情绪不浓时归零，不拿命理底色规定语气）
# 纪律：这里只写"怎么断"，不写台词。木火偏碎、土金偏整，水居中偏轻。
# 依据：真人 IM 单条约 5 词，多 turn 序列占 42%；同一数值下五行各自的断句节奏应当不同。
EXPR_WX_FRAG = {"木": 0.16, "火": 0.14, "土": -0.14, "金": -0.18, "水": 0.02}
EXPR_WX_LEN = {"木": -0.10, "火": 0.04, "土": 0.16, "金": -0.14, "水": -0.06}
EXPR_WX_EMOJI = {"木": -0.10, "火": 0.14, "土": -0.04, "金": -0.16, "水": -0.06}
EXPR_EMOJI_B = 0.40       # emoji 倾向基线
EXPR_EMOJI_T = 0.25
EXPR_REACT_B = 0.55       # 反应度基线（越高越倾向短反应+一问）
EXPR_REACT_A = 0.30
EXPR_NOISE = 0.06         # 波动层随机抖动幅度（可关，测试确定性）
EXPR_QUIRK_MAX = 2        # 注入口癖条数上限
EXPR_STICKY_PRAISE = 1.0  # 夸奖吸收黏性（她说的、你夸的 → 强）
EXPR_STICKY_DEMO = 0.6    # 示范种子黏性（你教的口头禅 → 弱）
EXPR_COOL_FACTOR = 0.5    # 纠正降温系数（sticky ×0.5）
EXPR_COOL_LIMIT = 3       # 连续降温次数 → 归档遗忘

# ---- 偏移自动检测（011 §5.3）----
# 前四个是 011 原文给的，全部是"拍"出来待实测的，没有实验依据；
# 后五个是实现时自加的，同样待实测。**注意：这里没有任何"情绪绝对值阈值"**，
# 全部是相对自身基线的偏离量——011 §5.3 明确禁止拿情绪值管她。
DRIFT_TONE_WINDOW = 2       # 恢复判据：连续几轮不偏算回正（011 原值）
DRIFT_TONE_LIMIT = 6        # 触发判据：连续几轮偏冷（011 原值）
DRIFT_PROACTIVE_CAP = 5     # 日均主动次数上限（011 原值）
DRIFT_RECOVER_TURNS = 3     # 回正需要连续几轮（011 原值）
DRIFT_BASE_TURNS = 20       # 基线窗口：取最近多少轮的中位数（新加）
DRIFT_REL_DELTA = 0.25      # 相对基线偏出多少算冷（新加）
DRIFT_SILENCE_CHARS = 12    # 短回复阈值（新加）
DRIFT_SILENCE_TURNS = 4     # 连续几轮短回复算不愿说话（新加）
DRIFT_SILENCE_RATIO = 0.70  # 还得比她平时的长度再短这么多（新加，防"本来就话少"被误判）
DRIFT_EXPR_ARO_DELTA = 0.30 # 表达强度：aro 低于基线多少（新加）
DRIFT_EXPR_LEN_RATIO = 0.60 # 表达强度：长度低于基线的比例（新加）

# ---- 承诺到期检查（011 §3 条款三第二句）----
PROMISE_FORGIVE_H = 72.0    # 没给确切时间的承诺，拖多少小时才提（新加）

# ---- 安慰决策 comfort.py（018 §六）----
# 用户 2026-11-11 定：**兜底值定死、判据写死、学习层不做**。
# 理由是他现在一条真实对话都没有，让参数去学只是学自己的假设。
# 将来有 14 天以上真实对话再谈学习，接口位置见 comfort.py 的说明。
#
# COMFORT_FLOOR_DAYS **不设学习区间**：这是"别消失"的底线。让它学，结果会
# 变成"他越沉默、她越不管"——正好反了。性质同 guard.py 那四条底线词。
COMFORT_DAILY_CAP = 2       # 一天最多主动接住几次
COMFORT_COOL_H = 6.0        # 两次之间至少隔多久
COMFORT_FLOOR_DAYS = 3.0    # 最低在场：再不济也要几天冒一次（不可关）
COMFORT_LOW_VAL = -0.25     # 日均 val 低于这个算"低"
COMFORT_LOW_DAYS = 2        # 连续几天低才算"一段时间"，一天不算
COMFORT_SILENT_H = 24.0     # 多久没说话算沉默，沉默时改成轻触而不是追问
COMFORT_STOP_H = 48.0       # 他说"别管我"之后尊重多久
COMFORT_STOP_WORDS = ("别管我", "别理我", "想静静", "让我一个人", "别烦我")

# ---- 四档分级召回 faint（020）----
# 用户 2026-11-12 定：沉底记忆不该是二值，中间要分「一半」和「印象」两档。
# 区别不在语气，在给不给内容：一半给残句，印象一个字都不给，只给一句反应。
#
# 门槛不是拍的：在 60 条不同事件组合成的真实多样语料（3000 条库、2860 条沉底）上扫过。
# A 类库内话题 top1 全部落在 0.500~0.949；B 类库外话题 top1 最高只到 0.374
# （"本来在说股票跌了心情差"撞上"把多肉浇死了心疼"，共享「心」「今天」两个字）。
# 两者之间的真空带是 0.374~0.500，门槛取 0.46 落在这条带里：A 类 10/10 命中、B 类 0 误。
# 旧值 0.30 是拿 10 句模板库标出来的，那个库只有两团离散 sim，中间一条样本都没有，
# 所以 0.30 从没被真实语料检验过 —— 真实语料下它会放 B 类 0.374 进来。
#
# 三路取最大：bge 下 omega=0.65 会把门槛自动抬到 0.65，不必另配一套数。
FAINT_ON = True             # 总开关，关掉即退回二值召回
FAINT_HALF_SIM = 0.46       # 一半档门槛（bow 实测真空带中点；真实库累积后需再校）
FAINT_SENSE_GAP = 0.08      # 印象档下界 = 一半门槛 - 此值（bow 下 = 0.38）
FAINT_HALF_CHARS = 25       # 一半档给多少字（后半不提）

# ---- 心跳与环境输入源（021 / 022）----
# v0.1.0 只落地四件：tick / daemon / 时辰 / 天气 / 重逢结算。
# 节气、日照、五运六气、天文、偏好自学习留 v0.1.0.5 以后；参数先全部放这里，
# 写代码时按参数总表逐条对照，**不要在实现里现编数字**。
#
# 铁律（022 §一）：用户 >> 外部源。任何外部源一次都不许盖过这一轮用户说的话。

# ---------- 心跳 ----------
TICK_ENABLED = True          # 总开关；关掉即退回"只在事件时动"的旧行为
TICK_INTERVAL_S = 600        # 与 sweep 同频（10 分钟），复用同一循环，不另起线程
TICK_CATCHUP_MAX_H = 24.0    # 关机回来最多补最后 24h。她"睡着"期间没有经历，不补全程
TICK_CATCHUP_MIN_H = 1.0     # 小于 1h 的缺口不补，防频繁开关造成情绪抖动

# ---------- 输入源权重（用户恒 1.0） ----------
ENV_W_USER = 1.00
ENV_W_EVENT = 0.60
ENV_W_SOLAR = 0.50
ENV_W_WEATHER = 0.30
ENV_W_HOUR = 0.20
ENV_W_ASTRO = 0.15
ENV_W_ABSENCE = 0.40

# ---------- 单次脉冲（真正进 on_event 的量） ----------
# 关键：时辰只在"切换那一刻"注入一次，**不是每个 tick 都注入**。
# 若每 tick 注入：144 次/天 × 0.03 = 4.32，E 会长期顶在 cap，主动性/冷战/表达全部失真。
ENV_P_HOUR = 0.03
ENV_P_SOLAR = 0.12
ENV_P_WEATHER = 0.15
ENV_P_WEATHER_SOFT = 0.06    # 类别不变、只是程度变化（小雨→中雨）
ENV_P_ASTRO = 0.25
ENV_P_PREF_HIT = 0.15        # 命中她的偏好时追加，不是替换
ENV_P_MAX_SINGLE = 0.35      # 任何单源一次都不许顶掉半个状态

# ---------- 显著性阈值（决定写不写环境记忆） ----------
ENV_TEMP_MEM_DELTA = 5.0     # 温差 ≥5°C 才记；14°→15° 不记
ENV_DL_JUMP_MIN = 60.0       # 日照时长变化 ≥60min 才记（单位：分钟）
ENV_DL_SHORT_H = 12.0        # 日照不足半天算"秋冬的晴"（武汉冬至 10.1h / 夏至 14.0h）
ENV_DL_SHORT_PENALTY = 0.7   # 这种晴天"火"打七折（冬天的晴和夏天的晴不是一回事）
ENV_DEFAULT_LAT = 30.6       # 缺省会坐标（武汉）
ENV_MEM_DAILY_CAP = 3        # 一天最多写几条环境记忆
ENV_MEM_YEAR_BUDGET = 80     # 一年上限，占记忆总量 <1%
ENV_SNAPSHOT_MAXCHARS = 120  # 快照人话长度上限

# ---------- 环境记忆本体 ----------
ENVMEM_SOURCE = "env"
ENVMEM_IMPORTANCE = 0.55     # 能被召回，但不抢正常对话的戏
ENVMEM_AROUSAL = 0.30        # 环境是背景，不该高唤醒
ENVMEM_VAL_SUN = 0.20
ENVMEM_VAL_RAIN = -0.15
ENVMEM_VAL_SNOW = 0.05       # 未必喜欢雪；命中偏好时才上调
ENVMEM_VAL_EXTREME = -0.30
ENVMEM_VAL_FOG = -0.10

# ---------- 重逢结算 ----------
GAP_SETTLE_MIN_H = 3.0       # 低于 3h 谈"想念"是假的
GAP_SETTLE_MAX_H = 168.0     # 7 天封顶，再久不线性增长
GAP_SETTLE_ONCE = True       # 结算后更新 last_user_at，否则每次说话都再难过一次
GAP_SLEEP_DISCOUNT = 0.15    # 缺口内无 tick 记录 → 按 15% 结算（她睡着了，不是被无视）
GAP_PARTING_PENALTY = 1.25   # 上次散场不愉快时整体放大
GAP_MAX_INTENSITY = 0.45     # 单次结算硬上限，不顶满 CAP_EMO
PROFILE_GAIN_MIN = 0.5
PROFILE_GAIN_MAX = 2.0
PROFILE_BLEND = 0.6          # final_gain = 1 + BLEND*(gain-1)
GAP_DEPTH_BASE = 400.0       # 事件数 400 条 ≈ 算"熟"
GAP_DEPTH_MIN = 0.5
GAP_DEPTH_MAX = 1.5

# 体质偏向矩阵：行 = W 的五行序（木火土金水），列 = 情绪五行同序。
# 读法：W 越偏向哪一行，该行对应情绪的敏感度越高。用加权平均，不"取主导"——
# W 很平时（全 0.2）算出来接近 1.0，天然无偏向；W 尖时才明显。
PROFILE_MATRIX = (
    (1.50, 1.10, 0.80, 0.80, 0.70),   # 木旺 → 怒强、恐弱
    (1.20, 1.50, 0.80, 0.60, 0.80),   # 火旺 → 喜强、忧弱
    (0.80, 0.80, 1.50, 1.00, 0.90),   # 土旺 → 思强
    (0.90, 0.60, 1.00, 1.50, 1.10),   # 金旺 → 忧强
    (0.80, 0.70, 0.90, 1.20, 1.40),   # 水旺 → 恐强、忧也偏高
)
