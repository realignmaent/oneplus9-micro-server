#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一加 9 端侧大模型公网安全气囊网关 (Public AI Streaming Gateway)
架构：
  1. 完整反代官方原生 llama-server WebUI (具备左侧历史边栏、Token吞吐速率统计、消息操作栏)
  2. 深度支持 SSE (Server-Sent Events) 逐字流式打字机输出
  3. 第一道防线：Cookie 免登录暗号门禁 (默认 888，100% 阻断全网爬虫扫描)
  4. 第二道防线：45°C 电池温控熔断器
  5. 第三道防线：单并发排队锁 (Lock=1)，坚决杜绝多任务并发榨干 CPU
"""

import os
import sys
import json
import time
import http.client
import urllib.parse
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
import threading

PORT = int(os.environ.get("GATEWAY_PORT", 8081))
BACKEND_HOST = os.environ.get("LLM_HOST", "127.0.0.1")
BACKEND_PORT = int(os.environ.get("LLM_PORT", 8080))
ACCESS_CODE = os.environ.get("ACCESS_CODE", "888").strip()
MAX_TEMP_CELSIUS = float(os.environ.get("MAX_TEMP_CELSIUS", 45.0))

inference_lock = threading.Lock()

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

AUTH_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>OnePlus 9 · 访问验证</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
      background: linear-gradient(135deg, #0f172a 0%, #1e293b 100%);
      color: #f8fafc;
      height: 100vh;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 20px;
    }
    .card {
      background: rgba(30, 41, 59, 0.7);
      backdrop-filter: blur(20px);
      border: 1px solid rgba(255, 255, 255, 0.1);
      border-radius: 20px;
      padding: 32px 28px;
      width: 100%;
      max-width: 380px;
      text-align: center;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
    }
    .icon {
      font-size: 42px;
      margin-bottom: 16px;
      display: inline-block;
      animation: pulse 2s infinite ease-in-out;
    }
    @keyframes pulse {
      0%, 100% { transform: scale(1); }
      50% { transform: scale(1.08); }
    }
    h2 {
      font-size: 20px;
      font-weight: 700;
      margin-bottom: 8px;
      letter-spacing: -0.5px;
    }
    p {
      font-size: 13px;
      color: #94a3b8;
      line-height: 1.6;
      margin-bottom: 24px;
    }
    .badge {
      display: inline-block;
      background: rgba(59, 130, 246, 0.15);
      border: 1px solid rgba(59, 130, 246, 0.3);
      color: #60a5fa;
      padding: 4px 10px;
      border-radius: 20px;
      font-size: 11px;
      margin-bottom: 16px;
      font-weight: 500;
    }
    input {
      width: 100%;
      padding: 12px 16px;
      background: rgba(15, 23, 42, 0.6);
      border: 1px solid rgba(255, 255, 255, 0.15);
      border-radius: 12px;
      font-size: 16px;
      color: #fff;
      text-align: center;
      outline: none;
      margin-bottom: 18px;
      letter-spacing: 3px;
      transition: all 0.2s;
    }
    input:focus {
      border-color: #3b82f6;
      box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.25);
      background: rgba(15, 23, 42, 0.9);
    }
    button {
      width: 100%;
      padding: 12px;
      background: linear-gradient(135deg, #3b82f6 0%, #2563eb 100%);
      color: white;
      border: none;
      border-radius: 12px;
      font-size: 15px;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 4px 12px rgba(37, 99, 235, 0.3);
      transition: transform 0.1s, opacity 0.2s;
    }
    button:active {
      transform: scale(0.98);
      opacity: 0.9;
    }
    .err-msg {
      color: #f87171;
      font-size: 12px;
      margin-top: 12px;
      display: none;
    }
  </style>
</head>
<body>
  <div class="card">
    <div class="icon">✨</div>
    <h2>OnePlus 9 移动微服务器</h2>
    <div class="badge">高通骁龙 888 · Qwen2.5-3B 端侧脱机大模型</div>
    <p>这是好友专属的家庭手机端侧 AI 智能体<br/>请输入主人告知的访问暗号开启畅聊体验</p>
    <input type="password" id="passcode" placeholder="输入访问暗号" autocomplete="off" autofocus />
    <button onclick="doVerify()">开启对话</button>
    <div class="err-msg" id="err-text">暗号不正确，请向主人获取哦~</div>
  </div>

  <script>
    const input = document.getElementById('passcode');
    const errText = document.getElementById('err-text');

    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') doVerify();
    });

    async function doVerify() {
      const code = input.value.trim();
      if (!code) return;
      try {
        const res = await fetch('/api/op9_verify', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ code: code })
        });
        if (res.ok) {
          // 写入 Cookie 并秒级刷新页面进入官方原生高级界面
          document.cookie = "op9_code=" + encodeURIComponent(code) + "; path=/; max-age=2592000; SameSite=Lax";
          location.reload();
        } else {
          errText.style.display = 'block';
          input.value = '';
          input.focus();
        }
      } catch (e) {
        alert('连接异常: ' + e.message);
      }
    }
  </script>
</body>
</html>
"""

class PublicStreamingProxyHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def check_authenticated(self) -> bool:
        """检查请求是否携带合法暗号 (Cookie 或 Header 或 Query)"""
        # 1. 检查 Cookie
        cookies = self.headers.get("Cookie", "")
        if cookies:
            for item in cookies.split(";"):
                if "=" in item:
                    k, v = item.strip().split("=", 1)
                    if k == "op9_code" and urllib.parse.unquote(v) == ACCESS_CODE:
                        return True
        # 2. 检查 Header
        if self.headers.get("X-Access-Code") == ACCESS_CODE:
            return True
        # 3. 检查 Query 参数
        if "?" in self.path:
            qs = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            if qs.get("code", [""])[0].strip() == ACCESS_CODE:
                return True
        return False

    def send_auth_page(self):
        """返回好看的暗号验证门禁页面"""
        body = AUTH_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS, PUT, DELETE")
        self.end_headers()

    def do_GET(self):
        # 1. 检查暗号认证
        if not self.check_authenticated():
            # 根路径返回暗号门禁，静态资源与接口拦截 403
            clean_path = self.path.split("?")[0]
            if clean_path in ("/", "/index.html") or not "." in clean_path:
                self.send_auth_page()
            else:
                self.send_response(403)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(b'{"error": "Forbidden: Please authenticate via main page"}')
            return

        # 2. 认证通过，透明反向代理
        self.forward_to_backend("GET")

    def do_POST(self):
        # 校验暗号专用验证接口
        if self.path == "/api/op9_verify":
            content_length = int(self.headers.get("Content-Length", 0))
            body_raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                data = json.loads(body_raw.decode("utf-8"))
            except Exception:
                data = {}
            if data.get("code") == ACCESS_CODE:
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Set-Cookie", f"op9_code={urllib.parse.quote(ACCESS_CODE)}; Path=/; Max-Age=2592000; SameSite=Lax")
                self.end_headers()
                self.wfile.write(b'{"status": "ok"}')
            else:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error": "Invalid code"}')
            return

        # 检查暗号认证
        if not self.check_authenticated():
            self.send_response(403)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(b'{"error": "Forbidden: Access code required"}')
            return

        # 检查是否为大模型推理接口（需经过温控熔断与单并发锁保护）
        is_generation = any(self.path.startswith(p) for p in (
            "/chat/completions",
            "/v1/chat/completions",
            "/completion",
            "/infill"
        ))

        if is_generation:
            # 硬件温控熔断
            temp = get_battery_temp()
            if temp >= MAX_TEMP_CELSIUS:
                self.send_response(429)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                err_msg = json.dumps({"error": f"手机当前机身温度较暖 ({temp:.1f}°C)，专属小管家正在休息降温中，请稍等 1~2 分钟后再试~"}).encode("utf-8")
                self.wfile.write(err_msg)
                return

            # 单并发互斥锁（严格限制同时 1 个推理，保 CPU 稳定）
            acquired = inference_lock.acquire(timeout=60.0)
            if not acquired:
                self.send_response(503)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": "前方有小伙伴正在生成中，请稍候再试~"}).encode("utf-8"))
                return

            try:
                self.forward_to_backend("POST")
            finally:
                inference_lock.release()
        else:
            self.forward_to_backend("POST")

    def forward_to_backend(self, method: str):
        """将请求透明转发至 127.0.0.1:8080，完美支持 chunked 与 text/event-stream 流式输出"""
        try:
            conn = http.client.HTTPConnection(BACKEND_HOST, BACKEND_PORT, timeout=120)
            
            # 透传请求头
            req_headers = {}
            for k, v in self.headers.items():
                if k.lower() not in ("host", "content-length"):
                    req_headers[k] = v

            body = None
            if method in ("POST", "PUT", "PATCH"):
                content_length = int(self.headers.get("Content-Length", 0))
                if content_length > 0:
                    body = self.rfile.read(content_length)
                req_headers["Content-Length"] = str(len(body) if body else 0)

            conn.request(method, self.path, body=body, headers=req_headers)
            resp = conn.getresponse()

            # 回传状态与响应头
            self.send_response(resp.status)
            is_stream = False
            for k, v in resp.getheaders():
                if k.lower() in ("transfer-encoding", "connection"):
                    continue
                if "text/event-stream" in v.lower():
                    is_stream = True
                self.send_header(k, v)
            self.end_headers()

            # 边读边写：如果是 SSE 流式响应，逐块 flush，带来丝般顺滑的打字机输出
            if is_stream:
                while True:
                    chunk = resp.read(128)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        break
            else:
                while True:
                    chunk = resp.read(4096)
                    if not chunk:
                        break
                    try:
                        self.wfile.write(chunk)
                    except (BrokenPipeError, ConnectionResetError):
                        break
            conn.close()
        except Exception as e:
            try:
                self.send_response(502)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.end_headers()
                self.wfile.write(json.dumps({"error": f"Bad Gateway: {str(e)}"}).encode("utf-8"))
            except Exception:
                pass

def main():
    print(f"[*] 启动 OnePlus 9 官方 WebUI 流式全反代网关...")
    print(f"[*] 监听端口: {PORT} -> 后端: {BACKEND_HOST}:{BACKEND_PORT}")
    print(f"[*] 访问暗号: {ACCESS_CODE} | 温控阈值: {MAX_TEMP_CELSIUS}°C")
    server = ThreadingHTTPServer(("0.0.0.0", PORT), PublicStreamingProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] 正在停止网关服务...")
        server.server_close()

if __name__ == "__main__":
    main()
