"""Prefer the Windows HTTPS default when supported, then try Chrome / Edge."""
import sys


def default_channel():
    if sys.platform != 'win32':
        return None
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                r'Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice') as key:
            progid = winreg.QueryValueEx(key, 'ProgId')[0].lower()
        if progid.startswith('chromehtml'):
            return 'chrome'
        if progid.startswith('msedgehtm'):
            return 'msedge'
    except OSError:
        pass
    return None


def browser_channels():
    preferred = default_channel()
    return list(dict.fromkeys(c for c in (preferred, 'chrome', 'msedge') if c))
