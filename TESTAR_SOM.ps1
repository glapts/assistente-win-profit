# Teste de Alertas Sonoros Binaurais e Síntese de Voz (SAPI)
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "       DISPARO DOS ALERTAS SONOROS BINAURAIS — B3 PROFIT PRO          " -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

# 1. Alerta de COMPRA
Write-Host "[1/2] DISPARANDO ALERTA DE COMPRA..." -ForegroundColor Green
Write-Host "  -> Tom: 1350 Hz (Agudo - Impulso Comprador)" -ForegroundColor Gray
Write-Host "  -> Frequencia: 5 apitos rapidos de 75ms" -ForegroundColor Gray
1..5 | ForEach-Object {
    [Console]::Beep(1350, 75)
    Start-Sleep -Milliseconds 60
}
Write-Host "  -> Sintese de Voz SAPI: 'COMPRA! Preço 171405'" -ForegroundColor Green
(New-Object -ComObject SAPI.SpVoice).Speak("COMPRA! Preço 171405") | Out-Null

Start-Sleep -Seconds 2

# 2. Alerta de VENDA
Write-Host ""
Write-Host "[2/2] DISPARANDO ALERTA DE VENDA..." -ForegroundColor Red
Write-Host "  -> Tom: 900 Hz (Grave - Rejeição/Pressão Vendedora)" -ForegroundColor Gray
Write-Host "  -> Frequencia: 5 apitos rapidos de 75ms" -ForegroundColor Gray
1..5 | ForEach-Object {
    [Console]::Beep(900, 75)
    Start-Sleep -Milliseconds 60
}
Write-Host "  -> Sintese de Voz SAPI: 'VENDA! Preço 172025'" -ForegroundColor Red
(New-Object -ComObject SAPI.SpVoice).Speak("VENDA! Preço 172025") | Out-Null

Write-Host ""
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  [OK] Teste de audio concluido com sucesso!" -ForegroundColor Green
Write-Host "======================================================================" -ForegroundColor Cyan
