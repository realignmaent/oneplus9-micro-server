@echo off
setlocal
set TARGET_IP=192.168.31.172
set TARGET_PORT=5555

set "PATH=E:\adb\platform-tools;%PATH%"

echo [1/3] Enabling TCP mode on port %TARGET_PORT% via USB...
adb tcpip %TARGET_PORT%

if %errorlevel% neq 0 (
    echo [ERROR] Failed to enable TCP mode. Please ensure phone is connected via USB.
    pause
    exit /b %errorlevel%
)

echo.
echo [2/3] Waiting 2 seconds then connecting to %TARGET_IP%:%TARGET_PORT% ...
timeout /t 2 /nobreak >nul
adb connect %TARGET_IP%:%TARGET_PORT%

echo.
echo [3/3] Current ADB devices:
echo ----------------------------------------
adb devices
echo ----------------------------------------
echo.
echo Wireless ADB is enabled! You can now unplug the USB cable.
echo.
pause
