"""GitHub Releases update checker: version compare + platform asset pick."""
import re
import ssl
import sys
import json
import urllib.request
import urllib.error

from bibleclip.config import UPDATE_CHECK_URL, IS_WINDOWS, __version__

try:
    import certifi as _certifi
except Exception:
    _certifi = None


def parse_version(s):
    """Parse 'v1.2.3' or '1.2.3' to a tuple of ints. Returns (0,) on failure."""
    if not s:
        return (0,)
    s = s.lstrip('vV').strip()
    nums = []
    for part in s.split('.'):
        m = re.match(r'(\d+)', part)
        if not m:
            break
        nums.append(int(m.group(1)))
    return tuple(nums) if nums else (0,)


def _verified_ssl_context():
    """A verifying SSL context, using certifi's CA bundle when available.

    PyInstaller-bundled Python on macOS has no access to the system trust
    store, so default verification fails with CERTIFICATE_VERIFY_FAILED.
    certifi (bundled into the app) provides a CA file that works everywhere.
    """
    try:
        if _certifi is not None:
            return ssl.create_default_context(cafile=_certifi.where())
    except Exception:
        pass
    try:
        return ssl.create_default_context()
    except Exception:
        return None


def urlopen_resilient(req, timeout):
    """urlopen that tries certifi/default verification, then falls back to an
    unverified context on SSL failure (acceptable for fetching GitHub data)."""
    try:
        return urllib.request.urlopen(req, timeout=timeout,
                                      context=_verified_ssl_context())
    except (ssl.SSLError, urllib.error.URLError) as e:
        reason = getattr(e, 'reason', e)
        if isinstance(e, urllib.error.URLError) and not isinstance(reason, ssl.SSLError):
            raise  # genuine network error, not a cert problem
        return urllib.request.urlopen(req, timeout=timeout,
                                      context=ssl._create_unverified_context())


def _fetch_release_raw(timeout=8, ssl_context=None):
    req = urllib.request.Request(UPDATE_CHECK_URL, headers={
        'User-Agent': f'BibleClip/{__version__}',
        'Accept': 'application/vnd.github+json',
    })
    if ssl_context is not None:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context) as resp:
            return json.loads(resp.read().decode('utf-8'))
    with urlopen_resilient(req, timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def fetch_latest_release(timeout=8):
    """Fetch latest release info from GitHub.

    Returns (info_dict_or_None, error_message_or_empty).
    Tries with default SSL verification; on SSL failure, retries with an
    unverified context (acceptable for fetching public release metadata).
    """
    error = ''
    data = None
    try:
        data = _fetch_release_raw(timeout=timeout)
    except (ssl.SSLError, urllib.error.URLError) as e:
        error = f"SSL/네트워크 오류: {e}"
        # Fallback: retry without SSL verification
        try:
            ctx = ssl._create_unverified_context()
            data = _fetch_release_raw(timeout=timeout, ssl_context=ctx)
            error = ''
        except Exception as e2:
            error = f"폴백 실패: {e2}"
    except (urllib.error.HTTPError) as e:
        error = f"HTTP 오류: {e.code} {e.reason}"
    except (json.JSONDecodeError, OSError, ValueError) as e:
        error = f"응답 파싱 실패: {e}"
    except Exception as e:
        error = f"알 수 없는 오류: {type(e).__name__}: {e}"

    if data is None:
        return None, (error or "응답 없음")

    tag = data.get('tag_name') or ''
    body = data.get('body') or ''
    asset_url, asset_name = select_platform_asset(data.get('assets') or [])
    if not tag:
        return None, "릴리스에 태그가 없음"
    if not asset_url:
        return None, f"릴리스 {tag}에 이 OS에 맞는 .zip 파일이 없음"
    return ({'version': tag, 'download_url': asset_url,
             'asset_name': asset_name, 'body': body}, '')


def select_platform_asset(assets):
    """Pick the release .zip matching the current OS.

    Releases may carry several platform zips (e.g. BibleClip-windows-*.zip,
    BibleClip-macos-*.zip). Choose by OS keyword; fall back to a zip that does
    not belong to another platform (handles legacy single-zip releases).
    Returns (download_url, asset_name) or ('', '').
    """
    zips = [(a.get('name', ''), a.get('browser_download_url', ''))
            for a in assets
            if a.get('name', '').lower().endswith('.zip') and a.get('browser_download_url')]
    if not zips:
        return '', ''
    if sys.platform == 'darwin':
        want, avoid = ('macos', 'mac', 'darwin'), ('windows', 'win', 'linux')
    elif IS_WINDOWS:
        want, avoid = ('windows', 'win'), ('macos', 'darwin', 'linux')
    else:
        want, avoid = ('linux',), ('windows', 'win', 'macos', 'darwin')
    # 1) explicit OS match
    for name, url in zips:
        low = name.lower()
        if any(w in low for w in want):
            return url, name
    # 2) a zip not tagged for another OS (e.g. legacy single BibleClip-vX.zip)
    for name, url in zips:
        low = name.lower()
        if not any(a in low for a in avoid):
            return url, name
    # 3) nothing suitable
    return '', ''
