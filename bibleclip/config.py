"""Configuration: version, platform flags, fonts, paths, GitHub URLs."""
import os
import sys

from bibleclip._version import __version__

IS_WINDOWS = sys.platform.startswith('win')

# Single app-wide font: each OS's default Korean Gothic (always pre-installed),
# used uniformly for UI, scripture body, and the log.
if sys.platform == 'darwin':
    APP_FONT = 'Apple SD Gothic Neo'
elif IS_WINDOWS:
    APP_FONT = 'Malgun Gothic'
else:  # Linux / other
    APP_FONT = 'Noto Sans CJK KR'
UI_FONT = BODY_FONT = MONO_FONT = APP_FONT

# Serif font for scripture body (editorial "book" feel); each is OS-default.
if sys.platform == 'darwin':
    SERIF_FONT = 'AppleMyungjo'
elif IS_WINDOWS:
    SERIF_FONT = '바탕'
else:
    SERIF_FONT = 'Noto Serif CJK KR'

GITHUB_OWNER = "tpwns432-maker"
GITHUB_REPO = "AutoBible"
UPDATE_CHECK_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"

def get_base_dir():
    """Get the base directory - works for both script and PyInstaller bundle.

    On Windows the data folders sit next to BibleClip.exe. On a macOS .app
    bundle, sys.executable lives in BibleClip.app/Contents/MacOS/, so walk up
    out of the bundle to look for the data folders next to BibleClip.app.
    """
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        if sys.platform == 'darwin' and exe_dir.endswith(os.path.join('Contents', 'MacOS')):
            # exe_dir = /path/BibleClip.app/Contents/MacOS -> /path
            return os.path.dirname(os.path.dirname(os.path.dirname(exe_dir)))
        return exe_dir
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def get_resource_dir():
    """Get bundled resource directory (for --add-data assets inside exe)."""
    if getattr(sys, 'frozen', False):
        return sys._MEIPASS
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def system_env():
    """Environment for running SYSTEM binaries (e.g. pbpaste) from a frozen app.

    PyInstaller injects DYLD_/LD_LIBRARY_PATH pointing at the bundle's libs,
    which can break system executables. Restore the original values (saved by
    the bootloader with a _ORIG suffix) so the child runs in a clean env.
    """
    env = dict(os.environ)
    for var in ('DYLD_LIBRARY_PATH', 'DYLD_FRAMEWORK_PATH', 'LD_LIBRARY_PATH'):
        orig = env.pop(var + '_ORIG', None)
        if orig:
            env[var] = orig
        else:
            env.pop(var, None)
    # A .app launched from Finder has no LANG, so pbpaste emits '?' for Korean.
    # Force a UTF-8 locale so non-ASCII text round-trips correctly.
    env['LANG'] = 'en_US.UTF-8'
    env['LC_ALL'] = 'en_US.UTF-8'
    return env

BASE_DIR = get_base_dir()
SETTINGS_FILE = "bibleclip_settings.json"
# Pre-1.6 settings filename. Read once (and only as a fallback) so existing
# users keep their version order, last position, theme, window size, etc.
LEGACY_SETTINGS_FILE = "autobible_settings.json"
BIBLE_DIR = "bible_versions"


def candidate_data_roots():
    """Folders to search for data (bible_versions, original_lang), in order.

    BASE_DIR first (next to the exe / .app — lets users drop in extra data).
    On a frozen build also the executable's own dir: inside a macOS .app this
    is Contents/MacOS, where bundled data lives so it survives App
    Translocation and the app being moved.
    """
    roots = [BASE_DIR]
    if getattr(sys, 'frozen', False):
        exe_dir = os.path.dirname(sys.executable)
        if exe_dir not in roots:
            roots.append(exe_dir)
        try:
            mei = sys._MEIPASS
            if mei not in roots:
                roots.append(mei)
        except Exception:
            pass
    return roots


def resolve_data_dir(name):
    """First existing candidate root containing `name`, else BASE_DIR/name."""
    for root in candidate_data_roots():
        p = os.path.join(root, name)
        if os.path.isdir(p):
            return p
    return os.path.join(BASE_DIR, name)
