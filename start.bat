@echo off
chcp 65001 >nul
title Turniket shlyuzi (EESBO)
cd /d "%~dp0"

:loop
echo [%date% %time%] Shlyuz ishga tushmoqda...
python turnstile_gateway.py
echo [%date% %time%] Shlyuz to'xtadi, 5 soniyadan keyin qayta ishga tushadi...
timeout /t 5 /nobreak >nul
goto loop
