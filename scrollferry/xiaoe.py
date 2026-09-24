"""Visible-browser Xiaoe adapter; stops when the expected UI cannot be verified."""
import re
import json
import time
from pathlib import Path
from .paths import user_data_dir
from .browsers import browser_channels

BASE = 'https://admin.xiaoe-tech.com/t/exam/questionBankIndex'
INDEX = BASE + '#/questionBankIndex/questionIndex?intoQuestionBank=true'
MATERIAL_CENTER = 'https://admin.xiaoe-tech.com/t/material-center/materialCenter#/materialCenter/imageList'
TYPES = {'single_choice': 0, 'multiple_choice': 1, 'fill_blank': 4, 'solution': 2}


class MenuNotReady(RuntimeError):
    """A transient collapsed menu, before any material is inserted."""


class XiaoeBrowser:
    def __init__(self, profile=None):
        self.profile = Path(profile) if profile else None
        self.runtime = self.context = None

    def open(self, progress):
        self.progress = progress
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ValueError('尚未安装上传组件。请双击“安装上传组件_mac.command”或“安装上传组件_windows.bat”，完成后重试。') from exc
        self.runtime = sync_playwright().start()
        failures = []
        for channel in browser_channels():
            name = 'Chrome' if channel == 'chrome' else 'Edge'
            progress(f'正在启动 {name} 上传窗口', 0, 0)
            profile = self.profile or user_data_dir()/'browser-profiles'/channel
            try:
                self.context = self.runtime.chromium.launch_persistent_context(
                    str(profile), channel=channel, headless=False,
                    viewport={'width': 1360, 'height': 900})
                self.browser_name = name
                break
            except Exception as exc:
                failures.append(f'{name}: {exc}')
        if self.context is None:
            self.runtime.stop()
            self.runtime = None
            raise ValueError('Chrome 和 Edge 均无法启动。请安装其中任一浏览器，或关闭软件之前打开的上传窗口后重试。')
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.set_default_timeout(15000)
        self.page.goto(MATERIAL_CENTER)
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            progress(f'请在新打开的 {self.browser_name} 登录小鹅通，登录后自动继续', 0, 0)
            if self.page.get_by_placeholder('请输入图片名称', exact=True).is_visible():
                break
            self.page.wait_for_timeout(500)
        else:
            raise ValueError('等待登录超时，请重新开始上传')

    def find_material_group(self, group_name):
        """Search again after reload; search results need not expose treeitem roles."""
        from playwright.sync_api import TimeoutError as BrowserTimeout
        for attempt in range(3):
            if attempt:
                self.progress(f'正在重新查找素材分组（{attempt}/2）',0,0)
                self.page.goto(MATERIAL_CENTER)
            search = self.page.get_by_role('textbox', name='请输入分组名称', exact=True).first
            try:
                search.wait_for(timeout=15000)
                search.fill(group_name)
                search.press('Enter')
                # Search results may be flat rows instead of ARIA tree items.
                label = self.page.get_by_text(group_name, exact=True).filter(visible=True)
                label.first.wait_for(timeout=7000)
                if label.count()!=1:
                    raise ValueError('素材分组名称不唯一，已停止')
                return label
            except BrowserTimeout:
                continue
        return None

    def open_material_center(self, group_name, group_status='pending'):
        self.center_mode = True
        self.material_group = group_name
        if self.page.url != MATERIAL_CENTER:
            self.page.goto(MATERIAL_CENTER)
        self.material = self.page
        self.page.get_by_placeholder('请输入图片名称', exact=True).wait_for()
        target = self.find_material_group(group_name)
        if target is None:
            if group_status in ('ready','unconfirmed'):
                raise ValueError('重试后仍未找到原素材分组，请检查分组是否被移动或删除；进度已保留。')
            back = self.page.get_by_text('返回', exact=True)
            if back.count()==1 and back.is_visible():
                back.click()
            self.page.get_by_role('img', name='addgroup', exact=True).click()
            self.page.get_by_role('textbox', name='请输入分组名称', exact=True).last.fill(group_name)
            from .upload import MaterialGroupUnconfirmed
            try:
                self.page.get_by_role('button', name='确定', exact=True).click()
                target = self.find_material_group(group_name)
                if target is None:
                    raise MaterialGroupUnconfirmed('素材分组创建结果未确认，请重试查找；不会重复创建。')
            except Exception as exc:
                raise MaterialGroupUnconfirmed('素材分组创建结果未确认，请重试查找；不会重复创建。') from exc
        target.click()
        self.page.get_by_placeholder('请输入图片名称', exact=True).fill('')
        # Upload destination is independently verified before selecting any files.

    def dismiss_tip(self):
        tip = self.page.get_by_text('题库支持多级知识点，快来体验吧！', exact=False)
        if tip.count() and tip.first.is_visible():
            close = self.page.get_by_role('button', name='Close', exact=True)
            if close.count() == 1 and close.is_visible():
                try:
                    close.click(timeout=3000)
                except Exception:
                    if tip.first.is_visible():
                        raise

    def ensure_question_category(self, category, status='pending'):
        from playwright.sync_api import expect
        self.page.goto(INDEX)
        self.page.get_by_role('button', name=re.compile('添加题目')).wait_for()
        self.dismiss_tip()
        search = self.page.get_by_role('textbox', name='请输入分类名称', exact=True)
        search.fill(category)
        search.press('Enter')
        target = self.page.get_by_text(category, exact=True).filter(visible=True)
        try:
            target.wait_for(timeout=5000)
        except Exception:
            if status == 'ready':
                raise ValueError('原题库分类未找到，请检查是否被改名或删除')
            search.fill('')
            search.press('Enter')
            self.page.get_by_role('img', name='addgroup', exact=True).click()
            entry = self.page.get_by_role('textbox', name='请输入分类名称', exact=True).last
            entry.fill(category)
            expect(entry).to_have_value(category)
            self.page.get_by_role('button', name='确定', exact=True).click()
            target.wait_for()
        if target.count() != 1:
            raise ValueError('同名题库分类不唯一，已停止')
        target.click()

    def new_question(self, kind):
        self.page.goto(INDEX)
        self.page.get_by_role('button', name=re.compile('添加题目')).wait_for()
        self.dismiss_tip()
        self.page.goto(BASE + f'#/questionBankIndex/addQuestion?type={TYPES[kind]}&isEdit=false')
        self.page.get_by_role('button', name='保存', exact=True).wait_for()
        self.page.get_by_text('图片', exact=True).first.wait_for()

    def select_category(self, category):
        selected = self.page.get_by_text(category, exact=True).filter(visible=True)
        reselect = self.page.get_by_text('重新选择', exact=True)
        if reselect.is_visible() and selected.count() == 1:
            return
        if reselect.is_visible():
            reselect.click()
        else:
            self.page.get_by_text('选择分类', exact=True).click()
        target = self.page.get_by_text(category, exact=True).filter(visible=True)
        target.wait_for()
        if target.count() != 1:
            raise ValueError(f'分类“{category}”不唯一，请在后台为试传分类使用唯一名称')
        target.click()
        # A category picker may require confirmation. Restrict it to the open dialog.
        dialog = self.page.get_by_role('dialog').filter(has_text='分类')
        if dialog.count() == 1 and dialog.is_visible():
            confirm = dialog.get_by_role('button', name=re.compile('^(确 定|确定|确认)$'))
            if confirm.count() == 1:
                confirm.click()
        dialog.wait_for(state='hidden')
        from playwright.sync_api import expect
        expect(self.page.get_by_text(category, exact=True).filter(visible=True)).to_have_count(1)
        expect(self.page.get_by_text('重新选择', exact=True)).to_be_visible()

    def editor_body(self, index):
        # UEditor IDs are generated dynamically; locate editors by their toolbars/frames.
        editors = self.page.locator('iframe').filter(visible=True)
        handle = editors.nth(index).element_handle()
        frame = handle.content_frame() if handle else None
        if frame is None:
            raise ValueError('无法定位题目编辑框，已停止以避免填错字段')
        body = frame.locator('body[contenteditable="true"]')
        body.wait_for()
        return body

    def on_screen_text(self, text, timeout=2):
        # UEditor retains offscreen toolbar clones as visible DOM nodes.
        # Only the expanded menu inside the viewport is an actionable target.
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            matches = self.page.get_by_text(text, exact=True).filter(visible=True)
            candidates = []
            viewport = self.page.viewport_size
            for index in range(matches.count()):
                locator = matches.nth(index)
                box = locator.bounding_box()
                if box and box['width'] > 0 and box['height'] > 0 and 0 <= box['x'] < viewport['width'] and 0 <= box['y'] < viewport['height']:
                    candidates.append(locator)
            if len(candidates) == 1:
                return candidates[0]
            if len(candidates) > 1:
                raise ValueError(f'页面中有多个可见“{text}”，已停止以避免误点')
            self.page.wait_for_timeout(100)
        raise MenuNotReady(f'菜单中未找到可见“{text}”')

    def material_dialog(self):
        # Closed pickers stay in the DOM. Only reuse the currently open picker.
        title = self.page.get_by_text('选择图片', exact=True).filter(visible=True)
        if not title.count():
            return None
        dialogs = self.page.get_by_role('dialog').filter(has=title).filter(visible=True)
        if not dialogs.count():
            dialogs = title.locator('xpath=ancestor::*[.//button[contains(.,"上传图片")] and .//input][1]')
        if dialogs.count() != 1:
            raise ValueError('素材选择窗口无法唯一定位，已停止以避免选错素材')
        return dialogs

    def click_material_menu(self):
        self.on_screen_text('图片').hover(timeout=2000)
        target = self.on_screen_text('从素材库选择')
        # Native pointer movement toward a cascading menu can cross another
        # menu item and collapse the submenu. Activate the verified DOM node
        # without moving the pointer; no upload/insert/save is performed here.
        clicked = target.evaluate('''el => {
            const r = el.getBoundingClientRect();
            if (!r.width || !r.height || r.x < 0 || r.y < 0 ||
                r.x >= innerWidth || r.y >= innerHeight ||
                getComputedStyle(el).visibility !== 'visible' ||
                el.textContent.trim() !== '从素材库选择') return false;
            el.click();
            return true;
        }''', timeout=2000)
        if not clicked:
            raise MenuNotReady('素材库子菜单在点击前收起')

    def open_materials(self, index=0):
        from playwright.sync_api import TimeoutError as PlaywrightTimeout
        self.center_mode = False
        for attempt in range(3):
            getattr(self, 'progress', lambda *args: None)(
                f'打开第 {index+1} 个编辑区的素材库' + (f' · 正在重试 {attempt}/2' if attempt else ''), 0, 0)
            try:
                material = self.material_dialog()
                if material is None:
                    self.editor_body(index).click(timeout=3000)
                    # Bind the toolbar to this editor, rather than an index in
                    # all retained toolbar/menu clones on the page.
                    frame = self.page.locator('iframe').filter(visible=True).nth(index)
                    toolbar_owner = frame.locator('xpath=ancestor::*[.//*[normalize-space(text())="插入"]][1]')
                    toolbar_owner.get_by_text('插入', exact=True).filter(visible=True).click(timeout=3000)
                    self.click_material_menu()
                    self.page.get_by_text('选择图片', exact=True).filter(visible=True).wait_for(timeout=4000)
                    material = self.material_dialog()
                    if material is None:
                        raise MenuNotReady('素材选择窗口尚未打开')
                self.material = material
                self.material.get_by_role('button', name='上传图片', exact=True).wait_for(timeout=4000)
                self.material.locator('.ss-loading-mask:visible').first.wait_for(state='hidden', timeout=4000)
                return
            except (MenuNotReady, PlaywrightTimeout) as exc:
                if attempt == 2:
                    raise RuntimeError(f'打开素材库重试 3 次仍未完成，当前题目尚未保存。\n{exc}') from exc
                # If the picker opened late, reuse it on the next pass instead
                # of toggling the toolbar again. Nothing has been inserted yet.
                self.page.wait_for_timeout(300 * (attempt+1))

    def find_material(self, name):
        search = self.material.get_by_placeholder(
            '请输入图片名称' if self.center_mode else '图片名称', exact=True)
        search.first.wait_for()
        if search.count() != 1:
            raise ValueError('无法唯一定位素材文件名搜索框')
        search.fill(name)
        search.press('Enter')
        # Search is asynchronous; never use its initial empty rows as a result.
        self.page.wait_for_timeout(1200)
        self.material.locator('.ss-loading-mask:visible').first.wait_for(state='hidden')
        match = self.material.get_by_role('row').filter(
            has=self.page.get_by_text(name, exact=True)).filter(visible=True)
        if match.count() > 1:
            raise ValueError(f'素材文件名重复：{name}')
        return match.count() == 1 and match.is_visible()

    def upload_files(self, files):
        from .upload import UploadNotStarted
        stage = '检查素材中心'
        try:
            if not self.center_mode:
                raise ValueError('请先在素材中心完成集中上传')
            stage = '打开上传窗口'
            # Closed upload dialogs remain in the DOM after a batch. Their
            # hidden titles must not compete with the visible upload entry.
            self.page.get_by_text('上传图片', exact=True).filter(visible=True).click()
            uploader = self.page.get_by_role('dialog', name='上传图片', exact=True)
            uploader.wait_for()
            from playwright.sync_api import expect
            stage = '核对上传目标分组'
            expect(uploader.get_by_role('textbox', name='请选择', exact=True)).to_have_value(self.material_group)
            stage = '等待确认上传按钮'
            confirm = uploader.get_by_role('button', name=re.compile(r'^确认上传(?:\(\d+\))?$'))
            confirm.wait_for()
            stage = '打开文件选择器'
            with self.page.expect_file_chooser() as choice:
                uploader.get_by_text('选择图片', exact=True).click()
        except Exception as exc:
            raise UploadNotStarted(f'本轮文件尚未提交：{stage}失败。\n具体原因：{exc}') from exc
        choice.value.set_files([str(file) for file in files])
        getattr(self, 'progress', lambda *args: None)(f'已选择 {len(files)} 张图片 · 提交上传并等待后台回执', 0, 0)
        confirm.click()
        from playwright.sync_api import expect
        expect(uploader).to_contain_text(
            re.compile(r'上传成功\s*' + str(len(files)) + r'(?!\d)'), timeout=120000)
        uploader.get_by_role('button', name='Close', exact=True).click()
        uploader.wait_for(state='hidden')

    def upload_file(self, file):
        self.upload_files([file])

    def wait_material(self, name, progress):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            progress(f'等待素材上传完成：{name}', 0, 1)
            if self.find_material(name):
                return
            self.page.wait_for_timeout(500)
        raise ValueError(f'素材上传回执超时：{name}。已保留状态，请在后台核对')

    def close_materials(self):
        self.material.get_by_role('button', name='取消', exact=True).click()
        self.page.get_by_text('选择图片', exact=True).wait_for(state='hidden')

    def insert(self, index, name):
        body = self.editor_body(index)
        before = body.locator('img').count()
        self.open_materials(index)
        getattr(self, 'progress', lambda *args: None)(f'在素材库精确搜索图片：{name}', 0, 0)
        # Initial dialog loading may overwrite the first search response.
        deadline = time.monotonic() + 30
        while not self.find_material(name):
            if time.monotonic() >= deadline:
                raise ValueError(f'未找到已上传素材：{name}')
            self.page.wait_for_timeout(500)
        row = self.material.get_by_role('row').filter(
            has=self.page.get_by_text(name, exact=True)).filter(visible=True)
        if row.count() != 1:
            raise ValueError(f'素材行无法唯一匹配：{name}')
        checkbox = row.get_by_role('checkbox')
        if not checkbox.is_checked():
            checkbox.locator('xpath=..').click()
        from playwright.sync_api import expect
        expect(checkbox).to_be_checked()
        self.material.get_by_role('button', name=re.compile('^(确认|确 定|确定)$')).click()
        self.page.get_by_text('选择图片', exact=True).wait_for(state='hidden')
        from playwright.sync_api import expect
        expect(body.locator('img')).to_have_count(before + 1)

    def fill_question(self, row, assets, category):
        kind = 'solution' if row['type'] == 'fill_blank' else row['type']
        self.new_question(kind)
        self.select_category(category)
        options = sorted(k for k in assets if k.startswith('option_'))
        if kind in ('single_choice', 'multiple_choice'):
            self.adjust_options(len(options))
        expected = len(options)+2 if kind in ('single_choice', 'multiple_choice') else (3 if kind == 'solution' else 2)
        self.wait_editors(expected)
        self.insert(0, assets['stem'])
        if kind in ('single_choice', 'multiple_choice'):
            for i, key in enumerate(options, 1):
                self.insert(i, assets[key])
            answers = self.page.get_by_text('设为正确答案', exact=True)
            if answers.count() != len(options):
                raise ValueError('无法对应正确答案控件')
            for answer in row['answer']:
                answers.nth(ord(answer)-ord('A')).click()
            explanation_index = len(options)+1
        else:
            if assets.get('answer'):
                self.insert(1, assets['answer'])
            elif row.get('answer'):
                self.editor_body(1).fill(row['answer'])
            else:
                self.insert(1, assets['explanation'])
            explanation_index = 2
        if assets.get('explanation'):
            self.insert(explanation_index, assets['explanation'])

    def adjust_options(self, count):
        from playwright.sync_api import expect
        if not 2 <= count <= 8:
            raise ValueError('选择题选项数量必须为 2–8 项')
        choices = self.page.get_by_text('设为正确答案', exact=True)
        current = choices.count()
        while current < count:
            self.page.get_by_role('button', name=re.compile('新增选项')).click()
            current += 1
            expect(choices).to_have_count(current)
        while current > count:
            self.page.get_by_role('img', name='close', exact=True).filter(visible=True).last.click()
            current -= 1
            expect(choices).to_have_count(current)
        self.wait_editors(count + 2)

    def wait_editors(self, count):
        from playwright.sync_api import expect, TimeoutError as BrowserTimeout
        from .upload import EditorNotReady
        editors = self.page.locator('iframe').filter(visible=True)
        try:
            expect(editors).to_have_count(count, timeout=20000)
            for index in range(count):
                editors.nth(index).content_frame.locator('body').wait_for(timeout=15000)
        except (AssertionError, BrowserTimeout) as exc:
            raise EditorNotReady(f'编辑器尚未加载完整：需要 {count} 个，当前显示 {editors.count()} 个。\n'
                                 '已保存的题目会保留，可点击“重试”继续。') from exc

    def save_question(self):
        self.page.get_by_role('button', name='保存', exact=True).click()
        # A click is not success; require navigation back to the question list.
        self.page.wait_for_url(re.compile(r'/questionBankIndex/questionIndex(?:\?|$)'), timeout=30000)
        self.page.get_by_role('button', name=re.compile('添加题目')).wait_for()
        self.dismiss_tip()

    def diagnose(self, path):
        if self.context:
            self.page.screenshot(path=str(path), full_page=False, timeout=5000)
            info = {'pages': [{'title': p.title(), 'url': p.url} for p in self.context.pages]}
            info['ui'] = self.page.locator('body').evaluate("""el => ({inputs:[...el.querySelectorAll('input')].map(x=>({type:x.type, placeholder:x.placeholder, cls:x.className})), loading:[...el.querySelectorAll('[class*=loading]')].map(x=>({cls:x.className,visible:!!x.getBoundingClientRect().height})), buttons:[...el.querySelectorAll('button')].filter(x=>x.getBoundingClientRect().height).map(x=>x.textContent)})""")
            Path(path).with_suffix('.json').write_text(json.dumps(info, ensure_ascii=False, indent=2))

    def close(self):
        if self.context:
            self.context.close()
        if self.runtime:
            self.runtime.stop()
