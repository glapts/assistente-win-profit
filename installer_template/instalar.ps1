# =====================================================================
# INSTALADOR AUTOMATIZADO PARA WINDOWS 11 — ASSISTENTE WIN PROFIT PRO
# Cenário 3 Oficial: SMC & Tape Reading Flow (Stop 250 / Alvo 400 pts)
# =====================================================================

$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "       INSTALADOR OFICIAL — ASSISTENTE WIN PROFIT PRO (B3)            " -ForegroundColor Yellow
Write-Host "          Arquitetura Institucional SMC & Tape Reading Flow           " -ForegroundColor Yellow
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

$SourceDir = $PSScriptRoot
$InstallDir = Join-Path $env:LOCALAPPDATA "AssistenteWIN"
$DesktopDir = [System.Environment]::GetFolderPath([System.Environment+SpecialFolder]::DesktopDirectory)
$ExeName = "AssistenteWIN.exe"
$SourceExe = Join-Path $SourceDir $ExeName

if (-not (Test-Path $SourceExe)) {
    Write-Host "[ERRO CRÍTICO] O executável '$ExeName' não foi encontrado na pasta do instalador!" -ForegroundColor Red
    Write-Host "Certifique-se de extrair todos os arquivos do instalador antes de executar." -ForegroundColor Red
    Exit 1
}

Write-Host "1. Criando diretório de instalação..." -ForegroundColor Gray
if (-not (Test-Path $InstallDir)) {
    New-Item -Path $InstallDir -ItemType Directory -Force | Out-Null
}
Write-Host "   [OK] Destino: $InstallDir" -ForegroundColor Green

Write-Host "2. Copiando arquivos do sistema e manuais..." -ForegroundColor Gray
Copy-Item -Path $SourceExe -Destination (Join-Path $InstallDir $ExeName) -Force

# Copia manual rápido se existir
$ManualFile = Join-Path $SourceDir "LEIA-ME_PRIMEIROS_PASSOS.txt"
if (Test-Path $ManualFile) {
    Copy-Item -Path $ManualFile -Destination (Join-Path $InstallDir "LEIA-ME_PRIMEIROS_PASSOS.txt") -Force
}

# Copia Guia Completo em PDF se existir
$PdfFile = Join-Path $SourceDir "Guia_Instalacao_Profit_RTD_DDE_ultimo.pdf"
if (Test-Path $PdfFile) {
    Copy-Item -Path $PdfFile -Destination (Join-Path $InstallDir "Guia_Instalacao_Profit_RTD_DDE_ultimo.pdf") -Force
}

Write-Host "3. Criando atalhos na Área de Trabalho (Desktop)..." -ForegroundColor Gray
$WshShell = New-Object -ComObject WScript.Shell

$ShortcutPath = Join-Path $DesktopDir "Assistente WIN - Profit Pro.lnk"
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = Join-Path $InstallDir $ExeName
$Shortcut.WorkingDirectory = $InstallDir
$Shortcut.Description = "Assistente de Trading Institucional Mini-Índice B3 (WIN) - Cenário 3 Oficial"
$Shortcut.Save()
Write-Host "   [OK] Atalho do Assistente WIN criado na Área de Trabalho com sucesso!" -ForegroundColor Green

if (Test-Path $PdfFile) {
    $PdfShortcutPath = Join-Path $DesktopDir "Manual do Trader - Assistente WIN.lnk"
    $PdfShortcut = $WshShell.CreateShortcut($PdfShortcutPath)
    $PdfShortcut.TargetPath = Join-Path $InstallDir "Guia_Instalacao_Profit_RTD_DDE_ultimo.pdf"
    $PdfShortcut.WorkingDirectory = $InstallDir
    $PdfShortcut.Description = "Manual Completo e Auditoria Estatística do Assistente WIN"
    $PdfShortcut.Save()
    Write-Host "   [OK] Atalho do Manual do Trader em PDF criado na Área de Trabalho!" -ForegroundColor Green
}

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "                 INSTALAÇÃO CONCLUÍDA COM SUCESSO!                    " -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Os ícones de acesso rápido foram adicionados à sua Área de Trabalho." -ForegroundColor White
Write-Host ""

$resposta = Read-Host "Deseja iniciar o Assistente WIN agora para ativar sua licença? (S/N)"
if ($resposta -match "^[sSyY]") {
    Write-Host "Iniciando Assistente WIN..." -ForegroundColor Green
    Start-Process -FilePath (Join-Path $InstallDir $ExeName)
}
