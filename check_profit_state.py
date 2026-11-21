import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

WINSTA_ALL = 0x37F
DESKTOP_ALL = 0x1FF

hwinsta = user32.OpenWindowStationW("winsta0", False, WINSTA_ALL)
user32.SetProcessWindowStation(hwinsta)
hdesk = user32.OpenDesktopW("default", 0, False, DESKTOP_ALL)
user32.SetThreadDesktop(hdesk)

main_hwnd = 0x00010756

class WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ('length', wintypes.UINT),
        ('flags', wintypes.UINT),
        ('showCmd', wintypes.UINT),
        ('ptMinPosition', wintypes.POINT),
        ('ptMaxPosition', wintypes.POINT),
        ('rcNormalPosition', wintypes.RECT),
    ]

wp = WINDOWPLACEMENT()
wp.length = ctypes.sizeof(WINDOWPLACEMENT)
user32.GetWindowPlacement(main_hwnd, ctypes.byref(wp))

# showCmd: 1 = SW_SHOWNORMAL, 2 = SW_SHOWMINIMIZED, 3 = SW_SHOWMAXIMIZED
print(f"showCmd: {wp.showCmd} (1=Normal, 2=Minimized, 3=Maximized)")
print(f"Normal Position: ({wp.rcNormalPosition.left}, {wp.rcNormalPosition.top}) to ({wp.rcNormalPosition.right}, {wp.rcNormalPosition.bottom})")
rect = wintypes.RECT()
user32.GetWindowRect(main_hwnd, ctypes.byref(rect))
print(f"Current Rect: ({rect.left}, {rect.top}) to ({rect.right}, {rect.bottom})")
