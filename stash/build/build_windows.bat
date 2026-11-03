@echo off
rem ---------------------------------------------------------------------------
rem  Stash - Windows build script
rem  Produces:  build\dist\Stash.exe               (standalone app)
rem             build\Output\Stash-Setup-1.0.0.exe (installer, needs Inno Setup 6)
rem  Usage:     build\build_windows.bat            (from anywhere)
rem ---------------------------------------------------------------------------
setlocal EnableExtensions EnableDelayedExpansion

set "APP_VERSION=1.0.0"
rem Project root = parent of this script's folder
pushd "%~dp0.." || goto :fail
set "ROOT=%CD%"
set "VENV=%ROOT%\.venv"

echo.
echo  ==^> Stash %APP_VERSION% build
echo      Project: %ROOT%
echo.

rem --- 1. Python ------------------------------------------------------------
set "PY="
where py >nul 2>&1 && py -3.11 -c "import sys" >nul 2>&1 && set "PY=py -3.11"
if not defined PY (
    where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
    echo [ERROR] Python 3.11 not found. Install it from https://www.python.org/downloads/
    goto :fail
)

rem --- a. Virtual environment ------------------------------------------------
if not exist "%VENV%\Scripts\python.exe" (
    echo  ==^> Creating virtual environment in .venv
    %PY% -m venv "%VENV%" || goto :fail
)
set "VPY=%VENV%\Scripts\python.exe"

rem --- b. Dependencies -------------------------------------------------------
echo  ==^> Installing dependencies
"%VPY%" -m pip install --upgrade pip --disable-pip-version-check -q || goto :fail
"%VPY%" -m pip install -r requirements.txt pyinstaller -q || goto :fail

rem --- Branding assets (icon + installer images) -----------------------------
if not exist "build\stash.ico" (
    echo  ==^> Generating icon and installer artwork
    "%VPY%" build\make_icon.py || goto :fail
)

rem --- c. PyInstaller --------------------------------------------------------
echo  ==^> Building Stash.exe with PyInstaller
"%VPY%" -m PyInstaller build\stash.spec --distpath build\dist --workpath build\work --noconfirm --clean || goto :fail
if not exist "build\dist\Stash.exe" (
    echo [ERROR] build\dist\Stash.exe was not produced.
    goto :fail
)

rem --- d. Inno Setup ---------------------------------------------------------
set "ISCC="
where iscc >nul 2>&1 && set "ISCC=iscc"
if not defined ISCC if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if not defined ISCC if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"

if not defined ISCC (
    echo.
    echo [WARN] Inno Setup 6 not found - skipping the installer.
    echo        Install it from https://jrsoftware.org/isdl.php and re-run this script.
    echo.
    echo  Standalone EXE: %ROOT%\build\dist\Stash.exe
    popd
    exit /b 0
)

echo  ==^> Compiling installer with Inno Setup
"%ISCC%" /Q /DAppVersion=%APP_VERSION% build\setup.iss || goto :fail

rem --- e. Result -------------------------------------------------------------
echo.
echo  ==========================================================================
echo   Build complete
echo   Standalone EXE : %ROOT%\build\dist\Stash.exe
echo   Installer      : %ROOT%\build\Output\Stash-Setup-%APP_VERSION%.exe
echo  ==========================================================================
popd
exit /b 0

:fail
echo.
echo [ERROR] Build failed (see messages above).
popd 2>nul
exit /b 1
