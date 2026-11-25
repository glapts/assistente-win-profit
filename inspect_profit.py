import ctypes
from ctypes import wintypes
import sys
import subprocess

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Get current PID of profitchart.exe dynamically
out = subprocess.run(["powershell", "-NoProfile", "-Command", "Get-Process -Name profitchart -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Id"], capture_output=True, text=True)
pids = [int(p.strip()) for p in out.stdout.splitlines() if p.strip().isdigit()]
print(f"Profit PIDs found: {pids}")

WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

for target_pid in pids:
    found_windows = []

    def enum_cb(hwnd, lparam):
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value == target_pid:
            length = user32.GetWindowTextLengthW(hwnd)
            title_buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, title_buf, length + 1)
            
            class_buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_buf, 256)
            
            vis = bool(user32.IsWindowVisible(hwnd))
            found_windows.append((hwnd, vis, class_buf.value, title_buf.value))
        return True

    user32.EnumWindows(WNDENUMPROC(enum_cb), 0)

    print(f"\nWindows found for PID {target_pid}: {len(found_windows)}")
    for h, vis, cls, title in found_windows:
        if title or vis:
            print(f"HWND: 0x{h:08X} | Visible: {vis:5} | Class: {cls:30} | Title: {title}")
