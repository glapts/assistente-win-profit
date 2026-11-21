# Especificação de Atualização do Algoritmo: Scanner MTF de FVG e Alerta no PowerShell (Mini Índice)

Este documento contém o prompt de comando e as regras de negócio para atualizar o algoritmo de leitura do Mini Índice (WIN) integrado ao ProfitChart Pro.

---

## 1. Prompt para o Antigravity (Copie e Cole no Chat do Agente)

> **Instrução para o Agente de IA:**
> Atue como um Engenheiro de Software Quantitativo Sênior especialista em Python. Preciso que você atualize o nosso algoritmo atual de leitura do Mini Índice (integrado ao Profit Pro) seguindo estritamente as diretrizes do arquivo `@fvg_mtf_antigravity_spec.md`.
>
> **REGRA DE OURO (INVIOLÁVEL):**
> **NÃO altere nenhuma conta matemática, cálculo ou fórmula que já existe no algoritmo atual.** Toda a lógica matemática já presente no código deve permanecer $100\%$ intacta. Sua tarefa é apenas estender a arquitetura para ler múltiplos tempos gráficos, rastrear FVGs antigos não liquidados usando os cálculos já existentes e exibir o alerta antecipado colorido no PowerShell.
>
> **Requisitos obrigatórios da implementação:**
> 1. **Preservação Matemática Total:** Mantenha todas as fórmulas e contas atuais do script sem qualquer modificação.
> 2. **Suporte Multi-Timeframe (MTF):** Expanda a leitura para monitorar candles e FVGs nos tempos gráficos de **10, 15, 30, 60 e 240 minutos**.
> 3. **Rastreamento de FVGs Antigos Não Liquidados:** O algoritmo deve guardar na memória os FVGs formados anteriormente nesses tempos gráficos e monitorar quando o preço atual do Mini Índice está indo testar essas regiões (descartando apenas os que já foram totalmente liquidados).
> 4. **Alerta Antecipado no PowerShell:** Antes de o preço tocar na zona (ex: quando estiver indo em direção aos $170.000$ pontos), o código deve disparar um alerta antecipado no terminal PowerShell.
> 5. **Formatação Visual e Cores no PowerShell:**
>    * Todos os preços exibidos devem usar pontuação de milhar com ponto (ex: `170.000`).
>    * O rótulo **`Ponto de 50% (CE)`** deve ter uma cor de destaque exclusiva (Amarelo Brilhante / Ciano em negrito) para fácil e imediata identificação visual.
>    * O **preço do Ponto de 50% (CE)** e a indicação da operação devem ficar coloridos em **VERMELHO para VENDA** (quando o preço sobe para testar um FVG de baixa/resistência) e coloridos em **VERDE para COMPRA** (quando o preço cai para testar um FVG de alta/suporte).

---

## 2. Diretrizes Técnicas e Regras de Negócio

### 2.1. Preservação das Fórmulas Matemáticas Atuais
* **Proibição de Refatoração Matemática:** Nenhuma fórmula existente no código-fonte atual (cálculo de gaps, médias, filtros, distâncias ou indicadores internos) pode ser reescrita, simplificada ou alterada.
* **Reaproveitamento:** Utilize as mesmas funções/fórmulas matemáticas que o algoritmo já possui para identificar o FVG e seu nível de $50\%$ ($\text{CE}$), aplicando-as sobre as séries históricas dos tempos gráficos solicitados.

### 2.2. Tempos Gráficos Monitorados (MTF)
O algoritmo deve monitorar simultaneamente os seguintes tempos gráficos para buscar pontos de reversão de $200$ a $300$ pontos:
* $10\text{ minutos}$ (`10m`)
* $15\text{ minutos}$ (`15m`)
* $30\text{ minutos}$ (`30m`)
* $60\text{ minutos}$ (`60m`)
* $240\text{ minutos}$ (`240m` / $4\text{ horas}$)

---

## 3. Gerenciamento de FVGs Antigos (Não Liquidados)

O algoritmo deve manter uma lista ativa dos FVGs históricos de $10\text{m}$, $15\text{m}$, $30\text{m}$, $60\text{m}$ e $240\text{m}$ que ainda **não foram liquidados** (mitigados por completo):
1. **Armazenamento:** Guardar os limites da zona e o nível de $50\%$ calculado pela fórmula original do algoritmo.
2. **Verificação de Liquidação:**
   * Se um FVG de Baixa (Oferta/Venda) já foi completamente rompido para cima anteriormente, ele está liquidado e deve sair do radar.
   * Se um FVG de Alta (Demanda/Compra) já foi completamente rompido para baixo anteriormente, ele está liquidado e deve sair do radar.
   * Caso contrário, o FVG permanece ativo no radar aguardando o teste do preço.

---

## 4. Padronização do Alerta Antecipado e Cores no PowerShell

Quando o preço atual do Mini Índice estiver caminhando em direção a um FVG ativo e entrar na distância de pré-alerta (antes da entrada), o script deve imprimir no **PowerShell** usando códigos ANSI (via `colorama` ou escape nativo `\033[`).

### 4.1. Regra de Formatação Numérica (Milhar com Ponto)
Todos os níveis de preço do Mini Índice devem ser formatados obrigatoriamente com separador de milhar por ponto e sem casas decimais (exemplo em Python):
```python
def formatar_preco_win(valor: float) -> str:
    return f"{int(round(valor)):,}".replace(",", ".")
# Exemplo de saída: 170.000
```

### 4.2. Regra de Cores no Terminal PowerShell
Utilize os seguintes códigos ANSI para garantir leitura instantânea no terminal:
* **Destaque do Rótulo `Ponto de 50% (CE)`:** Amarelo Brilhante em Negrito (`\033[1;93m`) ou Ciano Brilhante (`\033[1;96m`).
* **Sinal de VENDA (Bearish FVG / Resistência):** Preço colorido em **VERMELHO BRILHANTE** (`\033[1;91m`).
* **Sinal de COMPRA (Bullish FVG / Suporte):** Preço colorido em **VERDE BRILHANTE** (`\033[1;92m`).
* **Reset de Cor:** `\033[0m`.

### 4.3. Exemplo Visual Exato no PowerShell

#### Cenário 1: Preço subindo rumo aos $170.000$ pontos (FVG de Baixa -> Alerta de VENDA em Vermelho)
```text
======================================================================
[RADAR FVG ANTECIPADO] - MINI ÍNDICE SE APROXIMANDO DE ZONA DE LIQUIDEZ
======================================================================
 Preço Atual       : 169.880
 Timeframe do FVG  : 60 Minutos (Aberto / Não Liquidado)
 Direção / Ação    : [VENDA - RESISTÊNCIA] (Em Vermelho: \033[1;91m)
 Início da Zona    : 170.000 (Faltam 120 pts)
 \033[1;93mPonto de 50% (CE)\033[0m : \033[1;91m170.085 (VENDA)\033[0m  <-- Rótulo em Amarelo e Preço em VERMELHO
 Fim da Zona       : 170.170
 Objetivo Estimado : Reversão de 200 a 300 pontos
======================================================================
```

#### Cenário 2: Preço caindo rumo aos $170.000$ pontos (FVG de Alta -> Alerta de COMPRA em Verde)
```text
======================================================================
[RADAR FVG ANTECIPADO] - MINI ÍNDICE SE APROXIMANDO DE ZONA DE LIQUIDEZ
======================================================================
 Preço Atual       : 170.120
 Timeframe do FVG  : 30 Minutos (Aberto / Não Liquidado)
 Direção / Ação    : [COMPRA - SUPORTE] (Em Verde: \033[1;92m)
 Início da Zona    : 170.000 (Faltam 120 pts)
 \033[1;93mPonto de 50% (CE)\033[0m : \033[1;92m169.915 (COMPRA)\033[0m <-- Rótulo em Amarelo e Preço em VERDE
 Fim da Zona       : 169.830
 Objetivo Estimado : Reversão de 200 a 300 pontos
======================================================================
```

---

## 5. Checklist de Execução para o Agente no Antigravity

- [ ] **Verificação de Segurança:** Garantir que nenhuma equação ou fórmula matemática original do script foi alterada ou removida.
- [ ] **Leitura MTF:** Adicionar suporte às janelas de `10m`, `15m`, `30m`, `60m` e `240m` utilizando a mesma matemática do código base.
- [ ] **Memória de FVGs Antigos:** Manter lista de FVGs antigos ainda não liquidados para identificar quando o preço atual volta a testá-los.
- [ ] **Formatação e Cores no PowerShell:** Aplicar a máscara de milhar (`170.000`), destacar o texto `Ponto de 50% (CE)` em amarelo brilhante (`\033[1;93m`) e colorir o preço em **vermelho (`\033[1;91m`) para venda** e **verde (`\033[1;92m`) para compra** antes da entrada.