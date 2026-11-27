@echo off
chcp 65001 >nul
title INICIAR TODOS OS TERMINAIS - ASSISTENTE WIN
cd /d "%~dp0"

echo ===============================================================================
echo     INICIALIZANDO OS 5 TERMINAIS OPERACIONAIS (WIN B3)
echo ===============================================================================
echo.
echo 1. Orquestrador Multi-Agente...
start "1. ORQUESTRADOR MULTI-AGENTE" cmd /k "EXECUTAR_ORQUESTRADOR_AGENTES.bat"
timeout /t 2 /nobreak > nul

echo 2. Execution Harness Copiloto...
start "2. HARNESS COPILOTO" cmd /k "EXECUTAR_HARNESS_COPILOTO.bat"
timeout /t 2 /nobreak > nul

echo 3. Whale Flow US Monitor...
start "3. WHALE FLOW MONITOR" cmd /k "INICIAR_WHALE_NY_MONITOR.bat"
timeout /t 2 /nobreak > nul

echo 4. Servico Tecla F8...
start "4. TECLA F8 PROFIT" cmd /k "ATIVAR_TECLA_F8.bat"
timeout /t 2 /nobreak > nul

echo 5. Scalper Glaucio SMC 1M...
start "5. SCALPER GLAUCIO" cmd /k "INICIAR_SCALPER_GLAUCIO.bat"

echo.
echo ===============================================================================
echo     TODOS OS 5 TERMINAIS FORAM INICIADOS COM SUCESSO!
echo ===============================================================================
pause
