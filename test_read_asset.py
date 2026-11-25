import ctypes
from ctypes import wintypes

kernel32 = ctypes.windll.kernel32

GENERIC_READ = 0x80000000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
FILE_SHARE_DELETE = 0x00000004
OPEN_EXISTING = 3
FILE_ATTRIBUTE_NORMAL = 0x80

path = r"C:\Users\glaci\AppData\Roaming\Nelogica\Profit\database\assets\WINZ26_F_0"

hfile = kernel32.CreateFileW(
    path,
    GENERIC_READ,
    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
    None,
    OPEN_EXISTING,
    FILE_ATTRIBUTE_NORMAL,
    None
)

print(f"CreateFileW handle: {hfile}")
if hfile != -1:
    buf = ctypes.create_string_buffer(512)
    bytes_read = wintypes.DWORD(0)
    kernel32.ReadFile(hfile, buf, 512, ctypes.byref(bytes_read), None)
    kernel32.CloseHandle(hfile)
    data = buf.raw[:bytes_read.value]
    print(f"Read {bytes_read.value} bytes successfully!")
    import re
    strings = re.findall(b'[\x20-\x7e]{3,}', data)
    print("Strings:", [s.decode() for s in strings])
else:
    err = kernel32.GetLastError()
    print(f"CreateFileW failed with error: {err}")
