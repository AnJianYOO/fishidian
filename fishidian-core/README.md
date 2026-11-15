# fishidian-core · 小鱼治理内核（Python 包）

> 从早期的原型脚本里把治理机制抽出来，做成一个统一的 Python 包，供 DSH 插件调用。
> 版本 0.1.0 · 零第三方依赖（只用标准库）· `tests/test_core.py` **21/21 通过**。

## 为什么有它

治理逻辑全部放在一个 **Python 包**里；DSH 插件是一层 TypeScript 薄壳，通过本地子进程调用它 —— 中医那一套机制不翻译、不搬到 JS 里。

## 目录

```
fishidian-core/
├── fishidian_core/
│   ├── __init__.py    # 导出 Governor / Store / score_text / neg_strength
│   ├── config.py      # 全部参数（早期原型里试出来的值，勿改）
│   ├── store.py       # SQLite（WAL）：memories / events / fuse_log / kv；按 ns 隔离
│   ├── pools.py       # 血海/孕育/督脉：R 公式、adopt/touch、衰减、满池泄、相似合并、巡检
│   ├── persona.py     # 体质 P：慢演化、边界钳位、情绪上限
│   ├── safety.py      # 安全熔断：滑动窗口、挂起、钳制、审计
│   ├── throttle.py    # 中庸节流：θ_节/θ_和、节律 ω 呼吸
│   ├── tail.py        # 去我执 γ_ego、长尾保护
│   ├── scoring.py     # 文本→(imp,aro,val)、负面强度、BoW 检索（bge 可插拔）
│   └── governor.py    # 统一 API（插件唯一入口）
├── tests/test_core.py # 21 项断言
└── README.md
```

## 用法（本地验证）

```bash
cd fishidian-core
python tests/test_core.py        # 期望 21/21 passed
```

```python
from fishidian_core import Governor, Store

g = Governor("qq:dm:123456", store=Store("data/df.db"))   # 一个 ns 一个实例
g.observe_turn("今天升职述职通过了，好开心", "恭喜你！")   # 回写：新记忆入血海
items = g.recall("升职", k=6)                             # 召回（只 touch 不涨 R）
inj = g.build_injection(items)                            # 注入块（带 marker）
out = g.govern_output("回复文本", emotion_contributions=[0.9])  # 输出治理
print(g.state())                                          # 状态面板数据
g.sweep()                                                 # 离线巡检
```

## 插件接口契约（DSH 插件按此实现）

| 方法 | 用途 | 关键纪律 |
|---|---|---|
| `recall(ns_query, k)` | 五路融合召回，返回 (mem, rec, sim, adopt) | 只 touch，不涨 R |
| `build_injection(items)` | 拼注入块（≤600 字，marker 内）；**无条目返回 None** | 不覆盖人格，marker 先删后写；宿主侧 None 即不注入 |
| `observe_turn(user, asst, cited_ids)` | 回写：入池/adopt/熔断观察 | 极端输入挂起期不写入 |
| `govern_output(text, contribs)` | 节流→熔断→去我执 | boost 钳到 -0.2 |
| `sweep()` | 衰减/归档/合并/长尾/满池泄 | 每 10 分钟 |
| `state() / list_memories() / forget() / export()` | 管理命令数据 | owner 限定 |

## 关键参数（DSH 插件配置映射）

见 `config.py`；DSH 插件配置项（owner_id/群白名单/inject_top_k/omega_min 等）一一映射，默认值是在实际使用里调出来的。

## 验收

- `tests/test_core.py`：**21/21**（晋升/熔断/节流/长尾/隔离/召回不强化/注入预算/端到端）

## 给 DSH 插件的三条红线（不许退化）

1. 召回 ≠ 强化：只有 adopt 涨 R。
2. 注入不覆盖人格：只在 marker 内追加。
3. 群聊不注入私聊记忆：recall 按 visibility 过滤。
