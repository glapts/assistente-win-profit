# Especificação Técnica: Monitoramento Institucional US (`>= 400 cts`) e Estratégia Abertura NY (`11:30 BRT`)

## 1. Visão Geral e Premissas de Arquitetura
* **Objetivo:** Elevar a taxa de acerto em reversões de topo/fundo e continuações pós-varredura de liquidez no Mini Índice (`WIN`), rastreando execuções de grande porte de players americanos e globais combinadas à dinâmica da abertura à vista de Nova York (`11:30 BRT`).
* **Restrições Operacionais:**
  * Preservar integralmente o diretório `C:\Users\glaci\assistente-win-profit` sem alterações ou exclusões.
  * Manter intactas todas as fórmulas matemáticas existentes de FVG (`5m` a `240m`), Delta de agressão, absorção e gerenciamento de risco.
  * Operar via ingestão do **Times & Trades (`Ordem Original`)** do Profit Pro (única fonte que expõe a corretora agressora).

---

## 2. Taxonomia de Players e Magnitude de Ordens

### 2.1 Classificação de Corretoras
| Grupo | Identificadores no Profit Pro | Peso Institucional | Critério de Ativação |
| :--- | :--- | :---: | :--- |
| **TIER_1_US** | `Morgan`, `Goldman`, `JP Morgan`, `BofA`, `Merrill`, `Citi`, `Jefferies` | **1.00** (Máximo) | Lote único ou cluster `<= 3s` **`>= 400` contratos** |
| **TIER_2_GLOBAL** | `UBS`, `Barclays`, `BNP`, `Deutsche`, `SocGen` | **0.90** (Alto) | Lote único ou cluster `<= 3s` **`>= 400` contratos** |
| **TIER_3_DMA** | `Ideal`, `BTG`, `XP` | **0.60** (Condicional) | Lote **`>= 600` contratos** + confluência `WSP` e `DI1F29` |

### 2.2 Classificação por Tamanho de Lote
* **WHALE_BLOCK (`400` a `999` contratos):** Execução institucional relevante; exige confluência de zona SMC e correlação.
* **MEGA_CLIMAX (`>= 1.000` contratos — ex.: `Morgan 1.400 cts`):** Evento de alta energia institucional; ativa monitoramento imediato de **Exaustão de Topo/Fundo** ou **Ignição de Rompimento**.

---

## 3. Lógica de Decisão em Topos e Fundos (Venda no Topo / Compra no Fundo)

### 3.1 Setup A — Venda Institucional em Topo (Reversão / Exaustão)
1. **Localização:** Preço testando zona de oferta (`FVG 15m/60m/240m`, `Order Block` de baixa ou varredura de máxima intradiária/anterior).
2. **Gatilho de Fluxo (`TIER_1_US` / `TIER_2_GLOBAL`):**
   * *Padrão Clímax Comprador (Stop Hunt):* Player US compra `>= 400` (ou `>= 1.000`) contratos no extremo superior (`preço*`), o preço trava (absorção passiva vendedora) e perde o nível nos `30s–180s` seguintes; **OU**
   * *Padrão Agressão Vendedora:* Player US entra vendendo `>= 400` contratos contra o topo, iniciando deslocamento vendedor.
3. **Validação Gráfica (`5Min` + `2Min`):**
   * Candle de **`5Min` NÃO fecha corpo cheio** acima da resistência.
   * Candle de **`2Min` confirma CHoCH de baixa** (perda da mínima do último candle comprador).
4. **Execução:** Venda na perda do micro-suporte após o CHoCH do `2Min`, com Stop acima da máxima do pavio (`150 pts` no Modo Ignição ou `250 pts` estrutural) e Alvo fixo de `400 pts`.

### 3.2 Setup B — Compra Institucional em Fundo (Defesa / Absorção)
1. **Localização:** Preço testando zona de demanda (`FVG 15m/60m/240m`, `Order Block` de alta ou varredura de mínima intradiária/anterior).
2. **Gatilho de Fluxo (`TIER_1_US` / `TIER_2_GLOBAL`):**
   * Player US bate `>= 400` contratos na venda sobre o suporte sem romper o nível (absorção passiva compradora), ou agride `>= 400` contratos na compra iniciando virada.
3. **Validação Gráfica (`5Min` + `2Min`):**
   * Candle de **`5Min` NÃO fecha corpo cheio** abaixo do suporte.
   * Candle de **`2Min` confirma CHoCH de alta** (rompimento da máxima do último candle vendedor).
4. **Execução:** Compra na retomada acima do CHoCH do `2Min`, com Stop abaixo da mínima do pavio (`150 pts` ou `250 pts`) e Alvo fixo de `400 pts`.

---

## 4. Protocolo Operacional: Abertura de Nova York (`11:30 BRT`)

| Janela Horária (BRT) | Regime de Mercado | Regra do Algoritmo |
| :--- | :--- | :--- |
| **`11:15 – 11:29`** | Pré-Abertura NY / Posicionamento | Mapear máxima e mínima da manhã (`10:00–11:25`) como alvos primários de varredura de liquidez (*Sweep*). |
| **`11:30:00 – 11:33:00`** | Leilão NYSE/Nasdaq & Arbitragem ADRs | **Bloqueio de disparo (`HOLD`)** para evitar *spreads* abertos e violinadas nos 3 minutos iniciais. |
| **`11:33:01 – 12:30:00`** | Fluxo Direcional NY (`NY_CASH_OPEN`) | Liberar gatilhos com peso dobrado para players `TIER_1_US` alinhados a `WSP`, `WDO`, `DI1F29` e ADRs (`ITUB4`, `PETR4`, `VALE3`). |

### 4.1 Matriz de Alinhamento Cross-Market (`11:30 BRT`)
* **Viés Vendedor Validado:** `WSP` negativo + `WDO` positivo + `DI1F29` em alta + `TIER_1_US` vendendo `>= 400 cts` (ou absorvendo topo).
* **Viés Comprador Validado:** `WSP` positivo + `WDO` negativo + `DI1F29` em queda + `TIER_1_US` comprando `>= 400 cts` (ou absorvendo fundo).
* **Bloqueio de Divergência:** Se `TIER_1_US` entrar contra `WSP`, `WDO` e `DI1F29` simultaneamente fora de zona `60m/240m`, classificar como *Ruído de Arbitragem* e não operar.

---

## 5. Modelo de Pontuação (Score de Assertividade `0–100`)
* **+30 pts:** Preço dentro/borda (`<= 100 pts`) de FVG `15m/60m/240m` ou Sweep de Topo/Fundo.
* **+30 pts:** Ordem `TIER_1_US` ou `TIER_2_GLOBAL` **`>= 400` contratos** (`+10 pts` bônus se `>= 1.000` contratos).
* **+20 pts:** Rejeição confirmada no `5Min` + **CHoCH no `2Min`** com inversão de Delta.
* **+20 pts:** Alinhamento simultâneo de pelo menos 3 entre 4 correlações (`WSP`, `WDO`, `DI1F29`, `Blue Chips`).
* **Limiar de Operação:** Disparar alerta operacional de alta assertividade no PowerShell somente quando **`Score >= 80`**.