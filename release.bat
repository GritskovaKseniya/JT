@echo off
rem Crea il pacchetto per i colleghi: test, costruzione, firma, controlli. Vedi RILASCIO.md.
cd /d "%~dp0"
.venv\Scripts\python.exe tools\release.py %*
echo.
pause
