#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一加 9 (LE2110) 移动微服务器一体化控制台 (Mobile Micro-Server Console)
融合方案：Supervisor 工业级服务生命周期管理 + 原生硬件性能全景遥测
功能：
  1. 硬件遥测：高通骁龙 888 8 核独立频率、4 区硬件热度矩阵、12GB 物理内存与 ZRAM 动态水位
  2. 微服务管理中枢 (Supervisor 风格)：
     - 青龙自动化面板 (:5700)
     - 端侧大模型 llama-server (:8080)
     - WorkBuddy 管理端 (:7864)
     - wb2api 网关核心 (:7863)
     - 公网安全共享网关 (:8081)
  3. 生命周期控制：一键启动 (Start)、停止 (Stop)、平滑重启 (Restart)、一键全员自愈
  4. 实时日志终端：查看指定服务的最新运行日志与输出回显
  5. 零重型依赖：基于 Python 标准库，内存占用 < 20MB
"""

import os
import sys
import glob
import time
import json
import socket
import subprocess
import threading
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, ThreadingHTTPServer, BaseHTTPRequestHandler

PORT = 5701

HOME_DIR = "/data/data/com.termux/files/home"

MANAGED_SERVICES = {
    "qinglong": {
        "id": "qinglong",
        "name": "青龙自动化面板",
        "port": 5700,
        "category": "定时任务",
        "pattern": "static/build/app.js",
        "log_file": os.path.join(HOME_DIR, "qinglong.log"),
        "start_cmd": f"nohup proot-distro login debian -- bash -c 'cd /ql && export QL_DIR=\"/ql\" && export QL_DATA_DIR=\"/ql/data\" && export QlPort=5700 && export QL_SCHEDULER=\"node\" && node static/build/app.js' > {HOME_DIR}/qinglong.log 2>&1 &",
        "url": "http://192.168.31.172:5700"
    },
    "llama": {
        "id": "llama",
        "name": "Qwen2.5-3B 本地推理引擎",
        "port": 8080,
        "category": "端侧 AI",
        "pattern": "llama-server",
        "log_file": os.path.join(HOME_DIR, "llama_server.log"),
        "start_cmd": f"nohup proot-distro login debian -- bash -c 'llama-server -m /ql/data/models/qwen2.5-3b-instruct-q4_k_m.gguf --host 0.0.0.0 --port 8080 -c 2048 -t 4 --alias qwen2.5-3b' > {HOME_DIR}/llama_server.log 2>&1 &",
        "url": "http://192.168.31.172:8080"
    },
    "workbuddy": {
        "id": "workbuddy",
        "name": "WorkBuddy 管理控制台",
        "port": 7864,
        "category": "Web 后台",
        "pattern": "server.main:app",
        "log_file": os.path.join(HOME_DIR, "manager.log"),
        "start_cmd": f"nohup proot-distro login debian -- bash -c 'cd /opt/workbuddy-manager && python3 -m uvicorn server.main:app --host 0.0.0.0 --port 7864 --env-file .env' > {HOME_DIR}/manager.log 2>&1 &",
        "url": "http://192.168.31.172:7864"
    },
    "wb2api": {
        "id": "wb2api",
        "name": "wb2api 核心网关",
        "port": 7863,
        "category": "OpenAI 代理",
        "pattern": "wb2api",
        "log_file": os.path.join(HOME_DIR, "wb2api.log"),
        "start_cmd": f"nohup proot-distro login debian -- bash -c 'cd /opt/workbuddy-manager/upstream && ./wb2api -config config.json' > {HOME_DIR}/wb2api.log 2>&1 &",
        "url": "http://192.168.31.172:7863"
    },
    "public_gateway": {
        "id": "public_gateway",
        "name": "公网共享网关与隧道",
        "port": 8081,
        "category": "穿透隧道",
        "pattern": "public_ai_gateway.py",
        "log_file": os.path.join(HOME_DIR, "logs", "gateway.log"),
        "start_cmd": f"bash {HOME_DIR}/start_public_ai.sh > /dev/null 2>&1 &",
        "url": "http://192.168.31.172:8081"
    }
}

metrics_lock = threading.Lock()
latest_metrics = {
    "timestamp": 0,
    "uptime_str": "0天 0小时",
    "cpu_total": 0.0,
    "cpu_cores": [0.0] * 8,
    "cpu_freqs": [0] * 8,
    "ram": {"total_mb": 11230, "used_mb": 0, "free_mb": 0, "pct": 0.0},
    "zram": {"total_mb": 7679, "used_mb": 0, "free_mb": 7679, "pct": 0.0},
    "thermals": {"battery": 30.0, "cpu_max": 35.0, "status": "NORMAL"},
    "services": {}
}

def format_uptime(seconds: float) -> str:
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    mins = int((seconds % 3600) // 60)
    if days > 0:
        return f"{days}天 {hours}小时 {mins}分"
    elif hours > 0:
        return f"{hours}小时 {mins}分"
    return f"{mins}分钟"

def check_port(port: int, timeout=0.2) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False

def get_procs_info():
    """解析当前系统进程占用"""
    procs = {}
    try:
        out = subprocess.check_output(["ps", "-ef"], text=True, stderr=subprocess.DEVNULL)
        for line in out.strip().splitlines()[1:]:
            parts = line.split(None, 7)
            if len(parts) >= 8:
                pid, cmd = parts[1], parts[7]
                for s_key, s_cfg in MANAGED_SERVICES.items():
                    if s_cfg["pattern"] in cmd and "grep" not in cmd and "nohup" not in cmd:
                        procs[s_key] = {"pid": pid, "cmd": cmd}
    except Exception:
        pass
    return procs

def get_proc_rss_mb(pid: str) -> float:
    try:
        with open(f"/proc/{pid}/statm", "r") as f:
            rss_pages = int(f.read().split()[1])
            return round(rss_pages * 4 / 1024, 1)
    except Exception:
        return 0.0

def read_thermal_matrix():
    temps = {"battery": 30.0, "cpu_max": 35.0, "status": "NORMAL"}
    # 电池温度
    try:
        with open("/sys/class/thermal/thermal_zone100/temp", "r") as f:
            v = float(f.read().strip())
            temps["battery"] = round(v / 1000.0, 1) if v > 1000 else round(v, 1)
    except Exception:
        pass

    # CPU 核心最高温
    max_c = 0.0
    for z in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        try:
            with open(z, "r") as f:
                v = float(f.read().strip())
                t = v / 1000.0 if v > 1000 else v
                if 20.0 <= t <= 95.0 and t > max_c:
                    max_c = t
        except Exception:
            continue
    temps["cpu_max"] = round(max_c if max_c > 0 else temps["battery"] + 3.0, 1)
    temps["status"] = "HIGH" if temps["battery"] >= 42.0 else "NORMAL"
    return temps

def read_cpu_freqs():
    freqs = []
    for i in range(8):
        f_path = f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq"
        try:
            with open(f_path, "r") as f:
                freqs.append(int(int(f.read().strip()) / 1000))
        except Exception:
            freqs.append(0)
    return freqs

def read_mem_info():
    total, free, avail, cached, swap_total, swap_free = 11230, 0, 0, 0, 7679, 6400
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                parts = line.split()
                k, v = parts[0], int(parts[1]) // 1024
                if k == "MemTotal:": total = v
                elif k == "MemFree:": free = v
                elif k == "MemAvailable:": avail = v
                elif k == "Cached:": cached = v
                elif k == "SwapTotal:": swap_total = v
                elif k == "SwapFree:": swap_free = v
    except Exception:
        pass
    used = total - avail if avail else total - free
    swap_used = swap_total - swap_free
    return {
        "ram": {
            "total_mb": total,
            "used_mb": used,
            "avail_mb": avail,
            "pct": round(used / total * 100, 1) if total else 0
        },
        "zram": {
            "total_mb": swap_total,
            "used_mb": swap_used,
            "free_mb": swap_free,
            "pct": round(swap_used / swap_total * 100, 1) if swap_total else 0
        }
    }

def metrics_collector_loop():
    global latest_metrics
    while True:
        try:
            now = time.time()
            uptime_str = "正常"
            try:
                with open("/proc/uptime", "r") as f:
                    uptime_str = format_uptime(float(f.read().split()[0]))
            except Exception:
                pass

            mem_data = read_mem_info()
            freqs = read_cpu_freqs()
            thermals = read_thermal_matrix()
            procs = get_procs_info()

            # 评估微服务矩阵状态
            services_status = {}
            for s_key, s_cfg in MANAGED_SERVICES.items():
                is_port_ok = check_port(s_cfg["port"])
                proc_info = procs.get(s_key)
                is_running = is_port_ok or (proc_info is not None)
                pid = proc_info["pid"] if proc_info else None
                rss_mb = get_proc_rss_mb(pid) if pid else 0.0

                services_status[s_key] = {
                    "id": s_key,
                    "name": s_cfg["name"],
                    "category": s_cfg["category"],
                    "port": s_cfg["port"],
                    "url": s_cfg["url"],
                    "running": is_running,
                    "pid": pid,
                    "memory_mb": rss_mb
                }

            with metrics_lock:
                latest_metrics["timestamp"] = int(now)
                latest_metrics["uptime_str"] = uptime_str
                latest_metrics["cpu_freqs"] = freqs
                latest_metrics["ram"] = mem_data["ram"]
                latest_metrics["zram"] = mem_data["zram"]
                latest_metrics["thermals"] = thermals
                latest_metrics["services"] = services_status
        except Exception:
            pass
        time.sleep(1.5)

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="zh-CN" class="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>OnePlus 9 · 移动微服务器统一控制台</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    * { box-sizing: border-box; }
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #0f172a; }
    ::-webkit-scrollbar-thumb { background: #334155; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #475569; }
    @keyframes pulse-slow { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
    .pulse-slow { animation: pulse-slow 2s infinite ease-in-out; }
  </style>
</head>
<body class="bg-[#0b1120] text-[#f8fafc] font-sans antialiased min-h-screen p-4 md:p-6 select-none">

  <!-- Header -->
  <header class="max-w-7xl mx-auto flex flex-col md:flex-row items-start md:items-center justify-between pb-6 border-b border-slate-800/80 gap-4">
    <div class="flex items-center space-x-3">
      <div class="w-11 h-11 rounded-2xl bg-gradient-to-tr from-blue-600 to-indigo-600 flex items-center justify-center shadow-lg shadow-blue-500/20">
        <i class="fa-solid fa-server text-white text-lg"></i>
      </div>
      <div>
        <div class="flex items-center gap-2">
          <h1 class="text-xl font-bold tracking-tight">OnePlus 9 移动微服务器 · 统一控制台</h1>
          <span class="text-xs font-mono font-semibold px-2.5 py-0.5 rounded-full bg-blue-500/20 text-blue-400 border border-blue-500/30">Snapdragon 888</span>
        </div>
        <p class="text-xs text-slate-400 mt-1">局域网 IP: <span class="font-mono text-slate-300">192.168.31.172</span> · 运行时间: <span id="uptime" class="font-mono text-slate-300">--</span></p>
      </div>
    </div>

    <!-- Quick Action Hub -->
    <div class="flex items-center space-x-3 text-xs">
      <button onclick="triggerAction('all', 'heal')" class="px-3.5 py-2 rounded-xl bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 text-white font-medium shadow-md shadow-emerald-500/20 transition flex items-center gap-2 active:scale-95">
        <i class="fa-solid fa-wand-magic-sparkles"></i>
        <span>一键全员自愈守护</span>
      </button>
      <a href="http://192.168.31.172:8080" target="_blank" class="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 border border-slate-700/80 transition flex items-center gap-1.5 text-slate-200">
        <span>WebUI 大模型 ↗</span>
      </a>
    </div>
  </header>

  <main class="max-w-7xl mx-auto mt-6 space-y-6">

    <!-- 4 Main Gauges -->
    <div class="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
      
      <!-- Battery Temp -->
      <div class="p-5 rounded-2xl bg-slate-900/60 border border-slate-800/80 backdrop-blur-sm relative overflow-hidden">
        <div class="flex items-center justify-between text-slate-400 text-xs font-semibold uppercase tracking-wider">
          <span>电池核心温</span>
          <i class="fa-solid fa-battery-half text-emerald-400 text-sm"></i>
        </div>
        <div class="mt-3 flex items-baseline justify-between">
          <span id="bat-temp" class="text-3xl font-extrabold text-white font-mono">--°C</span>
          <span id="temp-badge" class="text-xs px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300 font-mono">温控极佳</span>
        </div>
        <p class="text-xs text-slate-400 mt-2">CPU 峰值温: <span id="cpu-temp" class="font-mono text-slate-200">--°C</span></p>
      </div>

      <!-- RAM -->
      <div class="p-5 rounded-2xl bg-slate-900/60 border border-slate-800/80 backdrop-blur-sm">
        <div class="flex items-center justify-between text-slate-400 text-xs font-semibold uppercase tracking-wider">
          <span>物理内存 (RAM)</span>
          <span class="font-mono text-blue-400">12GB LPDDR5</span>
        </div>
        <div class="mt-3 flex items-baseline justify-between">
          <span id="ram-used" class="text-3xl font-extrabold text-white font-mono">-- GB</span>
          <span id="ram-pct" class="text-xs font-mono text-slate-400">0%</span>
        </div>
        <div class="w-full bg-slate-800 h-2 rounded-full mt-3 overflow-hidden">
          <div id="ram-bar" class="bg-gradient-to-r from-blue-500 to-indigo-500 h-full rounded-full transition-all duration-500" style="width: 0%"></div>
        </div>
      </div>

      <!-- ZRAM -->
      <div class="p-5 rounded-2xl bg-slate-900/60 border border-slate-800/80 backdrop-blur-sm">
        <div class="flex items-center justify-between text-slate-400 text-xs font-semibold uppercase tracking-wider">
          <span>ZRAM 压缩缓冲池</span>
          <span class="font-mono text-purple-400">7.8GB Swap</span>
        </div>
        <div class="mt-3 flex items-baseline justify-between">
          <span id="zram-used" class="text-3xl font-extrabold text-white font-mono">-- MB</span>
          <span id="zram-pct" class="text-xs font-mono text-slate-400">0%</span>
        </div>
        <div class="w-full bg-slate-800 h-2 rounded-full mt-3 overflow-hidden">
          <div id="zram-bar" class="bg-gradient-to-r from-purple-500 to-pink-500 h-full rounded-full transition-all duration-500" style="width: 0%"></div>
        </div>
      </div>

      <!-- Managed Services Count -->
      <div class="p-5 rounded-2xl bg-slate-900/60 border border-slate-800/80 backdrop-blur-sm">
        <div class="flex items-center justify-between text-slate-400 text-xs font-semibold uppercase tracking-wider">
          <span>微服务在线矩阵</span>
          <span class="font-mono text-emerald-400">Supervisor 管控</span>
        </div>
        <div class="mt-3 flex items-baseline justify-between">
          <span id="active-srv-count" class="text-3xl font-extrabold text-emerald-400 font-mono">5 / 5</span>
          <span class="text-xs px-2 py-0.5 rounded-md bg-emerald-500/20 text-emerald-300">全部正常</span>
        </div>
        <p class="text-xs text-slate-400 mt-2">支持一键启停 · 热重启 · 实时日志</p>
      </div>
    </div>

    <!-- CPU 8 Cores Frequency Bar -->
    <div class="p-6 rounded-2xl bg-slate-900/60 border border-slate-800/80 backdrop-blur-sm">
      <div class="flex items-center justify-between mb-4">
        <h2 class="text-sm font-bold flex items-center gap-2">
          <i class="fa-solid fa-microchip text-blue-400"></i>
          <span>高通骁龙 888 · 8 核心实时频率动态</span>
        </h2>
        <span class="text-xs text-slate-400 font-mono">1x Cortex-X1 (2.84G) + 3x A78 (2.42G) + 4x A55 (1.80G)</span>
      </div>
      <div class="grid grid-cols-2 sm:grid-cols-4 lg:grid-cols-8 gap-3" id="cores-container">
        <!-- Rendered via JS -->
      </div>
    </div>

    <!-- Services Management Matrix (Supervisor Style) -->
    <div class="p-6 rounded-2xl bg-slate-900/60 border border-slate-800/80 backdrop-blur-sm space-y-4">
      <div class="flex items-center justify-between border-b border-slate-800 pb-3">
        <div>
          <h2 class="text-base font-bold flex items-center gap-2">
            <i class="fa-solid fa-cubes-stacked text-indigo-400"></i>
            <span>微服务生命周期管理中枢</span>
          </h2>
          <p class="text-xs text-slate-400 mt-0.5">免 Root 容器与宿主双层架构 · 实时 PID 与内存追踪 · 进程级热控制</p>
        </div>
      </div>

      <!-- Services List Cards -->
      <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" id="services-grid">
        <!-- Rendered via JS -->
      </div>
    </div>

  </main>

  <!-- Log Modal -->
  <div id="log-modal" class="fixed inset-0 bg-black/70 backdrop-blur-md hidden items-center justify-center z-50 p-4">
    <div class="bg-[#0f172a] border border-slate-700/80 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
      <!-- Modal Header -->
      <div class="px-5 py-3.5 border-b border-slate-800 flex items-center justify-between bg-slate-900/80">
        <div class="flex items-center gap-2.5">
          <i class="fa-solid fa-terminal text-blue-400 text-sm"></i>
          <span id="log-modal-title" class="font-bold text-sm text-slate-200">服务控制台日志</span>
          <span id="log-modal-badge" class="text-xs font-mono px-2 py-0.5 rounded bg-slate-800 text-slate-400">tail -n 80</span>
        </div>
        <div class="flex items-center gap-2">
          <button onclick="refreshCurrentLogs()" class="px-2.5 py-1 text-xs rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition">
            <i class="fa-solid fa-arrows-rotate mr-1"></i>刷新
          </button>
          <button onclick="closeLogModal()" class="w-7 h-7 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 flex items-center justify-center transition">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
      </div>

      <!-- Log Terminal Body -->
      <div class="p-4 flex-1 overflow-y-auto font-mono text-xs text-slate-300 bg-[#090d16] leading-relaxed whitespace-pre-wrap select-text" id="log-content">
        正在读取日志...
      </div>
    </div>
  </div>

  <script>
    let activeLogService = null;

    // 格式化 CPU 核心展示
    function renderCores(freqs) {
      const container = document.getElementById('cores-container');
      if (!container) return;
      container.innerHTML = freqs.map((f, i) => {
        let maxF = i === 0 ? 2841 : (i <= 3 ? 2419 : 1804);
        let pct = Math.min(100, Math.round(f / maxF * 100));
        let typeName = i === 0 ? '超大核 X1' : (i <= 3 ? `大核 A78` : `小核 A55`);
        return `
          <div class="p-3 rounded-xl bg-slate-800/60 border border-slate-700/50 flex flex-col justify-between">
            <div class="flex justify-between items-center text-xs text-slate-400">
              <span class="font-semibold text-slate-300">#${i}</span>
              <span class="text-[10px] text-slate-400">${typeName}</span>
            </div>
            <div class="my-2">
              <div class="text-lg font-bold font-mono text-blue-400">${(f/1000).toFixed(2)}<span class="text-[10px] text-slate-400 font-normal">GHz</span></div>
            </div>
            <div class="w-full bg-slate-700/60 h-1.5 rounded-full overflow-hidden">
              <div class="bg-blue-500 h-full rounded-full transition-all duration-300" style="width: ${pct}%"></div>
            </div>
          </div>
        `;
      }).join('');
    }

    // 渲染微服务卡片
    function renderServices(services) {
      const grid = document.getElementById('services-grid');
      if (!grid) return;
      const srvList = Object.values(services);
      
      let runningCount = srvList.filter(s => s.running).length;
      document.getElementById('active-srv-count').innerText = `${runningCount} / ${srvList.length}`;

      grid.innerHTML = srvList.map(s => {
        let isOnline = s.running;
        let dotColor = isOnline ? 'bg-emerald-500 shadow-emerald-500/50' : 'bg-rose-500 shadow-rose-500/50';
        let statusText = isOnline ? '运行中 (Active)' : '已停止 (Stopped)';
        let statusBadge = isOnline ? 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30' : 'bg-rose-500/15 text-rose-400 border-rose-500/30';
        
        return `
          <div class="p-4 rounded-xl bg-slate-800/60 border border-slate-700/60 flex flex-col justify-between hover:border-slate-600 transition">
            <div>
              <div class="flex items-center justify-between mb-2">
                <span class="text-[11px] font-mono px-2 py-0.5 rounded bg-slate-700/50 text-slate-300">${s.category}</span>
                <span class="text-xs font-mono px-2 py-0.5 rounded-full border ${statusBadge} flex items-center gap-1.5">
                  <span class="w-1.5 h-1.5 rounded-full ${dotColor} ${isOnline ? 'pulse-slow' : ''}"></span>
                  ${statusText}
                </span>
              </div>
              <h3 class="font-bold text-sm text-slate-100 flex items-center justify-between">
                <span>${s.name}</span>
                <span class="font-mono text-xs text-blue-400 font-normal">:${s.port}</span>
              </h3>
              <div class="flex items-center gap-4 text-xs text-slate-400 font-mono mt-2 mb-3">
                <span>PID: <b class="text-slate-200">${s.pid || '--'}</b></span>
                <span>内存: <b class="text-slate-200">${s.memory_mb ? s.memory_mb + ' MB' : '--'}</b></span>
              </div>
            </div>

            <!-- Action Buttons -->
            <div class="flex items-center gap-2 pt-2 border-t border-slate-700/50 text-xs">
              <button onclick="triggerAction('${s.id}', 'restart')" class="flex-1 py-1.5 rounded-lg bg-blue-600/20 hover:bg-blue-600/30 text-blue-300 border border-blue-500/30 transition flex items-center justify-center gap-1">
                <i class="fa-solid fa-arrows-rotate"></i>重启
              </button>
              <button onclick="triggerAction('${s.id}', '${isOnline ? 'stop' : 'start'}')" class="flex-1 py-1.5 rounded-lg ${isOnline ? 'bg-rose-600/20 hover:bg-rose-600/30 text-rose-300 border-rose-500/30' : 'bg-emerald-600/20 hover:bg-emerald-600/30 text-emerald-300 border-emerald-500/30'} border transition flex items-center justify-center gap-1">
                <i class="fa-solid ${isOnline ? 'fa-stop' : 'fa-play'}"></i>${isOnline ? '停止' : '启动'}
              </button>
              <button onclick="openLogs('${s.id}', '${s.name}')" class="px-2.5 py-1.5 rounded-lg bg-slate-700/40 hover:bg-slate-700/80 text-slate-300 border border-slate-600/50 transition">
                <i class="fa-solid fa-file-lines"></i>
              </button>
              <a href="${s.url}" target="_blank" class="px-2.5 py-1.5 rounded-lg bg-slate-700/40 hover:bg-slate-700/80 text-slate-300 border border-slate-600/50 transition">
                <i class="fa-solid fa-arrow-up-right-from-square"></i>
              </a>
            </div>
          </div>
        `;
      }).join('');
    }

    async function fetchMetrics() {
      try {
        const res = await fetch('/api/metrics');
        const data = await res.json();

        document.getElementById('uptime').innerText = data.uptime_str;
        document.getElementById('bat-temp').innerText = data.thermals.battery + '°C';
        document.getElementById('cpu-temp').innerText = data.thermals.cpu_max + '°C';

        // RAM
        const ramUsedGb = (data.ram.used_mb / 1024).toFixed(1);
        document.getElementById('ram-used').innerText = ramUsedGb + ' GB';
        document.getElementById('ram-pct').innerText = data.ram.pct + '%';
        document.getElementById('ram-bar').style.width = data.ram.pct + '%';

        // ZRAM
        document.getElementById('zram-used').innerText = data.zram.used_mb + ' MB';
        document.getElementById('zram-pct').innerText = data.zram.pct + '%';
        document.getElementById('zram-bar').style.width = data.zram.pct + '%';

        renderCores(data.cpu_freqs);
        renderServices(data.services);
      } catch (e) {
        console.error("Fetch metrics error:", e);
      }
    }

    async function triggerAction(service, action) {
      if (!confirm(`确定对 [${service}] 执行 [${action}] 操作吗？`)) return;
      try {
        const res = await fetch('/api/service/action', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ service, action })
        });
        const result = await res.json();
        alert(result.message || '指令已下发！');
        setTimeout(fetchMetrics, 1200);
      } catch (e) {
        alert('执行失败: ' + e.message);
      }
    }

    function openLogs(serviceId, serviceName) {
      activeLogService = serviceId;
      document.getElementById('log-modal-title').innerText = `${serviceName} · 实时运行日志`;
      document.getElementById('log-modal').style.display = 'flex';
      refreshCurrentLogs();
    }

    function closeLogModal() {
      document.getElementById('log-modal').style.display = 'none';
      activeLogService = null;
    }

    async function refreshCurrentLogs() {
      if (!activeLogService) return;
      const logBox = document.getElementById('log-content');
      logBox.innerText = '正在读取中...';
      try {
        const res = await fetch(`/api/service/logs?service=${activeLogService}&lines=80`);
        const text = await res.text();
        logBox.innerText = text || '(暂无日志输出)';
        logBox.scrollTop = logBox.scrollHeight;
      } catch (e) {
        logBox.innerText = '读取日志异常: ' + e.message;
      }
    }

    fetchMetrics();
    setInterval(fetchMetrics, 2000);
  </script>
</body>
</html>
"""

class ConsoleHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # 首页
        if self.path in ("/", "/index.html") or not self.path.startswith("/api/"):
            body = HTML_DASHBOARD.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        # 实时全景指标
        if self.path == "/api/metrics":
            with metrics_lock:
                data = dict(latest_metrics)
            self.send_json(200, data)
            return

        # 日志读取
        if self.path.startswith("/api/service/logs"):
            qs = parse_qs(urlparse(self.path).query)
            srv = qs.get("service", [""])[0]
            lines = int(qs.get("lines", ["80"])[0])
            cfg = MANAGED_SERVICES.get(srv)
            if not cfg or not os.path.exists(cfg["log_file"]):
                content = f"日志文件尚未生成或不存在: {cfg['log_file'] if cfg else '未知服务'}"
            else:
                try:
                    out = subprocess.check_output(
                        ["tail", f"-n{lines}", cfg["log_file"]],
                        text=True, stderr=subprocess.STDOUT
                    )
                    content = out
                except Exception as e:
                    content = f"读取日志异常: {str(e)}"

            body = content.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        if self.path == "/api/service/action":
            content_length = int(self.headers.get("Content-Length", 0))
            body_raw = self.rfile.read(content_length) if content_length > 0 else b"{}"
            try:
                data = json.loads(body_raw.decode("utf-8"))
            except Exception:
                data = {}

            srv_id = data.get("service")
            action = data.get("action")

            if srv_id == "all" and action == "heal":
                # 全自愈
                subprocess.Popen(
                    ["bash", os.path.join(HOME_DIR, "start_qinglong_daemon.sh")],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
                self.send_json(200, {"status": "ok", "message": "已在后台启动全员自愈守护进程！"})
                return

            cfg = MANAGED_SERVICES.get(srv_id)
            if not cfg:
                self.send_json(400, {"error": "未识别的服务标识"})
                return

            if action in ("stop", "restart"):
                subprocess.run(["pkill", "-f", cfg["pattern"]], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(1)

            if action in ("start", "restart"):
                subprocess.Popen(
                    cfg["start_cmd"],
                    shell=True,
                    executable="/data/data/com.termux/files/usr/bin/bash",
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )

            self.send_json(200, {
                "status": "ok",
                "message": f"服务 [{cfg['name']}] 已成功下发 {action} 操作指令！"
            })
            return

        self.send_response(404)
        self.end_headers()

def main():
    print(f"[*] 启动 OnePlus 9 移动微服务器一体化控制台 (Supervisor+遥测)...")
    print(f"[*] 监听端口: 0.0.0.0:{PORT}")

    t = threading.Thread(target=metrics_collector_loop, daemon=True)
    t.start()

    server = ThreadingHTTPServer(("0.0.0.0", PORT), ConsoleHTTPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] 正在停止控制台服务...")
        server.server_close()

if __name__ == "__main__":
    main()
