@echo off
chcp 65001 >nul
title Diagnostico do Sistema - Profit Pro & B3
cd /d "%~dp0"
python main.py diagnose
pause
