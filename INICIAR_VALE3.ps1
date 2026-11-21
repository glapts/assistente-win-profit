# Assistente Quantitativo B3 - Vale S.A. (VALE3)
$host.UI.RawUI.WindowTitle = "Assistente Quantitativo B3 - Vale S.A. (VALE3)"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location -Path $PSScriptRoot
python main.py run-dde --symbol VALE3
