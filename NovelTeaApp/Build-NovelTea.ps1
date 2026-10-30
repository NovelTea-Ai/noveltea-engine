# NovelTea Engine rebuild: renderer -> backend\webui -> NovelTeaEngine.exe -> relaunch.
#
# Runs on its own: double-click Build-NovelTea.bat, or the Build button on the Workspace
# Assistant page starts it as a detached process, so it keeps going after it stops the app
# (the exe can't be rebuilt while it's running) and starts the app again at the end.
#
# Order matters (see build-all.bat): the renderer is copied into backend\webui BEFORE PyInstaller,
# or the exe bakes in the old UI. The renderer is built while the app is still up, so a frontend
# error leaves the running app untouched. If PyInstaller fails, the previous exe is restored and
# relaunched, so a failed build never leaves you without the app.
#
# Progress goes to backend\build_status.json (read by the Build button) and backend\build_button.log.

param([switch]$NoLaunch)

$ErrorActionPreference = 'Stop'
$App      = Split-Path -Parent $MyInvocation.MyCommand.Path
$Renderer = Join-Path $App 'renderer'
$Backend  = Join-Path $App 'backend'
$Webui    = Join-Path $Backend 'webui'
$Exe      = Join-Path $Backend 'dist\NovelTeaEngine.exe'
$Prev     = "$Exe.prev"
$StatusF  = Join-Path $Backend 'build_status.json'
$Log      = Join-Path $Backend 'build_button.log'
$Work     = Join-Path $env:TEMP 'noveltea-pyi-work'
$Started  = (Get-Date).ToString('s')

function Set-Status([string]$state, [string]$step) {
    $o = [ordered]@{ state = $state; step = $step; started = $Started; updated = (Get-Date).ToString('s'); pid = $PID }
    [IO.File]::WriteAllText($StatusF, ($o | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
}
function Say([string]$msg) {
    $line = "[{0}] {1}" -f (Get-Date).ToString('HH:mm:ss'), $msg
    Write-Host $line
    Add-Content -Path $Log -Value $line -Encoding UTF8
}
function Run([string]$dir, [string]$cmd) {
    # cmd /c so native stderr goes to the log instead of becoming PowerShell errors
    cmd /c "cd /d `"$dir`" && $cmd >> `"$Log`" 2>&1"
    return $LASTEXITCODE
}
function Launch-App {
    if ($NoLaunch) { return $true }
    if (-not (Test-Path $Exe)) { Say 'No NovelTeaEngine.exe to launch.'; return $false }
    # a fresh PyInstaller instance, not one that thinks it's a child of the old exe
    Get-ChildItem env: | Where-Object { $_.Name -like '_PYI*' -or $_.Name -like '_MEI*' } |
        ForEach-Object { Remove-Item "env:$($_.Name)" }
    $env:PYINSTALLER_RESET_ENVIRONMENT = '1'
    Say 'Launching NovelTea Engine...'
    Start-Process -FilePath $Exe -WorkingDirectory (Split-Path $Exe)
    for ($i = 0; $i -lt 90; $i++) {
        Start-Sleep -Seconds 1
        # 127.0.0.1, not localhost: PowerShell 5.1's localhost lookup here times out every time
        try { Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:7432/api/health' | Out-Null; Say 'App is back up.'; return $true } catch {}
    }
    Say 'App did not answer /api/health within 90s.'
    return $false
}

Set-Content -Path $Log -Value "NovelTea Engine build started $Started" -Encoding UTF8
try {
    Set-Status 'running' 'Building the frontend (npm run build)'
    Say 'Building the frontend...'
    if ((Run $Renderer 'npm run build') -ne 0) { throw 'Frontend build failed (npm run build). The app was left running.' }

    Set-Status 'running' 'Copying the frontend into backend\webui'
    Say 'Copying renderer\dist to backend\webui...'
    robocopy (Join-Path $Renderer 'dist') $Webui /MIR /NJH /NJS /NP /NFL /NDL | Out-Null
    if ($LASTEXITCODE -ge 8) { throw "robocopy failed (exit $LASTEXITCODE). The app was left running." }
    $bundles = @(Get-ChildItem (Join-Path $Webui 'assets') -Filter 'index-*.js')
    if ($bundles.Count -ne 1) { throw "Expected one index-*.js in backend\webui, found $($bundles.Count). The app was left running." }
    Say "Frontend bundle: $($bundles[0].Name)"

    Set-Status 'running' 'Stopping the app'
    Say 'Stopping NovelTea Engine...'
    Get-Process -Name 'NovelTea Engine' -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    for ($i = 0; $i -lt 30 -and (Get-Process -Name 'NovelTea Engine' -ErrorAction SilentlyContinue); $i++) { Start-Sleep -Milliseconds 500 }
    Start-Sleep -Seconds 1

    if (Test-Path $Exe) { Copy-Item $Exe $Prev -Force }
    Set-Status 'running' 'Building the backend (PyInstaller, a few minutes)'
    Say 'Building the backend exe (PyInstaller)...'
    # the Python that has PyInstaller (PATH's "python" can be a different install without it)
    $py = $null
    foreach ($c in @('py -3.12', 'python', 'py')) {
        cmd /c "$c -c `"import PyInstaller`" >nul 2>&1"
        if ($LASTEXITCODE -eq 0) { $py = $c; break }
    }
    if (-not $py) { throw 'No Python with PyInstaller found (tried py -3.12, python, py).' }
    Say "Using $py"
    $rc = Run $Backend "$py -m PyInstaller NovelTeaEngine.spec --noconfirm --clean --workpath `"$Work`""
    if ($rc -ne 0 -or -not (Test-Path $Exe)) {
        if (Test-Path $Prev) { Copy-Item $Prev $Exe -Force; Say 'Restored the previous exe.' }
        throw "Backend build failed (PyInstaller exit $rc). The previous version was restored."
    }

    Set-Status 'running' 'Starting the app'
    if (-not (Launch-App)) { throw 'Built, but the relaunched app did not answer within 90s - start NovelTeaEngine.exe by hand.' }
    Set-Status 'ok' "Built $($bundles[0].Name) and relaunched"
    Say 'BUILD COMPLETE'
}
catch {
    Say "BUILD FAILED: $($_.Exception.Message)"
    Set-Status 'failed' $_.Exception.Message
    if (-not (Get-Process -Name 'NovelTea Engine' -ErrorAction SilentlyContinue)) { Launch-App | Out-Null }
    exit 1
}
