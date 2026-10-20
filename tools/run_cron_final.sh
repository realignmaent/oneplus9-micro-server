#!/data/data/com.termux/files/usr/bin/bash
proot-distro login debian -- bash -c 'cp /sdcard/workbuddy/workbuddy_cron.py /ql/data/scripts/workbuddy/workbuddy_cron.py && cd /ql && task workbuddy/workbuddy_cron.py' > /sdcard/workbuddy/ai_cron_final.log 2>&1
echo "=== FINISHED ===" >> /sdcard/workbuddy/ai_cron_final.log
