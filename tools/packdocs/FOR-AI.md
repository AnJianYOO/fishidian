# 给 AI 的安装指南

你在帮一个人在这台 Windows 电脑上装「小鱼」。按顺序做，每一步都有判据，别跳步、别猜。

---

## 0. 先读这三条，否则容易做错

1. **包里没有 NapCat**。那是 QQ 的中间层，110 MB，必须和本机 QQ 的 build 号匹配。只有用户想用 QQ 才装，见第 3 节。
2. **包里没有任何凭据**。token 是安装时用 `[guid]::NewGuid()` 现场生成的，只落在本机。装的过程中你会看到它，**不要复述给用户，不要写进任何文件、不要上传**。
3. **装完不影响用户已有的「工作 DSH」**。她是第二个 DSH 实例（独立 `DSH_HOME` + 独立 `--user-data-dir`），装到 `%USERPROFILE%\fishidian\`，不碰 `%USERPROFILE%\.dsh\`。

---

## 0.1 从链接到解压（用户只丢给你一个 URL 时）

用户很可能只给你一个 URL，或者一个本地路径。先落到磁盘，再确认解压对了。

```powershell
$zip = Join-Path $env:TEMP "fishidian-v0.1.0.zip"
# 把「用户给的链接」换成真地址；用户给的是本地路径时，直接用那个路径当 $zip、跳过这一行
Invoke-WebRequest -Uri "用户给的链接" -OutFile $zip -UseBasicParsing
$dst = Join-Path $env:TEMP "fishidian-unzip"
if (Test-Path $dst) { Remove-Item $dst -Recurse -Force }
Expand-Archive -LiteralPath $zip -DestinationPath $dst -Force
$src = Get-ChildItem $dst -Recurse -Filter "install.cmd" | Select-Object -First 1
if (-not $src) { Write-Output "没找到 install.cmd —— 链接不对，或下载没完成" } else { $src.FullName }
```

判据：最后一行输出必须是 `<某目录>\install.cmd`。**那个目录就是下文所有命令的工作目录**，本文叫它「包根」。

几条硬规矩：

- **不要 `git clone`**。这个包不是拿来 clone 的：它带 2.4 MB payload、文档和一堆 `_release` 产物，clone 下来多一堆版本控制文件，还得自己找子目录。Release 的 zip 就是为这个准备的。
- **`Invoke-WebRequest` 失败时不要自己换镜像、找第三方源、或改用别的下载器。** 让用户手动把 zip 下下来，把他的本地路径给你，从 `Expand-Archive` 那步继续。
- **别把 zip 解到 `%USERPROFILE%\fishidian\`**。那会被安装器当成已有安装，`robocopy` 会覆盖掉用户的记忆库周边文件。

## 0.2 这三件事必须停下来交回给人

装的过程里有三步任何自动化都做不到，走到那里就停，说清要用户做什么，然后等他回话：

| # | 什么时候 | 要用户做什么 | 为什么做不了 |
|---|---|---|---|
| 1 | 用户要用 QQ，第一次点「连 QQ」时 | 点 UAC 的「是」 | NapCat 要注入 QQ 进程，Windows 规定提权必须本人确认，不能代点 |
| 2 | 二维码浮层出来后 | 用手机 QQ 扫码登录 | 凭据在用户手机上 |
| 3 | 第一次开窗口后 | 回答她的称呼引导 | 那是 `config\setup.json` 触发的对话，不是配置项；替用户填等于替他决定她叫什么 |

**除此之外都你自己做**：下载、解压、跑安装、装依赖（含 `ws`）、建桌面快捷方式、跑验证、读报错修错、清理临时目录。

**另外记住你在哪**：你现在跑在用户的**工作实例**（`%USERPROFILE%\.dsh`）里，而你要装的东西在**另一个实例**（`%USERPROFILE%\fishidian`，独立 `DSH_HOME`）。所以：

- 装的过程中不要往你自己所在的目录里写任何东西
- 不要指望装完自己的配置会变 —— 变的是那个新实例
- 装完 `launch.ps1` 起来的是新实例的一个独立进程，它和你不是同一个 DSH，记忆库也不是同一个

---

## 1. 前置检查（四条，缺一条就停）

```powershell
# 1) DSH 装没装
Test-Path "$env:LOCALAPPDATA\Programs\DeepSeek Harness\DeepSeek Harness.exe"

# 2) DSH 有没有在跑（有输出就是还在跑，必须先让用户关掉）
Get-Process -Name "DeepSeek Harness" -ErrorAction SilentlyContinue

# 3) node / python 版本
node --version
python --version

# 4) DSH 自带的 pnpm
Test-Path "$env:LOCALAPPDATA\Programs\DeepSeek Harness\resources\runtime\primary-runtime\dependencies\pnpm\bin\pnpm.cjs"
```

判据：

| 项 | 通过条件 | 不通过怎么办 |
|---|---|---|
| DSH | 返回 `True` | 让用户去 dsh.deepseek.com 装，装完**登录一次**（登录后 token 自动带上，不需要用户手动填 API Key） |
| DSH 进程 | 没有输出 | 让用户右键托盘图标退出，全部关掉 |
| node | `>= v18` | 让用户装 nodejs.org 的 LTS。**这是硬门槛**：桥用 `fetch`(bridge.js:98 等 12 处) / `AbortSignal.timeout` / `structuredClone`(store.js:158)，Node 16 装得上但 QQ 通道起不来，且报错不指向版本。`install_v0.1.0.ps1:89` 现在会当场拦住 |
| python | `>= 3.8` | 让用户装 python.org，**必须勾 Add python.exe to PATH**。实测内核兼容 3.8+（无 `match`、无 `removeprefix`、全部 `from __future__ import annotations`）。⚠️ 敲 `python` 弹出微软商店 = 装的是占位 stub，`install_v0.1.0.ps1:94` 会因为 `--version` 退出码非 0 而拦住 |
| pnpm.cjs | 返回 `True` | DSH 装得不完整，让用户重装 DSH |

**不要替用户安装 DSH / node / python**，除非用户明确要求。这三样都是有账号或系统级影响的安装。

---

## 2. 安装

在「包根」（§0.1 定位到的那个含 `install.cmd` 的目录）里跑：

```powershell
Set-Location -LiteralPath "包根的实际路径"
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_v0.1.0.ps1
```

**不要跑 `install.cmd` 而跑 `install_v0.1.0.ps1`**：`.cmd` 是给用户双击用的，它里面会 `chcp 65001` 并调同一个 ps1；你在 PowerShell 里直接叫 ps1 更干净，也不受代码页影响。

要顺手填 QQ 号（用户给了就传，没给就别传，脚本会自己走非交互分支留占位）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_v0.1.0.ps1 -BotQq 123456789
```

**这条命令是安全的**：如果 stdin 被重定向（你用管道跑），脚本检测到后会自动跳过所有 `Read-Host`，不会挂住。

### 两个可选开关（不要随手加）

| 开关 | 作用 | 什么时候用 |
|---|---|---|
| `-TargetRoot <路径>` | 装到指定目录，默认 `%USERPROFILE%\fishidian` | 只想验证流程、不想碰真实环境时，指到一个临时目录 |
| `-SkipDshCheck` | 允许 DSH 开着也继续装 | **只用于上面那种临时目录演练**。真实安装永远不要加：DSH 开着装，插件文件会被占用，装完也是坏的 |

演练命令长这样（装到临时目录，不碰用户现有环境）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\install_v0.1.0.ps1 -TargetRoot "$env:TEMP\fishidian-drill" -BotQq 10000000 -SkipNapCat -NoShortcut -SkipDshCheck
```

`-SkipNapCat` 跳过 NapCat 体检、`-NoShortcut` 不建桌面图标 —— 演练时都不需要。

期望输出（关键行）：

```
[0/9] 环境自检 ... OK ×5
[1/9] 建目录 ... OK
[2/9] 拷贝运行文件 ... fishidian-core / dsh-fishidian / dsh-client-ui-fatfish / dsh-qq-onebot-bridge 各一行 OK
[3/9] QQ 身份与本地口令 ... 本地口令已生成
[4/9] 写窗口 profile ... OK
[5/9] 装依赖（pnpm install） ... 依赖装好 + 4 个插件 OK
     桥自己的依赖（只有 ws 一个）... 桥 ws 就位（v8.x.x，真目录）
[6/9] QQ 通道组件体检（NapCat） ... 一段 build 号报告
[7/9] 桌面快捷方式 ... 桌面 小鱼.lnk + run-fishidian.cmd
[8/9] 内核自检 ... 内核能跑（新库已建）
[9/9] 装完了
```

退出码 `0` 即成功。

第 5 步桥的依赖只有 `ws` 一个包，正常输出是 `v8.x.x，真目录`。**如果它说"是软链接"，说明装成了 pnpm 的 isolated 模式，换个机器拷贝会断** —— 删掉 `<安装根>\dsh-qq-onebot-bridge\node_modules` 和 `pnpm-lock.yaml` 再重跑一次。

桥 import 的 `@deepseek-ai/*`（dsh-llm / dsh-session / dsh-tools / schemastery）**不需要装**，由 DSH 进程在加载插件时用自己的运行时提供。所以看到桥目录里没有 `@deepseek-ai` 是正常的，**不要自己去补**。

### 失败怎么读

| 现象 | 原因 | 处理 |
|---|---|---|
| `DSH 正在运行（N 个进程）` | 用户没关干净 | 让用户关掉（含托盘），重跑 |
| `pnpm install 失败（退出码 1）` | 网络 | 换网络 / 开代理，**重跑同一条命令**。重复装是安全的，不会覆盖记忆库 |
| `没找到 python` | 没装或没进 PATH | 装 Python 并勾 PATH，**装完要新开一个终端** |
| `没找到 node` | 没装或版本低于 18 | 装 Node 18+ 并勾 PATH |
| `robocopy 失败 code=8+` | 磁盘/权限 | 看具体文件名，通常是文件被占用 |
| `桥 ws 是软链接` | pnpm 走了 isolated | 删 `dsh-qq-onebot-bridge\node_modules` + `pnpm-lock.yaml`，重跑 |

**不要在失败后自己去 `pip install` / `npm install -g` 补依赖** —— 缺的东西都在上面这张表里，别引入新的。

---

## 3. NapCat 与 QQ（只有用户要用 QQ 才做）

### 3.1 先体检，拿两个数

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$env:USERPROFILE\fishidian\check_napcat.ps1" -Json
```

装到别处的话把路径换成你的安装根。也可以让用户直接双击安装根里的 `check_napcat.ps1`，结果一样。

它会输出：

```json
{
  "napcat_path": "...\\NapCat",
  "napcat_target_qq": "9.9.22-40990",
  "napcat_target_build": "40990",
  "qq_path": "D:\\QQ\\QQ.exe",
  "qq_file_version": "9.9.19.35469",
  "qq_build": "35469",
  "state": "build-differs"
}
```

### 3.2 这里必须由你来判断，不要让脚本判断

**为什么**：NapCat 每个 release 声明的兼容范围都不一样，写死在脚本里必然过期。而且实测存在"两个数不一致但能用"的情况（见过 35469 配 40990 仍能正常出码的情况）。

流程：

1. `state` 是 `build-equal` → 直接用，跳到 3.3。
2. `state` 是 `napcat-missing` → 从 `github.com/NapNeko/NapCatQQ/releases` 下 `NapCat.Shell.zip`，解压到 `%USERPROFILE%\NapCat`，确认里面有 `launcher.bat`。装完回到 3.1 再体检一次。
3. `state` 是 `qq-missing` → 让用户装 QQNT（9.9.x 版本）。
4. `state` 是 `build-differs` → **先让用户真跑一次**（3.3），看二维码出不出来。
   - 出得来 → 能用，不用管版本差。
   - 出不来 → 去 releases 页，翻到对应 `qq_build` 落在它声明范围内的那个版本，换 NapCat。镜像站 `napneko.icu`。

**不要**用 `NapCat.Shell.Windows.OneKey.zip`（它自带一个配套 QQ，会变成两个 QQ 客户端，和用户"同一个号不能登两处"直接冲突）。

### 3.3 实际验一次

让用户双击桌面「小鱼」，然后在窗口右下角点「连 QQ」。出现的浮层里应该有二维码。

| 看到什么 | 说明 |
|---|---|
| 有二维码，QQ 扫码后登录成功 | 通 |
| 浮层白框、写着"这个码可能过期了" | 码过期，点一下刷新；连着两次都不出就是 NapCat 没写码 |
| 一直没有浮层 | 皮肤插件没挂上，检查 `node_modules\dsh-client-ui-fatfish` |

**UAC 会弹一次**，必须用户自己点。这是 NapCat 注入 QQ 进程要管理员权限，Windows 规定不能代点。

---

## 4. 验收（四条，逐条核）

下文所有命令都用一个 `$Inst` 指安装根。**装到默认位置就是 `%USERPROFILE%\fishidian`；用了 `-TargetRoot` 就换成那个值。** 先在本会话里定死，别每处手敲：

```powershell
$Inst = Join-Path $env:USERPROFILE "fishidian"   # 装到别处：改成你的 -TargetRoot
Get-Item -LiteralPath $Inst | Select-Object FullName
```

**第一件事是跑它自带的验证脚本，别自己拼命令**——一次覆盖 8 类、二十多项，比手敲准：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File "$Inst\verify_install.ps1" -TargetRoot $Inst
```

退出码 `0` = 无硬失败；`1` = 有硬失败。输出分 `[OK]` / `[FAIL]` / `[WARN]` 三级，最后一行给汇总。**`[FAIL]` 必须清零才算装对；`[WARN]` 可以带着，但要说清哪条、影响什么。**

它查这七类：

| 类 | 具体 |
|---|---|
| 运行时 | node ≥18、python ≥3.8 |
| 安装根 | `launch.ps1`、`check_napcat.ps1`、`tools\qq-qrcode-server.js`、`START-HERE.md`、`fishidian-core\cli.py`、桥的 `lib\bridge.js` / `lib\onebot.js`、皮肤与插件的 `lib\index.js` |
| profile | `var package.json` 里三个 link 依赖都在；`node_modules` 下三个包真链上 |
| 桥 ws | `node_modules\ws\package.json` 在且是真目录（不是 junction）——**这条是 QQ 通道唯一的外部依赖** |
| 配置 | `cordis.patch.yml` 存在；`botQq` 不是占位 `0`；`allowUsers` 有值 |
| 数据目录 | `workspace\memory`、`workspace\sessions`、`logs`、`backup` |
| 内核三件套 | `launch.ps1` 里要能搜到 `FISHIDIAN_CORE` / `FISHIDIAN_DB` / `FISHIDIAN_PYTHON` 三个环境变量；安装根有 `python-path.txt` 且里面路径存在；插件 `lib\index.js` 支持 `FISHIDIAN_DB`（不支持的话库会建到 `~\.dsh\fishidian-memory\`）。**这四条挂了不报错，只表现为"她失忆"** |
| 内核 | `cli.py state` 退出码 0（会用同一个 db 建库，和首次开窗口等价） |

脚本判不了的四条（只有人看得出来）：

1. 窗口能开、左下栏写着「小鱼」
2. 聊几句后 `dfy.db` 体积在长（**没长先看 `~\.dsh\fishidian-memory\` 有没有多出一个库 —— 那是路径跑偏，不是她忘性大**）
3. 工作 DSH 里说的话，她答不上来（两套 profile 确实分开）
4. QQ 里发消息，她的窗口能看到、她的回复会到 QQ

**为什么内核路径要单列一条**：插件 `apply(ctx, config)` 只取 `config.ns`，`cordis.patch.yml` 里 `fishidian.python / core / db` 三个键**从来没人读**。真实生效的是 `process.env.FISHIDIAN_PYTHON`（`lib/index.js:28`）、`_resolveCore()`（env → 逐级向上找 `fishidian-core\cli.py` → 打包那台机器的 D 盘路径）、`dbPath()`（`FISHIDIAN_DB` → `FISHIDIAN_DB_DIR` → `~/.dsh/fishidian-memory/`，最后才看 legacy `dafeiyu-memory/dfy.db`）。打包那台机器上一直能跑，是因为遗留那个库恰好存在，纯巧合。**所以别去改配置换路径，改不动；要换就重装或改 `launch.ps1`。**

想自己单独核时，也可以用下面这几条（`$Inst` 沿用上面定好的）：

```powershell
# ① 装到哪了
Test-Path "$Inst\data\profiles\desktop\cordis.patch.yml"

# ② 依赖链上了没
Get-ChildItem "$Inst\data\profiles\desktop\node_modules" |
  Where-Object { $_.Name -in @("dsh-fishidian","dsh-client-ui-fatfish","dsh-qq-onebot-bridge","dsh-pet") } |
  Select-Object Name

# ③ 记忆库在哪（新装是空库，文件很小是正常的）
Get-Item "$Inst\workspace\memory\dfy.db" | Select-Object Length

# ④ 内核能跑
python -X utf8 "$Inst\fishidian-core\cli.py" dsh:desktop "$Inst\workspace\memory\dfy.db" state

# ⑤ 五份文档在不在（装进安装根，用户不用翻压缩包）
Get-ChildItem $Inst -File | Where-Object { $_.Name -in @("README.md","START-HERE.md","FOR-AI.md","VERSION.txt","README.txt") } | Select-Object Name, Length
```

判据：

- ① 返回 `True`
- ② 列出 4 个名字
- ③ 文件存在（`Length` 几十 KB 起）
- ④ 输出里有 `W` 或 `E` 之类的五行字段，退出码 0
- ⑤ 列出 5 个文件名

再让用户亲手做一次两条隔离检查：

- 双击桌面「小鱼」→ 窗口开出来，左下栏写「小鱼」
- 打开工作 DSH 随便说两句 → 回她的窗口问「我刚才在工作窗口说了什么」→ **她应该不知道**

### 4.1 第一次起窗口（这个你不用等用户双击）

装完就可以自己把它拉起来，不用让用户去找桌面图标：

```powershell
Start-Process -FilePath "powershell.exe" `
  -ArgumentList "-NoProfile","-ExecutionPolicy","Bypass","-File","$Inst\launch.ps1" `
  -WindowStyle Hidden
Start-Sleep -Seconds 8
# 三条判据：窗口标题是「小鱼」、8798 在听、进程起来了
(Get-Process | Where-Object { $_.MainWindowTitle -like "*小鱼*" } | Select-Object Id, MainWindowTitle)
@(Get-NetTCPConnection -LocalPort 8798 -State Listen -ErrorAction SilentlyContinue).Count
```

判据：

| 看到什么 | 说明 |
|---|---|
| 有一个进程的 `MainWindowTitle` 含「小鱼」 | 窗口起来了 |
| 8798 的监听数 ≥ 1 | 二维码服务起来了（这一项和她聊不聊天无关，是给「连 QQ」用的） |
| 都没有 | 读 `$Inst\logs\` 下最新的日志，或者让用户手动双击桌面图标看报什么 |

**窗口是弹在用户的桌面上，不是你的会话里。** 起完跟用户说一句"窗口应该已经出来了"，别自己以为要在这里等他看到。

**第一次开窗口会问用户怎么称呼她** —— 这就是 §0.2 里第 3 条要交回给人的那一步，**别替用户答**。

---

## 5. 不要做的事

- 不要打印、复述、保存 `cordis.patch.yml` 里的 `token`
- 不要把这个包里的任何文件上传到外部服务
- 不要改 `%USERPROFILE%\.dsh\`（那是用户的工作实例）
- 不要在 DSH 运行时装
- 不要为了"验证能用"就替用户发 QQ 消息
- 不要删 `%USERPROFILE%\fishidian\workspace\` —— 那是记忆库，删了就没了
- **不要用 `install.cmd` 代替 `install_v0.1.0.ps1`**：`.cmd` 走交互分支，在你这儿会挂住等输入
- **不要自己改 `cordis.patch.yml` 里的内核路径**：那里没有可改的键，路径由 `launch.ps1` 的环境变量决定（见 §4 那段说明）
