@echo off
REM ===========================================================================
REM  NovelTea Engine - full build: renderer -> backend webui -> server exe, then the desktop client
REM
REM  Outputs:
REM    backend\dist\NovelTeaEngine.exe        the SERVER (PyInstaller): serves the UI and the API
REM    dist\win-unpacked\NovelTeaEngine.exe      the desktop CLIENT (Electron): connects to a running server, contains no server
REM
REM  Why each step matters (learned the hard way):
REM    * webui is baked INTO the server exe at build time, so the renderer must be
REM      rebuilt and copied BEFORE the exe is packaged. (The desktop client loads the
REM      UI from the server it connects to, so it needs no copy of it.)
REM    * backend\webui is DELETED before copying. Copying over the top leaves
REM      old hashed index-*.js bundles behind - nine had piled up, bloating the
REM      exe and making "is my change in there?" impossible to answer.
REM    * PyInstaller is run with --clean. Without it, it reuses a cached bundle
REM      and silently ships the PREVIOUS ui even though the build "succeeds".
REM    * running exes are killed first, or the packagers fail on locked files.
REM ===========================================================================

setlocal
cd /d "%~dp0"

echo.
echo ============================================================
echo  NovelTea Engine full build
echo ============================================================

REM --- 0. stop anything holding the output files -------------------------
echo.
echo [0/5] Stopping running instances...
taskkill /F /IM NovelTeaEngine.exe /T >nul 2>&1
taskkill /F /IM NovelTeaEngine.exe /T    >nul 2>&1
timeout /t 2 /nobreak >nul

REM --- 1. renderer -------------------------------------------------------
echo.
echo [1/5] Building React renderer...
pushd renderer
call npm run build
if errorlevel 1 (
    popd
    goto :failed
)
popd
if not exist "renderer\dist\index.html" (
    echo    ERROR: renderer\dist\index.html missing after build.
    goto :failed
)

REM --- 2. publish renderer into the backend ------------------------------
echo.
echo [2/5] Publishing renderer to backend\webui...
if exist "backend\webui" rmdir /S /Q "backend\webui"
xcopy "renderer\dist" "backend\webui" /E /I /Q /Y >nul
if errorlevel 1 goto :failed
for /f %%C in ('dir /b "backend\webui\assets\index-*.js" 2^>nul ^| find /c /v ""') do set BUNDLES=%%C
echo    bundles in webui: %BUNDLES%  (must be 1)
if not "%BUNDLES%"=="1" (
    echo    ERROR: expected exactly one index-*.js bundle.
    goto :failed
)

REM --- 3. backend exe ----------------------------------------------------
echo.
echo [3/5] Building backend exe (PyInstaller)...
pushd backend
if exist "build" rmdir /S /Q "build"
if exist "dist\NovelTeaEngine.exe" del /Q "dist\NovelTeaEngine.exe"
python -m PyInstaller NovelTeaEngine.spec --noconfirm --clean --distpath dist
if errorlevel 1 (
    popd
    goto :failed
)
popd
if not exist "backend\dist\NovelTeaEngine.exe" (
    echo    ERROR: NovelTeaEngine.exe was not produced.
    goto :failed
)

REM --- 4. electron exe ---------------------------------------------------
echo.
echo [4/5] Building the desktop client (electron-builder)...
set CSC_IDENTITY_AUTO_DISCOVERY=false
call npx electron-builder --win --dir
if errorlevel 1 goto :failed
if not exist "dist\win-unpacked\NovelTeaEngine.exe" (
    echo    ERROR: NovelTeaEngine.exe was not produced.
    goto :failed
)

REM --- 5. verify ---------------------------------------------------------
echo.
echo [5/5] Verifying outputs...
if exist "dist\win-unpacked\resources\app.asar.unpacked\backend\main.py" (
    echo    ERROR: the desktop client must not contain the server.
    goto :failed
)
echo    client contains no server OK

echo.
echo ============================================================
echo  BUILD COMPLETE
echo ============================================================
for %%F in ("backend\dist\NovelTeaEngine.exe") do echo   server: %%~tF  %%~zF bytes  %%~fF
for %%F in ("dist\win-unpacked\NovelTeaEngine.exe") do echo   client: %%~tF  %%~zF bytes  %%~fF
echo.
echo  NOTE: launch NovelTeaEngine.exe from Explorer, not from a shell that has
echo        ELECTRON_RUN_AS_NODE set - that variable makes Electron run as
echo        plain Node and the app exits instantly with no window.
echo.
endlocal
exit /b 0

:failed
echo.
echo ============================================================
echo  BUILD FAILED - see the error above. Nothing was published.
echo ============================================================
endlocal
exit /b 1
