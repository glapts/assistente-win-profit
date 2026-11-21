"""
gerar_manual_pdf.py
Gera o Manual Oficial em PDF com imagens do passo a passo de instalação e configuração do Profit Pro.
Diagramação profissional em 4 páginas exatas, sem páginas vazias ou quebras acidentais.
"""

import os
import sys
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table, TableStyle, PageBreak, KeepTogether, HRFlowable
)
from reportlab.pdfgen import canvas

# Caminhos dos arquivos
UPLOADED_DIR = r"C:\Users\glaci\.gemini\antigravity-cli\brain\db50b63a-6ef9-43cf-a0ab-3fb7bb1b90f2\.user_uploaded"
OUTPUT_DIR = r"C:\Users\glaci\OneDrive\Desktop\PACOTE_CLIENTE_TRIAL"
PDF_FILENAME = "MANUAL_DE_INSTALACAO_PROFIT.pdf"
PDF_PATH = os.path.join(OUTPUT_DIR, PDF_FILENAME)

IMG_0 = os.path.join(UPLOADED_DIR, "uploaded_media_0_1794615944569.png") # Menu Cotacoes
IMG_1 = os.path.join(UPLOADED_DIR, "uploaded_media_1_1794615944569.png") # Ativos
IMG_2 = os.path.join(UPLOADED_DIR, "uploaded_media_2_1794615944569.png") # Atributos 1
IMG_3 = os.path.join(UPLOADED_DIR, "uploaded_media_3_1794615944569.png") # Atributos 2
IMG_4 = os.path.join(UPLOADED_DIR, "uploaded_media_4_1794615944569.png") # Configuracoes
IMG_5 = os.path.join(UPLOADED_DIR, "uploaded_media_5_1794615944569.png") # Pasta Windows Explorer


class NumberedCanvas(canvas.Canvas):
    """Canvas com rodapé numerado oficial e cabeçalho em todas as páginas."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        
        # Cabeçalho a partir da página 2
        if self._pageNumber > 1:
            self.drawString(36, 810, "Assistente Quantitativo B3 — Manual Oficial de Instalação e Configuração")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(36, 804, 559, 804)
        
        # Rodapé em todas as páginas
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.5)
        self.line(36, 38, 559, 38)
        
        self.drawString(36, 26, "Uso Exclusivo e Restrito — Período Oficial de Teste (15 Dias) | Nelogica Profit Pro")
        self.drawRightString(559, 26, f"Página {self._pageNumber} de {page_count}")
        self.restoreState()


def criar_manual():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    doc = SimpleDocTemplate(
        PDF_PATH,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=38,
        bottomMargin=46
    )

    styles = getSampleStyleSheet()
    
    # Cores Oficiais
    c_primary = colors.HexColor("#0F172A")   # Azul Marinho Grafite
    c_blue = colors.HexColor("#0284C7")      # Azul Royal
    c_text = colors.HexColor("#334155")      # Cinza Texto

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=c_primary,
        alignment=1,
        spaceAfter=4
    )

    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=13,
        textColor=c_blue,
        alignment=1,
        spaceAfter=10
    )

    h1_style = ParagraphStyle(
        'SectionH1',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=12,
        leading=15,
        textColor=c_primary,
        spaceBefore=8,
        spaceAfter=4
    )

    h2_style = ParagraphStyle(
        'SectionH2',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10.5,
        leading=14,
        textColor=c_blue,
        spaceBefore=6,
        spaceAfter=3
    )

    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.8,
        leading=12.5,
        textColor=c_text,
        spaceAfter=4
    )

    body_bold = ParagraphStyle(
        'BodyBold',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8.8,
        leading=12.5,
        textColor=c_primary
    )

    tip_style = ParagraphStyle(
        'TipText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#1E293B")
    )

    caption_style = ParagraphStyle(
        'ImageCaption',
        parent=styles['Normal'],
        fontName='Helvetica-Oblique',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#64748B"),
        alignment=1,
        spaceBefore=2,
        spaceAfter=6
    )

    elements = []

    # =========================================================================
    # PÁGINA 1: CAPA, ESTRUTURA DOS ARQUIVOS E ATIVAÇÃO DA LICENÇA (15 DIAS)
    # =========================================================================
    elements.append(Paragraph("MANUAL DE INSTALAÇÃO E CONFIGURAÇÃO", title_style))
    elements.append(Paragraph("Assistente Quantitativo B3 — Nelogica Profit Pro (WIN, WDO e VALE3)", subtitle_style))
    elements.append(HRFlowable(width="100%", thickness=1.2, color=c_blue, spaceBefore=0, spaceAfter=8))

    box_intro_data = [[
        Paragraph(
            "<b>Bem-vindo ao período de avaliação oficial de 15 dias!</b><br/>"
            "Este assistente monitora o mercado da B3 em tempo real, integrando "
            "<b>Smart Money Concepts (SMC)</b> e <b>Tape Reading Institucional</b>. "
            "O programa é 100% autônomo e não requer instalação de Python (executável binário nativo .exe). "
            "Siga os passos a seguir para ativar sua licença e configurar o Profit Pro.",
            tip_style
        )
    ]]
    box_intro = Table(box_intro_data, colWidths=[523])
    box_intro.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#EFF6FF")),
        ('BORDER', (0,0), (-1,-1), 1, colors.HexColor("#BFDBFE")),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(box_intro)
    elements.append(Spacer(1, 6))

    # ETAPA 1: O QUE VEM NA PASTA
    elements.append(Paragraph("1. Extração dos Arquivos e Estrutura da Pasta", h1_style))
    elements.append(Paragraph(
        "Descompacte o arquivo <b>PACOTE_CLIENTE_TRIAL.zip</b> na sua Área de Trabalho ou pasta de sua escolha. "
        "Você encontrará o executável <b>AssistenteB3.exe</b> e os atalhos de inicialização rápida:",
        body_style
    ))

    # Imagem da pasta (IMG_5)
    if os.path.exists(IMG_5):
        im5 = Image(IMG_5, width=480, height=209)
        t_im5 = Table([[im5]], colWidths=[523])
        t_im5.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
        elements.append(t_im5)
        elements.append(Paragraph("Figura 1: Pasta descompactada com o executável AssistenteB3.exe e atalhos de inicialização", caption_style))

    # ETAPA 2: ATIVAÇÃO DE 15 DIAS
    elements.append(Paragraph("2. Ativação da Licença de Teste (15 Dias)", h1_style))
    elements.append(Paragraph(
        "O sistema possui amarração segura por Hardware ID (placa-mãe do seu computador). Para liberar seu acesso:<br/>"
        "• <b>Passo A:</b> Na pasta, dê 2 cliques no arquivo <b>EXECUTAR_DIAGNOSTICO.bat</b>.<br/>"
        "• <b>Passo B:</b> A tela exibirá seu código único: <code>[>>>] HARDWARE ID: B3-XXXX-XXXX-XXXX</code>.<br/>"
        "• <b>Passo C:</b> Copie esse código e envie para o suporte via WhatsApp.<br/>"
        "• <b>Passo D:</b> Você receberá o arquivo <b>licenca.key</b>. Basta colá-lo dentro desta mesma pasta. Seu acesso estará liberado imediatamente!",
        body_style
    ))

    elements.append(PageBreak())

    # =========================================================================
    # PÁGINA 2: CONFIGURAÇÃO DO PROFIT PRO (MENU DDE + ABA ATIVOS)
    # =========================================================================
    elements.append(Paragraph("3. Configuração do Nelogica Profit Pro (Transmissão DDE)", h1_style))
    elements.append(Paragraph(
        "Para que o assistente analise o fluxo de agressão e cotações em tempo real, o Profit Pro deve exportar "
        "os dados via tecnologia DDE nativa do Windows. Siga os passos visuais:",
        body_style
    ))

    # Passo 3.1: Menu Cotacoes
    elements.append(Paragraph("Passo 3.1 — Acessar a Janela de Exportação DDE", h2_style))
    elements.append(Paragraph(
        "No menu superior principal do seu Profit Pro, clique em <b>Cotações</b> e selecione a opção "
        "<b>Exportar em Tempo Real (RTD/DDE)</b> conforme destacado na Figura 2:",
        body_style
    ))

    if os.path.exists(IMG_0):
        im0 = Image(IMG_0, width=170, height=182)
        t_im0 = Table([[im0]], colWidths=[523])
        t_im0.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
        elements.append(t_im0)
        elements.append(Paragraph("Figura 2: Menu superior: Cotações > Exportar em Tempo Real (RTD/DDE)", caption_style))

    # Passo 3.2: Aba Ativos
    elements.append(Paragraph("Passo 3.2 — Selecionar os Ativos na Grade", h2_style))
    elements.append(Paragraph(
        "Na janela aberta, clique na aba <b>Ativos</b>:<br/>"
        "1. No campo de busca à esquerda, adicione os ativos: <b>WINZ26</b> (Mini-Índice), <b>WDOZ26</b> (Mini-Dólar) e <b>VALE3</b>.<br/>"
        "2. No rodapé inferior esquerdo, <b>certifique-se de marcar a opção circular DDE</b> (círculo azul).",
        body_style
    ))

    if os.path.exists(IMG_1):
        im1 = Image(IMG_1, width=420, height=288)
        t_im1 = Table([[im1]], colWidths=[523])
        t_im1.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
        elements.append(t_im1)
        elements.append(Paragraph("Figura 3: Aba Ativos — Inserção de VALE3, WDOZ26, WINZ26 e seleção da opção DDE", caption_style))

    elements.append(PageBreak())

    # =========================================================================
    # PÁGINA 3: CONFIGURAÇÃO DE ATRIBUTOS (PREÇO + FLUXO LADO A LADO)
    # =========================================================================
    elements.append(Paragraph("Passo 3.3 — Seleção Obrigatória de Atributos", h1_style))
    elements.append(Paragraph(
        "Clique na aba <b>Atributos</b>. Marque exatamente as caixas indicadas abaixo. "
        "Esses atributos fornecem os dados de preço, volume e fluxo de agressão (Tape Reading):",
        body_style
    ))

    # Montar tabela com IMG_2 e IMG_3 lado a lado
    if os.path.exists(IMG_2) and os.path.exists(IMG_3):
        im2 = Image(IMG_2, width=254, height=176)
        im3 = Image(IMG_3, width=254, height=176)
        
        t_attrs_imgs = Table([
            [im2, im3],
            [
                Paragraph("<b>Figura 4:</b> Preços e Volume:<br/>• Último, Abertura, Máximo, Mínimo e Negócios", caption_style),
                Paragraph("<b>Figura 5:</b> Fluxo e Tape Reading:<br/>• Agr. Compra e Agr. Venda (Essenciais)", caption_style)
            ]
        ], colWidths=[260, 260])
        t_attrs_imgs.setStyle(TableStyle([
            ('ALIGN', (0,0), (-1,-1), 'CENTER'),
            ('VALIGN', (0,0), (-1,-1), 'TOP'),
            ('BOTTOMPADDING', (0,0), (-1,-1), 2),
            ('TOPPADDING', (0,0), (-1,-1), 2),
        ]))
        elements.append(t_attrs_imgs)

    elements.append(Spacer(1, 6))

    # Tabela descritiva dos atributos
    tab_desc_data = [
        [
            Paragraph("<b>Grupo</b>", body_bold),
            Paragraph("<b>Atributos Obrigatórios</b>", body_bold),
            Paragraph("<b>Função no Assistente</b>", body_bold)
        ],
        [
            Paragraph("<b>Preço</b>", body_style),
            Paragraph("Último, Abertura, Máximo, Mínimo", body_style),
            Paragraph("Mapeia níveis estruturais SMC, pivôs, máximas, mínimas e Fair Value Gaps (FVG).", body_style)
        ],
        [
            Paragraph("<b>Volume</b>", body_style),
            Paragraph("Negócios", body_style),
            Paragraph("Quantifica a atividade geral de contratos por minuto.", body_style)
        ],
        [
            Paragraph("<b>Tape Reading</b>", body_style),
            Paragraph("Agr. Compra e Agr. Venda", body_style),
            Paragraph("Calcula o saldo de Delta institucional, velocidade e absorção no topo/fundo.", body_style)
        ]
    ]
    t_desc = Table(tab_desc_data, colWidths=[80, 180, 263])
    t_desc.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#F1F5F9")),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#CBD5E1")),
        ('PADDING', (0,0), (-1,-1), 5),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(t_desc)
    elements.append(Spacer(1, 8))

    box_aviso_data = [[
        Paragraph(
            "<b>ATENÇÃO:</b> No rodapé da aba Atributos, certifique-se de que a opção circular "
            "<b>DDE</b> permaneça selecionada.",
            tip_style
        )
    ]]
    box_aviso = Table(box_aviso_data, colWidths=[523])
    box_aviso.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#FEF3C7")),
        ('BORDER', (0,0), (-1,-1), 1, colors.HexColor("#FCD34D")),
        ('PADDING', (0,0), (-1,-1), 5),
    ]))
    elements.append(box_aviso)

    elements.append(PageBreak())

    # =========================================================================
    # PÁGINA 4: ABA CONFIGURAÇÕES E EXECUÇÃO COM 1 CLIQUE NO SUPERDOM
    # =========================================================================
    elements.append(Paragraph("Passo 3.4 — Parâmetros de Configuração e Ativação", h1_style))
    elements.append(Paragraph(
        "Acesse a aba <b>Configurações</b> no topo da janela e ajuste exatamente como mostrado na Figura 6:<br/>"
        "• <b>Tipo:</b> Marcar <b>DDE</b> | <b>Exportar:</b> Marcar <b>Microsoft Excel</b><br/>"
        "• <b>Colunas:</b> Marcar <b>Copiar o título de cada coluna</b> | <b>Valores:</b> Marcar <b>Exibir valores do pregão anterior</b><br/>"
        "• <b>Transferência de Dados:</b> Marcar a caixa <b>☑️ Ativar transferência de dados</b> (Obrigatório!)<br/>"
        "• Clique no botão azul <b>OK</b> no canto inferior direito para salvar e fechar a janela.",
        body_style
    ))

    if os.path.exists(IMG_4):
        im4 = Image(IMG_4, width=390, height=272)
        t_im4 = Table([[im4]], colWidths=[523])
        t_im4.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
        elements.append(t_im4)
        elements.append(Paragraph("Figura 6: Aba Configurações — Ativação formal da transferência de dados DDE", caption_style))

    # EXECUÇÃO DO DIA A DIA
    elements.append(Paragraph("4. Como Operar no Dia a Dia com 1 Clique", h1_style))
    elements.append(Paragraph(
        "Com o Profit Pro aberto e a transmissão DDE ativa, basta dar dois cliques no atalho desejado:<br/>"
        "• <b>Mini-Índice:</b> Dê 2 cliques em <b>INICIAR_MINI_INDICE.bat</b><br/>"
        "• <b>Mini-Dólar:</b> Dê 2 cliques em <b>INICIAR_MINI_DOLAR.bat</b><br/>"
        "• <b>Simulação com Áudio:</b> Dê 2 cliques em <b>SIMULAR_COMPRA_11h30.bat</b> ou <b>SIMULAR_VENDA_11h38.bat</b>.",
        body_style
    ))

    # Box de Destaque Final
    box_final_data = [[
        Paragraph(
            "<b>COMO EXECUTAR NO SUPERDOM COM 1 CLIQUE:</b><br/>"
            "Quando o assistente confirmar uma operação, ele emitirá <b>5 apitos sonoros imediatos</b> e "
            "exibirá no topo do terminal um card colorido (Azul para Compra / Vermelho para Venda) informando o "
            "preço exato do tick. Você não precisa digitar nada: basta dar <b>1 clique na coluna do SuperDOM</b> "
            "com a estratégia OCO configurada (Stop de 50 ticks / Alvo de 80 ticks). Boas operações e excelentes lucros!",
            tip_style
        )
    ]]
    box_final = Table(box_final_data, colWidths=[523])
    box_final.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,-1), colors.HexColor("#F0FDF4")),
        ('BORDER', (0,0), (-1,-1), 1, colors.HexColor("#BBF7D0")),
        ('PADDING', (0,0), (-1,-1), 6),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
    ]))
    elements.append(box_final)

    doc.build(elements, canvasmaker=NumberedCanvas)
    print(f"Manual em PDF gerado com sucesso em: {PDF_PATH}")
    return PDF_PATH


if __name__ == "__main__":
    criar_manual()
