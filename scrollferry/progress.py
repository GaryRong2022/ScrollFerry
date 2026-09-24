"""Tk-only progress display; animation indicates activity, never completion."""
import time
import tkinter as tk
from tkinter import ttk
from PIL import Image, ImageTk


class ProgressView:
    def __init__(self, window, title, logo_path, cancel):
        self.window = window
        self.started = self.changed = time.monotonic()
        self.last_stage = ''
        self.cancelled = False
        self.timer = None
        self.waiting = True
        self.scene_elapsed = 0
        self.animation_frozen = False
        shell = tk.Frame(window, background='#f5f5f7', padx=28, pady=20)
        shell.pack(fill='both', expand=True)
        self.sea = tk.Canvas(shell, width=300, height=138, background='#f5f5f7', highlightthickness=0)
        self.sea.pack(fill='x', pady=(0,12))
        self.scene = self.sea.create_image(0, 0, anchor='nw')
        with Image.open(logo_path) as logo:
            from .ferry_animation import prepare_ferry_logo
            self.logo_source = prepare_ferry_logo(logo)
        tk.Label(shell, text=title, font=('TkDefaultFont',17,'bold'),
                 background='#f5f5f7', foreground='#1d1d1f').pack(pady=(2,12))
        self.stage = tk.StringVar(value='正在准备…')
        tk.Label(shell, textvariable=self.stage, wraplength=510, background='#f5f5f7', foreground='#515156', justify='center').pack(fill='x')
        self.count = tk.StringVar(value='等待开始')
        tk.Label(shell, textvariable=self.count, wraplength=510, background='#f5f5f7', foreground='#1d1d1f').pack(pady=(14,6))
        self.bar = ttk.Progressbar(shell, maximum=100, mode='indeterminate')
        self.bar.pack(fill='x')
        self.bar.start(35)
        self.clock = tk.StringVar()
        tk.Label(shell, textvariable=self.clock, foreground='#86868b', background='#f5f5f7').pack(pady=(8,6))
        self.hint = tk.StringVar(value='处理期间可使用其他应用。动画表示界面仍在响应，不代表任务已完成。')
        tk.Label(shell, textvariable=self.hint, wraplength=510, foreground='#6e6e73', background='#f5f5f7').pack(fill='x', pady=(0,14))
        from .progress_button import ProgressButton
        self.actions = ttk.Frame(shell)
        self.actions.pack(side='bottom',anchor='center',pady=(18,2))
        self.cancel_button = ProgressButton(self.actions, text='取消任务', command=cancel)
        self.cancel_button.pack(side='left')
        log_frame = ttk.Frame(shell)
        log_frame.pack(fill='both', expand=True)
        self.log = tk.Text(log_frame, height=5, wrap='word', state='disabled', relief='flat', background='#ffffff', foreground='#515156', padx=12, pady=10)
        scroll = ttk.Scrollbar(log_frame, command=self.log.yview)
        scroll._scroll_target = (self.log, 'y')
        self.log.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.log.pack(fill='both', expand=True)
        self.tick()

    def update(self, stage, current, total):
        if self.cancelled:
            return
        stage = str(stage)
        if stage != self.last_stage:
            self.changed = time.monotonic()
            self.last_stage = stage
            self.log.configure(state='normal')
            self.log.insert('end', time.strftime('%H:%M:%S')+'  '+stage+'\n')
            if int(self.log.index('end-1c').split('.')[0]) > 100:
                self.log.delete('1.0','2.0')
            self.log.see('end')
            self.log.configure(state='disabled')
        self.stage.set(stage)
        waiting = total <= 0
        if waiting != self.waiting:
            self.bar.stop()
            self.bar.configure(mode='indeterminate' if waiting else 'determinate')
            if waiting:
                self.bar.start(35)
            self.waiting = waiting
        if waiting:
            self.count.set('当前步骤正在等待响应 · 暂无可核实的百分比')
        else:
            current = max(0, min(current, total))
            self.bar['value'] = current / total * 100
            self.count.set(f'当前阶段：{current} / {total}（{current / total:.0%}）')
        self.hint.set('请在浏览器完成登录，登录后会自动继续。' if '登录' in stage else
                      '正在等待后台响应；请勿重复提交，已有进度会保留。' if waiting else
                      '这是当前阶段的进度；进入下一阶段时会重新计数。')

    def cancelling(self):
        self.cancelled = True
        self.animation_frozen = True
        self.stage.set('正在取消，等待当前操作结束…')
        self.hint.set('已发出取消请求；当前浏览器操作可能需要一些时间才能返回。')
        self.cancel_button.configure(state='disabled')

    def tick(self):
        elapsed = time.monotonic()-self.started
        quiet = time.monotonic()-self.changed
        self.clock.set(f'已用时 {int(elapsed)//60:02d}:{int(elapsed)%60:02d} · 当前步骤 {int(quiet)} 秒')
        if quiet >= 20 and not self.cancelled and '登录' not in self.last_stage:
            self.hint.set('当前步骤暂未返回新进度，仍在等待。若超时会提示具体原因；也可以取消。')
        if not self.animation_frozen:
            self.draw_scene(elapsed)
        self.timer = self.window.after(40, self.tick)

    def draw_scene(self, elapsed, arrived=False):
        self.scene_elapsed = elapsed
        from .ferry_animation import ferry_frame
        width = max(300,self.sea.winfo_width())
        frame = ferry_frame(elapsed * 17.5, arrived, round(width*240/138), self.logo_source)
        frame = frame.resize((width,138), Image.Resampling.LANCZOS).convert('RGB')
        photo = getattr(self, 'scene_photo', None)
        if photo is not None and (photo.width(), photo.height()) == frame.size:
            # Keep the Tk image alive. Deleting/replacing its handle every
            # frame can briefly blank the canvas between two redraws.
            photo.paste(frame)
        else:
            replacement = ImageTk.PhotoImage(frame)
            self.sea.itemconfigure(self.scene, image=replacement)
            self.scene_photo = replacement

    def finish(self, summary, success, acknowledge, retry=None):
        self.close()
        elapsed = time.monotonic()-self.started
        self.stage.set('处理完成' if success else '处理已停止')
        self.count.set(summary.split('\n')[0])
        self.bar.configure(mode='determinate')
        if success:
            self.bar['value'] = 100
        self.clock.set(f'总用时 {int(elapsed)//60:02d}:{int(elapsed)%60:02d}')
        self.hint.set('结果和记录已保留，点击“确定”后关闭。')
        self.log.configure(state='normal')
        self.log.insert('end', '\n── 处理结果 ──\n'+summary+'\n')
        self.log.see('end')
        self.log.configure(state='disabled')
        self.animation_frozen = True
        self.draw_scene(getattr(self, 'scene_elapsed', 0), arrived=success)
        self.cancel_button.set_primary()
        self.cancel_button.configure(text='确定', state='normal', command=acknowledge)
        self.cancel_button.focus_set()
        self.window.protocol('WM_DELETE_WINDOW', acknowledge)
        self.window.bind('<Return>', lambda event: acknowledge())
        if retry is not None:
            self.hint.set('已保存的进度会保留。点击“重试”将重新连接并继续；未确认的提交会先停止核对。')
            self.cancel_button.configure(text='关闭')
            if isinstance(self.cancel_button,ttk.Button):
                self.cancel_button.configure(default='normal',style='TButton')
            else:
                self.cancel_button.primary = False
                self.cancel_button.paint()
            self.retry_button = ttk.Button(self.actions,text='重试',style='Primary.TButton',
                                          command=retry,width=16,default='active')
            self.retry_button.pack(side='left',padx=(12,0))
            self.retry_button.focus_set()
            self.window.bind('<Return>',lambda event:retry())

    def add_action(self, text, command):
        button = ttk.Button(self.actions,text=text,style='Primary.TButton',command=command)
        button.pack(side='left',padx=(12,0))

    def close(self):
        if self.timer is not None:
            self.window.after_cancel(self.timer)
            self.timer = None
        self.bar.stop()
