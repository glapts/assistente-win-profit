@echo off
chcp 65001 > nul
title ATALHO GLOBAL TECLA F8 - PROFIT PRO
cd /d "%~dp0"
python f8_hotkey_service.py
pause
