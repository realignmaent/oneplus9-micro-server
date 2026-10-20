@echo off
setlocal
set TARGET_IP=192.168.31.172
set TARGET_PORT=5555

echo [1/3] Checking ADB...
set "PATH=E:\adb\platform-tools;%PATH%"

echo [2/3] Connecting to %TARGET_IP%:%TARGET_PORT% ...
adb connect %TARGET_IP%:%TARGET_PORT%

echo.
echo [3/3] Current ADB devices:
echo ----------------------------------------
adb devices
echo ----------------------------------------
echo.
echo If you see "%TARGET_IP%:%TARGET_PORT% device", Wireless ADB is ready!
echo You can now disconnect the USB cable.
echo.
pause
