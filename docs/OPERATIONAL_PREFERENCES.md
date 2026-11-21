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
   * Com a regra OCO selecionada (`SMC_50x80`), clica na coluna de Compra/Venda.
   * A ordem é apregoada e o Profit Pro ancora os stops e alvos visíveis na grade.

## Por que a ordem não pendura no SuperDOM e como resolver

1. **Modo 1 Clique Desativado no SuperDOM:**
   * Clique com o botão direito no SuperDOM -> **Propriedades do Livro** -> aba **Geral** -> marcar **"Modo 1 Clique"**.
   * No cabeçalho da janela do SuperDOM, certifique-se de que o ícone do **Raio** (One-Click) está ativo.

2. **Estratégia OCO Não Selecionada no Topo do SuperDOM:**
   * No campo suspenso **"Estratégia"** no topo da janela do SuperDOM (ao lado da Quantidade), selecione a estratégia **`SMC_50x80`**.
   * Se o campo estiver em branco ou "Nenhuma", o Profit envia apenas a ordem simples sem pendurar o Stop e o Alvo automáticos.

3. **Ordem Limite vs Ordem Stop (Tecla SHIFT):**
   * Na coluna de **Compra (Azul)**:
     * Abaixo do preço de mercado = **Compra Limite** (Clique direto pendura a ordem).
     * Acima do preço de mercado = **Compra Stop** (Exige segurar **SHIFT** + Clique, regra de proteção da B3).
   * Na coluna de **Venda (Vermelha)**:
     * Acima do preço de mercado = **Venda Limite** (Clique direto pendura a ordem).
     * Abaixo do preço de mercado = **Venda Stop** (Exige segurar **SHIFT** + Clique, regra de proteção da B3).
   * *Se tentar colocar uma ordem Stop sem segurar o SHIFT, o Profit Pro não pendura a ordem por segurança.*

4. **Pop-up de Confirmação de Envio:**
   * No menu do Profit Pro: `Negociação` -> `Configurações` -> `Confirmações`.
   * Desmarque a opção **"Confirmar envio de ordens no SuperDOM"** para envio instantâneo sem janela modal de confirmação.
