"""指定实例的ADB接入；二进制截图不经过PowerShell重定向。"""

from pathlib import Path
import os
import struct
import subprocess
import time


class ScreenshotDataError(RuntimeError):
    """截图传输不完整，可重新读取；不涉及重新发送点击。"""


def validate_screenshot(data):
    from io import BytesIO
    from PIL import Image
    if data[:8]!=b'\x89PNG\r\n\x1a\n':
        raise RuntimeError('截屏未返回PNG，未保存')
    if len(data)<33 or data[12:16]!=b'IHDR' or data[-8:-4]!=b'IEND':
        raise ScreenshotDataError('PNG数据不完整，未保存')
    width,height=struct.unpack('>II',data[16:24])
    if not width or not height:raise ScreenshotDataError('PNG尺寸无效，未保存')
    try:
        with Image.open(BytesIO(data)) as image:image.verify()
        with Image.open(BytesIO(data)) as image:image.load()
    except (OSError,ValueError,SyntaxError) as exc:
        raise ScreenshotDataError('PNG校验或解码失败，未保存') from exc
    return width,height


class Adb:
    def __init__(self, executable: str = "adb", serial: str | None = None, control=None, server_port=None):
        if server_port is not None and (type(server_port) is not int or not 0<server_port<65536):
            raise ValueError('ADB服务端口必须为1～65535的整数')
        self.executable = executable
        self.serial = serial
        self.control = control
        self.server_port = server_port

    def _run(self, args: list[str], device: bool = False) -> bytes:
        command = [self.executable]
        if self.server_port is not None:
            command += ['-P',str(self.server_port)]
        if device:
            if not self.serial:
                raise ValueError("设备命令必须显式指定serial")
            command += ["-s", self.serial]
        command += args
        options={}
        if self.server_port is not None:
            environment=dict(os.environ)
            environment.pop('ADB_SERVER_SOCKET',None)
            environment['ANDROID_ADB_SERVER_PORT']=str(self.server_port)
            options['env']=environment
        for attempt in range(3):
            process = subprocess.run(command, capture_output=True, timeout=20, check=False,
                                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),**options)
            if not process.returncode:
                return process.stdout
            error=process.stderr.decode('utf-8',errors='replace').strip() or 'ADB执行失败'
            # 仅客户端尚未连上本地daemon的错误可重试：此时shell尚未派发。
            # 超时、设备离线、shell执行错误或其他非零退出均不重发输入。
            predispatch=any(text in error.lower() for text in (
                'cannot connect to daemon','cannot connect to adb daemon'))
            if not predispatch or attempt==2:
                raise RuntimeError(error)
            if self.control:
                self.control.checkpoint()
                self.control.wait(.3)
            else:
                time.sleep(.3)

    def devices(self) -> str:
        return self._run(["devices", "-l"]).decode("utf-8", errors="replace")

    def connect(self, address: str) -> str:
        if not address or address.startswith("-"):
            raise ValueError("请填写实例诊断中实际显示的地址:端口")
        output = self._run(["connect", address]).decode("utf-8", errors="replace").strip()
        if "connected to" not in output.lower():
            raise RuntimeError(output or "ADB未确认连接成功")
        return output

    def screenshot(self, path: str) -> dict:
        attempts=0
        for attempt in range(3):
            attempts=attempt+1
            if self.control:
                self.control.checkpoint()
            try:
                data = self._run(["exec-out", "screencap", "-p"], device=True)
                width,height=validate_screenshot(data)
                break
            except (RuntimeError,subprocess.TimeoutExpired) as exc:
                transient=isinstance(exc,(ScreenshotDataError,subprocess.TimeoutExpired)) or any(text in str(exc).lower() for text in (
                    'cannot connect to daemon','cannot connect to adb daemon',
                    'could not read ok from adb server'))
                if not transient or attempt==2:
                    raise
                # 截图无资源副作用；仅重读，不重发输入、不重连或重启服务。
                if self.control:
                    self.control.wait(.4)
                else:
                    time.sleep(.4)
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as stream:
            stream.write(data)
        return {"path": str(target.resolve()), "width": width, "height": height,
                "serial": self.serial, "attempts":attempts,
                "validation": "PNG头尾、尺寸、校验与图像解码通过"}

    def tap(self, x: int, y: int):
        if type(x) is not int or type(y) is not int or not (0 <= x < 1280 and 0 <= y < 720):
            raise ValueError("点击坐标必须位于已标定的1280×720画面内")
        if self.control:
            self.control.before_input()
        self._run(["shell", "input", "tap", str(x), str(y)], device=True)

    def swipe(self,x1:int,y1:int,x2:int,y2:int,duration_ms:int=500):
        for x,y in ((x1,y1),(x2,y2)):
            if type(x) is not int or type(y) is not int or not (0<=x<1280 and 0<=y<720):
                raise ValueError('滑动坐标必须位于1280×720画面内')
        if type(duration_ms) is not int or not 100<=duration_ms<=2000:
            raise ValueError('滑动时长必须为100～2000毫秒')
        if self.control:
            self.control.before_input()
        self._run(['shell','input','swipe',str(x1),str(y1),str(x2),str(y2),str(duration_ms)],device=True)
