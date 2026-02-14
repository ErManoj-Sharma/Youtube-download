@echo off
echo Starting Simpler-FileBot in WSL...

wsl -d Ubuntu bash -lc "cd ~/tools/youtube-downloader && source venv/bin/activate && python3 main.py"

pause
