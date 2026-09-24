"""Match a question paper to a separate solution paper by explicit question number."""
import copy
import re
import unicodedata
from pathlib import Path

from .core import OPTION, QUESTION, prefix_box, split_option_lines

SHARED = re.compile(r'^\s*(\d+)\s*[~～—–-]\s*(\d+)\s*题基于以下题[干⼲]')
SECTION = re.compile(r'^(?:[一二三四五六七八九十]+[、.．]\s*)?(单项选择题|多项选择题|名词解释|简答题|论述题|计算题|解答题|证明题|填空题|单选题|多选题|选择题|数学|逻辑|写作|单选|选择|多选|填空|解答|计算|证明)(?=\s|[（(]|基础|推理|部分|$)')
ANSWER_LABEL = re.compile(r'【\s*(?:参考)?答案\s*】|(?:参考)?答案\s*[:：]')

def section_name(label):
    return {'单项选择题':'单选','单选题':'单选','选择题':'单选','选择':'单选',
            '多项选择题':'多选','多选题':'多选','计算题':'计算','解答题':'解答',
            '证明题':'证明','填空题':'填空'}.get(label,label)
WRITING = re.compile(r'^\s*\d+\s*[.．、]\s*(论证有效性分析|论说文)')
SEPARATE_ANSWER = re.compile(r'(?:【\s*(?:参考)?答案\s*】|(?:参考)?答案\s*[:：])\s*([A-H](?:[A-H\s,，、]*[A-H])?)(?=\s|[.。；;【]|$)')


def clean(text):
    return unicodedata.normalize('NFKC', text)


class Paper:
    def __init__(self, pages, offset=0):
        self.pages, self.offset = pages, offset
        self.lines, self.bounds = [], []
        from collections import Counter
        headers = Counter(text for page in pages for text in {l['text'].strip() for l in page['lines'] if l['top'] < page['height']*.12})
        for pn, page in enumerate(pages):
            lines = [l for l in page['lines'] if l['bottom']-l['top'] < 65
                     and not (l['top'] < page['height']*.12 and headers[l['text'].strip()] >= 2)
                     and not (l['top'] > page['height']*.85 and re.fullmatch(r'(?:第\s*)?\d+\s*(?:页\s*共\s*\d+\s*页)?', l['text'].strip()))]
            # Inline labels may have different baselines beside tall formula images.
            grouped = []
            for line in lines:
                if grouped and OPTION.match(line['text']) and OPTION.match(grouped[-1]['text']):
                    prev = grouped[-1]
                    if abs(line['top']-prev['top']) < 14 and (line['x0'] >= prev.get('x1', page['width']) or prev['x0'] >= line.get('x1', page['width'])):
                        parts = sorted([prev, line], key=lambda l:l['x0'])
                        grouped[-1] = dict(parts[0], text=' '.join(l['text'] for l in parts),
                                           chars=[c for l in parts for c in l['chars']],
                                           top=min(l['top'] for l in parts), bottom=max(l['bottom'] for l in parts),
                                           x1=max(l['x1'] for l in parts))
                        continue
                grouped.append(line)
            lines = grouped
            images = [i for i in page.get('images', []) if i['bottom']-i['top'] < page['height']*.8]
            content = lines + images
            self.bounds.append((max(0, min((l['top'] for l in content), default=20)-3),
                                min(page['height'], max((l['bottom'] for l in content), default=page['height']-20)+3)))
            self.lines.extend((pn, l) for l in lines)

    def event(self, pn, line, **kwargs):
        top = line['top']
        mid = (line['top']+line['bottom'])/2
        for img in self.pages[pn].get('images', []):
            if img['top'] <= mid <= img['bottom'] and img['bottom']-img['top'] < 120:
                top = min(top, img['top'])
        cut = max(0, top-4)
        # Some adjacent formula images have less than four points of whitespace.
        # Put the shared boundary inside that gap, never through the prior image.
        previous = [i['bottom'] for i in self.pages[pn].get('images', [])
                    if cut < i['bottom'] <= top]
        if previous:
            cut = (max(previous)+top)/2
        return dict(page=pn, cut=cut, line=line, **kwargs)

    def regions(self, start, end, mask=None, left=None, right=None):
        result = []
        for pn in range(start['page'], end['page']+1):
            top, bottom = self.bounds[pn]
            if pn == start['page']:
                top = max(top, start['cut'])
            if pn == end['page']:
                bottom = min(bottom, end['cut'])
            if bottom <= top+1:
                continue
            page = self.pages[pn]
            result.append({'page': pn+self.offset,
                           'box': [left if left is not None else 20, top,
                                   right if right is not None else page['width']-20, bottom],
                           'masks': [mask] if mask and pn == start['page'] else []})
        return result

    def end(self):
        return {'page': len(self.pages)-1, 'cut': self.pages[-1]['height']}


def detect_separate(source, answer_source, pages, answer_pages, progress=None):
    paper, solutions = Paper(pages), Paper(answer_pages, len(pages))
    events = []
    for pn, line in paper.lines:
        text = clean(line['text'])
        q, shared, section, option = QUESTION.match(text), SHARED.match(text), SECTION.match(text), OPTION.match(text)
        if line['x0'] > pages[pn]['width']*.25 and not option:
            continue
        if q or shared or section or option:
            events.append(paper.event(pn, line, kind='shared' if shared else 'section' if section else 'question' if q else 'option',
                                      match=shared or section or q or option))
    questions, current, active, shared_block = [], None, None, None
    type_name = 'single_choice'
    section_key = ''

    def finish(end):
        nonlocal active, shared_block
        if not active:
            return
        if active['kind'] == 'shared':
            shared_block = (int(active['match'][1]), int(active['match'][2]), paper.regions(active, end))
        elif current:
            if active['kind'] == 'question':
                regs = paper.regions(active, end, prefix_box(active['line'], active['match'].end()))
                if shared_block and shared_block[0] <= int(current['original_number']) <= shared_block[1]:
                    regs = copy.deepcopy(shared_block[2]) + regs
                    current['shared_range'] = list(shared_block[:2])
                current['assets'].append({'kind':'stem', 'regions':regs})
            else:
                parts = split_option_lines([active['line']], pages[active['page']]['width'])
                for part in parts:
                    match = OPTION.match(part['text'])
                    if not match:
                        continue
                    inline = len(parts)>1
                    regs = paper.regions(active, end, prefix_box(part, match.end()),
                                         part['x0']-1 if inline else None,
                                         part.get('clip_right') if inline else None)
                    current['assets'].append({'kind':'option_'+match[1], 'regions':regs})
        active = None

    for e in events:
        if progress:
            progress('识别独立题目卷', e['page']+1, len(pages))
        if e['kind'] == 'section':
            finish(e)
            current, shared_block = None, None
            label = section_name(e['match'][1])
            section_key = label
            type_name = 'solution' if label in ('写作','解答','计算','证明','名词解释','简答题','论述题') else 'fill_blank' if label=='填空' else 'multiple_choice' if label=='多选' else 'single_choice'
        elif e['kind'] == 'shared':
            finish(e)
            current = None
            active = e
        elif e['kind'] == 'question':
            finish(e)
            number = e['match'][1]
            writing = WRITING.match(clean(e['line']['text']))
            current = {'id':f'Q{len(questions)+1:04d}', 'original_number':number,
                       'type':'solution' if writing else type_name, 'section':section_key, 'answer':'', 'answer_status':'missing',
                       'reviewed':False, 'assets':[], 'issues':[]}
            if writing:
                current['subtype'] = writing[1]
            elif type_name == 'solution':
                current['subtype'] = section_key
            questions.append(current)
            active = e
        elif current and current['type'] in ('single_choice','multiple_choice'):
            finish(e)
            active = e
    finish(paper.end())
    if not questions:
        raise ValueError('题目卷未识别到题目；请检查文件顺序和文字层')

    # Only explicit answer labels or writing titles start a solution. Numbered
    # reasoning steps such as "1. ..." inside an explanation are not questions.
    boundaries = []
    section_key = ''
    for pn, line in solutions.lines:
        text = clean(line['text'])
        q, section = QUESTION.match(text), SECTION.match(text)
        ans, writing = SEPARATE_ANSWER.search(text), WRITING.match(text)
        if line['x0'] > answer_pages[pn]['width']*.25:
            continue
        if section:
            section_key = section_name(section[1])
            boundaries.append(solutions.event(pn,line,number=None,section=section_key,answer=''))
        elif q and (ANSWER_LABEL.search(text) or writing):
            boundaries.append(solutions.event(pn,line,number=q[1],section=section_key,answer=ans[1] if ans else ''))
        elif not q and ANSWER_LABEL.match(text):
            # An unnumbered reference answer is safe only in a one-question section.
            candidates = [question for question in questions if question['section']==section_key]
            if len(candidates)==1:
                boundaries.append(solutions.event(pn,line,number=candidates[0]['original_number'],
                                                  section=section_key,answer=ans[1] if ans else ''))
    matches = {}
    for i, start in enumerate(boundaries):
        if start['number'] is None:
            continue
        end = boundaries[i+1] if i+1<len(boundaries) else solutions.end()
        matches.setdefault((start['section'],start['number']), []).append((start, end))
    warnings = []
    numbers = [(q['section'],q['original_number']) for q in questions]
    used_matches = set()
    for q in questions:
        number = (q['section'],q['original_number'])
        candidates = matches.get(number, [])
        match_key = number
        if not candidates and sum(n[1]==number[1] for n in numbers)==1:
            alternatives = [key for key in matches if key[1]==number[1]]
            if len(alternatives)==1:
                match_key = alternatives[0]
                candidates = matches[match_key]
        if len(candidates) == 1 and numbers.count(number) == 1:
            start, end = candidates[0]
            used_matches.add(match_key)
            q['answer'] = re.sub(r'[\s,，、]', '', start['answer'])
            # Keep the answer header with its explanation, hiding only the number.
            # This also preserves writing reference ideas without inventing an answer.
            m = QUESTION.match(clean(start['line']['text']))
            q['assets'].append({'kind':'explanation', 'regions':solutions.regions(start, end, prefix_box(start['line'], m.end()) if m else None)})
            q['answer_status'] = 'extracted' if q['answer'] else 'in_explanation'
        else:
            q['issues'].append('题号重复，无法可靠匹配解析' if candidates or numbers.count(number)>1 else '未匹配到答案解析')
        options = [a['kind'][-1] for a in q['assets'] if a['kind'].startswith('option_')]
        if q['type'] in ('single_choice','multiple_choice'):
            if len(options)<2 or options != list('ABCDEFGH'[:len(options)]):
                q['issues'].append('选项数量或顺序异常')
            if not q['answer'] or any(c not in options for c in q['answer']):
                q['issues'].append('选择题答案未可靠识别')
    extra = sorted(set(matches)-used_matches)
    if extra:
        warnings.append('解析卷存在未匹配题号：'+', '.join(f'{section or "未分区"} {number}' for section,number in extra))
    return {'version':4, 'source':str(Path(source).resolve()), 'answer_source':str(Path(answer_source).resolve()),
            'question_page_count':len(pages), 'questions':questions, 'warnings':warnings}
