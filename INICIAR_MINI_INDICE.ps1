# Assistente Quantitativo B3 - Mini-Índice (WIN)
$host.UI.RawUI.WindowTitle = "Assistente Quantitativo B3 - Mini-Índice (WIN)"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location -Path $PSScriptRoot
python main.py run-dde --symbol WIN
