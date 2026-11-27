"""
f8_hotkey_service.py
Ouvinte Global da Tecla F8 para Cópia em 1-Clique do Times & Trades no Nelogica Profit Pro.
Pressione F8 a qualquer momento no Windows para enviar Ctrl+C e soar um bip de confirmação.
"""

import time
import ctypes
import winsound

def main():
    print("=" * 65)
    print("🚀 SERVIÇO GLOBAL DA TECLA F8 — CÓPIA AUTOMÁTICA DO TIMES & TRADES")
    print("=" * 65)
    print(" Instrução: Deixe esta janela minimizada.")
    print(" A qualquer momento no pregão, aperte F8 para copiar os negócios")
    print(" do Profit Pro e alimentar o monitor Whale Flow automaticamente!")
    print(" Para encerrar: aperte Ctrl+C nesta janela.")
    print("=" * 65 + "\n")

    user32 = ctypes.windll.user32
    VK_F8 = 0x77
    VK_CONTROL = 0x11
    KEY_C = 0x43
    KEYEVENTF_KEYUP = 0x0002

    was_down = False
    try:
        while True:
            is_down = bool(user32.GetAsyncKeyState(VK_F8) & 0x8000)
            if is_down and not was_down:
                was_down = True
                try:
                    # Se a janela do Profit Pro existir, traz ela para o foco antes do Ctrl+C
                    profit_hwnd = user32.FindWindowW("TProfitChartForm", None)
                    if profit_hwnd:
                        user32.SetForegroundWindow(profit_hwnd)
                        time.sleep(0.06)
                    else:
                        fg_hwnd = user32.GetForegroundWindow()
                        title_buf = ctypes.create_unicode_buffer(512)
                        user32.GetWindowTextW(fg_hwnd, title_buf, 512)
                        fg_title = title_buf.value.lower()
                        if any(k in fg_title for k in ["powershell", "terminal", "prompt", "f8"]):
                            print(f"[{time.strftime('%H:%M:%S')}] ⚠️ [AVISO FOCO] Clique no Profit Pro antes de teclar F8!")
                            continue

                    scan_ctrl = user32.MapVirtualKeyW(VK_CONTROL, 0)
                    scan_c = user32.MapVirtualKeyW(KEY_C, 0)
                    user32.keybd_event(VK_CONTROL, scan_ctrl, 0, 0)
                    user32.keybd_event(KEY_C, scan_c, 0, 0)
                    time.sleep(0.04)
                    user32.keybd_event(KEY_C, scan_c, KEYEVENTF_KEYUP, 0)
                    user32.keybd_event(VK_CONTROL, scan_ctrl, KEYEVENTF_KEYUP, 0)

                    try:
                        winsound.Beep(1800, 100)
                    except Exception:
                        pass

                    now_str = time.strftime("%H:%M:%S")
                    print(f"[{now_str}] ⚡ [F8 DISPARADO] Comando Ctrl+C enviado com sucesso!")
                except Exception as e:
                    print(f"[ERRO F8] {e}")
            elif not is_down and was_down:
                was_down = False
            time.sleep(0.04)
    except KeyboardInterrupt:
        print("\n[F8 SERVICE] Serviço encerrado pelo operador.")

if __name__ == "__main__":
    main()
