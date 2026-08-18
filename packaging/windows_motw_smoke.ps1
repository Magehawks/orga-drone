#Requires -Version 5.1
<#
.SYNOPSIS
  Dev-equivalent Windows release smoke test with Mark-of-the-Web (MOTW).

.DESCRIPTION
  Stamps Zone.Identifier on a candidate zip (unless -SkipMotwStamp), extracts
  with Windows Explorer (Shell.Application) into a parentheses path, launches
  orga-drone.exe, and runs automated launch/API checks.

  For a shipping release, prefer a real browser download from GitHub over
  -SkipMotwStamp. See packaging/README.md "Windows pre-release smoke test".
#>
[CmdletBinding()]
param(
    [string]$ZipPath = "",
    [string]$DistFolder = "",
    [string]$ExtractRoot = 'C:\temp\orga-drone-windows-x64(2)',
    [switch]$SkipMotwStamp,
    [switch]$SkipFunctional,
    [string]$Python = "",
    [string]$BaseUrl = "http://127.0.0.1:8765"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir

if (-not $DistFolder) {
    $DistFolder = Join-Path $RepoRoot "dist\orga-drone"
}
if (-not $ZipPath) {
    $ZipPath = Join-Path $RepoRoot "dist\orga-drone-windows-x64.zip"
}
if (-not $Python) {
    $venvPy = Join-Path $RepoRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) { $Python = $venvPy } else { $Python = "python" }
}

function Test-Motw([string]$Path) {
    return ($null -ne (Get-Item -LiteralPath $Path -Stream Zone.Identifier -ErrorAction SilentlyContinue))
}

function Write-Check([string]$Name, [bool]$Pass, [string]$Detail = "") {
    $status = if ($Pass) { "PASS" } else { "FAIL" }
    $suffix = if ($Detail) { " - $Detail" } else { "" }
    Write-Output "[$status] $Name$suffix"
    return $Pass
}

if (-not (Test-Path $DistFolder)) {
    throw "Build missing: $DistFolder (run pyinstaller first)"
}

if (Test-Path $ZipPath) { Remove-Item $ZipPath -Force }
Compress-Archive -Path $DistFolder -DestinationPath $ZipPath -CompressionLevel Optimal
$sha = (Get-FileHash $ZipPath -Algorithm SHA256).Hash
Write-Output "ZIP=$ZipPath"
Write-Output "SHA256=$sha"

Get-Process orga-drone -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 2
if (Test-Path $ExtractRoot) { Remove-Item $ExtractRoot -Recurse -Force }
New-Item -ItemType Directory -Path $ExtractRoot -Force | Out-Null

if (-not $SkipMotwStamp) {
    $motw = @"
[ZoneTransfer]
ZoneId=3
ReferrerUrl=https://github.com/Magehawks/orga-drone/releases
HostUrl=https://objects.githubusercontent.com/orga-drone-windows-x64.zip

"@
    Set-Content -Path "$ZipPath`:Zone.Identifier" -Value $motw -NoNewline
}
Write-Check "ZIP has MOTW" (Test-Motw $ZipPath) | Out-Null

$shell = New-Object -ComObject Shell.Application
$dst = $shell.NameSpace($ExtractRoot)
$src = $shell.NameSpace($ZipPath)
$dst.CopyHere($src.Items(), 16)

$exe = Join-Path $ExtractRoot "orga-drone\orga-drone.exe"
$deadline = (Get-Date).AddMinutes(8)
while (-not (Test-Path $exe) -and (Get-Date) -lt $deadline) {
    Start-Sleep -Seconds 2
}
$stable = 0
$lastCount = 0
while ((Get-Date) -lt $deadline) {
    $count = (Get-ChildItem (Join-Path $ExtractRoot "orga-drone") -Recurse -File -ErrorAction SilentlyContinue).Count
    if ($count -eq $lastCount) { $stable++ } else { $stable = 0 }
    if ($stable -ge 3) { break }
    $lastCount = $count
    Start-Sleep -Seconds 2
}
$allPass = Write-Check "Explorer extract complete" (Test-Path $exe) "files=$lastCount"

$coreBundled = Join-Path $ExtractRoot "orga-drone\_internal\webview\lib\Microsoft.Web.WebView2.Core.dll"
$allPass = (Write-Check "Bundled Core.dll has MOTW" (Test-Motw $coreBundled)) -and $allPass

$appdata = Join-Path $env:APPDATA "orga-drone"
$crashLog = Join-Path $appdata "startup-crash.log"
$appLog = Join-Path $appdata "orga-drone.log"
$wvHome = Join-Path $appdata "webview-lib"
if (Test-Path $crashLog) { Remove-Item $crashLog -Force -ErrorAction SilentlyContinue }
$logOffset = if (Test-Path $appLog) { (Get-Content $appLog).Count } else { 0 }
if (Test-Path $wvHome) { Remove-Item $wvHome -Recurse -Force -ErrorAction SilentlyContinue }

$browserBefore = (Get-Process msedge, chrome, firefox -ErrorAction SilentlyContinue | Measure-Object).Count
$proc = Start-Process -FilePath $exe -PassThru
$health = $null
$winFormsWindow = $null

$sig = @'
using System; using System.Collections.Generic; using System.Runtime.InteropServices; using System.Text;
public class OrgaDroneSmokeWindow {
  [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowsProc cb, IntPtr l);
  delegate bool EnumWindowsProc(IntPtr h, IntPtr l);
  [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetWindowText(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
  [DllImport("user32.dll")] static extern uint GetWindowThreadProcessId(IntPtr h, out uint pid);
  public static List<string> ForPid(int pid) {
    var res = new List<string>();
    EnumWindows((h,l)=>{ uint p; GetWindowThreadProcessId(h,out p); if(pid!=0&&p!=(uint)pid) return true;
      if(!IsWindowVisible(h)) return true; var sb=new StringBuilder(512); GetWindowText(h,sb,sb.Capacity);
      if(sb.Length==0) return true; var cls=new StringBuilder(256); GetClassName(h,cls,cls.Capacity);
      res.Add(h.ToInt64().ToString()+"|"+cls.ToString()+"|"+sb.ToString()); return true; }, IntPtr.Zero);
    return res;
  }
}
'@
Add-Type -TypeDefinition $sig -ErrorAction SilentlyContinue

$launchDeadline = (Get-Date).AddSeconds(120)
while ((Get-Date) -lt $launchDeadline) {
    if (-not $health) {
        try {
            $resp = Invoke-WebRequest -Uri "$BaseUrl/health" -UseBasicParsing -TimeoutSec 3
            if ($resp.StatusCode -eq 200) { $health = $resp.Content }
        } catch {}
    }
    if (-not $winFormsWindow) {
        $winFormsWindow = [OrgaDroneSmokeWindow]::ForPid($proc.Id) |
            Where-Object { $_ -match "WindowsForms" } |
            Select-Object -First 1
    }
    if ($health -and $winFormsWindow) { break }
    Start-Sleep -Milliseconds 800
}

$browserAfter = (Get-Process msedge, chrome, firefox -ErrorAction SilentlyContinue | Measure-Object).Count
$allPass = (Write-Check "Health endpoint" ($null -ne $health) $health) -and $allPass
$allPass = (Write-Check "Standalone WinForms window" ($null -ne $winFormsWindow) $winFormsWindow) -and $allPass
$allPass = (Write-Check "No startup-crash.log" (-not (Test-Path $crashLog))) -and $allPass
$allPass = (Write-Check "No browser fallback" ($browserAfter -le ($browserBefore + 1)) "before=$browserBefore after=$browserAfter") -and $allPass

$copiedCore = Join-Path $wvHome "Microsoft.Web.WebView2.Core.dll"
$allPass = (Write-Check "webview-lib copy created" (Test-Path $copiedCore)) -and $allPass
if (Test-Path $copiedCore) {
    $allPass = (Write-Check "Copied Core.dll has no MOTW" (-not (Test-Motw $copiedCore))) -and $allPass
}
if (Test-Path $appLog) {
    Write-Output "---- runtime log (new lines) ----"
    Get-Content $appLog | Select-Object -Skip $logOffset |
        Select-String "relocated WebView2|interop_dll_path|desktop shell failed|Traceback" |
        ForEach-Object { $_.Line }
}

foreach ($asset in @(
    "/static/fonts/outfit-latin-400.woff2",
    "/static/icons/orga-drone.ico",
    "/static/icons/orga-drone.png"
)) {
    try {
        $resp = Invoke-WebRequest -Uri "$BaseUrl$asset" -UseBasicParsing -TimeoutSec 5
        $ok = ($resp.StatusCode -eq 200 -and $resp.RawContentLength -gt 100)
        $allPass = (Write-Check "Asset $asset" $ok "$($resp.RawContentLength) bytes") -and $allPass
    } catch {
        $allPass = (Write-Check "Asset $asset" $false $_.Exception.Message) -and $allPass
    }
}

Add-Type -AssemblyName System.Windows.Forms
function Invoke-PickerCancel([string]$Url, [string]$Body) {
    $job = Start-Job -ScriptBlock {
        param($u, $b)
        try {
            if ($b) {
                return Invoke-RestMethod -Uri $u -Method Post -Body $b -ContentType "application/json" -TimeoutSec 60
            }
            return Invoke-RestMethod -Uri $u -Method Post -TimeoutSec 60
        } catch {
            return $_.Exception.Message
        }
    } -ArgumentList $Url, $Body
    Start-Sleep -Seconds 2
    [System.Windows.Forms.SendKeys]::SendWait("{ESC}")
    return Receive-Job $job -Wait -AutoRemoveJob
}

$folderRes = Invoke-PickerCancel "$BaseUrl/api/desktop/pick-folder" $null
$folderOk = ($folderRes.status -in @("cancelled", "ok")) -or ("$folderRes" -match "cancelled")
$allPass = (Write-Check "Folder picker opens/cancels" $folderOk "$folderRes") -and $allPass

$saveRes = Invoke-PickerCancel "$BaseUrl/api/desktop/pick-save-file" '{"filename":"motw-smoke.mp4"}'
$saveOk = ($saveRes.status -in @("cancelled", "ok")) -or ("$saveRes" -match "cancelled")
$allPass = (Write-Check "Save-as picker opens/cancels" $saveOk "$saveRes") -and $allPass

$openRes = Invoke-PickerCancel "$BaseUrl/api/desktop/pick-open-file" '{"directory":""}'
$openOk = ($openRes.status -in @("cancelled", "ok")) -or ("$openRes" -match "cancelled")
$allPass = (Write-Check "Open-file picker opens/cancels" $openOk "$openRes") -and $allPass
$allPass = (Write-Check "App alive after picker tests" (-not $proc.HasExited) "pid=$($proc.Id)") -and $allPass

if (-not $SkipFunctional) {
    $functional = Join-Path $ScriptDir "motw_smoke_functional.py"
    $extractDir = Join-Path $ExtractRoot "orga-drone"
    & $Python $functional --base-url $BaseUrl --extract-root $extractDir
    $exportOk = ($LASTEXITCODE -eq 0)
    if ($LASTEXITCODE -eq 2) {
        Write-Output "[SKIP] 1080p export (no library media or ffmpeg)"
    } else {
        $allPass = (Write-Check "1080p export" $exportOk "exit=$LASTEXITCODE") -and $allPass
    }

    Get-Process orga-drone -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Seconds 3
    $proc2 = Start-Process -FilePath $exe -PassThru
    $health2 = $null
    $restartDeadline = (Get-Date).AddSeconds(90)
    while ((Get-Date) -lt $restartDeadline) {
        try {
            $resp = Invoke-WebRequest -Uri "$BaseUrl/health" -UseBasicParsing -TimeoutSec 3
            if ($resp.StatusCode -eq 200) { $health2 = $resp.Content; break }
        } catch {}
        Start-Sleep -Milliseconds 800
    }
    $allPass = (Write-Check "Restart health" ($null -ne $health2) $health2) -and $allPass

    & $Python $functional --base-url $BaseUrl --restart-only
    if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 2) {
        $allPass = (Write-Check "Restart persistence" $false "exit=$LASTEXITCODE") -and $allPass
    } elseif ($LASTEXITCODE -eq 0) {
        $allPass = (Write-Check "Restart persistence" $true) -and $allPass
    }
}

Get-Process orga-drone -ErrorAction SilentlyContinue | Stop-Process -Force
Write-Output "EXE=$exe"
Write-Output "SHA256=$sha"
if ($allPass) {
    Write-Output "VERDICT=WINDOWS_RELEASE_READY"
    exit 0
}
Write-Output "VERDICT=WINDOWS_RELEASE_BLOCKED"
exit 1
