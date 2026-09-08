"""Durable upload plan. A submitted operation is never blindly retried."""
import hashlib
import json
import re
import shutil
from pathlib import Path
from uuid import uuid4
from .paths import batch_runtime_dir


class UploadNotStarted(RuntimeError):
    pass


def write_state(path, value):
    path = Path(path)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def question_problem(row):
    kind = row.get('type')
    assets = {item['kind'] for item in row['images']}
    answer = row.get('answer', '').strip()
    if 'stem' not in assets:
        return '缺少题干截图'
    if kind in ('single_choice', 'multiple_choice'):
        options = sorted(k[-1] for k in assets if k.startswith('option_'))
        if len(options) < 2 or options != list('ABCDEFGH'[:len(options)]):
            return '选项必须从 A 起连续编号且至少两项'
        if not re.fullmatch('[A-H]+', answer) or any(c not in options for c in answer):
            return '正确答案不对应选项'
        if kind == 'single_choice' and len(answer) != 1:
            return '单选题必须只有一个正确选项'
    elif kind == 'fill_blank':
        if 'answer' not in assets and not answer:
            return '填空转问答题缺少答案截图或文字'
    elif kind == 'solution':
        if not answer and not ({'answer', 'explanation'} & assets):
            return '解答题缺少答案或完整解析'
    else:
        return '题型尚不支持'
    issues = list(row.get('issues', []))
    if kind == 'fill_blank' and 'answer' in assets:
        issues = [i for i in issues if i != '公式答案已保留截图，文字识别需复核']
    if issues:
        return '；'.join(str(i) for i in issues)
    return ''


def prepare_upload(batch):
    batch = Path(batch).resolve()
    raw = (batch/'manifest.json').read_bytes()
    rows = json.loads(raw)
    if json.loads((batch/'status.json').read_text(encoding='utf-8'))['status'] != 'completed':
        raise ValueError('此批次尚未导出完成，不能上传')
    if not rows or len({r['id'] for r in rows}) != len(rows):
        raise ValueError('题目清单为空或题号重复')
    fingerprint = hashlib.sha256(raw).hexdigest()
    files = []
    for row in rows:
        kinds = [i['kind'] for i in row['images']]
        if len(kinds) != len(set(kinds)):
            raise ValueError('同一题存在重复截图类型')
        for item in row['images']:
            file = (batch/item['filename']).resolve()
            if file.parent != batch or not file.is_file() or file.suffix.lower() != '.png':
                raise ValueError('上传图片缺失或路径无效')
            files.append((row, item, file, hashlib.sha256(file.read_bytes()).hexdigest()))
    signature = hashlib.sha256((fingerprint + ''.join(f[3] for f in files)).encode()).hexdigest()
    runtime = batch_runtime_dir(batch)
    path = runtime/'upload-queue.json'
    legacy = batch/'upload-queue.json'
    prior_path = path if path.exists() else legacy
    if prior_path.exists():
        prior = json.loads(prior_path.read_text(encoding='utf-8'))
        if prior.get('version') in (2, 3):
            if prior['signature'] != signature:
                raise ValueError('本批次截图或答案已变化，请重新导出为新批次后上传')
            for item in prior['images']:
                name = item['upload_name']
                if Path(name).name != name or '/' in name or '\\' in name:
                    raise ValueError('上传副本文件名无效')
                staged = runtime/'upload-assets'/name
                if not staged.exists() and prior_path == legacy:
                    old = batch/'upload-assets'/name
                    if not old.is_file() or hashlib.sha256(old.read_bytes()).hexdigest() != item['sha256']:
                        raise ValueError('旧版上传副本缺失或已变化，无法迁移进度')
                    staged.parent.mkdir(exist_ok=True)
                    shutil.copyfile(old, staged)
                if not staged.is_file() or hashlib.sha256(staged.read_bytes()).hexdigest() != item['sha256']:
                    raise ValueError('待上传副本已变化，请重新导出批次')
            lookup = {row['id']: row for row in rows}
            for question in prior['questions']:
                if question['status'] not in ('saved', 'submitting'):
                    row = dict(lookup[question['id']])
                    if question['id'] in prior.get('answer_overrides', {}):
                        row['answer'] = prior['answer_overrides'][question['id']]
                        row['issues'] = [i for i in row.get('issues', []) if i != '公式答案已保留截图，文字识别需复核']
                    problem = question_problem(row)
                    question.update(status='blocked' if problem else 'pending', reason=problem)
            prior['unresolved_questions'] = sum(q['status'] == 'blocked' for q in prior['questions'])
            write_state(path, prior)
            return prior
    from .core import safe_paper_name
    metadata_path = batch/'batch.json'
    metadata = json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.exists() else {}
    prefix = metadata.get('prefix') or (safe_paper_name(batch.name) + '_' + uuid4().hex[:8])
    if not isinstance(prefix, str) or len(prefix) > 45 or re.search(r'[<>:"/\\|?*\x00-\x1f]', prefix) or prefix.strip(' .') != prefix:
        raise ValueError('试卷前缀格式无效，请重新导出批次')
    staging = runtime/'upload-assets'
    staging.mkdir(exist_ok=True)
    images = []
    for index, (row, item, file, digest) in enumerate(files, 1):
        name = file.name if file.name.startswith(prefix + '_') else f'{prefix}_{index:04d}_{file.name}'
        shutil.copyfile(file, staging/name)
        images.append({'question_id': row['id'], 'kind': item['kind'], 'filename': file.name,
                       'upload_name': name, 'sha256': digest, 'status': 'pending'})
    questions = []
    for row in rows:
        problem = question_problem(row)
        questions.append({'id': row['id'], 'status': 'blocked' if problem else 'pending', 'reason': problem})
    report = {'version': 3, 'signature': signature, 'batch_id': prefix, 'status': 'prepared',
              'paper_name': metadata.get('paper_name', safe_paper_name(batch.name)),
              'material_group': prefix, 'group_status': 'pending',
              'category': '', 'image_count': len(images), 'images': images, 'questions': questions,
              'unresolved_questions': sum(bool(q['reason']) for q in questions)}
    write_state(path, report)
    return report


def correct_answer(batch, question_id, answer):
    """Record a reviewed answer without changing uploaded image identities."""
    batch = Path(batch)
    state = prepare_upload(batch)
    question = next(q for q in state['questions'] if q['id'] == question_id)
    if question['status'] in ('saved', 'submitting'):
        raise ValueError('已提交题目不能在本地覆盖答案')
    row = next(r for r in json.loads((batch/'manifest.json').read_text(encoding='utf-8')) if r['id'] == question_id)
    row.update(answer=answer.strip(), answer_status='reviewed')
    row['issues'] = [i for i in row.get('issues', []) if i != '公式答案已保留截图，文字识别需复核']
    problem = question_problem(row)
    if problem:
        raise ValueError(problem)
    state.setdefault('answer_overrides', {})[question_id] = row['answer']
    question.update(status='pending', reason='')
    state['unresolved_questions'] = sum(q['status'] == 'blocked' for q in state['questions'])
    write_state(batch_runtime_dir(batch)/'upload-queue.json', state)


def execute(batch, category, adapter, progress=lambda *args: None, limit=None, materials_only=False):
    """Adapter performs UI actions; persisted ambiguity stops unsafe resubmission."""
    batch = Path(batch).resolve()
    state = prepare_upload(batch)
    if state.get('version') != 3:
        raise ValueError('这是旧版上传批次，原进度已保留。新建素材分组流程请使用新版导出；已保存题目请勿重复录入。')
    requested_category = category.strip()
    category = state['material_group']
    if len(category.encode('utf-16-le')) // 2 > 40:
        raise ValueError('试卷分组名称超过题库分类的 40 字限制，请重新导出')
    if requested_category and requested_category != category and not materials_only:
        raise ValueError('不能选择另一题库分类：题库分类必须与素材分组同名')
    if not materials_only and state['category'] and state['category'] != category:
        raise ValueError('此批次已绑定另一题库分类，请使用原分类继续')
    if category and not materials_only:
        state['category'] = category
    runtime = batch_runtime_dir(batch)
    path = runtime/'upload-queue.json'
    save = lambda: write_state(path, state)
    save()
    rows = {r['id']: r for r in json.loads((batch/'manifest.json').read_text(encoding='utf-8'))}
    for question_id, answer in state.get('answer_overrides', {}).items():
        rows[question_id]['answer'] = answer
        rows[question_id]['issues'] = [i for i in rows[question_id].get('issues', []) if i != '公式答案已保留截图，文字识别需复核']
    for question in state['questions']:
        if question['status'] not in ('saved', 'submitting'):
            problem = question_problem(rows[question['id']])
            question.update(status='blocked' if problem else 'pending', reason=problem)
    state['unresolved_questions'] = sum(q['status'] == 'blocked' for q in state['questions'])
    save()
    pending = [q for q in reversed(state['questions']) if q['status'] not in ('saved', 'blocked')]
    if not materials_only and any(q['status'] == 'submitting' for q in pending):
        raise ValueError('有题目上次已点击保存但未确认结果，请在后台核对，不能自动重复提交')
    if limit is not None:
        pending = pending[:limit]
    if not pending and all(i['status'] == 'uploaded' for i in state['images']):
        return state
    images = state['images']
    try:
        adapter.open(progress)
        progress('在素材中心建立试卷分组', 0, len(images))
        adapter.open_material_center(state['material_group'], state['group_status'])
        state['group_status'] = 'ready'
        save()
        total = len(images) + len(pending)
        done = 0
        missing = []
        for item in images:
            progress(f'检查素材 {item["upload_name"]}', done, total)
            if item['status'] != 'uploaded':
                if adapter.find_material(item['upload_name']):
                    item['status'] = 'uploaded'
                    save()
                elif item['status'] == 'submitting':
                    raise ValueError(f'图片 {item["upload_name"]} 上次提交结果未确认，请先在素材库核对')
                else:
                    missing.append(item)
        for offset in range(0, len(missing), 100):
            group = missing[offset:offset+100]
            progress(f'批量上传 {len(group)} 张截图', done, total)
            for item in group:
                item['status'] = 'submitting'
            save()
            try:
                adapter.upload_files([runtime/'upload-assets'/item['upload_name'] for item in group])
            except UploadNotStarted:
                for item in group:
                    item['status'] = 'pending'
                save()
                raise
            for item in group:
                adapter.wait_material(item['upload_name'], progress)
                item['status'] = 'uploaded'
                done += 1
                save()
        done = len(images)
        if materials_only:
            state['status'] = 'materials_uploaded'
            state.pop('last_error', None)
            save()
            return state
        progress('创建并核对同名题库分类', done, total)
        adapter.ensure_question_category(category, state.get('category_status', 'pending'))
        state['category_status'] = 'ready'
        save()
        for question in pending:
            row = rows[question['id']]
            progress(f'填入第 {question["id"]} 题', done, total)
            assets = {i['kind']: i['upload_name'] for i in images if i['question_id'] == question['id']}
            adapter.fill_question(row, assets, category)
            progress(f'保存第 {question["id"]} 题', done, total)
            question['status'] = 'submitting'
            save()
            adapter.save_question()
            question['status'] = 'saved'
            question['reason'] = ''
            done += 1
            save()
            progress(f'已保存第 {question["id"]} 题', done, total)
        state['status'] = 'completed' if all(q['status'] == 'saved' for q in state['questions']) else 'partial'
        state.pop('last_error', None)
        save()
        return state
    except Exception as exc:
        state['status'] = 'paused'
        state['last_error'] = str(exc)
        if hasattr(adapter, 'diagnose'):
            try:
                adapter.diagnose(runtime/'upload-error.png')
            except Exception:
                pass
        save()
        raise
    finally:
        adapter.close()
