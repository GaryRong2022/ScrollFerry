"""PyInstaller entry point (absolute import also works when frozen)."""
import json
import sys
from pathlib import Path

from scrollferry.app import main

if __name__ == '__main__':
    if '--smoke-test' in sys.argv:
        import tkinter as tk
        import pypdfium2 as pdfium
        from playwright.sync_api import sync_playwright
        from scrollferry.app import App
        from scrollferry.paths import user_data_dir
        receipt = Path(sys.argv[sys.argv.index('--smoke-test') + 1])
        root = tk.Tk()
        root.withdraw()
        app = App(root)
        root.update()
        assert app.logo_icon.width() == 256
        root.destroy()
        document = pdfium.PdfDocument.new()
        document.close()
        with sync_playwright() as runtime:
            browser = runtime.chromium.launch(channel='msedge', headless=True)
            page = browser.new_page()
            page.set_content('<title>ScrollFerry build test</title>')
            assert page.title() == 'ScrollFerry build test'
            browser.close()
        receipt.write_text(json.dumps({'ok': True, 'data_dir': str(user_data_dir())}), encoding='utf-8')
    else:
        main()
