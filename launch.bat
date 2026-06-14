@echo off
title Qortium CLI
mode con cols=130 lines=45
cd /d "%~dp0"
"C:\Users\Itachi\AppData\Local\Programs\Python\Python312\python.exe" main.py
if errorlevel 1 pause
