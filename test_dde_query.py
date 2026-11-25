import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32

WINSTA_ALL = 0x37F
DESKTOP_ALL = 0x1FF
hwinsta = user32.OpenWindowStationW("winsta0", False, WINSTA_ALL)
user32.SetProcessWindowStation(hwinsta)
hdesk = user32.OpenDesktopW("default", 0, False, DESKTOP_ALL)
user32.SetThreadDesktop(hdesk)

# DDE constants
CP_WINUNICODE = 1200
XTYP_REQUEST = 0x00B0 | 0x2000
CF_TEXT = 1
TIMEOUT_ASYNC = 0xFFFFFFFF

PFNCALLBACK = ctypes.WINFUNCTYPE(ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)

def dde_callback(uType, uFmt, hconv, hsz1, hsz2, hdata, dwData1, dwData2):
    return 0

cb = PFNCALLBACK(dde_callback)
idInst = wintypes.DWORD(0)
user32.DdeInitializeW(ctypes.byref(idInst), cb, 0, 0)

hsz_srv = user32.DdeCreateStringHandleW(idInst.value, "profitchart", CP_WINUNICODE)
hsz_top = user32.DdeCreateStringHandleW(idInst.value, "cot", CP_WINUNICODE)

hconv = user32.DdeConnect(idInst.value, hsz_srv, hsz_top, None)
print(f"Connected to profitchart|cot: hconv={hconv}")

if hconv:
    items_to_test = [
        "WINZ26.ULT", "WINZ26.ABE", "WINZ26.MAX", "WINZ26.MIN", "WINZ26.FECH",
        "WINZ26.VOL", "WINZ26.VOLF", "WINZ26.HOR", "WINZ26.DAT", "WINZ26.VAR",
        "WINZ26.NEG", "WINZ26.OFE_C_PRE", "WINZ26.OFE_C_QTD", "WINZ26.OFE_V_PRE", "WINZ26.OFE_V_QTD",
        "WINZ26.OFE_C_AGE", "WINZ26.OFE_V_AGE",
        "WINZ26.MELHOR_C", "WINZ26.MELHOR_V",
        "WINZ26.ULT_AGR", "WINZ26.AGR", "WINZ26.DELTA",
        "WIN$N.ULT", "WIN$N.MAX", "WIN$N.MIN", "WIN$.ULT"
    ]
    
    for item in items_to_test:
        hsz_item = user32.DdeCreateStringHandleW(idInst.value, item, CP_WINUNICODE)
        pdwResult = wintypes.DWORD(0)
        
        # Call DdeClientTransaction
        hdata = user32.DdeClientTransaction(
            None, 0, hconv, hsz_item, CF_TEXT, XTYP_REQUEST, 3000, ctypes.byref(pdwResult)
        )
        
        if hdata:
            # Query data size
            size = user32.DdeGetData(hdata, None, 0, 0)
            buf = ctypes.create_string_buffer(size)
            user32.DdeGetData(hdata, buf, size, 0)
            val = buf.value.decode('latin-1', errors='replace')
            print(f"ITEM: {item:18} -> VALUE: '{val.strip()}'")
            user32.DdeFreeDataHandle(hdata)
        else:
            err = user32.DdeGetLastError(idInst.value)
            print(f"ITEM: {item:18} -> NOT FOUND / ERR: {hex(err)}")
            
        user32.DdeFreeStringHandle(idInst.value, hsz_item)

    user32.DdeDisconnect(hconv)

user32.DdeFreeStringHandle(idInst.value, hsz_srv)
user32.DdeFreeStringHandle(idInst.value, hsz_top)
user32.DdeUninitialize(idInst.value)
