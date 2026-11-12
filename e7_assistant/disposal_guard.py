"""同一ADB实例的处置确认记录；未知结果不能因新任务或重启而丢失。"""
import hashlib
import json
import os
from pathlib import Path
import uuid


class PendingActionGuard:
    actions = frozenset({'extract','sell'})
    label = '处置'
    action_text = '出售/萃取'

    def __init__(self, directory, serial):
        if not isinstance(serial, str) or not serial.strip():
            raise ValueError(f'{self.label}记录需要明确的ADB实例serial')
        self.serial = serial
        key = hashlib.sha256(serial.encode('utf-8')).hexdigest()
        self.path = Path(directory) / (key + '.json')

    def read(self):
        try:
            with self.path.open(encoding='utf-8') as stream:
                record = json.load(stream)
        except FileNotFoundError:
            return None
        except (ValueError, OSError) as exc:
            raise ValueError(f'{self.label}记录无法读取，禁止重复操作：{self.path}') from exc
        if (not isinstance(record, dict) or record.get('serial') != self.serial
                or not isinstance(record.get('operation_id'), str)
                or not record['operation_id'] or record.get('action') not in self.actions):
            raise ValueError(f'{self.label}记录不完整，禁止重复操作：{self.path}')
        return record

    def check_clear(self):
        record = self.read()
        if record is not None:
            raise ValueError(f'上次{self.action_text}结果未结算，禁止重复操作；需核对记录：{self.path}')

    def begin(self, action, before, confirmation, run_directory):
        if action not in self.actions:
            raise ValueError(f'{self.label}记录的操作类型无效')
        self.path.parent.mkdir(parents=True, exist_ok=True)
        record = {'operation_id': uuid.uuid4().hex, 'serial': self.serial, 'action': action,
                  'before': before, 'confirmation': confirmation,
                  'run_directory': str(run_directory)}
        try:
            # 排他创建覆盖并发任务；写入失败也保留文件，后续不得猜测未发生输入。
            with self.path.open('x', encoding='utf-8') as stream:
                json.dump(record, stream, ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError as exc:
            raise ValueError(f'存在未结算{self.label}，未发送确认：{self.path}') from exc
        return record['operation_id']

    def settle(self, operation_id):
        record = self.read()
        if record is None or record['operation_id'] != operation_id:
            raise ValueError(f'{self.label}记录身份变化，未清除未知结果记录')
        self.path.unlink()


class DisposalGuard(PendingActionGuard):
    pass


class BatchEnhancementGuard(PendingActionGuard):
    actions = frozenset({'batch_enhance'})
    label = '批量强化'
    action_text = '批量强化'


class CraftSessionGuard(PendingActionGuard):
    actions = frozenset({'craft'})
    label = '打造会话'
    action_text = '打造'
