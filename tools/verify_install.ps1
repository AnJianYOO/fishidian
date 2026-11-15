# 大肥鱼 V1 装完验证
# ---------------------------------------------------------------------------
# 用法（装完在同一个命令行里跑）：
#   powershell -NoProfile -ExecutionPolicy Bypass -File "%USERPROFILE%\fishidian\verify_install.ps1"
#
# 也可以指定安装根（装到别处时）：
#   ... -File verify_install.ps1 -TargetRoot "D:\fishidian"
#
# 它只读不写（唯一会写的是让内核建一次空库，和首次开窗口时做的事一样）。
# 为什么要有它：START-HERE 让人肉眼验四条，"窗口开了"很容易误判成功 ——
# 插件没链上、ws 没装、QQ 号还是占位 0，窗口照样开得出来。这里把能判的都判掉。
# ---------------------------------------------------------------------------
param(
    [string]$TargetRoot = ""
)

$ErrorActionPreference = "Continue"

$pass = 0
$fail = 0
$warn = 0

function Ok($m) {
    $script:pass++
    Write-Host "  [OK]   " -ForegroundColor Green -NoNewline
    Write-Host $m
}
function Bad($m) {
    $script:fail++
    Write-Host "  [FAIL] " -ForegroundColor Red -NoNewline
    Write-Host $m
}
function Warn2($m) {
    $script:warn++
    Write-Host "  [WARN] " -ForegroundColor Yellow -NoNewline
    Write-Host $m
}
function Head($m) {
    Write-Host ""
    Write-Host $m -ForegroundColor Cyan
}

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

if (-not $TargetRoot) { $TargetRoot = Join-Path $env:USERPROFILE "fishidian" }
$Target   = $TargetRoot
$FishProf = Join-Path $Target "data\profiles\desktop"
$MemDir   = Join-Path $Target "workspace\memory"
$CoreDir  = Join-Path $Target "fishidian-core"
$BridgeDir = Join-Path $Target "dsh-qq-onebot-bridge"

Write-Host ""
Write-Host "大肥鱼 V1 装完验证" -ForegroundColor Cyan
Write-Host ("安装根：" + $Target)

# ---------- 1. 运行时版本 ----------
Head "1. 运行时"

$node = (Get-Command node -ErrorAction SilentlyContinue).Source
if ($node) {
    $nr = Invoke-Native -Exe $node -Arguments @("--version")
    $nv = (($nr.Out -split "`n") | Select-Object -First 1).Trim()
    if ($nv -match 'v(\d+)\.') {
        if ([int]$Matches[1] -ge 18) { Ok ("Node " + $nv + "（≥18）") }
        else { Bad ("Node " + $nv + " 低于 18，QQ 通道起不来（要 fetch / AbortSignal.timeout / structuredClone）") }
    } else { Bad ("读不出 node 版本：" + $nv) }
} else {
    Bad "找不到 node"
}

$py = $null
foreach ($c in @("python", "py")) {
    $cmd = Get-Command $c -ErrorAction SilentlyContinue
    if ($cmd) { $py = $cmd.Source; break }
}
if ($py) {
    $pr = Invoke-Native -Exe $py -Arguments @("--version")
    $pv = (($pr.Out -split "`n") | Select-Object -First 1).Trim()
    if ($pv -match '(\d+)\.(\d+)') {
        $maj = [int]$Matches[1]
        $min = [int]$Matches[2]
        if ($maj -lt 3 -or ($maj -eq 3 -and $min -lt 8)) { Bad ("Python " + $pv + " 低于 3.8") }
        else { Ok ("Python " + $pv) }
    } else { Bad ("读不出 python 版本：" + $pv + "（可能是 Store 占位程序）") }
} else {
    Bad "找不到 python"
}

# ---------- 2. 安装根与副本 ----------
Head "2. 安装根"

if (Test-Path -LiteralPath $Target) { Ok ("安装根存在（" + $Target + "）") }
else {
    Bad "安装根不存在 —— 安装没跑成，或者被删了"
}

$needFiles = @(
    @{ p = (Join-Path $Target "launch.ps1");                                n = "launch.ps1" },
    @{ p = (Join-Path $Target "check_napcat.ps1");                          n = "check_napcat.ps1" },
    @{ p = (Join-Path $Target "tools\qq-qrcode-server.js");                n = "tools\qq-qrcode-server.js" },
    @{ p = (Join-Path $Target "START-HERE.md");                            n = "START-HERE.md" },
    @{ p = (Join-Path $CoreDir "cli.py");                                  n = "fishidian-core\cli.py" },
    @{ p = (Join-Path $BridgeDir "lib\bridge.js");                         n = "桥 lib\bridge.js" },
    @{ p = (Join-Path $BridgeDir "lib\onebot.js");                         n = "桥 lib\onebot.js" },
    @{ p = (Join-Path $Target "dsh-client-ui-fatfish\lib\index.js");       n = "皮肤 lib\index.js" },
    @{ p = (Join-Path $Target "dsh-fishidian\lib\index.js");               n = "插件 lib\index.js" }
)
foreach ($f in $needFiles) {
    if (Test-Path -LiteralPath $f.p) { Ok $f.n } else { Bad ($f.n + " 缺失") }
}

# ---------- 3. profile 与依赖 ----------
Head "3. 窗口 profile"

$pkg = Join-Path $FishProf "package.json"
if (Test-Path -LiteralPath $pkg) {
    try {
        $pj = [IO.File]::ReadAllText($pkg, [Text.Encoding]::UTF8) | ConvertFrom-Json
        $deps = @($pj.dependencies.PSObject.Properties.Name)
        foreach ($d in @("dsh-fishidian", "dsh-client-ui-fatfish", "dsh-qq-onebot-bridge")) {
            if ($deps -contains $d) { Ok ("package.json 含 " + $d) } else { Bad ("package.json 缺 " + $d) }
        }
    } catch {
        Bad "package.json 读不出来（JSON 坏了）"
    }
} else {
    Bad "profile\package.json 缺失 —— 第 4 步没跑完"
}

$nm = Join-Path $FishProf "node_modules"
if (Test-Path -LiteralPath $nm) {
    Ok "profile\node_modules 已生成"
    foreach ($d in @("dsh-fishidian", "dsh-client-ui-fatfish", "dsh-qq-onebot-bridge")) {
        if (Test-Path -LiteralPath (Join-Path $nm $d)) { Ok ("  链上 " + $d) }
        else { Bad ("  " + $d + " 没链上 —— 窗口里会缺功能") }
    }
} else {
    Bad "profile\node_modules 不存在 —— pnpm install 没成功"
}

# 桥的 ws：只影响 QQ 通道，窗口本身照常。但要用 QQ 就必须有。
$wsPkg = Join-Path $BridgeDir "node_modules\ws\package.json"
if (Test-Path -LiteralPath $wsPkg) {
    $wsItem = Get-Item -LiteralPath (Join-Path $BridgeDir "node_modules\ws") -Force
    if ($wsItem.LinkType) {
        Bad ("桥的 ws 是软链接（" + $wsItem.LinkType + "），换机器会断；重跑一次 install.cmd")
    } else {
        $wv = ([IO.File]::ReadAllText($wsPkg, [Text.Encoding]::UTF8) | ConvertFrom-Json).version
        Ok ("桥 ws 就位（v" + $wv + "，真目录）")
    }
} else {
    Warn2 "桥的 ws 没装上 —— 窗口能开，但 QQ 通道起不来。要用 QQ 就重跑一次 install.cmd"
}

# ---------- 4. 配置 ----------
Head "4. 配置"

$cfg = Join-Path $FishProf "cordis.patch.yml"
if (Test-Path -LiteralPath $cfg) {
    $txt = [IO.File]::ReadAllText($cfg, [Text.Encoding]::UTF8)
    Ok "cordis.patch.yml 存在"
    if ($txt -match 'botQq:\s*([0-9]+)') {
        $qq = $Matches[1]
        if ($qq -eq "0") {
            Warn2 "botQq 还是占位 0 —— QQ 通道不会工作，补上机器人的 QQ 号再重跑 install.cmd"
        } else {
            Ok ("botQq = " + $qq)
        }
    } else {
        Warn2 "cordis.patch.yml 里没找到 botQq"
    }
    # allowUsers 有两种合法写法：模板出来的是 YAML 列表（换行 + 缩进 - 号），
    # 安装器第 334 行写的是行内数组。只认前者会误报"没配"，两种都要接。
    $auInline = $txt -match 'allowUsers:\s*\[[^\]]+\]'
    $auBlock  = $txt -match 'allowUsers:\s*\r?\n\s+-\s*\S'
    if ($auInline -or $auBlock) { Ok "allowUsers 已配置" } else { Warn2 "allowUsers 没配 —— 没人能和她说上话" }
} else {
    Bad "cordis.patch.yml 缺失"
}

# ---------- 4.5 内核三件套 ----------
# 这一节查的是"装到干净机器上最容易静默失效"的三条链路。
# 它们的共同点是：配置里看着对，跑起来不报错，只是她失忆 / 记忆不增长。
Head "4.5 内核路径（静默失效高发区）"

$launchPath = Join-Path $Target "launch.ps1"
if (Test-Path -LiteralPath $launchPath) {
    $ltext = [IO.File]::ReadAllText($launchPath, [Text.Encoding]::UTF8)
    foreach ($v in @("FISHIDIAN_CORE", "FISHIDIAN_DB", "FISHIDIAN_PYTHON")) {
        if ($ltext.Contains($v)) { Ok ("launch.ps1 会设 " + $v) }
        else { Bad ("launch.ps1 没设 " + $v + " —— 这一条不设，她是会失忆的，而且不报错") }
    }
} else {
    Bad "launch.ps1 缺失"
}

# python-path.txt：安装器写下的 python 绝对路径。不在时 launch.ps1 会退到裸命令，
# 而窗口进程的 PATH 未必含 python。
$pyHint = Join-Path $Target "python-path.txt"
if (Test-Path -LiteralPath $pyHint) {
    $hint = ([IO.File]::ReadAllText($pyHint, [Text.Encoding]::UTF8)).Trim()
    if ($hint -and (Test-Path -LiteralPath $hint)) { Ok ("python-path.txt 有效（" + $hint + "）") }
    elseif ($hint) { Warn2 ("python-path.txt 指向的路径不存在：" + $hint + " —— launch.ps1 会退到裸 python") }
    else { Warn2 "python-path.txt 是空的，launch.ps1 会退到裸 python" }
} else {
    Warn2 "没有 python-path.txt（旧安装包的产物）。launch.ps1 会退到裸 python，GUI 进程 PATH 里没有它时内核不工作"
}

# 插件必须支持 FISHIDIAN_DB，否则记忆库会落到 ~/.dsh\fishidian-memory\fishidian.db，
# 和文档里的 workspace\memory\dfy.db 不是一个文件 —— 用户按验收清单看它永远不增长。
$pluginJs = Join-Path $Target "dsh-fishidian\lib\index.js"
if (Test-Path -LiteralPath $pluginJs) {
    $jtext = [IO.File]::ReadAllText($pluginJs, [Text.Encoding]::UTF8)
    if ($jtext.Contains("FISHIDIAN_DB")) { Ok "插件支持 FISHIDIAN_DB（库会落在安装根下）" }
    else { Bad "插件不支持 FISHIDIAN_DB —— 记忆库会建到 ~/.dsh\fishidian-memory\fishidian.db，不是文档写的那个" }
    # 逐级向上找内核的实现（旧版写死 ..\..\，在 node_modules 布局下必然落空）
    if ($jtext -match "for \(let i = 0; i < 8; i\+\+\)") { Ok "内核目录逐级查找已启用" }
    else { Warn2 "内核目录还是旧的固定层数查找，node_modules 布局下可能落到开发机路径（由环境变量兜着）" }
} else {
    Bad "缺 dsh-fishidian\lib\index.js"
}

# 配置模板里残留的死键
$cfgTpl = Join-Path $FishProf "cordis.patch.yml"
if (Test-Path -LiteralPath $cfgTpl) {
    $ctext = [IO.File]::ReadAllText($cfgTpl, [Text.Encoding]::UTF8)
    $dead = @()
    foreach ($k in @("python", "core", "db")) {
        if ($ctext -match ("(?m)^\s{4,}" + $k + ":\s")) { $dead += $k }
    }
    if ($dead.Count -eq 0) { Ok "cordis.patch.yml 无死键" }
    else { Warn2 ("cordis.patch.yml 还有不生效的键：" + ($dead -join ", ") + "（插件只读 ns，改这里换不了路径）") }
} else {
    Bad "cordis.patch.yml 缺失"
}

# ---------- 5. 数据目录 ----------
Head "5. 数据目录"

foreach ($d in @($MemDir, (Join-Path $Target "workspace\sessions"), (Join-Path $Target "logs"), (Join-Path $Target "backup"))) {
    if (Test-Path -LiteralPath $d) { Ok ((Split-Path -Leaf $d) + " 目录在") } else { Bad ((Split-Path -Leaf $d) + " 目录缺失") }
}

$db = Join-Path $MemDir "dfy.db"
if (Test-Path -LiteralPath $db) {
    Ok ("dfy.db 已存在（" + (Get-Item -LiteralPath $db).Length + " B）")
} else {
    Warn2 "记忆库还没建 —— 首次开窗口或下面这步自检会建出来"
}

# ---------- 6. 内核能不能跑 ----------
Head "6. 内核自检"

$cli = Join-Path $CoreDir "cli.py"
if ((Test-Path -LiteralPath $cli) -and $py) {
    $r = Invoke-Native -Exe $py -Arguments @("-X", "utf8", $cli, "dsh:desktop", $db, "state")
    if ($r.Code -eq 0) {
        Ok "内核能跑（cli.py state 正常返回）"
        $head = ($r.Out -split "`n") | Select-Object -First 6
        foreach ($l in $head) { Write-Host ("         " + $l) -ForegroundColor DarkGray }
    } else {
        Bad "内核跑不起来（退出码 " + $r.Code + "）"
        $head = ($r.Out -split "`n") | Select-Object -First 12
        foreach ($l in $head) { Write-Host ("         " + $l) -ForegroundColor DarkGray }
    }
} else {
    Bad "缺 cli.py 或 python，跳过内核自检"
}

# ---------- 7. 桌面快捷方式 ----------
Head "7. 快捷方式"

$lnk = Join-Path ([Environment]::GetFolderPath("Desktop")) "大肥鱼.lnk"
if (Test-Path -LiteralPath $lnk) { Ok "桌面 大肥鱼.lnk 在" }
else { Warn2 "桌面没有 大肥鱼.lnk（用 -NoShortcut 装的话是正常的，可以手动建一个指向 launch.ps1）" }

# ---------- 汇总 ----------
Head "汇总"
Write-Host ("  通过 " + $pass + " ｜ 失败 " + $fail + " ｜ 注意 " + $warn)
if ($fail -eq 0) {
    Write-Host ""
    Write-Host "  没有硬失败。双击桌面「大肥鱼」应该能开出窗口。" -ForegroundColor Green
    if ($warn -gt 0) { Write-Host "  上面还有几条「注意」，不影响开窗口，但可能影响 QQ 通道。" -ForegroundColor Yellow }
} else {
    Write-Host ""
    Write-Host ("  有 " + $fail + " 项硬失败。按上面每条的提示处理，或者重跑一次 install.cmd（不会覆盖记忆库）。") -ForegroundColor Red
    Write-Host "  还是不行就把这份输出和 FOR-AI.md 一起丢给 AI。" -ForegroundColor Red
}
Write-Host ""
exit $(if ($fail -eq 0) { 0 } else { 1 })
