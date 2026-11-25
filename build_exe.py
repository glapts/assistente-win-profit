"""
build_exe.py
Script de compilação em executável binário autônomo (.exe) para Windows 11.
Empacota o código em binário nativo, ocultando o código-fonte (.py) e as regras matemáticas do SMC (Cenário 3 Oficial).
"""

import os
import subprocess
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent


def build():
    print("=" * 70)
    print("COMPILANDO ASSISTENTE WIN EM EXECUTÁVEL (.EXE) SEGURO — CENÁRIO 3")
    print("=" * 70)
    
    dist_dir = BASE_DIR / "dist"
    build_dir = BASE_DIR / "build"
    spec_file = BASE_DIR / "AssistenteWIN.spec"
    
    # Limpa compilações anteriores
    if dist_dir.exists():
        shutil.rmtree(dist_dir)
    if build_dir.exists():
        shutil.rmtree(build_dir)
    if spec_file.exists():
        spec_file.unlink()
        
    cmd = [
        "python", "-m", "PyInstaller",
        "--name=AssistenteWIN",
        "--onefile",
        "--clean",
        "--console",  # Exibe console semafórico ANSI com cores
        "--collect-all=colorama",
        "--hidden-import=licensing.hwid",
        "--hidden-import=licensing.validator",
        "--hidden-import=simular_cenario3",
        "--hidden-import=simular_liberado",
        "--hidden-import=simular_fvg_delta",
        "--hidden-import=analysis.fvg_mtf_scanner",
        "--hidden-import=feeds.csv_feed",
        str(BASE_DIR / "main.py")
    ]
    
    print("Executando PyInstaller...")
    res = subprocess.run(cmd, cwd=str(BASE_DIR))
    if res.returncode == 0:
        exe_path = dist_dir / "AssistenteWIN.exe"
        print("\n" + "=" * 70)
        print("COMPILAÇÃO CONCLUÍDA COM SUCESSO!")
        print(f"Executável gerado: {exe_path}")
        print(f"Tamanho: {exe_path.stat().st_size / (1024*1024):.2f} MB")
        print("=" * 70)
        return True
    else:
        print("\n[ERRO] Falha durante a compilação do executável.")
        return False


if __name__ == "__main__":
    build()
