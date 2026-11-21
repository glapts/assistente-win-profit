"""
gerar_licenca.py
Painel do Criador para Geração de Licenças e Chaves de Teste (15 Dias / Definitiva).
Uso Exclusivo do Desenvolvedor / Administrador do Algoritmo.

Exemplos de uso no PowerShell:
  1. Ativar a própria máquina do criador (vitalícia):
     python gerar_licenca.py --ativar-este-pc

  2. Gerar licença de 15 dias para um cliente:
     python gerar_licenca.py --hwid B3-8F4A-91C2-77D0 --dias 15 --cliente "Nome do Cliente"

  3. Consultar o Hardware ID desta máquina:
     python gerar_licenca.py --meu-id

  4. Verificar os dados de uma licenca.key existente:
     python gerar_licenca.py --ver
"""

import sys
import os
import argparse

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from core.licenca import (
    obter_hardware_id,
    gerar_arquivo_licenca,
    carregar_e_validar_licenca
)


def main():
    parser = argparse.ArgumentParser(description="Gerador de Licenças Oficiais B3 — Assistente Quantitativo")
    parser.add_argument("--hwid", type=str, default=None, help="Hardware ID da máquina do cliente (ex: B3-XXXX-XXXX-XXXX)")
    parser.add_argument("--dias", type=int, default=15, help="Quantidade de dias de validade (padrão: 15 dias de teste)")
    parser.add_argument("--cliente", type=str, default="Cliente Trial", help="Nome ou identificação do cliente")
    parser.add_argument("--out", type=str, default="licenca.key", help="Caminho do arquivo de saída (padrão: licenca.key)")
    parser.add_argument("--ativar-este-pc", action="store_true", help="Gera licença definitiva e ativa a própria máquina do criador")
    parser.add_argument("--meu-id", action="store_true", help="Mostra o Hardware ID desta máquina")
    parser.add_argument("--ver", action="store_true", help="Inspeciona o arquivo licenca.key atual")

    args = parser.parse_args()

    meu_hwid = obter_hardware_id()

    if args.meu_id:
        print("\n" + "=" * 60)
        print("IDENTIFICADOR DESTA MÁQUINA (HARDWARE ID):")
        print(f"👉 \033[1;93m{meu_hwid}\033[0m")
        print("=" * 60 + "\n")
        return

    if args.ver:
        valido, status, dados = carregar_e_validar_licenca()
        print("\n" + "=" * 60)
        print("INSPEÇÃO DE LICENÇA ATUAL:")
        print("=" * 60)
        print(f"Status da Validação : {'VÁLIDA' if valido else 'INVÁLIDA / BLOQUEADA'}")
        print(f"Detalhes            : {status}")
        if dados:
            for k, v in dados.items():
                print(f" - {k:<15}: {v}")
        print("=" * 60 + "\n")
        return

    if args.ativar_este_pc:
        destino = os.path.join(PROJECT_DIR, "licenca.key")
        ok, msg = gerar_arquivo_licenca(
            hwid=meu_hwid,
            dias_validade=3650, # 10 anos
            nome_cliente="Administrador / Criador do Algoritmo",
            arquivo_saida=destino
        )
        print("\n" + "=" * 70)
        print("✅ ATIVAÇÃO DA MÁQUINA PRINCIPAL CONCLUÍDA")
        print("=" * 70)
        print(f"Hardware ID  : {meu_hwid}")
        print(f"Arquivo      : {destino}")
        print(f"Validade     : Vitalícia (10 anos)")
        print(f"Mensagem     : {msg}")
        print("=" * 70 + "\n")
        return

    if not args.hwid:
        print("\n[ERRO] É necessário informar o --hwid do cliente ou usar --ativar-este-pc.")
        print("Exemplo: python gerar_licenca.py --hwid B3-XXXX-XXXX-XXXX --dias 15 --cliente 'João Silva'\n")
        return

    # Gera a licença para o cliente
    caminho_out = args.out
    if not os.path.isabs(caminho_out):
        caminho_out = os.path.join(PROJECT_DIR, caminho_out)

    ok, msg = gerar_arquivo_licenca(
        hwid=args.hwid,
        dias_validade=args.dias,
        nome_cliente=args.cliente,
        arquivo_saida=caminho_out
    )

    if ok:
        print("\n" + "=" * 70)
        print(f"✅ LICENÇA DE {args.dias} DIAS GERADA COM SUCESSO!")
        print("=" * 70)
        print(f"Cliente      : {args.cliente}")
        print(f"Hardware ID  : {args.hwid.upper()}")
        print(f"Prazo        : {args.dias} dias a partir de hoje")
        print(f"Arquivo      : {caminho_out}")
        print("-" * 70)
        print(f"👉 COMO ENVIAR PARA O CLIENTE:")
        print(f"   Basta enviar o arquivo '{os.path.basename(caminho_out)}' para o cliente")
        print(f"   e pedir para ele colar dentro da pasta do algoritmo.")
        print("=" * 70 + "\n")
    else:
        print(f"\n[ERRO] Falha ao gerar licença: {msg}\n")


if __name__ == "__main__":
    main()
