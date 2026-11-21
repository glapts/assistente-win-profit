# EXECUTAR_REPLAY_LOTE.ps1
# Menu interativo em PowerShell para Teste em Lote e Replay de Mercado
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Set-Location $PSScriptRoot

Clear-Host
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "   ASSISTENTE QUANTITATIVO B3 — TESTE EM LOTE E REPLAY HISTÓRICO" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Escolha uma das opções abaixo:" -ForegroundColor White
Write-Host " [1] Executar Teste em Lote nos arquivos da pasta (data\historico)" -ForegroundColor Green
Write-Host " [2] Iniciar Coletor Inteligente de Clipboard (Copie no Profit Pro)" -ForegroundColor Yellow
Write-Host " [3] Gerar 5 Dias Sintéticos Realistas e Executar Teste Imediato" -ForegroundColor Magenta
Write-Host " [4] Executar Replay em um Arquivo CSV Específico" -ForegroundColor Blue
Write-Host " [5] Abrir Pasta de Relatórios e Planilhas Geradas" -ForegroundColor Gray
Write-Host " [6] Sair" -ForegroundColor Red
Write-Host ""
$opt = Read-Host "Digite a opção desejada (1-6)"

switch ($opt) {
    "1" { python main.py batch-replay --dir "data/historico" --contracts 5 }
    "2" { python main.py batch-replay --collect-clipboard }
    "3" { python main.py batch-replay --generate-samples 5 --contracts 5 }
    "4" { 
        $f = Read-Host "Digite o caminho do arquivo CSV"
        if ($f) { python main.py batch-replay --file $f --contracts 5 }
    }
    "5" { 
        if (-not (Test-Path "data\relatorios")) { New-Item -ItemType Directory "data\relatorios" | Out-Null }
        explorer.exe "data\relatorios" 
    }
    Default { Write-Host "Finalizado." }
}
