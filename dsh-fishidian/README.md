# dsh-fishidian

小鱼情感记忆经络系统的 DSH 插件（宿主半侧）：TypeScript/JS 薄壳 + 本地 Python 内核 `fishidian-core`。

## 架构

```
DSH(对话) → dsh-fishidian(TS 薄壳) → python cli.py(子进程) → fishidian-core(治理层)
```

- 薄壳只做事件桥：`agent/pre-step` 注入记忆、`session/event` 回写、`/memory /state /forget` 命令、10 分钟巡检。
- 内核零第三方依赖（SQLite WAL + 规则打分 + BoW 检索），治理层异常时插件降级为无记忆回复，不阻塞聊天。

## 安装（已在 DSH 0.1.5-rc.2 上验证）

```powershell
# 1) 复制插件包到无中文路径（link: 协议要求）
Copy-Item -LiteralPath "<你解压出来的源码目录>\dsh-fishidian" -Destination "$env:USERPROFILE\dsh-fishidian" -Recurse -Force

# 2) 装进目标 profile（web 为例；desktop 由 Electron 独占，需在桌面 UI 的插件设置里装）
cd $env:USERPROFILE\.dsh\profiles\web
corepack pnpm add link:C:/Users/你的用户名/dsh-fishidian

# 3) 把 dsh-fishidian 加进 package.json 的 dsh.profile.bundles 数组
#    （python 脚本改写，勿手动破坏 JSON）
```

重启 profile 即生效。验证：

```powershell
dsh --profile web --dump-config        # 配置树应有 # == dsh-fishidian 段（ns: dsh:desktop）
dsh --profile web --no-open --port 0   # boot 无报错
```

## 使用

- **注入**：每个对话回合第一步前，内核按五路召回拼记忆块（带 `fishidian:memory` marker），作为 user 消息追加；无相关记忆或治理层异常时不注入。
- **回写**：回合结束（turn/end）把 user/assistant 文本交给内核 observe_turn：入池/adopt/熔断观察。
- **命令**：
  - `/memory` —— 最近记忆（R/池/ID）
  - `/state` —— 体质 P、三池（血海/孕育/督脉）、熔断状态
  - `/forget <ID>` —— 遗忘指定记忆
- **巡检**：每 10 分钟 sweep（衰减/归档/合并/长尾保底/满池泄）。

## 配置（环境变量，可选）

| 变量 | 默认 | 说明 |
|---|---|---|
| `FISHIDIAN_PYTHON` | `python` | python 命令 |
| `FISHIDIAN_CORE` | `<安装根>\fishidian-core` | 内核目录（cli.py 所在） |
| `FISHIDIAN_DB_DIR` | `~/.dsh/fishidian-memory` | 记忆库目录（fishidian.db） |

## 红线（不允许退化）

1. 召回≠强化：注入只读，只有 observe_turn 的内核判定会涨 R。
2. 注入不覆盖人格：记忆块带 marker 只作参考，不写系统提示词。
3. 群聊不注入私聊记忆：由内核 ns + visibility 隔离保证（QQ 接入时按此扩展）。

## 验证

- `tests/integration.mjs`：12/12（注入/回写/命令全链路，真实内核 + 真实 CLI）
- 在 DSH 0.1.5-rc.2 上实测：插件挂进 web profile 配置树、DSH boot 加载成功、内核回归 21/21。
