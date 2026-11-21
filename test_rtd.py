import comtypes
import comtypes.client
from comtypes import GUID, IUnknown, COMMETHOD, HRESULT
from ctypes import wintypes
import ctypes

# IRtdServer interface
# [guid("EC0E6191-DB51-11D3-8F3E-00C04F3651B8")]
class IRtdServer(IUnknown):
    _iid_ = GUID("{EC0E6191-DB51-11D3-8F3E-00C04F3651B8}")
    _methods_ = [
        COMMETHOD([], HRESULT, "ServerStart",
                  (['in'], ctypes.c_void_p, "CallbackObject"),
                  (['out', 'retval'], ctypes.POINTER(ctypes.c_long), "pfResult")),
        COMMETHOD([], HRESULT, "ConnectData",
                  (['in'], ctypes.c_long, "TopicID"),
                  (['in'], ctypes.POINTER(comtypes.automation.VARIANT), "Strings"),
                  (['in', 'out'], ctypes.POINTER(ctypes.c_bool), "GetNewValues"),
                  (['out', 'retval'], ctypes.POINTER(comtypes.automation.VARIANT), "pvarOut")),
        COMMETHOD([], HRESULT, "RefreshData",
                  (['in', 'out'], ctypes.POINTER(ctypes.c_long), "TopicCount"),
                  (['out', 'retval'], ctypes.POINTER(comtypes.automation.VARIANT), "parrayOut")),
        COMMETHOD([], HRESULT, "DisconnectData",
                  (['in'], ctypes.c_long, "TopicID")),
        COMMETHOD([], HRESULT, "Heartbeat",
                  (['out', 'retval'], ctypes.POINTER(ctypes.c_long), "pfResult")),
        COMMETHOD([], HRESULT, "ServerTerminate"),
    ]

try:
    print("Instantiating RTDTrading.RtdServer...")
    rtd = comtypes.client.CreateObject("RTDTrading.RtdServer")
    print(f"Created object: {rtd}")
    
    server = rtd.QueryInterface(IRtdServer)
    print(f"Queried IRtdServer interface: {server}")
    
    # Try ServerStart with null callback for test
    res = server.ServerStart(None)
    print(f"ServerStart result: {res}")
    
    # Try Heartbeat
    hb = server.Heartbeat()
    print(f"Heartbeat result: {hb}")
    
except Exception as e:
    import traceback
    traceback.print_exc()
