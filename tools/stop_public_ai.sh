#!/data/data/com.termux/files/usr/bin/bash
# 停止公网共享通道
pkill -f "public_ai_gateway.py" 2>/dev/null
pkill -f "cloudflared tunnel" 2>/dev/null
echo "已安全关闭公网共享通道与安全气囊网关。"
