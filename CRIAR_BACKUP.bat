@echo off
chcp 65001 >nul
title Backup do Assistente B3 e Sincronizacao Google Drive
cd /d "%~dp0"
python gerar_backup.py
pause
