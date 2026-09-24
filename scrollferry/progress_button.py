"""Rounded, keyboard-accessible primary action with consistent macOS color."""
import tkinter as tk
import sys
from tkinter import ttk
from PIL import Image, ImageDraw, ImageTk


class ProgressButton(tk.Canvas):
    def __init__(self, parent, text, command):
        super().__init__(parent, width=208, height=48, highlightthickness=0,
                         background='#f5f5f7', takefocus=True, cursor='hand2')
        self.caption, self.command = text, command
        self.enabled, self.primary, self.hovered = True, False, False
        self.bind('<Enter>', lambda e: self.hover(True))
        self.bind('<Leave>', lambda e: self.hover(False))
        self.bind('<ButtonPress-1>', lambda e: self.focus_set())
        self.bind('<ButtonRelease-1>', self.activate)
        self.bind('<Return>', self.activate)
        self.bind('<space>', self.activate)
        self.bind('<FocusIn>', lambda e: self.paint())
        self.bind('<FocusOut>', lambda e: self.paint())
        self.paint()

    def hover(self, value):
        self.hovered = value
        self.paint()

    def activate(self, event):
        if getattr(event, 'num', None)==1 and not (0<=event.x<208 and 0<=event.y<48):
            return 'break'
        if self.enabled:
            self.command()
        return 'break'

    def set_primary(self):
        self.primary = True
        self.paint()

    def configure(self, cnf=None, **kwargs):
        if 'text' in kwargs: self.caption = kwargs.pop('text')
        if 'command' in kwargs: self.command = kwargs.pop('command')
        if 'state' in kwargs: self.enabled = kwargs.pop('state') != 'disabled'
        if cnf or kwargs:
            super().configure(cnf, **kwargs)
        self.paint()

    def paint(self):
        surface = Image.new('RGB',(416,96),'#f5f5f7')
        d = ImageDraw.Draw(surface)
        if self.focus_get() == self:
            d.rounded_rectangle((1,1,414,94),radius=26,outline='#99c6ff',width=4)
        color = ('#0071e3' if self.hovered else '#007aff') if self.primary else ('#e3e4e8' if self.hovered else '#e9e9ed')
        if not self.enabled: color='#ededf0'
        d.rounded_rectangle((8,8,408,88),radius=20,fill=color)
        self.photo = ImageTk.PhotoImage(surface.resize((208,48),Image.Resampling.LANCZOS))
        self.delete('all')
        self.create_image(0,0,anchor='nw',image=self.photo)
        self.create_text(104,24,text=self.caption,font=('TkDefaultFont',13,'bold'),
                         fill='#ffffff' if self.primary and self.enabled else '#6e6e73')


if sys.platform == 'darwin':
    class ProgressButton(ttk.Button):
        """Expose a real system button to keyboard and accessibility services."""
        def __init__(self, parent, text, command):
            super().__init__(parent, text=text, command=command, width=22,
                             padding=(16,10), takefocus=True)

        def set_primary(self):
            self.configure(style='Primary.TButton', default='active')
