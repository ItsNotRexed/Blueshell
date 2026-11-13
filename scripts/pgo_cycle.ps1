# (blueshell) The whole optimized build, unattended and gentle: lift with the hot list, split, an instrumented build, a training
# race (windowed, muted, BelowNormal), the profile merged, the PGO build, and a measured run. Builds run at Idle on 2 jobs.
#   powershell -File scripts/pgo_cycle.ps1 [-SkipLift] [-Tag name]
param([switch]$SkipLift, [string]$Tag = "cycle")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$mingw = "C:\Users\NotRexed\Tools\llvm-mingw-20261104-ucrt-x86_64"
$env:HOOKSHOT_MINGW = $mingw
$env:A64_HOT_FUNCS = (Resolve-Path work\hot_funcs.txt).Path
$env:A64_HOT_CHUNK = "1"
$env:RX_RELEASE = "1"
$log = Join-Path $root "work\$Tag.log"
function Say($m) { "$(Get-Date -Format HH:mm:ss) $m" | Tee-Object -FilePath $log -Append }
function Step($what, $argv) {
    Say "start: $what"
    $p = Start-Process python -ArgumentList $argv -NoNewWindow -PassThru -RedirectStandardOutput "work\$Tag-$what.out" -RedirectStandardError "work\$Tag-$what.err"
    $null = $p.Handle   # (keep the handle: without it ExitCode reads empty once the process is gone)
    $p.PriorityClass = 'Idle'
    $p.WaitForExit()
    if ($p.ExitCode -ne 0) { Say "FAILED: $what ($($p.ExitCode))"; exit 1 }
    Say "done: $what"
}
function Race($name, $envs) {
    Say "run: $name"
    powershell -NoProfile -File scripts/run-vk.ps1 -Window -Seconds 180 -Name $name -ShotEvery 600 -MaxGB 10 -Priority BelowNormal -Env "$envs;" | Tee-Object -FilePath $log -Append
}
"" | Set-Content $log -Encoding utf8
if (-not $SkipLift) { Step "lift" @('-I', '-u', 'nx2/lift.py', '--standalone', '--write') }
Step "split" @('-I', '-u', 'nx2/split_hot.py', 'work\sa\gen')
$env:RX_PGO = "gen"
Step "build-gen" @('-I', '-u', 'nx2/build.py', '--standalone', '--jobs', '2')
$run = Join-Path $root "work\runs\$Tag-train"
New-Item -ItemType Directory -Force $run | Out-Null
$raw = Join-Path $run "mkw.profraw"
$job = Start-Job -ScriptBlock { param($r) Start-Sleep 50; New-Item "$r.reset" -ItemType File | Out-Null; Start-Sleep 120; New-Item "$r.dump" -ItemType File | Out-Null } -ArgumentList $raw
Race "$Tag-train" "HOS_PGO=$raw"
Wait-Job $job | Out-Null
if (-not (Test-Path $raw)) { Say "FAILED: no profile written"; exit 1 }
& "$mingw\bin\llvm-profdata.exe" merge -o work\hookshot_pieces.prof $raw
Say "profile merged"
$env:RX_PGO = (Resolve-Path work\hookshot_pieces.prof).Path
Step "build-pgo" @('-I', '-u', 'nx2/build.py', '--standalone', '--jobs', '2')
Race "$Tag-measure" ""
Say "all done"
