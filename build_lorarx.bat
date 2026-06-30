@echo off
setlocal enabledelayedexpansion

rem Build lorarx.exe for Windows (MSVC cl.exe)
rem Run from "x64 Native Tools Command Prompt for VS" or after vcvars64.bat

set SRCDIR=%~dp0src\lorarx-src
set OUTDIR=%~dp0bin
if not exist "%OUTDIR%" mkdir "%OUTDIR%"

set CFLAGS=/nologo /O2 /W3 /DWIN32 /D_WIN32 /D_CRT_SECURE_NO_WARNINGS /I"%SRCDIR%"
set LDFLAGS=ws2_32.lib

set OBJ=%OUTDIR%\lorarx_build
if not exist "%OBJ%" mkdir "%OBJ%"

set SOURCES=port_win.c osic.c osi.c aprspos.c aprsstr.c tcp.c udp.c soundctl.c Select.c loraprotocols.c lorarx.c

pushd "%SRCDIR%"
for %%F in (%SOURCES%) do (
  echo [compile] %%F
  cl %CFLAGS% /c %%F /Fo%OBJ%\
  if errorlevel 1 goto :fail
)

echo [link] lorarx.exe
link /nologo /OUT:"%OUTDIR%\lorarx.exe" %OBJ%\*.obj %LDFLAGS%
if errorlevel 1 goto :fail

echo.
echo Built: %OUTDIR%\lorarx.exe
"%OUTDIR%\lorarx.exe" -h
popd
exit /b 0

:fail
echo Build failed.
popd
exit /b 1
