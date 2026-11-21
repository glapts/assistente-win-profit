@echo off
chcp 65001 >nul
title Assistente Quantitativo B3 - Teste em Lote de Múltiplos Dias (Batch Backtest)
cd /d "%~dp0"

:MENU
cls
echo ======================================================================
echo    ASSISTENTE QUANTITATIVO B3 — TESTE EM LOTE E REPLAY HISTÓRICO
echo ======================================================================
echo.
echo Escolha uma das opções abaixo:
echo.
echo  [1] Executar Teste em Lote nos arquivos da pasta (data\historico)
echo  [2] Iniciar Coletor Inteligente de Clipboard (Copie no Profit Pro)
echo  [3] Gerar 5 Dias Sintéticos Realistas e Executar Teste Imediato
echo  [4] Executar Replay em um Arquivo CSV Específico
echo  [5] Abrir Pasta de Relatórios e Planilhas Geradas
echo  [6] Sair
echo.
echo ======================================================================
set /p OPCAO="Digite a opção desejada (1-6): "

if "%OPCAO%"=="1" goto OPCAO1
if "%OPCAO%"=="2" goto OPCAO2
if "%OPCAO%"=="3" goto OPCAO3
if "%OPCAO%"=="4" goto OPCAO4
if "%OPCAO%"=="5" goto OPCAO5
if "%OPCAO%"=="6" goto FIM
echo Opção inválida! Tente novamente.
timeout /t 2 >nul
goto MENU

:OPCAO1
cls
echo ======================================================================
echo EXECUTANDO TESTE EM LOTE NA PASTA data\historico...
echo ======================================================================
echo.
python main.py batch-replay --dir "data/historico" --mode FIXO --contracts 5
echo.
pause
goto MENU

:OPCAO2
cls
echo ======================================================================
echo COLETOR INTELIGENTE DE CLIPBOARD (PROFIT PRO)
echo ======================================================================
echo.
python main.py batch-replay --collect-clipboard
echo.
pause
goto MENU

:OPCAO3
cls
echo ======================================================================
echo GERANDO 5 DIAS SINTÉTICOS E EXECUTANDO TESTE EM LOTE...
echo ======================================================================
echo.
python main.py batch-replay --generate-samples 5 --contracts 5
echo.
pause
goto MENU

:OPCAO4
cls
echo ======================================================================
echo REPLAY DE ARQUIVO ESPECÍFICO
echo ======================================================================
echo.
set /p ARQUIVO="Digite o caminho completo ou relativo do arquivo CSV: "
if "%ARQUIVO%"=="" (
    echo Nenhum arquivo informado!
    pause
    goto MENU
)
python main.py batch-replay --file %ARQUIVO% --contracts 5
echo.
pause
goto MENU

:OPCAO5
cls
echo Abrindo pasta de relatórios...
if not exist "data\relatorios" mkdir "data\relatorios"
start "" "data\relatorios"
goto MENU

:FIM
exit
