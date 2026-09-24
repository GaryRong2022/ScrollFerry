import json
import tempfile
import unittest
import os
from unittest.mock import patch
from pathlib import Path
from scrollferry.upload import prepare_upload, execute, question_problem, UploadNotStarted, correct_answer


class FakeBrowser:
    def __init__(self, fail_save=False):
        self.materials = set()
        self.uploads = 0
        self.saves = 0
        self.fail_save = fail_save
        self.group_opened = False
        self.group_names = []
    def open(self, progress): pass
    def ensure_question_category(self, category, status):
        assert category == self.group_names[-1]
        self.category = category
    def open_materials(self): pass
    def open_material_center(self, group, status):
        self.group_opened = True
        self.group_names.append(group)
    def find_material(self, name): return name in self.materials
    def upload_file(self, path):
        assert self.group_opened
        self.materials.add(path.name)
        self.uploads += 1
    def upload_files(self, files):
        for path in files: self.upload_file(path)
    def wait_material(self, name, progress): assert name in self.materials
    def close_materials(self): pass
    def fill_question(self, row, assets, category):
        assert category == self.category == self.group_names[-1]
        assert 'stem' in assets
        assert self.materials.issuperset(assets.values())
    def save_question(self):
        self.saves += 1
        if self.fail_save: raise TimeoutError('missing receipt')
    def close(self): pass


class UploadTest(unittest.TestCase):
    def test_uncertain_group_creation_is_remembered_for_retry(self):
        from scrollferry.upload import MaterialGroupUnconfirmed
        class GroupBrowser(FakeBrowser):
            statuses=[]
            def open_material_center(self,group,status):
                self.statuses.append(status)
                raise MaterialGroupUnconfirmed('group result unknown')
        browser=GroupBrowser()
        for _ in range(2):
            with self.assertRaises(MaterialGroupUnconfirmed):
                execute(self.batch,'',browser)
        self.assertEqual(browser.statuses,['pending','unconfirmed'])
        self.assertEqual(browser.uploads,0)

    def test_incomplete_editor_reopens_before_save_and_resumes(self):
        from scrollferry.upload import EditorNotReady
        class LoadingBrowser(FakeBrowser):
            attempts = 0
            def fill_question(self, row, assets, category):
                self.attempts += 1
                if self.attempts <= 2:
                    raise EditorNotReady('only 3 editors')
                super().fill_question(row,assets,category)
        browser = LoadingBrowser()
        execute(self.batch,'',browser)
        self.assertEqual(browser.attempts,3)
        self.assertEqual(browser.saves,1)
        self.assertEqual(browser.uploads,3)

    def test_editor_retry_limit_keeps_question_pending(self):
        from scrollferry.upload import EditorNotReady
        class LoadingBrowser(FakeBrowser):
            attempts = 0
            def fill_question(self,*args):
                self.attempts += 1
                raise EditorNotReady('still loading')
        browser = LoadingBrowser()
        with self.assertRaises(EditorNotReady):
            execute(self.batch,'',browser)
        self.assertEqual(browser.attempts,3)
        self.assertEqual(browser.saves,0)
        self.assertEqual(prepare_upload(self.batch)['questions'][0]['status'],'pending')

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        data = tempfile.TemporaryDirectory()
        self.addCleanup(data.cleanup)
        override = patch.dict(os.environ, {'SCROLLFERRY_DATA_DIR': data.name})
        override.start()
        self.addCleanup(override.stop)
        self.batch = Path(self.tmp.name)
        self.row = {'id':'Q0001', 'type':'single_choice', 'answer':'A', 'issues':[],
                    'images':[{'kind':k,'filename':k+'.png'} for k in ('stem','option_A','option_B')]}
        for image in self.row['images']: (self.batch/image['filename']).write_bytes(b'png-data')
        (self.batch/'manifest.json').write_text(json.dumps([self.row]))
        (self.batch/'status.json').write_text('{"status":"completed"}')
    def test_resume_keeps_names_and_does_not_resubmit(self):
        first = prepare_upload(self.batch)
        self.assertEqual(first, prepare_upload(self.batch))
        browser = FakeBrowser()
        result = execute(self.batch, '', browser)
        self.assertEqual(result['status'], 'completed')
        execute(self.batch, '', browser)
        self.assertEqual(browser.uploads, 3)
        self.assertEqual(browser.saves, 1)
    def test_uncertain_save_does_not_duplicate(self):
        browser = FakeBrowser(fail_save=True)
        with self.assertRaises(TimeoutError): execute(self.batch, '', browser)
        with self.assertRaisesRegex(ValueError, '重复提交'): execute(self.batch, '', browser)
        self.assertEqual(browser.saves, 1)
    def test_changed_image_cannot_reuse_receipt(self):
        prepare_upload(self.batch)
        (self.batch/'stem.png').write_bytes(b'new-image')
        with self.assertRaisesRegex(ValueError, '已变化'): prepare_upload(self.batch)
    def test_invalid_answer_and_formula_are_blocked(self):
        self.row['answer'] = 'C'
        self.assertIn('正确答案', question_problem(self.row))
        self.row.update(type='fill_blank', answer='6', answer_status='needs_formula_recognition')
        self.assertEqual(question_problem(self.row), '')
    def test_solution_can_use_full_explanation(self):
        self.row.update(type='solution', answer='')
        self.row['images'].append({'kind':'explanation','filename':'exp.png'})
        self.assertEqual(question_problem(self.row), '')
    def test_path_traversal_rejected(self):
        self.row['images'][0]['filename'] = '../outside.png'
        (self.batch/'manifest.json').write_text(json.dumps([self.row]))
        with self.assertRaisesRegex(ValueError, '路径无效'): prepare_upload(self.batch)
    def test_category_cannot_change_mid_batch(self):
        execute(self.batch, '', FakeBrowser())
        with self.assertRaisesRegex(ValueError, '另一题库分类'): execute(self.batch, 'other', FakeBrowser())
    def test_interrupted_upload_not_blindly_retried(self):
        class Interrupted(FakeBrowser):
            def wait_material(self, name, progress): raise TimeoutError('timeout')
        with self.assertRaises(TimeoutError): execute(self.batch, '', Interrupted())
        browser = FakeBrowser()
        with self.assertRaisesRegex(ValueError, '上次提交结果未确认'): execute(self.batch, '', browser)
        self.assertEqual(browser.uploads, 0)

    def test_file_chooser_failure_can_retry_without_upload(self):
        class NoChooser(FakeBrowser):
            def upload_file(self, path): raise UploadNotStarted('no chooser')
        with self.assertRaises(UploadNotStarted): execute(self.batch, '', NoChooser())
        self.assertEqual(prepare_upload(self.batch)['images'][0]['status'], 'pending')
        browser = FakeBrowser()
        execute(self.batch, '', browser)
        self.assertEqual(browser.saves, 1)

    def test_three_batches_resume_after_second_batch_never_started(self):
        rows = []
        for index in range(69):
            row = dict(self.row, id=f'Q{index+1:04d}', images=[])
            for item in self.row['images']:
                filename = f'{index}_{item["filename"]}'
                (self.batch/filename).write_bytes(b'png-data')
                row['images'].append(dict(item, filename=filename))
            rows.append(row)
        (self.batch/'manifest.json').write_text(json.dumps(rows))

        class FailSecondBatch(FakeBrowser):
            def __init__(self):
                super().__init__()
                self.batches = []
                self.fail = True
            def upload_files(self, files):
                self.batches.append(len(files))
                if len(self.batches) == 2 and self.fail:
                    raise UploadNotStarted('dialog did not open')
                super().upload_files(files)

        browser = FailSecondBatch()
        with self.assertRaisesRegex(UploadNotStarted, '100/207'):
            execute(self.batch, '', browser, materials_only=True)
        state = prepare_upload(self.batch)
        self.assertEqual(sum(i['status']=='uploaded' for i in state['images']), 100)
        self.assertFalse(any(i['status']=='submitting' for i in state['images']))
        browser.fail = False
        result = execute(self.batch, '', browser, materials_only=True)
        self.assertEqual(browser.batches, [100,100,100,7])
        self.assertEqual(browser.uploads, 207)
        self.assertTrue(all(i['status']=='uploaded' for i in result['images']))
        self.assertEqual(browser.saves, 0)

    def test_trial_still_uploads_whole_paper_including_blocked_answers(self):
        second = dict(self.row, id='Q0002', type='fill_blank', answer='', answer_status='needs_formula_recognition')
        (self.batch/'manifest.json').write_text(json.dumps([self.row, second]))
        browser = FakeBrowser()
        result = execute(self.batch, '', browser, limit=1)
        self.assertEqual(browser.uploads, 6)
        self.assertEqual(browser.saves, 1)
        self.assertEqual(result['questions'][1]['status'], 'blocked')
        self.assertTrue(all(i['status']=='uploaded' for i in result['images']))

    def test_materials_only_does_not_save_questions(self):
        browser = FakeBrowser()
        result = execute(self.batch, '', browser, materials_only=True)
        self.assertEqual(result['status'], 'materials_uploaded')
        self.assertEqual(browser.uploads, 3)
        self.assertEqual(browser.saves, 0)
        self.assertEqual(result['questions'][0]['status'], 'pending')
        self.assertEqual(len(browser.group_names), 1)

    def test_named_exports_preserve_upload_names(self):
        prefix = '六月数学_a1b2c3d4'
        for image in self.row['images']:
            old = self.batch/image['filename']
            image['filename'] = prefix + '_' + image['filename']
            old.rename(self.batch/image['filename'])
        (self.batch/'manifest.json').write_text(json.dumps([self.row]))
        (self.batch/'batch.json').write_text(json.dumps({'prefix':prefix, 'paper_name':'六月数学'}))
        state = prepare_upload(self.batch)
        self.assertEqual(state['material_group'], prefix)
        self.assertTrue(all(i['filename']==i['upload_name'] for i in state['images']))

    def test_reverse_order_including_formula_answer_image(self):
        second = dict(self.row, id='Q0002', type='fill_blank', answer='',
                      answer_status='needs_formula_recognition',
                      issues=['公式答案已保留截图，文字识别需复核'],
                      images=self.row['images'] + [{'kind':'answer','filename':'answer.png'}])
        (self.batch/'answer.png').write_bytes(b'answer-image')
        (self.batch/'manifest.json').write_text(json.dumps([self.row, second]))
        class Ordered(FakeBrowser):
            def __init__(self):
                super().__init__()
                self.ids = []
            def fill_question(self, row, assets, category):
                super().fill_question(row, assets, category)
                self.ids.append(row['id'])
        browser = Ordered()
        execute(self.batch, '', browser, limit=1)
        self.assertEqual(browser.ids, ['Q0002'])
        execute(self.batch, '', browser)
        self.assertEqual(browser.ids, ['Q0002', 'Q0001'])

    def test_reviewed_answer_preserves_uploaded_materials(self):
        self.row.update(type='fill_blank', answer='', answer_status='needs_formula_recognition',
                        issues=['公式答案已保留截图，文字识别需复核'])
        (self.batch/'manifest.json').write_text(json.dumps([self.row]))
        browser = FakeBrowser()
        before = execute(self.batch, '', browser, materials_only=True)
        correct_answer(self.batch, 'Q0001', '1/6')
        after = prepare_upload(self.batch)
        self.assertEqual(before['images'], after['images'])
        class CheckedBrowser(FakeBrowser):
            def fill_question(self, row, assets, category):
                assert row['answer'] == '1/6'
        result = execute(self.batch, '', CheckedBrowser())
        self.assertEqual(result['questions'][0]['status'], 'saved')
        with self.assertRaisesRegex(ValueError, '已提交'):
            correct_answer(self.batch, 'Q0001', '2')
