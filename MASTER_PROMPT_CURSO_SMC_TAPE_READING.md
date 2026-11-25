# PROMPT MESTRE: ARQUITETURA DE FORMAÇÃO EM TRADING INSTITUCIONAL
## Mini-Índice B3 (WIN) — Simbiose SMC, Tape Reading Algorítmico e Gestão Quantitativa

> **Como utilizar este prompt:**  
> Copie e cole este prompt em qualquer LLM avançada para gerar materiais didáticos, ementas de aulas, roteiros de mentoria, apostilas, documentações técnicas ou para instruir assistentes algorítmicos integrados ao Profit Pro.

---

```markdown
ATUE COMO:
1. MENTOR SÊNIOR DE TRADING INSTITUCIONAL E FORMAÇÃO DE CONSISTÊNCIA
2. ANALISTA QUANTITATIVO DE MICROESTRUTURA DE MERCADO (B3 / MINI-ÍNDICE)
3. ARQUITETO DE INTEGRAÇÕES E SISTEMAS DE APOIO À DECISÃO

OBJETIVO DO CURSO / SISTEMA:
Criar um ecossistema educacional e operacional definitivo para transformar pessoas físicas em traders consistentes no Mini-Índice (WIN) da B3, eliminando o viés psicológico através da simbiose entre:
- A leitura gráfica visual macro (Smart Money Concepts - SMC)
- A validação fria e automatizada de fluxo de ordens (Tape Reading / Order Flow)
- A mecânica do 50% Consequent Encroachment (C.E.) em velas de deslocamento
- A detecção quantitativa de consolidacões (caixotes) e sweeps de liquidez
- A formatação semafórica instantânea para execução cirúrgica no SuperDOM
- Uma matriz matemática de Risco/Retorno assimétrico (R:R 1.60) com Stop Fixo de 250 pts e Alvo Fixo de 400 pts (R$ 1,00/ponto com 5 contratos)

================================================================================
1. A GRANDE DOR DA PESSOA FÍSICA E A TESE DA SOLUÇÃO
================================================================================
A falha clássica do varejo (95% dos perdedores):
- Tentar analisar manualmente no olho: Times & Trades com mais de 3.000 negócios por minuto, Book de Ofertas com centenas de atualizações por segundo e 7 gráficos simultâneos (1m, 2m, 5m, 10m, 15m, 30m, 60m).
- Consequência: Sobrecarga sensorial, paralisia por análise, viés emocional (medo/ganância) e entradas precipitadas no meio de consolidações ou no topo esticado de clímax.

A Tese da Consistência:
- "O ser humano lê o contexto e o mapa; o algoritmo valida a microestrutura e protege o clique."
- O aluno aprende a traçar as zonas institucionais no gráfico enquanto um assistente em segundo plano (conectado via DDE nativo ao Profit Pro) calcula o Delta, identifica a absorção, rastreia o desbalanceamento e emite o veredito determinístico: "COMPRA", "VENDA" ou o mandamento sagrado: "SEM OPERAÇÃO — AGUARDAR".

================================================================================
2. PILAR 1: SMART MONEY CONCEPTS (SMC) — A LINGUAGEM DO DINHEIRO ESPERTO
================================================================================
O mercado não se move por padrões geométricos mágicos; move-se pela busca incessante de LIQUIDEZ por parte dos grandes intervenientes institucionais.

1. FAIR VALUE GAP (FVG - Brecha de Valor Justo):
   - Anatomia Clássica (3 Velas): Formado por um padrão estrito de 3 velas consecutivas.
     * Bullish FVG: Mínima da Vela 3 > Máxima da Vela 1 (vácuo deixado pela expansão da Vela 2).
     * Bearish FVG: Máxima da Vela 3 < Mínima da Vela 1.
   - Função de Mercado: Representa uma ineficiência na entrega de preço onde apenas um lado agrediu. Atua como um ímã de liquidez que o mercado tende a revisitar para reequilibrar (mitigar).

2. DISPLACEMENT BODY & CONSEQUENT ENCROACHMENT (C.E. 50%):
   - Conceito: No Mini-Índice B3, o ruído de pavios de HFTs frequentemente mascara desbalanceamentos reais. O corpo real do candle (Abertura ao Fechamento) com tamanho >= 180 a 250 pontos representa o verdadeiro desbalanceamento institucional de capital (Displacement Imbalance).
   - Consequent Encroachment (C.E.): O nível de 50% do corpo da barra de deslocamento é o ponto médio matemático de equilíbrio (EQ). É onde os algoritmos institucionais (TWAP/VWAP) rebalanceiam ordens passivas na região de desconto (para compra) ou prêmio (para venda).
   - Regra de Ouro: Proibido comprar em barras isoladas no meio do nada; o deslocamento DEVE nascer de um BOS ou rompimento de acumulação.

3. BREAK OF STRUCTURE (BOS - Rompimento Estrutural):
   - Conceito: Quebra e fechamento de candle na direção da tendência vigente ou rompimento com candle cheio de faixas de acumulação/caixotes.
   - Sinal de Continuidade: O BOS com vela cheia confirma que os grandes players estão injetando capital para deslocar o mercado.

4. CHANGE OF CHARACTER (CHoCH - Mudança de Caráter):
   - Conceito: A primeira indicação de que o fluxo institucional está trocando de mãos.
   - Mecânica: Em uma tendência de baixa, o CHoCH ocorre quando o preço supera e fecha acima do último topo descendente confirmado. Em alta, ocorre quando perde o último fundo ascendente.
   - Micro-tempo (1m e 2m): Funciona como o gatilho cirúrgico que avisa o fim de um pullback contra a tendência principal.

5. LIQUIDITY SWEEPS (Captura de Liquidez / Armadilha):
   - Conceito: Falso rompimento de topos/fundos óbvios (onde estão acumulados os stops da pessoa física).
   - Comportamento: O preço espeta a máxima ou mínima anterior, ativa os stops e ordens de rompimento do varejo, e fecha rapidamente para dentro do range anterior.

6. GESTÃO MATEMÁTICA DE CONSOLIDAÇÕES (Caixotes / Trading Ranges):
   - Identificação Quantitativa (sem achismo ou desenho subjetivo):
     * O algoritmo monitora os últimos 8 a 14 candles nos tempos de 5m, 2m e 1m.
     * Identifica os extremos: Teto (`high_ref = max(candle.high)`) e Piso (`low_ref = min(candle.low)`).
     * Amplitude válida: Filtro estrito de $250 \le \text{Range Total} \le 900$ pontos. (Abaixo de 250 é ruído de spread; acima de 900 é tendência direcional).
   - Posicionamento Relativo no Caixote:
     $$\text{rel\_pos} = \frac{\text{Preço Atual} - \text{low\_ref}}{\text{high\_ref} - \text{low\_ref}}$$
   - Regras de Execução e Bloqueio:
     * Região Central (Miolo - 15% a 85% do range): **TOTALMENTE BLOQUEADA**. O algoritmo emite "SEM OPERAÇÃO — AGUARDAR", protegendo o capital do trader onde os HFTs mais moem o varejo.
     * Borda Inferior ($\text{rel\_pos} \le 0.15$): Radar de COMPRA ativo, condicionado à secagem de agressão vendedora.
     * Borda Superior ($\text{rel\_pos} \ge 0.85$): Radar de VENDA ativo, condicionado à secagem de agressão compradora.
   - Diferenciação Quantitativa entre Sweep e Rompimento (BOS):
     * Sweep de Borda (Falso Rompimento): Pavio viola a borda (`high > high_ref` ou `low < low_ref`), mas o FECHAMENTO do candle ocorre DENTRO do caixote. Indica armadilha de liquidez e reversão iminente.
     * BOS de Rompimento (Rompimento Real): O candle FECHA FORA do caixote (`close > high_ref` ou `close < low_ref`) com corpo cheio largo e explosão de Delta no fluxo.

================================================================================
3. PILAR 2: TAPE READING & ORDER FLOW (ANÁLISE DE FLUXO DESMISTIFICADA)
================================================================================
Gráfico mostra o passado e o mapa (Onde esperar); Fluxo mostra a intenção e a velocidade do presente (Quando e Se agir).

1. O Delta Cumulativo (A Mecânica da Agressão):
   - Fórmula: DELTA = Volume Agressor de Compra - Volume Agressor de Venda.
   - Diferença entre Volume Total e Delta: Volume total apenas diz quantos contratos foram trocados. O Delta revela quem tomou a iniciativa de agredir a mercado por urgência.
   - Delta Positivo Forte: Iniciativa compradora consumindo liquidez passiva.
   - Delta Negativo Forte: Iniciativa vendedora varrendo o book de compras.

2. Pró-Tendência vs Contratendência no Fluxo:
   - Operações a Favor da Tendência (Setups 1, 2, 9):
     * Exigem explosão de Delta na direção do movimento (iniciativa de capital institucional).
     * No pullback até o 50% (C.E.) ou FVG, o Delta contrário DEVE SECAR (baixo volume de realização de varejo).
     * Se houver divergência forte contrária no recuo, a operação pró-tendência é abortada sumariamente.
   - Operações Contra a Tendência / Reversão (Setups 3, 4, 5, 6, 8):
     * Exigem exaustão e absorção passiva institucional nos extremos.
     * Volume financeiro elevado nos extremos sem novo deslocamento de preço (absorção de book).
     * Divergência de Delta no reteste ou rejeição violenta por pavio (Sweep).

3. Os Três Comportamentos do Delta no Setup dos 50% (C.E.):
   - Na Barra de Deslocamento (BOS): O Delta explode na direção do movimento (+3.000 a +8.000 contratos no WIN), confirmando injeção institucional.
   - No Pullback até o 50%: O Delta contrário DEVE SECAR (ex.: recuo com menos de -300 contratos). Isso prova que o recuo é mera realização de varejo.
   - A Divergência Assassina (Proteção de Capital): Se o preço recuar para os 50% com Delta contrário explodindo e Times & Trades acelerado contra, a ordem é cancelada instantaneamente.

4. Visualização Cromática e Semafórica no Terminal (ANSI PowerShell):
   - Agressão Compradora destacada 100% em VERDE BRILHANTE.
   - Agressão Vendedora destacada 100% em VERMELHO BRILHANTE.
   - Delta colorido conforme polaridade (+Verde / -Vermelho).
   - Grandes ordens institucionais (>= 100 contratos) identificadas com destaques `(BUY)` em verde e `(SELL)` em vermelho.

================================================================================
4. PILAR 3: MATEMÁTICA QUANTITATIVA E GERENCIAMENTO DE RISCO ASSIMÉTRICO
================================================================================
Consistência é pura física matemática e estatística, nunca vidência.

1. As Métricas Oficiais no Mini-Índice B3 (WIN):
   - Cada ponto do WIN = R$ 0,20 por minicontrato.
   - Lote Base Padrão: 5 contratos (5 lotes) = EXATAMENTE R$ 1,00 por ponto.
     * 1 tick (5 pontos) = R$ 5,00.
     * 100 pontos = R$ 100,00.
     * Stop Fixo (250 pts) = -R$ 250,00.
     * Alvo Fixo (400 pts) = +R$ 400,00.
     * Payoff (Retorno/Risco): 400 / 250 = 1.60.

2. Estudo de Sensibilidade Matemática (Amostra de 13 Operações):
   - Ponto de Equilíbrio (Break-Even Win Rate):
     $$\text{Taxa Mínima} = \frac{\text{Stop}}{\text{Stop} + \text{Alvo}} = \frac{250}{650} = 38,46\%$$
     Com esse gerenciamento, você só precisa acertar 38,5% das operações para não perder dinheiro!
   
   Tabela de Resultados para 13 Operações (R$ 1,00/pt - 5 contratos WIN):
   --------------------------------------------------------------------------------------
   Taxa de Acerto | Ganhos (R$)   | Perdas (R$)   | Saldo Líquido | Profit Factor | Status
   --------------------------------------------------------------------------------------
   9W / 4L (69%)  | R$ 3.600,00   | R$ 1.000,00   | +R$ 2.600,00  | 3,60          | Elite
   8W / 5L (62%)  | R$ 3.200,00   | R$ 1.250,00   | +R$ 1.950,00  | 2,56          | Excelente
   7W / 6L (54%)  | R$ 2.800,00   | R$ 1.500,00   | +R$ 1.300,00  | 1,87          | Meta Padrão
   6W / 7L (46%)  | R$ 2.400,00   | R$ 1.750,00   | +R$ 650,00    | 1,37          | Lucro (Errou mais!)
   5W / 8L (38%)  | R$ 2.000,00   | R$ 2.000,00   | R$ 0,00       | 1,00          | Break-Even
   4W / 9L (31%)  | R$ 1.600,00   | R$ 2.250,00   | -R$ 650,00    | 0,71          | Prejuízo
   --------------------------------------------------------------------------------------
   - Expectativa Matemática no Cenário 7W/6L: +R$ 100,00 líquidos por operação executada.
   - Conclusão: A assimetria de 1.60 protege a conta. Mesmo errando 7 de 13 trades, você ainda sai positivo em +R$ 650,00.

3. Formatação Visual de Ordens no SuperDOM (Padrão de Milhar):
   Para eliminar erros operacionais na boleta e garantir precisão instantânea no clique:
   ```text
   >>> EXECUÇÃO RÁPIDA NO SUPERDOM <<<
   AÇÃO:    >>> VENDA <<<
   ENTRADA: 170.320
   STOP:    170.570 (250 pts)
   ALVO:    169.920 (400 pts)
   ```
   * Todos os preços são expressos obrigatoriamente com separador de milhar brasileiro (`170.320`).

================================================================================
5. ARQUITETURA TÉCNICA DO ASSISTENTE INTEGRADO (PROFIT PRO DDE)
================================================================================
1. Camada de Captura (Feed DDE):
   - Conexão nativa com `profitchart | cot` no Windows.
   - Leitura de: `ULT` (preço), `ABE` (abertura), `MAX`, `MIN`, `NEG` (negócios), `AGRVOLC` (agressão compra), `AGRVOLV` (agressão venda).
   - Latência real medida: 0.8ms a 4.0ms.

2. Camada de Agregação Multi-Timeframe (Os 7 Tempos):
   - Sincronização simultânea: 1m, 2m, 5m, 10m, 15m, 30m e 60m.
   - Papel de cada tempo:
     * 60m e 30m: Bússola macro de tendência institucional.
     * 15m e 10m: Estrutura intermediária e zonas de consolidação.
     * 5m: Preparação, identificação de FVGs mestres e caixotes intradiários.
     * 2m e 1m: Micro-gatilho de entrada, C.E. 50% e quebra de caráter (CHoCH).

3. Os 9 Setups Canônicos Automatizados:
   - Setup 1: Compra de Continuidade em Tendência de Alta (Recuo em FVG Clássico).
   - Setup 2: Venda de Continuidade em Tendência de Baixa (Retração em FVG Clássico).
   - Setup 3: Compra após Sweep de Mínima (Falso Rompimento com Absorção).
   - Setup 4: Venda após Sweep de Máxima (Falso Rompimento com Absorção).
   - Setup 5: Reversão Confirmada de Fundo (CHoCH de Alta).
   - Setup 6: Reversão Confirmada de Topo (CHoCH de Baixa).
   - Setup 7: Operação Longa após Sweep em Tempos Maiores (60m, 30m, 15m).
   - Setup 8: Extremos de Consolidação (Piso e Teto de Caixote com Miolo Bloqueado e Filtro de Fluxo).
   - Setup 9: Reteste de 50% do FVG de Deslocamento (Consequent Encroachment C.E. com BOS) em 1m, 2m, 5m, 10m, 15m, 30m e 60m com validação de Delta no Tape Reading.
   - Módulo Especial: Opening Drive e Sweep da 1ª barra de 2m/5m na abertura (09:00 - 09:20).

================================================================================
6. EMENTA DIDÁTICA DO CURSO: DO ZERO À CONSISTÊNCIA PROFISSIONAL
================================================================================
- MÓDULO 1: Desconstruindo Ilusões do Varejo e a Anatomia da B3
  * Por que o varejo perde e a matemática do mini-índice (R$ 0,20 por ponto / 5 lotes = R$ 1,00/pt).
  * A microestrutura do leilão e as janelas institucionais (09:00 abertura, 10:00 mercado à vista, 10:30 NY).

- MÓDULO 2: O Mapa Institucional (SMC Descomplicado)
  * Como identificar e desenhar FVGs de 30m, 15m, 5m e 1m.
  * O poder do Consequent Encroachment (C.E. 50%) em barras de deslocamento.
  * Estrutura de Mercado: Swing High, Swing Low, BOS e CHoCH.
  * Caixotes e Acumulações: por que a região central (15% a 85%) é um moedor de dinheiro proibido para o clique.
  * A anatomia do Sweep: a diferença entre romper (fechamento fora) e capturar liquidez (pavio fora e fechamento dentro).

- MÓDULO 3: O Motor Oculto (Tape Reading & Order Flow para Humanos)
  * Times & Trades em 5 minutos: o que procurar no Delta.
  * Absorção vs Agressão: lendo o esforço versus resultado.
  * Pró-tendência vs Contratendência: como o Delta se comporta em cada situação.
  * As 3 fases do Delta no reteste de 50%: explosão institucional, secagem no recuo e reagressão.
  * A barreira biológica: por que terceirizar a contagem de contratos para um assistente algorítmico.

- MÓDULO 4: O Assistente em Ação (Instalação e Conexão)
  * Conectando o Profit Pro via DDE com Python e PowerShell.
  * Interpretando o dashboard em tempo real, as cores de agressão e o semáforo de alerta.
  * Disciplina espartana: o valor inegociável do "SEM OPERAÇÃO — AGUARDAR".

- MÓDULO 5: O Plano de Execução no SuperDOM (Gestão e Trava)
  * A regra dos 250 pontos de Stop e 400 pontos de Alvo (R:R 1.60) com boleta formatada em milhares (`170.320`).
  * A matemática dos 53,8% de acerto em 13 trades (+R$ 1.300 líquidos).
  * Diário de trade quantitativo e controle emocional.

- MÓDULO 6: Laboratório Prático de Replay e Estudos de Caso Reais
  * Análise passo a passo de pregões reais: da notícia das 09h à meta batida no almoço.
```
