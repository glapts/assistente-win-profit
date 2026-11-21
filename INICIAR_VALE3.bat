@echo off
chcp 65001 >nul
title Assistente Quantitativo B3 - Vale S.A. (VALE3)
cd /d "%~dp0"
python main.py run-dde --symbol VALE3
pause
