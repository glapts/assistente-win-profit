import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WINSTA_ALL = 0x37F
DESKTOP_ALL = 0x1FF

hwinsta = user32.OpenWindowStationW("winsta0", False, WINSTA_ALL)
user32.SetProcessWindowStation(hwinsta)
hdesk = user32.OpenDesktopW("default", 0, False, DESKTOP_ALL)
user32.SetThreadDesktop(hdesk)

main_hwnd = 0x00010756

WNDENUMCHILDPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

children = []

def child_cb(hwnd, lparam):
    length = user32.GetWindowTextLengthW(hwnd)
    title_buf = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title_buf, length + 1)
    
    class_buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, class_buf, 256)
    
    vis = bool(user32.IsWindowVisible(hwnd))
    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    
    children.append((hwnd, vis, class_buf.value, title_buf.value, (rect.left, rect.top, rect.right, rect.bottom)))
    return True

user32.EnumChildWindows(main_hwnd, WNDENUMCHILDPROC(child_cb), 0)

print(f"Total child windows under ProfitPro: {len(children)}")
for h, vis, cls, title, r in children:
    # Filter for interesting children (charts, books, grids, titles)
    if any(k in title.lower() for k in ['win', 'livro', 'book', 'times', 'trade', 'oferta', 'grfico', 'grafico', 'negocios']) or any(c in cls.lower() for c in ['mdi', 'chart', 'grid', 'book']):
        print(f"HWND: 0x{h:08X} | Vis: {vis:5} | Class: {cls:30} | Rect: {r} | Title: {title}")
