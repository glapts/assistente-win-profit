# EXECUTAR_HARNESS_COPILOTO.ps1
# Script PowerShell para iniciar o Execution Harness no Modo Copiloto
$Host.UI.RawUI.WindowTitle = "Assistente WIN - Execution Harness (Modo Copiloto)"
Set-Location -Path $PSScriptRoot

Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host "    INICIANDO EXECUTION HARNESS — MODO COPILOTO / ASSISTIDO (WIN B3)" -ForegroundColor Green
Write-Host "===============================================================================" -ForegroundColor Cyan
Write-Host ""

python run_harness_copilot.py --mode COPILOT
