"""Windows implementation: typing, clipboard, global hotkeys, window checks.

Plain ctypes, no keyboard hooks (hooks look like keyloggers to antivirus
software). Hotkeys use RegisterHotKey, which also tells us when another
program already owns a shortcut.
"""

from __future__ import annotations

import ctypes
import queue
import threading
import time
from ctypes import wintypes
from typing import Callable

from .hotkeys import Hotkey

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

ULONG_PTR = ctypes.c_size_t
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x2
KEYEVENTF_UNICODE = 0x4
VK_CONTROL = 0x11
VK_V = 0x56
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x2
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_APP_CMD = 0x8000 + 1
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x8
TOKEN_ELEVATION = 20


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wintypes.DWORD), ("wParamL", wintypes.WORD), ("wParamH", wintypes.WORD)]


class _INPUTUNION(ctypes.Union):
    # The union must be as large as its biggest member or SendInput rejects it.
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
user32.SetClipboardData.restype = wintypes.HANDLE
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_int
user32.PeekMessageW.argtypes = [
    ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT,
]
user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.GetCurrentProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
advapi32.OpenProcessToken.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE)]
advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
]


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ki = KEYBDINPUT(wVk=vk, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=0)
    return inp


def _send(inputs: list[INPUT]) -> None:
    arr = (INPUT * len(inputs))(*inputs)
    sent = user32.SendInput(len(inputs), arr, ctypes.sizeof(INPUT))
    if sent != len(inputs):
        raise OSError(ctypes.get_last_error(), "SendInput nie wysłał wszystkich znaków")


def _process_elevated(process) -> bool | None:
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
        return None
    try:
        value, size = wintypes.DWORD(), wintypes.DWORD()
        ok = advapi32.GetTokenInformation(token, TOKEN_ELEVATION, ctypes.byref(value), 4, ctypes.byref(size))
        return bool(value.value) if ok else None
    finally:
        kernel32.CloseHandle(token)


class _HotkeyThread(threading.Thread):
    """RegisterHotKey delivers to the registering thread, so one thread owns them all."""

    def __init__(self):
        super().__init__(daemon=True, name="dictaitor-hotkeys")
        self.ready = threading.Event()
        self.requests: queue.Queue = queue.Queue()
        self.callbacks: dict[int, Callable[[], None]] = {}
        self.thread_id = 0

    def run(self) -> None:
        self.thread_id = kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)  # creates the message queue
        self.ready.set()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                callback = self.callbacks.get(int(msg.wParam))
                if callback:
                    try:
                        callback()
                    except Exception:  # never let a UI error kill the hotkey thread
                        pass
            elif msg.message == WM_APP_CMD:
                while not self.requests.empty():
                    fn, result, done = self.requests.get()
                    try:
                        result.append(fn())
                    finally:
                        done.set()

    def call(self, fn):
        self.ready.wait()
        result: list = []
        done = threading.Event()
        self.requests.put((fn, result, done))
        user32.PostThreadMessageW(self.thread_id, WM_APP_CMD, 0, 0)
        done.wait(5)
        return result[0] if result else None


class WindowsPlatform:
    def __init__(self):
        self._hotkeys = _HotkeyThread()
        self._hotkeys.start()
        self._ids: dict[Hotkey, int] = {}
        self._next_id = 0xB100
        self._self_elevated = bool(_process_elevated(kernel32.GetCurrentProcess()))

    # -------------------------------------------------------------- windows

    def foreground_window(self) -> int:
        return int(user32.GetForegroundWindow() or 0)

    def window_title(self, window: int) -> str:
        length = user32.GetWindowTextLengthW(window)
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(window, buf, length + 1)
        return buf.value

    def is_elevated_window(self, window: int) -> bool:
        """True when Windows would silently block our keystrokes (admin window)."""
        if self._self_elevated:
            return False
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(window, ctypes.byref(pid))
        process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
        if not process:
            return True  # can't even look at it: be safe, use the clipboard
        try:
            elevated = _process_elevated(process)
        finally:
            kernel32.CloseHandle(process)
        return True if elevated is None else elevated

    def focus_window(self, window: int) -> bool:
        return bool(user32.SetForegroundWindow(window))

    # --------------------------------------------------------------- typing

    def type_text(self, text: str) -> None:
        data = text.replace("\r", "").replace("\n", " ").encode("utf-16-le")
        units = [int.from_bytes(data[i : i + 2], "little") for i in range(0, len(data), 2)]
        for start in range(0, len(units), 40):  # small batches so slow apps keep up
            batch = []
            for unit in units[start : start + 40]:
                batch.append(_key(scan=unit, flags=KEYEVENTF_UNICODE))
                batch.append(_key(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP))
            _send(batch)
            time.sleep(0.01)

    def paste_text(self, text: str) -> None:
        previous = self.get_clipboard()
        self.set_clipboard(text)
        _send([_key(VK_CONTROL), _key(VK_V), _key(VK_V, flags=KEYEVENTF_KEYUP), _key(VK_CONTROL, flags=KEYEVENTF_KEYUP)])
        time.sleep(0.3)  # the target reads the clipboard asynchronously
        if previous is not None:
            self.set_clipboard(previous)

    # ------------------------------------------------------------ clipboard

    def _open_clipboard(self) -> None:
        for _ in range(20):
            if user32.OpenClipboard(None):
                return
            time.sleep(0.05)
        raise OSError("schowek jest zajęty przez inny program")

    def get_clipboard(self) -> str | None:
        self._open_clipboard()
        try:
            handle = user32.GetClipboardData(CF_UNICODETEXT)
            if not handle:
                return None
            pointer = kernel32.GlobalLock(handle)
            try:
                return ctypes.wstring_at(pointer)
            finally:
                kernel32.GlobalUnlock(handle)
        finally:
            user32.CloseClipboard()

    def set_clipboard(self, text: str) -> None:
        data = text.encode("utf-16-le") + b"\x00\x00"
        self._open_clipboard()
        try:
            user32.EmptyClipboard()
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
            pointer = kernel32.GlobalLock(handle)
            ctypes.memmove(pointer, data, len(data))
            kernel32.GlobalUnlock(handle)
            user32.SetClipboardData(CF_UNICODETEXT, handle)
        finally:
            user32.CloseClipboard()

    # -------------------------------------------------------------- hotkeys

    def register_hotkey(self, hotkey: Hotkey, callback: Callable[[], None]) -> bool:
        hk_id = self._next_id
        self._next_id += 1

        def register():
            ok = bool(user32.RegisterHotKey(None, hk_id, hotkey.modifiers | MOD_NOREPEAT, hotkey.vk))
            if ok:
                self._hotkeys.callbacks[hk_id] = callback
            return ok

        if self._hotkeys.call(register):
            self._ids[hotkey] = hk_id
            return True
        return False

    def unregister_hotkey(self, hotkey: Hotkey) -> None:
        hk_id = self._ids.pop(hotkey, None)
        if hk_id is None:
            return

        def unregister():
            self._hotkeys.callbacks.pop(hk_id, None)
            return bool(user32.UnregisterHotKey(None, hk_id))

        self._hotkeys.call(unregister)
