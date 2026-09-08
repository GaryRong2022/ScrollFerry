import copy
import sys
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk
from .core import crop_region, detect, export, read_pages, render_page

TYPE_NAMES = {'single_choice':'单选题','multiple_choice':'多选题','fill_blank':'填空题','solution':'解答题','unknown':'未分类'}
ASSET_NAMES = {'stem':'题干','answer':'答案原图','explanation':'解析', **{f'option_{x}':f'选项 {x}' for x in 'ABCDEFGH'}}


class App:
    def __init__(self, root):
        self.root = root
        root.title('ScrollFerry·舷渡-小鹅通题库上传工具-v1.0.2')
        root.geometry('1250x850')
        logo_path = Path(__file__).parent / 'assets' / 'logo.png'
        with Image.open(logo_path) as logo:
            self.logo_icon = ImageTk.PhotoImage(logo.resize((256, 256), Image.Resampling.LANCZOS))
            self.logo_toolbar = ImageTk.PhotoImage(logo.resize((40, 40), Image.Resampling.LANCZOS))
        root.iconphoto(True, self.logo_icon)
        self.project = None
        self.page = 0
        self.scale = 1.2
        self.photo = None
        self.entries = []
        self.busy = False
        self.undo_stack = []
        self.redo_stack = []
        self.export_parent = None
        self.last_export = None
        toolbar = ttk.Frame(root, padding=10)
        toolbar.pack(fill='x')
        ttk.Label(toolbar, image=self.logo_toolbar).pack(side='left', padx=(0, 8))
        for label, action in [('打开 PDF', self.open_pdf), ('读取工程', self.load), ('保存工程', self.save), ('导出截图', self.export), ('小鹅通上传', self.upload)]:
            ttk.Button(toolbar, text=label, command=lambda f=action: self.safe(f)).pack(side='left', padx=4)
        self.status = tk.StringVar(value='打开 PDF 自动分析，在页面中检查或调整，点击导出时再保存截图。')
        ttk.Label(root, textvariable=self.status, padding=8).pack(fill='x')
        body = ttk.Panedwindow(root, orient='horizontal')
        body.pack(fill='both', expand=True)
        left = ttk.Frame(body, padding=10)
        body.add(left, weight=1)
        self.tree = ttk.Treeview(left, show='tree', height=24)
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        for label, action in [('新增题目', self.add_question), ('新增截图', self.add_asset), ('删除所选截图', self.delete_asset), ('预览去标号截图', self.preview)]:
            ttk.Button(left, text=label, command=lambda f=action: self.safe(f)).pack(fill='x', pady=3)
        ttk.Label(left, text='新截图类型').pack(anchor='w')
        self.kind = tk.StringVar(value='stem')
        ttk.Combobox(left, textvariable=self.kind, state='readonly', values=['stem'] + [f'option_{x}' for x in 'ABCDEFGH'] + ['answer','explanation']).pack(fill='x')
        self.question_type = tk.StringVar(value='单选题')
        ttk.Label(left, text='题型').pack(anchor='w')
        ttk.Combobox(left, textvariable=self.question_type, state='readonly', values=list(TYPE_NAMES.values())).pack(fill='x')
        self.issue_text = tk.StringVar()
        ttk.Label(left, textvariable=self.issue_text, wraplength=240).pack(fill='x', pady=4)
        ttk.Label(left, text='答案（文字，可修改）').pack(anchor='w', pady=(10, 0))
        self.answer = tk.StringVar()
        ttk.Entry(left, textvariable=self.answer).pack(fill='x')
        self.reviewed = tk.BooleanVar()
        ttk.Checkbutton(left, text='此题截图和答案已校对', variable=self.reviewed).pack(anchor='w')
        ttk.Button(left, text='保存此题答案与校对状态', command=lambda: self.safe(self.commit)).pack(fill='x', pady=5)
        right = ttk.Frame(body)
        body.add(right, weight=4)
        nav = ttk.Frame(right, padding=6)
        nav.pack(fill='x')
        ttk.Button(nav, text='上一页', command=lambda: self.safe(lambda: self.turn(-1))).pack(side='left')
        ttk.Button(nav, text='下一页', command=lambda: self.safe(lambda: self.turn(1))).pack(side='left')
        self.mode = tk.StringVar(value='browse')
        for label, value in [('浏览', 'browse'), ('调整截图', 'crop'), ('擦除标号', 'mask'), ('添加片段', 'append')]:
            ttk.Radiobutton(nav, text=label, variable=self.mode, value=value).pack(side='left', padx=5)
        ttk.Button(nav, text='撤销', command=self.undo).pack(side='left')
        ttk.Button(nav, text='重做', command=self.redo).pack(side='left')
        ttk.Label(right, text='先选择左侧截图，再选择操作并拖动。添加片段可用于跨页；Esc 返回浏览。', padding=5).pack(fill='x')
        frame = ttk.Frame(right)
        frame.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(frame, bg='#dfe3e8')
        sy = ttk.Scrollbar(frame, orient='vertical', command=self.canvas.yview)
        sx = ttk.Scrollbar(frame, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=sy.set, xscrollcommand=sx.set)
        sy.pack(side='right', fill='y')
        sx.pack(side='bottom', fill='x')
        self.canvas.pack(fill='both', expand=True)
        self.canvas.bind('<MouseWheel>', self.wheel)
        self.canvas.bind('<Button-4>', self.wheel)
        self.canvas.bind('<Button-5>', self.wheel)
        self.root.bind('<Escape>', lambda e: self.cancel_drag())
        modifier = 'Command' if sys.platform == 'darwin' else 'Control'
        self.root.bind(f'<{modifier}-z>', self.undo)
        self.root.bind(f'<{modifier}-Shift-Z>', self.redo)
        self.canvas.bind('<ButtonPress-1>', self.start_drag)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', lambda event: self.safe(lambda: self.end_drag(event)))

    def safe(self, action):
        try:
            action()
        except Exception as exc:
            self.notice('操作未完成', str(exc))

    def run_job(self, title, work, done):
        if self.busy:
            raise ValueError('正在处理，请等待当前任务完成')
        self.busy = True
        messages = queue.Queue()
        cancelled = threading.Event()
        popup = tk.Toplevel(self.root)
        popup.title(title)
        self.center(popup, 480, 180)
        popup.transient(self.root)
        popup.grab_set()
        label = tk.StringVar(value='正在准备…')
        ttk.Label(popup, textvariable=label, padding=18).pack(fill='x')
        bar = ttk.Progressbar(popup, maximum=100, length=430)
        bar.pack(padx=20, pady=10)
        def cancel():
            cancelled.set()
            label.set('正在取消，等待当前步骤结束…')
        ttk.Button(popup, text='取消', command=cancel).pack()
        popup.protocol('WM_DELETE_WINDOW', cancel)
        def progress(stage, current, total):
            if cancelled.is_set():
                raise InterruptedError('已取消处理')
            messages.put(('progress', (stage, current, total)))
        def worker():
            try:
                messages.put(('done', work(progress)))
            except Exception as exc:
                messages.put(('error', exc))
        def poll():
            try:
                while True:
                    kind, value = messages.get_nowait()
                    if kind == 'progress':
                        stage, current, total = value
                        label.set(f'{stage}  {current}/{total}')
                        bar['value'] = 100 * current / max(1, total)
                    else:
                        self.busy = False
                        popup.grab_release()
                        popup.destroy()
                        if kind == 'error':
                            self.status.set(str(value))
                            self.notice('处理未完成', str(value))
                        else:
                            self.safe(lambda: done(value))
                        return
            except queue.Empty:
                self.root.after(80, poll)
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(80, poll)

    def open_pdf(self):
        path = filedialog.askopenfilename(parent=self.root, filetypes=[('PDF 试卷', '*.pdf')])
        if not path:
            return
        def work(progress):
            pages = read_pages(path, progress)
            project = detect(path, pages=pages, progress=progress)
            return project, pages
        def done(result):
            project, pages = result
            self.undo_stack.clear()
            self.redo_stack.clear()
            self.last_export = None
            self.project, self.pages, self.page = project, pages, 0
            self.refresh()
            self.show_page()
            issues = sum(bool(q.get('issues')) for q in project['questions'])
            self.status.set(f'已分析 {len(project["questions"])} 题；{issues} 题需检查。点击导出保存截图。')
        self.run_job('自动拆题与截图', work, done)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        for qi, q in enumerate(self.project['questions']):
            parent = self.tree.insert('', 'end', iid=f'q{qi}', text=f"{'✓' if q['reviewed'] else ('⚠' if q.get('issues') else '○')} {q['id']} {TYPE_NAMES.get(q.get('type'), '未分类')}", open=True)
            for ai, asset in enumerate(q['assets']):
                self.tree.insert(parent, 'end', iid=f'q{qi}a{ai}', text=ASSET_NAMES.get(asset['kind'],asset['kind']))

    def selected(self):
        selection = self.tree.selection()
        if not selection:
            raise ValueError('请先在左侧选择题目或截图')
        parts = selection[0][1:].split('a')
        q = self.project['questions'][int(parts[0])]
        return q, q['assets'][int(parts[1])] if len(parts) > 1 else None

    def select(self, event=None):
        if not self.tree.selection():
            return
        q, asset = self.selected()
        self.answer.set(q['answer'])
        self.reviewed.set(q['reviewed'])
        self.question_type.set(TYPE_NAMES.get(q.get('type'), '未分类'))
        self.issue_text.set('；'.join(q.get('issues', [])) or ('答案包含在解题步骤中' if q.get('answer_status')=='in_explanation' else ''))
        if asset and asset['regions']:
            self.page = asset['regions'][0]['page']
        self.show_page()

    def show_page(self):
        if not self.project:
            return
        self.photo = ImageTk.PhotoImage(render_page(self.project['source'], self.page, self.scale))
        self.canvas.delete('all')
        self.canvas.create_image(0, 0, anchor='nw', image=self.photo)
        self.canvas.configure(scrollregion=(0, 0, self.photo.width(), self.photo.height()))
        if self.tree.selection():
            _, asset = self.selected()
            for r in asset['regions'] if asset else []:
                if r['page'] == self.page:
                    self.canvas.create_rectangle(*[v * self.scale for v in r['box']], outline='#16856b', width=2)
                    for mask in r['masks']:
                        self.canvas.create_rectangle(*[v * self.scale for v in mask], outline='#d74b55', fill='white')
        self.status.set(f'第 {self.page+1} / {len(self.pages)} 页 · 绿色为截图范围；白色红框为去标号区域 · 修改后需重新校对')

    def turn(self, delta):
        if self.project:
            self.page = max(0, min(len(self.pages)-1, self.page+delta))
            self.show_page()

    def start_drag(self, event):
        if self.mode.get() == 'browse':
            self.origin = None
            return
        self.origin = (self.canvas.canvasx(event.x), self.canvas.canvasy(event.y))

    def drag(self, event):
        if not getattr(self, 'origin', None):
            return
        self.canvas.delete('drag')
        self.canvas.create_rectangle(*self.origin, self.canvas.canvasx(event.x), self.canvas.canvasy(event.y), outline='#4263eb', width=2, tags='drag')

    def end_drag(self, event):
        if not getattr(self, 'origin', None):
            return
        q, asset = self.selected()
        if asset is None:
            raise ValueError('请选择或新增一个截图')
        x, y = self.origin
        ex, ey = self.canvas.canvasx(event.x), self.canvas.canvasy(event.y)
        page = self.pages[self.page]
        box = [max(0, min(x, ex)/self.scale), max(0, min(y, ey)/self.scale), min(page['width'], max(x, ex)/self.scale), min(page['height'], max(y, ey)/self.scale)]
        if box[2]-box[0] < 2 or box[3]-box[1] < 2:
            return
        candidates = [r for r in asset['regions'] if r['page'] == self.page]
        if self.mode.get() == 'mask' and not candidates:
            raise ValueError('请先在本页框选截图范围')
        self.checkpoint()
        if self.mode.get() == 'append':
            asset['regions'].append({'page': self.page, 'box': box, 'masks': []})
        elif not candidates:
            if self.mode.get() == 'mask':
                raise ValueError('请先在本页框选截图范围')
            asset['regions'].append({'page': self.page, 'box': box, 'masks': []})
        elif self.mode.get() == 'mask':
            candidates[-1]['masks'].append(box)
        else:
            candidates[-1]['box'] = box
        q['reviewed'] = False
        self.reviewed.set(False)
        self.origin = None
        self.show_page()

    def undo_mask(self):
        q, asset = self.selected()
        for region in reversed(asset['regions'] if asset else []):
            if region['page'] == self.page and region['masks']:
                region['masks'].pop()
                q['reviewed'] = False
                self.reviewed.set(False)
                self.show_page()
                break

    def add_question(self):
        if not self.project:
            raise ValueError('请先打开 PDF')
        self.checkpoint()
        n = len(self.project['questions']) + 1
        self.project['questions'].append({'id': f'Q{n:04d}', 'original_number': str(n), 'answer': '', 'reviewed': False, 'assets': []})
        self.refresh()
        self.tree.selection_set(f'q{n-1}')

    def add_asset(self):
        q, _ = self.selected()
        self.checkpoint()
        q['assets'].append({'kind': self.kind.get(), 'regions': []})
        q['reviewed'] = False
        qi = self.project['questions'].index(q)
        self.refresh()
        self.tree.selection_set(f'q{qi}a{len(q["assets"])-1}')

    def delete_asset(self):
        q, asset = self.selected()
        if asset:
            self.checkpoint()
            q['assets'].remove(asset)
            q['reviewed'] = False
            self.refresh()

    def commit(self):
        q, _ = self.selected()
        self.checkpoint()
        q['answer'] = self.answer.get().strip()
        q['type'] = next(k for k,v in TYPE_NAMES.items() if v == self.question_type.get())
        needs_answer = q['type'] in ('single_choice','multiple_choice','fill_blank')
        if self.reviewed.get() and ((needs_answer and not q['answer']) or not q['assets'] or any(not a['regions'] for a in q['assets'])):
            raise ValueError('请填写答案并为每个截图框选区域')
        q['reviewed'] = self.reviewed.get()
        if q['reviewed']:
            q['answer_status'] = 'verified' if q['answer'] else 'in_explanation'
            q['issues'] = []
        selected = self.tree.selection()[0]
        self.refresh()
        self.tree.selection_set(selected)

    def preview(self):
        _, asset = self.selected()
        if not asset or not asset['regions']:
            raise ValueError('请选择已有截图范围的项目')
        from PIL import Image
        parts = [crop_region(self.project['source'], r) for r in asset['regions']]
        combined = Image.new('RGB', (max(p.width for p in parts), sum(p.height for p in parts)), 'white')
        y = 0
        for part in parts:
            combined.paste(part, (0,y))
            y += part.height
        popup = tk.Toplevel(self.root)
        popup.title('截图预览')
        self.center(popup, 900, 650)
        canvas = tk.Canvas(popup, background='#e5e7eb')
        scroll = ttk.Scrollbar(popup, command=canvas.yview)
        scroll.pack(side='right', fill='y')
        canvas.pack(fill='both', expand=True)
        canvas.configure(yscrollcommand=scroll.set)
        photo = ImageTk.PhotoImage(combined)
        canvas.photo = photo
        canvas.create_image(0,0,anchor='nw',image=photo)
        canvas.configure(scrollregion=(0,0,photo.width(),photo.height()))
        canvas.bind('<MouseWheel>', lambda e: canvas.yview_scroll(-1 if e.delta>0 else 1, 'units'))
        popup.grab_set()

    def save(self):
        if not self.project:
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension='.json', filetypes=[('拆题工程', '*.json')])
        if path:
            Path(path).write_text(json.dumps(self.project, ensure_ascii=False, indent=2), encoding='utf-8')

    def load(self):
        path = filedialog.askopenfilename(parent=self.root, filetypes=[('拆题工程', '*.json')])
        if path:
            project = json.loads(Path(path).read_text(encoding='utf-8'))
            if not Path(project['source']).is_file():
                source = filedialog.askopenfilename(parent=self.root, title='请重新选择工程对应的原始 PDF', filetypes=[('PDF', '*.pdf')])
                if not source:
                    return
                project['source'] = source
            def done(pages):
                self.undo_stack.clear()
                self.redo_stack.clear()
                self.last_export = None
                self.project, self.pages, self.page = project, pages, 0
                self.refresh()
                self.show_page()
            self.run_job('载入工程', lambda progress: read_pages(project['source'], progress), done)

    def export(self):
        if not self.project:
            return
        path = filedialog.askdirectory(parent=self.root, title='选择保存位置（自动新建批次文件夹）', initialdir=self.export_parent or str(Path.home()))
        if not path:
            return
        self.export_parent = path
        from .core import new_batch_path
        output = new_batch_path(path, Path(self.project['source']).stem)
        snapshot = copy.deepcopy(self.project)
        def done(rows):
            self.last_export = output
            self.notice('导出完成', f'已保存 {len(rows)} 题。\n{output}')
        self.run_job('导出截图', lambda progress: export(snapshot, output, progress=progress), done)

    def upload(self):
        if not self.last_export:
            manifest = filedialog.askopenfilename(parent=self.root, title='选择已导出批次的 manifest.json', filetypes=[('批次清单', 'manifest.json')])
            if not manifest:
                return
            self.last_export = Path(manifest).parent
        from .upload import prepare_upload, execute
        from .xiaoe import XiaoeBrowser
        report = prepare_upload(self.last_export)
        popup = tk.Toplevel(self.root)
        popup.title('上传到小鹅通 · 试用')
        self.center(popup, 720, 500)
        popup.grab_set()
        saved = sum(q['status'] == 'saved' for q in report['questions'])
        pending = sum(q['status'] == 'pending' for q in report['questions'])
        ttk.Label(popup, text=f'当前批次：{len(report["questions"])} 题 / {report["image_count"]} 张图\n'
                  f'可上传 {pending} 题，已保存 {saved} 题，需补全 {report["unresolved_questions"]} 题',
                  padding=16).pack(fill='x')
        ttk.Label(popup, text=f'素材分组：{report.get("material_group", "旧版批次，请重新导出")}\n'
                  '全部截图先上传至该分组，再按完整文件名搜索插题。',
                  wraplength=660, padding=(16, 0, 16, 12)).pack(fill='x')
        ttk.Label(popup, text='题库分类（自动创建，与素材分组同名）').pack(anchor='w', padx=16)
        category = tk.StringVar(value=report.get('material_group', ''))
        ttk.Entry(popup, textvariable=category, state='readonly').pack(fill='x', padx=16, pady=8)
        ttk.Label(popup, text='优先使用兼容的 Windows 默认浏览器，自动尝试 Chrome / Edge；首次需登录。\n'
                  '执行顺序：新建素材分组 → 集中上传 → 创建同名题库分类 → 搜索插题 → 保存。\n'
                  '从最后一题倒序录入；填空题按问答题上传，优先使用答案截图。',
                  wraplength=660, padding=16).pack(fill='x')
        blocked = '\n'.join(f'{q["id"]}：{q["reason"]}' for q in report['questions'] if q['status']=='blocked')
        def show_blocked():
            self.notice('需要补全的题目', blocked or '没有待补全题目')
            popup.grab_set()
        ttk.Button(popup, text='查看待补全题目', command=show_blocked).pack(pady=4)
        def start(limit, materials_only=False):
            destination = category.get().strip()
            if not destination and not materials_only:
                return
            popup.destroy()
            batch = self.last_export
            def done(state):
                count = sum(q['status']=='saved' for q in state['questions'])
                uploaded = sum(i['status']=='uploaded' for i in state['images'])
                self.notice('上传结果', f'素材分组：{state.get("material_group", "")}\n'
                            f'已上传 {uploaded} 张图；累计保存 {count} 题。\n'
                            f'待补全 {state["unresolved_questions"]} 题。\n进度已保存在批次 upload-queue.json。')
            self.run_job('小鹅通上传', lambda progress: execute(batch, destination, XiaoeBrowser(), progress, limit, materials_only), done)
        buttons = ttk.Frame(popup)
        buttons.pack(pady=12)
        ttk.Button(buttons, text='仅上传整卷图片', command=lambda: start(None, True)).pack(side='left', padx=8)
        ttk.Button(buttons, text='试传下一题', command=lambda: start(1)).pack(side='left', padx=8)
        ttk.Button(buttons, text='上传全部可用题目', command=lambda: start(None)).pack(side='left', padx=8)
        ttk.Button(buttons, text='关闭', command=popup.destroy).pack(side='left', padx=8)

    def center(self, window, width, height):
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width()-width)//2
        y = self.root.winfo_rooty() + (self.root.winfo_height()-height)//2
        window.geometry(f'{width}x{height}+{max(0,x)}+{max(0,y)}')
        window.transient(self.root)

    def notice(self, title, text):
        popup = tk.Toplevel(self.root)
        popup.title(title)
        self.center(popup, 520, 250)
        ttk.Label(popup, text=text, wraplength=475, padding=20).pack(fill='both', expand=True)
        ttk.Button(popup, text='确定', command=popup.destroy).pack(pady=12)
        popup.grab_set()
        popup.bind('<Return>', lambda e: popup.destroy())
        popup.wait_window()

    def checkpoint(self):
        self.last_export = None
        self.undo_stack.append((copy.deepcopy(self.project), self.page, self.tree.selection()))
        self.undo_stack = self.undo_stack[-50:]
        self.redo_stack.clear()

    def restore(self, source, target):
        if not source or self.busy:
            return
        target.append((copy.deepcopy(self.project), self.page, self.tree.selection()))
        self.project, self.page, selection = source.pop()
        self.last_export = None
        self.refresh()
        if selection and self.tree.exists(selection[0]):
            self.tree.selection_set(selection[0])
        self.show_page()

    def undo(self, event=None):
        if event and isinstance(event.widget, (tk.Entry, ttk.Entry, tk.Text)):
            return
        self.restore(self.undo_stack, self.redo_stack)
        return 'break'

    def redo(self, event=None):
        if event and isinstance(event.widget, (tk.Entry, ttk.Entry, tk.Text)):
            return
        self.restore(self.redo_stack, self.undo_stack)
        return 'break'

    def cancel_drag(self):
        self.origin = None
        self.canvas.delete('drag')
        self.mode.set('browse')

    def wheel(self, event):
        delta = -1 if getattr(event,'num',0)==4 else 1 if getattr(event,'num',0)==5 else (-1 if event.delta>0 else 1)
        amount = max(1, min(12, abs(int(event.delta)) if sys.platform=='darwin' else abs(int(event.delta/120)))) if getattr(event,'delta',0) else 1
        top,bottom = self.canvas.yview()
        if delta>0 and bottom>=.999 and self.project and self.page<len(self.pages)-1:
            self.turn(1);self.canvas.yview_moveto(0)
        elif delta<0 and top<=.001 and self.project and self.page>0:
            self.turn(-1);self.canvas.yview_moveto(1)
        else:
            self.canvas.yview_scroll(delta*amount,'units')
        return 'break'


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
