import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
WINSTA_ALL = 0x37F
DESKTOP_ALL = 0x1FF
hwinsta = user32.OpenWindowStationW('winsta0', False, WINSTA_ALL)
user32.SetProcessWindowStation(hwinsta)
hdesk = user32.OpenDesktopW('default', 0, False, DESKTOP_ALL)
user32.SetThreadDesktop(hdesk)

CP_WINUNICODE = 1200
XTYP_REQUEST = 0x00B0 | 0x2000
CF_TEXT = 1

PFNCALLBACK = ctypes.WINFUNCTYPE(ctypes.c_void_p, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)
cb = PFNCALLBACK(lambda *args: 0)
idInst = wintypes.DWORD(0)
user32.DdeInitializeW(ctypes.byref(idInst), cb, 0, 0)

hsz_srv = user32.DdeCreateStringHandleW(idInst.value, 'profitchart', CP_WINUNICODE)
hsz_top = user32.DdeCreateStringHandleW(idInst.value, 'cot', CP_WINUNICODE)

hconv = user32.DdeConnect(idInst.value, hsz_srv, hsz_top, None)

fields = [
    'ULT', 'ABE', 'MAX', 'MIN', 'VOL', 'NEG', 'FEC', 'MED',
    'AGRVOLC', 'AGRVOLV', 'AGRSALDO', 'HOR', 'DAT', 'VAR', 'VARPTS'
]

print("=== VERIFICANDO DADOS AO VIVO DO WINZ26 ===")
if hconv:
    for f in fields:
        item = f"WINZ26.{f}"
        hsz_item = user32.DdeCreateStringHandleW(idInst.value, item, CP_WINUNICODE)
        pdwResult = wintypes.DWORD(0)
        hdata = user32.DdeClientTransaction(
            None, 0, hconv, hsz_item, CF_TEXT, XTYP_REQUEST, 2000, ctypes.byref(pdwResult)
        )
        if hdata:
            size = user32.DdeGetData(hdata, None, 0, 0)
            buf = ctypes.create_string_buffer(size)
            user32.DdeGetData(hdata, buf, size, 0)
            val = buf.value.decode('latin-1', errors='replace').strip()
            print(f"  {item:16} = '{val}'")
            user32.DdeFreeDataHandle(hdata)
        else:
            print(f"  {item:16} = (não disponível)")
        user32.DdeFreeStringHandle(idInst.value, hsz_item)
    user32.DdeDisconnect(hconv)

user32.DdeFreeStringHandle(idInst.value, hsz_srv)
user32.DdeFreeStringHandle(idInst.value, hsz_top)
user32.DdeUninitialize(idInst.value)
