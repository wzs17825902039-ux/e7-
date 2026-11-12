"""一次启动任务内实际强化成品的速度统计；不写入下次任务配置。"""


class EnhancementStatistics:
    def __init__(self):
        self.counts={'speed14':0,'speed15':0,'speed16plus':0,'total14plus':0}
        self.seen=set()

    def record(self,key,before,after):
        if (key in self.seen or before.equipment_id!=after.equipment_id
                or before.enhancement>=15 or after.enhancement!=15
                or not after.recognition_ok):
            return False
        speed=after.stats.get('speed',0)
        if speed<14:
            return False
        bucket='speed14' if speed==14 else 'speed15' if speed==15 else 'speed16plus'
        self.seen.add(key)
        self.counts[bucket]+=1
        self.counts['total14plus']+=1
        return True

    def snapshot(self):
        return dict(self.counts)
