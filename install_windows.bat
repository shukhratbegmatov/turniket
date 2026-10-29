@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo === 1. Kutubxonalar o'rnatilmoqda ===
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo XATO: Python topilmadi yoki pip ishlamadi. python.org dan Python o'rnating.
    pause
    exit /b 1
)

echo.
echo === 2. ЕЭСБО ulanishi tekshirilmoqda ===
python turnstile_gateway.py --test-api

echo.
echo === 3. Windows yoqilganda avtomatik ishga tushirish ===
schtasks /create /tn "TurniketShlyuz" /tr "\"%~dp0start.bat\"" /sc onlogon /rl highest /f
if errorlevel 1 (
    echo Avtomatik ishga tushirish qo'shilmadi. Bu faylni "Run as administrator" bilan oching.
) else (
    echo Tayyor: kompyuter yoqilib, foydalanuvchi kirganda shlyuz o'zi ishga tushadi.
)

echo.
pause
