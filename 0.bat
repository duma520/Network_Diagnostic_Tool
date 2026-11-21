cls
rmdir /s /q build
rmdir /s /q dist

pyinstaller --windowed  --noconfirm  --icon=icon.ico --add-data "icon.ico;." Network_Diagnostic_Tool.py