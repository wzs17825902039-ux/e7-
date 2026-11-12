"""用七列卡片外框定位背包行；不识别等级、主属性或副属性文字。"""
from statistics import median

import cv2
import numpy as np
from PIL import Image


def locate_rows(source, tail):
    with Image.open(source) as image:
        pixels=np.asarray(image.convert('RGB').resize((1280,720)))
    edges=cv2.Canny(cv2.cvtColor(pixels,cv2.COLOR_RGB2GRAY),25,65)>0
    contours,_=cv2.findContours(edges.astype(np.uint8)*255,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE)
    candidates=[];gold_candidates=[]
    for contour in contours:
        x,y,w,h=cv2.boundingRect(contour)
        columns=[c for c in range(7) if abs(x-(145+99*c))<=4]
        if len(columns)==1 and 82<=w<=94 and 108<=h<=116 and 147<=y<=610:
            candidates.append((y,columns[0]))
        # 整行选中后只有加厚金框形成闭合轮廓（96×123），不能再按普通卡框尺寸找行。
        gold_columns=[c for c in range(7) if abs(x-(141+99*c))<=2]
        if len(gold_columns)==1 and 94<=w<=100 and 120<=h<=126 and 142<=y<=603:
            patch=pixels[y:y+5,x+8:x+w-8].astype(float)
            gold=((patch[:,:,0]>160)&(patch[:,:,1]>140)&(patch[:,:,2]>70)
                  &(patch[:,:,0]>patch[:,:,2]*1.1))
            if gold.any(axis=0).mean()>=.9:
                # 仅提出锚点，下面仍对七列逐格核对四边，不凭金框补行。
                gold_candidates.append((y+7,gold_columns[0]))
    # 新装备的N标记连接上边框，使整行没有闭合轮廓。用第一列水平线
    # 提出锚点，但仍须七列各自四边全部通过原0.9门槛，不按行距补行。
    for y in range(147,611):
        if len({col for top,col in candidates if abs(top-y)<=8})>=3:
            continue
        # N标记旁的抗锯齿可能把边线分散到三行；与下方逐格取证保持
        # 相同的三行搜索窗口，否则第一列提出锚点时已错过其他列的边线。
        if (edges[y:y+3,150:226].any(axis=0).mean()<.9
                or edges[y+106:y+116,150:226].any(axis=0).mean()<.9):
            continue
        complete=True
        for column in range(7):
            x=145+99*column
            ratios=(edges[y-3:y+5,x+5:x+81].any(axis=0).mean(),
                    edges[y+106:y+116,x+5:x+81].any(axis=0).mean(),
                    edges[y+10:y+101,x-3:x+6].any(axis=1).mean(),
                    edges[y+10:y+101,x+81:x+94].any(axis=1).mean())
            if not all(np.isfinite(r) and r>=.9 for r in ratios):
                complete=False;break
        if complete:
            tops=[]
            for column in range(7):
                x=145+99*column
                actual=[top for top in range(y,y+8)
                        if edges[top:top+2,x+5:x+81].any(axis=0).mean()>=.9]
                if not actual:
                    # 新装备标记叠在外框时，抗锯齿边缘可能分散到三条像素行。
                    # 仍要求同一位置至少90%的水平覆盖及七列完整四边证据。
                    actual=[top for top in range(y,y+8)
                            if edges[top:top+3,x+5:x+81].any(axis=0).mean()>=.9]
                if not actual:break
                top=min(actual)
                # 黄色选中外框在原框上方3像素；先消除这条实际可见的描边，
                # 避免一行选过半后中位数突然上移，卡片内容本身没有移动。
                # 抗锯齿边缘提出的top可能已落在黄色描边下方，须同时查看上方四行。
                brightest=max(range(max(0,top-4),top+4),key=lambda yy:float(pixels[yy,x+5:x+81].mean()))
                line=pixels[brightest,x+5:x+81].astype(float)
                glow=((line[:,0]>180)&(line[:,1]>170)&(line[:,2]>100)
                      &(line[:,0]>line[:,2]*1.1)).mean()
                tops.append((brightest+3 if glow>.8 else top,column))
            if len(tops)==7:
                candidates.extend(tops)
    # 已有完整普通/水平线锚点时沿用其坐标；金框仅补充原定位路径缺失的行。
    # 否则选中数量过半会把同一静止行的裁框向下移动两像素。
    fallback_gold=[(y,column) for y,column in gold_candidates
                   if len({col for top,col in candidates if abs(top-y)<=8})<3]
    candidates.extend(fallback_gold)
    # 加厚金框下沿也会与下一行内容组成伪闭合框；优先已定位的金框锚点，
    # 排除与它重叠、但不属于同一行的候选。真实行距至少120px，不补造任何行。
    gold_groups=[]
    for y,column in sorted(gold_candidates):
        if not gold_groups or abs(y-median(p[0] for p in gold_groups[-1]))>4:
            gold_groups.append([])
        gold_groups[-1].append((y,column))
    gold_anchors=[median(p[0] for p in group) for group in gold_groups if len({p[1] for p in group})>=3]
    candidates=[(y,column) for y,column in candidates
                if not any(4<abs(y-anchor)<120 for anchor in gold_anchors)]
    groups=[]
    for y,column in sorted(candidates):
        if not groups or abs(y-median(p[0] for p in groups[-1]))>4:
            groups.append([])
        groups[-1].append((y,column))
    rows=[]
    for group in groups:
        # 同一卡片的内外边框会生成多个轮廓；每列只用最外层一次投票，
        # 避免内框数量随装备图形变化而把行顶推低数像素。
        outer={column:min(top for top,col in group if col==column)
               for column in {col for _,col in group}}
        y=round(median(outer.values()))
        is_tail=tail.get('end_verified') is True and (
            abs(y-tail['row_top'])<=8 if 'row_top' in tail else 580<=y<=610)
        count=tail.get('tail_count') if is_tail else 7
        if not isinstance(count,int) or not 1<=count<=7:
            continue
        # 图标与外框相接时，闭合轮廓可能仅剩三列；轮廓只提供行锚点，
        # 是否完整仍由下方七列逐格四边证据与最终连续行距共同确认。
        if not is_tail and (y*933/720+7+150>815 or len({p[1] for p in group})<3):
            continue
        accepted=False
        # 发光边缘的轮廓中位数可能落在真实边框上方1像素。
        # 仅在已经有轮廓锚点的附近找完整四边，不借行距推测缺失行。
        for candidate in (y,y-1,y+1,y-2,y+2,y-3,y+3,y-4,y+4):
            complete=True
            for column in range(count):
                x=145+99*column
                ratios=(edges[candidate-3:candidate+5,x+5:x+81].any(axis=0).mean(),
                        edges[candidate+106:candidate+116,x+5:x+81].any(axis=0).mean(),
                        edges[candidate+10:candidate+101,x-3:x+6].any(axis=1).mean(),
                        edges[candidate+10:candidate+101,x+81:x+94].any(axis=1).mean())
                if not all(np.isfinite(r) and r>=.9 for r in ratios):
                    complete=False
                    break
            if complete:
                y=candidate;accepted=True;break
        if accepted:
            rows.append(round(y*933/720)+7)
    if not rows or not 190<=rows[0]<=365 or any(not 155<=b-a<=190 for a,b in zip(rows,rows[1:])):
        raise ValueError('卡片外框未形成连续完整网格，不能跳过未定位行')
    # 勾选边框可能使一行的轮廓中位数变动1像素。用已逐格验证的全部行
    # 拟合标定172像素行距，避免单行裁切漂移；不增加或补齐任何缺行。
    origin=round(median(y-i*172 for i,y in enumerate(rows)))
    fitted=[origin+i*172 for i in range(len(rows))]
    for observed,aligned in zip(rows,fitted):
        if abs(observed-aligned)<=3:
            continue
        # 金框、紫色发光框或等级徽标可能令闭合轮廓锚点偏移。
        # 只校正已有行锚点附近的位置，七列四边仍须全部通过，不补行。
        y=round((aligned-7)*720/933)
        if abs(observed-aligned)>7:
            raise ValueError('外框行距与标定网格不一致')
        count=tail['tail_count'] if (tail.get('end_verified') and 'row_top' in tail
              and abs(y-tail['row_top'])<=8) else 7
        aligned_verified=False
        for target in (y,y-1,y+1):
            complete=True
            for column in range(count):
                x=145+99*column
                ratios=(edges[target-3:target+5,x+5:x+81].any(axis=0).mean(),
                        edges[target+106:target+116,x+5:x+81].any(axis=0).mean(),
                        edges[target+10:target+101,x-3:x+6].any(axis=1).mean(),
                        edges[target+10:target+101,x+81:x+94].any(axis=1).mean())
                if not all(np.isfinite(r) and r>=.9 for r in ratios):
                    complete=False;break
            if complete:
                aligned_verified=True;break
        if not aligned_verified:
            raise ValueError('外框行距与标定网格不一致')
    return fitted
