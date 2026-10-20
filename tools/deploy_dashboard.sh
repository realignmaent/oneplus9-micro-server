#!/data/data/com.termux/files/usr/bin/bash
# 1. 复制最新 dashboard.py 到容器
proot-distro login debian -- bash -c 'cp /sdcard/workbuddy/dashboard.py /ql/data/scripts/dashboard.py && chmod +x /ql/data/scripts/dashboard.py'

# 2. 复制最新守护脚本
cp /sdcard/workbuddy/start_qinglong_daemon.sh ~/start_qinglong_daemon.sh
chmod +x ~/start_qinglong_daemon.sh

# 3. 执行守护拉起看板
bash ~/start_qinglong_daemon.sh

sleep 2

# 4. 测试看板接口
curl -s http://127.0.0.1:5701/api/metrics > /sdcard/workbuddy/dashboard_test.json
echo "Dashboard deployment finished!"
