@echo off
chcp 65001 >nul
title Teste de Alerta Sonoro e Visual - Execucao 1 Clique SuperDOM
cd /d "%~dp0"
cls
echo ======================================================================
echo    TESTE DO SISTEMA DE ALERTA SONORO + VOZ + VISUAL SUPERDOM
echo ======================================================================
echo.
echo Este teste vai:
echo 1. Tocar os 5 apitos sonoros de alerta de entrada
echo 2. Anunciar a ordem por voz no Windows (ex: "Compra! Preco 171.405")
echo 3. Exibir na tela o patamar exato de preco e a coluna para 1 clique
echo.
echo Prepare o som do seu computador e abra o SuperDOM no Profit Pro!
echo.
pause
cls
python main.py demo-alert
echo.
echo ======================================================================
echo Teste concluido!
echo ======================================================================
pause
