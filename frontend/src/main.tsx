import React, { useEffect, useRef, useState } from 'react'
import { createRoot } from 'react-dom/client'
import * as Dialog from '@radix-ui/react-dialog'
import * as Select from '@radix-ui/react-select'
import { Anvil, Play, Pause, Square, Settings2, LayoutDashboard, ScrollText, CircleHelp, X,
  ChevronDown, Check, Plus, Pencil, Trash2, Download, Upload, ShieldCheck, Monitor,
  SlidersHorizontal, Gem, Gauge, Coins, ArrowRight, CircleCheck, AlertCircle, LoaderCircle, Save,
  Sparkles, Backpack, Hammer, FolderOpen, RotateCcw } from 'lucide-react'
import './styles.css'

type Config = { adb_path: string; serial: string; policy: Record<string, any>; limits: Record<string, number>; workflow: Record<string, any> }
type Preset = { name: string; sets: string[]; stats: string[] }
type Catalog = { sets: Record<string,string>; set_groups: string[][]; stats: Record<string,string>; slots: Record<string,string>; right_main_stats: Record<string,string[]>; sources: string[]; templates: Record<string,string[]> }
type Log = { id: number; time: string; message: string; kind: string }
type State = { busy: boolean; paused: boolean; status: string; phase: string; connection: string; statistics: Record<string,number>; result: any; task: string; last_match: any; logs: Log[]; cursor: number }
declare global { interface Window { pywebview?: {api: Record<string,(...args:any[])=>Promise<any>>} } }
const tasks = [{id:'workflow',name:'打造并强化',desc:'从工坊到成品，一次完成',icon:Hammer}, {id:'inventory',name:'仅强化背包',desc:'处理已有的可强化装备',icon:Backpack}, {id:'legendary',name:'传说定向制作',desc:'指定套装与部位，逐件制作',icon:Sparkles}]
const categories = [{id:'rules',name:'强化与上锁',icon:ShieldCheck}, {id:'mains',name:'主属性筛选',icon:Gem}, {id:'presets',name:'套装与词条',icon:SlidersHorizontal}, {id:'flow',name:'打造与速度',icon:Gauge}, {id:'budget',name:'资源预算',icon:Coins}, {id:'device',name:'设备连接',icon:Monitor}, {id:'tools',name:'高级与恢复',icon:RotateCcw}]
const stages = ['0','3','6','9','12','15']

function Choice({value,onChange,items,disabled=false}:{value:string;onChange:(value:string)=>void;items:[string,string][];disabled?:boolean}) {
  return <Select.Root value={value} onValueChange={onChange} disabled={disabled}><Select.Trigger className="select"><Select.Value/><Select.Icon><ChevronDown size={15}/></Select.Icon></Select.Trigger><Select.Portal><Select.Content className="select-menu" position="popper" sideOffset={6}><Select.Viewport>{items.map(([key,label])=><Select.Item key={key} value={key} className="select-item"><Select.ItemText>{label}</Select.ItemText><Select.ItemIndicator><Check size={15}/></Select.ItemIndicator></Select.Item>)}</Select.Viewport></Select.Content></Select.Portal></Select.Root>
}
function Toggle({value,onChange,label,description}:{value:boolean;onChange:(value:boolean)=>void;label:string;description?:string}) {
  return <label className="toggle-row"><span><strong>{label}</strong>{description&&<small>{description}</small>}</span><button type="button" className={'switch '+(value?'on':'')} role="switch" aria-label={label} aria-checked={value} onClick={()=>onChange(!value)}><span/></button></label>
}
function Field({label,children,hint}:{label:string;children:React.ReactNode;hint?:string}) { return <label className="field"><span>{label}</span>{children}{hint&&<small>{hint}</small>}</label> }
function Card({title,subtitle,children,className=''}:{title:string;subtitle?:string;children:React.ReactNode;className?:string}) {return <section className={'card '+className}><div className="card-heading"><h3>{title}</h3>{subtitle&&<p>{subtitle}</p>}</div>{children}</section>}
function Modal({open,onOpenChange,title,description,children}:{open:boolean;onOpenChange:(value:boolean)=>void;title:string;description:string;children:React.ReactNode}) {return <Dialog.Root open={open} onOpenChange={onOpenChange}><Dialog.Portal><Dialog.Overlay className="overlay"/><Dialog.Content className="modal"><Dialog.Title>{title}</Dialog.Title><Dialog.Description>{description}</Dialog.Description><Dialog.Close className="icon-button modal-close" aria-label="关闭"><X size={20}/></Dialog.Close>{children}</Dialog.Content></Dialog.Portal></Dialog.Root>}

function App() {
  const [config,setConfig]=useState<Config|null>(null), [catalog,setCatalog]=useState<Catalog|null>(null)
  const [saved,setSaved]=useState(''), [state,setState]=useState<State|null>(null), [logs,setLogs]=useState<Log[]>([])
  const [page,setPage]=useState('tasks'), [section,setSection]=useState('rules'), [task,setTask]=useState('workflow')
  const [help,setHelp]=useState(false), [toast,setToast]=useState(''), [error,setError]=useState('')
  const [edit,setEdit]=useState<{index:number;value:Preset}|null>(null), [pending,setPending]=useState<any[]>([]), [backups,setBackups]=useState<any[]>([])
  const [requesting,setRequesting]=useState(false), [loadError,setLoadError]=useState('')
  const [presetError,setPresetError]=useState('')
  const cursor=useRef(0), initialized=useRef(false), lastBusy=useRef(false), importInput=useRef<HTMLInputElement>(null)
  const busy=!!state?.busy || requesting
  async function call(name:string,...args:any[]) {
    if (!window.pywebview?.api) throw new Error('桌面连接尚未就绪，请使用客户端打开')
    const result=await window.pywebview.api[name](...args)
    if (result?.ok===false) throw new Error(result.error)
    return result
  }
  async function initialize() {
    if (initialized.current || !window.pywebview?.api) return
    initialized.current=true
    try {
      const data=await call('bootstrap')
      const copy=structuredClone(data.settings) as Config
      const group=data.catalog.set_groups[copy.workflow.source_index] as string[]
      if (!group.includes(copy.workflow.legendary_set)) copy.workflow.legendary_set=group.includes('speed')?'speed':group[0]
      setConfig(copy);setSaved(JSON.stringify(copy));setCatalog(data.catalog);setLoadError(data.load_error||'')
      const initial=await call('snapshot',0);setState(initial);setLogs(initial.logs);cursor.current=initial.cursor
      setBackups(await call('preset_backups'));setPending(await call('pending'))
    } catch (e) {initialized.current=false;setError(String(e))}
  }
  useEffect(()=>{
    initialize()
    window.addEventListener('pywebviewready',initialize)
    let inFlight=false,disposed=false
    const timer=window.setInterval(async()=>{
      if (!initialized.current) {initialize();return}
      if (inFlight || !window.pywebview?.api) return
      inFlight=true
      try {const next=await call('snapshot',cursor.current);if(!disposed){if(lastBusy.current&&!next.busy)setPending(await call('pending'));lastBusy.current=next.busy;setState(next);cursor.current=next.cursor;setLogs(old=>[...old,...next.logs].slice(-250))}}
      catch(e){if(!disposed)setError('无法读取任务状态：'+String(e))} finally {inFlight=false}
    },750)
    return ()=>{disposed=true;clearInterval(timer);window.removeEventListener('pywebviewready',initialize)}
  },[])
  useEffect(()=>{if(!toast)return;const timer=setTimeout(()=>setToast(''),4000);return()=>clearTimeout(timer)},[toast])
  useEffect(()=>setPresetError(''),[edit?.index])
  function update(group:'workflow'|'policy'|'limits',key:string,value:any) {setConfig(old=>old?{...old,[group]:{...old[group],[key]:value}}:old)}
  function sourceChanged(value:string) {
    const source=Number(value),group=catalog!.set_groups[source]
    setConfig(old=>old?{...old,workflow:{...old.workflow,source_index:source,legendary_set:group.includes(old.workflow.legendary_set)?old.workflow.legendary_set:group.includes('speed')?'speed':group[0]}}:old)
  }
  async function action(operation:()=>Promise<any>,success?:string) {setRequesting(true);setError('');try {await operation();if(success)setToast(success)}catch(e){setError(String(e).replace(/^Error: /,''))}finally{setRequesting(false)}}
  async function save() {await action(async()=>{const result=await call('save',config);setConfig(result.settings);setSaved(JSON.stringify(result.settings));setBackups(await call('preset_backups'))},'设置已保存，旧配置已备份')}
  async function start(id=task) {await action(async()=>{await call('start',id,config);setSaved(JSON.stringify(config));const next=await call('snapshot',cursor.current);setState(next);cursor.current=next.cursor;setLogs(next.logs)})}
  function numeric(group:'policy'|'workflow'|'limits',key:string,step=1) {return <input type="number" value={config?.[group][key]??''} step={step} onChange={e=>update(group,key,e.target.value===''?'':Number(e.target.value))}/>}
  async function importPresets(file?:File) {
    if(!file)return
    try {const data=JSON.parse(await file.text()),rules=Array.isArray(data)?data:data.custom_targets??data.policy?.custom_targets
      if(!Array.isArray(rules)||!rules.length)throw new Error('文件内没有自定义组合')
      if(rules.some((r:Preset)=>typeof r.name!=='string'||!Array.isArray(r.sets)||!Array.isArray(r.stats)))throw new Error('组合文件格式无效')
      await call('validate_presets',rules)
      update('policy','custom_targets',rules);setToast('已导入到编辑区，确认后点击保存；未自动启用')
    }catch(e){setError(String(e))} finally {if(importInput.current)importInput.current.value=''}
  }
  async function exportPresets() {await action(()=>call('export_presets',config?.policy.custom_targets),'导出操作已结束')}
  function acceptPreset() {
    if(!edit||!config)return
    const value={...edit.value,name:edit.value.name.trim()}
    if(!value.name||value.name.length>40||value.stats.length<1||value.stats.length>4){setPresetError('组合名称需为1～40字，副词条需选择1～4项');return}
    const rules=[...(config.policy.custom_targets||[])]
    if(edit.index<0&&rules.length>=32){setPresetError('最多保存32组组合');return}
    if(rules.some((r,i)=>r.name===value.name&&i!==edit.index)){setPresetError('组合名称不能重复');return}
    if(edit.index<0)rules.push(value);else rules[edit.index]=value
    update('policy','custom_targets',rules);setEdit(null);setPresetError('')
  }
  function togglePreset(key:'sets'|'stats',value:string) {setEdit(old=>old?{...old,value:{...old.value,[key]:old.value[key].includes(value)?old.value[key].filter(v=>v!==value):[...old.value[key],value]}}:old)}
  if(!config||!catalog) return <div className="loading"><Anvil size={42}/><h2>第七史诗打铁助手</h2><p>{error||'正在准备本地界面…'}</p><small>通过桌面客户端打开，本页面不连接外部服务。</small></div>
  const p=config.policy,w=config.workflow,dirty=JSON.stringify(config)!==saved
  const presetRules=(p.custom_targets||[]) as Preset[]
  const sourceChoice=<Choice value={String(w.source_index)} onChange={sourceChanged} items={catalog.sources.map((name,i)=>[String(i),name])}/>
  const slotChoice=<Choice value={w.slot} onChange={v=>update('workflow','slot',v)} items={Object.entries(catalog.slots)}/>
  const speedField=<Field label="操作间隔" hint="默认 0.2 秒，越小越快">{numeric('workflow','action_interval',0.1)}</Field>
  const renderTask=()=> <><div className="page-heading"><div><span className="eyebrow">YOUR PERSONAL WORKSHOP</span><h1>让好装备，留在你的背包。</h1><p>选好任务和目标，其余交给助手。</p></div><span className="badge"><span className="dot"/>国服 · MuMu</span></div>
    <div className="task-picker">{tasks.map(({id,name,desc,icon:Icon})=><button key={id} className={'task-option '+(task===id?'selected':'')} disabled={busy} onClick={()=>setTask(id)}><div className="task-icon"><Icon size={23}/></div><span><strong>{name}</strong><small>{desc}</small></span><span className="radio-mark">{task===id&&<Check size={12}/>}</span></button>)}</div>
    <div className="task-grid"><Card title="任务选项" subtitle="本次开始时保存，后续启动沿用。"><fieldset disabled={busy}><div className="form-grid">
      {task!=='inventory'&&<><Field label="打造来源">{sourceChoice}</Field><Field label="装备部位">{slotChoice}</Field></>}
      {task==='workflow'&&<><Field label="执行轮数">{numeric('workflow','rounds')}</Field><Field label="首次清理"><Choice value={w.initial_disposal} onChange={v=>update('workflow','initial_disposal',v)} items={[["extract","萃取"],["sell","出售"]]}/></Field></>}
      {task==='legendary'&&<><Field label="指定套装"><Choice value={w.legendary_set} onChange={v=>update('workflow','legendary_set',v)} items={catalog.set_groups[w.source_index].map(key=>[key,catalog.sets[key]])}/></Field><Field label="制作件数（留空用完次数）"><input type="number" min={1} max={1000} placeholder="直到传说次数用完" value={w.legendary_count??''} onChange={e=>update('workflow','legendary_count',e.target.value===''?null:Number(e.target.value))}/></Field></>}
      {task==='inventory'&&speedField}
    </div>{task!=='inventory'&&<details className="task-advanced"><summary>更多选项 · {task==='workflow'?`每批 ${w.craft_count} 次 · `:''}{w.action_interval} 秒操作间隔</summary><div className="form-grid">{task==='workflow'&&<Field label="每批打造次数"><Choice value={String(w.craft_count)} onChange={v=>update('workflow','craft_count',Number(v))} items={[["10","10 次（推荐）"],["1","1 次"]]}/></Field>}{speedField}</div><Toggle label="统计打造材料消耗" description="默认关闭；识别失败不影响制作，材料不足时停止。" value={!!w.track_craft_consumption} onChange={v=>update('workflow','track_craft_consumption',v)}/></details>}</fieldset><div className="task-note"><ShieldCheck size={18}/><span>{task==='workflow'?'打造至背包满 → 清理 → 逐档强化 → 保留上锁':task==='inventory'?'从背包顶部选择可强化装备，按当前规则处理。':'仅制作指定套装与部位，完成后停止。'}</span></div><button className="text-button" onClick={()=>{setPage('settings');setSection('rules')}}>调整强化规则与预设 <ArrowRight size={15}/></button></Card>
    <Card title="本轮强化成果" subtitle="从本次开始到任务结束统计，下次开始重置。" className="results-card"><div className="results-total"><span>{state?.statistics.total14plus??0}</span><small>件 14 速及以上装备</small></div><div className="stat-row">{[['speed14','14 速'],['speed15','15 速'],['speed16plus','16 速及以上']].map(([key,label])=><div key={key}><strong>{state?.statistics[key]??0}</strong><small>{label}</small></div>)}</div><div className="match-note"><Gem size={17}/>{state?.last_match?`发现「${state.last_match.names.join('、')}」 · ${state.last_match.score} 分`:p.custom_targets_enabled?`已启用 ${presetRules.length} 组自定义搭配`:'自定义搭配未启用'}</div></Card></div>
    <Card title="运行动态" className="activity"><div className="activity-status"><span className={'status-orb '+(state?.busy?'running':'')}>{state?.busy?<LoaderCircle size={19} className="spin"/>:<CircleCheck size={19}/>}</span><div><strong>{state?.status||'准备就绪'}</strong><p>{state?.phase||'等待开始'}</p></div></div><div className="activity-lines">{logs.slice(-3).map(log=><p key={log.id}><time>{log.time}</time>{log.message}</p>)}</div></Card></>
  const rulesPage=()=> <><Card title="速度与保留" subtitle="速度优先；红装速度不佳时，再按有效加权分判断。"><div className="form-grid three">{[['initial_speed_min','初始速度最低值'],['purple_plus6_speed_min','紫装 +6 速度线'],['purple_plus9_speed_min','紫装 +9 速度线'],['retain_speed_min','可选保留速度'],['priority_speed_min','优先保留速度'],['red_raw_speed_keep_min','红装未重铸保留速度']].map(([key,label])=><Field key={key} label={label}>{numeric('policy',key)}</Field>)}</div></Card><Card title="强化与处置"><Toggle label="不按装备等级筛选" description="背包选装省略逐件装备等级核验" value={p.ignore_equipment_level} onChange={v=>update('policy','ignore_equipment_level',v)}/><Toggle label="出售明确淘汰的紫装" description="紫装只追速度，紫装鞋子不强化；已锁装备不自动解锁出售" value={p.sell_failed_purple} onChange={v=>update('policy','sell_failed_purple',v)}/><Toggle label="使用红装用途有效分" description="包含输出、生存等用途模板；输出用途计入生命%与防御%" value={p.red_profile_enabled} onChange={v=>update('policy','red_profile_enabled',v)}/><Toggle label="出售明确淘汰的红装" description="用途或识别不明确的装备暂存" value={p.sell_failed_red} onChange={v=>update('policy','sell_failed_red',v)}/><div className="form-grid spacing"><Field label="红装上锁分比保留线增加">{numeric('policy','red_lock_score_margin',0.5)}</Field></div></Card><Card title="红装有效分门槛" subtitle="初始与各强化节点分别判断；带速红装仍遵循竞速规则。"><div className="score-table"><div className="score-header"><span>装备位置</span>{stages.map(s=><span key={s}>{s==='0'?'初始':'+'+s}</span>)}</div>{[['left','左三件'],['right','右三件']].map(([side,label])=><div className="score-inputs" key={side}><span>{label}</span>{stages.map(s=><input key={s} type="number" aria-label={label+' '+s+'门槛'} value={p['red_'+side+'_gates'][s]} onChange={e=>update('policy','red_'+side+'_gates',{...p['red_'+side+'_gates'],[s]:Number(e.target.value)})}/>)}</div>)}</div></Card></>
  const presetPage=()=> <><Card title="我的词条预设" subtitle="指定套装与副词条组合。仅红装命中后按全部副词条加权分筛选，紫装沿用原规则。"><Toggle label="启用自定义搭配" description={presetRules.length?`已保存 / 编辑 ${presetRules.length} 组组合`:'先添加或导入组合，再启用'} value={p.custom_targets_enabled} onChange={v=>update('policy','custom_targets_enabled',v)}/><div className="toolbar"><button className="button secondary" onClick={()=>setEdit({index:-1,value:{name:'',sets:[],stats:[]}})}><Plus size={16}/>添加组合</button><button className="button ghost" onClick={()=>importInput.current?.click()}><Upload size={16}/>导入</button><button className="button ghost" onClick={exportPresets}><Download size={16}/>导出</button><input type="file" ref={importInput} hidden accept=".json" onChange={e=>importPresets(e.target.files?.[0])}/></div>
    {!presetRules.length?<div className="empty"><SlidersHorizontal size={28}/><h4>尚未找到已保存的组合</h4><p>可从旧备份导入；这里不会自动填入演示预设。</p></div>:<div className="preset-list">{presetRules.map((rule,index)=><div className="preset" key={index}><div><h4>{rule.name}</h4><p>{rule.sets.map(key=>catalog.sets[key]).join(' / ')||'任意套装'}</p><div className="chips">{rule.stats.map(key=><span key={key}>{catalog.stats[key]}</span>)}</div></div><div className="row"><button className="icon-button" aria-label={'编辑'+rule.name} onClick={()=>setEdit({index,value:structuredClone(rule)})}><Pencil size={17}/></button><button className="icon-button danger" aria-label={'删除'+rule.name} onClick={()=>update('policy','custom_targets',presetRules.filter((_,i)=>i!==index))}><Trash2 size={17}/></button></div></div>)}</div>}
    {!!backups.length&&<div className="backup-box"><h4>找到的已保存配置</h4>{backups.map((entry,i)=><div key={i}><span>{entry.rules.length} 组组合 · {entry.source.split(/[\\/]/).slice(-1)[0]}</span><button className="text-button" onClick={()=>{update('policy','custom_targets',entry.rules);setToast('已载入编辑区，请确认后保存')}}>载入</button></div>)}</div>}</Card><Card title="自定义组合的分数门槛" subtitle="留空使用通用红装门槛，适用于命中上述组合的红装。"><div className="score-table"><div className="score-header"><span>装备位置</span>{stages.map(s=><span key={s}>{s==='0'?'初始':'+'+s}</span>)}</div>{[['left','左三件'],['right','右三件']].map(([side,label])=><div className="score-inputs" key={side}><span>{label}</span>{stages.map(s=><input key={s} type="number" placeholder={String(p['red_'+side+'_gates'][s])} aria-label={label+'自定义'+s} value={p['custom_'+side+'_gates']?.[s]??''} onChange={e=>{const gates={...p['custom_'+side+'_gates']};if(e.target.value==='')delete gates[s];else gates[s]=Number(e.target.value);update('policy','custom_'+side+'_gates',gates)}}/>)}</div>)}</div></Card></>
  const settingsBody=()=>{
    if(section==='rules')return <><div className="callout"><Gem size={18}/><span>红装 +12 节点副速度达到 12 速，继续强化到 +15，不受未加速次数或有效分限制；成品仍按最终速度与有效分判断。</span></div>{rulesPage()}</>
    if(section==='presets')return presetPage()
    if(section==='mains')return <><div className="callout"><Gem size={18}/><span>紫装项链、戒指只看副速度，紫装鞋子不强化；固定主属性保留带速例外。</span></div>{Object.entries(catalog.right_main_stats).map(([slot,stats])=><Card key={slot} title={catalog.slots[slot]} subtitle="选择允许强化的主属性"><div className="main-stat-grid">{stats.map(key=>{const selected=(p.right_main_stats[slot]||[]).includes(key);return <button key={key} className={'choice-chip '+(selected?'active':'')} aria-pressed={selected} onClick={()=>update('policy','right_main_stats',{...p.right_main_stats,[slot]:selected?p.right_main_stats[slot].filter((s:string)=>s!==key):[...(p.right_main_stats[slot]||[]),key]})}><span>{selected?<Check size={13}/>:null}</span>{catalog.stats[key]}</button>})}</div></Card>)}</>
    if(section==='flow')return <><Card title="打造偏好"><div className="form-grid"><Field label="打造来源">{sourceChoice}</Field><Field label="装备部位">{slotChoice}</Field><Field label="每批打造次数"><Choice value={String(w.craft_count)} onChange={v=>update('workflow','craft_count',Number(v))} items={[["10","10 次"],["1","1 次"]]}/></Field><Field label="执行轮数">{numeric('workflow','rounds')}</Field><Field label="首次清理"><Choice value={w.initial_disposal} onChange={v=>update('workflow','initial_disposal',v)} items={[["extract","萃取"],["sell","出售"]]}/></Field><Field label="无速红装强化起点"><Choice value={String(w.first_target)} onChange={v=>update('workflow','first_target',Number(v))} items={[["3","+3"],["6","+6"]]}/></Field></div></Card><Card title="响应与扫描"><div className="form-grid">{speedField}<Field label="背包扫描页数上限">{numeric('workflow','scan_pages')}</Field></div></Card></>
    if(section==='budget')return <Card title="任务预算" subtitle="制作按结果与剩余次数推进，材料不足时停止。材料统计不完整时不显示为已核实消耗。"><Toggle label="统计打造材料消耗" description="默认关闭；识别失败不阻塞任务。普通及传说打造不再强制执行材料金额预算。" value={!!w.track_craft_consumption} onChange={v=>update('workflow','track_craft_consumption',v)}/><div className="form-grid"><Field label="任务操作次数上限">{numeric('limits','max_steps')}</Field></div><details><summary>旧模式兼容预算（不用于当前结果驱动打造）</summary><div className="form-grid">{Object.keys(config.limits).filter(key=>key!=='max_steps').map(key=><Field key={key} label={({craft_material:'打造材料上限（旧模式）',gold:'金币',powder:'装备粉末',lesser_stone:'下级装备石',greater_stone:'上级装备石',epic_stone:'传说装备石',jewelry_powder:'饰品粉末',jewelry_lesser_stone:'下级饰品石',jewelry_greater_stone:'上级饰品石',jewelry_epic_stone:'传说饰品石'} as Record<string,string>)[key]||key}>{numeric('limits',key)}</Field>)}</div></details></Card>
    if(section==='device')return <Card title="MuMu 设备连接" subtitle="首次配置后，点击开始会自动连接所选实例。"><Field label="ADB 程序路径"><div className="input-action"><input value={config.adb_path} onChange={e=>setConfig({...config,adb_path:e.target.value})}/><button className="button secondary" onClick={()=>action(async()=>{const path=await call('choose_adb');if(path)setConfig({...config,adb_path:path})})}><FolderOpen size={16}/>选择</button></div></Field><Field label="实例地址" hint="填写 MuMu 实例诊断中的实际地址与端口"><input value={config.serial} onChange={e=>setConfig({...config,serial:e.target.value})} placeholder="127.0.0.1:16384"/></Field><p className="muted spacing">当前状态：{state?.connection}</p><button className="button secondary" onClick={()=>action(async()=>{const list=await call('discover',config.adb_path);if(list.length===1)setConfig({...config,serial:list[0].serial});setToast(list.length===1?'已填入发现的实例':'发现多个实例，请根据实例诊断选择地址')})}><Monitor size={16}/>查找 MuMu 实例</button></Card>
    return <><Card title="待核验记录" subtitle="恢复会先核验既有提交，之后继续强化剩余背包；不会重发旧确认。">{pending.length?pending.map((entry,i)=><div className="pending-item" key={i}><AlertCircle size={18}/><span>{entry.type} · {entry.error||'存在未结算提交'}</span></div>):<p className="muted">未发现待核验记录</p>}<div className="toolbar">{[['recover_sale','核验出售并继续背包'],['recover_enhancement','核验强化并继续背包'],['recover_craft','核验满包打造'],['recover_legendary','核验传说制作']].map(([id,label])=><button className="button secondary" key={id} onClick={()=>start(id)}>{label}</button>)}</div></Card><Card title="只走选择流程" subtitle="会进入游戏界面并完成套装选择，但不点击制作。"><button className="button secondary" onClick={()=>start('preview_legendary')}>预览当前传说制作选项 <ArrowRight size={15}/></button></Card></>
  }
  return <div className="app"><aside className="sidebar"><div className="brand"><div className="brand-icon"><Anvil size={25}/></div><div><strong>E7 FORGE</strong><small>第七史诗 · 打铁助手</small></div></div><div className="nav-label">我的工坊</div><nav>{[{id:'tasks',label:'任务',icon:LayoutDashboard},{id:'settings',label:'设置',icon:Settings2},{id:'history',label:'运行记录',icon:ScrollText}].map(({id,label,icon:Icon})=><button key={id} className={page===id?'active':''} onClick={()=>setPage(id)}><Icon size={19}/>{label}{page===id&&<span className="nav-active"/>}</button>)}</nav><div className="sidebar-bottom"><div className="local-badge"><ShieldCheck size={15}/>本地运行 · 本地识别</div><span>桌面前端预览 · 0.4</span></div></aside><div className="workspace"><header className="topbar"><span>{page==='tasks'?'任务中心':page==='settings'?'偏好设置':'运行记录'}</span><div className="row"><span className="connection"><span className={'dot '+(state?.connection.startsWith('已连接')?'online':'')}/>{state?.connection.startsWith('已连接')?'MuMu 已连接':'等待连接'}</span><button className="icon-button" onClick={()=>setHelp(true)} aria-label="帮助"><CircleHelp size={20}/></button></div></header>
    {error&&<div className="alert"><AlertCircle size={18}/><span>{error}</span><button className="icon-button" onClick={()=>setError('')} aria-label="关闭错误"><X size={16}/></button></div>}{loadError&&<div className="alert">原配置无法读取，已保留原文件：{loadError}</div>}
    <main className={page==='settings'?'settings-main':''}>{page==='tasks'?renderTask():page==='history'?<><div className="page-heading"><div><span className="eyebrow">ACTIVITY</span><h1>运行记录</h1><p>查看本次客户端的任务动态，详细证据保存在本地。</p></div></div><Card title="任务动态">{logs.length?<div className="log-list">{logs.map(log=><div key={log.id} className={log.kind==='failed'?'error-log':''}><time>{log.time}</time><span>{log.message}</span></div>)}</div>:<div className="empty"><ScrollText size={30}/><h4>还没有运行记录</h4><p>开始任务后，进度会显示在这里。</p></div>}</Card></>:<><div className="settings-heading"><div><h1>按你的习惯打铁</h1><p>设置会保留，首页只需选好任务并开始。</p></div><button className="button primary" disabled={busy||!!loadError} onClick={save}><Save size={16}/>{dirty?'保存修改':'保存设置'}</button></div><div className="settings-layout"><nav className="settings-nav">{categories.map(({id,name,icon:Icon})=><button className={section===id?'active':''} key={id} onClick={()=>setSection(id)}><Icon size={17}/>{name}{id==='presets'&&!!presetRules.length&&<em>{presetRules.length}</em>}</button>)}</nav><fieldset className="settings-content" disabled={busy}>{settingsBody()}</fieldset></div></>}</main>
    <footer className="controlbar"><div className="footer-status"><span className={'dot '+(state?.busy?'online':'')}/><div><strong>{state?.status||'准备就绪'}</strong><small>{dirty?'有未保存修改，开始时会自动保存':state?.phase||'选择任务，开始打造'}</small></div></div><div className="row"><button className="button secondary" disabled={!state?.busy} onClick={()=>action(()=>call('stop'))}><Square size={15}/>停止</button><button className="button secondary" disabled={!state?.busy} onClick={()=>action(()=>call('pause'))}>{state?.paused?<Play size={15}/>:<Pause size={15}/>} {state?.paused?'继续':'暂停'}</button><button className="button primary start-button" disabled={busy||!!loadError} onClick={()=>start()}>{busy?<LoaderCircle className="spin" size={18}/>:<Play size={18}/>} {busy?'任务进行中':'开始任务'}</button></div></footer></div>
    {toast&&<div className="toast" role="status"><CircleCheck size={18}/>{toast}</div>}
    {presetError&&<div className="toast error-toast" role="alert"><AlertCircle size={18}/>{presetError}</div>}
    <Modal open={help} onOpenChange={setHelp} title="选好任务，点击开始" description="首次使用先在设置中配置 MuMu，之后沿用。"><div className="help-steps">{[['01','选择任务','打造并强化、仅强化背包，或传说定向制作。'],['02','确认偏好','部位、套装与数量在任务页；词条预设在设置中。'],['03','开始运行','自动连接设备，按规则强化、保留上锁。']].map(([n,title,desc])=><div key={n}><span>{n}</span><section><h4>{title}</h4><p>{desc}</p></section></div>)}</div><p className="muted">暂停或停止会等待当前操作核对。结果待核验时，请使用高级与恢复入口。自定义搭配仅用于红装。</p><button className="button primary full" onClick={()=>setHelp(false)}>知道了</button></Modal>
    <Modal open={!!edit} onOpenChange={open=>{if(!open)setEdit(null)}} title={edit?.index===-1?'添加词条组合':'编辑词条组合'} description="套装满足任意一个，所选副词条必须同时具备。">{edit&&<><Field label="组合名称"><input value={edit.value.name} placeholder="例如：速度套输出胚子" onChange={e=>setEdit({...edit,value:{...edit.value,name:e.target.value}})}/></Field><div className="modal-section"><h4>装备套装 <small>不选则不限套装</small></h4><div className="chips selectable">{Object.entries(catalog.sets).map(([key,label])=><button className={edit.value.sets.includes(key)?'active':''} onClick={()=>togglePreset('sets',key)} key={key}>{label}</button>)}</div></div><div className="modal-section"><h4>指定副词条 <small>选择 1～4 项</small></h4><div className="chips selectable">{Object.entries(catalog.stats).map(([key,label])=><button className={edit.value.stats.includes(key)?'active':''} onClick={()=>togglePreset('stats',key)} key={key}>{label}</button>)}</div></div><div className="modal-actions"><button className="button ghost" onClick={()=>setEdit(null)}>取消</button><button className="button primary" onClick={acceptPreset}>确认组合</button></div></>}</Modal>
  </div>
}

createRoot(document.getElementById('root')!).render(<App/> )
