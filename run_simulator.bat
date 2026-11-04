@echo off
cd /d "%~dp0"
rem Simulatore di Oracle: senza argomenti esegue gli scenari; con --gui apre la finestra di JT sul database simulato.
.venv\Scripts\python.exe tools\simulate.py %*
if "%~1"=="" pause
