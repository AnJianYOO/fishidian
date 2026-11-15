# 大肥鱼 一键启动
# 双击桌面「大肥鱼」就会跑这个脚本：拉起二维码服务 -> 开她的窗口 -> 拉 QQ 通道。
#
# 这个文件在安装包里叫 payload 之外的同级，安装后落在安装根（默认
#   %USERPROFILE%\fishidian\launch.ps1，但 install_v1.ps1 的 -TargetRoot 可以装到别处）。
# tools\qq-qrcode-server.js 也在同一层，所以 $PSScriptRoot 相对路径可直接用。

$ErrorActionPreference = "SilentlyContinue"

# ---------- 1. 定位她的数据目录 ----------
# 四段优先级。第一段是"自己所在目录"——安装器允许 -TargetRoot 装到任意位置，
# 只看 %USERPROFILE% 的话，装到 D:\fishidian 或临时目录就会找不到数据、开成空壳。
#   $PSScriptRoot\data               本次安装实际落点（最可靠）
#   %USERPROFILE%\fishidian\data     默认安装位置
#   %USERPROFILE%\大肥鱼\data        早期结构
#   %USERPROFILE%\.dsh-fatfish       最早结构
$fishRoot = Join-Path $env:USERPROFILE "fishidian"
$newRoot  = Join-Path $env:USERPROFILE "大肥鱼"
$oldRoot  = Join-Path $env:USERPROFILE ".dsh-fatfish"

if ($PSScriptRoot -and (Test-Path -LiteralPath (Join-Path $PSScriptRoot "data\profiles"))) {
    $dataRoot = Join-Path $PSScriptRoot "data"
} elseif (Test-Path -LiteralPath (Join-Path $fishRoot "data\profiles")) {
    $dataRoot = Join-Path $fishRoot "data"
} elseif (Test-Path -LiteralPath (Join-Path $newRoot "data\profiles")) {
    $dataRoot = Join-Path $newRoot "data"
} elseif (Test-Path -LiteralPath (Join-Path $oldRoot "profiles")) {
    $dataRoot = $oldRoot
} else {
    $dataRoot = Join-Path $fishRoot "data"
}

# ---------- 2. 二维码小服务 ----------
# 它秒起、不弹窗，窗口一起来就要查它，所以放最前面。
# 旧实例一律换掉：改了服务端代码却不重启进程，会出现"明明改过了却没反应"。
$qrJs = Join-Path $PSScriptRoot "tools\qq-qrcode-server.js"
Get-CimInstance Win32_Process -Filter "Name='node.exe'" |
    Where-Object { $_.CommandLine -like "*qq-qrcode-server.js*" } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 300

# node 的绝对路径：先用 PATH，再试默认安装位置。
# 为什么不能直接写 "node.exe"：快捷方式拉起的进程和用户在终端里跑的进程，
# PATH 未必一致（刚装完 Node 没重开资源管理器就是这个症状）。找不到时
# Start-Process 在 SilentlyContinue 下静默失败，表现是点「连 QQ」一片白框，
# 没有任何提示。所以这里显式找一次，找不到就说出来。
$nodeExe = (Get-Command node -ErrorAction SilentlyContinue).Source
if (-not $nodeExe) {
    foreach ($cand in @((Join-Path $env:ProgramFiles "nodejs\node.exe"),
                        (Join-Path ${env:ProgramFiles(x86)} "nodejs\node.exe"),
                        (Join-Path $env:LOCALAPPDATA "Programs\nodejs\node.exe"))) {
        if ($cand -and (Test-Path -LiteralPath $cand)) { $nodeExe = $cand; break }
    }
}
if ((Test-Path -LiteralPath $qrJs) -and $nodeExe) {
    Start-Process -FilePath $nodeExe -ArgumentList ('"' + $qrJs + '"') -WindowStyle Hidden
} elseif (-not $nodeExe) {
    Write-Host "  没找到 node —— 二维码服务起不来，窗口里点「连 QQ」会是白框。"
    Write-Host "  装 Node.js 18 以上（nodejs.org），然后重开这个窗口。"
    Start-Sleep -Seconds 2
}

# ---------- 2.5 内核三件套（必须在起窗口之前设进环境） ----------
# 插件的 config 只读 ns —— cordis.patch.yml 里的 python / core / db 三个键
# 是死配置（见 dsh-fishidian/lib/index.js 的 PYTHON / _resolveCore / dbPath）。
# 真正生效的是下面这三个环境变量，由启动器打到 DSH 子进程上：
#   FISHIDIAN_CORE    内核目录。不设时插件会逐级向上找，node_modules 布局下要多绕几层
#   FISHIDIAN_DB      记忆库完整路径。不设会落到 ~/.dsh\fishidian-memory\fishidian.db，
#                     和文档/验收清单里的 workspace\memory\dfy.db 不是一个文件
#   FISHIDIAN_PYTHON  python 绝对路径。不设就是裸 "python"，
#                     GUI 进程 PATH 里没有它时 spawnSync 全失败 → 她"失忆"但无报错
# 安装根 = 这个脚本所在的目录（launch.ps1 就落在安装根）。
# 早期那种 ~\.dsh-fatfish 结构下 $PSScriptRoot 未必是安装根，
# 所以拿 $dataRoot 的上一级兜一次 —— 安装包场景两者是同一个目录，这一步不会改变结果。
$fishHome = $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $fishHome "fishidian-core\cli.py"))) {
    $alt = Split-Path -Parent $dataRoot
    if ($alt -and (Test-Path -LiteralPath (Join-Path $alt "fishidian-core\cli.py"))) { $fishHome = $alt }
}
$fishCore = Join-Path $fishHome "fishidian-core"
$fishDb   = Join-Path $fishHome "workspace\memory\dfy.db"
if (Test-Path -LiteralPath (Join-Path $fishCore "cli.py")) {
    $env:FISHIDIAN_CORE = $fishCore
} else {
    Write-Host ("  注意：$fishCore 里没有 cli.py，内核可能起不来。")
}
$env:FISHIDIAN_DB = $fishDb

# python 绝对路径。安装器会把它写进同目录的 python-path.txt，优先用那个；
# 没有就现找。写文件而不是写死在脚本里，是因为用户以后可能升级/换位置。
$pyHint = Join-Path $fishHome "python-path.txt"
$pyExe = $null
if (Test-Path -LiteralPath $pyHint) {
    $t = ([IO.File]::ReadAllText($pyHint, [Text.Encoding]::UTF8)).Trim()
    if ($t -and (Test-Path -LiteralPath $t)) { $pyExe = $t }
}
if (-not $pyExe) {
    foreach ($c in @("python", "py")) {
        $cmd = Get-Command $c -ErrorAction SilentlyContinue
        if ($cmd) { $pyExe = $cmd.Source; break }
    }
}
if ($pyExe) {
    $env:FISHIDIAN_PYTHON = $pyExe
} else {
    Write-Host "  没找到 python —— 记忆/五行那套会静默不工作（窗口本身照开）。"
}

# ---------- 3. 开她的窗口 ----------
# 先开窗口再拉 QQ：反过来会让黑框和 UAC 先盖在桌面上，观感是"先弹个框，然后才轮到她"。
# 独立窗口不是另一个 app，而是第二个 DSH 实例：独立 DSH_HOME + 独立 --user-data-dir，
# 皮肤由 profile 里装的 dsh-client-ui-fatfish 换。
$env:DSH_HOME = $dataRoot
$exe = Join-Path $env:LOCALAPPDATA "Programs\DeepSeek Harness\DeepSeek Harness.exe"
if (Test-Path -LiteralPath $exe) {
    Start-Process -FilePath $exe -ArgumentList ("--user-data-dir=" + (Join-Path $dataRoot "electron-data"))
} else {
    Write-Host "  没找到 DeepSeek Harness，先装它再打开这个窗口。"
    Write-Host ("  预期位置：" + $exe)
    Start-Sleep -Seconds 3
    exit 1
}

# ---------- 4. 再拉 QQ 通道 ----------
# 等窗口真的露头再拉 QQ。判据是"主窗口句柄出现"而不是"进程存在"——
# DSH 起来时先有几个没窗口的后台进程，只判进程会在窗口还没画出来时就弹 UAC。
# 最多等 25 秒，超时按当前状态继续，不卡死她。
$deadline = (Get-Date).AddSeconds(25)
$woke = $false
while ((Get-Date) -lt $deadline) {
    $ui = Get-Process -Name "DeepSeek Harness" -ErrorAction SilentlyContinue |
          Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
    if ($ui) { $woke = $true; break }
    Start-Sleep -Milliseconds 250
}
if (-not $woke) { Write-Host "  （25 秒没等到主窗口，先按当前状态继续，不影响她用）" }

$nb = Join-Path $env:USERPROFILE "NapCat"
$napBat = Join-Path $nb "launcher.bat"
$napRunning = Get-Process -Name "NapCatWinBootMain","NapCat" -ErrorAction SilentlyContinue
if (-not $napRunning -and (Test-Path -LiteralPath $napBat)) {
    # 为什么绕一层 VBS：直接 Start-Process launcher.bat -Verb RunAs 时，
    # launcher.bat 里的 `net session` 自检还没生效，它会走"非管理员"分支去调
    # launcher-elevate.ps1 → wt.exe，那个 Windows Terminal 黑框就是这么冒出来的。
    # ShellExecute 的第 5 个参数 0 = 隐藏窗口：提权后进程本身是管理员，
    # launcher.bat 走 :napcat_admin 分支直接注入 QQ，不再有 wt 窗口。
    # UAC 授权框仍会弹一次——Windows 规定提权必须本人点，这个绕不过。
    $vbs = Join-Path $env:TEMP "fishidian-launch-napcat.vbs"
    $q = [char]34
    $line1 = 'Set sh = CreateObject("Shell.Application")'
    $line2 = 'sh.ShellExecute "cmd.exe", "/c ""' + $napBat + '""", "' + $nb + '", "runas", 0'
    # 存 UTF-16LE：VBS 默认按 ANSI 读，用户名或路径里有中文时 ANSI 会读坏
    [IO.File]::WriteAllText($vbs, ($line1 + "`r`n" + $line2 + "`r`n"), [Text.Encoding]::Unicode)
    Start-Process -FilePath "wscript.exe" -ArgumentList ($q + $vbs + $q)
} elseif (-not (Test-Path -LiteralPath $napBat)) {
    Write-Host "  QQ 通道还不完整：没找到 NapCat，所以这次只开窗口，QQ 那边先不通。"
    Write-Host "  想用 QQ：先跑一遍 check_napcat.ps1 看缺什么。"
}
