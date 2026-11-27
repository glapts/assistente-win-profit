# Especificação Arquitetural: Sincronização Determinística e Poller DDE Dedicado

## 1. Contexto e Objetivo
Corrigir a dessincronização de índices de candles, o consumo de cotações teóricas durante o leilão de abertura e o gargalo de latência (~16.5s) no motor `ScalperGlaucio` e no conector `assistente-win-profit/feeds/dde_feed.py`, garantindo alinhamento 1:1 com o Profit Pro e execução abaixo de 50ms.

---

## 2. Requisitos Técnicos de Alteração

### Pilar 1: Sincronização Determinística de Índice (Baseada no Relógio)
* **Remover:** Qualquer acumulador linear em memória do tipo `self.candle_counter += 1` para definição do número do candle.
* **Implementar:** Cálculo determinístico do índice do candle com base no horário de abertura real da sessão contínua ($T_{\text{open}}$):
  $$\text{Candle Index} = (\text{Hora Atual} \times 60 + \text{Minuto Atual}) - (\text{Hora Abertura} \times 60 + \text{Minuto Abertura}) + 1$$
* **Regra de Resiliência:** Caso o script seja iniciado ou reiniciado no meio do pregão (ex.: às 10:45), o índice deve ser calculado diretamente pela diferença em minutos em relação a $T_{\text{open}}$ (ex.: se $T_{\text{open}} = \text{09:03}$, às $\text{10:45}$ o índice deve ser exatamente `#103`).
* **Fallback de $T_{\text{open}}$:** Se o robô iniciar após o início do pregão e não tiver capturado o primeiro tick real do dia, permitir configuração explícita ou detecção do horário de abertura do ativo no dia (padrão pós-leilão B3: `09:03`, ou inferido via histórico/parâmetro).

### Pilar 2: Notação Dupla no Terminal (Horário + Número da Barra)
* Atualizar a formatação dos logs e alertas de sinal no terminal para exibir explicitamente tanto a janela de horário (`HH:MM`) quanto o índice absoluto (`#N`):
  ```text
  ESTRUTURA      : Candles [10:42, 10:43 e 10:44] (Barras #100, #101 e #102)
  GATILHO 50% CE : 182.850 (Ponto de Equilíbrio)
  AÇÃO SUPERDOM  : PENDURAR VENDA EM 182.850 NO CANDLE DAS 10:45 (#103)
  ```

### Pilar 3: Poller Ultra-Rápido Dedicado (< 50ms)
* **Isolamento de Rota no `dde_feed.py`:** Criar um método/rota leve exclusivo para o `ScalperGlaucio` (sem quebrar a compatibilidade com o *Execution Harness*, que continua usando a rota completa de Tape Reading).
* **Tags Permitidas na Rota Leve (Price Action M1):**
  * `<ATIVO>.ULT` (Último preço)
  * `<ATIVO>.ABE` (Abertura do dia)
  * `<ATIVO>.MAX` (Máxima do dia)
  * `<ATIVO>.MIN` (Mínima do dia)
  * `<ATIVO>.VOL` (Volume financeiro/quantidade)
  * `<ATIVO>.NEG` (Número de negócios)
* **Tags Proibidas no Loop do Scalper:** Remover completamente chamadas a `AGRVOLC`, `AGRVOLV`, `AGRC`, `WSPZ26` e quaisquer campos que causem bloqueio ou timeout de 10s no loop de formação de candles.
* **Meta de Performance:** O ciclo de leitura e fechamento de candle de 1 minuto deve operar em `< 50ms`, disparando o cálculo do FVG imediatamente na virada do segundo `:00`.

### Pilar 4: Filtro de Validação de Leilão (Detecção do Primeiro Trade Real)
* **Problema:** Entre `09:00:00` e o fim do leilão (ex.: `09:02:59`), o Profit envia preços teóricos em `.ULT` sem negócios reais fechados, gerando candles artificiais.
* **Regra de Início de Sessão ($T_{\text{open}}$):**
  * Ignorar ticks antes do início efetivo das negociações contínuas.
  * Só registrar $T_{\text{open}}$ e iniciar a formação do `Candle #1` quando houver **transição real de negócios** pós-09:00:00 (`NEG > 0` com incremento real de negócios/volume e variação efetiva de trade executado).
  * Descartar completamente os minutos de leilão (`09:00` a `09:02` quando em leilão) para evitar deslocamento de índice.

---

## 3. Critérios de Aceitação
1. O `Execution Harness` permanece intacto e funcional.
2. O `ScalperGlaucio` não utiliza `self.candle_counter += 1`.
3. O loop DDE do `ScalperGlaucio` executa abaixo de `50ms` (logar/validar tempo de ciclo).
4. Reiniciar o script no meio do pregão mantém a numeração exata das barras idêntica ao Profit Pro.
5. Cotações de leilão antes do primeiro negócio real não geram candles #1, #2 ou #3 falsos.