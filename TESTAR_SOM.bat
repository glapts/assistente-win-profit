@echo off
chcp 65001 >nul
title Teste dos Alertas Sonoros Binaurais e Sintese de Voz
cd /d "%~dp0"
cls
echo ======================================================================
echo    TESTE DOS ALERTAS SONOROS BINAURAIS E VOZ (COMPRA E VENDA)
echo ======================================================================
echo.
echo 1. Alerta de COMPRA: Frequencia Aguda (1350 Hz) + Voz do Windows
echo 2. Alerta de VENDA : Frequencia Grave (900 Hz)  + Voz do Windows
echo.
echo Prepare o volume dos alto-falantes ou fones de ouvido!
echo.
pause
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0TESTAR_SOM.ps1"
echo.
pause
