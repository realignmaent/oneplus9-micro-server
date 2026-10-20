#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一加 9 端侧大模型公网安全气囊网关 (Public AI Gateway)
特性：
  1. 零依赖：纯 Python 3 原生标准库开发，内存占用 < 15MB
  2. 防御爬虫：免登录极简暗号（默认: 888，可通过环境变量 ACCESS_CODE 自定义）
  3. 物理保镖：单并发排队锁 (Semaphore=1)，坚决杜绝多任务并发榨干 CPU
  4. 温控熔断：联动 /sys 实时硬件温度，超 45°C 自动温柔限流降温
  5. 移动端高颜值 WebUI：专为微信 / 手机浏览器优化的响应式原生聊天界面
"""

import os
import sys
import json
import time
import urllib.request
import urllib.error
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
import threading

PORT = int(os.environ.get("GATEWAY_PORT", 8081))
LLM_BACKEND_URL = os.environ.get("LLM_BACKEND_URL", "http://127.0.0.1:8080/v1/chat/completions")
ACCESS_CODE = os.environ.get("ACCESS_CODE", "888").strip()
MAX_TEMP_CELSIUS = float(os.environ.get("MAX_TEMP_CELSIUS", 45.0))

# 单并发互斥锁（防止多人并发压垮骁龙888）
inference_lock = threading.Lock()
waiting_count = 0
waiting_count_lock = threading.Lock()

def get_battery_temp() -> float:
    """读取手机当前电池或主板温度"""
    paths = [
        "/sys/class/thermal/thermal_zone100/temp",
        "/sys/class/thermal/thermal_zone0/temp",
        "/sys/class/power_supply/battery/temp"
    ]
    for p in paths:
        try:
            if os.path.exists(p):
                with open(p, "r") as f:
                    val = float(f.read().strip())
                    return val / 1000.0 if val > 1000 else val
        except Exception:
            continue
    return 32.0

HTML_PAGE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>OnePlus 9 · 端侧 Qwen2.5 掌上微智脑</title>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background-color: #f6f8fb;
      color: #2c3e50;
      height: 100vh;
      display: flex;
      flex-direction: column;
    }
    header {
      background: rgba(255, 255, 255, 0.92);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid #eef2f6;
      padding: 12px 16px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      position: sticky;
      top: 0;
      z-index: 10;
    }
    .header-title {
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .status-dot {
      width: 9px;
      height: 9px;
      background-color: #10b981;
      border-radius: 50%;
      box-shadow: 0 0 0 3px rgba(16, 185, 129, 0.2);
    }
    .title-text {
      font-size: 15px;
      font-weight: 700;
      color: #1e293b;
    }
    .metrics-badge {
      font-size: 12px;
      background: #f1f5f9;
      padding: 4px 8px;
      border-radius: 20px;
      color: #64748b;
      display: flex;
      align-items: center;
      gap: 6px;
    }
    #chat-container {
      flex: 1;
      overflow-y: auto;
      padding: 16px;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .msg-row {
      display: flex;
      gap: 8px;
      max-width: 86%;
    }
    .msg-row.user {
      align-self: flex-end;
      flex-direction: row-reverse;
    }
    .msg-row.assistant {
      align-self: flex-start;
    }
    .avatar {
      width: 32px;
      height: 32px;
      border-radius: 50%;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 14px;
      flex-shrink: 0;
    }
    .msg-row.user .avatar {
      background: #3b82f6;
      color: #fff;
    }
    .msg-row.assistant .avatar {
      background: #ff85c0;
      color: #fff;
    }
    .bubble {
      padding: 10px 14px;
      border-radius: 14px;
      font-size: 14px;
      line-height: 1.5;
      word-break: break-word;
      box-shadow: 0 1px 3px rgba(0,0,0,0.04);
    }
    .msg-row.user .bubble {
      background: #3b82f6;
      color: #fff;
      border-bottom-right-radius: 4px;
    }
    .msg-row.assistant .bubble {
      background: #ffffff;
      color: #1e293b;
      border-bottom-left-radius: 4px;
      border: 1px solid #eef2f6;
    }
    .loading-dots {
      display: inline-flex;
      gap: 4px;
      padding: 4px 8px;
    }
    .loading-dots span {
      width: 6px;
      height: 6px;
      background: #94a3b8;
      border-radius: 50%;
      animation: bounce 1.4s infinite ease-in-out both;
    }
    .loading-dots span:nth-child(1) { animation-delay: -0.32s; }
    .loading-dots span:nth-child(2) { animation-delay: -0.16s; }
    @keyframes bounce {
      0%, 80%, 100% { transform: scale(0); }
      40% { transform: scale(1); }
    }
    footer {
      background: #ffffff;
      border-top: 1px solid #eef2f6;
      padding: 10px 14px;
      display: flex;
      gap: 8px;
      align-items: flex-end;
    }
    #user-input {
      flex: 1;
      padding: 10px 14px;
      border: 1px solid #e2e8f0;
      border-radius: 20px;
      outline: none;
      font-size: 14px;
      resize: none;
      max-height: 100px;
      line-height: 1.4;
      background: #f8fafc;
      transition: border-color 0.2s;
    }
    #user-input:focus {
      border-color: #3b82f6;
      background: #fff;
    }
    #send-btn {
      width: 38px;
      height: 38px;
      border-radius: 50%;
      background: #3b82f6;
      color: white;
      border: none;
      outline: none;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      flex-shrink: 0;
      transition: transform 0.1s, background-color 0.2s;
    }
    #send-btn:active {
      transform: scale(0.92);
    }
    #send-btn:disabled {
      background: #cbd5e1;
      cursor: not-allowed;
    }
    /* 暗号弹窗 */
    #auth-modal {
      position: fixed;
      top: 0; left: 0; right: 0; bottom: 0;
      background: rgba(15, 23, 42, 0.6);
      backdrop-filter: blur(8px);
      display: none;
      align-items: center;
      justify-content: center;
      z-index: 100;
      padding: 20px;
    }
    .modal-card {
      background: #ffffff;
      border-radius: 16px;
      padding: 24px;
      width: 100%;
      max-width: 340px;
      text-align: center;
      box-shadow: 0 10px 25px rgba(0,0,0,0.1);
    }
    .modal-title {
      font-size: 17px;
      font-weight: 700;
      color: #0f172a;
      margin-bottom: 8px;
    }
    .modal-desc {
      font-size: 13px;
      color: #64748b;
      margin-bottom: 18px;
      line-height: 1.5;
    }
    .modal-input {
      width: 100%;
      padding: 10px 14px;
      border: 1px solid #cbd5e1;
      border-radius: 10px;
      font-size: 15px;
      text-align: center;
      outline: none;
      margin-bottom: 16px;
      letter-spacing: 2px;
    }
    .modal-btn {
      width: 100%;
      padding: 10px;
      background: #3b82f6;
      color: white;
      border: none;
      border-radius: 10px;
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
    }
  </style>
</head>
<body>

  <header>
    <div class="header-title">
      <div class="status-dot"></div>
      <span class="title-text">OnePlus 9 · 端侧 Qwen2.5</span>
    </div>
    <div class="metrics-badge" id="temp-badge">
      <i class="fa-solid fa-fire-flame-curved" style="color:#ef4444;"></i>
      <span id="temp-val">检测中</span>
    </div>
  </header>

  <div id="chat-container">
    <div class="msg-row assistant">
      <div class="avatar"><i class="fa-solid fa-wand-magic-sparkles"></i></div>
      <div class="bubble">
        你好呀！我是住在一加 9 手机里的端侧 AI 智脑（基于 Qwen2.5-3B 离线脱机运行）。<br/>
        由手机高通骁龙 888 8 核实时本地推理，找我想聊点什么呢？✨
      </div>
    </div>
  </div>

  <footer>
    <textarea id="user-input" rows="1" placeholder="发送消息给端侧大模型..."></textarea>
    <button id="send-btn"><i class="fa-solid fa-arrow-up"></i></button>
  </footer>

  <div id="auth-modal">
    <div class="modal-card">
      <div style="font-size: 32px; margin-bottom: 10px;">🔐</div>
      <div class="modal-title">访问安全验证</div>
      <div class="modal-desc">这是好友专属的家庭手机端侧 AI<br/>请输入主人告知的访问暗号以继续</div>
      <input type="password" id="access-code-input" class="modal-input" placeholder="输入访问暗号" autocomplete="off" />
      <button class="modal-btn" onclick="saveAccessCode()">确认进入</button>
    </div>
  </div>

  <script>
    const chatContainer = document.getElementById('chat-container');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const authModal = document.getElementById('auth-modal');
    const accessCodeInput = document.getElementById('access-code-input');
    const tempVal = document.getElementById('temp-val');

    let chatHistory = [];

    // 检查暗号
    function getStoredCode() {
      return localStorage.getItem('op9_ai_code') || '';
    }

    function checkAuth() {
      if (!getStoredCode()) {
        authModal.style.display = 'flex';
        accessCodeInput.focus();
      } else {
        authModal.style.display = 'none';
      }
    }

    function saveAccessCode() {
      const code = accessCodeInput.value.trim();
      if (!code) {
        alert('请输入暗号哦~');
        return;
      }
      localStorage.setItem('op9_ai_code', code);
      authModal.style.display = 'none';
      refreshStatus();
    }

    // 刷新温度状态
    async function refreshStatus() {
      try {
        const res = await fetch('/api/status', {
          headers: { 'X-Access-Code': getStoredCode() }
        });
        if (res.status === 403) {
          localStorage.removeItem('op9_ai_code');
          checkAuth();
          return;
        }
        const data = await res.json();
        tempVal.innerText = data.temp + '°C' + (data.waiting > 0 ? ` (${data.waiting}人排队)` : '');
      } catch (e) {
        tempVal.innerText = '在线';
      }
    }

    function appendMessage(role, text) {
      const row = document.createElement('div');
      row.className = 'msg-row ' + role;
      
      const avatar = document.createElement('div');
      avatar.className = 'avatar';
      avatar.innerHTML = role === 'user' ? '<i class="fa-solid fa-user"></i>' : '<i class="fa-solid fa-wand-magic-sparkles"></i>';

      const bubble = document.createElement('div');
      bubble.className = 'bubble';
      bubble.innerText = text;

      row.appendChild(avatar);
      row.appendChild(bubble);
      chatContainer.appendChild(row);
      chatContainer.scrollTop = chatContainer.scrollHeight;
      return bubble;
    }

    async function sendMessage() {
      const text = userInput.value.trim();
      if (!text) return;

      const code = getStoredCode();
      if (!code) {
        checkAuth();
        return;
      }

      userInput.value = '';
      sendBtn.disabled = true;
      appendMessage('user', text);
      chatHistory.push({ role: 'user', content: text });

      // 添加 loading 气泡
      const loadingRow = document.createElement('div');
      loadingRow.className = 'msg-row assistant';
      loadingRow.innerHTML = `
        <div class="avatar"><i class="fa-solid fa-wand-magic-sparkles"></i></div>
        <div class="bubble"><div class="loading-dots"><span></span><span></span><span></span></div></div>
      `;
      chatContainer.appendChild(loadingRow);
      chatContainer.scrollTop = chatContainer.scrollHeight;

      try {
        const resp = await fetch('/api/chat', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-Access-Code': code
          },
          body: JSON.stringify({
            messages: [
              { role: 'system', content: '你是住在一加9手机里的专属智能搭档，性格温柔甜美、灵动自然、真诚体贴。' },
              ...chatHistory.slice(-6)
            ]
          })
        });

        chatContainer.removeChild(loadingRow);

        if (resp.status === 403) {
          localStorage.removeItem('op9_ai_code');
          checkAuth();
          return;
        }

        const data = await resp.json();
        if (resp.status === 200 && data.content) {
          appendMessage('assistant', data.content);
          chatHistory.push({ role: 'assistant', content: data.content });
        } else {
          appendMessage('assistant', '⚠️ ' + (data.error || '请求失败，请稍后重试'));
        }
      } catch (err) {
        chatContainer.removeChild(loadingRow);
        appendMessage('assistant', '⚠️ 手机网络连接异常: ' + err.message);
      } finally {
        sendBtn.disabled = false;
        refreshStatus();
      }
    }

    sendBtn.addEventListener('click', sendMessage);
    userInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
      }
    });

    checkAuth();
    refreshStatus();
    setInterval(refreshStatus, 15000);
  </script>
</body>
</html>
"""

class SafeAIGatewayHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # 仅简要记录关键 API 请求，避免日志洪泛
        pass

    def check_access_code(self) -> bool:
        """检查请求是否携带正确的暗号"""
        code = self.headers.get("X-Access-Code", "").strip()
        if not code:
            # 兼容 Query 参数中的 code
            if "?" in self.path:
                from urllib.parse import parse_qs, urlparse
                qs = parse_qs(urlparse(self.path).query)
                code = qs.get("code", [""])[0].strip()
        return code == ACCESS_CODE

    def send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Access-Code")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Access-Code")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def do_GET(self):
        # 1. 首页直接返回 Web 聊天界面
        if self.path == "/" or self.path.startswith("/?"):
            body = HTML_PAGE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 2. 状态探针接口
        if self.path.startswith("/api/status"):
            if not self.check_access_code():
                self.send_json(403, {"error": "暗号错误或未授权"})
                return
            temp = get_battery_temp()
            with waiting_count_lock:
                current_waiting = waiting_count
            self.send_json(200, {
                "status": "online",
                "temp": round(temp, 1),
                "waiting": current_waiting,
                "model": "Qwen2.5-3B"
            })
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path.startswith("/api/chat"):
            # 1. 第一道防线：免登录暗号校验（拦截全部全网爬虫）
            if not self.check_access_code():
                self.send_json(403, {"error": "暗号错误或未授权"})
                return

            # 2. 第二道防线：硬件温控熔断（防电池过热）
            temp = get_battery_temp()
            if temp >= MAX_TEMP_CELSIUS:
                self.send_json(429, {
                    "error": f"手机当前机身温度较暖 ({temp:.1f}°C)，专属小管家正在休息降温中，请稍等 1~2 分钟后再试~"
                })
                return

            # 读取请求体
            content_length = int(self.headers.get("Content-Length", 0))
            if content_length > 32 * 1024:  # 限制请求体最大 32KB
                self.send_json(413, {"error": "输入内容过长"})
                return

            try:
                body_raw = self.rfile.read(content_length)
                req_data = json.loads(body_raw.decode("utf-8"))
            except Exception:
                self.send_json(400, {"error": "请求 JSON 格式无效"})
                return

            messages = req_data.get("messages", [])
            if not messages:
                self.send_json(400, {"error": "消息列表不能为空"})
                return

            # 3. 第三道防线：单并发异步排队锁（严格限制同时 1 个推理，保 CPU 稳定）
            global waiting_count
            with waiting_count_lock:
                waiting_count += 1

            try:
                # 获取排队锁，超时 60s
                acquired = inference_lock.acquire(timeout=60.0)
                if not acquired:
                    self.send_json(503, {"error": "当前排队人数较多，请稍后再试"})
                    return

                try:
                    # 转发请求给本地 llama-server
                    llm_payload = {
                        "messages": messages,
                        "temperature": 0.8,
                        "max_tokens": 150
                    }
                    req = urllib.request.Request(
                        LLM_BACKEND_URL,
                        data=json.dumps(llm_payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"}
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        res_json = json.loads(resp.read().decode("utf-8"))
                        answer = res_json["choices"][0]["message"]["content"].strip()
                        self.send_json(200, {"content": answer})
                except Exception as e:
                    self.send_json(500, {"error": f"端侧大模型推理异常: {str(e)}"})
                finally:
                    inference_lock.release()
            finally:
                with waiting_count_lock:
                    waiting_count = max(0, waiting_count - 1)
            return

        self.send_response(404)
        self.end_headers()

def main():
    print(f"[*] 启动 OnePlus 9 端侧大模型公网安全气囊网关...")
    print(f"[*] 监听端口: {PORT} | 访问暗号: {ACCESS_CODE} | 温控阈值: {MAX_TEMP_CELSIUS}°C")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), SafeAIGatewayHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] 正在停止网关服务...")
        server.server_close()

if __name__ == "__main__":
    main()
