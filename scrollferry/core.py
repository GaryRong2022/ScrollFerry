"""PDF coordinates and masks remain editable; originals are never modified."""
import json
import re
from pathlib import Path

import pdfplumber
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageOps


def safe_paper_name(name):
    """Shared Windows/macOS file stem, leaving room for the batch and question IDs."""
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', str(name)).strip(' ._')
    value = re.sub(r'\s+', ' ', value)[:30].rstrip(' .')
    while len(value.encode('utf-16-le')) // 2 > 30:
        value = value[:-1]
    value = value.rstrip(' .')
    return value or '试卷'


def new_batch_path(parent, stem):
    from datetime import datetime
    import uuid
    return Path(parent) / (safe_paper_name(stem) + '_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8])

QUESTION = re.compile(r"^\s*(\d{1,4})\s*[.．、](?!\d)\s*")
OPTION = re.compile(r"^\s*([A-H])\s*[.．、)）]\s*")
ANSWER = re.compile(r"(?:【\s*(?:参考)?答案\s*】|(?:参考)?答案\s*[:：])\s*([A-H](?:[A-H\s,，、]*[A-H])?|正确|错误|对|错|√|×)(?=\s|[。；;【]|$)")
EXPLANATION = re.compile(r"^\s*(?:\d{1,4}\s*[.．、]\s*)?(?:【\s*(?:答案)?解析\s*】|(?:答案)?解析\s*[:：])\s*")


def split_option_lines(lines, width):
    result = []
    for line in lines:
        matches = list(re.finditer(r'(?<![A-Za-z])([A-H])[.．、)）]\s*', line['text']))
        if len(matches) < 2 or matches[0].start() > 2:
            result.append(line)
            continue
        chars = sorted(line.get('chars', []), key=lambda c: c['x0'])
        chars = [c for c in chars if c['text'].strip()]
        for i, match in enumerate(matches):
            end = matches[i+1].start() if i+1 < len(matches) else len(line['text'])
            start_index = len(re.sub(r'\s', '', line['text'][:match.start()]))
            end_index = len(re.sub(r'\s', '', line['text'][:end]))
            subset = chars[start_index:end_index]
            if not subset:
                continue
            right = chars[end_index]['x0'] - 2 if end_index < len(chars) else width - 20
            result.append(dict(line, text=line['text'][match.start():end], chars=subset,
                               x0=subset[0]['x0'], clip_right=right, inline=True))
    return result


def read_pages(source, progress=None):
    pages = []
    with pdfplumber.open(source) as doc:
        for index, page in enumerate(doc.pages):
            if progress:
                progress('读取 PDF 页面', index, len(doc.pages))
            lines = page.extract_text_lines(return_chars=True, y_tolerance=5)
            pages.append({'width': page.width, 'height': page.height, 'lines': lines,
                          'rects': [{'x0':r['x0'],'x1':r['x1'],'top':r['top'],'bottom':r['bottom'],
                                     'color':r.get('non_stroking_color')} for r in page.rects]})
    return pages


def prefix_box(line, count):
    prefix_length = len(re.sub(r'\s', '', line['text'][:count]))
    chars = [c for c in sorted(line.get('chars', []), key=lambda c: c['x0']) if c['text'].strip()][:prefix_length]
    if not chars:
        return None
    return [min(c['x0'] for c in chars) - 0.3, min(c['top'] for c in chars) - 3,
            max(c['x1'] for c in chars), max(c['bottom'] for c in chars) + 3]


def detect(source, pages=None, progress=None):
    """Automatically locate supported layouts; retain unresolved items in the report."""
    pages = read_pages(source, progress) if pages is None else pages
    from .layout import segment
    structured = segment(str(Path(source).resolve()), pages, progress)
    if structured and structured['questions']:
        return structured
    questions = []
    current = None
    region = None
    answer_section = False
    for page_no, page in enumerate(pages):
        if progress:
            progress('识别题目、选项和答案', page_no + 1, len(pages))
        lines = split_option_lines(page['lines'], page['width'])
        if current and region:
            region = {'page': page_no, 'box': [20, 20, page['width'] - 20, page['height'] - 20], 'masks': []}
            current['assets'][-1]['regions'].append(region)
        for line in lines:
            value = line['text']
            q = QUESTION.match(value)
            opt = OPTION.match(value)
            exp = EXPLANATION.match(value)
            ans = ANSWER.search(value)
            if re.fullmatch(r'\s*(?:参考答案|答案与解析|参考答案与解析|答案解析)\s*', value):
                answer_section = True
                if region and region['page'] == page_no:
                    region['box'][3] = max(region['box'][1] + 1, line['top'] - 3)
                region = None
                continue
            if answer_section and q:
                candidates = [item for item in questions if item['original_number'] == q[1]]
                if len(candidates) == 1:
                    if region and region['page'] == page_no:
                        region['box'][3] = max(region['box'][1]+1, line['top']-3)
                    current = candidates[0]
                    region = None
                    bare = re.match(r'([A-H]+)(?=\s|[。；;【]|$)', value[q.end():])
                    if ans or bare:
                        current['answer'] = re.sub(r'[\s,，、]', '', (ans or bare)[1])
                    # A subsequent explanation marker starts its screenshot.
                    exp_pos = re.search(r'【(?:答案)?解析】|(?:答案)?解析[:：]', value)
                    if not exp_pos:
                        continue
                    exp = re.match(r'.{' + str(exp_pos.end()) + r'}', value)
                    q = None
                    opt = None
                    ans = None
            if q and not exp:
                if region and region['page'] == page_no:
                    region['box'][3] = max(region['box'][1] + 1, line['top'] - 2)
                current = {'id': f'Q{len(questions)+1:04d}', 'original_number': q[1], 'answer': '', 'reviewed': False, 'assets': []}
                questions.append(current)
                kind, match = 'stem', q
            elif current and exp:
                kind, match = 'explanation', exp
            elif current and opt:
                kind, match = f'option_{opt[1]}', opt
            elif current and ans:
                current['answer'] = re.sub(r'[\s,，、]', '', ans[1])
                if region and region['page'] == page_no:
                    region['box'][3] = max(region['box'][1] + 1, line['top'] - 2)
                region = None
                exp_pos = re.search(r'【(?:答案)?解析】|(?:答案)?解析[:：]', value)
                if not exp_pos:
                    continue
                kind, match = 'explanation', re.match(r'.{' + str(exp_pos.end()) + r'}', value)
            else:
                continue
            if region and region['page'] == page_no:
                region['box'][3] = max(region['box'][1] + 1, line['top'] - 2)
            if region and line.get('inline') and abs(region['box'][1] - (line['top']-5)) < 2:
                region['box'][3] = line['bottom'] + 4
            left = max(0, line['x0']-2) if line.get('inline') else 20
            region = {'page': page_no, 'box': [left, max(0, line['top'] - 5), line.get('clip_right', page['width'] - 20), page['height'] - 20], 'masks': []}
            mask = prefix_box(line, match.end())
            if kind == 'explanation':
                number = QUESTION.match(value)
                mask = prefix_box(line, number.end()) if number else None
            if mask:
                region['masks'].append(mask)
            current['assets'].append({'kind': kind, 'regions': [region]})
    for question in questions:
        kinds = [a['kind'] for a in question['assets']]
        question['issues'] = []
        if not question['answer']:
            question['issues'].append('未识别到答案')
        if 'explanation' not in kinds:
            question['issues'].append('未识别到解析')
        if len(kinds) != len(set(kinds)):
            question['issues'].append('截图类型重复，请检查拆题边界')
    warnings = []
    empty = [str(i+1) for i, p in enumerate(pages) if not p['lines']]
    if empty:
        warnings.append('以下页无可读文字，未自动识别（尚未接入 OCR）：' + ', '.join(empty))
    if not questions:
        raise ValueError('未识别到题目。扫描件 OCR 或当前题号/排版尚不支持，请提供实际 PDF 以适配。')
    return {'version': 2, 'source': str(Path(source).resolve()), 'questions': questions, 'warnings': warnings}


def render_page(source, page, scale=1.5):
    doc = pdfium.PdfDocument(source)
    try:
        p = doc[page]
        try:
            bitmap = p.render(scale=scale)
            try:
                return bitmap.to_pil().convert('RGB').copy()
            finally:
                bitmap.close()
        finally:
            p.close()
    finally:
        doc.close()


def crop_region(source, region, scale=2):
    image = render_page(source, region['page'], scale)
    draw = ImageDraw.Draw(image)
    for mask in region['masks']:
        draw.rectangle(tuple(round(v * scale) for v in mask), fill='white')
    box = tuple(round(v * scale) for v in region['box'])
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError('截图范围无效，请重新框选')
    # Keep a visible buffer around the final image; masking never expands into
    # adjoining content merely to make the screenshot look tighter.
    return ImageOps.expand(image.crop(box), border=8, fill='white')


def export(project, destination, progress=None):
    if not project['questions']:
        raise ValueError('尚未添加题目')
    for q in project['questions']:
        if not re.fullmatch(r'Q\d{4,}', q['id']):
            raise ValueError('题目编号格式无效')
        if not q['assets'] or any(not a['regions'] for a in q['assets']):
            raise ValueError('存在缺少截图区域的题目')
        if any(not re.fullmatch(r'stem|answer|explanation|option_[A-H]', a['kind']) for a in q['assets']):
            raise ValueError('截图类型无效')
    if len({q['id'] for q in project['questions']}) != len(project['questions']):
        raise ValueError('题目编号重复')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    if any(destination.iterdir()):
        raise ValueError('请选择空文件夹，避免覆盖已有批次')
    from uuid import uuid4
    paper_name = safe_paper_name(project.get('paper_name') or Path(project['source']).stem)
    prefix = paper_name + '_' + uuid4().hex[:8]
    metadata = {'version': 1, 'paper_name': paper_name, 'prefix': prefix, 'material_group': prefix}
    (destination / 'batch.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')
    (destination / 'project.json').write_text(json.dumps(project, ensure_ascii=False, indent=2), encoding='utf-8')
    report = {'status': 'processing', 'completed_questions': 0, 'total_questions': len(project['questions'])}
    (destination / 'status.json').write_text(json.dumps(report), encoding='utf-8')
    rows = []
    total = sum(len(q['assets']) for q in project['questions'])
    completed = 0
    for question in project['questions']:
        row = {k: question[k] for k in ('id', 'original_number', 'answer')}
        row['type'] = question.get('type', 'unknown')
        row['answer_status'] = question.get('answer_status', 'extracted')
        row['images'] = []
        row['issues'] = question.get('issues', [])
        row['reviewed'] = question['reviewed']
        for index, asset in enumerate(question['assets']):
            if progress:
                progress('截图去标号并保存', completed, total)
            images = [crop_region(project['source'], r) for r in asset['regions']]
            if not images:
                continue
            canvas = Image.new('RGB', (max(i.width for i in images), sum(i.height for i in images)), 'white')
            y = 0
            for image in images:
                canvas.paste(image, (0, y))
                y += image.height
            name = f"{prefix}_{question['id']}_{index+1:02d}_{asset['kind']}.png"
            canvas.save(destination / name)
            row['images'].append({'kind': asset['kind'], 'filename': name})
            completed += 1
        rows.append(row)
        (destination / 'manifest.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
        report['completed_questions'] = len(rows)
        (destination / 'status.json').write_text(json.dumps(report), encoding='utf-8')
    (destination / 'manifest.json').write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding='utf-8')
    (destination / 'warnings.json').write_text(json.dumps(project.get('warnings', []), ensure_ascii=False, indent=2), encoding='utf-8')
    if progress:
        progress('保存完成', total, total)
    report['status'] = 'completed'
    (destination / 'status.json').write_text(json.dumps(report), encoding='utf-8')
    return rows
