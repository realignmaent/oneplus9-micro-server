#!/data/data/com.termux/files/usr/bin/bash
proot-distro login debian -- bash -c 'cd /ql && task thermal_guard.py' > /sdcard/workbuddy/thermal_task_run.log 2>&1
