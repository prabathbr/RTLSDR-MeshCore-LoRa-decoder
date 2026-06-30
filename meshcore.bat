@echo off
cd /d "%~dp0"
call activate_meshcore.bat
python src\meshcore_win.py %*
