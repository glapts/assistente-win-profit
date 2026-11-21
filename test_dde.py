import ctypes
from ctypes import wintypes
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

WINSTA_ALL = 0x37F
DESKTOP_ALL = 0x1FF
hwinsta = user32.OpenWindowStationW("winsta0", False, WINSTA_ALL)
user32.SetProcessWindowStation(hwinsta)
hdesk = user32.OpenDesktopW("default", 0, False, DESKTOP_ALL)
user32.SetThreadDesktop(hdesk)

# DDE constants
DMLERR_NO_ERROR = 0
CP_WINUNICODE = 1200
CP_WINANSI = 1004
XTYP_REQUEST = 0x00B0 | 0x2000 # XCLASS_DATA
CF_TEXT = 1

PFNCALLBACK = ctypes.WINFUNCTYPE(ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

def dde_callback(uType, uFmt, hconv, hsz1, hsz2, hdata, dwData1, dwData2):
    return 0

cb = PFNCALLBACK(dde_callback)
idInst = wintypes.DWORD(0)

res = user32.DdeInitializeW(ctypes.byref(idInst), cb, 0, 0)
print(f"DdeInitializeW result: {res}, idInst: {idInst.value}")

def test_service_topic(service_name, topic_name):
    hsz_srv = user32.DdeCreateStringHandleW(idInst.value, service_name, CP_WINUNICODE)
    hsz_top = user32.DdeCreateStringHandleW(idInst.value, topic_name, CP_WINUNICODE)
    
    hconv = user32.DdeConnect(idInst.value, hsz_srv, hsz_top, None)
    err = user32.DdeGetLastError(idInst.value)
    print(f"DdeConnect(srv='{service_name}', topic='{topic_name}') -> hconv={hconv}, err={hex(err)}")
    
    user32.DdeFreeStringHandle(idInst.value, hsz_srv)
    user32.DdeFreeStringHandle(idInst.value, hsz_top)
    return hconv

services = ["profitchart", "ProfitChart", "PROFIT", "profit", "nelogica", "Nelogica", "PROFITDDE"]
topics = ["cot", "COT", "COTACAO", "winz26", "System"]

for s in services:
    for t in topics:
        hc = test_service_topic(s, t)
        if hc:
            print(f"*** SUCCESS: Connected to {s}|{t} ! ***")
            user32.DdeDisconnect(hc)
            break

user32.DdeUninitialize(idInst.value)
