# Preferências Operacionais do Usuário

## Interface de Execução: SuperDOM (Profit Pro)
* **Status:** ATIVADO E DEFINIDO COMO PADRÃO.
* **Finalidade:** O usuário utiliza o **SuperDOM** (Price Ladder / Profundidade Vertical) do Profit Pro como a interface preferencial para apregoamento, clique e envio ágil de ordens.
* **Vantagens Técnicas no Fluxo de Tape Reading:**
  * Visualização da fila de ordens nos níveis de preço da B3.
  * Agilidade de execução a 1 clique com estratégias OCO pré-configuradas.
  * Localização visual imediata do preço de **ENTRADA** indicado pelo Assistente de Análise.

## Workflow Integrado (Assistente PowerShell + SuperDOM Profit)
1. **Identificação pelo Assistente (PowerShell):**
   * O Assistente detecta a confluência de SMC (Sweep, FVG, BOS/CHoCH) e emite o alerta colorido:
     * `DIREÇÃO: COMPRA ou VENDA`
     * `ENTRADA: [Preço em Ciano]`
     * `STOP: 250 pontos [Preço em Vermelho]`
     * `ALVO: 400 pontos [Preço em Verde]`
2. **Execução no SuperDOM (Manual pelo Usuário):**
   * O usuário localiza o nível de preço no SuperDOM.
   * Com a regra OCO selecionada (`50 ticks Loss / 80 ticks Gain`), clica na coluna de Compra/Venda.
   * A ordem é apregoada e o Profit Pro ancora os stops e alvos visíveis na grade.
