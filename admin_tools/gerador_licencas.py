"""
admin_tools/gerador_licencas.py
FERRAMENTA EXCLUSIVA DO DESENVOLVEDOR / VENDEDOR
Gera chaves de licença seguras amarradas ao HWID do cliente.
NUNCA envie este arquivo para clientes!
"""

import sys
import os
from pathlib import Path

# Adiciona raiz do projeto comercial ao path para importar licensing
sys.path.insert(0, str(Path(__file__).parent.parent))

from licensing.validator import create_license_key
from licensing.hwid import get_machine_hwid


def main():
    print("=" * 72)
    print("   PAINEL DO VENDEDOR — GERADOR DE CHAVES DE LICENÇA (HWID LOCK)   ")
    print("=" * 72)
    print("Use esta ferramenta para emitir licenças para clientes que compraram seu robô.\n")
    
    my_hwid = get_machine_hwid()
    print(f"HWID da sua própria máquina (para testes locais): {my_hwid}\n")
    
    client_name = input("1. Nome do Cliente: ").strip()
    if not client_name:
        client_name = "Cliente Autorizado"
        
    hwid = input(f"2. HWID do Computador do Cliente (ex: {my_hwid}): ").strip()
    if not hwid:
        print("[ERRO] O HWID do cliente é obrigatório!")
        return
        
    print("\n3. Escolha o tipo de licença:")
    print("   [1] Vitalícia (Recomendado para venda de software permanente)")
    print("   [2] 1 Mês (30 dias)")
    print("   [3] 1 Ano (365 dias)")
    print("   [4] Data personalizada (AAAA-MM-DD)")
    choice = input("Opção [1]: ").strip() or "1"
    
    from datetime import date, timedelta
    
    if choice == "1":
        expiration = "LIFETIME"
    elif choice == "2":
        expiration = (date.today() + timedelta(days=30)).isoformat()
    elif choice == "3":
        expiration = (date.today() + timedelta(days=365)).isoformat()
    elif choice == "4":
        expiration = input("Digite a data de expiração (AAAA-MM-DD): ").strip()
    else:
        expiration = "LIFETIME"
        
    license_key = create_license_key(hwid=hwid, client_name=client_name, expiration=expiration)
    
    print("\n" + "=" * 72)
    print("   LICENÇA GERADA COM SUCESSO! COPIE E ENVIE AO SEU CLIENTE:")
    print("=" * 72)
    print(f"Cliente   : {client_name}")
    print(f"HWID Alvo : {hwid.upper()}")
    print(f"Validade  : {expiration}")
    print("-" * 72)
    print(f"CHAVE DE ATIVAÇÃO:\n\n{license_key}\n")
    print("=" * 72)
    print("Instrua o cliente a abrir o programa e colar essa chave quando for solicitada.")
    print("Se ele tentar usar essa chave em outro computador, o programa BLOQUEARÁ automaticamente.")
    print("=" * 72 + "\n")


if __name__ == "__main__":
    main()
