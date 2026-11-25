"""
licensing/validator.py
Módulo de Validação e Ativação Criptográfica de Licença vinculada ao Hardware (HWID).
Impede que o programa seja copiado ou executado em outros computadores.
"""

import os
import json
import base64
import hmac
import hashlib
from datetime import datetime, date
from pathlib import Path
from typing import Tuple, Optional

from licensing.hwid import get_machine_hwid

# Chave mestra privada interna de assinatura do desenvolvedor (HMAC-SHA256)
_MASTER_SECRET = b"WIN_INSTITUCIONAL_B3_SECURE_KEY_@2026#QUANT_SMC_ALGO_SECRET_TOKEN"


def _get_license_path() -> Path:
    """Retorna o caminho seguro onde o arquivo de licença fica salvo."""
    appdata = os.getenv("APPDATA")
    if appdata:
        dir_path = Path(appdata) / "AssistenteWIN"
    else:
        dir_path = Path.home() / ".assistente_win"
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path / "license.key"


def create_license_key(hwid: str, client_name: str, expiration: str = "LIFETIME") -> str:
    """
    Gera uma chave de licença criptografada para o cliente.
    expiration: 'LIFETIME' ou formato 'AAAA-MM-DD' (ex: '2027-12-31')
    """
    payload = {
        "hwid": hwid.strip().upper(),
        "client": client_name.strip(),
        "exp": expiration.strip().upper(),
        "gen_at": date.today().isoformat()
    }
    raw_json = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8')
    b64_payload = base64.urlsafe_b64encode(raw_json).decode('ascii')
    
    # Assinatura HMAC-SHA256
    sig = hmac.new(_MASTER_SECRET, b64_payload.encode('ascii'), hashlib.sha256).hexdigest()[:16].upper()
    return f"WIN-LIC-{b64_payload}-{sig}"


def verify_license_key(key_str: str) -> Tuple[bool, str, Optional[dict]]:
    """
    Verifica se a chave de licença é íntegra, válida para a máquina atual e não expirada.
    Retorna: (is_valid, mensagem_diagnostico, payload_info)
    """
    key_str = key_str.strip()
    if not key_str.startswith("WIN-LIC-"):
        return False, "Formato de chave inválido.", None
    
    parts = key_str[len("WIN-LIC-"):].rsplit("-", 1)
    if len(parts) != 2:
        return False, "Estrutura de chave corrompida.", None
    
    b64_payload, signature = parts
    
    # 1. Verifica Assinatura HMAC
    expected_sig = hmac.new(_MASTER_SECRET, b64_payload.encode('ascii'), hashlib.sha256).hexdigest()[:16].upper()
    if not hmac.compare_digest(signature.upper(), expected_sig):
        return False, "Assinatura digital inválida (chave falsificada ou adulterada).", None
    
    # 2. Decodifica Payload
    try:
        raw_json = base64.urlsafe_b64decode(b64_payload.encode('ascii')).decode('utf-8')
        payload = json.loads(raw_json)
    except Exception:
        return False, "Falha ao decodificar dados da licença.", None
    
    lic_hwid = payload.get("hwid", "")
    current_hwid = get_machine_hwid()
    
    # 3. Trava de Hardware (HWID)
    if lic_hwid != current_hwid:
        return False, (
            f"ESTA LICENÇA PERTENCE A OUTRO COMPUTADOR!\n"
            f"   HWID da Licença : {lic_hwid}\n"
            f"   HWID Deste PC   : {current_hwid}\n"
            f"   Proibido compartilhamento ou execução não autorizada."
        ), payload

    # 4. Verifica Data de Expiração
    exp_str = payload.get("exp", "LIFETIME")
    if exp_str != "LIFETIME":
        try:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            if date.today() > exp_date:
                return False, f"Licença expirada em {exp_date.strftime('%d/%m/%Y')}.", payload
        except ValueError:
            return False, "Formato de expiração corrompido.", payload
            
    return True, "Licença válida e ativa.", payload


def check_and_enforce_license() -> bool:
    """
    Valida a licença no início do programa. Se não houver ou for inválida,
    solicita ativação imediata via console interativo.
    Retorna True se autorizado; se cancelado ou inválido, encerra.
    """
    lic_file = _get_license_path()
    current_hwid = get_machine_hwid()
    
    # Tenta ler licença existente
    if lic_file.exists():
        try:
            saved_key = lic_file.read_text(encoding="utf-8").strip()
            ok, msg, info = verify_license_key(saved_key)
            if ok:
                exp_display = "VITALÍCIA" if info.get('exp') == 'LIFETIME' else info.get('exp')
                print(f"[LICENÇA OK] Registrado para: {info.get('client')} | Validade: {exp_display}")
                return True
        except Exception:
            pass

    # Tela de Ativação
    print("\n" + "=" * 72)
    print("      ASSISTENTE DE TRADING INSTITUCIONAL WIN — ATIVAÇÃO DE LICENÇA      ")
    print("=" * 72)
    print("STATUS: Licença não encontrada ou não autorizada para este computador.\n")
    print(f"SEU CÓDIGO DE IDENTIFICAÇÃO DESTE COMPUTADOR (HWID):")
    print(f"  >>>  {current_hwid}  <<<\n")
    print("INSTRUÇÕES:")
    print("1. Envie o código acima para o desenvolvedor para receber sua chave.")
    print("2. Cole a chave de ativação no campo abaixo e pressione Enter.")
    print("=" * 72 + "\n")
    
    while True:
        try:
            key_input = input("Insira sua Chave de Ativação (ou digite 'sair'): ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nAtivação cancelada pelo usuário.")
            return False
            
        if key_input.lower() in ("sair", "exit", "q"):
            print("Operação encerrada.")
            return False
            
        if not key_input:
            continue
            
        ok, msg, info = verify_license_key(key_input)
        if ok:
            lic_file.write_text(key_input, encoding="utf-8")
            print("\n" + "*" * 72)
            print("  SUCESSO! O SOFTWARE FOI ATIVADO COM SUCESSO NESTE COMPUTADOR!  ")
            print(f"  Titular  : {info.get('client')}")
            print(f"  Validade : {'VITALÍCIA' if info.get('exp') == 'LIFETIME' else info.get('exp')}")
            print("*" * 72 + "\n")
            return True
        else:
            print(f"\n[ERRO] {msg}")
            print("Verifique se copiou a chave completa e tente novamente.\n")
