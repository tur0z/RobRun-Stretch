@echo off
rem Builds a single RobRunResolutionTool.exe into .\dist
cd /d "%~dp0"
python -m pip install -r requirements.txt pyinstaller || exit /b 1
python -m PyInstaller --noconfirm --onefile --windowed --name RobRunResolutionTool ^
    --add-data "assets;assets" --icon "assets\icon.ico" ^
    --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.Qt3DCore ^
    main.py || exit /b 1
echo.
echo Done: dist\RobRunResolutionTool.exe
