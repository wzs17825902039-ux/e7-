import argparse
from dataclasses import asdict
import json
from pathlib import Path
import subprocess
import sys

from .adb import Adb
from .replay import replay
from .rules import Equipment, Policy, evaluate


def read_json(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main():
    # Windows管道默认编码可能与调用方不同，JSON输出统一为UTF-8。
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="第七史诗打铁助手：规则评估、离线回放、MuMu截图")
    parser.add_argument("--policy", help="规则JSON，省略则使用保守默认值")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("evaluate", "replay"):
        sub = commands.add_parser(name)
        sub.add_argument("input", help="装备对象或回放数组JSON路径")
    commands.add_parser("inspect", help="Windows本地OCR，只读分析强化页截图").add_argument("image")
    commands.add_parser("gui", help="打开桌面界面")
    adb_parser = commands.add_parser("adb")
    adb_parser.add_argument("--executable", default="adb", help="adb.exe路径")
    adb_parser.add_argument("--serial", help="明确指定实例设备号")
    adb_commands = adb_parser.add_subparsers(dest="adb_command", required=True)
    adb_commands.add_parser("devices")
    adb_commands.add_parser("connect").add_argument("address")
    adb_commands.add_parser("screenshot").add_argument("output")
    args = parser.parse_args()
    try:
        if args.command == "gui":
            from .desktop import launch
            launch()
            return 0
        if args.command == "inspect":
            from .vision import inspect_image
            output = inspect_image(args.image)
        elif args.command == "adb":
            adb = Adb(args.executable, args.serial)
            if args.adb_command == "devices":
                output = {"devices": adb.devices()}
            elif args.adb_command == "connect":
                output = {"connection": adb.connect(args.address)}
            else:
                output = adb.screenshot(args.output)
        else:
            policy = Policy(**read_json(args.policy)) if args.policy else Policy()
            data = read_json(args.input)
            output = asdict(evaluate(Equipment(**data), policy)) if args.command == "evaluate" else replay(data, policy)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, RuntimeError, subprocess.TimeoutExpired) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
