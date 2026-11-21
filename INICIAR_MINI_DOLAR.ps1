# Assistente Quantitativo B3 - Mini-Dólar (WDO)
$host.UI.RawUI.WindowTitle = "Assistente Quantitativo B3 - Mini-Dólar (WDO)"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location -Path $PSScriptRoot
python main.py run-dde --symbol WDO
