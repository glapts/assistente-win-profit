@echo off
chcp 65001 >nul
title Whale Flow US & NY Cash Open Monitor (WIN B3)
cd /d "C:\Users\glaci\assistente-win-profit"

echo ===============================================================================
echo     INICIANDO MONITOR INSTITUCIONAL US (>= 400 CTS) & ABERTURA NY (11:30 BRT)
echo ===============================================================================
echo.
echo Modulo quantitativo desacoplado ativo.
echo Para alimentar o monitor via Clipboard: selecione ordens no Times & Trades e tecle Ctrl+C.
echo.
python whale_ny_monitor.py --mode LIVE_CLIPBOARD

pause
