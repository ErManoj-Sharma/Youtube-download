"""
YouTube Downloader - Kivy Application
Main application file with yt-dlp integration
Supports: Android, Desktop, and WSL
"""

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.clock import Clock
from kivy.properties import StringProperty, BooleanProperty, NumericProperty
from kivy.lang import Builder
from urllib.parse import urlparse
import threading
import os
import subprocess
from pathlib import Path
from kivy.core.window import Window
Window.minimum_height = 780
Window.minimum_width = 560

# Import yt-dlp
import yt_dlp

# Android imports (will only work on Android)
try:
    from android.permissions import request_permissions, Permission
    from android.storage import primary_external_storage_path
    ANDROID = True
except ImportError:
    ANDROID = False


class YouTubeDownloader(BoxLayout):
    """Main widget for YouTube Downloader"""
    
    url_text = StringProperty('')
    quality_selected = StringProperty('max')
    audio_only = BooleanProperty(False)
    is_loading = BooleanProperty(False)
    error_message = StringProperty('')
    success_message = StringProperty('')
    
    # Properties for progress tracking (will use later)
    download_progress = NumericProperty(0)
    current_item = StringProperty('')
    total_items = NumericProperty(0)
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setup_storage()
    
    def is_wsl(self):
        """Detect if running in WSL"""
        try:
            with open('/proc/version', 'r') as f:
                version_info = f.read().lower()
                return 'microsoft' in version_info or 'wsl' in version_info
        except:
            return False
    
    def get_windows_username(self):
        """Get Windows username when running in WSL"""
        try:
            result = subprocess.run(['cmd.exe', '/c', 'echo', '%USERNAME%'], 
                                  capture_output=True, text=True, timeout=2)
            username = result.stdout.strip()
            if username and username != '%USERNAME%':
                return username
        except:
            pass
        
        try:
            result = subprocess.run(['powershell.exe', '-Command', '$env:USERNAME'], 
                                  capture_output=True, text=True, timeout=2)
            username = result.stdout.strip()
            if username:
                return username
        except:
            pass
        
        try:
            users_dir = '/mnt/c/Users'
            if os.path.exists(users_dir):
                users = [d for d in os.listdir(users_dir) 
                        if os.path.isdir(os.path.join(users_dir, d)) 
                        and d not in ['Public', 'Default', 'Default User', 'All Users']]
                if users:
                    return users[0]
        except:
            pass
        
        return None
    
    def setup_storage(self):
        """Setup storage paths for Android, Desktop, or WSL"""
        try:
            if ANDROID:
                request_permissions([
                    Permission.WRITE_EXTERNAL_STORAGE,
                    Permission.READ_EXTERNAL_STORAGE
                ])
                ext_storage = primary_external_storage_path()
                base_path = os.path.join(ext_storage, 'Download', 'YouTubeDownloader')
                print("Running on Android")
            
            elif self.is_wsl():
                print("Running in WSL")
                windows_user = self.get_windows_username()
                
                if windows_user:
                    base_path = f'/mnt/c/Users/{windows_user}/Downloads/YouTubeDownloader'
                    print(f"Using Windows Downloads for user: {windows_user}")
                else:
                    base_path = str(Path.home() / "Downloads" / "YouTubeDownloader")
                    print(f"Could not detect Windows user, using WSL home: {base_path}")
            
            else:
                base_path = str(Path.home() / "Downloads" / "YouTubeDownloader")
                print(f"Running on Desktop: {base_path}")
            
            self.audio_path = os.path.join(base_path, 'Audio')
            self.video_path = os.path.join(base_path, 'Video')
            
            os.makedirs(self.audio_path, exist_ok=True)
            os.makedirs(self.video_path, exist_ok=True)
            
            print(f"✓ Audio path: {self.audio_path}")
            print(f"✓ Video path: {self.video_path}")
            
        except Exception as e:
            print(f"⚠ Storage setup error: {e}")
            self.audio_path = os.path.join(os.getcwd(), 'downloads', 'Audio')
            self.video_path = os.path.join(os.getcwd(), 'downloads', 'Video')
            os.makedirs(self.audio_path, exist_ok=True)
            os.makedirs(self.video_path, exist_ok=True)
            print(f"Using fallback path: {os.getcwd()}/downloads/")
    
    def validate_url(self, url):
        """Validate if the URL is a valid YouTube URL"""
        if not url.strip():
            return False
        try:
            parsed = urlparse(url)
            return 'youtube.com' in parsed.netloc or 'youtu.be' in parsed.netloc
        except:
            return False
    
    def is_playlist(self, url):
        """Check if URL is a playlist"""
        return 'playlist' in url.lower() or 'list=' in url
    
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
            self.error_message = 'Unable to paste from clipboard'
    
    def on_url_change(self, text):
        """Handle URL input change"""
        self.url_text = text
        self.error_message = ''
        self.success_message = ''
    
    def on_quality_select(self, quality):
        """Handle quality selection"""
        if not self.audio_only:
            self.quality_selected = quality
            self.error_message = ''
    
    def on_audio_toggle(self, active):
        """Handle audio only toggle"""
        self.audio_only = active
        self.error_message = ''
        if active:
            self.quality_selected = 'max'
    
    def start_download(self):
        """Start the download process"""
        self.error_message = ''
        self.success_message = ''
        
        if not self.validate_url(self.url_text):
            self.error_message = 'Please enter a valid YouTube URL'
            return
        
        self.is_loading = True
        self.total_items = 0
        
        thread = threading.Thread(target=self.download_video)
        thread.daemon = True
        thread.start()
    
    def download_video(self):
        """Download video/audio using yt-dlp"""
        try:
            output_path = self.audio_path if self.audio_only else self.video_path

            print("\n" + "=" * 60)
            print("🚀 DOWNLOAD STARTED")
            print("=" * 60)
            print(f"URL: {self.url_text}")
            print(f"Mode: {'Audio (MP3)' if self.audio_only else 'Video'}")
            print(f"Quality: {self.quality_selected}")
            print(f"Output Path: {output_path}")

            # Progress hook for UI updates
            def progress_hook(d):
                try:
                    if d['status'] == 'downloading':
                        if 'downloaded_bytes' in d and 'total_bytes' in d:
                            percent = (d['downloaded_bytes'] / d['total_bytes']) * 100
                            Clock.schedule_once(
                                lambda dt: setattr(self, 'download_progress', percent), 0
                            )

                        elif 'downloaded_bytes' in d and 'total_bytes_estimate' in d:
                            percent = (
                                d['downloaded_bytes'] / d['total_bytes_estimate']
                            ) * 100
                            Clock.schedule_once(
                                lambda dt: setattr(self, 'download_progress', percent), 0
                            )

                        filename = d.get('filename', '')
                        if filename:
                            filename = os.path.basename(filename)
                            Clock.schedule_once(
                                lambda dt: setattr(self, 'current_item', filename[:40]), 0
                            )

                    elif d['status'] == 'finished':
                        Clock.schedule_once(
                            lambda dt: setattr(self, 'download_progress', 100), 0
                        )

                except Exception:
                    pass

            ydl_opts = {
                'outtmpl': os.path.join(output_path, '%(title)s.%(ext)s'),
                'quiet': True,
                'no_warnings': True,
                'progress_hooks': [progress_hook],
                'noprogress': False,
            }

            if self.is_playlist(self.url_text):
                ydl_opts['noplaylist'] = False
                print("📋 Playlist detected - downloading all videos")
                Clock.schedule_once(
                    lambda dt: setattr(self, 'success_message', 'Downloading playlist...'),
                    0,
                )
            else:
                ydl_opts['noplaylist'] = True
                print("📹 Single video download")

            if self.audio_only:
                ydl_opts['format'] = 'bestaudio/best'
                ydl_opts['postprocessors'] = [
                    {
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }
                ]
                ydl_opts['prefer_ffmpeg'] = True

            else:
                if self.quality_selected == 'max':
                    ydl_opts['format'] = 'bestvideo+bestaudio/best'
                elif self.quality_selected == '1080p':
                    ydl_opts['format'] = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]'
                elif self.quality_selected == '720':
                    ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]'
                elif self.quality_selected == '480':
                    ydl_opts['format'] = 'bestvideo[height<=480]+bestaudio/best[height<=480]'

                ydl_opts['merge_output_format'] = 'mp4'

            print("-" * 60)
            print("⏳ Fetching video information...")

            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.url_text, download=False)

                if 'entries' in info:
                    total = len(list(info['entries']))
                    Clock.schedule_once(
                        lambda dt: setattr(self, 'total_items', total), 0
                    )
                    print(f"📊 Found {total} videos in playlist")
                else:
                    Clock.schedule_once(
                        lambda dt: setattr(self, 'total_items', 1), 0
                    )
                    print(f"📊 Video Title: {info.get('title', 'Unknown')}")

                print("-" * 60)
                print("⬇️  Starting download...")
                ydl.download([self.url_text])

            print("-" * 60)
            print("✅ Download process completed successfully!")
            print("=" * 60 + "\n")

            Clock.schedule_once(lambda dt: self.on_download_success(), 0)

        except yt_dlp.utils.DownloadError as e:
            error_msg = str(e)

            print("\n" + "=" * 60)
            print("❌ DOWNLOAD ERROR")
            print("=" * 60)
            print(f"Error: {error_msg}")
            print("=" * 60 + "\n")

            if 'Video unavailable' in error_msg:
                Clock.schedule_once(
                    lambda dt: self.on_download_error('Video is unavailable or private'),
                    0,
                )
            elif 'No video formats' in error_msg:
                Clock.schedule_once(
                    lambda dt: self.on_download_error('Selected quality not available'),
                    0,
                )
            else:
                Clock.schedule_once(
                    lambda dt: self.on_download_error('Download failed. Check URL'),
                    0,
                )

        except Exception as e:
            error_message = f'Error: {str(e)[:50]}'

            print("\n" + "=" * 60)
            print("❌ UNEXPECTED ERROR")
            print("=" * 60)
            print(f"Error Type: {type(e).__name__}")
            print(f"Error Message: {e}")
            print("=" * 60 + "\n")

            Clock.schedule_once(
                lambda dt: self.on_download_error(error_message), 0
            )

    
    def on_download_success(self):
        """Handle successful download"""
        self.is_loading = False
        self.error_message = ''
        
        file_type = 'Audio' if self.audio_only else 'Video'
        folder = 'Audio' if self.audio_only else 'Video'
        folder_path = self.audio_path if self.audio_only else self.video_path
        
        print("\n" + "🎉"*30)
        print("✅ DOWNLOAD COMPLETED SUCCESSFULLY!")
        print("🎉"*30)
        
        if self.total_items > 1:
            self.success_message = f'✓ {self.total_items} items downloaded to {folder} folder'
            print(f"📦 Total Items Downloaded: {self.total_items}")
        else:
            self.success_message = f'✓ {file_type} downloaded to {folder} folder'
            print(f"📦 {file_type} Downloaded: 1 file")
        
        print(f"📁 Location: {folder_path}")
        print("="*60 + "\n")
        
        self.url_text = ''
        self.ids.url_input.text = ''
        
        # Reset progress
        self.download_progress = 0
        self.current_item = ''
        
        Clock.schedule_once(lambda dt: self.clear_success(), 7)
    def on_download_error(self, error):
        """Handle download error"""
        self.is_loading = False
        self.error_message = error
        self.success_message = ''
        
        print("\n" + "⚠️ "*30)
        print(f"Error displayed to user: {error}")
        print("⚠️ "*30 + "\n")
    
    def clear_success(self):
        """Clear success message"""
        self.success_message = ''


class YouTubeDownloaderApp(App):
    """Main Kivy Application"""
    
    def build(self):
        self.title = 'YouTube Downloader'
        Builder.load_file('design.kv')
        return YouTubeDownloader()


if __name__ == '__main__':
    YouTubeDownloaderApp().run()