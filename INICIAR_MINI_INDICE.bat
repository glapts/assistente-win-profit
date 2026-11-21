@echo off
chcp 65001 >nul
title Assistente Quantitativo B3 - Mini-Indice (WIN)
cd /d "%~dp0"
python main.py run-dde --symbol WIN
pause
