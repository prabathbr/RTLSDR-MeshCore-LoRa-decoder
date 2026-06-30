@echo off
set ROOT=%~dp0
cd /d "%ROOT%"

if not defined MESHCORE_CONDA set MESHCORE_CONDA=K:\Miniconda3
call "%MESHCORE_CONDA%\Scripts\activate.bat" meshcore-decode

set PATH=%ROOT%bin;%PATH%
echo meshcore-decode env active
echo   meshcore.bat --gain 40 --ppm -15 -v
echo   python src\meshcore_win.py --gain 40 --ppm -15 -v
