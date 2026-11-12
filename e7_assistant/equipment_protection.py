"""按实例、规则版本保存未满级装备暂存结论；属性等价保护，不是游戏唯一ID。"""
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re

from .inventory_detail import detail_fingerprint
from .rules import Equipment, evaluate


class EquipmentProtection:
    def __init__(self, directory, serial, policy):
        if not isinstance(serial,str) or not serial.strip():
            raise ValueError('装备暂存记录需要明确的实例serial')
        self.serial, self.policy = serial, policy
        self.policy_data = asdict(policy)
        policy_key = hashlib.sha256(json.dumps(self.policy_data,sort_keys=True).encode()).hexdigest()
        self.directory = Path(directory)/hashlib.sha256(serial.encode()).hexdigest()/policy_key

    def _path(self, fingerprint):
        if not isinstance(fingerprint,str) or not re.fullmatch(r'[a-f0-9]{64}',fingerprint):
            raise ValueError('暂存装备指纹格式无效')
        return self.directory/(fingerprint+'.json')

    def read(self, fingerprint):
        path = self._path(fingerprint)
        try:
            with path.open(encoding='utf-8') as stream:
                record = json.load(stream)
        except FileNotFoundError:
            return None
        except (ValueError,OSError) as exc:
            raise ValueError(f'装备暂存记录无法读取，停止选装：{path}') from exc
        try:
            equipment = Equipment(**record['equipment'])
            decision = evaluate(equipment,self.policy)
            if (record['serial'] != self.serial or record['policy'] != self.policy_data
                    or record['fingerprint'] != fingerprint
                    or detail_fingerprint(equipment,record['main']) != fingerprint
                    or not 0 <= equipment.enhancement < 15 or not equipment.recognition_ok):
                raise ValueError('暂存条件不一致')
        except (KeyError,TypeError,ValueError) as exc:
            raise ValueError(f'装备暂存记录不完整或结论失效，停止选装：{path}') from exc
        # 规则代码更新可能未改变Policy字段。完整旧记录若已不再适用，
        # 不得挡住新规则继续强化，也不把它当成损坏记录中断选装。
        if decision.action not in {'stop','review','store'} or decision.discard_allowed:
            return None
        return record

    def remember(self, detail):
        equipment = detail['equipment']
        fingerprint = detail_fingerprint(equipment,detail['main'])
        decision = evaluate(equipment,self.policy)
        if (detail['fingerprint'] != fingerprint or not 0 <= equipment.enhancement < 15
                or not equipment.recognition_ok or decision.action not in {'stop','review','store'}
                or decision.discard_allowed):
            raise ValueError('只能暂存已核对且不允许淘汰的+0～+14停止/复核装备')
        path = self._path(fingerprint)
        record = {'serial':self.serial,'policy':self.policy_data,'fingerprint':fingerprint,
                  'equipment':asdict(equipment),'main':detail['main'],
                  'decision':asdict(decision),'source':detail['source']}
        self.directory.mkdir(parents=True,exist_ok=True)
        try:
            with path.open('x',encoding='utf-8') as stream:
                json.dump(record,stream,ensure_ascii=False)
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            return self.read(fingerprint)
        return record

    def should_skip(self, detail):
        record = self.read(detail['fingerprint'])
        if record is None:
            return False
        if detail_fingerprint(detail['equipment'],detail['main']) != detail['fingerprint']:
            raise ValueError('当前装备详情与暂存指纹不一致')
        # 当前主属性用途、人工指定目标等语义可改变；旧暂存不能覆盖新判断。
        decision = evaluate(detail['equipment'],self.policy)
        return decision.action in {'stop','review','store'} and not decision.discard_allowed

    def records(self):
        records = [self.read(path.stem) for path in sorted(self.directory.glob('*.json'))]
        return [record for record in records if record is not None]
