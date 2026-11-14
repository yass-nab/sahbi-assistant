@echo off
title Sahbi - Gmail setup
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (set PY=.venv\Scripts\python.exe) else (set PY=..\.venv\Scripts\python.exe)
"%PY%" setup_email.py
