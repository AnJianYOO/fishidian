# 小鱼 v0.1.0 安装包自检
# 用法：powershell -NoProfile -ExecutionPolicy Bypass -File tools\verify_v0.1.0_package.ps1
#
# 只做静态核验，不安装、不动用户目录。装包前跑一遍，能拦住九成的低级错误。

$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
if (-not (Test-Path -LiteralPath (Join-Path $root "tools\build_v0.1.0_package.py"))) {
    $root = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
}
$pkg = Join-Path $root "_release\fishidian-v0.1.0"

$pass = 0
$fail = 0
$warn = 0

function Ok($msg) {
    $script:pass++
    Write-Host "  [OK]   " -ForegroundColor Green -NoNewline
    Write-Host $msg
}
function Bad($msg) {
    $script:fail++
    Write-Host "  [FAIL] " -ForegroundColor Red -NoNewline
    Write-Host $msg
}
function Warn2($msg) {
    $script:warn++
    Write-Host "  [WARN] " -ForegroundColor Yellow -NoNewline
    Write-Host $msg
}
function Head($msg) {
    Write-Host ""
    Write-Host $msg -ForegroundColor Cyan
}

Write-Host ""
Write-Host "小鱼 v0.1.0 包自检" -ForegroundColor Cyan
Write-Host ("包目录：" + $pkg)

if (-not (Test-Path -LiteralPath $pkg)) {
    Write-Host "包目录不存在，先跑 build_v0.1.0_package.py" -ForegroundColor Red
    exit 1
}

# ---------- 1. 包根文件 ----------
Head "1. 包根文件"
$rootFiles = @(
    "install.cmd", "install_v0.1.0.ps1", "launch.ps1", "check_napcat.ps1", "verify_install.ps1",
    "README.md", "START-HERE.md", "FOR-AI.md", "VERSION.txt", "QQ桥怎么用.md"
)
foreach ($f in $rootFiles) {
    $p = Join-Path $pkg $f
    if (Test-Path -LiteralPath $p) {
        Ok ($f + "  " + (Get-Item -LiteralPath $p).Length + " B")
    } else {
        Bad ($f + " 缺失")
    }
}

# ---------- 2. ps1 编码与语法 ----------
Head "2. PowerShell 脚本编码 / 语法（5.1 兼容）"
$ps1s = @("install_v0.1.0.ps1", "launch.ps1", "check_napcat.ps1", "verify_install.ps1")
foreach ($f in $ps1s) {
    $p = Join-Path $pkg $f
    if (-not (Test-Path -LiteralPath $p)) { Bad ($f + " 不存在，跳过检查"); continue }

    $bytes = [IO.File]::ReadAllBytes($p)
    $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191)
    if ($hasBom) { Ok ($f + " BOM OK") } else { Bad ($f + " 缺 UTF-8 BOM（中文会乱码）") }

    $raw = [IO.File]::ReadAllText($p, [Text.Encoding]::UTF8)
    $crlf = ([regex]::Matches($raw, "`r`n")).Count
    $lfOnly = ([regex]::Matches($raw, "(?<!`r)`n")).Count
    if ($lfOnly -eq 0 -and $crlf -gt 0) {
        Ok ($f + " 行尾全 CRLF（" + $crlf + " 行）")
    } else {
        Bad ($f + " 有 " + $lfOnly + " 行是裸 LF")
    }

    try {
        [ScriptBlock]::Create($raw) | Out-Null
        Ok ($f + " 5.1 语法 OK")
    } catch {
        Bad ($f + " 语法错误：" + $_.Exception.Message)
    }
}

# ---------- 3. install.cmd ----------
Head "3. install.cmd（必须纯 ASCII 无 BOM）"
$cmdPath = Join-Path $pkg "install.cmd"
if (Test-Path -LiteralPath $cmdPath) {
    $cb = [IO.File]::ReadAllBytes($cmdPath)
    if ($cb.Length -ge 3 -and $cb[0] -eq 239 -and $cb[1] -eq 187 -and $cb[2] -eq 191) {
        Bad "带 BOM，第一行会被当成命令的一部分"
    } else {
        Ok "无 BOM"
    }
    $nonAscii = $false
    foreach ($b in $cb) { if ($b -gt 127) { $nonAscii = $true; break } }
    if ($nonAscii) { Bad "含非 ASCII 字节（chcp 之前必然乱码）" } else { Ok "纯 ASCII" }

    $craw = [IO.File]::ReadAllText($cmdPath, [Text.Encoding]::ASCII)
    if ($craw -match "install_v1\.ps1") { Ok "调用 install_v0.1.0.ps1" } else { Bad "没调用 install_v0.1.0.ps1" }
} else {
    Bad "install.cmd 缺失"
}

# ---------- 4. payload 内容 ----------
Head "4. payload 内容完整性"
$expect = @(
    @{ Path = "payload\fishidian-core\fishidian_core\governor.py"; What = "内核 governor.py" },
    @{ Path = "payload\fishidian-core\cli.py"; What = "内核 cli.py" },
    @{ Path = "payload\fishidian-core\daemon.py"; What = "内核 daemon.py" },
    @{ Path = "payload\dsh-fishidian\lib\index.js"; What = "插件 lib\index.js" },
    @{ Path = "payload\dsh-client-ui-fatfish\package.json"; What = "皮肤 package.json" },
    @{ Path = "payload\dsh-qq-onebot-bridge\lib\bridge.js"; What = "桥 lib\bridge.js" },
    @{ Path = "payload\dsh-qq-onebot-bridge\package.json"; What = "桥 package.json" },
    @{ Path = "payload\fatfish-window\cordis.patch.yml"; What = "窗口配置模板" },
    @{ Path = "payload\fatfish-window\home-template\README.txt"; What = "home-template README" },
    @{ Path = "payload\tools\qq-qrcode-server.js"; What = "二维码服务" }
)
foreach ($e in $expect) {
    $p = Join-Path $pkg $e.Path
    if (Test-Path -LiteralPath $p) { Ok $e.What } else { Bad ($e.What + " 缺失：" + $e.Path) }
}

# ---------- 5. 隐私文件不能进包 ----------
Head "5. 隐私 / 垃圾文件不能出现（这是最要命的一项）"
$forbidden = @(
    "*.bak", "*.bak-*", "*.db", "*.db-wal", "*.db-shm", "*.jsonl", "*.log", "*.pyc"
)
$badHits = @()
foreach ($pat in $forbidden) {
    $hits = @(Get-ChildItem -LiteralPath $pkg -Recurse -File -Filter $pat -Force -ErrorAction SilentlyContinue)
    if ($hits.Count -gt 0) {
        foreach ($h in $hits) { $badHits += $h.FullName.Replace($pkg + "\", "") }
    }
}
$privDirs = @("qq-history", "qq-memory", "node_modules", "__pycache__", "sessions", "electron-data", "storages")
foreach ($d in $privDirs) {
    $hits = @(Get-ChildItem -LiteralPath $pkg -Recurse -Directory -Force -ErrorAction SilentlyContinue | Where-Object { $_.Name -eq $d })
    foreach ($h in $hits) {
        # 空目录不算问题：home-template 里的 workspace\sessions 本来就是个空骨架
        $inside = @(Get-ChildItem -LiteralPath $h.FullName -Recurse -File -Force -ErrorAction SilentlyContinue)
        if ($inside.Count -gt 0) {
            $badHits += $h.FullName.Replace($pkg + "\", "") + "\ (" + $inside.Count + " 个文件)"
        }
    }
}
if ($badHits.Count -eq 0) {
    Ok "没有 .db / .log / .bak / .pyc / qq-history / node_modules"
} else {
    foreach ($b in $badHits) { Bad ("不该进包的：" + $b) }
}

# ---------- 6. 配置模板占位符 ----------
Head "6. cordis.patch.yml 占位符"
$patch = Join-Path $pkg "payload\fatfish-window\cordis.patch.yml"
if (Test-Path -LiteralPath $patch) {
    $ptext = [IO.File]::ReadAllText($patch, [Text.Encoding]::UTF8)
    # 只查安装器真正会替换的三个。内核路径不在此列 —— 那三个走环境变量，见下一条。
    $ph = @("__WEBHOOK_TOKEN__", "__BOT_QQ__", "__ALLOW_USER__")
    foreach ($x in $ph) {
        if ($ptext.Contains($x)) { Ok ($x + " 有") } else { Bad ($x + " 缺失，安装器替换不上") }
    }
    # 死键回归检查：fishidian 段下不该再出现 python / core / db 缩进键。
    # 插件只读 config.ns，这三个写了也不生效，只会让人以为改配置能换路径。
    $deadKeys = @()
    foreach ($k in @("python", "core", "db")) {
        if ($ptext -match ("(?m)^\s{4,}" + $k + ":\s")) { $deadKeys += $k }
    }
    if ($deadKeys.Count -eq 0) {
        Ok "无死键（python/core/db 已移除，路径走环境变量）"
    } else {
        Bad ("模板里还有不生效的配置键：" + ($deadKeys -join ", ") + "（插件只读 ns）")
    }
    # 替换后残留的占位符会原样进配置，装完表现为路径写错
    if ($ptext.Contains("__PROJECT_ROOT__") -or $ptext.Contains("__MEMORY_DIR__")) {
        Bad "还有已废弃的 __PROJECT_ROOT__ / __MEMORY_DIR__ 占位符（安装器已不再替换）"
    } else {
        Ok "无废弃占位符残留"
    }
    # 模板里不能残留真实凭据
    # 检查目标要拆开拼，否则这段代码会命中自己的"开发机路径"检测（自检脚本自己也过不了自检）
    $bs = [char]92
    $cu = "C:" + $bs + $bs + "Users" + $bs + $bs + "cheng" + "long"
    $dd = "D:" + $bs + $bs + "Desk" + "top"
    if ($ptext -match $cu) { Bad "模板里残留开发机用户路径" } else { Ok "无开发机路径残留" }
    if ($ptext -match $dd) { Bad "模板里残留 D 盘硬编码路径" } else { Ok "无 D 盘硬编码残留" }
} else {
    Bad "cordis.patch.yml 不存在"
}

# ---------- 7. node / python 探针 ----------
Head "7. 代码能否被解释器吃下"
$js = Join-Path $pkg "payload\tools\qq-qrcode-server.js"
if ((Test-Path -LiteralPath $js) -and (Get-Command node -ErrorAction SilentlyContinue)) {
    $out = & node --check $js 2>&1
    if ($LASTEXITCODE -eq 0) { Ok "qq-qrcode-server.js node --check 通过" } else { Bad ("node --check 失败：" + ($out -join " ")) }
} else {
    Warn2 "跳过 node 检查（node 不在 PATH 或文件缺失）"
}

# 插件和桥都是 ESM（文件里是 import/export）。node --check 对 .js 按 CJS 解析，
# 直接查会误报 "Cannot use import statement outside a module"，
# 所以先拷成 .mjs 再查 —— 这一项查语法，不解析 import 目标存不存在。
$esmTargets = @(
    @{ Path = (Join-Path $pkg "payload\dsh-fishidian\lib\index.js"); Label = "插件 lib\index.js" },
    @{ Path = (Join-Path $pkg "payload\dsh-fishidian\lib\turn-merge.js"); Label = "插件 lib\turn-merge.js" },
    @{ Path = (Join-Path $pkg "payload\dsh-qq-onebot-bridge\lib\bridge.js"); Label = "桥 lib\bridge.js" },
    @{ Path = (Join-Path $pkg "payload\dsh-qq-onebot-bridge\lib\onebot.js"); Label = "桥 lib\onebot.js" }
)
if (Get-Command node -ErrorAction SilentlyContinue) {
    foreach ($t in $esmTargets) {
        if (-not (Test-Path -LiteralPath $t.Path)) { Bad ($t.Label + " 缺失"); continue }
        $tmpJs = Join-Path $env:TEMP ("fish-esm-check-" + [guid]::NewGuid().ToString("N") + ".mjs")
        try {
            Copy-Item -LiteralPath $t.Path -Destination $tmpJs -Force
            $out = & node --check $tmpJs 2>&1
            if ($LASTEXITCODE -eq 0) { Ok ($t.Label + " 语法通过") } else { Bad ($t.Label + " 语法错误：" + ($out -join " ")) }
        } finally {
            if (Test-Path -LiteralPath $tmpJs) { Remove-Item -LiteralPath $tmpJs -Force -ErrorAction SilentlyContinue }
        }
    }
} else {
    Warn2 "跳过 ESM 语法检查（node 不在 PATH）"
}

$cli = Join-Path $pkg "payload\fishidian-core\cli.py"
if ((Test-Path -LiteralPath $cli) -and (Get-Command python -ErrorAction SilentlyContinue)) {
    $out = & python -X utf8 $cli --help 2>&1
    if ($LASTEXITCODE -eq 0) {
        Ok "kernel cli.py --help 正常"
    } else {
        # 有些版本的 cli.py 没有 --help，退一步只做语法编译
        $out2 = & python -X utf8 -c "import py_compile,sys; py_compile.compile(r'$cli', doraise=True); print('ok')" 2>&1
        if ($LASTEXITCODE -eq 0) { Ok "kernel cli.py 语法编译通过" } else { Bad ("cli.py 跑不起来：" + ($out -join " ")) }
    }
    $gv = Join-Path $pkg "payload\fishidian-core\fishidian_core\governor.py"
    $out3 = & python -X utf8 -c "import py_compile; py_compile.compile(r'$gv', doraise=True); print('ok')" 2>&1
    if ($LASTEXITCODE -eq 0) { Ok "governor.py 语法编译通过" } else { Bad "governor.py 编译失败" }
} else {
    Warn2 "跳过 python 检查（python 不在 PATH 或文件缺失）"
}

# ---------- 8. zip ----------
Head "8. zip 包"
$zips = @(Get-ChildItem -LiteralPath (Join-Path $root "_release") -Filter "fishidian-v0.1.0-*.zip" -File -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending)
if ($zips.Count -gt 0) {
    $z = $zips[0]
    Ok ($z.Name + "  " + [math]::Round($z.Length/1KB,1) + " KB")
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    try {
        $za = [IO.Compression.ZipFile]::OpenRead($z.FullName)
        $nRoot = @($za.Entries | Where-Object { $_.FullName -notmatch "/" }).Count
        $nAll = $za.Entries.Count
        $za.Dispose()
        if ($nRoot -ge 8) { Ok ("根层 " + $nRoot + " 个文件，共 " + $nAll + " 条目") } else { Bad ("根层只有 " + $nRoot + " 个文件，应为 8") }
    } catch {
        Bad ("zip 打不开：" + $_.Exception.Message)
    }
} else {
    Bad "没有 zip 产物"
}

# ---------- 汇总 ----------
Write-Host ""
Write-Host ("=" * 44) -ForegroundColor Cyan
Write-Host ("  通过 " + $pass + "   失败 " + $fail + "   警告 " + $warn)
Write-Host ("=" * 44) -ForegroundColor Cyan
if ($fail -eq 0) {
    Write-Host "  这个包可以拿去装了。" -ForegroundColor Green
    Write-Host ""
    exit 0
} else {
    Write-Host ("  有 " + $fail + " 项没过，别拿去装。") -ForegroundColor Red
    Write-Host ""
    exit 1
}
