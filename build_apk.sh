#!/bin/bash
# Build runner — builds the Android debug APK
set -e
cd /home/manoj/tools/Youtube-download

source buildozer-venv/bin/activate

export JAVA_HOME=/home/manoj/.local/share/mise/installs/java/17
export PATH="$JAVA_HOME/bin:$PATH"

export ANDROIDSDK="$HOME/.buildozer/android/platform/android-sdk"
export ANDROIDNDK="$HOME/.buildozer/android/platform/android-ndk-r25b"
export ANDROIDAPI=33
export ANDROIDMINAPI=21

echo "=== Build started: $(date) ==="
echo "Python: $(python --version 2>&1)"
echo "JAVA_HOME: $JAVA_HOME"
echo "ping p4a download host"
curl -sI --max-time 15 https://www.ffmpeg.org/releases/ffmpeg-8.0.1.tar.xz | head -1 || echo "curl failed"

exec buildozer -v android debug 2>&1