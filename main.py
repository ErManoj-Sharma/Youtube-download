"""
YouTube Downloader - Kivy Application
Main application file
"""

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.popup import Popup
from kivy.clock import Clock
from kivy.properties import StringProperty, BooleanProperty, ObjectProperty
from urllib.parse import urlparse
import threading
import time

# Optional: Import yt-dlp for actual downloading
# Uncomment when ready to implement real downloads
# import yt_dlp


class YouTubeDownloader(BoxLayout):
    """Main widget for YouTube Downloader"""
    
    url_text = StringProperty('')
    quality_selected = StringProperty('max')
    audio_only = BooleanProperty(False)
    is_loading = BooleanProperty(False)
    error_message = StringProperty('')
    success_message = StringProperty('')
    
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
    
    def validate_url(self, url):
        """Validate if the URL is a valid YouTube URL"""
        if not url.strip():
            return False
        try:
            parsed = urlparse(url)
            return 'youtube.com' in parsed.netloc or 'youtu.be' in parsed.netloc
        except:
            return False
    
    def on_paste_click(self):
        """Handle paste button click"""
        try:
            # Kivy doesn't have direct clipboard access
            # This is a placeholder - you'll need to use platform-specific code
            # or a library like pyperclip
            from kivy.core.clipboard import Clipboard
            text = Clipboard.paste()
            self.ids.url_input.text = text
            self.url_text = text
            self.error_message = ''
        except Exception as e:
            self.error_message = 'Unable to paste from clipboard'
    
    def on_url_change(self, text):
        """Handle URL input change"""
        self.url_text = text
        self.error_message = ''
    
    def on_quality_select(self, quality):
        """Handle quality selection"""
        if not self.audio_only:
            self.quality_selected = quality
    
    def on_audio_toggle(self, active):
        """Handle audio only toggle"""
        self.audio_only = active
    
    def start_download(self):
        """Start the download process"""
        self.error_message = ''
        self.success_message = ''
        
        # Validate URL
        if not self.validate_url(self.url_text):
            self.error_message = 'Please enter a valid YouTube URL'
            return
        
        self.is_loading = True
        
        # Run download in separate thread to avoid blocking UI
        thread = threading.Thread(target=self.download_video)
        thread.daemon = True
        thread.start()
    
    def download_video(self):
        """Download video (simulated for now)"""
        try:
            # Simulate download process
            time.sleep(2)
            
            # Schedule UI updates on main thread
            Clock.schedule_once(lambda dt: self.on_download_success(), 0)
            
            # Uncomment and implement actual download with yt-dlp:
            """
            ydl_opts = {
                'format': 'bestaudio/best' if self.audio_only else f'best[height<={self.quality_selected}]',
                'outtmpl': '%(title)s.%(ext)s',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }] if self.audio_only else [],
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.url_text])
            
            Clock.schedule_once(lambda dt: self.on_download_success(), 0)
            """
            
        except Exception as e:
            Clock.schedule_once(lambda dt: self.on_download_error(str(e)), 0)
    
    def on_download_success(self):
        """Handle successful download"""
        self.is_loading = False
        self.success_message = 'Download started successfully!'
        self.url_text = ''
        self.ids.url_input.text = ''
        
        # Clear success message after 3 seconds
        Clock.schedule_once(lambda dt: self.clear_success(), 3)
    
    def on_download_error(self, error):
        """Handle download error"""
        self.is_loading = False
        self.error_message = f'Failed to download: {error}'
    
    def clear_success(self):
        """Clear success message"""
        self.success_message = ''


class YouTubeDownloaderApp(App):
    """Main Kivy Application"""
    
    def build(self):
        self.title = 'YouTube Downloader'
        # Explicitly load the kv file
        from kivy.lang import Builder
        Builder.load_file('design.kv')
        return YouTubeDownloader()


if __name__ == '__main__':
    YouTubeDownloaderApp().run()