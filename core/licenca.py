"""
core/licenca.py
Módulo de Proteção e Licenciamento Criptografado (Opção A - Offline por Hardware ID)
Garante que o algoritmo só execute em computadores previamente autorizados
e expira automaticamente após o período estipulado (ex: 15 dias).

Não altera nenhuma lógica, fórmula ou cálculo do motor de análise.
"""

import os
import sys
import hmac
import hashlib
import json
import base64
import subprocess
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple, Dict, Any

# Forçar UTF-8 seguro no console Windows para evitar UnicodeEncodeError em cp1252
try:
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    if hasattr(sys.stderr, 'reconfigure'):
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass
# ATENÇÃO: Essa chave é privada e exclusiva do criador do algoritmo.
_CHAVE_MESTRA = b"Antigravity_B3_Algo_Secret_Key_2026_QuantMaster_99182746"


def obter_hardware_id() -> str:
    """
    Obtém o Identificador Único do Computador (HWID) de forma persistente.
    Usa o UUID da placa-mãe/BIOS do Windows ou fallback estável.
    """
    raw_id = ""
    
    # 1. Tentar via PowerShell (Get-CimInstance Win32_ComputerSystemProduct)
    try:
        cmd = ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_ComputerSystemProduct).UUID"]
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3)
        res = proc.stdout.strip()
        if res and len(res) > 10 and "FFFFFFFF" not in res.upper():
            raw_id = res
    except Exception:
        pass

    # 2. Se falhar, tentar via WMIC (UUID da máquina)
    if not raw_id:
        try:
            proc = subprocess.run(["wmic", "csproduct", "get", "uuid"], capture_output=True, text=True, timeout=3)
            lines = [l.strip() for l in proc.stdout.splitlines() if l.strip() and "UUID" not in l.upper()]
            if lines and len(lines[0]) > 10:
                raw_id = lines[0]
        except Exception:
            pass

    # 3. Fallback estável baseado em nome do computador + UUID de rede
    if not raw_id:
        import platform, uuid
        raw_id = f"{platform.node()}-{uuid.getnode()}"

    # Gera um hash SHA-256 curto e legível: B3-XXXX-XXXX-XXXX
    h = hashlib.sha256(raw_id.encode("utf-8")).hexdigest().upper()
    return f"B3-{h[:4]}-{h[4:8]}-{h[8:12]}"


def assinar_payload(payload_bytes: bytes) -> str:
    """Gera assinatura HMAC-SHA256 do payload usando a chave mestra."""
    return hmac.new(_CHAVE_MESTRA, payload_bytes, hashlib.sha256).hexdigest()


def gerar_arquivo_licenca(hwid: str, dias_validade: int, nome_cliente: str = "Cliente Trial", arquivo_saida: str = "licenca.key") -> Tuple[bool, str]:
    """
    Gera um arquivo de licença criptografada com validade de N dias para um Hardware ID específico.
    """
    agora = datetime.now()
    expiracao = agora + timedelta(days=dias_validade)
    
    dados = {
        "hwid": hwid.strip().upper(),
        "cliente": nome_cliente,
        "emissao": agora.strftime("%Y-%m-%d %H:%M:%S"),
        "expiracao": expiracao.strftime("%Y-%m-%d %H:%M:%S"),
        "dias_total": dias_validade,
        "tipo": "TRIAL_15_DIAS" if dias_validade <= 15 else "LICENCA_DEFINITIVA"
    }
    
    raw_json = json.dumps(dados, sort_keys=True).encode("utf-8")
    assinatura = assinar_payload(raw_json)
    
    envelope = {
        "payload": base64.b64encode(raw_json).decode("utf-8"),
        "sig": assinatura
    }
    
    conteudo_final = base64.b64encode(json.dumps(envelope).encode("utf-8")).decode("utf-8")
    
    try:
        with open(arquivo_saida, "w", encoding="utf-8") as f:
            f.write(conteudo_final)
        return True, f"Licença gerada com sucesso! Válida até {expiracao.strftime('%d/%m/%Y às %H:%M:%S')} para o HWID {hwid}."
    except Exception as e:
        return False, f"Erro ao gravar arquivo de licença: {e}"


def obter_caminhos_licenca() -> list:
    """Retorna os locais prováveis onde o arquivo licenca.key pode estar."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    exe_dir = os.path.dirname(sys.executable) if getattr(sys, 'frozen', False) else None
    
    paths = []
    if exe_dir:
        paths.extend([
            os.path.join(exe_dir, "licenca.key"),
            os.path.join(exe_dir, "license.key"),
            os.path.join(exe_dir, "data", "licenca.key")
        ])
    paths.extend([
        os.path.join(base_dir, "licenca.key"),
        os.path.join(base_dir, "license.key"),
        os.path.join(base_dir, "data", "licenca.key"),
        os.path.join(os.getcwd(), "licenca.key")
    ])
    return paths


def carregar_e_validar_licenca() -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Lê o arquivo de licença local e valida criptografia, Hardware ID e data de expiração.
    """
    hwid_atual = obter_hardware_id()
    arquivo_encontrado = None
    
    for caminho in obter_caminhos_licenca():
        if os.path.exists(caminho):
            arquivo_encontrado = caminho
            break
            
    if not arquivo_encontrado:
        return False, f"ARQUIVO_INEXISTENTE|{hwid_atual}", None

    try:
        with open(arquivo_encontrado, "r", encoding="utf-8") as f:
            conteudo = f.read().strip()
            
        envelope = json.loads(base64.b64decode(conteudo.encode("utf-8")).decode("utf-8"))
        raw_json = base64.b64decode(envelope["payload"].encode("utf-8"))
        sig_esperada = assinar_payload(raw_json)
        
        # 1. Checagem de Autenticidade Criptográfica (Impedir adulteração)
        if not hmac.compare_digest(envelope["sig"], sig_esperada):
            return False, f"LICENCA_ADULTERADA|{hwid_atual}", None
            
        dados = json.loads(raw_json.decode("utf-8"))
        
        # 2. Checagem de Hardware ID (Impedir cópia para outro computador)
        if dados.get("hwid", "").upper() != hwid_atual:
            return False, f"HWID_INCOMPATIVEL|{hwid_atual}|{dados.get('hwid')}", dados

        # 3. Checagem de Expiração
        data_exp = datetime.strptime(dados["expiracao"], "%Y-%m-%d %H:%M:%S")
        agora = datetime.now()
        
        if agora > data_exp:
            return False, f"LICENCA_EXPIRADA|{hwid_atual}|{dados['expiracao']}", dados
            
        dias_restantes = (data_exp - agora).days
        horas_restantes = int((data_exp - agora).seconds / 3600)
        
        return True, f"OK|{dias_restantes} dias e {horas_restantes}h restantes|{dados.get('cliente')}", dados
        
    except Exception as e:
        return False, f"LICENCA_CORROMPIDA|{hwid_atual}|{str(e)}", None


def verificar_licenca_ou_encerrar():
    """
    Ponto de entrada obrigatório na inicialização do assistente.
    Se a licença for válida, continua a execução normal.
    Se inválida ou expirada, exibe card informativo no terminal e encerra.
    """
    valido, status, dados = carregar_e_validar_licenca()
    
    if valido:
        partes = status.split("|")
        tempo_str = partes[1] if len(partes) > 1 else ""
        cliente_str = partes[2] if len(partes) > 2 else ""
        print(f"\033[1;32m[LICENÇA ATIVA]\033[0m Acesso autorizado para \033[1m{cliente_str}\033[0m | Validade: \033[1;33m{tempo_str}\033[0m")
        return True

    # Tratamento de Bloqueios
    partes = status.split("|")
    motivo = partes[0]
    hwid = partes[1] if len(partes) > 1 else obter_hardware_id()
    
    print("\n" + "=" * 76)
    if motivo == "ARQUIVO_INEXISTENTE":
        print("\033[1;43m\033[1;30m [!] SISTEMA BLOQUEADO -- LICENCA DE TESTES NAO ENCONTRADA [!] \033[0m")
        print("=" * 76)
        print("Para liberar o seu acesso de teste de 15 dias, voce precisa de uma chave ativa.")
        print(f"\n[>>>] \033[1;36mSEU CODIGO DE IDENTIFICACAO (HARDWARE ID):\033[0m \033[1;93m{hwid}\033[0m")
        print("\nCopie o codigo acima e envie para o suporte para receber seu arquivo 'licenca.key'.")
        print("Apos receber o arquivo, basta coloca-lo na mesma pasta deste programa e reiniciar.")
        
    elif motivo == "LICENCA_EXPIRADA":
        data_fim = partes[2] if len(partes) > 2 else "15 dias"
        print("\033[1;41m\033[1;37m [X] SEU PERIODO DE TESTE EXPIROU (15 DIAS ESGOTADOS) [X] \033[0m")
        print("=" * 76)
        print(f"O seu periodo de testes foi encerrado em: \033[1;31m{data_fim}\033[0m.")
        print("Esperamos que o assistente tenha gerado excelentes resultados operacionais!")
        print(f"\n[>>>] \033[1;36mSEU CODIGO DE IDENTIFICACAO:\033[0m \033[1;93m{hwid}\033[0m")
        print("\nPara adquirir a licenca definitiva ou renovar seu plano, fale com o suporte.")

    elif motivo == "HWID_INCOMPATIVEL":
        print("\033[1;41m\033[1;37m [X] ERRO DE LICENCA -- MAQUINA NAO AUTORIZADA [X] \033[0m")
        print("=" * 76)
        print("Este arquivo de licenca foi gerado para outro computador e nao pode ser transferido.")
        print(f"\n[>>>] \033[1;36mCODIGO DESTA MAQUINA:\033[0m \033[1;93m{hwid}\033[0m")
        print("Solicite uma chave valida para o seu computador com o administrador.")
        
    else:
        print("\033[1;41m\033[1;37m [X] FALHA DE VALIDACAO DE LICENCA [X] \033[0m")
        print("=" * 76)
        print("O arquivo de licenca esta invalido ou corrompido.")
        print(f"Codigo da sua maquina: {hwid}")

    print("=" * 76 + "\n")
    sys.exit(1)
