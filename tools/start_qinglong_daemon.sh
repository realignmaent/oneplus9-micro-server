#!/data/data/com.termux/files/usr/bin/bash
# OnePlus 9 移动微服务器统一守护进程 (Self-Healing Daemon)

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
    echo "[$(date)] 启动 DeepSeek-R1 本地推理服务..."
    nohup proot-distro login debian -- bash -c 'llama-server -m /ql/data/models/deepseek-r1-1.5b-q4_k_m.gguf --host 0.0.0.0 --port 8080 -c 2048 -t 4 --alias DeepSeek-R1-1.5B,deepseek-r1-1.5b,qwen2.5-3b' > /data/data/com.termux/files/home/llama_server.log 2>&1 &
fi

# 5. 检查微服务器统一控制台 dashboard.py 是否已启动，若未启动则拉起 (端口 5701)
if ! pgrep -f "dashboard.py" > /dev/null; then
    echo "[$(date)] 启动微服务器统一控制台 (5701)..."
    nohup python /data/data/com.termux/files/home/dashboard.py > /data/data/com.termux/files/home/dashboard.log 2>&1 &
fi

# 6. 检查 WorkBuddy 上游网关 wb2api 是否已启动，若未启动则拉起 (端口 7863)
if ! pgrep -f "wb2api" > /dev/null; then
    echo "[$(date)] 启动 WorkBuddy 上游网关 (7863)..."
    nohup proot-distro login debian -- bash -c 'cd /opt/workbuddy-manager/upstream && ./wb2api -config config.json' > /data/data/com.termux/files/home/wb2api.log 2>&1 &
fi

# 7. 检查 WorkBuddy Web 管理端是否已启动，若未启动则拉起 (端口 7864)
if ! pgrep -f "server.main:app" > /dev/null; then
    echo "[$(date)] 启动 WorkBuddy 管理面板 (7864)..."
    nohup proot-distro login debian -- bash -c 'cd /opt/workbuddy-manager && python3 -m uvicorn server.main:app --host 0.0.0.0 --port 7864 --env-file .env' > /data/data/com.termux/files/home/manager.log 2>&1 &
fi

# 8. 检查端侧 AI 公网网关与安全隧道是否已启动，若未启动则拉起 (端口 8081)
if ! pgrep -f "public_ai_gateway.py" > /dev/null; then
    echo "[$(date)] 启动端侧 AI 公网安全网关 (8081)..."
    bash /data/data/com.termux/files/home/start_public_ai.sh > /dev/null 2>&1 &
fi
