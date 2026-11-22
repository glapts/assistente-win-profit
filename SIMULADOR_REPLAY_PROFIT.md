# Roteiro do Simulador — Replay de Mercado no Profit Pro com DDE, Book e Times & Trades

Este documento consolida o protocolo de simulação e replay de mercado no **Nelogica Profit Pro** para testes com o **Harness de Execução** e a **Arquitetura Multi-Agente**.

---

## 1. Replay em Tempo Real via Conexão DDE (100% Pronto para Executar)

Quando você abre o Profit Pro, solicita um **Replay de Mercado** de qualquer dia e clica no **Play**:
- O Profit Pro começa a transmitir as cotações históricas exatamente como se o pregão estivesse acontecendo ao vivo.
- O conector [`feeds/dde_feed.py`](feeds/dde_feed.py) lê esses dados em tempo real no tópico `profitchart|cot`.
- **O que o DDE do Profit transmite:** Último preço (`ULT`), Máxima (`MAX`), Mínima (`MIN`), Volume (`VOL`), Melhor Oferta de Compra (`OFC`) e Melhor Oferta de Venda (`OFV`) no topo do Book.
- O Harness e o Orquestrador avaliam o mercado segundo a segundo e disparam os alarmes na tela conforme o replay avança.

### Comando para iniciar:
```powershell
cd C:\Users\glaci\assistente-win-profit
python run_harness_copilot.py
```

---

## 2. Book de Ofertas Completo (L2) e Times & Trades (Negócio a Negócio)

O protocolo DDE do Windows é um protocolo dos anos 90 e não suporta a avalanche de dados de milhares de negócios por segundo do Times & Trades completo nem a profundidade total de 20 níveis do Book sem perder pacotes.

Para simularmos com o **Times & Trades completo (com agressor)** e o **Book de Ofertas integral**, o Profit Pro oferece duas abordagens:

| Método | Como funciona | Para que serve |
| :--- | :--- | :--- |
| **A. Exportação de Times & Trades (CSV / Área de Transferência)** | No Profit Pro, você clica com o botão direito no Times & Trades do dia do replay e seleciona *"Copiar para Excel"* ou *"Exportar para Arquivo"*. Nosso [`feeds/csv_feed.py`](feeds/csv_feed.py) carrega todos os negócios em memória e roda o replay a 100x de velocidade. | Ideal para **backtests determinísticos ultrarrápidos** de microestrutura e absorção institucional. |
| **B. ProfitDLL da Nelogica (API Oficial em C/C++)** | A Nelogica possui a ProfitDLL com os eventos nativos `SetTradeCallback` (Times & Trades tick a tick com corretora e agressão) e `SetOfferBookCallback` (todas as filas do Book L2). | Ideal para **execução ao vivo ou replay assistido** em sub-milissegundo com profundidade total. |

---

## 3. Próximos Passos Agendados para a Sessão

1. **Opção 1 — Testar o Replay DDE ao Vivo:**
   - Abrir o Profit Pro no modo Replay (escolher pregão, ex: 18/11/2026 ou 19/11/2026).
   - Iniciar `run_harness_copilot.py`.
   - Acompanhar os alarmes e o Gatekeeper reagindo na tela em tempo real no tick-a-tick.

2. **Opção 2 — Rodar Replay de Microestrutura com CSV/Times & Trades:**
   - Exportar o Times & Trades do dia no Profit Pro para a pasta `data/`.
   - Executar o filtro de microestrutura [`core/harness/microstructure_filter.py`](core/harness/microstructure_filter.py) validando absorção de lotes institucionais ($\ge 100$ contratos) e corte de ruídos de HFT ($< 20$ contratos).
