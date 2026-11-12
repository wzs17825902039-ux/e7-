"""只导航及切换五个打造来源，记录游戏标题和套装图标；禁止制作输入。"""
import json
from pathlib import Path
import re
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from PIL import Image
from scripts.probe_inventory_traversal import NavigationOnlyAdb
from e7_assistant.adb import Adb
from e7_assistant.forge_loop import number
from e7_assistant.tasks import Journal,TaskControl
from e7_assistant.workflow_navigation import WorkflowNavigator


class SourcePreviewAdb(NavigationOnlyAdb):
    def tap(self,x,y):
        intent=self.intent
        if (intent and intent.get('action')=='forge_source_preview'
                and (intent.get('x'),intent.get('y'))==(x,y)
                and y==108 and x in (200,300,400,500,600)):
            self.intent=None
            Adb.tap(self,x,y)
            self.navigation_taps.append({'action':'forge_source_preview','point':(x,y)})
            return
        super().tap(x,y)


def observe(screen):
    if screen.page!='forge':raise ValueError('未确认工坊页')
    names=[m[1] for w in screen.words if w['confidence']>=.95
           and 910<w['center'][0]<1270 and 75<w['center'][1]<130
           and (m:=re.fullmatch(r'制作装备[【〖](.+)[】〗]',w['text']))]
    if len(names)!=1:raise ValueError('打造来源标题不唯一')
    with Image.open(screen.source) as image:
        if image.size!=(1280,720):raise ValueError('画面尺寸未标定')
        selected=[]
        for index in range(5):
            pixels=list(image.convert('RGB').crop((155+index*100,132,244+index*100,139)).getdata())
            if sum(b>120 and g>110 and b>r*1.1 for r,g,b in pixels)/len(pixels)>=.15:
                selected.append(index)
    if len(selected)!=1:raise ValueError('来源选中图形不唯一')
    gold=int(number(screen,'gold',(665,15,805,55)).replace(',',''))
    return {'index':selected[0],'name':names[0],'gold':gold,'source':screen.source}


def main():
    directory=ROOT/'runs'/('forge-source-catalogue-'+uuid.uuid4().hex[:8])
    control=TaskControl(.8)
    adb=SourcePreviewAdb(r'C:\Program Files\Netease\MuMuPlayer-12.0\nx_main\adb.exe','127.0.0.1:16384',control)
    journal=Journal(directory,adb.event);nav=WorkflowNavigator(adb,directory,control,journal)
    start=observe(nav.navigate('forge'))
    records=[]
    for index in [0,1,2,3,4,start['index']]:
        before=observe(nav.read())
        if before['gold']!=start['gold']:raise ValueError('查看来源期间金币变化，停止')
        x,y=200+100*index,108
        journal.emit('navigation_intent',action='forge_source_preview',x=x,y=y,image=before['source'])
        adb.tap(x,y);control.wait(.5)
        current=observe(nav.read())
        if current['index']!=index or current['gold']!=start['gold']:raise ValueError('切换来源结果不符')
        if len(records)<5:
            path=directory/f'source-{index}-sets.png'
            with Image.open(current['source']) as image:image.crop((920,139,1065,177)).save(path)
            current['sets_image']=str(path)
            records.append(current)
    if len({r['name'] for r in records})!=5:raise ValueError('五个来源名称不唯一')
    result={'sources':records,'restored_index':start['index'],'gold_unchanged':True,
            'resource_confirmations':0,'navigation_taps':adb.navigation_taps}
    (directory/'sources.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'directory':str(directory),**result},ensure_ascii=False))


if __name__=='__main__':main()
