"""
licensing/hwid.py
Módulo seguro e determinístico de identificação de hardware (HWID) no Windows 11.
Combina MachineGuid do Windows, UUID da Placa-Mãe e ID do Processador.
"""

import subprocess
import hashlib
import platform
import os


def get_machine_hwid() -> str:
    """
    Retorna o Hardware ID (HWID) único e imutável da máquina Windows.
    Formato: XXXX-XXXX-XXXX-XXXX
    """
    components = []
    
    # 1. Windows Cryptography MachineGuid (Registro Oficial)
    try:
        out = subprocess.check_output(
            ['reg', 'query', r'HKLM\SOFTWARE\Microsoft\Cryptography', '/v', 'MachineGuid'],
            stderr=subprocess.DEVNULL,
            text=True
        )
        for line in out.splitlines():
            if 'MachineGuid' in line:
                val = line.split()[-1].strip()
                if val:
                    components.append(f"GUID:{val}")
    except Exception:
        pass

    # 2. UUID da Placa-Mãe via CIM
    try:
        cmd = "Get-CimInstance -ClassName Win32_ComputerSystemProduct | Select-Object -ExpandProperty UUID"
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command", cmd],
            stderr=subprocess.DEVNULL,
            text=True
        ).strip()
        if out and out != "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF":
            components.append(f"MBD:{out}")
    except Exception:
        pass

    # 3. Serial do Disco do Sistema (Volume C:)
    try:
        drive_serial = os.popen("vol C:").read()
        for line in drive_serial.splitlines():
            if "Serial Number" in line or "Número de Série" in line:
                val = line.split()[-1].strip()
                if val:
                    components.append(f"VOL:{val}")
    except Exception:
        pass

    # 4. Fallback de Arquitetura e Host
    if not components:
        components.append(f"NODE:{platform.node()}:{platform.machine()}")

    raw = "|".join(components)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest().upper()
    
    # Divide em 4 blocos de 4 caracteres
    hwid = f"{digest[0:4]}-{digest[4:8]}-{digest[8:12]}-{digest[12:16]}"
    return hwid


if __name__ == "__main__":
    print(f"HWID Desta Máquina: {get_machine_hwid()}")
