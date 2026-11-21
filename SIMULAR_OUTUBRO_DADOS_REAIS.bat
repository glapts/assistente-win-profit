@echo off
chcp 65001 >nul
title Simulação Outubro/2026 - Dados Reais B3 com 5 Contratos
cd /d "%~dp0"
cls
echo ======================================================================
echo    SIMULAÇÃO DIA A DIA — OUTUBRO DE 2026 (COTAÇÕES 100%% REAIS B3)
echo    Configuração: 5 Minicontratos WIN | Stop: 250 pts | Alvo: 400 pts
echo ======================================================================
echo.
python simular_outubro_real_5ct.py
echo.
pause