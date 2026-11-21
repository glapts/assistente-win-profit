# Diagnóstico do Sistema - Profit Pro & B3
$host.UI.RawUI.WindowTitle = "Diagnóstico do Sistema - Profit Pro & B3"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location -Path $PSScriptRoot
python main.py diagnose
