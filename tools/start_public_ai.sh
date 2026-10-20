#!/data/data/com.termux/files/usr/bin/bash
# OnePlus 9 端侧 AI 公网安全共享一键拉起脚本

DIR="$(cd "$(dirname "$0")" && pwd)"
GATEWAY_PY="$DIR/public_ai_gateway.py"
LOG_DIR="$DIR/logs"
mkdir -p "$LOG_DIR"

GATEWAY_LOG="$LOG_DIR/gateway.log"
CF_LOG="$LOG_DIR/cloudflared.log"

# 1. 停止既有进程
pkill -f "public_ai_gateway.py" 2>/dev/null
pkill -f "cloudflared tunnel" 2>/dev/null
sleep 1

# 2. 启动安全气囊网关 (:8081)
nohup python "$GATEWAY_PY" > "$GATEWAY_LOG" 2>&1 &
echo "[1/3] 安全气囊网关已在后台启动 (:8081)..."
sleep 1

# 3. 启动 Cloudflare Tunnel
rm -f "$CF_LOG"
nohup cloudflared tunnel --url http://127.0.0.1:8081 > "$CF_LOG" 2>&1 &
echo "[2/3] Cloudflare Tunnel 正在建立出站安全隧道..."

# 4. 轮询提取 trycloudflare 公网安全域名
echo "[3/3] 正在获取公网访问安全网址 (通常需 3~8 秒)..."
URL=""
for i in {1..20}; do
    sleep 1
    if [ -f "$CF_LOG" ]; then
        URL=$(grep -o 'https://[-a-zA-Z0-9@:%._\+~#=]*.trycloudflare.com' "$CF_LOG" | head -n 1)
        if [ -n "$URL" ]; then
            break
        fi
    fi
done

echo "=========================================================="
if [ -n "$URL" ]; then
    echo "🎉 恭喜！端侧 AI 公网安全共享通道已成功建立！"
    echo ""
    echo "🔗 公网访问网址: $URL"
    echo "🔑 默认访问暗号: 888"
    echo ""
    echo "可以直接将上面的网址发给朋友，朋友在微信/浏览器点开输入暗号即可开始畅聊！"
    echo "已开启【单并发防爆锁】与【45°C 电池温控熔断】，全网爬虫已被 100% 阻断。"
else
    echo "⚠️ 域名获取超时，请查看日志: cat $CF_LOG"
fi
echo "=========================================================="
