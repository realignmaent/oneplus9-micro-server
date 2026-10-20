#!/data/data/com.termux/files/usr/bin/bash
# 1. 复制守护脚本并运行
cp /sdcard/workbuddy/start_qinglong_daemon.sh ~/start_qinglong_daemon.sh
chmod +x ~/start_qinglong_daemon.sh
bash ~/start_qinglong_daemon.sh

# 2. 复制最新 workbuddy_cron.py 到青龙容器
proot-distro login debian -- bash -c 'cp /sdcard/workbuddy/workbuddy_cron.py /ql/data/scripts/workbuddy/workbuddy_cron.py'

# 3. 等待 llama-server 启动就绪 (最多15秒)
echo "正在等待本地大模型服务就绪..."
for i in {1..15}; do
    if curl -s http://127.0.0.1:8080/health | grep -q "ok"; then
        echo "Llama-server 已就绪！"
        break
    fi
    sleep 1
done

# 4. 执行青龙打卡任务，并将日志输出到 /sdcard/workbuddy/ai_cron_test.log
echo "开始运行带有端侧AI寄语的打卡任务..."
proot-distro login debian -- bash -c 'cd /ql && task workbuddy/workbuddy_cron.py' > /sdcard/workbuddy/ai_cron_test.log 2>&1
echo "任务执行完毕，结果已保存至 /sdcard/workbuddy/ai_cron_test.log"
