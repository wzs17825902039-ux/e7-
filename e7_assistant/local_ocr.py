"""本地RapidOCR：仅对指定文字区域识别，不上传截图。"""

from functools import lru_cache
import re
from collections import OrderedDict
from copy import deepcopy
from pathlib import Path
from threading import RLock


@lru_cache(maxsize=1)
def _batch_pool():
    from concurrent.futures import ThreadPoolExecutor
    return ThreadPoolExecutor(max_workers=_runtime_threads()[0], thread_name_prefix='e7-ocr')


def _runtime_threads():
    import os
    cpu=os.cpu_count() or 2
    workers=max(1,min(2,cpu//4))
    threads=max(1,min(8,cpu//workers))
    # 可调度预算共用，避免每组并发推理都创建完整CPU线程池。
    return workers,threads


def field_detection(box,polygon):
    """检测字框须主要属于本字段；擦边或跨字段检测不能参与投票。"""
    x1,y1,x2,y2=box
    left,top=min(p[0] for p in polygon),min(p[1] for p in polygon)
    right,bottom=max(p[0] for p in polygon),max(p[1] for p in polygon)
    if right<=left or bottom<=top:
        return None
    overlap=max(0,min(right,x2)-max(left,x1))/(right-left)
    if not (y1<=(top+bottom)/2<y2 and x1<=(left+right)/2<x2 and overlap>=.6):
        return None
    guided=(max(x1,round(left)),max(0,round(top)),min(x2,round(right)),round(bottom))
    if guided[0]>=guided[2] or guided[1]>=guided[3]:
        return None
    return left,top,right,bottom


def stat_number_box(box,extra_left=0):
    """完整读取和紫装专读共用数字左边界，保留8/6的左笔画。"""
    return (max(0,box[0]-3-extra_left),*box[1:])


class CachedOCREngine:
    """仅复用完全相同的模型输入；不缓存页面判断或装备状态。"""

    def __init__(self, engine, max_entries=4096, max_bytes=32*1024*1024):
        self.engine = engine
        self.max_entries, self.max_bytes = max_entries, max_bytes
        self.cache, self.bytes = OrderedDict(), 0
        self.lock = RLock()
        self.hits = self.misses = 0

    def prefetch(self, images):
        """同一填充宽度的小图成批推理，保留逐图预处理及原来的候选投票。"""
        if self.max_entries <= 0 or not hasattr(self.engine, 'text_rec'):
            return
        options = (('use_cls', False), ('use_det', False))
        with self.lock:
            pending = {}
            for image in images:
                payload = image.tobytes()
                key = (('array', image.shape, image.dtype.str, payload), options)
                if key not in self.cache and key not in pending:
                    pending[key] = (image, len(payload))
            groups = {}
            _, height, width = self.engine.text_rec.rec_image_shape
            for key, (image, size) in pending.items():
                prepared, _, _ = self.engine.preprocess(self.engine.load_img(image))
                padded_width = int(height * max(width/height, prepared.shape[1]/prepared.shape[0]))
                groups.setdefault(padded_width, []).append((key, prepared, size))
            groups = list(groups.values())
            futures = [_batch_pool().submit(self.engine.text_rec, [entry[1] for entry in group])
                       for group in groups]
            for group, future in zip(groups, futures):
                recognized, elapsed = future.result()
                if len(recognized) != len(group):
                    raise RuntimeError('批量OCR结果数量不符')
                for (key, _, size), result in zip(group, recognized):
                    value = ([[result[0], result[1]]], [elapsed/len(group)])
                    if size <= self.max_bytes:
                        self.cache[key] = (deepcopy(value), size)
                        self.bytes += size
                while len(self.cache) > self.max_entries or self.bytes > self.max_bytes:
                    _, (_, removed) = self.cache.popitem(last=False)
                    self.bytes -= removed

    def __call__(self, image, **kwargs):
        import numpy as np
        if isinstance(image, (str, Path)):
            payload = Path(image).read_bytes()
            identity = ('file', payload)
        elif isinstance(image, np.ndarray):
            payload = image.tobytes()
            identity = ('array', image.shape, image.dtype.str, payload)
        else:
            return self.engine(image, **kwargs)
        # 当前调用仅使用布尔推理选项；未来复杂参数保持原路径。
        if any(type(value) not in (bool, int, float, str, type(None)) for value in kwargs.values()):
            return self.engine(image, **kwargs)
        key = (identity, tuple(sorted(kwargs.items())))
        with self.lock:
            if key in self.cache:
                self.hits += 1
                value, size = self.cache.pop(key)
                self.cache[key] = (value, size)
                return deepcopy(value)
            self.misses += 1
            value = self.engine(image, **kwargs)
            # 异常不缓存；结果副本防止调用方修改后污染后续识别。
            size = len(payload)
            if self.max_entries > 0 and size <= self.max_bytes:
                self.cache[key] = (deepcopy(value), size)
                self.bytes += size
                while len(self.cache) > self.max_entries or self.bytes > self.max_bytes:
                    _, (_, removed) = self.cache.popitem(last=False)
                    self.bytes -= removed
            return value


def _value_text(text, key):
    from .vision import normalize
    text = normalize(text)
    if key.startswith('badge') and re.fullmatch(r'\+?\d{1,2}', text):
        # 强化徽标的加号是装饰；相同数字的有/无加号读数应投给同一值。
        return text.lstrip('+')
    if key.startswith('level'):
        # 金色装备装饰可能被OCR读成末尾句点；只接受已支持的完整两位等级。
        # 不补数字，不删除小数点，不将单字5或内部8.5解释为85。
        match=re.fullmatch(r'(85|88|90)[.。]',text)
        if match:
            return match[1]
    if key.startswith('main'):
        match = re.fullmatch(r'(\d{1,3}(?:,\d{3})+|\d+)(%?)(?:\(.*)?', text)
        if match:
            return match[1].replace(',', '') + match[2]
    if key.startswith(('stat', 'main')):
        match = re.fullmatch(r'(\d+%?)(?:\(.*)?', text)
        if match:
            return match[1]
    return text


@lru_cache(maxsize=1)
def _engine():
    try:
        from rapidocr_onnxruntime import RapidOCR
    except ImportError as exc:
        raise RuntimeError("未安装本地OCR依赖，请安装项目ocr可选依赖") from exc
    # 并发组和单组线程共同限额；具体速度需要新版本基准验证。
    _,threads = _runtime_threads()
    return CachedOCREngine(RapidOCR(intra_op_num_threads=threads, inter_op_num_threads=threads))


def _contextual_fast_regions(path, regions, minimum_confidence, detections, inference):
    """提前执行原规则已有的整行/引导裁切共识；不满足则走完整候选路径。"""
    import numpy as np
    from PIL import Image
    pending = {}
    with Image.open(path) as image:
        for key,(x1,y1,x2,y2) in regions.items():
            matches = []
            for polygon,text,confidence in detections or []:
                bounds=field_detection((x1,y1,x2,y2),polygon)
                if bounds is None:
                    continue
                left,top,right,bottom=bounds
                if key.startswith(('stat','main')) and left<x1-40:
                    continue
                matches.append((left,top,right,bottom,text,float(confidence)))
            if len(matches)!=1 or matches[0][5]<minimum_confidence:
                continue
            left,top,right,bottom,text,confidence=matches[0]
            text=_value_text(text,key)
            if key.startswith(('stat','main')) and left<x1:
                text=_value_text(re.sub(r'^[※≥>]+','',text),key)
            pattern=(r'\d+%?' if key.startswith(('stat','main')) else
                     r'\+?\d{1,2}' if key.startswith('badge') else
                     r'\d+' if key.startswith(('score','level')) else None)
            if not text or pattern and not re.fullmatch(pattern,text):
                continue
            box=(max(x1,round(left)),max(0,round(top)),min(x2,round(right)),min(image.height,round(bottom)))
            if box[0]>=box[2] or box[1]>=box[3]:
                continue
            candidate=np.asarray(image.crop(box).convert('RGB'))[:,:,::-1].copy()
            pending[key]=(candidate,text,confidence)
    inference.prefetch([value[0] for value in pending.values()])
    values,details={},{}
    for key,(candidate,text,confidence) in pending.items():
        raw,_=inference(candidate,use_det=False,use_cls=False)
        guided,guided_confidence=raw[0] if raw else ('',0)
        guided=_value_text(guided,key)
        if guided==text and guided_confidence>=minimum_confidence:
            values[key]=text
            details[key]={'text':text,'confidence':max(confidence,float(guided_confidence)),
                          'accepted':True,'fast_context_consensus':True,
                          'candidates':[{'variant':'detected','text':text,'confidence':confidence},
                                        {'variant':'guided','text':guided,'confidence':float(guided_confidence)}]}
    return values,details


def read_local_regions(path, regions, minimum_confidence=.9, detections=None, contrast=False, _inference=None,
                       _skip_context=False):
    import numpy as np
    from PIL import Image, ImageOps

    inference = _inference if _inference is not None else _engine()
    if isinstance(inference,CachedOCREngine) and detections and not _skip_context:
        fast_values,fast_details=_contextual_fast_regions(path,regions,minimum_confidence,detections,inference)
        if fast_values:
            remaining={key:box for key,box in regions.items() if key not in fast_values}
            if remaining:
                rest_values,rest_details=read_local_regions(path,remaining,minimum_confidence,detections,contrast,
                                                            _inference=inference,_skip_context=True)
                fast_values.update(rest_values)
                fast_details.update(rest_details)
            return fast_values,fast_details
    if isinstance(inference, CachedOCREngine) and inference.max_entries > 0:
        # 先收集所有原候选（包含可能需要的扩边），合并推理；正式路径仍按原条件投票。
        requests = []
        def collect(candidate, **kwargs):
            requests.append(candidate.copy())
            # 这里只预取基本四种变体；扩边重试留给实际拒识的字段。
            return [['%', 0]], None
        read_local_regions(path, regions, minimum_confidence, detections, contrast, _inference=collect)
        inference.prefetch(requests)
    result, details = {}, {}
    with Image.open(path) as image:
        for key, box in regions.items():
            x1, y1, x2, y2 = box
            if not (0 <= x1 < x2 <= image.width and 0 <= y1 < y2 <= image.height):
                raise ValueError("本地OCR区域越界")
            patch = image.crop(box).convert("RGB")
            if contrast:
                patch = ImageOps.autocontrast(patch)
            if key.startswith(('stat', 'main')):
                # 当前属性为灰白色，橙色是本次增量；先去除增量再取数字边界。
                pixels = np.array(patch)
                neutral = (pixels.max(axis=2).astype(int) - pixels.min(axis=2).astype(int) < 35)
                pixels[~neutral] = (40, 40, 40)
                patch = Image.fromarray(pixels)
            if key.startswith('badge'):
                patch = ImageOps.grayscale(patch).point(lambda v: 255 if v > 190 else 40).convert('RGB')
            gray = ImageOps.grayscale(patch)
            foreground = gray.point(lambda value: 255 if value > 90 else 0)
            bounds = foreground.getbbox()
            if not bounds:
                result[key] = ""
                details[key] = {"text": "", "confidence": 0}
                continue
            trimmed = patch.crop(bounds)
            enlarged = trimmed.resize((trimmed.width * 3, trimmed.height * 3), Image.Resampling.LANCZOS)
            inverted = ImageOps.invert(ImageOps.autocontrast(ImageOps.grayscale(trimmed))).convert("RGB")
            variants = [("raw", patch), ("trim", trimmed), ("large", enlarged), ("invert", inverted)]
            candidates = []
            for variant, candidate in variants:
                raw, _ = inference(np.asarray(candidate)[:, :, ::-1], use_det=False, use_cls=False)
                text, confidence = raw[0] if raw else ("", 0)
                candidates.append({"variant": variant, "text": _value_text(text, key),"raw_text":text,
                                   "confidence": float(confidence)})
            strong_initial=(not key.startswith('level') and len({c['text'] for c in candidates})==1
                            and bool(candidates[0]['text'])
                            and all(c['confidence']>=max(.98,minimum_confidence) for c in candidates))
            if all('%' not in c['text'] for c in candidates) and not strong_initial:
                padded = ImageOps.expand(trimmed, border=(8, 5), fill=(40, 40, 40))
                contrast_patch = ImageOps.autocontrast(ImageOps.grayscale(padded)).convert("RGB")
                raw, _ = inference(np.asarray(contrast_patch)[:, :, ::-1], use_det=False, use_cls=False)
                text, confidence = raw[0] if raw else ("", 0)
                candidates.append({"variant": "padded-contrast", "text": _value_text(text, key),"raw_text":text,
                                   "confidence": float(confidence)})
                for padding in (2, 3):
                    padded = ImageOps.expand(trimmed, border=padding, fill=(40, 40, 40))
                    raw, _ = inference(np.asarray(padded)[:, :, ::-1], use_det=False, use_cls=False)
                    text, confidence = raw[0] if raw else ('', 0)
                    candidates.append({'variant':f'symmetric-pad-{padding}',
                                       'text':_value_text(text, key),'raw_text':text,'confidence':float(confidence)})
            context = []
            for polygon, detected_text, detected_confidence in detections or []:
                bounds=field_detection((x1,y1,x2,y2),polygon)
                if bounds is None:
                    continue
                left,top,right,bottom=bounds
                if key.startswith(('stat', 'main')) and left < x1 - 40:
                    continue
                # 使用文字检测所得上下边界，防止固定裁切切掉字形上下笔画。
                guided = image.crop((max(x1, round(left)), max(0, round(top)),
                                     min(x2, round(right)), min(image.height, round(bottom)))).convert('RGB')
                raw, _ = inference(np.asarray(guided)[:, :, ::-1], use_det=False, use_cls=False)
                guided_text, guided_confidence = raw[0] if raw else ('', 0)
                guided_text = _value_text(guided_text, key)
                detected_text = _value_text(detected_text, key)
                if key.startswith(('stat', 'main')) and left < x1:
                    # 检测行可能包含属性图标，只去掉已知的非数字图标字形前缀。
                    detected_text = _value_text(re.sub(r'^[※≥>]+', '', detected_text), key)
                context.extend([{'variant':'detected', 'text':detected_text,
                                 'confidence':float(detected_confidence)},
                                {'variant':'guided', 'text':guided_text,
                                 'confidence':float(guided_confidence)}])
            # 原始整行和独立裁切一致时优先采用，避免变色/缩放导致的系统性误读。
            contextual = (len(context) == 2 and context[0]['text'] == context[1]['text']
                          and all(c['confidence'] >= minimum_confidence for c in context))
            candidates.extend(context)
            # 多种预处理可能高置信度地读出不同数字，分歧必须保留为失败。
            votes = {}
            for candidate in candidates:
                pattern = (r'\d+%?' if key.startswith(('stat', 'main')) else
                           r'\+?\d{1,2}' if key.startswith('badge') else
                           r'\d+' if key.startswith(('score', 'level')) else None)
                if pattern and not re.fullmatch(pattern, candidate['text']):
                    continue
                if candidate["text"] and candidate["confidence"] >= .5:
                    votes.setdefault(candidate["text"], []).append(candidate["confidence"])
            ranked = sorted(votes.items(), key=lambda pair: len(pair[1]), reverse=True)
            accepted = bool(ranked and len(ranked[0][1]) >= 2
                            and max(ranked[0][1]) >= minimum_confidence
                            and (len(ranked) == 1 or len(ranked[0][1]) > len(ranked[1][1]))
                            and all(max(values) < minimum_confidence for _, values in ranked[1:]))
            text = ranked[0][0] if accepted else ""
            if contextual and context[0]['text'] in votes:
                text, accepted = context[0]['text'], True
            result[key] = text
            details[key] = {"text": text, "confidence": max(votes[text]) if text else 0,
                            "candidates": candidates, "accepted": accepted}
    return result, details
