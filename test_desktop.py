import ctypes
from ctypes import wintypes
import subprocess

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Check current window station and desktop
h_winsta = user32.GetProcessWindowStation()
buf = ctypes.create_unicode_buffer(256)
user32.GetUserObjectInformationW(h_winsta, 2, buf, 256, None) # UOI_NAME = 2
print(f"Current WindowStation: {buf.value}")

h_desk = user32.GetThreadDesktop(kernel32.GetCurrentThreadId())
user32.GetUserObjectInformationW(h_desk, 2, buf, 256, None)
print(f"Current Desktop: {buf.value}")

# Let's open winsta0\default
WINSTA_ALL = 0x37F
DESKTOP_ALL = 0x1FF

hwinsta_interactive = user32.OpenWindowStationW("winsta0", False, WINSTA_ALL)
print(f"OpenWindowStation(winsta0): {hwinsta_interactive}")
if hwinsta_interactive:
    set_res = user32.SetProcessWindowStation(hwinsta_interactive)
    print(f"SetProcessWindowStation: {set_res}")
    
    hdesk_interactive = user32.OpenDesktopW("default", 0, False, DESKTOP_ALL)
    print(f"OpenDesktop(default): {hdesk_interactive}")
    if hdesk_interactive:
        set_desk = user32.SetThreadDesktop(hdesk_interactive)
        print(f"SetThreadDesktop: {set_desk}")
        
        WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
        found = []
        def cb(hwnd, lparam):
            pid = wintypes.DWORD()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                tbuf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, tbuf, length + 1)
                found.append((pid.value, hwnd, tbuf.value))
            return True
            
        user32.EnumDesktopWindows(hdesk_interactive, WNDENUMPROC(cb), 0)
        print(f"Total windows found on default desktop: {len(found)}")
        for pid, hwnd, title in found:
            if any(k in title.lower() for k in ['profit', 'win', 'nelogica']):
                print(f"PID: {pid} | HWND: 0x{hwnd:08X} | Title: {title}")
