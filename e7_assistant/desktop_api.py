"""本地 WebView 界面桥接；任务只使用点击开始时冻结的配置。"""
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
import json
from pathlib import Path
import threading
import uuid

from .adb import Adb
from .custom_targets import SET_GROUPS, SET_LABELS
from .rules import Policy, RIGHT_MAIN_STATS, TEMPLATES
from .runtime_paths import default_workspace
from .settings import Settings, load_settings, save_settings
from .tasks import Cancelled, Journal, Limits, TaskControl
from .workflow import WorkflowOptions

STAT_LABELS = {'speed':'速度','atk_pct':'攻击%','hp_pct':'生命%','def_pct':'防御%',
               'crit':'暴击率','cdmg':'暴击伤害','effectiveness':'效果命中','resistance':'效果抗性',
               'atk_flat':'固定攻击','hp_flat':'固定生命','def_flat':'固定防御'}
SLOT_LABELS = {'weapon':'武器','helmet':'头盔','armor':'铠甲','necklace':'项链','ring':'戒指','boots':'鞋子'}
TASKS = {'workflow','inventory','legendary','preview_legendary','recover_sale','recover_enhancement',
         'recover_craft','recover_legendary'}
STAGES = {'preflight':'准备任务','navigate_forge':'进入钢铁工坊','initial_cleanup':'清理新装备',
          'select_unenhanced':'选择可强化装备','batch_evaluate':'评估当前批次',
          'post_enhancement_sale':'出售淘汰装备','craft':'打造装备'}


def desktop_workspace():
    """优先复用已有用户目录；项目内发行包与原项目共用回执，避免丢失待核验记录。"""
    current = default_workspace()
    if (current/'config/ui.json').is_file():
        return current
    import sys
    if getattr(sys,'frozen',False):
        for parent in Path(sys.executable).resolve().parents:
            if (parent/'config/ui.json').is_file() and (parent/'e7_assistant').is_dir():
                return parent
    return current


class DesktopApi:
    def __init__(self,workspace=None):
        self.workspace=Path(workspace) if workspace is not None else desktop_workspace()
        self.settings_path=self.workspace/'config/ui.json'
        self._lock=threading.RLock()
        self._control=None
        self._thread=None
        self._sequence=0
        self._logs=[]
        self._load_error=None
        try:
            self._settings=load_settings(self.settings_path)
        except (ValueError,TypeError,OSError) as exc:
            self._settings=Settings()
            self._load_error=str(exc)
        self._state={'busy':False,'paused':False,'status':'准备就绪','phase':'等待开始','connection':'未连接',
                     'statistics':dict.fromkeys(('speed14','speed15','speed16plus','total14plus'),0),
                     'result':None,'task':None,'last_match':None}

    def _event(self,event):
        with self._lock:
            kind=event.get('kind')
            if kind=='enhancement_statistics':
                for key in self._state['statistics']:
                    self._state['statistics'][key]=event[key]
            if kind=='workflow_stage':
                stage=STAGES.get(event.get('stage'))
                if stage:self._state['phase']=stage
            if kind=='batch_entry_verified':self._state['phase']='筛选并强化当前批次'
            if kind=='custom_target_match':
                self._state['last_match']={'names':event['names'],'score':event['score'],'action':event['action']}
            message=None
            if kind=='workflow_stage':message=STAGES.get(event.get('stage'))
            elif kind in {'failed','legendary_failed','stopped'}:message=event.get('message')
            elif kind=='round_finished':message=f"第 {event['round']} 轮已完成"
            elif kind=='workflow_batch_finished':message=f"第 {event['batch']} 批已完成"
            elif kind=='custom_target_match':message=f"发现搭配：{'、'.join(event['names'])}，加权分 {event['score']:g}"
            elif kind=='batch_entry_read_retry':message=f"正在重读装备（{event['attempt']}/{event['max_attempts']}）"
            elif kind=='legendary_craft_settled':message=f"已制作 {event['completed']} 件传说装备"
            elif kind=='legendary_unchanged_charges_verified':message='成品与材料双帧核验通过，制作次数净值未减少，可以继续'
            elif kind=='legendary_auto_recovery_started':
                message='正在自动核对上次制作，核对后继续'
                self._state['phase']=message
            elif kind=='legendary_recovered':message='上次制作结果已确认，继续执行'
            elif kind=='workflow_auto_recovery':
                message='正在自动恢复当前批次，请稍候'
                self._state['phase']=message
            elif kind=='workflow_auto_recovered':message='当前批次已自动恢复，继续任务'
            elif kind=='legendary_observation_retry':
                message=f"正在重读{event['stage']}（{event['attempt']}/{event['max_attempts']}）"
                self._state['phase']=message
            if message:self._notice(message,kind)

    def _notice(self,message,kind='info'):
        self._sequence+=1
        self._logs.append({'id':self._sequence,'time':datetime.now().strftime('%H:%M:%S'),
                           'message':str(message),'kind':kind})
        del self._logs[:-250]

    def _persist(self,settings):
        if self._load_error:
            raise ValueError('原配置损坏，已保留原文件；请先从备份恢复，避免覆盖旧预设')
        if self.settings_path.is_file():
            original=self.settings_path.read_bytes()
            if json.loads(original.decode('utf-8-sig'))!=asdict(settings):
                folder=self.settings_path.parent/'backups'
                folder.mkdir(parents=True,exist_ok=True)
                backup=folder/('ui-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]+'.json')
                backup.write_bytes(original)
        save_settings(self.settings_path,settings)
        self._settings=settings

    def bootstrap(self):
        with self._lock:
            return {'settings':asdict(self._settings),'catalog':{'sets':SET_LABELS,'set_groups':SET_GROUPS,
                    'stats':STAT_LABELS,'slots':SLOT_LABELS,'right_main_stats':RIGHT_MAIN_STATS,
                    'sources':['双足飞龙','魔像','报丧妖','阿吉玛纳克','卡戴斯'],
                    'templates':{key:sorted(value) for key,value in TEMPLATES.items()}},
                    'load_error':self._load_error,'preset_count':len(self._settings.policy.get('custom_targets',[])),
                    'workspace':str(self.workspace)}

    def snapshot(self,after=0):
        with self._lock:
            return {**deepcopy(self._state),'logs':[entry.copy() for entry in self._logs if entry['id']>after],
                    'cursor':self._sequence}

    def save(self,payload):
        with self._lock:
            if self._state['busy']:return {'ok':False,'error':'任务运行中，请停止后保存设置'}
            try:
                settings=Settings(**deepcopy(payload)).validate()
                self._persist(settings)
                self._notice('设置已保存；原配置已自动备份')
                return {'ok':True,'settings':asdict(settings)}
            except (ValueError,TypeError,OSError) as exc:
                return {'ok':False,'error':str(exc)}

    def preset_backups(self):
        """仅列本产品配置与备份，不把演示或测试数据当成用户预设。"""
        with self._lock:
            candidates=[self.settings_path,*sorted((self.settings_path.parent/'backups').glob('*.json'),reverse=True)]
            for base in {default_workspace(),self.workspace}:
                other=base/'config/ui.json'
                if other not in candidates:candidates.append(other)
            found=[]
            for path in candidates:
                try:
                    settings=load_settings(path)
                    rules=settings.policy.get('custom_targets',[])
                    if rules:found.append({'source':str(path),'rules':deepcopy(rules),
                                           'enabled':settings.policy.get('custom_targets_enabled',False)})
                except (ValueError,TypeError,OSError):continue
            return found

    def start(self,task,payload):
        with self._lock:
            if self._state['busy']:return {'ok':False,'error':'已有任务运行'}
            try:
                if task not in TASKS:raise ValueError('未知任务')
                settings=Settings(**deepcopy(payload)).validate()
                if not settings.adb_path or not settings.serial:raise ValueError('请先在设备连接中填写 ADB 路径与实例地址')
                if task in {'legendary','preview_legendary'} and not settings.workflow.get('legendary_set'):
                    raise ValueError('请选择要制作的套装')
                self._persist(settings)
            except (ValueError,TypeError,OSError) as exc:return {'ok':False,'error':str(exc)}
            self._control=TaskControl(settings.workflow['action_interval'])
            self._state.update(busy=True,paused=False,status='正在连接 MuMu',phase='连接设备',connection='连接中',
                               result=None,task=task,last_match=None)
            self._state['statistics']=dict.fromkeys(self._state['statistics'],0)
            self._logs.clear()
            self._notice('任务开始，正在连接已选择的设备')
            self._thread=threading.Thread(target=self._run,args=(task,deepcopy(settings),self._control),
                                          name='e7-desktop-task',daemon=False)
            self._thread.start()
            return {'ok':True}

    def _connect(self,settings,control):
        control.checkpoint()
        adb=Adb(settings.adb_path,settings.serial,control=control,server_port=5039)
        if ':' in settings.serial:adb.connect(settings.serial)
        matching=[line.split() for line in adb.devices().splitlines()
                  if line.split() and line.split()[0]==settings.serial]
        if len(matching)!=1 or matching[0][1]!='device':raise ValueError('指定的 MuMu 实例尚未就绪')
        control.checkpoint()
        return adb

    def _execute(self,task,settings,control,adb):
        from .workflow_navigation import WorkflowNavigator
        directory=self.workspace/'runs'/('desktop-'+uuid.uuid4().hex[:12])
        journal=Journal(directory,self._event)
        navigator=WorkflowNavigator(adb,directory,control,journal)
        options=WorkflowOptions(**settings.workflow)
        if task in {'legendary','preview_legendary','recover_legendary'}:
            from .legendary_crafting import run_legendary,preview_legendary,settle_legendary
            from .tasks import Ledger
            ledger=Ledger(Limits(**settings.limits))
            if task=='legendary':result=run_legendary(navigator,options,ledger,journal)
            elif task=='recover_legendary':result=settle_legendary(navigator,options,ledger,journal)
            else:result=preview_legendary(navigator,options,ledger,options.legendary_set,journal)
        else:
            from .live_workflow import LiveWorkflowTask
            workflow=LiveWorkflowTask(navigator,options,Policy(**settings.policy),Limits(**settings.limits),control,journal)
            if task=='recover_sale':
                result=workflow.resume_pending_batch('sale')
            elif task=='recover_enhancement':
                result=workflow.resume_pending_batch('enhancement')
            elif task=='recover_craft':
                from .craft_recovery import settle_full_craft
                result=settle_full_craft(workflow)
            else:result=workflow.run(inventory_only=task=='inventory')
        (directory/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
        return result

    def _run(self,task,settings,control):
        try:
            adb=self._connect(settings,control)
            with self._lock:
                self._state.update(connection='已连接 '+settings.serial,status='任务运行中',phase='准备执行')
            control.checkpoint()
            result=self._execute(task,settings,control,adb)
            labels={'complete':'任务已完成','stopped':'任务已停止','failed':'任务停止，需要复核',
                    'budget_reached':'已达到任务上限','inventory_full':'装备背包已满',
                    'resources_exhausted':'制作材料不足，任务已结束',
                    'charges_exhausted':'传说制作次数不足','preview_ready':'选择预览已完成，未制作'}
            with self._lock:
                self._state['result']=result
                self._state['status']=labels.get(result.get('state'),'任务已结束')
                self._state['phase']=self._state['status']
                if result.get('state')=='failed' and result.get('message'):
                    self._state['phase']=result['message']
                if result.get('outcome_unknown'):self._state['status']+=' · 存在待核验结果，请勿重复提交'
                if result.get('enhancement_statistics'):
                    self._state['statistics']=result['enhancement_statistics']
                self._notice(self._state['status'])
        except Exception as exc:
            with self._lock:
                self._state.update(status='任务已停止' if isinstance(exc,Cancelled) else '无法继续执行',phase=str(exc))
                self._state['result']={'state':'stopped' if isinstance(exc,Cancelled) else 'failed','message':str(exc)}
                self._notice(str(exc),'failed')
        finally:
            with self._lock:self._state.update(busy=False,paused=False)

    def pause(self):
        with self._lock:
            if not self._state['busy'] or self._control is None:return {'ok':False,'error':'没有正在运行的任务'}
            if self._state['paused']:
                self._control.resume();self._state.update(paused=False,status='任务运行中')
            else:
                self._control.pause();self._state.update(paused=True,status='正在暂停，等待当前操作核对')
            return {'ok':True}

    def stop(self):
        with self._lock:
            if self._control and self._state['busy']:
                self._control.stop()
                self._state.update(paused=False,status='正在停止，等待当前操作核对')
            return {'ok':True}

    def pending(self):
        from .disposal_guard import BatchEnhancementGuard,CraftSessionGuard,DisposalGuard
        with self._lock:
            serial=self._settings.serial
            if not serial:return []
            result=[]
            for cls,folder,label in ((BatchEnhancementGuard,'enhancement-pending','强化'),
                                     (DisposalGuard,'disposal-pending','出售或萃取'),
                                     (CraftSessionGuard,'craft-pending','打造')):
                try:
                    record=cls(self.workspace/'runs'/folder,serial).read()
                    if record:result.append({'type':label,'operation_id':record['operation_id']})
                except (ValueError,OSError) as exc:result.append({'type':label,'error':str(exc)})
            return result

    def choose_adb(self):
        import webview
        result=webview.windows[0].create_file_dialog(webview.FileDialog.OPEN,
            file_types=('ADB executable (*.exe)',))
        return result[0] if result else None

    def discover(self,adb_path):
        from .settings import discover_mumu
        with self._lock:
            if self._state['busy']:return {'ok':False,'error':'任务运行中不能查询实例'}
        manager=Path(adb_path).with_name('MuMuManager.exe')
        if not manager.is_file():
            return {'ok':False,'error':'同目录未找到 MuMuManager.exe，请从 MuMu 实例诊断中填写实际地址'}
        return discover_mumu(manager)

    def export_presets(self,rules):
        from .custom_targets import validate_targets
        import webview
        try:validate_targets(False,rules)
        except (ValueError,TypeError) as exc:return {'ok':False,'error':str(exc)}
        result=webview.windows[0].create_file_dialog(webview.FileDialog.SAVE,
            save_filename='e7-词条预设.json',file_types=('JSON files (*.json)',))
        if not result:return {'ok':True,'cancelled':True}
        path=Path(result if isinstance(result,str) else result[0])
        path.write_text(json.dumps({'format':'e7-custom-targets-v1','custom_targets':rules},
                                   ensure_ascii=False,indent=2),encoding='utf8')
        return {'ok':True,'path':str(path)}

    def validate_presets(self,rules):
        from .custom_targets import validate_targets
        try:
            validate_targets(False,rules)
            return {'ok':True}
        except (ValueError,TypeError) as exc:
            return {'ok':False,'error':str(exc)}
