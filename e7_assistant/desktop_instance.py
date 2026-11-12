"""Windows桌面窗口单实例；先兼容发现旧版窗口，再防止同时启动竞态。"""
TITLE='第七史诗 · 打铁助手'


class DesktopInstance:
    def __init__(self,kernel,user,last_error):
        self.kernel,self.user,self.last_error=kernel,user,last_error
        self.handle=None

    def acquire(self):
        existing=self.user.FindWindowW(None,TITLE)
        if existing:
            self.user.ShowWindow(existing,9)  # SW_RESTORE
            self.user.SetForegroundWindow(existing)
            return False
        handle=self.kernel.CreateMutexW(None,False,'Local\\E7ForgeAssistantDesktop')
        error=self.last_error()
        if not handle:raise OSError(error,'无法建立客户端单实例标记')
        if error==183:  # ERROR_ALREADY_EXISTS
            self.kernel.CloseHandle(handle)
            return False
        self.handle=handle
        return True

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle=None


def desktop_instance():
    import ctypes
    from ctypes import wintypes
    kernel=ctypes.WinDLL('kernel32',use_last_error=True)
    user=ctypes.WinDLL('user32',use_last_error=True)
    kernel.CreateMutexW.argtypes=[ctypes.c_void_p,wintypes.BOOL,wintypes.LPCWSTR]
    kernel.CreateMutexW.restype=wintypes.HANDLE
    kernel.CloseHandle.argtypes=[wintypes.HANDLE]
    kernel.CloseHandle.restype=wintypes.BOOL
    user.FindWindowW.argtypes=[wintypes.LPCWSTR,wintypes.LPCWSTR]
    user.FindWindowW.restype=wintypes.HWND
    user.ShowWindow.argtypes=[wintypes.HWND,ctypes.c_int]
    user.SetForegroundWindow.argtypes=[wintypes.HWND]
    return DesktopInstance(kernel,user,ctypes.get_last_error)
