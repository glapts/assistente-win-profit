@echo off
chcp 65001 >nul
title Instalador - Assistente WIN Mini-Índice B3
echo ======================================================================
echo    INSTALADOR OFICIAL — ASSISTENTE DE TRADING INSTITUCIONAL WIN
echo ======================================================================
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"
if %errorlevel% neq 0 (
    echo.
    echo [ERRO] Ocorreu uma falha durante a instalação.
)
pause
