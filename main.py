"""
YouTube Downloader - Kivy Application
Main application file with yt-dlp integration
Supports: Android, Desktop, and WSL

Fixes applied:
  - All Android imports guarded with try/except at top level
  - mActivity imported correctly for ffmpeg binary resolution
  - ffmpeg binary resolved lazily via get_ffmpeg_bin() — never at module level
  - Correct API 33 permissions (READ_MEDIA_VIDEO / READ_MEDIA_AUDIO + WRITE_EXTERNAL_STORAGE)
  - Permissions requested with callback — setup_storage() runs AFTER user grants
  - Storage uses Environment.DIRECTORY_DOWNLOADS (survives uninstall, works API 29+)
  - LD_LIBRARY_PATH set safely, preserving existing entries
  - merge_output_format only applied when ffmpeg is used
  - ffmpeg_location passed explicitly to yt-dlp on both platforms

New features:
  - Pause / Continue button during download (pauses the download thread)
  - Cancel button with confirmation dialog — also deletes .part files on disk
  - Resume continues from where it stopped (yt-dlp --continue flag)
  - Share intent: YouTube URL pasted from YouTube share, copied to clipboard as fallback
"""

import os
import re
import glob
import threading
import subprocess
from pathlib import Path
from urllib.parse import urlparse

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.clock import Clock
from kivy.properties import StringProperty, BooleanProperty, NumericProperty
from kivy.lang import Builder
from kivy.core.window import Window

# ── Platform detection ─────────────────────────────────────────────────────────
# ALL Android imports must live inside this single try/except block.
try:
    from android import mActivity
    from android.permissions import request_permissions, Permission, check_permission
    from android.storage import primary_external_storage_path
    ANDROID = True
except ImportError:
    ANDROID = False

if not ANDROID:
    Window.minimum_height = 780
    Window.minimum_width = 560

# ── yt-dlp ─────────────────────────────────────────────────────────────────────
import yt_dlp


# ── FFmpeg binary — lazy resolution ────────────────────────────────────────────
_ffmpeg_bin_cache = None


def _find_ffmpeg_on_desktop():
    """
    Search for ffmpeg in all common locations on Windows, WSL, and Linux/macOS.
    Returns the full path string if found, or None if not found anywhere.
    """
    import shutil

    # 1. System PATH first (fastest check)
    found = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")
    if found:
        print(f"[FFmpeg] Found on PATH: {found}")
        return found

    candidates = []

    # 2. Native Windows absolute paths
    win_subdirs = [
        "ffmpeg/bin/ffmpeg.exe",
        "ffmpeg-master-latest-win64-gpl/bin/ffmpeg.exe",
        "Program Files/ffmpeg/bin/ffmpeg.exe",
        "Program Files (x86)/ffmpeg/bin/ffmpeg.exe",
        "ProgramData/chocolatey/bin/ffmpeg.exe",
        "tools/ffmpeg/bin/ffmpeg.exe",
    ]
    for drive in ["C:", "D:"]:
        for sub in win_subdirs:
            candidates.append(os.path.join(drive + os.sep, sub))

    # Scoop (per-user Windows)
    userprofile = os.environ.get("USERPROFILE", "")
    if userprofile:
        candidates.append(os.path.join(userprofile, "scoop", "shims", "ffmpeg.exe"))
        candidates.append(os.path.join(userprofile, "scoop", "apps", "ffmpeg", "current", "bin", "ffmpeg.exe"))

    # Conda / Miniconda
    conda_base = os.environ.get("CONDA_PREFIX", "") or os.environ.get("CONDA_DIR", "")
    if conda_base:
        candidates.append(os.path.join(conda_base, "bin", "ffmpeg"))
        candidates.append(os.path.join(conda_base, "Library", "bin", "ffmpeg.exe"))

    # 3. WSL — Windows drives mounted under /mnt/c, /mnt/d
    for mnt_drive in ["c", "d"]:
        base = f"/mnt/{mnt_drive}"
        if os.path.isdir(base):
            for sub in win_subdirs:
                wsl_sub = sub.replace("\\", "/")
                candidates.append(f"{base}/{wsl_sub}")

    # 4. Common Linux / macOS locations
    candidates.extend([
        "/usr/bin/ffmpeg",
        "/usr/local/bin/ffmpeg",
        "/opt/homebrew/bin/ffmpeg",
        "/usr/local/Cellar/ffmpeg/bin/ffmpeg",
        "/snap/bin/ffmpeg",
        "/opt/ffmpeg/bin/ffmpeg",
        os.path.expanduser("~/.local/bin/ffmpeg"),
        os.path.expanduser("~/bin/ffmpeg"),
    ])

    # Check each candidate
    for path in candidates:
        if os.path.isfile(path):
            try:
                result = subprocess.run([path, "-version"], capture_output=True, timeout=3)
                if result.returncode == 0:
                    print(f"[FFmpeg] Found at: {path}")
                    return path
            except Exception:
                continue

    print("[FFmpeg] Not found in any known location")
    return None


FFMPEG_INSTALL_HELP = (
    "ffmpeg not found. Please install it:\n"
    "  Windows : winget install ffmpeg   (or: choco install ffmpeg)\n"
    "  Ubuntu  : sudo apt install ffmpeg\n"
    "  macOS   : brew install ffmpeg\n"
    "Then restart the app."
)


def get_ffmpeg_bin():
    """
    Returns the path to the ffmpeg binary.
    On Android: libffmpegbin.so from nativeLibraryDir (placed by p4a ffmpeg recipe)
    On Desktop: 'ffmpeg' from system PATH.
    Result is cached after first call.
    """
    global _ffmpeg_bin_cache
    if _ffmpeg_bin_cache is not None:
        return _ffmpeg_bin_cache

    if ANDROID:
        app_info = mActivity.getApplicationInfo()
        native_lib_dir = app_info.nativeLibraryDir
        _ffmpeg_bin_cache = os.path.join(native_lib_dir, "libffmpegbin.so")

        existing = os.environ.get("LD_LIBRARY_PATH", "")
        if native_lib_dir not in existing:
            os.environ["LD_LIBRARY_PATH"] = (
                native_lib_dir + (":" + existing if existing else "")
            )
        print(f"[FFmpeg] Binary: {_ffmpeg_bin_cache}")
        print(f"[FFmpeg] LD_LIBRARY_PATH: {os.environ['LD_LIBRARY_PATH']}")
    else:
        found = _find_ffmpeg_on_desktop()
        if not found:
            raise RuntimeError(FFMPEG_INSTALL_HELP)
        _ffmpeg_bin_cache = found
        print(f"[FFmpeg] Using: {_ffmpeg_bin_cache}")

    return _ffmpeg_bin_cache


def format_size(bytes_count):
    """
    Convert a byte count into a human-readable string.
    e.g. 1024 → '1.0 KB', 1048576 → '1.0 MB', 1073741824 → '1.0 GB'
    """
    if bytes_count <= 0:
        return '0 KB'
    elif bytes_count < 1024 * 1024:
        return f'{bytes_count / 1024:.1f} KB'
    elif bytes_count < 1024 * 1024 * 1024:
        return f'{bytes_count / (1024 * 1024):.1f} MB'
    else:
        return f'{bytes_count / (1024 * 1024 * 1024):.2f} GB'


# ── yt-dlp logger ──────────────────────────────────────────────────────────────
class YTDLPLogger:
    def debug(self, msg):
        pass

    def warning(self, msg):
        print(f"[yt-dlp WARNING] {msg}")

    def error(self, msg):
        print(f"[yt-dlp ERROR] {msg}")

    def write(self, msg):
        if msg.strip():
            print(msg.strip())

    def flush(self):
        pass


# ── Main widget ────────────────────────────────────────────────────────────────
class YouTubeDownloader(BoxLayout):
    """Main widget for YouTube Downloader"""

    url_text = StringProperty('')
    quality_selected = StringProperty('max')
    audio_only = BooleanProperty(False)
    is_loading = BooleanProperty(False)
    is_paused = BooleanProperty(False)
    error_message = StringProperty('')
    success_message = StringProperty('')

    download_progress = NumericProperty(0)
    current_item = StringProperty('')
    total_items = NumericProperty(0)
    download_size = StringProperty('')

    def __init__(self, **kwargs):
        # ── ALL instance vars MUST be set before super().__init__() ───────────
        # Kivy dispatches on_kv_post from inside super().__init__() (via
        # widget.py → EventDispatcher.dispatch). If on_kv_post runs before
        # these attributes exist we get AttributeError and the app crashes.
        self._pending_shared_url = None   # URL buffered until UI is ready
        self._pause_event = threading.Event()
        self._pause_event.set()           # start in running state
        self._cancel_flag = False
        self._download_thread = None
        self._current_output_path = None

        super().__init__(**kwargs)        # on_kv_post may fire here

        print(f"[App] __init__ complete. ANDROID={ANDROID}")

        if ANDROID:
            print("[App] Requesting permissions...")
            request_permissions(
                [
                    Permission.READ_MEDIA_VIDEO,
                    Permission.READ_MEDIA_AUDIO,
                    Permission.WRITE_EXTERNAL_STORAGE,
                ],
                self.on_permissions_result
            )
        else:
            self.setup_storage()

    # ── KV ready ──────────────────────────────────────────────────────────────

    def on_kv_post(self, base_widget):
        """
        Kivy calls this once after the KV file is loaded and self.ids is ready.
        This is the ONLY place we trigger intent reading on Android —
        it guarantees the UI exists before we try to paste a URL into it.
        """
        print("[App] on_kv_post fired — UI (self.ids) is now ready")

        # Flush any URL that arrived before the UI was built
        if self._pending_shared_url:
            print(f"[Intent] Flushing buffered URL from on_kv_post: {self._pending_shared_url}")
            self._apply_url(self._pending_shared_url)
            self._pending_shared_url = None

        if ANDROID:
            # 0.5 s delay lets the Android activity fully settle after launch
            print("[Intent] Scheduling _read_intent in 0.5 s...")
            Clock.schedule_once(lambda dt: self._read_intent(), 0.5)

    # ── Intent handling ────────────────────────────────────────────────────────

    def _read_intent(self):
        """
        Read the current Android intent.

        If it is a YouTube URL shared via ACTION_SEND / text/plain:
          STEP 1 — copy URL to clipboard   (always works — user can paste manually)
          STEP 2 — paste URL into input field
          STEP 3 — clear the intent        (prevents re-processing on next resume)

        All exceptions are caught and logged — a broken intent can never crash the app.
        """
        print("[Intent] _read_intent called")

        if not ANDROID:
            print("[Intent] Not Android — skipping")
            return

        try:
            from jnius import autoclass
            Intent = autoclass('android.content.Intent')
            print("[Intent] jnius autoclass OK")

            intent = mActivity.getIntent()
            if intent is None:
                print("[Intent] mActivity.getIntent() returned None — nothing to handle")
                return

            action   = intent.getAction()
            mimetype = intent.getType()
            print(f"[Intent] action  = {action}")
            print(f"[Intent] mime    = {mimetype}")

            if action != Intent.ACTION_SEND:
                print(f"[Intent] action is not ACTION_SEND — ignoring")
                return

            if mimetype != 'text/plain':
                print(f"[Intent] mime is not text/plain — ignoring")
                return

            shared_text = intent.getStringExtra(Intent.EXTRA_TEXT)
            print(f"[Intent] EXTRA_TEXT = {repr(shared_text)}")

            if not shared_text:
                print("[Intent] EXTRA_TEXT is empty — nothing to do")
                return

            # ── Extract YouTube URL ────────────────────────────────────────────
            # YouTube share text is typically:
            #   "Video Title https://youtu.be/xxxx"
            # or just the URL. The regex finds the first YouTube URL in the string.
            pattern = r'https?://(?:www\.)?(?:youtube\.com/watch\?[^\s]+|youtu\.be/[^\s]+)'
            match = re.search(pattern, shared_text)

            if match:
                url = match.group(0)
                print(f"[Intent] URL extracted by regex: {url}")
            else:
                # Fall back to the whole text stripped
                url = shared_text.strip()
                print(f"[Intent] No regex match — using full text as URL: {url}")

            if not self.validate_url(url):
                print(f"[Intent] validate_url FAILED for: {url}")
                print("[Intent] URL rejected — not a recognised YouTube URL")
                return

            print(f"[Intent] URL is valid: {url}")

            # ── STEP 1: Clipboard ─────────────────────────────────────────────
            # Done first so the user always has the URL even if the UI paste fails.
            try:
                from kivy.core.clipboard import Clipboard
                Clipboard.copy(url)
                print(f"[Intent] STEP 1 OK — URL copied to clipboard: {url}")
            except Exception as clip_err:
                print(f"[Intent] STEP 1 FAILED — clipboard copy error: {clip_err}")

            # ── STEP 2: Paste into input field ────────────────────────────────
            self._apply_url(url)

            # ── STEP 3: Clear intent ──────────────────────────────────────────
            # Prevents this same intent being re-read when the user returns
            # to the app after navigating away (e.g. after visiting Settings).
            try:
                mActivity.setIntent(None)
                print("[Intent] STEP 3 OK — intent cleared (setIntent(None))")
            except Exception as clear_err:
                print(f"[Intent] STEP 3 FAILED — could not clear intent: {clear_err}")

        except Exception as e:
            import traceback
            print(f"[Intent] _read_intent EXCEPTION: {type(e).__name__}: {e}")
            print(traceback.format_exc())

    def _apply_url(self, url):
        """
        Write url into self.ids.url_input.

        _on_new_intent_activity fires on the Android thread, not the Kivy
        thread. Writing to widgets from a non-Kivy thread raises:
          TypeError: Cannot change graphics instruction outside the main Kivy thread
        Fix: always dispatch the actual widget write via Clock.schedule_once,
        which guarantees it runs on the Kivy main thread regardless of which
        thread _apply_url was called from.
        """
        print(f"[Intent] _apply_url called with: {url} — scheduling on Kivy thread")
        Clock.schedule_once(lambda dt: self._write_url_to_field(url), 0)

    def _write_url_to_field(self, url):
        """Runs on the Kivy main thread — safe to touch widgets."""
        print(f"[Intent] _write_url_to_field: writing to input field")
        try:
            input_widget = self.ids.url_input
            self.url_text = url
            input_widget.text = url
            self.error_message  = ''
            self.success_message = ''
            print(f"[Intent] STEP 2 OK — URL written to input field: {url}")
        except Exception as e:
            print(f"[Intent] STEP 2 FAILED — ({type(e).__name__}: {e})")
            print(f"[Intent] Buffering URL — on_kv_post will retry")
            self._pending_shared_url = url

    def on_new_intent(self, intent):
        """
        Called by activity.bind when Android delivers a new share intent to
        the already-running (backgrounded) app.

        THREADING: this method runs on the Android/Java thread, NOT the Kivy
        main thread. Therefore we must never touch Kivy widgets directly here.

        Strategy:
          1. Extract the URL from the intent on the Android thread (safe — no widgets).
          2. Copy to clipboard on the Android thread (safe).
          3. Hand off ALL widget writes to the Kivy thread via Clock.schedule_once.
        """
        print("[Intent] on_new_intent — app backgrounded, new share received")
        if not ANDROID:
            return
        try:
            # ── Extract URL on Android thread (no widget access) ───────────────
            from jnius import autoclass
            Intent = autoclass('android.content.Intent')

            action   = intent.getAction()
            mimetype = intent.getType()
            print(f"[Intent] on_new_intent: action={action}  mime={mimetype}")

            if action != Intent.ACTION_SEND or mimetype != 'text/plain':
                print("[Intent] on_new_intent: not a text/plain share — ignoring")
                return

            shared_text = intent.getStringExtra(Intent.EXTRA_TEXT)
            print(f"[Intent] on_new_intent: EXTRA_TEXT={repr(shared_text)}")
            if not shared_text:
                print("[Intent] on_new_intent: EXTRA_TEXT empty — nothing to do")
                return

            pattern = r'https?://(?:www\.)?(?:youtube\.com/watch\?[^\s]+|youtu\.be/[^\s]+)'
            match = re.search(pattern, shared_text)
            url = match.group(0) if match else shared_text.strip()
            print(f"[Intent] on_new_intent: extracted url={url}")

            if not self.validate_url(url):
                print("[Intent] on_new_intent: not a valid YouTube URL — ignoring")
                return

            # ── Clipboard (safe on Android thread) ────────────────────────────
            try:
                from kivy.core.clipboard import Clipboard
                Clipboard.copy(url)
                print("[Intent] on_new_intent: URL copied to clipboard")
            except Exception as ce:
                print(f"[Intent] on_new_intent: clipboard copy failed: {ce}")

            # ── Store intent on activity (safe on Android thread) ─────────────
            mActivity.setIntent(intent)

            # ── All widget writes → Kivy main thread via Clock.schedule_once ──
            # _apply_url already uses Clock internally, but we also need to
            # clear the old URL — do that in the same scheduled call.
            print("[Intent] on_new_intent: scheduling UI update on Kivy thread")
            Clock.schedule_once(lambda dt: self._on_new_intent_kivy_thread(url), 0)

        except Exception as e:
            import traceback
            print(f"[Intent] on_new_intent ERROR: {type(e).__name__}: {e}")
            print(traceback.format_exc())

    def _on_new_intent_kivy_thread(self, url):
        """
        Runs on the Kivy main thread — safe to read/write widgets here.
        Clears the old URL then writes the new one.
        """
        print(f"[Intent] _on_new_intent_kivy_thread: updating UI with url={url}")
        try:
            self.url_text = ''
            self.ids.url_input.text = ''
            self.error_message = ''
            self.success_message = ''
            print("[Intent] Input field cleared")
        except Exception as e:
            print(f"[Intent] Could not clear input field: {e}")
        # _write_url_to_field is already on Kivy thread — call directly
        self._write_url_to_field(url)

    # ── Permissions ────────────────────────────────────────────────────────────

    def on_permissions_result(self, permissions, grants):
        print("[Permissions] on_permissions_result called")
        for perm, granted in zip(permissions, grants):
            status = 'GRANTED' if granted else 'DENIED'
            print(f"[Permissions]   {perm.split('.')[-1]}: {status}")

        if ANDROID:
            try:
                from jnius import autoclass
                Environment = autoclass('android.os.Environment')
                Build = autoclass('android.os.Build')

                print(f"[Permissions] Android SDK version: {Build.VERSION.SDK_INT}")

                if Build.VERSION.SDK_INT >= 30:
                    is_manager = Environment.isExternalStorageManager()
                    print(f"[Permissions] isExternalStorageManager: {is_manager}")
                    if not is_manager:
                        Intent = autoclass('android.content.Intent')
                        Settings = autoclass('android.provider.Settings')
                        Uri = autoclass('android.net.Uri')
                        intent = Intent(
                            Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION
                        )
                        intent.setData(Uri.parse('package:org.ytdl.ytdlapp'))
                        mActivity.startActivity(intent)
                        print("[Permissions] Sent user to All Files Access settings")
                else:
                    print("[Permissions] SDK < 30 — no MANAGE_EXTERNAL_STORAGE needed")

            except Exception as e:
                print(f"[Permissions] Storage manager check error: {e}")

        print("[Permissions] Calling setup_storage()")
        self.setup_storage()
        # Intent is handled in on_kv_post — do NOT schedule it here.
        # on_permissions_result may fire before on_kv_post on some devices.

    # ── Storage setup ──────────────────────────────────────────────────────────

    def is_wsl(self):
        """Detect if running inside WSL"""
        try:
            with open('/proc/version', 'r') as f:
                content = f.read().lower()
                return 'microsoft' in content or 'wsl' in content
        except Exception:
            return False

    def get_windows_username(self):
        """Get Windows username when running in WSL"""
        try:
            result = subprocess.run(
                ['cmd.exe', '/c', 'echo', '%USERNAME%'],
                capture_output=True, text=True, timeout=2
            )
            username = result.stdout.strip()
            if username and username != '%USERNAME%':
                return username
        except Exception:
            pass

        try:
            result = subprocess.run(
                ['powershell.exe', '-Command', '$env:USERNAME'],
                capture_output=True, text=True, timeout=2
            )
            username = result.stdout.strip()
            if username:
                return username
        except Exception:
            pass

        try:
            users_dir = '/mnt/c/Users'
            if os.path.exists(users_dir):
                skip = {'Public', 'Default', 'Default User', 'All Users'}
                users = [
                    d for d in os.listdir(users_dir)
                    if os.path.isdir(os.path.join(users_dir, d)) and d not in skip
                ]
                if users:
                    return users[0]
        except Exception:
            pass

        return None

    def setup_storage(self):
        """Setup download paths for Android, Desktop, or WSL."""
        print("[Storage] setup_storage() called")
        try:
            if ANDROID:
                from jnius import autoclass
                Environment = autoclass('android.os.Environment')
                downloads_dir = Environment.getExternalStoragePublicDirectory(
                    Environment.DIRECTORY_DOWNLOADS
                ).getAbsolutePath()
                base_path = os.path.join(downloads_dir, 'YouTubeDownloader')
                print(f"[Storage] Android Downloads: {base_path}")

            elif self.is_wsl():
                print("[Storage] Running in WSL")
                windows_user = self.get_windows_username()
                if windows_user:
                    base_path = f'/mnt/c/Users/{windows_user}/Downloads/YouTubeDownloader'
                    print(f"[Storage] Windows Downloads for user: {windows_user}")
                else:
                    base_path = str(Path.home() / "Downloads" / "YouTubeDownloader")
                    print(f"[Storage] WSL fallback: {base_path}")

            else:
                base_path = str(Path.home() / "Downloads" / "YouTubeDownloader")
                print(f"[Storage] Desktop: {base_path}")

            self.audio_path = os.path.join(base_path, 'Audio')
            self.video_path = os.path.join(base_path, 'Video')
            os.makedirs(self.audio_path, exist_ok=True)
            os.makedirs(self.video_path, exist_ok=True)
            print(f"[Storage] Audio path: {self.audio_path}")
            print(f"[Storage] Video path: {self.video_path}")

        except Exception as e:
            print(f"[Storage] Setup error: {e} — using fallback")
            fallback = os.path.join(os.getcwd(), 'downloads')
            self.audio_path = os.path.join(fallback, 'Audio')
            self.video_path = os.path.join(fallback, 'Video')
            os.makedirs(self.audio_path, exist_ok=True)
            os.makedirs(self.video_path, exist_ok=True)
            print(f"[Storage] Fallback path: {fallback}")

    # ── URL helpers ────────────────────────────────────────────────────────────

    def validate_url(self, url):
        """Validate if the URL is a valid YouTube URL"""
        if not url.strip():
            return False
        try:
            parsed = urlparse(url)
            return 'youtube.com' in parsed.netloc or 'youtu.be' in parsed.netloc
        except Exception:
            return False

    def is_playlist(self, url):
        """Check if URL points to a playlist"""
        return 'playlist' in url.lower() or 'list=' in url

    # ── UI event handlers ──────────────────────────────────────────────────────

    def on_paste_click(self):
        """Handle paste button click"""
        try:
            from kivy.core.clipboard import Clipboard
            text = Clipboard.paste()
            if text:
                self.ids.url_input.text = text
                self.url_text = text
                self.error_message = ''
        except Exception as e:
            print(f"[Clipboard] Error: {e}")
            self.error_message = 'Unable to paste from clipboard'

    def on_url_change(self, text):
        """Handle URL input changes"""
        self.url_text = text
        self.error_message = ''
        self.success_message = ''

    def on_quality_select(self, quality):
        """Handle quality selection"""
        if not self.audio_only:
            self.quality_selected = quality
            self.error_message = ''

    def on_audio_toggle(self, active):
        """Handle audio-only toggle"""
        self.audio_only = active
        self.error_message = ''
        if active:
            self.quality_selected = 'max'

    # ── Pause / Resume ─────────────────────────────────────────────────────────

    def on_pause_resume_click(self):
        """Toggle between paused and running state."""
        if self.is_paused:
            self.is_paused = False
            self._pause_event.set()
            print("[Control] Download RESUMED")
        else:
            self.is_paused = True
            self._pause_event.clear()
            print("[Control] Download PAUSED")

    # ── Cancel with confirmation ───────────────────────────────────────────────

    def on_cancel_click(self):
        """Show a well-spaced Android-friendly confirmation popup."""
        from kivy.metrics import dp, sp

        msg = Label(
            text='Cancel the current download?\nThe incomplete file will be deleted.',
            font_size=sp(15),
            color=(0.88, 0.88, 0.88, 1),
            halign='center',
            valign='middle',
            size_hint_y=None,
            height=dp(72),
        )
        msg.bind(size=msg.setter('text_size'))

        divider = BoxLayout(size_hint_y=None, height=dp(1))
        with divider.canvas.before:
            from kivy.graphics import Color as GColor, Rectangle as GRect
            GColor(0.72, 0.15, 0.15, 1)
            divider._rect = GRect(pos=divider.pos, size=divider.size)
        def _update_div(instance, value):
            instance._rect.pos  = instance.pos
            instance._rect.size = instance.size
        divider.bind(pos=_update_div, size=_update_div)

        btn_no = Button(
            text='No',
            background_normal='',
            background_color=(0.20, 0.20, 0.20, 1),
            color=(0.88, 0.88, 0.88, 1),
            font_size=sp(15),
            bold=True,
            size_hint_y=None,
            height=dp(54),
        )

        btn_yes = Button(
            text='Yes, Cancel',
            background_normal='',
            background_color=(0.72, 0.15, 0.15, 1),
            color=(1, 1, 1, 1),
            font_size=sp(15),
            bold=True,
            size_hint_y=None,
            height=dp(54),
        )

        btn_row = BoxLayout(
            orientation='horizontal',
            spacing=dp(10),
            size_hint_y=None,
            height=dp(54),
        )
        btn_row.add_widget(btn_no)
        btn_row.add_widget(btn_yes)

        content = BoxLayout(
            orientation='vertical',
            padding=[dp(20), dp(18), dp(20), dp(18)],
            spacing=dp(14),
        )
        content.add_widget(msg)
        content.add_widget(divider)
        content.add_widget(btn_row)

        total_h = dp(18) + dp(72) + dp(1) + dp(14)*2 + dp(54) + dp(18)

        popup = Popup(
            title='Cancel Download',
            title_color=(1, 1, 1, 1),
            title_size=sp(16),
            title_align='center',
            content=content,
            size_hint=(0.86, None),
            height=total_h + dp(48),
            background='',
            background_color=(0.12, 0.12, 0.12, 1),
            separator_color=(0.72, 0.15, 0.15, 1),
            separator_height=dp(2),
            auto_dismiss=False,
        )

        btn_no.bind(on_release=lambda _: popup.dismiss())
        btn_yes.bind(on_release=lambda _: self._confirm_cancel(popup))
        popup.open()

    def _confirm_cancel(self, popup):
        """User confirmed cancel — stop download and clean up."""
        popup.dismiss()
        print("[Control] Download CANCELLED by user")
        self._cancel_flag = True
        self._pause_event.set()
        self._reset_download_state()
        Clock.schedule_once(lambda dt: self._cleanup_part_files(), 1.5)

    def _cleanup_part_files(self):
        """Delete any .part or .ytdl files left by the cancelled download."""
        if not self._current_output_path:
            return
        try:
            patterns = [
                os.path.join(self._current_output_path, '*.part'),
                os.path.join(self._current_output_path, '*.ytdl'),
                os.path.join(self._current_output_path, '*.part-Frag*'),
            ]
            deleted = []
            for pattern in patterns:
                for f in glob.glob(pattern):
                    try:
                        os.remove(f)
                        deleted.append(os.path.basename(f))
                        print(f"[Cleanup] Deleted: {f}")
                    except Exception as del_err:
                        print(f"[Cleanup] Could not delete {f}: {del_err}")

            if deleted:
                print(f"[Cleanup] Removed {len(deleted)} temp file(s)")
            else:
                print("[Cleanup] No .part files found")

        except Exception as e:
            print(f"[Cleanup] Error: {e}")

    def _reset_download_state(self):
        """Reset all download-related UI properties."""
        self.is_loading = False
        self.is_paused = False
        self.download_progress = 0
        self.download_size = ''
        self.current_item = ''
        self.error_message = ''
        self.success_message = ''
        self._pause_event.set()
        try:
            self.url_text = ''
            self.ids.url_input.text = ''
            print("[Control] URL input cleared after cancel")
        except Exception as e:
            print(f"[Control] Could not clear URL field: {e}")

    # ── Download logic ─────────────────────────────────────────────────────────

    def start_download(self):
        """Validate input and kick off download thread"""
        self.error_message = ''
        self.success_message = ''

        if not self.validate_url(self.url_text):
            self.error_message = 'Please enter a valid YouTube URL'
            return

        self._cancel_flag = False
        self._pause_event.set()

        self.is_loading = True
        self.is_paused = False
        self.download_progress = 0
        self.download_size = ''
        self.total_items = 0

        self._download_thread = threading.Thread(target=self.download_video, daemon=True)
        self._download_thread.start()

    def download_video(self):
        """
        Core download worker — runs on background thread.
        Checks _cancel_flag and _pause_event on every progress tick.
        """
        try:
            output_path = self.audio_path if self.audio_only else self.video_path
            self._current_output_path = output_path

            print("\n" + "=" * 60)
            print("DOWNLOAD STARTED")
            print("=" * 60)
            print(f"URL:      {self.url_text}")
            print(f"Mode:     {'Audio (M4A/MP3)' if self.audio_only else 'Video'}")
            print(f"Quality:  {self.quality_selected}")
            print(f"Output:   {output_path}")
            print(f"Platform: {'Android' if ANDROID else 'Desktop'}")

            def progress_hook(d):
                if self._cancel_flag:
                    raise yt_dlp.utils.DownloadCancelled("User cancelled")

                while not self._pause_event.is_set():
                    if self._cancel_flag:
                        raise yt_dlp.utils.DownloadCancelled("User cancelled while paused")
                    self._pause_event.wait(timeout=0.2)

                try:
                    if d['status'] == 'downloading':
                        downloaded = d.get('downloaded_bytes', 0)
                        total = d.get('total_bytes') or d.get('total_bytes_estimate', 0)
                        if total:
                            percent = (downloaded / total) * 100
                            Clock.schedule_once(
                                lambda dt: setattr(self, 'download_progress', percent), 0
                            )

                        if total:
                            size_str = f'{format_size(downloaded)} / {format_size(total)}'
                        elif downloaded:
                            size_str = format_size(downloaded)
                        else:
                            size_str = ''

                        if size_str:
                            Clock.schedule_once(
                                lambda dt, s=size_str: setattr(self, 'download_size', s), 0
                            )

                        filename = d.get('filename', '')
                        if filename:
                            short_name = os.path.basename(filename)[:35]
                            Clock.schedule_once(
                                lambda dt, n=short_name: setattr(self, 'current_item', n), 0
                            )
                    elif d['status'] == 'finished':
                        Clock.schedule_once(
                            lambda dt: setattr(self, 'download_progress', 100), 0
                        )
                except yt_dlp.utils.DownloadCancelled:
                    raise
                except Exception as hook_err:
                    print(f"[Progress hook] Error: {hook_err}")

            ydl_opts = {
                'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
                'logger': YTDLPLogger(),
                'progress_hooks': [progress_hook],
                'quiet': False,
                'no_warnings': False,
                'noprogress': False,
                'ignoreerrors': False,
                'nocheckcertificate': True,
                'continuedl': True,
            }

            if self.is_playlist(self.url_text):
                ydl_opts['noplaylist'] = False
                print("Playlist detected — downloading all videos")
                Clock.schedule_once(
                    lambda dt: setattr(self, 'success_message', 'Downloading playlist...'), 0
                )
            else:
                ydl_opts['noplaylist'] = True
                print("Single video download")

            if self.audio_only:
                if ANDROID:
                    ydl_opts['format'] = 'bestaudio[ext=m4a]/bestaudio'
                    print("Android: Downloading M4A audio (no post-processing)")
                else:
                    ffmpeg = get_ffmpeg_bin()
                    ydl_opts['format'] = 'bestaudio/best'
                    ydl_opts['postprocessors'] = [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }]
                    ydl_opts['prefer_ffmpeg'] = True
                    ydl_opts['ffmpeg_location'] = ffmpeg
                    print("Desktop: Converting audio to MP3 via ffmpeg")
            else:
                quality_map = {
                    'max':   ('best',               'bestvideo+bestaudio/best'),
                    '1080p': ('best[height<=1080]',  'bestvideo[height<=1080]+bestaudio/best[height<=1080]'),
                    '720':   ('best[height<=720]',   'bestvideo[height<=720]+bestaudio/best[height<=720]'),
                    '480':   ('best[height<=480]',   'bestvideo[height<=480]+bestaudio/best[height<=480]'),
                }
                android_fmt, desktop_fmt = quality_map.get(
                    self.quality_selected, quality_map['max']
                )

                if ANDROID:
                    ffmpeg = get_ffmpeg_bin()
                    ydl_opts['format'] = desktop_fmt
                    ydl_opts['ffmpeg_location'] = ffmpeg
                    ydl_opts['merge_output_format'] = 'mp4'
                    print(f"Android: Merging via ffmpeg_bin (format: {desktop_fmt})")
                else:
                    ydl_opts['format'] = desktop_fmt
                    ydl_opts['merge_output_format'] = 'mp4'
                    print(f"Desktop: Merging video+audio (format: {desktop_fmt})")

            print("-" * 60)
            print("Fetching video information...")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url_text, download=False)

                if self._cancel_flag:
                    return

                if info and 'entries' in info:
                    total = len(list(info['entries']))
                    Clock.schedule_once(
                        lambda dt: setattr(self, 'total_items', total), 0
                    )
                    print(f"Found {total} videos in playlist")
                else:
                    Clock.schedule_once(
                        lambda dt: setattr(self, 'total_items', 1), 0
                    )
                    title = info.get('title', 'Unknown') if info else 'Unknown'
                    print(f"Video title: {title}")

                print("-" * 60)
                print("Starting download...")
                ydl.download([self.url_text])

            if self._cancel_flag:
                return

            print("-" * 60)
            print("Download completed successfully!")
            print("=" * 60 + "\n")

            Clock.schedule_once(lambda dt: self.on_download_success(), 0)

        except yt_dlp.utils.DownloadCancelled:
            print("[Control] Download thread exited after cancel")

        except RuntimeError as e:
            msg = str(e)
            print(f"[FFmpeg] {msg}")
            Clock.schedule_once(lambda dt: self.on_download_error(msg), 0)

        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)
            print("\n" + "=" * 60)
            print("DOWNLOAD ERROR (yt_dlp.DownloadError)")
            print("=" * 60)
            print(f"Full error: {error_msg}")
            print("=" * 60 + "\n")

            if self._cancel_flag:
                return

            if 'Video unavailable' in error_msg:
                user_msg = 'Video is unavailable or private'
            elif 'No video formats' in error_msg:
                user_msg = 'Selected quality not available for this video'
            elif 'Sign in' in error_msg or 'login' in error_msg.lower():
                user_msg = 'This video requires login — cannot download'
            else:
                user_msg = error_msg[:80] if len(error_msg) > 80 else error_msg

            Clock.schedule_once(lambda dt: self.on_download_error(user_msg), 0)

        except Exception as e:
            import traceback
            print("\n" + "=" * 60)
            print("UNEXPECTED ERROR")
            print("=" * 60)
            print(f"Type:      {type(e).__name__}")
            print(f"Message:   {e}")
            print(f"Traceback:\n{traceback.format_exc()}")
            print("=" * 60 + "\n")

            if self._cancel_flag:
                return

            user_msg = f'{type(e).__name__}: {str(e)[:60]}'
            Clock.schedule_once(lambda dt: self.on_download_error(user_msg), 0)

    # ── Download result handlers ───────────────────────────────────────────────

    def on_download_success(self):
        """Called on main thread after successful download"""
        self.is_loading = False
        self.is_paused = False
        self.error_message = ''

        file_type = 'Audio' if self.audio_only else 'Video'
        folder = 'Audio' if self.audio_only else 'Video'
        folder_path = self.audio_path if self.audio_only else self.video_path

        print("\n" + "=" * 60)
        print("DOWNLOAD COMPLETED SUCCESSFULLY!")
        print("=" * 60)
        print(f"Items:  {self.total_items}")
        print(f"Saved:  {folder_path}")
        print("=" * 60 + "\n")

        if self.total_items > 1:
            self.success_message = (
                f'✓ {self.total_items} items downloaded to {folder} folder'
            )
        else:
            if self.audio_only:
                self.success_message = '✓ Audio downloaded to Audio folder'
            else:
                self.success_message = f'✓ {file_type} downloaded to {folder} folder'

        self.url_text = ''
        self.ids.url_input.text = ''
        self.download_progress = 0
        self.download_size = ''
        self.current_item = ''

        Clock.schedule_once(lambda dt: self.clear_success(), 7)

    def on_download_error(self, error):
        """Called on main thread when download fails"""
        self.is_loading = False
        self.is_paused = False
        self.error_message = error
        self.success_message = ''
        self.download_progress = 0
        self.download_size = ''
        print(f"[Error displayed to user] {error}")

    def clear_success(self):
        """Clear success message"""
        self.success_message = ''


# ── Application ────────────────────────────────────────────────────────────────
class YouTubeDownloaderApp(App):
    """Main Kivy Application"""

    def build(self):
        self.title = 'YouTube Downloader'
        Builder.load_file('design.kv')
        self.root_widget = YouTubeDownloader()

        # ── Wire on_new_intent to the Android activity ────────────────────────
        # p4a does NOT call on_new_intent on the Kivy App class automatically.
        # We must bind a Python callback to the activity ourselves.
        # Without this, sharing a URL to an already-running app does nothing.
        if ANDROID:
            try:
                from android import activity  # p4a helper module
                activity.bind(on_new_intent=self._on_new_intent_activity)
                print("[App] on_new_intent bound to Android activity via activity.bind()")
            except Exception as e:
                print(f"[App] Could not bind on_new_intent via activity.bind(): {e}")
                print("[App] Falling back — on_new_intent may not work when app is backgrounded")

        return self.root_widget

    def _on_new_intent_activity(self, intent):
        """
        Called by p4a activity binding when Android delivers a new intent
        to the already-running app (e.g. user shares a URL from YouTube
        while our app is in the background).
        """
        print("[App] _on_new_intent_activity called — new intent received from Android")
        if hasattr(self, 'root_widget'):
            self.root_widget.on_new_intent(intent)
        else:
            print("[App] _on_new_intent_activity: root_widget not ready — intent lost")


if __name__ == '__main__':
    YouTubeDownloaderApp().run()