"""Writable runtime files are independent of the installation directory."""
import hashlib
import os
import sys
from pathlib import Path


def user_data_dir():
    override = os.environ.get('SCROLLFERRY_DATA_DIR')
    if override:
        root = Path(override).expanduser().resolve()
    elif sys.platform == 'win32':
        root = Path(os.environ.get('LOCALAPPDATA', str(Path.home()/'AppData'/'Local')))/'ScrollFerry'
    elif sys.platform == 'darwin':
        root = Path.home()/'Library'/'Application Support'/'ScrollFerry'
    else:
        root = Path(os.environ.get('XDG_DATA_HOME', str(Path.home()/'.local'/'share')))/'ScrollFerry'
    root.mkdir(parents=True, exist_ok=True)
    return root


def batch_runtime_dir(batch):
    key = hashlib.sha256(str(Path(batch).resolve()).encode('utf-8')).hexdigest()
    directory = user_data_dir()/'batches'/key
    directory.mkdir(parents=True, exist_ok=True)
    return directory
