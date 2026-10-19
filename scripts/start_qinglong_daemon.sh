#!/data/data/com.termux/files/usr/bin/bash
# 1. 锁住后台防止 CPU 深度休眠
termux-wake-lock

# 2. 宿主 crond 定时守护
if ! pgrep crond > /dev/null; then
    crond
fi

# 3. 检查青龙面板是否已启动，若未启动则拉起 (端口 5700)
if ! pgrep -f "static/build/app.js" > /dev/null; then
    echo "[$(date)] 启动青龙面板服务..."
    nohup proot-distro login debian -- bash -c 'cd /ql && export QL_DIR="/ql" && export QL_DATA_DIR="/ql/data" && export QlPort=5700 && export QL_SCHEDULER="node" && node static/build/app.js' > /data/data/com.termux/files/home/qinglong.log 2>&1 &
fi

# 4. 检查 Qwen2.5-3B llama-server 是否已启动，若未启动则拉起 (端口 8080)
if ! pgrep -f "llama-server" > /dev/null; then
    echo "[$(date)] 启动 Qwen2.5-3B 本地推理服务..."
    nohup proot-distro login debian -- bash -c 'llama-server -m /ql/data/models/qwen2.5-3b-instruct-q4_k_m.gguf --host 0.0.0.0 --port 8080 -c 2048 -t 4 --alias qwen2.5-3b' > /data/data/com.termux/files/home/llama_server.log 2>&1 &
fi

# 5. 检查手机实时性能监控看板 dashboard.py 是否已启动，若未启动则拉起 (端口 5701)
if ! pgrep -f "dashboard.py" > /dev/null; then
    echo "[$(date)] 启动手机性能监控看板服务 (5701)..."
    nohup proot-distro login debian -- bash -c 'python3 /ql/data/scripts/dashboard.py' > /data/data/com.termux/files/home/dashboard.log 2>&1 &
fi
