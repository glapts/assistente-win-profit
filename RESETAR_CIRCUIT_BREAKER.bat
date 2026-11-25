@echo off
chcp 65001 > nul
title RESETAR CIRCUIT BREAKER
cd /d "%~dp0"
python record_stop.py --reset
pause
