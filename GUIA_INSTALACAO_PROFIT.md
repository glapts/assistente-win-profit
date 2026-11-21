# 📘 MANUAL DE INSTALAÇÃO E CONFIGURAÇÃO — ASSISTENTE QUANTITATIVO B3

Este guia foi elaborado para que qualquer pessoa consiga configurar o **Nelogica Profit Pro** e rodar o assistente em menos de 3 minutos.

---

## 🚀 PARTE 1: Configuração do Profit Pro (Transmissão DDE em Tempo Real)

Para que o algoritmo receba os dados de cotação e agressão (Tape Reading), configure o Profit exatamente como mostrado nas etapas abaixo:

### Passo 1: Abrir a Janela de Exportação DDE
1. No menu superior principal do seu Profit Pro, clique em **Cotações**.
2. Clique na opção **Exportar em Tempo Real (RTD/DDE)**.

---

### Passo 2: Aba "Ativos"
1. No campo de busca à esquerda, digite e adicione os 3 ativos suportados:
   * **`WINZ26`** (ou o contrato atual vigente do Mini-Índice)
   * **`WDOZ26`** (ou o contrato atual vigente do Mini-Dólar)
   * **`VALE3`** (Ação da Vale)
2. No rodapé inferior esquerdo da janela, certifique-se de selecionar a opção circular **🔘 DDE**.

---

### Passo 3: Aba "Atributos"
Na barra de seleção de atributos, marque exatamente as seguintes caixas:

1. **Campos de Preço e Volume:**
   * `[X] Último`
   * `[X] Abertura`
   * `[X] Máximo`
   * `[X] Mínimo`
   * `[X] Negócios`
2. **Campos de Fluxo e Agressão (Tape Reading):**
   * `[X] Agr. Compra`
   * `[X] Agr. Venda`
3. No rodapé, mantenha a opção **🔘 DDE** selecionada.

---

### Passo 4: Aba "Configurações"
Na aba **Configurações**, marque as opções exatamente como segue:
* **Tipo:** Marcar **🔘 DDE**
* **Exportar:** Marcar **🔘 Microsoft Excel**
* **Colunas:** Marcar **🔘 Copiar o título de cada coluna**
* **Valores:** Marcar **🔘 Exibir valores do pregão anterior**
* **Transferência de Dados:** Marcar **☑️ Ativar transferência de dados** (Essencial!)
* Clique no botão azul **OK** no canto inferior direito para salvar e fechar a janela.

---

## 🔑 PARTE 2: Como Funciona a Liberação da Licença de Testes (15 Dias)

1. Quando o cliente abre o programa pela primeira vez, o terminal exibe o código único dele:
   ```text
   👉 SEU CÓDIGO DE IDENTIFICAÇÃO (HARDWARE ID): B3-XXXX-XXXX-XXXX
   ```
2. O cliente copia esse código e envia para você no WhatsApp.
3. Você gera a chave de 15 dias rodando no seu terminal:
   ```powershell
   python gerar_licenca.py --hwid B3-XXXX-XXXX-XXXX --dias 15 --cliente "Nome do Cliente"
   ```
4. O script gera o arquivo `licenca.key`.
5. Você envia esse arquivo para o cliente e pede para ele colar dentro da pasta do programa.
6. Ao abrir o programa novamente, a licença estará ativa com contagem regressiva de 15 dias!

---

## 🖥️ PARTE 3: Como Executar o Assistente no Dia a Dia

Com o Profit Pro aberto e a transmissão DDE ativa, basta abrir o PowerShell na pasta e rodar:

* **Para operar Mini-Índice:**
  ```powershell
  python main.py run-dde --symbol WIN
  ```

* **Para operar Mini-Dólar:**
  ```powershell
  python main.py run-dde --symbol WDO
  ```

* **Para operar Ações VALE3:**
  ```powershell
  python main.py run-dde --symbol VALE3
  ```
