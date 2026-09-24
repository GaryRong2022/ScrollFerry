"""Coordinate-driven segmentation for mixed-type papers with inline solutions."""
import re
from PIL import ImageOps

Q = re.compile(r'^\s*((?:\d\s*){1,4})[、.．]\s*')
O = re.compile(r'^\s*([A-H])\s*[、.．)）]\s*')
TAG = re.compile(r'^\s*【(答案|解析)】')
SECTION = re.compile(r'^[一二三四五六七八九十]+[、．.]\s*(选择题|单项选择题|单选题|多项选择题|多选题|填空题|解答题|计算题|证明题)')
TYPES = {'选择题':'single_choice','单项选择题':'single_choice','单选题':'single_choice','多项选择题':'multiple_choice','多选题':'multiple_choice','填空题':'fill_blank','解答题':'solution','计算题':'solution','证明题':'solution'}


def segment(source, pages, progress=None):
    from .core import render_page, prefix_box, split_option_lines
    events = []
    for pn, page in enumerate(pages):
        for line in page['lines']:
            text = line['text']
            section, q, option, tag = SECTION.match(text), Q.match(text), O.match(text), TAG.match(text)
            if not any((section, q, option, tag)):
                continue
            # Structural labels must start at the body margin, not inside a formula.
            if line['x0'] > page['width'] * .23:
                continue
            match = section or q or option or tag
            box = prefix_box(line, match.end())
            kind = 'section' if section else 'question' if q else 'option' if option else tag[1]
            events.append({'page':pn, 'line':line, 'kind':kind, 'match':match, 'mask':box,
                           'top':box[1]+.5, 'bottom':box[3]-.5})
    sections = [e for e in events if e['kind']=='section']
    if not sections or not any(e['kind']=='答案' for e in events):
        return None
    margins = [e['line']['x0'] for e in events if e['kind'] in ('question','答案','解析')]
    if not margins:
        return None
    left = max(0, min(margins)-3)
    page_bounds = []
    for pn, page in enumerate(pages):
        if progress:
            progress('分析页面图像与公式边界', pn+1, len(pages))
        img = render_page(source,pn,1)
        # Yellow highlights are background, not character pixels.
        ink = ImageOps.grayscale(img).point(lambda v:255 if v < 170 else 0)
        right = min(page['width']-left+6, page['width']-15)
        band=ink.crop((int(left),0,int(right),img.height))
        occupied=[bool(band.crop((0,y,band.width,y+1)).getbbox()) for y in range(band.height)]
        own=[e for e in events if e['page']==pn]
        previous=0
        for e in own:
            target=max(0,int(e['top']))
            lo=max(previous, target-110)
            gaps=[]; start=None
            for y in range(lo,target+1):
                if not occupied[min(y,len(occupied)-1)]:
                    if start is None:start=y
                elif start is not None:
                    gaps.append((start,y));start=None
            if start is not None:gaps.append((start,target+1))
            big=[g for g in gaps if g[1]-g[0]>=(9 if e['kind']=='question' else 2)]
            gap=(big[-1] if big else gaps[-1]) if gaps else None
            e['cut']=sum(gap)/2 if gap else max(previous,target-3)
            marker_y=(e['top']+e['bottom'])/2
            rects=page.get('rects',[])
            highlights=[r for r in rects if isinstance(r['color'],(list,tuple)) and list(r['color'])==[1,1,0]
                        and abs(r['x0']-e['line']['x0'])<2 and r['top']<=marker_y<=r['bottom']]
            if e['kind'] in ('答案','解析') and highlights:
                e['cut']=min(r['top'] for r in highlights)
            formulas=[r for r in rects if isinstance(r['color'],str) and r['color'].startswith('P')
                      and r['top']<=marker_y<=r['bottom']+5 and r['x0']>e['mask'][2]-2]
            if formulas and e['kind'] in ('question','option'):
                formula_top=min(r['top'] for r in formulas)
                e['cut']=formula_top if e['kind']=='option' else min(e['cut'],formula_top-2)
            previous=min(int(e['bottom'])-2,target+10)
        ink_rows=[y for y,v in enumerate(occupied) if v]
        page_bounds.append((left,right,max(0,min(ink_rows)-3) if ink_rows else 0,min(page['height'],max(ink_rows)+4) if ink_rows else page['height']))
    questions=[]; current=None; active=None; type_name='single_choice'; expected=1
    def regions(start,end):
        out=[]
        for pn in range(start['page'],end['page']+1):
            l,r,top,bottom=page_bounds[pn]
            if pn==start['page']:top=max(top,start['cut'])
            if pn==end['page']:bottom=min(bottom,end['cut'])
            if bottom>top+1:
                masks=[e['mask'] for e in events if e['page']==pn and e['kind'] not in ('section','解析') and e['mask']
                       and e['mask'][1]<bottom and e['mask'][3]>top]
                out.append({'page':pn,'box':[l,top,r,bottom],'masks':masks})
        return out
    def finish(end):
        nonlocal active
        if active and current:
            asset={'kind':active['asset_kind'],'regions':regions(active,end)}
            if active['asset_kind'].startswith('option_'):
                parts = split_option_lines([active['line']], pages[active['page']]['width'])
                if len(parts) > 1:
                    for part in parts:
                        match = O.match(part['text'])
                        if not match:
                            continue
                        clipped = []
                        for reg in asset['regions']:
                            l, t, r, b = reg['box']
                            l, r = max(l, part['x0'] - 1), min(r, part['clip_right'])
                            if r > l:
                                clipped.append(dict(reg, box=[l, t, r, b],
                                                    masks=reg['masks'] + [prefix_box(part, match.end())]))
                        if clipped:
                            current['assets'].append({'kind':'option_'+match[1], 'regions':clipped})
                    active = None
                    return
            if asset['regions']:current['assets'].append(asset)
            if active['asset_kind']=='answer':
                texts=[]
                for reg in asset['regions']:
                    for line in pages[reg['page']]['lines']:
                        if line['top']>=reg['box'][1] and line['bottom']<=reg['box'][3]+3:
                            texts.append(line['text'])
                text=' '.join(texts).replace('【答案】','').strip()
                if current['type'] in ('single_choice','multiple_choice'):
                    letters=re.sub(r'[\s,，、]','',text)
                    current['answer']=letters if re.fullmatch('[A-H]+',letters) else ''
                    if current['answer']:current['assets'].remove(asset)
                else:
                    current['answer']=text
                    has_formula=any(isinstance(r['color'],str) and r['color'].startswith('P')
                        and r['top']>=reg['box'][1]-1 and r['bottom']<=reg['box'][3]+1
                        for reg in asset['regions'] for r in pages[reg['page']].get('rects',[]))
                    current['answer_status']='needs_formula_recognition' if has_formula or not text else 'extracted'
            active=None
    for e in events:
        kind=e['kind']
        if kind=='section':
            finish(e);current=None;type_name=TYPES[e['match'][1]];continue
        if kind=='question':
            number=int(re.sub(r'\s','',e['match'][1]))
            if number != expected:continue
            finish(e)
            current={'id':f'Q{number:04d}','original_number':str(number),'type':type_name,'answer':'','answer_status':'extracted','reviewed':False,'assets':[],'issues':[]}
            questions.append(current);expected+=1
            active=dict(e,asset_kind='stem')
        elif current and kind=='option' and type_name in ('single_choice','multiple_choice') and (not active or active['asset_kind']!='explanation'):
            finish(e);active=dict(e,asset_kind='option_'+e['match'][1])
        elif current and kind in ('答案','解析'):
            finish(e);active=dict(e,asset_kind='answer' if kind=='答案' else 'explanation')
    finish({'page':len(pages)-1,'cut':pages[-1]['height']})
    for q in questions:
        kinds=[a['kind'] for a in q['assets']]
        if q['type'] in ('single_choice','multiple_choice'):
            options = sorted(k[-1] for k in kinds if k.startswith('option_'))
            if len(options) < 2 or options != list('ABCDEFGH'[:len(options)]):
                q['issues'].append('选项数量异常')
            if not q['answer']:q['issues'].append('选择题答案未可靠识别')
        elif q['type']=='fill_blank':
            if q['answer_status']=='needs_formula_recognition':
                q['issues'].append('公式答案已保留截图，文字识别需复核')
        elif not q['answer']:
            q['answer_status']='in_explanation'
        if 'explanation' not in kinds:q['issues'].append('解析未识别')
    return {'version':3,'source':str(source),'questions':questions,'warnings':['填空题公式答案保留原图；文字层无法可靠还原的公式不会伪装成已识别。',
            '截图保持当前 PDF 渲染结果；如果公式已出现异常符号，请先确认原 PDF 的字体显示。']}
