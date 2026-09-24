"""Shared light desktop theme with clear hierarchy and generous hit targets."""
import sys
from tkinter import ttk

BG = '#f4f5f8'
SURFACE = '#ffffff'
TEXT = '#202631'
MUTED = '#64748b'
BLUE = '#246bfd'


def apply_theme(root):
    root.configure(background=BG)
    family = 'SF Pro Text' if sys.platform=='darwin' else 'Segoe UI'
    root.option_add('*Font', (family, 11))
    root.option_add('*TCombobox*Listbox.font', (family, 11))
    root.option_add('*TCombobox*Listbox.background', SURFACE)
    style = ttk.Style(root)
    style.theme_use('clam')
    style.configure('.', font=(family,11), background=SURFACE, foreground=TEXT)
    style.configure('TFrame',background=SURFACE)
    style.configure('App.TFrame',background=BG)
    style.configure('TLabel',background=SURFACE,foreground=TEXT)
    style.configure('Title.TLabel',font=(family,16,'bold'))
    style.configure('Section.TLabel',font=(family,12,'bold'))
    style.configure('Muted.TLabel',foreground=MUTED,font=(family,10))
    style.configure('Status.TLabel',background=BG,foreground=MUTED,font=(family,10),padding=(18,8))
    style.configure('Badge.TLabel',background='#eaf3ff',foreground='#1762c4',padding=(10,5),font=(family,10))
    style.configure('TButton',padding=(12,9),background='#edf2f8',foreground=TEXT,
                    borderwidth=0,relief='flat',focusthickness=2,focuscolor='#94bfff')
    style.map('TButton',background=[('pressed','#dbe7f5'),('active','#e3ecf8')],
              foreground=[('disabled','#9ba9bb')])
    style.configure('Primary.TButton',background=BLUE,foreground='white',font=(family,11,'bold'))
    style.map('Primary.TButton',background=[('disabled','#c6daf4'),('pressed','#005ed9'),('active','#086bea')],
              foreground=[('disabled','#f5f9ff'),('!disabled','white')])
    style.configure('Quiet.TButton',background=SURFACE,foreground=MUTED)
    style.map('Quiet.TButton',background=[('active','#f0f5fc')])
    style.configure('Danger.TButton',foreground='#c55260',background='#fff2f3')
    style.configure('TEntry',fieldbackground='#f7f9fd',bordercolor='#dce5f0',padding=8,insertcolor=TEXT)
    style.map('TEntry',bordercolor=[('focus',BLUE)])
    style.configure('TCombobox',fieldbackground='#f7f9fd',background='#edf2f8',bordercolor='#dce5f0',padding=7,arrowsize=13)
    style.map('TCombobox',fieldbackground=[('readonly','#f7f9fd')],foreground=[('readonly',TEXT)],bordercolor=[('focus',BLUE)])
    style.configure('TCheckbutton',background=SURFACE,padding=(0,8))
    style.map('TCheckbutton',background=[('active',SURFACE)])
    style.configure('Tool.TRadiobutton',indicatoron=False,padding=(12,9),background='#f0f4fa',
                    relief='flat',borderwidth=0,focusthickness=2,focuscolor='#8bbaff')
    style.layout('Tool.TRadiobutton', [
        ('Radiobutton.padding', {'sticky': 'nswe', 'children': [
            ('Radiobutton.focus', {'sticky': 'nswe', 'children': [
                ('Radiobutton.label', {'sticky': 'nswe'})]})]})])
    style.map('Tool.TRadiobutton',background=[('selected','#dfedff'),('active','#eaf2fe')],
              foreground=[('selected','#0965d8')])
    style.configure('Treeview',background=SURFACE,fieldbackground=SURFACE,rowheight=30,
                    borderwidth=0,font=(family,11),indent=18)
    style.map('Treeview',background=[('selected','#dfedff')],foreground=[('selected','#075cca')])
    style.configure('Vertical.TScrollbar',background='#c2cede',troughcolor='#f4f7fb',borderwidth=0,arrowsize=11)
    style.configure('Horizontal.TScrollbar',background='#c2cede',troughcolor='#f4f7fb',borderwidth=0,arrowsize=11)
    style.configure('TProgressbar',background=BLUE,troughcolor='#e7effa',borderwidth=0,thickness=6)
    style.configure('TPanedwindow',background=BG,sashwidth=10)
    # Nine-slice images keep rounded corners crisp at any button width.
    # Keep PhotoImage handles on the root for the lifetime of the theme.
    from PIL import Image, ImageDraw, ImageTk
    root._theme_images = []
    def rounded(color, outline=None):
        image = Image.new('RGB', (96, 96), SURFACE)
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((2, 2, 93, 93), radius=22, fill=color,
                               outline=outline or color, width=3)
        photo = ImageTk.PhotoImage(image.resize((32,32), Image.Resampling.LANCZOS), master=root)
        root._theme_images.append(photo)
        return photo
    for name, colors in {
        'TButton': ('#f0f2f6','#e7ebf2','#dce3ed','#f6f7f9'),
        'Primary.TButton': (BLUE,'#195ce7','#144dcb','#cbd8f4'),
        'Quiet.TButton': (SURFACE,'#f0f2f6','#e7ebf2',SURFACE),
        'Danger.TButton': (SURFACE,'#fff0f1','#ffe1e4',SURFACE),
    }.items():
        normal, hover, pressed, disabled = [rounded(c) for c in colors]
        focus = rounded(colors[0], '#8db5ff')
        element = name + '.rounded'
        style.element_create(element, 'image', normal, ('disabled',disabled),
                             ('pressed',pressed), ('focus',focus), ('active',hover),
                             border=9, sticky='nsew')
        style.layout(name, [(element, {'sticky':'nsew','children':[
            ('Button.padding', {'sticky':'nsew','children':[
                ('Button.label', {'sticky':'nsew'})]})]})])
    style.layout('TMenubutton', style.layout('TButton'))
    style.configure('TMenubutton', padding=(12,9), background=SURFACE, foreground=TEXT)
    style.configure('Canvas.TFrame', background=SURFACE)
    style.configure('Canvas.TLabel', background=SURFACE, foreground=TEXT)
    style.configure('Welcome.TLabel', background=SURFACE, foreground=TEXT, font=(family,22,'bold'))
    style.configure('WelcomeHint.TLabel', background=SURFACE, foreground=MUTED, font=(family,12))
    return style
