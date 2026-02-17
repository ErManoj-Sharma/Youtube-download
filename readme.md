# Setup Guide
### Always use python 3.11 for build

## to build apk
create a venv "buildozer-venv" and activate it
```
python3.11 -m venv buildozer-venv
source buildozer-venv/bin/activate
```
Install buildozer and dependencies
```pip install --upgrade pip
pip install buildozer 
```
```
pip install appdirs==1.4.4 build==1.4.0 buildozer==1.5.0 colorama==0.4.6 \
Cython==0.29.36 distlib==0.4.0 filelock==3.21.2 Jinja2==3.1.6 \
MarkupSafe==3.0.3 meson==1.10.1 ninja==1.13.0 packaging==26.0 \
pexpect==4.9.0 platformdirs==4.7.0 ptyprocess==0.7.0 \
pyproject_hooks==1.2.0 setuptools==82.0.0 sh==1.14.3 toml==0.10.2 \
tomli==2.4.0 typing_extensions==4.15.0 virtualenv==20.36.1 wheel==0.43.0

```
Then run the following command to build the apk
```
buildozer android clean
buildozer -v android debug
```
This will create a debug apk in the bin directory. You can find the apk at `bin/YoutubeDownloader-0.1-debug.apk`    

## To fix ffmpeg
we use python for android ffmpeg recepie , by this we directly enable ffmpeg in android
```
https://github.com/kivy/python-for-android/tree/develop/pythonforandroid/recipes/ffmpeg
```