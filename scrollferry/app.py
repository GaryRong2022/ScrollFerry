import copy
import math
import sys
import json
import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk, ImageDraw
from . import __version__
from .core import detect, export, read_pages, render_page, render_asset, tighten_regions, repair_prefix_masks, paint_mask

TYPE_NAMES = {'single_choice':'单选题','multiple_choice':'多选题','fill_blank':'填空题','solution':'解答题','unknown':'未分类'}
ASSET_NAMES = {'stem':'题干','answer':'答案原图','explanation':'解析', **{f'option_{x}':f'选项 {x}' for x in 'ABCDEFGH'}}
APP_NAME = f'舷渡 ScrollFerry · v{__version__}'


def touchpad_pixels(delta):
    """Tk 9 packs signed X/Y distances into the high/low 16 bits."""
    raw = int(delta) & 0xffffffff
    def signed(value):
        return value - 65536 if value >= 32768 else value
    return tuple(max(-36,min(36,-signed(value))) for value in (raw >> 16,raw & 65535))


def wheel_pixels(event):
    """Small pixel steps, independent of the viewport height and Tk defaults."""
    number = getattr(event, 'num', None)
    if number in (4, 5):
        return -18 if number == 4 else 18
    delta = getattr(event, 'delta', 0)
    pixels = -delta * 2 if sys.platform == 'darwin' else -delta * 18 / 120
    return max(-36, min(36, pixels))


def reveal_offset(start, end, viewport, total, margin=24):
    """Center a small crop; show the beginning of a crop taller than the view."""
    position = (start + end - viewport) / 2 if end-start <= viewport-2*margin else start-margin
    return max(0, min(position, max(0, total-viewport))) / max(1, total)


class App:
    def __init__(self, root):
        self.root = root
        root.title(APP_NAME)
        root.tk.call('tk', 'appname', APP_NAME)
        from .theme import apply_theme
        self.theme = apply_theme(root)
        root.geometry(f'{min(1320, root.winfo_screenwidth()-60)}x{min(900, root.winfo_screenheight()-100)}')
        root.minsize(1040, 700)
        logo_path = Path(__file__).parent / 'assets' / 'logo.png'
        with Image.open(logo_path) as logo:
            self.logo_icon = ImageTk.PhotoImage(logo.resize((256, 256), Image.Resampling.LANCZOS))
            self.logo_toolbar = ImageTk.PhotoImage(logo.resize((40, 40), Image.Resampling.LANCZOS))
            self.logo_welcome = ImageTk.PhotoImage(logo.resize((80, 80), Image.Resampling.LANCZOS))
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
        self.reduce_motion = tk.BooleanVar(value=False)
        header = ttk.Frame(root, padding=(24,16))
        header.pack(fill='x')
        ttk.Label(header, image=self.logo_toolbar).pack(side='left', padx=(0,12))
        brand = ttk.Frame(header)
        brand.pack(side='left')
        ttk.Label(brand, text='舷渡', style='Title.TLabel').pack(anchor='w')
        ttk.Label(brand, text='ScrollFerry', style='Muted.TLabel').pack(anchor='w', pady=(2,0))
        ttk.Button(header, text='上传到小鹅通…', style='Primary.TButton', command=lambda: self.safe(self.upload)).pack(side='right')
        self.export_button = ttk.Button(header, text='导出截图', command=lambda: self.safe(self.export), state='disabled')
        self.export_button.pack(side='right', padx=10)
        ttk.Separator(header, orient='vertical').pack(side='left',fill='y',padx=24)
        import_button = ttk.Menubutton(header, text='导入文件  ▾')
        import_button.pack(side='left')
        imports = tk.Menu(import_button, tearoff=False)
        imports.add_command(label='打开 PDF…', command=lambda:self.safe(self.open_pdf))
        imports.add_command(label='题目＋解析 PDF…', command=lambda:self.safe(lambda:self.open_pdf(separate=True)))
        imports.add_separator()
        imports.add_command(label='读取工程…', command=lambda:self.safe(self.load))
        import_button.configure(menu=imports)
        ttk.Button(header,text='保存工程',style='Quiet.TButton',command=lambda:self.safe(self.save)).pack(side='left',padx=8)
        ttk.Button(header,text='侧栏',style='Quiet.TButton',command=self.toggle_sidebar).pack(side='left')
        self.status = tk.StringVar(value='准备就绪 · 选择 PDF 或读取工程开始整理')
        ttk.Label(root, textvariable=self.status, style='Status.TLabel', wraplength=1000).pack(side='bottom', fill='x')
        body = ttk.Panedwindow(root, orient='horizontal')
        body.pack(fill='both', expand=True, padx=20, pady=(16,0))
        sidebar = ttk.Frame(body)
        self.body, self.sidebar = body, sidebar
        self.sidebar_visible = True
        body.add(sidebar, weight=1)
        self.sidebar_canvas = tk.Canvas(sidebar, width=320, height=400, highlightthickness=0, background='white')
        sidebar_scroll = ttk.Scrollbar(sidebar, orient='vertical', command=self.sidebar_canvas.yview)
        self.sidebar_canvas.configure(yscrollcommand=sidebar_scroll.set)
        sidebar_scroll.pack(side='right', fill='y')
        self.sidebar_canvas.pack(side='left', fill='both', expand=True)
        left = ttk.Frame(self.sidebar_canvas, padding=16)
        sidebar_window = self.sidebar_canvas.create_window(0, 0, anchor='nw', window=left)
        def resize_sidebar(event=None):
            self.sidebar_canvas.itemconfigure(sidebar_window, width=self.sidebar_canvas.winfo_width(),
                                             height=max(left.winfo_reqheight(), self.sidebar_canvas.winfo_height()))
            self.sidebar_canvas.configure(scrollregion=self.sidebar_canvas.bbox('all'))
        left.bind('<Configure>', resize_sidebar)
        self.sidebar_canvas.bind('<Configure>', resize_sidebar)
        ttk.Label(left, text='题目导航', style='Section.TLabel').pack(anchor='w')
        self.paper_stats = tk.StringVar(value='尚未导入试卷')
        ttk.Label(left, textvariable=self.paper_stats, style='Muted.TLabel').pack(anchor='w', pady=(5,12))
        question_list = ttk.Frame(left)
        question_list.pack(fill='both', expand=True)
        self.tree = ttk.Treeview(question_list, show='tree', height=9)
        question_scroll = ttk.Scrollbar(question_list, orient='vertical', command=self.tree.yview)
        self.tree.configure(yscrollcommand=question_scroll.set)
        question_scroll.pack(side='right', fill='y')
        self.tree.pack(fill='both', expand=True)
        self.tree.bind('<<TreeviewSelect>>', self.select)
        actions = ttk.Frame(left)
        actions.pack(fill='x', pady=(10,14))
        actions.columnconfigure((0,1),weight=1)
        for index,(label,action,style) in enumerate([
                ('＋ 新增题目',self.add_question,'TButton'), ('＋ 新增截图',self.add_asset,'TButton'),
                ('预览截图',self.preview,'TButton'), ('删除截图',self.delete_asset,'Danger.TButton')]):
            ttk.Button(actions,text=label,style=style,command=lambda f=action:self.safe(f)).grid(
                row=index//2,column=index%2,sticky='ew',padx=(0,6) if index%2==0 else (0,0),pady=3)
        ttk.Separator(left).pack(fill='x',pady=(0,14))
        ttk.Label(left,text='校对与编辑',style='Section.TLabel').pack(anchor='w',pady=(0,10))
        fields=ttk.Frame(left)
        fields.pack(fill='x')
        fields.columnconfigure((0,1),weight=1)
        ttk.Label(fields,text='新截图类型',style='Muted.TLabel').grid(row=0,column=0,sticky='w',pady=(0,5))
        ttk.Label(fields,text='题型',style='Muted.TLabel').grid(row=0,column=1,sticky='w',pady=(0,5))
        self.kind = tk.StringVar(value='题干')
        ttk.Combobox(fields,textvariable=self.kind,state='readonly',width=10,
                     values=list(ASSET_NAMES.values())).grid(row=1,column=0,sticky='ew',padx=(0,8))
        self.question_type = tk.StringVar(value='单选题')
        ttk.Combobox(fields,textvariable=self.question_type,state='readonly',width=10,
                     values=list(TYPE_NAMES.values())).grid(row=1,column=1,sticky='ew')
        self.issue_text = tk.StringVar()
        ttk.Label(left,textvariable=self.issue_text,wraplength=275,style='Muted.TLabel').pack(fill='x',pady=(10,5))
        ttk.Label(left,text='参考答案',style='Muted.TLabel').pack(anchor='w',pady=(8,5))
        self.answer = tk.StringVar()
        ttk.Entry(left,textvariable=self.answer).pack(fill='x')
        self.reviewed = tk.BooleanVar()
        ttk.Checkbutton(left,text='已校对截图和答案',variable=self.reviewed).pack(anchor='w',pady=(4,0))
        ttk.Button(left,text='保存本题校对',style='Primary.TButton',command=lambda:self.safe(self.commit)).pack(fill='x',pady=(6,0))
        self.bind_scroll(self.sidebar_canvas, sidebar_scroll)
        self.bind_scroll(self.tree, question_scroll)
        right = ttk.Frame(body)
        body.add(right, weight=4)
        document_header = ttk.Frame(right,padding=(20,18))
        document_header.pack(fill='x')
        self.document_title = tk.StringVar(value='PDF 校对台')
        ttk.Label(document_header,textvariable=self.document_title,style='Section.TLabel').pack(side='left')
        self.page_label = tk.StringVar(value='未打开文件')
        ttk.Label(document_header,textvariable=self.page_label,style='Badge.TLabel').pack(side='right')
        ttk.Label(document_header,text='连续阅读',style='Muted.TLabel').pack(side='right',padx=8)
        nav = ttk.Frame(right,padding=(14,0,14,10))
        nav.pack(fill='x')
        self.mode = tk.StringVar(value='browse')
        for label,value in [('浏览','browse'),('调整截图','crop'),('擦除标号','mask'),('追加片段','append')]:
            ttk.Radiobutton(nav,text=label,variable=self.mode,value=value,style='Tool.TRadiobutton',
                            command=self.change_edit_mode).pack(side='left',padx=(0,3))
        ttk.Button(nav,text='重做',style='Quiet.TButton',command=self.redo).pack(side='right')
        ttk.Button(nav,text='撤销',style='Quiet.TButton',command=self.undo).pack(side='right')
        pager=ttk.Frame(right,padding=(14,10))
        pager.pack(side='bottom',fill='x')
        ttk.Button(pager,text='‹ 上一页',command=lambda:self.safe(lambda:self.turn(-1))).pack(side='left')
        ttk.Button(pager,text='下一页 ›',command=lambda:self.safe(lambda:self.turn(1))).pack(side='left',padx=6)
        ttk.Label(pager,text='Esc 返回浏览',style='Muted.TLabel').pack(side='left',padx=8)
        ttk.Button(pager,text='＋',width=3,command=lambda:self.safe(lambda:self.zoom(.1))).pack(side='right')
        ttk.Button(pager,text='－',width=3,command=lambda:self.safe(lambda:self.zoom(-.1))).pack(side='right',padx=3)
        frame = ttk.Frame(right)
        frame.pack(fill='both', expand=True)
        self.canvas = tk.Canvas(frame, bg='#eef1f6', highlightthickness=0)
        sy = ttk.Scrollbar(frame, orient='vertical', command=self.canvas.yview)
        sx = ttk.Scrollbar(frame, orient='horizontal', command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=lambda first,last:self.document_scrolled(sy,first,last), xscrollcommand=sx.set)
        sy.pack(side='right', fill='y')
        sx.pack(side='bottom', fill='x')
        self.canvas.pack(fill='both', expand=True)
        self.bind_scroll(self.canvas, sy)
        self.bind_scroll(self.canvas, sx, axis='x', include_target=False)
        self.root.bind('<Escape>', lambda e: self.cancel_drag())
        modifier = 'Command' if sys.platform == 'darwin' else 'Control'
        self.root.bind(f'<{modifier}-z>', self.undo)
        self.root.bind(f'<{modifier}-Shift-Z>', self.redo)
        self.canvas.bind('<Configure>', self.show_empty_state)
        self.show_empty_state()
        def set_initial_split(event):
            if event.width > 500:
                body.sashpos(0,340)
                body.unbind('<Configure>', split_binding)
        split_binding = body.bind('<Configure>', set_initial_split)
        self.canvas.bind('<ButtonPress-1>', self.start_drag)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<ButtonRelease-1>', lambda event: self.safe(lambda: self.end_drag(event)))
        self.install_menus()
        self.install_wheel_routing()

    def toggle_sidebar(self):
        if self.sidebar_visible:
            self.sidebar_width = self.body.sashpos(0)
            self.body.forget(self.sidebar)
        else:
            self.body.insert(0, self.sidebar, weight=1)
            self.body.sashpos(0, getattr(self, 'sidebar_width', 340))
        self.sidebar_visible = not self.sidebar_visible

    def install_menus(self):
        bar = tk.Menu(self.root)
        self.root.configure(menu=bar)
        modifier = 'Command' if sys.platform == 'darwin' else 'Control'
        prefix = '⌘' if sys.platform == 'darwin' else 'Ctrl+'
        def command(menu, label, action, key=None):
            def invoke(event=None):
                if self.root.grab_current() is None:
                    self.safe(action)
                return 'break'
            shortcut = {'equal':'+', 'minus':'−'}.get(key, key.upper() if key else '')
            menu.add_command(label=label, command=invoke, accelerator=prefix+shortcut if key else '')
            if key:
                self.root.bind(f'<{modifier}-{key}>', invoke)
        files = tk.Menu(bar, tearoff=False)
        bar.add_cascade(label='文件', menu=files)
        command(files, '打开 PDF…', self.open_pdf, 'o')
        command(files, '打开题目与解析 PDF…', lambda:self.open_pdf(separate=True))
        command(files, '读取工程…', self.load)
        command(files, '保存工程…', self.save, 's')
        files.add_separator()
        command(files, '导出截图…', self.export)
        command(files, '上传到小鹅通…', self.upload)
        edit = tk.Menu(bar, tearoff=False)
        bar.add_cascade(label='编辑', menu=edit)
        def edit_action(sequence, fallback=None):
            focused = self.root.focus_get()
            if isinstance(focused, (tk.Entry, ttk.Entry, tk.Text)):
                focused.event_generate(sequence)
            elif fallback:
                fallback()
        edit.add_command(label='撤销', accelerator=prefix+'Z', command=lambda:edit_action('<<Undo>>', self.undo))
        edit.add_command(label='重做', accelerator=prefix+'⇧Z', command=lambda:edit_action('<<Redo>>', self.redo))
        edit.add_separator()
        for label, event in [('剪切','<<Cut>>'),('复制','<<Copy>>'),('粘贴','<<Paste>>'),('全选','<<SelectAll>>')]:
            edit.add_command(label=label, command=lambda e=event:edit_action(e))
        view = tk.Menu(bar, tearoff=False)
        bar.add_cascade(label='显示', menu=view)
        command(view, '显示／隐藏侧栏', self.toggle_sidebar)
        command(view, '放大', lambda:self.zoom(.1), 'equal')
        command(view, '缩小', lambda:self.zoom(-.1), 'minus')
        view.add_separator()
        view.add_checkbutton(label='减少动态效果', variable=self.reduce_motion)
        help_menu = tk.Menu(bar, tearoff=False)
        bar.add_cascade(label='帮助', menu=help_menu)
        command(help_menu, '校对操作说明', lambda:self.notice('校对操作说明',
            '选择左侧题干或选项可定位到对应截图。\n\n使用“调整截图”修改边界；使用“擦除标号”清除题号。\nEsc 返回浏览，滚轮滚动，Shift＋滚轮横向移动。\n\n删除和调整截图均可撤销。完成校对后，导出截图或上传到小鹅通。'))

    def show_empty_state(self, event=None):
        if self.project:
            return
        self.canvas.delete('empty')
        if not hasattr(self, 'empty_panel'):
            panel = self.empty_panel = ttk.Frame(self.canvas, style='Canvas.TFrame',padding=(40,28))
            self.empty_logo = ttk.Label(panel,image=self.logo_welcome,style='Canvas.TLabel')
            self.empty_logo.pack(pady=(0,22))
            self.empty_heading = ttk.Label(panel,text='从一份试卷开始',style='Welcome.TLabel')
            self.empty_heading.pack()
            ttk.Label(panel,text='导入 PDF，整理题干、选项与解析。\n校对完成后，即可导出或上传题库。',
                      justify='center',style='WelcomeHint.TLabel').pack(pady=(12,24))
            ttk.Button(panel,text='打开 PDF',style='Primary.TButton',width=18,
                       command=lambda:self.safe(self.open_pdf)).pack()
            ttk.Button(panel,text='题目与解析是两个文件',style='Quiet.TButton',
                       command=lambda:self.safe(lambda:self.open_pdf(separate=True))).pack(pady=(10,0))
        if self.canvas.winfo_height() < 460:
            self.empty_logo.pack_forget()
        elif not self.empty_logo.winfo_manager():
            self.empty_logo.pack(before=self.empty_heading,pady=(0,22))
        self.canvas.create_window(self.canvas.winfo_width()/2,self.canvas.winfo_height()/2,
                                  window=self.empty_panel,tags='empty')

    def zoom(self, delta):
        if not self.project:
            return
        self.scale = round(max(.5,min(2.5,self.scale+delta)),2)
        self.show_page()
        if self.tree.selection():
            _, asset = self.selected()
            if asset and asset['regions']:
                region = next((r for r in asset['regions'] if r['page']==self.page),None)
                if region:
                    self.reveal_region(region)

    def scroll_sidebar(self, event):
        return self.scroll_content(self.sidebar_canvas, event)

    def bind_scroll(self, target, *controls, axis='y', include_target=True):
        for widget in ((target,) if include_target else ()) + controls:
            widget._scroll_target = (target, axis)

    def install_wheel_routing(self):
        # macOS can deliver wheel events to the focused window rather than
        # the widget under the pointer. Route before native class bindings.
        tag = 'ScrollFerryWheel'
        def attach(widget):
            if not isinstance(widget, tk.Misc):
                return
            if tag not in widget.bindtags():
                widget.bindtags((tag,) + widget.bindtags())
            for child in widget.winfo_children():
                attach(child)
        attach(self.root)
        self.root.bind_all('<Map>', lambda event: attach(event.widget), add='+')
        for sequence in ('<MouseWheel>', '<Shift-MouseWheel>', '<Button-4>', '<Button-5>'):
            self.root.bind_class(tag, sequence, self.route_wheel)
        try:
            self.root.bind_class(tag, '<TouchpadScroll>', lambda event:self.route_wheel(event, precise=True))
            self.root.bind_class(tag, '<Shift-TouchpadScroll>', lambda event:self.route_wheel(event, precise=True))
        except tk.TclError:
            pass  # Tk 8 does not define this event.

    def route_wheel(self, event, precise=False):
        x, y = self.root.winfo_pointerxy()
        widget = self.root.winfo_containing(x, y)
        if widget is None:
            return
        while widget is not None:
            if isinstance(widget, ttk.Combobox):
                return  # Keep the dropdown's native interaction.
            target = getattr(widget, '_scroll_target', None)
            if target:
                control, axis = target
                if precise:
                    dx, dy = touchpad_pixels(event.delta)
                    if getattr(event, 'state', 0) & 1:
                        dx, dy = dy, dx
                    if axis == 'x' and not dx:
                        dx, dy = dy, 0
                    if dx:
                        self.scroll_content(control,event,'x',pixels=dx)
                    if dy:
                        self.scroll_content(control,event,'y',pixels=dy)
                    return 'break'
                if getattr(event, 'state', 0) & 1:
                    axis = 'x'
                return self.scroll_content(control, event, axis)
            if isinstance(widget, (tk.Text, tk.Listbox)):
                if precise:
                    dx, dy = touchpad_pixels(event.delta)
                    if getattr(event,'state',0) & 1:
                        dx,dy = dy,dx
                    if dx: self.scroll_content(widget,event,'x',pixels=dx)
                    if dy: self.scroll_content(widget,event,'y',pixels=dy)
                    return 'break'
                return self.scroll_content(widget, event)
            widget = getattr(widget, 'master', None)

    def scroll_content(self, target, event, axis='y', pixels=None):
        if pixels is None:
            pixels = wheel_pixels(event)
        if isinstance(target, ttk.Treeview):
            # Treeview scrolls in whole rows. Accumulate small trackpad deltas
            # instead of letting Tk move several rows for every tiny gesture.
            key = '_wheel_remainder_' + axis
            remainder = getattr(target, key, 0) + pixels
            rows = int(remainder / 18)
            setattr(target, key, remainder - rows * 18)
            if rows:
                scroll = target.xview_scroll if axis == 'x' else target.yview_scroll
                scroll(rows, 'units')
        elif isinstance(target, (tk.Text, tk.Listbox)):
            if pixels:
                scroll = target.xview_scroll if axis == 'x' else target.yview_scroll
                scroll((1 if pixels > 0 else -1)*max(1,int(abs(pixels)/12)), 'units')
        else:
            bounds = target.bbox('all')
            if bounds:
                index = 0 if axis == 'x' else 1
                size = bounds[index+2] - bounds[index]
                view = target.xview if axis == 'x' else target.yview
                move = target.xview_moveto if axis == 'x' else target.yview_moveto
                if size > 0:
                    move(max(0, view()[0] + pixels / size))
        return 'break'

    def safe(self, action):
        try:
            action()
        except Exception as exc:
            self.notice('操作未完成', str(exc))

    def run_job(self, title, work, done, summary=None, retryable=False, next_action=None):
        if self.busy:
            raise ValueError('正在处理，请等待当前任务完成')
        self.busy = True
        messages = queue.Queue()
        cancelled = threading.Event()
        popup = tk.Toplevel(self.root)
        popup.title(title)
        self.center(popup, 580, 700)
        popup.transient(self.root)
        popup.grab_set()
        def cancel():
            cancelled.set()
            view.cancelling()
        from .progress import ProgressView
        view = ProgressView(popup, title, Path(__file__).parent/'assets'/'logo.png', cancel)
        view.animation_frozen = self.reduce_motion.get()
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
                for _ in range(100):
                    kind, value = messages.get_nowait()
                    if kind == 'progress':
                        stage, current, total = value
                        view.update(stage, current, total)
                    else:
                        def acknowledge(result=value, outcome=kind):
                            view.close()
                            popup.grab_release()
                            popup.destroy()
                            self.busy = False
                            if outcome == 'error':
                                self.status.set(str(result).splitlines()[0][:160] or '操作已停止')
                            else:
                                self.safe(lambda: done(result))
                        if kind == 'error':
                            description = str(value)
                        elif summary:
                            description = summary(value)
                        elif isinstance(value, tuple) and isinstance(value[0], dict) and 'questions' in value[0]:
                            project, pages = value
                            questions = project['questions']
                            assets = sum(len(q['assets']) for q in questions)
                            issues = sum(bool(q.get('issues')) for q in questions)
                            description = f'已分析 {len(pages)} 页，识别 {len(questions)} 题、{assets} 个截图区域。\n{issues} 题有检查提示。\n已处理题干、选项、答案匹配及截图边界；请进入主界面校对。'
                        else:
                            description = f'{title}已完成。'
                        def retry():
                            acknowledge()
                            self.run_job(title, work, done, summary, retryable=True, next_action=next_action)
                        view.finish(description, kind != 'error', acknowledge,
                                    retry=retry if kind == 'error' and retryable else None)
                        if kind == 'done' and next_action:
                            label, action = next_action
                            def proceed():
                                acknowledge()
                                self.safe(action)
                            view.add_action(label, proceed)
                        return
            except queue.Empty:
                pass
            self.root.after(80, poll)
        threading.Thread(target=worker, daemon=True).start()
        self.root.after(80, poll)

    def open_pdf(self, separate=False):
        path = filedialog.askopenfilename(parent=self.root, title='选择题目 PDF', filetypes=[('PDF 试卷', '*.pdf')])
        if not path:
            return
        answer_path = None
        if separate:
            answer_path = filedialog.askopenfilename(parent=self.root, title='选择对应的答案解析 PDF', filetypes=[('PDF 解析', '*.pdf')])
            if not answer_path:
                return
            if Path(path).resolve() == Path(answer_path).resolve():
                raise ValueError('题目卷和解析卷应选择不同文件；单文件请使用“打开 PDF”')
        def work(progress):
            pages = read_pages(path, progress)
            answers = read_pages(answer_path, progress) if answer_path else []
            project = detect(path, pages=pages, progress=progress, answer_source=answer_path, answer_pages=answers)
            return project, pages + answers
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
        questions = self.project['questions']
        checked = sum(q['reviewed'] for q in questions)
        self.paper_stats.set(f'{len(questions)} 题  ·  已校对 {checked}  ·  待校对 {len(questions)-checked}')
        name = Path(self.project['source']).stem
        self.root.title(f'{name} — {APP_NAME}')
        self.document_title.set(name if len(name)<=28 else name[:27]+'…')
        self.export_button.configure(state='normal')
        self.tree.delete(*self.tree.get_children())
        for qi, q in enumerate(self.project['questions']):
            parent = self.tree.insert('', 'end', iid=f'q{qi}', text=f"{'✓' if q['reviewed'] else ('⚠' if q.get('issues') else '○')} {q['id']} {q.get('subtype') or TYPE_NAMES.get(q.get('type'), '未分类')}", open=True)
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
        if asset and asset['regions']:
            self.reveal_region(asset['regions'][0])

    def reveal_region(self, region):
        self.canvas.update_idletasks()
        left, top, right, bottom = [v*self.scale for v in region['box']]
        top += self.page_offsets[region['page']]
        bottom += self.page_offsets[region['page']]
        _, asset = self.selected()
        if asset and len({r['page'] for r in asset['regions']}) > 1:
            last = asset['regions'][-1]
            bottom = self.page_offsets[last['page']] + last['box'][3]*self.scale
            if bottom-top > self.canvas.winfo_height()-48:
                # Show the page seam with original context on both sides.
                seam = self.page_offsets[region['page']] + self.pages[region['page']]['height']*self.scale
                top, bottom = seam-24, seam+24
        x,y = self.canvas.canvasx(0),self.canvas.canvasy(0)
        if left < x+12 or right > x+self.canvas.winfo_width()-12:
            self.canvas.xview_moveto(reveal_offset(left,right,self.canvas.winfo_width(),self.document_width))
        if top < y+12 or bottom > y+self.canvas.winfo_height()-12:
            self.canvas.yview_moveto(reveal_offset(top,bottom,self.canvas.winfo_height(),self.document_height))
        self.render_visible_pages()

    def document_scrolled(self, scrollbar, first, last):
        scrollbar.set(first,last)
        if self.project and getattr(self,'page_offsets',None) and not getattr(self,'document_render_pending',None):
            self.document_render_pending = self.root.after_idle(self.render_visible_pages)

    def show_page(self):
        if not self.project:
            return
        if getattr(self,'document_render_pending',None):
            self.root.after_cancel(self.document_render_pending)
            self.document_render_pending = None
        layout_key = (id(self.project), self.scale)
        if getattr(self, '_document_layout_key', None) == layout_key:
            self.render_visible_pages()
            return
        self._document_layout_key = layout_key
        self.canvas.delete('all')
        self.page_photos = {}
        self.page_offsets = []
        top = 0
        self.document_width = max(p['width'] for p in self.pages)*self.scale
        for index, page in enumerate(self.pages):
            self.page_offsets.append(top)
            height, width = page['height']*self.scale, page['width']*self.scale
            self.canvas.create_rectangle(0,top,width,top+height,fill='white',outline='',tags='paper')
            top += height+20
        self.document_height = top-20
        self.canvas.configure(scrollregion=(0,0,self.document_width,self.document_height))
        self.canvas.yview_moveto(self.page_offsets[self.page]/self.document_height)
        self.render_visible_pages()
        self.status.set('原 PDF 连续阅读 · 滚轮可跨页浏览；绿色框分别对应各页截图，可直接编辑')

    def render_visible_pages(self):
        pending = getattr(self,'document_render_pending',None)
        if pending:
            self.root.after_cancel(pending)
        self.document_render_pending = None
        if not self.project or not getattr(self,'page_offsets',None):
            return
        top = self.canvas.canvasy(0)
        bottom = top+self.canvas.winfo_height()
        visible = [i for i,y in enumerate(self.page_offsets)
                   if y <= bottom and y+self.pages[i]['height']*self.scale >= top]
        if not visible:
            return
        asset = self.selected()[1] if self.tree.selection() else None
        needed = set(visible)
        for index in list(self.page_photos):
            if index not in needed:
                self.canvas.delete(f'page-{index}')
                del self.page_photos[index]
        self.canvas.delete('selection-overlay')
        for index in visible:
            offset = self.page_offsets[index]
            regions = [r for r in asset['regions'] if r['page']==index] if asset else []
            tag = f'page-{index}'
            if index not in self.page_photos:
                image = render_page(self.project,index,self.scale)
                photo = ImageTk.PhotoImage(image)
                self.page_photos[index] = photo
                self.canvas.create_image(0,offset,anchor='nw',image=photo,tags=tag)
            tag = 'selection-overlay'
            for r in regions:
                l,t,rr,b = [v*self.scale for v in r['box']]
                self.canvas.create_rectangle(l,t+offset,rr,b+offset,outline='#16856b',width=2,tags=tag)
                for mask in r['masks']:
                    l,t = math.ceil(mask[0]*self.scale),math.ceil(mask[1]*self.scale)
                    rr,b = math.floor(mask[2]*self.scale)-1,math.floor(mask[3]*self.scale)-1
                    if rr-l >= 1 and b-t >= 1:
                        self.canvas.create_rectangle(l+.5,t+.5+offset,rr-.5,b-.5+offset,
                                                     outline='#d74b55',fill='white',width=1,tags=tag)
        self.photo = self.page_photos[visible[0]]
        if not getattr(self,'origin',None):
            self.page = visible[0]
        numbers = '–'.join(str(i+1) for i in (visible[0],visible[-1])) if len(visible)>1 else str(visible[0]+1)
        self.page_label.set(f'第 {numbers} / {len(self.pages)} 页 · {self.scale:.0%}')

    def change_edit_mode(self):
        self.origin = None
        self.canvas.delete('drag')

    def turn(self, delta):
        if self.project:
            self.page = max(0,min(len(self.pages)-1,self.page+delta))
            self.canvas.yview_moveto(self.page_offsets[self.page]/self.document_height)
            self.render_visible_pages()

    def start_drag(self, event):
        self.origin = None
        if self.mode.get() == 'browse' or not self.project:
            return
        x,y = self.canvas.canvasx(event.x),self.canvas.canvasy(event.y)
        for index,offset in enumerate(self.page_offsets):
            page = self.pages[index]
            if offset <= y < offset+page['height']*self.scale and 0 <= x < page['width']*self.scale:
                self.page = self.drag_page = index
                self.origin = (x,y)
                break

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
        self.page = self.drag_page
        offset = self.page_offsets[self.page]
        y, ey = y-offset, ey-offset
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
        position = self.canvas.yview()[0]
        self.show_page()
        self.canvas.yview_moveto(position)
        self.render_visible_pages()

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
        kind = next((key for key,label in ASSET_NAMES.items() if label==self.kind.get()), self.kind.get())
        q['assets'].append({'kind': kind, 'regions': []})
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
        combined = render_asset(self.project, asset)
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
        self.bind_scroll(canvas, scroll)
        popup.grab_set()

    def save(self):
        if not self.project:
            return
        path = filedialog.asksaveasfilename(parent=self.root, defaultextension='.json', filetypes=[('拆题工程', '*.json')])
        if path:
            Path(path).write_text(json.dumps(self.project, ensure_ascii=False, indent=2), encoding='utf-8')
            self.status.set(f'工程已保存 · {Path(path).name}')

    def load(self):
        path = filedialog.askopenfilename(parent=self.root, filetypes=[('拆题工程', '*.json')])
        if path:
            project = json.loads(Path(path).read_text(encoding='utf-8'))
            for key, label in [('source', '题目'), ('answer_source', '答案解析')]:
                if key in project and not Path(project[key]).is_file():
                    source = filedialog.askopenfilename(parent=self.root, title=f'请重新选择工程对应的{label} PDF', filetypes=[('PDF', '*.pdf')])
                    if not source:
                        return
                    project[key] = source
            def work(progress):
                pages = read_pages(project['source'], progress)
                if project.get('answer_source'):
                    if len(pages) != project['question_page_count']:
                        raise ValueError('题目卷页数与工程不符，请重新选择原文件或重新导入')
                    pages += read_pages(project['answer_source'], progress)
                repair_prefix_masks(project, pages)
                tighten_regions(project, progress)
                return pages
            def done(pages):
                self.undo_stack.clear()
                self.redo_stack.clear()
                self.last_export = None
                self.project, self.pages, self.page = project, pages, 0
                self.refresh()
                self.show_page()
            self.run_job('载入工程', work, done,
                         summary=lambda pages: f'已载入 {len(pages)} 页、{len(project["questions"])} 题。\n已检查原文件并更新自动截图框和标号遮罩。')

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
            self.status.set(f'已导出 {len(rows)} 题：{output}')
        self.run_job('导出截图', lambda progress: export(snapshot, output, progress=progress), done,
                     summary=lambda rows: f'已导出 {len(rows)} 题、{sum(len(r["images"]) for r in rows)} 张图片。\n保存位置：{output}\n包含工程、图片和上传清单。', next_action=('上传到小鹅通', self.upload))

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
        popup.title('上传到小鹅通')
        self.center(popup, 680, 580)
        popup.configure(background='white')
        popup.grab_set()
        saved = sum(q['status'] == 'saved' for q in report['questions'])
        pending = sum(q['status'] not in ('saved','blocked') for q in report['questions'])
        missing_images = sum(i['status'] != 'uploaded' for i in report['images'])
        shell = ttk.Frame(popup,padding=24)
        shell.pack(fill='both',expand=True)
        ttk.Label(shell,text='上传到小鹅通',style='Title.TLabel').pack(anchor='w')
        ttk.Label(shell,text=f'{len(report["questions"])} 道题目 · {report["image_count"]} 张截图',
                  style='Muted.TLabel').pack(anchor='w',pady=(6,16))
        ttk.Label(shell,text=f'已保存 {saved}  ·  待处理 {pending}  ·  需补全 {report["unresolved_questions"]}',
                  style='Badge.TLabel').pack(fill='x',pady=(0,20))
        ttk.Label(shell,text='上传到题库分类',style='Section.TLabel').pack(anchor='w')
        category = tk.StringVar(value=report.get('material_group', ''))
        ttk.Entry(shell,textvariable=category,state='readonly').pack(fill='x',pady=(8,6))
        ttk.Label(shell,text='图片存入同名素材分组，已确认保存的内容会自动跳过。',
                  style='Muted.TLabel').pack(anchor='w')
        ttk.Separator(shell).pack(fill='x',pady=20)
        ttk.Label(shell,text='本次上传',style='Section.TLabel').pack(anchor='w',pady=(0,8))
        upload_mode = tk.StringVar(value='all' if pending else 'images')
        for label,value in [('继续上传全部待处理题目','all'),('先试传一道题目','one'),('仅上传图片素材','images')]:
            ttk.Radiobutton(shell,text=label,value=value,variable=upload_mode,
                            state='disabled' if value!='images' and not pending else 'normal').pack(anchor='w',pady=4)
        blocked = '\n'.join(f'{q["id"]}：{q["reason"]}' for q in report['questions'] if q['status']=='blocked')
        def show_blocked():
            self.notice('需要补全的题目', blocked or '没有待补全题目')
            popup.grab_set()
        ttk.Button(shell,text='查看待补全题目',style='Quiet.TButton',command=show_blocked).pack(anchor='w',pady=(8,0))
        def start(limit, materials_only=False):
            destination = category.get().strip()
            if not destination and not materials_only:
                return
            popup.destroy()
            batch = self.last_export
            def done(state):
                count = sum(q['status']=='saved' for q in state['questions'])
                uploaded = sum(i['status']=='uploaded' for i in state['images'])
                self.status.set(f'已上传 {uploaded} 张图；累计保存 {count} 题。')
            self.run_job('小鹅通上传', lambda progress: execute(batch, destination, XiaoeBrowser(), progress, limit, materials_only), done,
                         summary=lambda state: f'已确认上传 {sum(i["status"]=="uploaded" for i in state["images"])}/{len(state["images"])} 张图；累计保存 {sum(q["status"]=="saved" for q in state["questions"])}/{len(state["questions"])} 题。\n'
                         f'待补全 {state["unresolved_questions"]} 题。\n素材分组：{state.get("material_group", "")}\n上传进度已保存在本机。', retryable=True)
        buttons = ttk.Frame(shell)
        buttons.pack(side='bottom',fill='x',pady=(16,0))
        def start_selected():
            mode = upload_mode.get()
            start(1 if mode=='one' else None, mode=='images')
        complete = not pending and not missing_images
        ttk.Button(buttons,text='全部已上传' if complete else '开始上传',style='Primary.TButton',
                   command=start_selected,state='disabled' if complete else 'normal').pack(side='right')
        ttk.Button(buttons,text='取消',style='Quiet.TButton',command=popup.destroy).pack(side='right',padx=12)
        popup.bind('<Escape>',lambda event:popup.destroy())

    def center(self, window, width, height):
        window.title(f'{window.title()} — {APP_NAME}')
        self.root.update_idletasks()
        x = self.root.winfo_rootx() + (self.root.winfo_width()-width)//2
        y = self.root.winfo_rooty() + (self.root.winfo_height()-height)//2
        window.geometry(f'{width}x{height}+{max(0,x)}+{max(0,y)}')
        window.transient(self.root)

    def notice(self, title, text):
        popup = tk.Toplevel(self.root)
        popup.title(title)
        self.center(popup, 560, 350)
        footer=ttk.Frame(popup,padding=(20,12))
        footer.pack(side='bottom',fill='x')
        ttk.Button(footer,text='确定',style='Primary.TButton',width=18,command=popup.destroy).pack()
        ttk.Label(popup,text=title,style='Section.TLabel',padding=(24,20,24,8)).pack(anchor='w')
        content=ttk.Frame(popup,padding=(24,4,24,12))
        content.pack(fill='both',expand=True)
        details=tk.Text(content,wrap='word',relief='flat',background='white',foreground='#475569',height=5)
        scrollbar=ttk.Scrollbar(content,command=details.yview)
        self.bind_scroll(details, scrollbar)
        details.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y')
        details.pack(fill='both',expand=True)
        details.insert('1.0',text)
        details.configure(state='disabled')
        popup.grab_set()
        popup.bind('<Return>', lambda e: popup.destroy())
        popup.bind('<Escape>', lambda e: popup.destroy())
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
        return self.scroll_content(self.canvas, event)


def main():
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == '__main__':
    main()
