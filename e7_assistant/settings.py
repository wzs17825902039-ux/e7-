"""本地界面配置；不保存凭据，不自动恢复任务。"""

from dataclasses import asdict, dataclass, field, replace
import json
from pathlib import Path
import subprocess

from .rules import Policy,RIGHT_MAIN_STATS
from .tasks import Limits
from .workflow import WorkflowOptions


@dataclass
class Settings:
    adb_path: str = ""
    serial: str = ""
    policy: dict = field(default_factory=lambda: asdict(Policy(
        sell_failed_purple=True,red_profile_enabled=True,sell_failed_red=True,discard_flat_right_without_speed=True,
        right_main_stats={slot:list(stats) for slot,stats in RIGHT_MAIN_STATS.items()})))
    limits: dict = field(default_factory=lambda: asdict(Limits()))
    workflow: dict = field(default_factory=lambda: asdict(WorkflowOptions()))

    def validate(self):
        if not isinstance(self.adb_path, str) or not isinstance(self.serial, str):
            raise ValueError("ADB路径和设备号必须为文本")
        Policy(**self.policy)
        Limits(**self.limits)
        WorkflowOptions(**self.workflow)
        return self


def load_settings(path):
    path = Path(path)
    return Settings(**json.loads(path.read_text(encoding="utf-8-sig"))).validate() if path.exists() else Settings()


def red_gate_note(policy_data):
    """显式旧配置不自动覆盖；把实际生效门槛及更新入口展示给用户。"""
    policy=Policy(**policy_data)
    defaults=Policy()
    stages=('0','3','6','9','12','15')
    values='；'.join(f"{'初始' if stage=='0' else '+'+stage}左{policy.red_left_gates[stage]:g}/右{policy.red_right_gates[stage]:g}"
                    for stage in stages)
    current=(policy.red_left_gates==defaults.red_left_gates and policy.red_right_gates==defaults.red_right_gates)
    old_left={'0':22,'3':28,'6':34,'9':40,'12':46,'15':52}
    old_right={'0':20,'3':26,'6':32,'9':38,'12':44,'15':50}
    if current:
        source='当前默认门槛'
    elif policy.red_left_gates==old_left and policy.red_right_gates==old_right:
        source='当前值与旧版默认一致，已保留；可点击下方按钮改用当前默认'
    else:
        source='使用已保存的自定义门槛，更新软件不覆盖；可点击下方按钮恢复当前默认'
    return (f'红装有效分（{source}）：\n{values}。'
            f'\n成品加权上锁线：左{policy.red_left_gates["15"]+policy.red_lock_score_margin:g}'
            f'/右{policy.red_right_gates["15"]+policy.red_lock_score_margin:g}；保留线不变。'
            f'\n红装+15未重铸速度保留线：{policy.red_raw_speed_keep_min}速。')


def current_red_gate_settings(settings):
    """仅重置红装门槛，保留连接、预算、其他规则和流程设置。"""
    defaults=Policy()
    policy=dict(settings.policy)
    policy.update(red_left_gates=dict(defaults.red_left_gates),red_right_gates=dict(defaults.red_right_gates))
    return replace(settings,policy=policy).validate()


def save_settings(path, settings):
    settings.validate()
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(target)


def discover_mumu(manager_path):
    process = subprocess.run([str(manager_path), "info", "-v", "all"], capture_output=True,
                             timeout=20, check=False,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if process.returncode:
        raise RuntimeError("MuMuManager实例查询失败")
    data = json.loads(process.stdout.decode("utf-8-sig"))
    instances = []
    for index, entry in data.items():
        host, port = entry.get("adb_host_ip"), entry.get("adb_port")
        if entry.get("is_android_started") and host and type(port) is int and 0 < port < 65536:
            instances.append({"index": index, "name": entry.get("name", index), "serial": f"{host}:{port}"})
    return instances
