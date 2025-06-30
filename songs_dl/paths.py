import os
import sys
from pathlib import Path

def get_app_data_path():
    if sys.platform == "win32":
        # For Windows, the app data path is usually in the user's profile
        return Path(os.environ['APPDATA'])
    elif sys.platform == "darwin":
        # For macOS, the app data path is usually in the user's Library folder
        return Path.home() / 'Library' / 'Application Support'
    else:
        # For Linux, the app data path is usually in the user's home directory
        return Path.home() / '.local' / 'share'
