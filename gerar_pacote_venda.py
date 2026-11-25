"""
gerar_pacote_venda.py
Script que agrupa o executável compilado (.exe), instalador automatizado e manual oficial em PDF (42 páginas)
em uma pasta limpa e gera um arquivo .ZIP pronto para entrega comercial ao comprador.
"""

import os
import shutil
import zipfile
from pathlib import Path

BASE_DIR = Path(__file__).parent
DIST_EXE = BASE_DIR / "dist" / "AssistenteWIN.exe"
TEMPLATE_DIR = BASE_DIR / "installer_template"
PACKAGE_DIR = BASE_DIR / "PACOTE_PARA_O_CLIENTE"
ZIP_OUTPUT = BASE_DIR / "Instalador_AssistenteWIN_v1.0.zip"


def create_package():
    print("=" * 70)
    print("GERANDO PACOTE COMERCIAL DE INSTALAÇÃO PARA VENDA — CENÁRIO 3")
    print("=" * 70)
    
    if not DIST_EXE.exists():
        print(f"[ERRO] O executável compilado não foi encontrado em: {DIST_EXE}")
        print("Execute primeiro: python build_exe.py")
        return False
        
    # Limpa pasta anterior
    if PACKAGE_DIR.exists():
        shutil.rmtree(PACKAGE_DIR)
    PACKAGE_DIR.mkdir(parents=True, exist_ok=True)
    
    # Copia arquivos necessários para o cliente
    print("1. Copiando AssistenteWIN.exe compilado (Cenário 3)...")
    shutil.copy2(DIST_EXE, PACKAGE_DIR / "AssistenteWIN.exe")
    
    print("2. Copiando instalador automatizado Windows 11 e manuais...")
    shutil.copy2(TEMPLATE_DIR / "instalar.bat", PACKAGE_DIR / "instalar.bat")
    shutil.copy2(TEMPLATE_DIR / "instalar.ps1", PACKAGE_DIR / "instalar.ps1")
    shutil.copy2(TEMPLATE_DIR / "LEIA-ME_PRIMEIROS_PASSOS.txt", PACKAGE_DIR / "LEIA-ME_PRIMEIROS_PASSOS.txt")
    
    pdf_source = TEMPLATE_DIR / "Guia_Instalacao_Profit_RTD_DDE_ultimo.pdf"
    if pdf_source.exists():
        print("3. Incluindo Guia Oficial de Instalação e Estatísticas em PDF...")
        shutil.copy2(pdf_source, PACKAGE_DIR / "Guia_Instalacao_Profit_RTD_DDE_ultimo.pdf")
    
    # Compacta em ZIP
    print("4. Gerando arquivo ZIP final para envio ao cliente...")
    if ZIP_OUTPUT.exists():
        ZIP_OUTPUT.unlink()
        
    with zipfile.ZipFile(ZIP_OUTPUT, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for file in PACKAGE_DIR.iterdir():
            zipf.write(file, arcname=file.name)
            
    print("\n" + "=" * 70)
    print("PACOTE COMERCIAL GERADO COM SUCESSO!")
    print(f"Pasta do Pacote  : {PACKAGE_DIR}")
    print(f"Arquivo ZIP Final: {ZIP_OUTPUT}")
    print(f"Tamanho do ZIP   : {ZIP_OUTPUT.stat().st_size / (1024*1024):.2f} MB")
    print("=" * 70)
    print("Você pode enviar esse arquivo ZIP diretamente para o comprador!")
    return True


if __name__ == "__main__":
    create_package()
