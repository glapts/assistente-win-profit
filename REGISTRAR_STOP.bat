@echo off
chcp 65001 > nul
title REGISTRAR STOP - CIRCUIT BREAKER
cd /d "%~dp0"
python record_stop.py
pause
