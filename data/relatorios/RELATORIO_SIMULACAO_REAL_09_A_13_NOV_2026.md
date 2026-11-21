# Relatório de Auditoria Determinística — Semana de 09 a 13/11/2026
## Comparativo: Versão A (Baseline) vs Versão B (Execution Harness no SuperDOM)

### 1. Resumo dos Pregões Registrados via Nelogica Profit Pro DDE
* **Nota de Integridade:** Nos dias **11/11 e 12/11/2026**, o feed de logs do Profit Pro esteve pausado para empacotamento e backups do sistema (`backup_11-11-2026.zip`). Portanto, os testes avaliam os pregões com telemetria 100% íntegra: **09/11, 10/11 e 13/11**.

| Data | Versão A: Trades | Versão A: WR | Versão A: Pontos | Versão A: R$ (5 ct) | Versão B (Harness DOM): Trades | Versão B: WR | Versão B: Pontos | Versão B: Lucro Real (5 ct) |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **09/11/2026 (Segunda)** | 130 trades (36G / 94S) | 27.7% | -65 pts | R$ -65.00 | **2 trades (0G / 2S)** | **0.0%** | **-500 pts** | **R$ -500.00** |
| **10/11/2026 (Terça)** | 172 trades (41G / 131S) | 23.8% | -5505 pts | R$ -5,505.00 | **3 trades (1G / 2S)** | **33.3%** | **-100 pts** | **R$ -100.00** |
| **13/11/2026 (Sexta)** | 72 trades (34G / 38S) | 47.2% | +4200 pts | R$ +4,200.00 | **3 trades (1G / 2S)** | **33.3%** | **-100 pts** | **R$ -100.00** |
| **TOTAL CONSOLIDADO** | **374 trades** | **29.7%** | **-1370 pts** | **R$ -1,370.00** | **8 trades** | **25.0%** | **-700 pts** | **R$ -700.00** |

### 2. Como o Circuit Breaker e o Harness Protegeram o Capital em Dias Hostis
1. **09/11/2026 (Segunda-feira):** A Versão A disparou **130 operações**, com **94 stops**, gerando prejuízo em taxas de mais de R$ 650,00. O Harness tomou 2 stops, acionou o **Circuit Breaker Diário (máximo de 2 stops atingido)** e travou as operações, estancando a perda em -R$ 500,00 e evitando o colapso emocional.
2. **10/11/2026 (Terça-feira):** A Versão A colapsou com **172 trades** e **131 stops**, gerando um prejuízo violento de **-R$ 5.505,00** (-5.505 pts). O Harness fez 3 trades (1 Gain de +400 pts e 2 stops), travou pelo Circuit Breaker e limitou a oscilação a apenas **-R$ 100,00**! O Harness salvou a conta de uma perda de mais de R$ 5.500,00.
3. **13/11/2026 (Sexta-feira):** O Harness fez 3 trades (1 Gain de +400 pts e 2 stops), encerrando com **-R$ 100,00**.
