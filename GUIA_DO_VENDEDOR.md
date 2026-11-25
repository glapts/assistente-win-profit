# GUIA DO VENDEDOR — DISTRIBUIÇÃO & PROTEÇÃO ANTI-PIRATARIA
## Assistente de Trading Institucional Mini-Índice B3 (WIN) — Cenário 3 Oficial

Este guia explica como funciona o ecossistema de proteção, geração de chaves e distribuição comercial do seu robô/assistente para Windows 11.

---

### 🛡️ 1. Como o seu algoritmo está protegido

1. **Código-Fonte Oculto (Compilação Binária Nativa PE):**
   * Todo o código-fonte, incluindo os modelos do Cenário 3 (Target +400 pts / Stop -250 pts, Radar FVG MTF, Mitigação de rompimentos secos de 1m e regras de Tape Reading), foi empacotado em um executável nativo do Windows (`AssistenteWIN.exe`).
   * O cliente não tem acesso aos arquivos de código e não precisa de nenhum interpretador instalado no computador dele.

2. **Trava Criptográfica de Hardware (HWID Lock):**
   * Cada computador possui uma identidade de hardware única no Windows (calculada a partir da Placa-Mãe, Registro do Windows e Volume do Disco).
   * A licença gerada é assinada digitalmente com algoritmo **HMAC-SHA256** e vinculada exclusivamente ao computador daquele cliente.
   * **Se o comprador repassar o programa para outra pessoa:** O programa lerá o HWID diferente e bloqueará a execução instantaneamente com a mensagem:
     `ESTA LICENÇA PERTENCE A OUTRO COMPUTADOR! Proibido compartilhamento ou execução não autorizada.`

---

### 💼 2. Passo a Passo: Quando um cliente comprar o software

#### Passo 1: Enviar o Instalador
* Envie para o comprador o arquivo:
  `Instalador_AssistenteWIN_v1.0.zip`

#### Passo 2: O Cliente Instala e Envia o Código dele
* O cliente extrai o ZIP e executa `instalar.bat`.
* O instalador cria o atalho oficial na Área de Trabalho do Windows 11 e disponibiliza o manual do trader em PDF com 42 páginas.
* Ao abrir o atalho, o programa exibirá:
  ```text
  SEU CÓDIGO DE IDENTIFICAÇÃO DESTE COMPUTADOR (HWID):
  >>> 8BB2-4F89-22C7-D97F <<<
  ```
* O cliente copia esse código e envia para você pelo WhatsApp / E-mail.

#### Passo 3: Você Gera a Chave de Ativação
* No seu computador, abra o PowerShell e execute:
  ```powershell
  python C:\Users\glaci\assistente-win-comercial\admin_tools\gerador_licencas.py
  ```
* O gerador solicitará:
  1. Nome do Cliente (ex.: `Carlos Eduardo`)
  2. HWID do Cliente (cole o código que ele te enviou)
  3. Tipo de Licença:
     * `[1]` Vitalícia (Acesso permanente)
     * `[2]` 30 Dias (Mensalidade)
     * `[3]` 1 Ano (Anual)
* O gerador emitirá a chave no formato:
  `WIN-LIC-eyJjbGllbn...-A1B2C3D4`

#### Passo 4: O Cliente Ativa
* Você envia a chave para o cliente.
* Ele cola na tela do programa e pressiona Enter.
* O sistema ativa imediatamente, grava a licença localmente e o menu principal é liberado!

---

### 🚀 3. Funcionalidades do Menu do Cliente (Cenário 3)

O cliente terá acesso ao menu interativo completo:
* **[1] Iniciar Monitoramento em Tempo Real (Cenário 3):** Conexão ao vivo com o Profit Pro (DDE) operando com Alvo de 400 pts e Stop de 250 pts.
* **[2] Iniciar Monitoramento (Modo Estrutural):** Alvo e stop calculados pela amplitude da zona SMC.
* **[3] Simulação do Cenário 3 (Bloqueio FVG):** Demonstra na prática como o algoritmo bloqueia uma armadilha institucional e protege a conta do trader.
* **[4] Simulação do Cenário 3 (Passagem Livre):** Demonstra uma entrada com confluência de Delta no fluxo e rota livre.
* **[5] Demonstração do Radar FVG Multi-Timeframe:** Exibe o rastreio antecipado em 10m, 15m, 30m, 60m e 240m.
* **[6] Demonstração Visual de Alertas:** Demonstra as cores e formato do SuperDOM.
* **[7] Diagnóstico Oficial:** Validação das conexões DDE e processos do Profit Pro.

---

### 🔄 4. Como Regerar o Pacote no Futuro (Atualizações)

Se no futuro você fizer novos ajustes nas estratégias da versão comercial:
1. Compile novamente o executável:
   ```powershell
   python C:\Users\glaci\assistente-win-comercial\build_exe.py
   ```
2. Gere o novo pacote ZIP:
   ```powershell
   python C:\Users\glaci\assistente-win-comercial\gerar_pacote_venda.py
   ```
O novo `Instalador_AssistenteWIN_v1.0.zip` estará pronto na pasta!
