"""
sync_to_gdrive.py
Copia o arquivo de backup compactado para a pasta do Google Drive (unidade G: ou sincronização local).
"""
import os
import shutil
import glob
from datetime import date

today_dmy = date.today().strftime('%d-%m-%Y')
today_ymd = date.today().strftime('%Y_%m_%d')

backups_dir = os.path.join(os.path.dirname(__file__), "backups")
patterns = [
    os.path.join(backups_dir, f"*{today_dmy}*.zip"),
    os.path.join(backups_dir, f"*{today_ymd}*.zip")
]

matches = []
for p in patterns:
    matches.extend(glob.glob(p))

matches = list(dict.fromkeys(matches)) # remover duplicatas mantendo ordem

if not matches:
    print(f"Nenhum backup encontrado com a data {today_dmy} ou {today_ymd} na pasta backups/")
    exit(1)

src_file = matches[0]
print(f"Arquivo de backup localizado: {src_file} ({os.path.getsize(src_file)/1024:.1f} KB)")

target_drives = [
    r"G:\Meu Drive",
    r"G:\Meu Drive\1. ALGO_B3-MINIs_VALE3",
    r"G:\My Drive",
    r"C:\Users\glaci\Google Drive",
    r"D:\Google Drive",
    r"C:\Users\glaci\OneDrive",
    r"C:\Users\glaci\OneDrive\Desktop"
]

copied = False
for tgt in target_drives:
    if os.path.exists(tgt):
        dest_path = os.path.join(tgt, os.path.basename(src_file))
        shutil.copy2(src_file, dest_path)
        print(f"[OK] Sincronizado com sucesso para: {dest_path}")
        copied = True

if not copied:
    print("[AVISO] O aplicativo Google Drive Desktop ainda não mapeou a unidade G: neste momento.")
    print(f"O arquivo está disponível na sua Área de Trabalho em:\nC:\\Users\\glaci\\OneDrive\\Desktop\\{os.path.basename(src_file)}")
