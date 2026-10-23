#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OnePlus 9 双反代安全融合网关 (Dual Reverse-Proxy Security Gateway)
聚合两大上游服务：
  1. QoderGateway (:5050) -> 阿里通义千问、DeepSeek、智谱GLM、月之暗面Kimi、MiniMax (1M 上下文 + 极致推理)
  2. WorkBuddy (:7863)   -> GPT-6-Sol, Grok-4.7, Hy4-preview, 全球大模型
  3. 端侧脱机模型 (:8080) -> Qwen2.5-3B (备用)

安全防护机制：
  1. 严格白名单路由：仅放行 /v1/models, /v1/chat/completions 以及 /qoder/v1/*, /wb/v1/*
     绝不暴露 /console, /ui, /admin 等任何管理路径 (100% 403 阻断扫描)
  2. Bearer Token 虚拟化鉴权门禁：无有效 API Key 直接 401 丢弃，防扫描与爬虫
  3. 异常 IP 防刷封禁：连续 5 次鉴权失败封禁 10 分钟
  4. 手机 45°C 电池/主板温控保护：过热熔断返回 429，保护一加 9 硬件健康
  5. 纯客户端极简适配：完美兼容 cc-switch / CherryStudio / NextChat，支持流式 SSE 打字机输出
"""

import os
import sys
import json
import time
import ssl
import http.client
import urllib.parse

import gateway_tokens
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler
import threading
from collections import defaultdict

# 监听端口（对接 Cloudflare Tunnel 出站）
PORT = int(os.environ.get("GATEWAY_PORT", 8081))
# 局域网 HTTPS API 端口（只暴露 API 路径，管理面留在 :5050 回环）
LAN_HTTPS_PORT = int(os.environ.get("GATEWAY_HTTPS_PORT", 8082))
TLS_CERT_FILE = os.environ.get(
    "GATEWAY_CERT_FILE", "/data/data/com.termux/files/home/certs/cert.pem"
)
TLS_KEY_FILE = os.environ.get(
    "GATEWAY_KEY_FILE", "/data/data/com.termux/files/home/certs/key.pem"
)

# 上游内网端口与鉴权
# 凭据一律不入库：手机端由守护脚本注入 GATEWAY_QODER_KEY / GATEWAY_WB_KEY /
# GATEWAY_STATIC_KEYS（逗号分隔）。仓库这份是逻辑快照，与手机实跑副本仅差这几行常量。
QODER_HOST = "127.0.0.1"
QODER_PORT = 5050
QODER_KEY = os.environ.get("GATEWAY_QODER_KEY", "")

WB_HOST = "127.0.0.1"
WB_PORT = 7863
WB_KEY = os.environ.get("GATEWAY_WB_KEY", "test_key")

LOCAL_LLM_HOST = "127.0.0.1"
LOCAL_LLM_PORT = 8080

# 内部静态 Key（仅用户本人 Qoder Key）；朋友 Key 走 SQLite 哈希 token
STATIC_KEYS = {
    k.strip() for k in os.environ.get("GATEWAY_STATIC_KEYS", "").split(",") if k.strip()
}

MAX_TEMP_CELSIUS = float(os.environ.get("MAX_TEMP_CELSIUS", 45.0))

# 防火墙与限流数据结构
failed_attempts = defaultdict(list)  # ip -> list of timestamps
banned_ips = {}                      # ip -> ban_expiry_timestamp
request_history = defaultdict(list)  # ip -> list of timestamps
rate_lock = threading.Lock()

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


def is_ip_banned(client_ip: str) -> bool:
    now = time.time()
    with rate_lock:
        if client_ip in banned_ips:
            if now < banned_ips[client_ip]:
                return True
            else:
                del banned_ips[client_ip]
        return False


def record_failed_attempt(client_ip: str):
    now = time.time()
    with rate_lock:
        # 清理 5 分钟之前的记录
        failed_attempts[client_ip] = [t for t in failed_attempts[client_ip] if now - t < 300]
        failed_attempts[client_ip].append(now)
        if len(failed_attempts[client_ip]) >= 5:
            banned_ips[client_ip] = now + 600  # 封禁 10 分钟
            print(f"[WAF BAN] IP {client_ip} has been banned for 10 minutes due to 5 consecutive auth failures.")


def is_rate_limited(client_ip: str) -> bool:
    now = time.time()
    with rate_lock:
        request_history[client_ip] = [t for t in request_history[client_ip] if now - t < 60]
        if len(request_history[client_ip]) > 60:  # 60 req/min
            return True
        request_history[client_ip].append(now)
        return False


# Qoder 原生支持的典型模型前缀/集合
QODER_MODEL_HINTS = {
    "auto",
    "qwen3.8-max", "qwen3.8-flash", "qwen3.7-plus",
    "deepseek-v4-pro", "deepseek-flash",
    "glm-5.3", "glm-5.3-flash",
    "kimi-k3", "kimi-k2.8",
    "minimax-m3.1-flash"
}


class DualProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    client_usage_key = ""

    def get_client_ip(self) -> str:
        # 兼容 Cloudflare 边缘真实客户端 IP
        return self.headers.get("CF-Connecting-IP") or self.headers.get("X-Forwarded-For", "").split(",")[0].strip() or self.client_address[0]

    def verify_auth(self) -> bool:
        auth_header = self.headers.get("Authorization", "").strip()
        if not auth_header.startswith("Bearer "):
            return False
        token = auth_header[7:].strip()
        if token in STATIC_KEYS:
            self.client_usage_key = token
            return True
        ok, _, _ = gateway_tokens.verify_token(token, self.get_client_ip())
        if ok:
            # 只透传非敏感前缀，QoderGateway 用它做用量归因而不是上游鉴权
            self.client_usage_key = token[: gateway_tokens.PREFIX_LEN]
        return ok

    def make_conn(self, host: str, port: int, timeout: int):
        """QoderGateway 已在 :5050 启用 HTTPS；同机回环连接跳过证书校验。"""
        if host == QODER_HOST and port == QODER_PORT:
            return http.client.HTTPSConnection(
                host, port, timeout=timeout, context=ssl._create_unverified_context()
            )
        return http.client.HTTPConnection(host, port, timeout=timeout)

    def send_json(self, status_code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        # 跨域预检支持（cc-switch / WebUI 调用必须）
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Max-Age", "86400")
        self.end_headers()

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()

    def do_GET(self):
        client_ip = self.get_client_ip()

        # 1. 检查 IP 封禁
        if is_ip_banned(client_ip):
            self.send_json(403, {"error": "Your IP has been temporarily blocked due to repeated violations."})
            return

        # 2. 根路径保活诊断
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        if path == "" or path == "/health":
            self.send_json(200, {
                "service": "OnePlus 9 Dual Reverse-Proxy Gateway",
                "status": "online",
                "hardware": "Snapdragon 888 (12GB RAM)",
                "endpoints": {
                    "unified": "/v1",
                    "anthropic": "/v1/messages",
                    "qoder_direct": "/qoder/v1",
                    "workbuddy_direct": "/wb/v1"
                },
                "usage": "Configure API Base URL in cc-switch with Bearer Key."
            })
            return

        # 3. 路由收敛白名单检测：严禁访问 /console, /ui 等敏感后台
        is_qoder_models = path in ("/qoder/v1/models", "/qoder/models")
        is_wb_models = path in ("/wb/v1/models", "/wb/models")
        is_unified_models = path in ("/v1/models", "/models")

        if not (is_qoder_models or is_wb_models or is_unified_models):
            # 严格拦截所有扫描请求（如 /console, /ui, /admin, /.env 等）
            record_failed_attempt(client_ip)
            self.send_json(403, {"error": "Access Denied: Path not allowed by security policy."})
            return

        # 4. Bearer Key 鉴权门禁
        if not self.verify_auth():
            record_failed_attempt(client_ip)
            self.send_json(401, {
                "error": {
                    "code": "invalid_api_key",
                    "message": "Missing or invalid API key. Please check your Bearer token.",
                    "type": "invalid_request_error"
                }
            })
            return

        # 5. 限流检查
        if is_rate_limited(client_ip):
            self.send_json(429, {"error": "Rate limit exceeded. Please slow down."})
            return

        # 6. 分发处理模型列表
        if is_qoder_models:
            self.forward_single_models(QODER_HOST, QODER_PORT, QODER_KEY)
        elif is_wb_models:
            self.forward_single_models(WB_HOST, WB_PORT, WB_KEY)
        else:
            # 统一聚合模式：合并 Qoder 与 WorkBuddy 的所有可用模型
            self.handle_aggregated_models()

    def do_POST(self):
        client_ip = self.get_client_ip()

        # 1. 检查 IP 封禁
        if is_ip_banned(client_ip):
            self.send_json(403, {"error": "Your IP has been temporarily blocked."})
            return

        # 2. 路由收敛白名单检测
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        is_qoder_chat = path in ("/qoder/v1/chat/completions", "/qoder/chat/completions")
        is_wb_chat = path in ("/wb/v1/chat/completions", "/wb/chat/completions")
        is_unified_chat = path in ("/v1/chat/completions", "/chat/completions")
        is_anthropic = path in ("/v1/messages", "/qoder/v1/messages", "/qoder/messages")

        if not (is_qoder_chat or is_wb_chat or is_unified_chat or is_anthropic):
            record_failed_attempt(client_ip)
            self.send_json(403, {"error": "Access Denied: Path not allowed by security policy."})
            return

        # 3. Bearer Key 鉴权门禁
        if not self.verify_auth():
            record_failed_attempt(client_ip)
            self.send_json(401, {
                "error": {
                    "code": "invalid_api_key",
                    "message": "Missing or invalid API key.",
                    "type": "invalid_request_error"
                }
            })
            return

        # 4. 限流与温控安全检查
        if is_rate_limited(client_ip):
            self.send_json(429, {"error": "Rate limit exceeded."})
            return

        temp = get_battery_temp()
        if temp >= MAX_TEMP_CELSIUS:
            self.send_json(429, {
                "error": f"Device thermal protection active ({temp:.1f}°C >= {MAX_TEMP_CELSIUS}°C). Cooling down, please retry in 1 minute."
            })
            return

        # 5. 读取 Body
        try:
            content_length = int(self.headers.get("Content-Length", 0))
            raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
            body_json = json.loads(raw_body.decode("utf-8")) if raw_body else {}
        except Exception as e:
            self.send_json(400, {"error": f"Invalid JSON payload: {str(e)}"})
            return

        model_name = body_json.get("model", "").lower().strip()

        # 6. Anthropic Messages 透传（Qoder / Claude Code 第三方推理）
        if is_anthropic:
            self.stream_forward_chat(QODER_HOST, QODER_PORT, "/v1/messages", QODER_KEY, raw_body)
            return

        # 7. 确定目标后端与鉴权 Key
        if is_qoder_chat:
            target_host, target_port, target_key = QODER_HOST, QODER_PORT, QODER_KEY
            target_path = "/v1/chat/completions"
        elif is_wb_chat:
            target_host, target_port, target_key = WB_HOST, WB_PORT, WB_KEY
            target_path = "/v1/chat/completions"
        else:
            # 智能统一分流
            if any(k in model_name for k in ("qwen", "deepseek", "glm", "minimax")) or model_name in QODER_MODEL_HINTS:
                target_host, target_port, target_key = QODER_HOST, QODER_PORT, QODER_KEY
            elif model_name.startswith("cn:") or model_name.startswith("global:") or any(k in model_name for k in ("gpt", "grok", "hy", "step")):
                target_host, target_port, target_key = WB_HOST, WB_PORT, WB_KEY
            elif model_name == "qwen2.5-3b":
                target_host, target_port, target_key = LOCAL_LLM_HOST, LOCAL_LLM_PORT, ""
            else:
                # 默认走 QoderGateway
                target_host, target_port, target_key = QODER_HOST, QODER_PORT, QODER_KEY
            target_path = "/v1/chat/completions"

        # 7. 透传请求并流式实时写回
        self.stream_forward_chat(target_host, target_port, target_path, target_key, raw_body)

    def forward_single_models(self, host: str, port: int, key: str):
        """转发单个后端的 /v1/models 接口"""
        try:
            conn = self.make_conn(host, port, 10)
            headers = {"Authorization": f"Bearer {key}"} if key else {}
            conn.request("GET", "/v1/models", headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            conn.close()

            self.send_response(resp.status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        except Exception as e:
            self.send_json(502, {"error": f"Failed to fetch models from backend: {str(e)}"})

    def handle_aggregated_models(self):
        """聚合返回 Qoder 与 WorkBuddy 的全量模型列表"""
        all_models = []
        seen_ids = set()

        # 1. 抓取 QoderGateway 模型
        try:
            conn = self.make_conn(QODER_HOST, QODER_PORT, 5)
            conn.request("GET", "/v1/models", headers={"Authorization": f"Bearer {QODER_KEY}"})
            resp = conn.getresponse()
            if resp.status == 200:
                q_data = json.loads(resp.read().decode("utf-8"))
                for m in q_data.get("data", []):
                    m_id = m.get("id")
                    if m_id and m_id not in seen_ids:
                        seen_ids.add(m_id)
                        all_models.append(m)
            conn.close()
        except Exception as e:
            print(f"[WARN] Aggregator failed to fetch Qoder models: {e}")

        # 2. 抓取 WorkBuddy 模型
        try:
            conn2 = http.client.HTTPConnection(WB_HOST, WB_PORT, timeout=5)
            conn2.request("GET", "/v1/models", headers={"Authorization": f"Bearer {WB_KEY}"})
            resp2 = conn2.getresponse()
            if resp2.status == 200:
                wb_data = json.loads(resp2.read().decode("utf-8"))
                for m in wb_data.get("data", []):
                    m_id = m.get("id")
                    if m_id and m_id not in seen_ids:
                        seen_ids.add(m_id)
                        all_models.append(m)
            conn2.close()
        except Exception as e:
            print(f"[WARN] Aggregator failed to fetch WorkBuddy models: {e}")

        payload = {
            "object": "list",
            "data": all_models
        }
        self.send_json(200, payload)

    def stream_forward_chat(self, host: str, port: int, path: str, key: str, body: bytes):
        """向目标后端转发 POST 对话，支持实时 SSE 逐块打字机输出"""
        try:
            conn = self.make_conn(host, port, 180)
            req_headers = {
                "Content-Type": "application/json",
                "Accept": self.headers.get("Accept", "*/*"),
                "Content-Length": str(len(body)),
            }
            if key:
                req_headers["Authorization"] = f"Bearer {key}"
            if self.client_usage_key:
                req_headers["X-Qoder-Usage-Key"] = self.client_usage_key

            conn.request("POST", path, body=body, headers=req_headers)
            resp = conn.getresponse()

            self.send_response(resp.status)
            is_sse = False
            for k, v in resp.getheaders():
                kl = k.lower()
                if kl in ("transfer-encoding", "connection"):
                    continue
                if "text/event-stream" in v.lower():
                    is_sse = True
                self.send_header(k, v)
            
            if is_sse or not resp.getheader("Content-Length"):
                self.send_header("Connection", "close")
                self.close_connection = True

            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "*")
            self.end_headers()

            # 边读边刷：若是 SSE 流式，逐 64 字节 flush，保证极佳打字机体验
            chunk_size = 64 if is_sse else 4096
            while True:
                chunk = resp.read(chunk_size)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                    if is_sse:
                        self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    break
            conn.close()
            try:
                self.wfile.flush()
            except Exception:
                pass
            # TLS 流式响应结束时完成 close_notify 握手，避免客户端把正常收尾判为网络错误
            if isinstance(self.connection, ssl.SSLSocket):
                try:
                    self.connection.settimeout(2)
                    self.connection.unwrap()
                except Exception:
                    pass
        except Exception as e:
            try:
                self.send_json(502, {"error": f"Upstream connection failed: {str(e)}"})
            except Exception:
                pass


def main():
    print("=" * 60)
    print(f"[*] 启动 OnePlus 9 双反代安全融合网关 (127.0.0.1:{PORT})")
    print(f"[*] 聚合上游: QoderGateway (:5050, HTTPS) & WorkBuddy (:7863)")
    print("[*] 安全策略: 仅放行 /v1 API，严禁暴露 /console 与管理路径")
    print("=" * 60)
    gateway_tokens.init_db()
    print("[*] Token 鉴权: SQLite 哈希存储 (可吊销/可审计)")
    http_server = ThreadingHTTPServer(("127.0.0.1", PORT), DualProxyHandler)
    https_server = None
    if os.path.exists(TLS_CERT_FILE) and os.path.exists(TLS_KEY_FILE):
        try:
            https_server = ThreadingHTTPServer(("0.0.0.0", LAN_HTTPS_PORT), DualProxyHandler)
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(certfile=TLS_CERT_FILE, keyfile=TLS_KEY_FILE)
            https_server.socket = context.wrap_socket(https_server.socket, server_side=True)
            threading.Thread(target=https_server.serve_forever, daemon=True).start()
            print(f"[*] 局域网 HTTPS API: https://0.0.0.0:{LAN_HTTPS_PORT}")
        except Exception as exc:
            print(f"[!] 局域网 HTTPS 启动失败: {exc}")
    else:
        print(f"[!] 未找到证书，局域网 HTTPS 未启用: {TLS_CERT_FILE}")
    try:
        http_server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] 网关正在安全停止...")
        http_server.server_close()
        if https_server is not None:
            https_server.server_close()


if __name__ == "__main__":
    main()
