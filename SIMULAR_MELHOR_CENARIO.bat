@echo off
chcp 65001 > nul
title SIMULADOR MESTRE B3 - MELHOR CENARIO COMPRA E VENDA
cd /d "%~dp0"

echo ======================================================================
echo    SIMULADOR MESTRE B3: MELHOR CENARIO DE COMPRA E VENDA
echo ======================================================================
echo.
echo Escolha o cenario para simular:
echo   [1] Melhor Cenario de COMPRA (Absorcao no Fundo + Escada Institucional)
echo   [2] Melhor Cenario de VENDA (Absorcao no Topo + Contra-Ataque Vendedor)
echo   [3] Rodar Ambos em Sequencia
echo.
set /p opcao="Digite a opcao desejada (1, 2 ou 3): "

if "%opcao%"=="1" (
    python simular_melhor_cenario.py compra
) else if "%opcao%"=="2" (
    python simular_melhor_cenario.py venda
) else (
    python simular_melhor_cenario.py
)

echo.
pause
