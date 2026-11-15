# 读本机 QQ 的 build 号 和 NapCat 的目标 build，并排报出来。
#
# 这个脚本只负责把数字读准，不下"能不能用"的结论。
# 为什么不做判断：NapCat 每个 release 声明的兼容范围都不一样，写死在脚本里必然过期；
# 而实际见过 QQ 9.9.19(35469) 配 NapCat 目标 40990 这种"看着不匹配"、却照样能出码的情况，
# 所以脚本只给事实，判断交给读 release 页的一方。
#
# 用法：
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File check_napcat.ps1
#   powershell.exe -NoProfile -ExecutionPolicy Bypass -File check_napcat.ps1 -Json

param(
    [switch]$Json
)

$ErrorActionPreference = "SilentlyContinue"

function Say($m) { Write-Host "  $m" }

# ---------- 1. 找 QQ（QQNT），取 build ----------
# 顺序：跑着的进程 > 常见安装路径 > 各盘根下的 QQ
# 用户这台把 QQ 装在 D:\QQ，不在 Program Files，所以进程和盘根都要扫。
$qqExe = $null

$proc = Get-Process -Name "QQ" -ErrorAction SilentlyContinue |
        Where-Object { $_.Path -and (Test-Path -LiteralPath $_.Path) } |
        Select-Object -First 1
if ($proc) { $qqExe = $proc.Path }

if (-not $qqExe) {
    $cands = @(
        "C:\Program Files\Tencent\QQNT\QQ.exe",
        "C:\Program Files (x86)\Tencent\QQNT\QQ.exe",
        "$env:LOCALAPPDATA\Programs\Tencent\QQNT\QQ.exe",
        "C:\Program Files\Tencent\QQ\QQ.exe",
        "C:\Program Files (x86)\Tencent\QQ\QQ.exe"
    )
    foreach ($drv in (Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Name -match "^[C-Z]$" })) {
        $cands += (Join-Path ($drv.Name + ":\") "QQ\QQ.exe")
    }
    foreach ($p in $cands) {
        if (Test-Path -LiteralPath $p) { $qqExe = $p; break }
    }
}

$qqFileVer = ""
$qqBuild = ""
$qqAppVer = ""
if ($qqExe) {
    $qqFileVer = [string](Get-Item -LiteralPath $qqExe).VersionInfo.FileVersion
    # 9.9.19.35469 这种四段号，最后一段就是 build
    if ($qqFileVer -match "^\d+\.\d+\.\d+\.(\d+)$") { $qqBuild = $Matches[1] }
    elseif ($qqFileVer -match "([0-9]{4,})") { $qqBuild = $Matches[1] }

    # QQNT 自己的构建号比 exe 文件版本更准，读到就用它覆盖
    $app = Join-Path (Split-Path -Parent $qqExe) "resources\app\package.json"
    if (Test-Path -LiteralPath $app) {
        try {
            $j = Get-Content -LiteralPath $app -Raw -Encoding utf8 | ConvertFrom-Json
            if ($j.version) {
                $qqAppVer = [string]$j.version
                if ($qqAppVer -match "-([0-9]{4,})") { $qqBuild = $Matches[1] }
            }
        } catch { }
    }
}

# ---------- 2. 找 NapCat，取它对接的目标 build ----------
# NapCat 自己的 package.json 里 version 是占位的 0.0.1，不能用来判断；
# 真正的对接信息在 qqnt.json 的 buildVersion（这个数字才是"它是按哪个 QQ 版本做的"）。
$napRoots = @()
foreach ($d in @($env:USERPROFILE, "$env:USERPROFILE\Desktop", "$env:USERPROFILE\Downloads", "C:\", "D:\", "E:\")) {
    if (-not (Test-Path -LiteralPath $d)) { continue }
    Get-ChildItem -LiteralPath $d -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "NapCat*" } |
        ForEach-Object { $napRoots += $_.FullName }
}
$napRoots = @($napRoots | Select-Object -Unique)

$napCat = $null
$napTargetVer = ""
$napTargetBuild = ""
foreach ($r in $napRoots) {
    $q = Join-Path $r "qqnt.json"
    if (Test-Path -LiteralPath $q) {
        try {
            $j = Get-Content -LiteralPath $q -Raw -Encoding utf8 | ConvertFrom-Json
            if ($j.version) { $napTargetVer = [string]$j.version }
            if ($j.buildVersion) { $napTargetBuild = [string]$j.buildVersion }
            elseif ($napTargetVer -match "-([0-9]{4,})") { $napTargetBuild = $Matches[1] }
        } catch { }
        $napCat = $r
        break
    }
    if (Test-Path -LiteralPath (Join-Path $r "napcat.mjs")) { $napCat = $r; break }
}

# ---------- 3. 汇总 ----------
$state = "unknown"
if (-not $napCat -and -not $qqExe) { $state = "both-missing" }
elseif (-not $napCat) { $state = "napcat-missing" }
elseif (-not $qqExe) { $state = "qq-missing" }
elseif ($qqBuild -and $napTargetBuild) {
    if ($qqBuild -eq $napTargetBuild) { $state = "build-equal" }
    else { $state = "build-differs" }
}
else { $state = "need-compare" }

$result = [ordered]@{
    napcat_path         = $napCat
    napcat_target_qq    = $napTargetVer
    napcat_target_build = $napTargetBuild
    qq_path             = $qqExe
    qq_file_version     = $qqFileVer
    qq_app_version      = $qqAppVer
    qq_build            = $qqBuild
    state               = $state
}

if ($Json) {
    $result | ConvertTo-Json -Depth 4
    exit 0
}

Write-Host ""
Write-Host "== 本机 QQ 通道组件体检 =="
Write-Host ""
if ($napCat) {
    Say ("NapCat     : " + $napCat)
    Say ("             按 QQ " + $(if ($napTargetVer) { $napTargetVer } else { "（读不到版本）" }) + " 做的，目标 build " + $(if ($napTargetBuild) { $napTargetBuild } else { "读不到" }))
} else {
    Say "NapCat     : 没找到（常见位置都扫过了）"
}
if ($qqExe) {
    Say ("QQ         : " + $qqExe)
    Say ("             文件版本 " + $(if ($qqFileVer) { $qqFileVer } else { "读不到" }) + "，build " + $(if ($qqBuild) { $qqBuild } else { "读不到" }))
} else {
    Say "QQ         : 没找到。NapCat 要注入的是 QQNT（9.9.x），老版 QQ 不行。"
}

Write-Host ""
switch ($state) {
    "both-missing" {
        Write-Host "  结论：两边都没有。先装 QQNT，再装 NapCat。"
    }
    "napcat-missing" {
        Write-Host "  结论：先装 NapCat。"
        Write-Host "        github.com/NapNeko/NapCatQQ/releases 下 NapCat.Shell.zip，"
        Write-Host "        解压到 %USERPROFILE%\NapCat，再回来跑这个脚本。"
    }
    "qq-missing" {
        Write-Host "  结论：先装 QQNT（9.9.x）。装完再回来跑这个脚本。"
    }
    "build-equal" {
        Write-Host ("  结论：QQ build " + $qqBuild + " 与 NapCat 目标 build 一致，可直接用。")
    }
    "build-differs" {
        Write-Host ("  结论：QQ 是 build " + $qqBuild + "，NapCat 是按 build " + $napTargetBuild + " 做的。")
        Write-Host "        这两个数不一致不等于一定不能用 —— 先实际起一次看二维码出不出来："
        Write-Host "        出得来就继续；出不来再去 NapCat 的 releases 页按你的 QQ build 换版本。"
    }
    default {
        Write-Host "  结论：有一个数读不到，按上面缺的那项补。"
    }
}
Write-Host ""
Write-Host "  说明：脚本只报数，不下结论 —— 兼容范围每版都变，判断要看 release 页原文。"
Write-Host ""
