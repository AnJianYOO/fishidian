# 大肥鱼 V1 安装器
# ---------------------------------------------------------------------------
# 装完是什么样：%USERPROFILE%\fishidian\ 下有一套完整的她 ——
#   内核 + 插件 + 皮肤 + QQ 桥 + 独立窗口 + 二维码服务，
#   双击桌面「大肥鱼」就开出一个单独的窗口，和你的工作 DSH 完全分开。
#
# 为什么不用链接/junction：安装包要能直接拷给别人，链接在别人的机上会断。
# 所以真拷一份运行文件，profile 的 link: 依赖指向这份拷贝。
#
# 隐私：包内不含任何 QQ 号、token、聊天记录、记忆库。
# 这些在安装时现场生成或现场问，只落在你本机。
# ---------------------------------------------------------------------------
param(
    [string]$TargetRoot = "",
    [string]$BotQq = "",
    [string]$AllowUser = "",
    [switch]$SkipNapCat,
    [switch]$NoShortcut,
    # 仅演练/自检用：允许 DSH 开着也继续。真实安装永远不要加这个 ——
    # 装的时候 DSH 要改 profile，开着装会把它的状态写坏。
    # 配合 -TargetRoot 指向临时目录，就能在不碰真实环境的前提下把九步全跑一遍。
    [switch]$SkipDshCheck
)

$ErrorActionPreference = "Stop"
$Utf8NoBom = New-Object System.Text.UTF8Encoding $false
$PackageRoot = $PSScriptRoot
$Interactive = -not [Console]::IsInputRedirected

# 跑外部程序时不因 stderr 崩：5.1 下 $ErrorActionPreference="Stop" 配 2>&1 必抛
function Invoke-Native {
    param([string]$Exe, [string[]]$Arguments, [string]$WorkDir = "")
    $prevEap = $ErrorActionPreference
    $prevLoc = (Get-Location).Path
    $ErrorActionPreference = "Continue"
    try {
        if ($WorkDir) { Set-Location -LiteralPath $WorkDir }
        $out = & $Exe @Arguments 2>&1
        $code = $LASTEXITCODE
    } finally {
        Set-Location -LiteralPath $prevLoc
        $ErrorActionPreference = $prevEap
    }
    return @{ Code = $code; Out = ($out -join "`n") }
}

# stdin 被重定向时（AI 用管道调用、或被 `echo. | powershell -File`），Read-Host
# 会立刻读到 EOF：要么吃掉默认值，要么在个别宿主上挂住。所以统一走 Ask。
function Ask($msg, $default = "") {
    if (-not $Interactive) { return $default }
    return (Read-Host $msg)
}

function Step($n, $t) { Write-Host ""; Write-Host "[$n] $t" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "    OK   $m" -ForegroundColor Green }
function Warn($m) { Write-Host "    注意 $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "    失败 $m" -ForegroundColor Red; throw $m }

Write-Host ""
Write-Host "=============================================" -ForegroundColor Cyan
Write-Host "  大肥鱼 V1 安装" -ForegroundColor Cyan
Write-Host "=============================================" -ForegroundColor Cyan

# ============================================================ [0/9] 环境自检
Step "0/9" "环境自检"

if (-not (Test-Path -LiteralPath $PackageRoot)) { Die "找不到安装包目录" }

$DshExe = Join-Path $env:LOCALAPPDATA "Programs\DeepSeek Harness\DeepSeek Harness.exe"
if (-not (Test-Path -LiteralPath $DshExe)) {
    Die ("没找到 DeepSeek Harness。预期位置：$DshExe`n" +
         "先去 dsh.deepseek.com 装它，用你的 DSH 账号登录一次，再回来跑这个安装器。")
}
Ok "DeepSeek Harness 已安装"

$dshRunning = @(Get-Process -Name "DeepSeek Harness" -ErrorAction SilentlyContinue)
if ($dshRunning.Count -gt 0) {
    if ($SkipDshCheck) {
        Warn ("DSH 有 " + $dshRunning.Count + " 个进程在跑，按 -SkipDshCheck 继续（仅演练）")
    } else {
        Die ("DSH 正在运行（" + $dshRunning.Count + " 个进程）。`n" +
             "安装要改它的 profile，开着装会写坏。`n" +
             "把 DSH 全部关掉（包括托盘那个图标），再跑一次。")
    }
} else {
    Ok "DSH 当前没在运行"
}

$NodeExe = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $NodeExe) { Die "没找到 node。QQ 桥和二维码服务都要它，先装 Node.js 18 以上（nodejs.org）。" }
# 只打印版本是不够的。桥里用到 fetch（bridge.js 等多处）、AbortSignal.timeout、
# structuredClone（store.js）——这三个都是 Node 18 才有的内置 API。Node 16 能把包
# 一路装到"装完了"都不报错，只在 QQ 通道启动时挂掉，而且错误信息不会指向版本。
# 所以这里真判一次，而不是留一句"装完再看"。
$nr = Invoke-Native -Exe $NodeExe -Arguments @("--version")
$nodeVer = (($nr.Out -split "`n") | Select-Object -First 1).Trim()
if ($nr.Code -ne 0 -or -not $nodeVer) {
    Die ("跑 node --version 失败（退出码 " + $nr.Code + "）。node 装坏了，重装一次再试。")
}
if ($nodeVer -match 'v(\d+)\.') {
    $nodeMajor = [int]$Matches[1]
    if ($nodeMajor -lt 18) {
        Die ("Node " + $nodeVer + " 太旧。她的桥用到 fetch / AbortSignal.timeout / structuredClone，" +
             "这三个是 Node 18 才有的内置 API —— 包能装上，但 QQ 通道起不来。`n" +
             "去 nodejs.org 装 18 以上的 LTS，装完**重开一个命令行**再跑这个安装器" +
             "（旧窗口的 PATH 不会更新）。")
    }
    Ok ("Node " + $nodeVer + "（≥18，桥要的三个 API 都在）")
} else {
    Die ("读不出 node 版本（输出：" + $nodeVer + "）。命令行手动敲 node --version 看一眼。")
}

$PyExe = $null
foreach ($c in @("python", "py")) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) { $PyExe = $cmd.Source; break }
}
if (-not $PyExe) { Die "没找到 python。她的内核是 Python 写的，先装 Python 3.8 以上（python.org），装时勾 Add to PATH。" }
# Windows 上 python 可能只是 Microsoft Store 的占位 stub：Get-Command 找得到，一跑
# 就弹商店或者直接报错。所以走 Invoke-Native 并检查退出码，读不出版本也按失败处理。
$pr = Invoke-Native -Exe $PyExe -Arguments @("--version")
$pyVer = (($pr.Out -split "`n") | Select-Object -First 1).Trim()
if ($pr.Code -ne 0 -or -not $pyVer) {
    Die ("跑 python --version 失败（退出码 " + $pr.Code + "）。`n" +
         "如果是 Microsoft Store 的占位程序，打开它只会跳商店 —— 去 python.org 装真 Python，" +
         "安装时勾 Add python.exe to PATH，装完重开一个命令行再试。")
}
if ($pyVer -match '(\d+)\.(\d+)') {
    $pyMajor = [int]$Matches[1]
    $pyMinor = [int]$Matches[2]
    if ($pyMajor -lt 3 -or ($pyMajor -eq 3 -and $pyMinor -lt 8)) {
        Die ("Python " + $pyVer + " 太旧，内核要 3.8 以上（代码里用了 f-string 与类型注解）。`n" +
             "去 python.org 装 3.10 以上的版本，安装时勾 Add python.exe to PATH。")
    }
    # 把路径一起打出来：PATH 里可能不止一个 python（别的软件自带的、商店 stub 等），
    # 抓到哪个会写进 python-path.txt 并交给 launch.ps1，用户得看得见。
    Ok ("Python " + $pyVer + "（≥3.8）  " + $PyExe)
} else {
    Die ("读不出 python 版本（输出：" + $pyVer + "）。")
}

$PnpmCjs = Join-Path $env:LOCALAPPDATA "Programs\DeepSeek Harness\resources\runtime\primary-runtime\dependencies\pnpm\bin\pnpm.cjs"
if (-not (Test-Path -LiteralPath $PnpmCjs)) { Die "没找到 DSH 自带的 pnpm。DSH 可能装得不完整，重装一次 DSH。" }
Ok "DSH 自带 pnpm 就位"

# ============================================================ [1/9] 目录
Step "1/9" "建目录"

if (-not $TargetRoot) { $TargetRoot = Join-Path $env:USERPROFILE "fishidian" }
$Target   = $TargetRoot
$FishHome = Join-Path $Target "data"                 # DSH_HOME，程序数据
$FishProf = Join-Path $FishHome "profiles\desktop"   # 她这个实例的 profile
$MemDir   = Join-Path $Target "workspace\memory"      # 记忆库在 workspace 下
$BinDir   = Join-Path $Target "tools"

foreach ($d in @($Target, $FishHome, $FishProf, $MemDir, $BinDir,
                 (Join-Path $FishHome "electron-data"),
                 (Join-Path $Target "config"),
                 (Join-Path $Target "backup\daily"),
                 (Join-Path $Target "backup\weekly"),
                 (Join-Path $Target "backup\manual"),
                 (Join-Path $Target "workspace\sessions"),
                 (Join-Path $Target "workspace\notes"),
                 (Join-Path $Target "workspace\files"),
                 (Join-Path $MemDir "snapshots"),
                 (Join-Path $Target "logs\app"),
                 (Join-Path $Target "logs\error"),
                 (Join-Path $Target "logs\bridge"),
                 (Join-Path $Target "logs\audit"))) {
    if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
}
Ok "安装根 $Target"

# ============================================================ [2/9] 拷运行文件
Step "2/9" "拷贝运行文件"

# 排除清单：测试、文档样例、git、Python 缓存，以及任何像聊天记录/库的东西。
# 最后那条最关键 —— 源码目录里混着的 qq-*.jsonl 是她和用户的历史，绝不能进别人的包。
$RoboExcludeDirs  = @("test", "tests", "docs", "examples", ".git", "__pycache__", ".github", ".vscode")
$RoboExcludeFiles = @("*.bak", "*.bak-*", "*.db", "*.db-wal", "*.db-shm", "*.jsonl", "*.log", "*.pyc")

function Copy-Tree($Src, $Dst) {
    if (-not (Test-Path -LiteralPath $Src)) { return }
    $a = @($Src, $Dst, "/E", "/NFL", "/NDL", "/NJH", "/NJS", "/NP", "/R:2", "/W:2")
    $a += "/XD"; $a += $RoboExcludeDirs
    $a += "/XF"; $a += $RoboExcludeFiles
    $r = Invoke-Native -Exe "robocopy.exe" -Arguments $a
    # robocopy 退出码 0-7 都算成功（1=已拷贝 2=有额外文件 3=1+2 4=有不匹配…），8 以上才是错
    if ($r.Code -ge 8) { Die ("robocopy 失败 code=" + $r.Code + "`n" + $r.Out) }
}

foreach ($pkg in @("fishidian-core", "dsh-fishidian", "dsh-client-ui-fatfish", "dsh-qq-onebot-bridge")) {
    $src = Join-Path $PackageRoot "payload\$pkg"
    if (-not (Test-Path -LiteralPath $src)) { Die "安装包缺 payload\$pkg" }
    Copy-Tree $src (Join-Path $Target $pkg)
    $sz = [math]::Round(((Get-ChildItem -LiteralPath (Join-Path $Target $pkg) -Recurse -File |
            Measure-Object -Sum Length).Sum / 1KB), 1)
    Ok "$pkg  $sz KB"
}

$qrSrc = Join-Path $PackageRoot "payload\tools\qq-qrcode-server.js"
if (-not (Test-Path -LiteralPath $qrSrc)) { Die "安装包缺 payload\tools\qq-qrcode-server.js" }
Copy-Item -LiteralPath $qrSrc -Destination (Join-Path $BinDir "qq-qrcode-server.js") -Force

foreach ($f in @("launch.ps1", "check_napcat.ps1", "verify_install.ps1")) {
    $src = Join-Path $PackageRoot $f
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $Target $f) -Force
    } else {
        Warn "安装包里没有 $f，跳过"
    }
}

# 把这次探测到的 python 绝对路径留给 launch.ps1。
# 为什么要落一个文件：快捷方式拉起的进程 PATH 和用户在终端里敲命令的 PATH 可能不同。
# launch.ps1 里没写死路径（用户以后可能升级/挪位置），它先读这个文件、读不到再现找。
[IO.File]::WriteAllText((Join-Path $Target "python-path.txt"), $PyExe, $Utf8NoBom)
Ok "python 路径已记录（launch.ps1 会用它，避免窗口进程 PATH 里没有 python）"

# 四份文档一起装到安装根 —— 用户装完在自己的目录里就能读到，不用回去翻压缩包。
# VERSION.txt 用包根那份（有模块清单），不要被 home-template 的模板版顶掉。
foreach ($f in @("README.md", "START-HERE.md", "FOR-AI.md", "VERSION.txt")) {
    $src = Join-Path $PackageRoot $f
    if (Test-Path -LiteralPath $src) {
        Copy-Item -LiteralPath $src -Destination (Join-Path $Target $f) -Force
    } else {
        Warn "安装包里没有 $f，跳过"
    }
}
Ok "二维码服务 + 启动脚本 + 4 份文档"

# 目录说明（home-template 那份，讲 workspace/logs/backup 各放什么）：
# 已存在就不覆盖，免得冲掉用户自己写的东西
$rtSrc = Join-Path $PackageRoot "payload\fatfish-window\home-template\README.txt"
$rtDst = Join-Path $Target "README.txt"
if ((Test-Path -LiteralPath $rtSrc) -and -not (Test-Path -LiteralPath $rtDst)) {
    Copy-Item -LiteralPath $rtSrc -Destination $rtDst -Force
}

# ============================================================ [3/9] QQ 身份与口令
Step "3/9" "QQ 身份与本地口令"

if (-not $BotQq) {
    Write-Host ""
    Write-Host "  接 QQ 需要一个能登录的 QQ 号（机器人号）。"
    Write-Host "  注意：同一个号不能在两个客户端同时登 —— 它登在 NapCat 上，你就不能用手机 QQ 再登同一个号。"
    Write-Host "  留空直接回车也行，之后再改 $FishProf\cordis.patch.yml。"
    $BotQq = Ask "  机器人 QQ 号" ""
}
if (-not $BotQq) {
    $BotQq = "0"
    Warn "没填 QQ 号，先写占位 0；QQ 通道要等你补上号才通"
} else {
    # QQ 号只接受纯数字。输错（尾随空格、全角数字、字母）会原样落进 cordis.patch.yml，
    # 桥启动时转不成数字就静默不启用通道 —— 要等到「连 QQ」才看出问题。
    # 这里当场判：不合法就不写坏配置，退化成"未填"，并说清怎么补。
    $BotQq = $BotQq.Trim()
    if ($BotQq -notmatch '^[0-9]{5,12}$') {
        Warn ("机器人 QQ 号「" + $BotQq + "」不是 5-12 位纯数字，按未填处理（写占位 0）。" +
              "装完把真号填进 cordis.patch.yml，再重跑一次 install.cmd。")
        $BotQq = "0"
    }
}

# 白名单：谁能和她说话。
# 旧版这里写的是 if (-not $AllowUser) { $AllowUser = $BotQq } —— 把白名单默认成
# 机器人自己的号。后果是装完谁都进不来，QQ 里发消息她不回，看起来像"她坏了"。
# 现在改成单独问一次，问的是用户自己的号。
$Users = @()
if ($BotQq -ne "0") {
    if ($AllowUser) {
        $Users = @($AllowUser -split '[,\s，、]+' | Where-Object { $_ })
    } else {
        Write-Host ""
        Write-Host "  还差一个，这个不能省：白名单 —— 谁有权和她说话。"
        Write-Host "  填你自己的 QQ 号（不是上面那个机器人号）。多个人用英文逗号分开，最多 5 个。"
        Write-Host "  留空的话，装完你在 QQ 里给她发消息不会有回应 —— 因为白名单里没人。"
        $raw = Ask "  你的 QQ 号" ""
        if ($raw) { $Users = @($raw -split '[,\s，、]+' | Where-Object { $_ }) }
    }

    $valid = @()
    foreach ($u in $Users) {
        $u = ([string]$u).Trim()
        if ($u -match '^[0-9]{5,12}$') { $valid += $u }
        else { Warn ("白名单里的「" + $u + "」不是 5-12 位纯数字，已忽略") }
    }
    $valid = @($valid | Select-Object -Unique | Select-Object -First 5)
    if ($valid.Count -gt 0) {
        $Users = $valid
        Ok ("白名单：" + ($Users -join "、"))
    } else {
        $Users = @("0")
        Warn "白名单是空的 —— 装完必须自己补，否则只有白名单里的人能和她说上话（现在一个都没有）"
    }
} else {
    $Users = @("0")
    Write-Host "    没接 QQ，白名单先留空（之后补 QQ 号时记得把你自己加进去）" -ForegroundColor DarkGray
}
$AllowUser = $Users[0]

# webhook 口令：每次安装现场生成，不重复用、不进包、不写进任何文档
$Token = [guid]::NewGuid().ToString("N")
Ok "本地口令已生成（32 位，只存在你本机）"

# ============================================================ [4/9] 写 profile
Step "4/9" "写窗口 profile"

$TargetSlash = $Target.Replace("\", "/")

# package.json —— 四个 link: 依赖 + bundles 顺序
# bundles 的顺序有讲究：皮肤必须排在桥前面，否则桥先连上、她要好久才出来。
$pkgJson = @"
{
  "name": "dsh-profile-desktop",
  "private": true,
  "dependencies": {
    "dsh-pet": "^0.3.8",
    "dsh-fishidian": "link:$TargetSlash/dsh-fishidian",
    "dsh-qq-onebot-bridge": "link:$TargetSlash/dsh-qq-onebot-bridge",
    "dsh-client-ui-fatfish": "link:$TargetSlash/dsh-client-ui-fatfish"
  },
  "dsh": {
    "profile": {
      "bundles": [
        "@deepseek-ai/dsh-base",
        "@deepseek-ai/dsh-web-app",
        "dsh-pet",
        "dsh-client-ui-fatfish",
        "dsh-fishidian",
        "dsh-qq-onebot-bridge"
      ]
    }
  }
}
"@
[IO.File]::WriteAllText((Join-Path $FishProf "package.json"), $pkgJson, $Utf8NoBom)

# cordis.yml —— 空入口列表，一切由 patch 层组合
$cordisYml = "# dsh profile root - an empty entry list. The tree is composed as patches:`r`n" +
             "# each bundle in package.json's dsh.profile.bundles, then cordis.patch.yml, then any`r`n" +
             "# --patch overlays. Edit cordis.patch.yml, not this file.`r`n[]`r`n"
[IO.File]::WriteAllText((Join-Path $FishProf "cordis.yml"), $cordisYml, $Utf8NoBom)

$wsYml = "packages:`r`n  - .`r`n`r`nnodeLinker: hoisted`r`nautoInstallPeers: false`r`n"
[IO.File]::WriteAllText((Join-Path $FishProf "pnpm-workspace.yaml"), $wsYml, $Utf8NoBom)

# cordis.patch.yml —— 从模板替换占位符
# 路径填正斜杠：YAML 里反斜杠是转义符，写 C:\xxx 会被吃掉。
$tpl = Join-Path $PackageRoot "payload\fatfish-window\cordis.patch.yml"
if (-not (Test-Path -LiteralPath $tpl)) { Die "安装包缺 payload\fatfish-window\cordis.patch.yml" }
$patch = [IO.File]::ReadAllText($tpl, [Text.Encoding]::UTF8)
# 只替换真正生效的四个占位符。内核路径/proto 不在这里 —— 那三个是环境变量，
# 由 launch.ps1 在起窗口前设（见模板里的注释）。
$patch = $patch.Replace("__WEBHOOK_TOKEN__", $Token)
$patch = $patch.Replace("__BOT_QQ__", $BotQq)
# 白名单展开成"每行一个"，模板里留的是 __ALLOW_USERS_LINES__ 这个整行占位符。
$userLines = ($Users | ForEach-Object { "      - $_" }) -join "`r`n"
$patch = $patch.Replace("__ALLOW_USERS_LINES__", $userLines)
$patch = $patch.Replace("__ALLOW_USER__", $AllowUser)
[IO.File]::WriteAllText((Join-Path $FishProf "cordis.patch.yml"), $patch, $Utf8NoBom)
Ok "package.json / cordis.yml / pnpm-workspace.yaml / cordis.patch.yml"

# setup.json —— 窗口里的新手指引用它拿称呼和 QQ 号
$setupPath = Join-Path $Target "config\setup.json"
if (-not (Test-Path -LiteralPath $setupPath)) {
    $setup = "{`r`n" +
             "  `"onboarded`": false,`r`n" +
             "  `"nickname`": `"`",`r`n" +
             "  `"botQq`": `"$BotQq`",`r`n" +
             "  `"allowUsers`": [" + (($Users | ForEach-Object { "`"$_`"" }) -join ", ") + "],`r`n" +
             "}`r`n"
    [IO.File]::WriteAllText($setupPath, $setup, $Utf8NoBom)
    Ok "config\setup.json（首次开窗口会引导你补称呼）"
}

# ============================================================ [5/9] 装依赖
Step "5/9" "装依赖（pnpm install）"

Write-Host "    这一步要联网，第一次比较慢，别关窗口。"
$r = Invoke-Native -Exe $NodeExe `
     -Arguments @($PnpmCjs, "install", "--prefer-offline", "--config.confirmModulesPurge=false") `
     -WorkDir $FishProf

if ($r.Code -ne 0) {
    Write-Host $r.Out -ForegroundColor DarkGray
    Die ("pnpm install 失败（退出码 " + $r.Code + "）。`n" +
         "绝大多数情况是网络问题：换网络或开代理后再跑一次 install.cmd。`n" +
         "如果提示某个 @deepseek-ai 包找不到，说明 DSH 装得不对，重装 DSH。")
}

$nm = Join-Path $FishProf "node_modules"
if (-not (Test-Path -LiteralPath $nm)) { Die "pnpm 说成功了但 node_modules 没生成，重跑一次看看" }
Ok "依赖装好"
foreach ($p in @("dsh-fishidian", "dsh-client-ui-fatfish", "dsh-qq-onebot-bridge", "dsh-pet")) {
    if (Test-Path -LiteralPath (Join-Path $nm $p)) { Ok "  $p" } else { Warn "  $p 没链上" }
}

# ---- 桥自己的依赖 ----
# 桥只依赖一个第三方包：ws（在 onebot.js 里 import）。它必须是**桥自己目录里**的，
# 因为 Node 是从"发生 import 的文件所在目录"往上爬找 node_modules，桥在
# $Target\dsh-qq-onebot-bridge 下，profile 那套 node_modules 不在它上行链上。
#
# 桥 import 的 @deepseek-ai/*（dsh-llm / dsh-session / dsh-tools / schemastery）
# **不要**装：这些由 DSH 进程在加载插件时用自己的运行时提供。实测两件事：
#   1. @deepseek-ai/dsh-session 声明了 peer @deepseek-ai/dsh-scope 0.2.0-rc.2，
#      而 npm 上 dsh-scope 只有 0.0.1-rc.1，版本对不上，装不下来；
#   2. 已经跑通的环境里，桥目录也的确没有 dsh-scope。
# 所以关掉 autoInstallPeers，只装 ws —— 顺带把桥依赖从 8.7 MB / 1196 文件
# 压到 152 KB / 22 文件，也避免桥里出现跟 DSH 版本不一致的 @deepseek-ai 副本。
#
# 为什么用 hoisted：pnpm 默认 isolated 模式造出来的是指向 .pnpm 的 junction，
# 拿这个包去别的电脑装、或整目录拷走，链接全断。hoisted 落的是真目录。
$bridgeDir = $Target + "\dsh-qq-onebot-bridge"
if (Test-Path -LiteralPath (Join-Path $bridgeDir "package.json")) {
    Write-Host "    桥自己的依赖（只有 ws 一个）..."
    $bridgeWsYml = "packages:`r`n  - .`r`n`r`nnodeLinker: hoisted`r`nautoInstallPeers: false`r`n"
    [IO.File]::WriteAllText((Join-Path $bridgeDir "pnpm-workspace.yaml"), $bridgeWsYml, $Utf8NoBom)

    $rb = Invoke-Native -Exe $NodeExe `
          -Arguments @($PnpmCjs, "install", "--prefer-offline", "--config.confirmModulesPurge=false") `
          -WorkDir $bridgeDir

    if ($rb.Code -ne 0) {
        Write-Host $rb.Out -ForegroundColor DarkGray
        Die ("桥的依赖装失败（退出码 " + $rb.Code + "）。`n" +
             "桥只依赖 ws 一个第三方包，失败基本是网络。换网络后再双击一次 install.cmd。")
    }

    $bridgeWs = Join-Path $bridgeDir "node_modules\ws\package.json"
    if (Test-Path -LiteralPath $bridgeWs) {
        # hoisted 下 ws 应是真目录，不是 junction；是 junction 说明装成了 isolated，
        # 拷到别的机器上是死链。
        $wi = Get-Item -LiteralPath (Join-Path $bridgeDir "node_modules\ws") -Force
        if ($wi.LinkType) {
            Warn ("  桥 ws 是软链接（" + $wi.LinkType + "），换机器会断；请重跑一次")
        } else {
            $wv = (Get-Content -LiteralPath $bridgeWs -Raw -Encoding UTF8 | ConvertFrom-Json).version
            Ok ("  桥 ws 就位（v" + $wv + "，真目录）")
        }
    } else {
        Warn "  桥 ws 没装上，QQ 通道会起不来（窗口本身不受影响）"
    }
} else {
    Warn "桥的 package.json 不见了，跳过桥依赖（QQ 通道会不可用）"
}

# ============================================================ [6/9] NapCat 检测
Step "6/9" "QQ 通道组件体检（NapCat）"

if ($SkipNapCat) {
    Warn "按参数跳过"
} else {
    $chk = Join-Path $Target "check_napcat.ps1"
    if (Test-Path -LiteralPath $chk) {
        $r = Invoke-Native -Exe "powershell.exe" `
             -Arguments @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", $chk)
        Write-Host $r.Out
        Write-Host ""
        Write-Host "    那两个 build 号不一致不用慌，先按 START-HERE 第 4 步真起一次，看二维码出不出来。"
    } else {
        Warn "没找到 check_napcat.ps1"
    }
}

# ============================================================ [7/9] 快捷方式
Step "7/9" "桌面快捷方式"

if ($NoShortcut) {
    Warn "按参数跳过"
} else {
    $lnkPath = Join-Path ([Environment]::GetFolderPath("Desktop")) "大肥鱼.lnk"
    $ps1 = Join-Path $Target "launch.ps1"
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($lnkPath)
    $lnk.TargetPath = "powershell.exe"
    $lnk.Arguments = "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$ps1`""
    $lnk.WorkingDirectory = $Target
    $lnk.IconLocation = "$DshExe,0"
    $lnk.WindowStyle = 7
    $lnk.Description = "打开大肥鱼的窗口（独立于工作 DSH）"
    $lnk.Save()
    Ok "桌面 大肥鱼.lnk"
}

# 一条纯 ASCII 的命令行入口，给计划任务和不信任中文路径的场合用
$runCmd = Join-Path $Target "run-fishidian.cmd"
$runBody = "@echo off`r`nchcp 65001 >nul`r`ncd /d `"%~dp0`"`r`n" +
           "powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"%~dp0launch.ps1`"`r`n"
[IO.File]::WriteAllText($runCmd, $runBody, $Utf8NoBom)
Ok "run-fishidian.cmd"

# ============================================================ [8/9] 内核自检
Step "8/9" "内核自检"

$coreDir = Join-Path $Target "fishidian-core"
$cli = Join-Path $coreDir "cli.py"
$db = Join-Path $MemDir "dfy.db"
if (-not (Test-Path -LiteralPath $cli)) {
    Warn "没找到 cli.py，跳过内核自检"
} else {
    $r = Invoke-Native -Exe $PyExe -Arguments @("-X", "utf8", $cli, "dsh:desktop", $db, "state")
    if ($r.Code -eq 0) {
        $head = ($r.Out -split "`n") | Select-Object -First 12
        foreach ($l in $head) { Write-Host ("    " + $l) }
        Ok "内核能跑（新库已建）"
    } else {
        $head = ($r.Out -split "`n") | Select-Object -First 20
        foreach ($l in $head) { Write-Host ("    " + $l) }
        Warn "内核自检没过。窗口能开，但记忆/五行那套可能不工作，按 START-HERE 的排错步骤看。"
    }
}

# ============================================================ [9/9] 完成
Step "9/9" "装完了"

Write-Host ""
Write-Host "  装在哪   : $Target" -ForegroundColor White
Write-Host "  程序数据 : $FishHome" -ForegroundColor White
Write-Host "  记忆库   : $MemDir\dfy.db（新装是空的，聊几天就有了）" -ForegroundColor White
Write-Host ""
Write-Host "  下一步看 : $Target\START-HERE.md" -ForegroundColor Yellow
Write-Host "             （同一目录还有 README.md 使用手册、VERSION.txt 模块清单、README.txt 目录说明）" -ForegroundColor DarkGray
Write-Host ""
# 装完立刻给一条可执行的验证命令：光看"窗口开了"很容易误判（插件没链上、
# ws 没装、QQ 号还是占位 0，窗口一样开得出来）。这一步只读不写。
Write-Host "  装完最好先验一次（只读，不重装）：" -ForegroundColor Cyan
Write-Host "    powershell -NoProfile -ExecutionPolicy Bypass -File `"$Target\verify_install.ps1`"" -ForegroundColor White
Write-Host "  它会逐项报窗口能不能开、QQ 通道还缺什么；绿了再去装 NapCat。" -ForegroundColor DarkGray
Write-Host ""
