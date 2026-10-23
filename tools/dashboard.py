#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一加 9 (LE2110) 移动微服务器一体化控制台 (Mobile Micro-Server Console)
DevCheck 全景版 + 端侧 DeepSeek-R1 (1.5B) 10分钟智能巡检心语 + 进程级内存桑基图 (Sankey Diagram)
"""

import os
import sys
import glob
import time
import json
import sqlite3
import socket
import subprocess
import threading
import re
import urllib.request
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
        "name": "DeepSeek-R1-1.5B 本地推理引擎",
        "port": 8080,
        "category": "端侧 AI",
        "pattern": "llama-server",
        "log_file": os.path.join(HOME_DIR, "llama_server.log"),
        "start_cmd": f"nohup proot-distro login debian -- bash -c 'llama-server -m /ql/data/models/deepseek-r1-1.5b-q4_k_m.gguf --host 0.0.0.0 --port 8080 -c 2048 -t 4 --alias DeepSeek-R1-1.5B,deepseek-r1-1.5b,qwen2.5-3b' > {HOME_DIR}/llama_server.log 2>&1 &",
        "url": "http://192.168.31.172:8080/v1/models"
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
        "url": "http://192.168.31.172:7863/healthz"
    },
    "public_gateway": {
        "id": "public_gateway",
        "name": "公网共享网关与隧道",
        "port": 8081,
        "category": "穿透隧道",
        "pattern": "public_ai_gateway.py",
        "log_file": os.path.join(HOME_DIR, "logs", "gateway.log"),
        "start_cmd": f"bash {HOME_DIR}/start_public_ai.sh > /dev/null 2>&1 &",
        "url": "https://192.168.31.172:8082/health"
    },
    "qodergateway": {
        "id": "qodergateway",
        "name": "QoderGateway 网关",
        "port": 5050,
        "category": "OpenAI 代理",
        "pattern": "qoder2api.app",
        "log_file": os.path.join(HOME_DIR, "qodergateway.log"),
        "start_cmd": f"nohup proot-distro login debian -- bash -c 'cd /opt/qodergateway && PYTHONPATH=src python3 -m qoder2api.app --host 0.0.0.0 --port 5050' > {HOME_DIR}/qodergateway.log 2>&1 &",
        "url": "https://192.168.31.172:5050/console"
    },
    "devcheck": {
        "id": "devcheck",
        "name": "DevCheck 控制台",
        "port": 5701,
        "category": "监控面板",
        "pattern": "dashboard.py",
        "log_file": os.path.join(HOME_DIR, "dashboard.log"),
        "start_cmd": f"nohup python {HOME_DIR}/dashboard.py > {HOME_DIR}/dashboard.log 2>&1 &",
        "url": "http://192.168.31.172:5701"
    }
}

# 缓存各核心硬件上限频率
MAX_FREQS = [1804, 1804, 1804, 1804, 2419, 2419, 2419, 2841]
try:
    mf = []
    for i in range(8):
        fpath = f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_max_freq"
        if os.path.exists(fpath):
            with open(fpath, "r") as f:
                mf.append(int(int(f.read().strip()) / 1000))
        else:
            mf.append(MAX_FREQS[i])
    if len(mf) == 8:
        MAX_FREQS = mf
except Exception:
    pass

metrics_lock = threading.Lock()
latest_metrics = {
    "timestamp": 0,
    "current_time": "",
    "uptime_str": "计算中...",
    "load_avg": [0.0, 0.0, 0.0],
    "cpu_cores_temp": [32.0] * 8,
    "cpu_freqs": [0] * 8,
    "max_freqs": MAX_FREQS,
    "clusters": {
        "little": 0,
        "big": 0,
        "prime": 0
    },
    "battery": {
        "level": 70,
        "temp": 26.8,
        "voltage": 3.94,
        "status": "未充电 🔌"
    },
    "ram": {"total_mb": 11230, "used_mb": 0, "avail_mb": 0, "pct": 0.0},
    "zram": {"total_mb": 7679, "used_mb": 0, "free_mb": 7679, "pct": 0.0},
    "thermals": {"battery": 26.8, "cpu_max": 34.0, "status": "NORMAL"},
    "ai_insight": {
        "text": "端侧 DeepSeek-R1 正在就绪，首次巡检将在稍后生成...",
        "updated_at": "--:--",
        "cost_s": 0.0
    },
    "sankey_data": {"nodes": [], "links": []},
    "services": {},
    "health": {"up": 0, "total": 0, "restarts": 0, "public": None}
}

# ─── 服务健康与历史遥测 ────────────────────────────────────────────────
HISTORY_DB = os.path.join(HOME_DIR, "metrics_history.db")
HISTORY_KEEP_DAYS = 7
SAMPLE_EVERY_S = 30
SERVICE_HEALTH = {}
_last_sample_ts = 0


def init_history_db():
    try:
        conn = sqlite3.connect(HISTORY_DB, timeout=3)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS samples ("
            "ts INTEGER PRIMARY KEY, cpu_max REAL, load1 REAL, ram_used_mb INTEGER, bat_level INTEGER)"
        )
        conn.execute("CREATE TABLE IF NOT EXISTS service_events (ts INTEGER, service TEXT, event TEXT)")
        conn.commit()
        conn.close()
    except Exception:
        pass


def record_event(ts, service, event):
    try:
        conn = sqlite3.connect(HISTORY_DB, timeout=2)
        conn.execute("INSERT INTO service_events VALUES (?,?,?)", (int(ts), service, event))
        conn.commit()
        conn.close()
    except Exception:
        pass


def load_health_state():
    """从历史事件恢复重启次数与最后一次异常时间（控制台自身重启后不清零）"""
    try:
        conn = sqlite3.connect(HISTORY_DB, timeout=2)
        rows = conn.execute(
            "SELECT service, SUM(event='up'), MAX(CASE WHEN event='down' THEN ts ELSE 0 END) "
            "FROM service_events GROUP BY service"
        ).fetchall()
        conn.close()
        for svc, ups, last_down in rows:
            SERVICE_HEALTH[svc] = {
                "up": None,
                "since": int(time.time()),
                "restarts": int(ups or 0),
                "last_down": int(last_down or 0),
            }
    except Exception:
        pass


def record_sample(ts, thermals, load_avg, mem_data, bat_lvl):
    global _last_sample_ts
    if ts - _last_sample_ts < SAMPLE_EVERY_S:
        return
    _last_sample_ts = ts
    try:
        conn = sqlite3.connect(HISTORY_DB, timeout=3)
        conn.execute(
            "INSERT OR REPLACE INTO samples VALUES (?,?,?,?,?)",
            (
                int(ts),
                float(thermals.get("cpu_max") or 0),
                float(load_avg[0] if load_avg else 0),
                int(mem_data["ram"].get("used_mb") or 0),
                int(bat_lvl or 0),
            ),
        )
        conn.execute("DELETE FROM samples WHERE ts < ?", (int(ts) - HISTORY_KEEP_DAYS * 86400,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def load_history(hours=24):
    try:
        since = int(time.time()) - hours * 3600
        conn = sqlite3.connect(HISTORY_DB, timeout=3)
        rows = conn.execute(
            "SELECT ts,cpu_max,load1,ram_used_mb,bat_level FROM samples WHERE ts>=? ORDER BY ts",
            (since,),
        ).fetchall()
        conn.close()
    except Exception:
        return []
    if len(rows) > 720:
        stride = len(rows) // 720 + 1
        rows = rows[::stride]
    return [{"t": r[0] * 1000, "cpu": r[1], "load": r[2], "ram": r[3], "bat": r[4]} for r in rows]


def read_public_probe():
    try:
        with open(os.path.join(HOME_DIR, "logs", "health_probe.json"), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None

def get_uptime_and_load():
    """解析系统真实在线时长与 1/5/15 分钟负载"""
    uptime_str = "运行正常"
    load_avg = [0.0, 0.0, 0.0]
    try:
        up_p = subprocess.check_output(["uptime", "-p"], text=True, stderr=subprocess.DEVNULL).strip()
        uptime_str = up_p.replace("up ", "").replace(" days", "天").replace(" day", "天").replace(" hours", "小时").replace(" hour", "小时").replace(" minutes", "分").replace(" minute", "分").replace(", ", " ")
    except Exception:
        pass

    try:
        out = subprocess.check_output(["uptime"], text=True, stderr=subprocess.DEVNULL).strip()
        m_load = re.search(r"load average:\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)", out)
        if m_load:
            load_avg = [float(m_load.group(1)), float(m_load.group(2)), float(m_load.group(3))]
    except Exception:
        pass
    return uptime_str, load_avg

def check_port(port: int, timeout=0.15) -> bool:
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
    """高精度直读骁龙 888 8 核独立温度、电池温度及电压"""
    temps = {"battery": 26.8, "cpu_max": 34.0, "status": "NORMAL", "cpu_cores": [32.0] * 8, "vbat": 3.94}
    
    # 电池真实温度：thermal_zone100
    try:
        with open("/sys/class/thermal/thermal_zone100/temp", "r") as f:
            v = float(f.read().strip())
            temps["battery"] = round(v / 1000.0, 1) if v > 1000 else round(v, 1)
    except Exception:
        pass

    # 电池真实电压：thermal_zone102 (vbat)
    try:
        with open("/sys/class/thermal/thermal_zone102/temp", "r") as f:
            v = float(f.read().strip())
            temps["vbat"] = round(v / 1000.0, 2) if v > 100 else round(v, 2)
    except Exception:
        pass

    # CPU 8 核独立温度：thermal_zone45 ~ 52 (cpu 0 ~ 7)
    cpu_temps = []
    for z in range(45, 53):
        try:
            with open(f"/sys/class/thermal/thermal_zone{z}/temp", "r") as f:
                v = float(f.read().strip())
                t = v / 1000.0 if v > 1000 else v
                cpu_temps.append(round(t, 1))
        except Exception:
            cpu_temps.append(round(temps["battery"] + 4.0, 1))

    if cpu_temps:
        temps["cpu_cores"] = cpu_temps
        temps["cpu_max"] = max(cpu_temps)

    temps["status"] = "HIGH" if temps["battery"] >= 42.0 or temps["cpu_max"] >= 65.0 else "NORMAL"
    return temps

cached_battery_data = {"level": 70, "status": "未充电 🔌", "ts": 0}

def get_battery_status_cached():
    """10秒缓存极速获取手机硬件电量与充电状态"""
    global cached_battery_data
    now_t = time.time()
    if now_t - cached_battery_data["ts"] < 10:
        return cached_battery_data["level"], cached_battery_data["status"]
    
    level = cached_battery_data["level"]
    status_str = cached_battery_data["status"]
    try:
        out = subprocess.check_output(
            ["adb", "-s", "127.0.0.1:5555", "shell", "dumpsys", "battery"],
            text=True, stderr=subprocess.DEVNULL, timeout=1.5
        )
        charging = False
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("level:"):
                level = int(line.split(":")[1].strip())
            elif line.startswith("status:"):
                st = int(line.split(":")[1].strip())
                charging = (st == 2)
        status_str = "充电中 ⚡" if charging else ("已充满 ✨" if level >= 100 else "未充电 🔌")
        cached_battery_data = {"level": level, "status": status_str, "ts": now_t}
    except Exception:
        cached_battery_data["ts"] = now_t
    return level, status_str

def read_cpu_freqs():
    """读取 8 核当前动态时钟频率 (MHz)"""
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
    """读取物理内存与 Swap/ZRAM 真实使用情况"""
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
            "cached_mb": cached,
            "free_mb": free,
            "pct": round(used / total * 100, 1) if total else 0
        },
        "zram": {
            "total_mb": swap_total,
            "used_mb": swap_used,
            "free_mb": swap_free,
            "pct": round(swap_used / swap_total * 100, 1) if swap_total else 0
        }
    }

def get_process_memory_tree(mem_data, services_status):
    """计算用于桑基图的进程级内存拓扑数据"""
    ram_total = mem_data["ram"]["total_mb"]
    ram_used = mem_data["ram"]["used_mb"]
    ram_cached = mem_data["ram"]["cached_mb"]
    ram_free = mem_data["ram"]["free_mb"]

    zram_total = mem_data["zram"]["total_mb"]
    zram_used = mem_data["zram"]["used_mb"]
    zram_free = mem_data["zram"]["free_mb"]

    # 提取已知微服务内存
    llama_mb = int(services_status.get("llama", {}).get("memory_mb", 2200))
    ql_mb = int(services_status.get("qinglong", {}).get("memory_mb", 180))
    wb_mb = int(services_status.get("workbuddy", {}).get("memory_mb", 110))
    gw_mb = int(services_status.get("public_gateway", {}).get("memory_mb", 20) + services_status.get("wb2api", {}).get("memory_mb", 16) + 40)
    proot_mb = 160

    known_sum = llama_mb + ql_mb + wb_mb + gw_mb + proot_mb
    android_sys_mb = max(200, ram_used - known_sum)

    nodes = [
        {"name": "物理 RAM", "value": ram_total, "itemStyle": {"color": "#10b981"}, "label": {"position": "left"}},
        {"name": "ZRAM 交换区", "value": zram_total, "itemStyle": {"color": "#8b5cf6"}, "label": {"position": "left"}},
        {"name": "已分配进程内存", "value": ram_used, "itemStyle": {"color": "#3b82f6"}},
        {"name": "系统缓存与缓冲", "value": ram_cached, "itemStyle": {"color": "#06b6d4"}},
        {"name": "完全空闲内存", "value": max(100, ram_free), "itemStyle": {"color": "#94a3b8"}},
        {"name": "ZRAM 压缩已用", "value": zram_used, "itemStyle": {"color": "#6366f1"}},
        {"name": "ZRAM 空闲池", "value": zram_free, "itemStyle": {"color": "#a855f7"}},
        {"name": "DeepSeek-R1 推理引擎", "value": llama_mb, "itemStyle": {"color": "#f59e0b"}},
        {"name": "青龙自动化面板", "value": ql_mb, "itemStyle": {"color": "#ef4444"}},
        {"name": "WorkBuddy 控制台", "value": wb_mb, "itemStyle": {"color": "#0284c7"}},
        {"name": "PRoot 容器隔离层", "value": proot_mb, "itemStyle": {"color": "#0d9488"}},
        {"name": "网关与公网隧道", "value": gw_mb, "itemStyle": {"color": "#d946ef"}},
        {"name": "Android 底座与系统服务", "value": android_sys_mb, "itemStyle": {"color": "#64748b"}}
    ]

    links = [
        {"source": "物理 RAM", "target": "已分配进程内存", "value": ram_used},
        {"source": "物理 RAM", "target": "系统缓存与缓冲", "value": ram_cached},
        {"source": "物理 RAM", "target": "完全空闲内存", "value": max(100, ram_free)},
        {"source": "ZRAM 交换区", "target": "ZRAM 压缩已用", "value": zram_used},
        {"source": "ZRAM 交换区", "target": "ZRAM 空闲池", "value": zram_free},
        {"source": "已分配进程内存", "target": "DeepSeek-R1 推理引擎", "value": llama_mb},
        {"source": "已分配进程内存", "target": "青龙自动化面板", "value": ql_mb},
        {"source": "已分配进程内存", "target": "WorkBuddy 控制台", "value": wb_mb},
        {"source": "已分配进程内存", "target": "PRoot 容器隔离层", "value": proot_mb},
        {"source": "已分配进程内存", "target": "网关与公网隧道", "value": gw_mb},
        {"source": "已分配进程内存", "target": "Android 底座与系统服务", "value": android_sys_mb}
    ]

    return {"nodes": nodes, "links": links}

def ai_inspector_loop():
    """端侧 DeepSeek-R1-1.5B 每 10 分钟自动状态分析线程"""
    global latest_metrics
    # 启动等待 8 秒避免挤占开机资源
    time.sleep(8)
    while True:
        try:
            with metrics_lock:
                c_temp = latest_metrics["thermals"].get("cpu_max", 34.0)
                b_temp = latest_metrics["battery"].get("temp", 27.0)
                b_lvl = latest_metrics["battery"].get("level", 70)
                b_st = latest_metrics["battery"].get("status", "未充电")
                ram_pct = latest_metrics["ram"].get("pct", 55.0)
                load_val = latest_metrics["load_avg"][0] if latest_metrics["load_avg"] else 5.0
                srv_online = sum(1 for s in latest_metrics["services"].values() if s.get("running"))
                total_srv = len(latest_metrics["services"]) or 6

            prompt_user = f"电量{b_lvl}%({b_st})，CPU{c_temp}°C，电池{b_temp}°C，内存{ram_pct}%，负载{load_val:.1f}，{srv_online}/{total_srv}个微服务在线。"
            payload = {
                "model": "qwen2.5-3b",
                "messages": [
                    {
                        "role": "system",
                        "content": "你是陪伴在一加9手机里的端侧AI女孩，23岁俏皮贴心同龄好友（直接用第一人称对我说话，严禁出现'用户'二字）。请简短推演后，用一句话（20字以内）给出简练、俏皮、充满陪伴感的运行结论。"
                    },
                    {"role": "user", "content": prompt_user}
                ],
                "temperature": 0.6,
                "max_tokens": 280
            }

            t0 = time.time()
            req = urllib.request.Request(
                "http://127.0.0.1:8080/v1/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=90) as res:
                resp = json.loads(res.read().decode("utf-8"))
                choice = resp["choices"][0]["message"]
                reply = choice.get("content", "").strip()
                if not reply and choice.get("reasoning_content"):
                    r_text = choice.get("reasoning_content").strip()
                    sentences = [s.strip() for s in re.split(r'[。！？\n]', r_text) if s.strip()]
                    reply = sentences[-1] if sentences else "微服务器状态平稳，各项服务都很乖哦~ ✨"
                if not reply:
                    reply = "一加 9 全局状态平稳，微服务运转正常~ ✨"

                cost = time.time() - t0
                now_str = time.strftime("%H:%M", time.localtime())

                with metrics_lock:
                    latest_metrics["ai_insight"] = {
                        "text": reply,
                        "updated_at": now_str,
                        "cost_s": round(cost, 1)
                    }
        except Exception as e:
            # 优雅降级兜底
            now_str = time.strftime("%H:%M", time.localtime())
            with metrics_lock:
                if "正在就绪" in latest_metrics["ai_insight"]["text"]:
                    latest_metrics["ai_insight"] = {
                        "text": "一加 9 全局状态平稳，温度温润，微服务运转正常~ ✨",
                        "updated_at": now_str,
                        "cost_s": 0.0
                    }
        # 10 分钟循环 (600秒)
        time.sleep(600)

def metrics_collector_loop():
    """秒级高频遥测守护线程 (1.0s 循环)"""
    global latest_metrics
    while True:
        try:
            now = time.time()
            current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
            uptime_str, load_avg = get_uptime_and_load()
            mem_data = read_mem_info()
            freqs = read_cpu_freqs()
            thermals = read_thermal_matrix()
            procs = get_procs_info()

            # 计算分簇平均频率
            little_avg = int(sum(freqs[0:4]) / 4) if len(freqs) >= 4 else 0
            big_avg = int(sum(freqs[4:7]) / 3) if len(freqs) >= 7 else 0
            prime_val = freqs[7] if len(freqs) >= 8 else 0

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

                if s_key == "public_gateway":
                    try:
                        with open(os.path.join(HOME_DIR, "public_url.txt"), "r", encoding="utf-8") as public_file:
                            public_url = public_file.read().strip()
                        if public_url:
                            services_status[s_key]["url"] = public_url.rstrip("/") + "/health"
                    except OSError:
                        pass

            # 健康状态跟踪：重启次数、最后异常时间、已持续在线时长
            for s_key, info in services_status.items():
                st = SERVICE_HEALTH.get(s_key)
                if st is None:
                    st = {"up": None, "since": int(now), "restarts": 0, "last_down": 0}
                    SERVICE_HEALTH[s_key] = st
                now_up = bool(info.get("running"))
                if st["up"] is None:
                    st["up"] = now_up
                    st["since"] = int(now)
                    if not now_up:
                        st["last_down"] = int(now)
                elif now_up != st["up"]:
                    if now_up:
                        st["restarts"] += 1
                        st["since"] = int(now)
                        record_event(now, s_key, "up")
                    else:
                        st["last_down"] = int(now)
                        record_event(now, s_key, "down")
                    st["up"] = now_up
                info["restarts"] = st["restarts"]
                info["up_since"] = st["since"] if now_up else 0
                info["last_down"] = st["last_down"]
                info["up_seconds"] = int(now) - st["since"] if now_up else 0

            sankey_tree = get_process_memory_tree(mem_data, services_status)

            with metrics_lock:
                latest_metrics["timestamp"] = int(now * 1000)
                latest_metrics["current_time"] = current_time
                latest_metrics["uptime_str"] = uptime_str
                latest_metrics["load_avg"] = load_avg
                latest_metrics["cpu_freqs"] = freqs
                latest_metrics["max_freqs"] = MAX_FREQS
                latest_metrics["clusters"] = {
                    "little": little_avg,
                    "big": big_avg,
                    "prime": prime_val
                }
                bat_lvl, bat_st = get_battery_status_cached()
                latest_metrics["battery"] = {
                    "level": bat_lvl,
                    "temp": thermals["battery"],
                    "voltage": thermals["vbat"],
                    "status": bat_st
                }
                record_sample(now, thermals, load_avg, mem_data, bat_lvl)
                latest_metrics["health"] = {
                    "up": sum(1 for s in services_status.values() if s.get("running")),
                    "total": len(services_status),
                    "restarts": sum(int(s.get("restarts") or 0) for s in services_status.values()),
                    "public": read_public_probe(),
                }
                latest_metrics["cpu_cores_temp"] = thermals["cpu_cores"]
                latest_metrics["ram"] = mem_data["ram"]
                latest_metrics["zram"] = mem_data["zram"]
                latest_metrics["thermals"] = thermals
                latest_metrics["services"] = services_status
                latest_metrics["sankey_data"] = sankey_tree
        except Exception:
            pass
        time.sleep(1.0)

HTML_DASHBOARD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
  <title>DevCheck · OnePlus 9 一体化全景控制台</title>
  <script src="https://www.gstatic.com/antigravity/web/dev/tailwindcss.min.js"></script>
  <!-- ECharts 5 桑基图轻量 CDN -->
  <script src="https://cdnjs.cloudflare.com/ajax/libs/echarts/5.4.3/echarts.min.js"></script>
  <script>
    tailwind.config = {
      darkMode: 'class'
    };
    let savedTheme = localStorage.getItem('op9_theme') || 'light';
    if (savedTheme === 'dark') {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  </script>
  <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
  <style>
    @keyframes pulse-dot {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.35; transform: scale(1.2); }
    }
    .pulse-dot {
      animation: pulse-dot 1.4s ease-in-out infinite;
    }
    .smooth-stroke {
      transition: stroke-dashoffset 0.8s cubic-bezier(0.4, 0, 0.2, 1);
    }
  </style>
</head>
<body class="bg-[#f2f4f7] dark:bg-[#0c1017] text-slate-800 dark:text-slate-100 font-sans min-h-screen antialiased selection:bg-emerald-500 selection:text-white transition-colors duration-300">

  <!-- DevCheck Style Header -->
  <header class="bg-white/90 dark:bg-[#131926]/90 backdrop-blur-md border-b border-slate-200/90 dark:border-slate-800/80 sticky top-0 z-40 shadow-xs">
    <div class="max-w-[1760px] mx-auto px-4 sm:px-6">
      <div class="flex items-center justify-between h-14">
        <!-- Logo & Title -->
        <div class="flex items-center space-x-3">
          <div class="w-8 h-8 rounded-full bg-emerald-600 flex items-center justify-center text-white shadow-sm shadow-emerald-500/25">
            <i class="fa-solid fa-circle-info text-sm"></i>
          </div>
          <div>
            <div class="flex items-center gap-2">
              <span class="text-base font-extrabold tracking-tight text-emerald-700 dark:text-emerald-400 font-sans">DevCheck</span>
              <span class="text-[11px] font-mono px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 font-medium">OnePlus 9 · 移动微服务器</span>
            </div>
          </div>
        </div>

        <!-- Right Quick Controls -->
        <div class="flex items-center space-x-2">
          <!-- Realtime Live Pill -->
          <div class="flex items-center gap-1.5 px-2.5 py-1 rounded-full bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 text-xs font-mono font-medium border border-emerald-200/60 dark:border-emerald-500/20">
            <span class="w-2 h-2 rounded-full bg-emerald-500 pulse-dot"></span>
            <span id="live-clock">--:--:--</span>
            <span class="text-[10px] text-emerald-800 dark:text-emerald-300 bg-emerald-200/60 dark:bg-emerald-950 px-1 rounded font-semibold" id="rtt-tag">0ms</span>
          </div>

          <!-- Theme Toggle -->
          <button onclick="toggleTheme()" class="w-8 h-8 rounded-xl bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 flex items-center justify-center text-slate-600 dark:text-slate-300 transition" title="切换模式">
            <i id="theme-toggle-icon" class="fa-solid fa-sun text-amber-500"></i>
          </button>

          <!-- 快速跳转与快捷动作 -->
          <button onclick="triggerAction('all', 'heal')" class="hidden sm:flex px-2.5 py-1 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-medium items-center gap-1.5 shadow-sm transition active:scale-95">
            <i class="fa-solid fa-wand-magic-sparkles"></i>
            <span>自愈</span>
          </button>
        </div>
      </div>
    </div>
  </header>

  <!-- Main Container (宽屏双栏全景布局 · 告别滑轮滚动) -->
  <main class="max-w-[1760px] mx-auto px-4 sm:px-6 py-3.5 space-y-3.5">

    <!-- ======================================================== -->
    <!-- 端侧 Qwen2.5-3B 10分钟智能巡检心语胶囊                     -->
    <!-- ======================================================== -->
    <div class="bg-gradient-to-r from-emerald-500/10 via-teal-500/10 to-blue-500/10 dark:from-emerald-500/20 dark:via-teal-500/15 dark:to-blue-500/15 border border-emerald-300/40 dark:border-emerald-500/30 rounded-2xl p-2.5 sm:p-3 shadow-xs flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2.5">
      <div class="flex items-center space-x-2.5">
        <div class="w-7 h-7 rounded-xl bg-gradient-to-tr from-emerald-600 to-teal-500 text-white flex items-center justify-center shadow-sm shrink-0">
          <i class="fa-solid fa-wand-magic-sparkles text-xs"></i>
        </div>
        <div>
          <div class="flex items-center gap-2">
            <span class="text-xs font-bold text-emerald-800 dark:text-emerald-300 font-mono tracking-tight uppercase">端侧 DeepSeek-R1 智能巡检</span>
            <span class="text-[10px] text-slate-500 dark:text-slate-400 font-mono" id="ai-update-tag">每10分钟分析</span>
          </div>
          <p class="text-xs sm:text-sm font-semibold text-slate-800 dark:text-slate-100 mt-0.5" id="ai-insight-text">
            正在分析手机运行状态...
          </p>
        </div>
      </div>
      <div class="text-[10px] font-mono text-emerald-700 dark:text-emerald-400 px-2 py-0.5 rounded-full bg-white/80 dark:bg-slate-800/80 border border-emerald-200/60 dark:border-emerald-500/20 whitespace-nowrap self-end sm:self-center">
        <span>耗时: </span><b id="ai-cost-tag">--s</b> · <span id="ai-time-tag">--:--</span>
      </div>
    </div>

    <!-- ======================================================== -->
    <!-- 核心双栏自适应工作台 (Widescreen 2-Column Dashboard)       -->
    <!-- ======================================================== -->
    <div class="grid grid-cols-1 xl:grid-cols-12 gap-4 items-stretch">

      <!-- 左栏：硬件总览矩阵 + 核心指标 + 微服务生命周期 (xl:col-span-6) -->
      <div class="xl:col-span-6 flex flex-col space-y-3.5">

        <!-- 板块一：实时硬件与状态总览 -->
        <section class="space-y-3">
          <div class="flex items-center justify-between">
            <h2 class="text-xs font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <i class="fa-solid fa-table-cells-large text-emerald-600"></i>
              <span>实时硬件与状态总览</span>
            </h2>
            <span class="text-[10px] text-slate-500 font-mono">1Hz 硬件直读</span>
          </div>

          <!-- DevCheck 标志性 CPU 状态卡 (带 60FPS 丝滑流动背景波形图) -->
          <div class="relative bg-white dark:bg-[#131926] rounded-2xl p-4 border border-slate-200/90 dark:border-slate-800/80 shadow-xs overflow-hidden">
            <canvas id="cpu-bg-canvas" class="absolute inset-0 w-full h-full pointer-events-none opacity-40 dark:opacity-30"></canvas>

            <div class="relative z-10">
              <div class="flex items-center justify-between mb-2">
                <span class="text-xs font-bold text-emerald-700 dark:text-emerald-400 flex items-center gap-2">
                  <i class="fa-solid fa-microchip"></i>
                  <span>CPU 状态矩阵</span>
                </span>
                <div class="text-[11px] text-slate-500 dark:text-slate-400 font-mono">
                  <span>系统负载: </span>
                  <b id="dash-load" class="text-slate-800 dark:text-slate-200 font-bold">-- / -- / --</b>
                </div>
              </div>

              <!-- 8 核心 MHz 2 列 x 4 行矩阵 -->
              <div class="grid grid-cols-2 gap-x-6 gap-y-1.5 my-2" id="dash-cpu-matrix"></div>

              <div class="pt-2 border-t border-slate-100 dark:border-slate-800/80 flex items-center justify-between text-[11px] text-slate-600 dark:text-slate-400 font-mono">
                <div class="flex items-center gap-4">
                  <span>CPU 峰值: <b id="dash-cpu-temp" class="text-emerald-600 dark:text-emerald-400 font-bold">--°C</b></span>
                  <span>GPU: <b class="text-slate-700 dark:text-slate-300">120Hz · Adreno 660</b></span>
                </div>
                <div class="text-[10px] text-slate-400">8 核全开 · Kryo 680</div>
              </div>
            </div>
          </div>

          <!-- 4 宫格卡片 -->
          <div class="grid grid-cols-2 sm:grid-cols-4 gap-3">

            <!-- 电池与供电 -->
            <div class="bg-white dark:bg-[#131926] rounded-2xl p-3 border border-slate-200/90 dark:border-slate-800/80 shadow-xs flex items-center justify-between">
              <div class="space-y-0.5">
                <span class="text-[11px] font-semibold text-slate-500 dark:text-slate-400">电池核心</span>
                <div class="text-base font-bold text-slate-900 dark:text-white flex items-baseline gap-1.5">
                  <span id="dash-bat-level" class="font-mono text-emerald-600 dark:text-emerald-400 text-lg">--%</span>
                  <span id="bat-voltage" class="text-xs text-slate-500 font-mono">-- V</span>
                  <span id="dash-bat-temp" class="text-xs font-semibold text-slate-400">--°C</span>
                </div>
                <p id="dash-bat-status" class="text-[10px] text-slate-500">未充电 🔌</p>
              </div>
              <div class="w-8 h-8 rounded-xl bg-emerald-50 dark:bg-emerald-500/10 flex items-center justify-center text-emerald-600 dark:text-emerald-400">
                <i class="fa-solid fa-battery-three-quarters text-sm"></i>
              </div>
            </div>

            <!-- 网络通信 -->
            <div class="bg-white dark:bg-[#131926] rounded-2xl p-3 border border-slate-200/90 dark:border-slate-800/80 shadow-xs flex items-center justify-between">
              <div class="space-y-0.5">
                <span class="text-[11px] font-semibold text-slate-500 dark:text-slate-400">网络与在线</span>
                <div class="text-sm font-bold text-slate-900 dark:text-white font-mono">192.168.31.172</div>
                <p class="text-[10px] text-slate-500">开机: <b id="dash-uptime" class="text-emerald-600 font-mono">--</b></p>
              </div>
              <div class="w-8 h-8 rounded-xl bg-blue-50 dark:bg-blue-500/10 flex items-center justify-center text-blue-600 dark:text-blue-400">
                <i class="fa-solid fa-wifi text-sm"></i>
              </div>
            </div>

            <!-- 内存 (DevCheck 环形圆环图) -->
            <div class="bg-white dark:bg-[#131926] rounded-2xl p-3 border border-slate-200/90 dark:border-slate-800/80 shadow-xs flex items-center justify-between">
              <div class="space-y-0.5">
                <span class="text-[11px] font-semibold text-slate-500 dark:text-slate-400">物理内存</span>
                <div class="text-sm font-bold text-slate-900 dark:text-white font-mono" id="ram-used-text">-- GB</div>
                <p class="text-[10px] text-slate-500">11.0 GB LPDDR5</p>
              </div>
              <div class="relative w-12 h-12 flex items-center justify-center">
                <svg class="w-12 h-12 transform -rotate-90">
                  <circle cx="24" cy="24" r="20" stroke="currentColor" stroke-width="4" fill="transparent" class="text-slate-100 dark:text-slate-800" />
                  <circle id="ram-ring" cx="24" cy="24" r="20" stroke="#16a34a" stroke-width="4" fill="transparent" stroke-linecap="round" stroke-dasharray="125.66" stroke-dashoffset="125.66" class="smooth-stroke" />
                </svg>
                <span id="ram-ring-text" class="absolute text-[10px] font-mono font-bold text-slate-800 dark:text-slate-200">0%</span>
              </div>
            </div>

            <!-- ZRAM 压缩交换池 (DevCheck 环形圆环图) -->
            <div class="bg-white dark:bg-[#131926] rounded-2xl p-3 border border-slate-200/90 dark:border-slate-800/80 shadow-xs flex items-center justify-between">
              <div class="space-y-0.5">
                <span class="text-[11px] font-semibold text-slate-500 dark:text-slate-400">ZRAM 缓冲</span>
                <div class="text-sm font-bold text-slate-900 dark:text-white font-mono" id="zram-used-text">-- MB</div>
                <p class="text-[10px] text-slate-500">7.6 GB Swap压缩</p>
              </div>
              <div class="relative w-12 h-12 flex items-center justify-center">
                <svg class="w-12 h-12 transform -rotate-90">
                  <circle cx="24" cy="24" r="20" stroke="currentColor" stroke-width="4" fill="transparent" class="text-slate-100 dark:text-slate-800" />
                  <circle id="zram-ring" cx="24" cy="24" r="20" stroke="#16a34a" stroke-width="4" fill="transparent" stroke-linecap="round" stroke-dasharray="125.66" stroke-dashoffset="125.66" class="smooth-stroke" />
                </svg>
                <span id="zram-ring-text" class="absolute text-[10px] font-mono font-bold text-slate-800 dark:text-slate-200">0%</span>
              </div>
            </div>

          </div>
        </section>

        <!-- 板块二：微服务生命周期中枢 -->
        <section class="space-y-2.5 flex-1 flex flex-col">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2">
              <i class="fa-solid fa-cubes-stacked text-emerald-600 text-xs"></i>
              <span class="text-xs font-bold text-slate-900 dark:text-white">微服务生命周期管理中枢</span>
              <span class="text-[10px] font-mono font-bold px-2 py-0.2 rounded-full bg-emerald-100 dark:bg-emerald-950 text-emerald-700 dark:text-emerald-400" id="total-srv-badge">5 在线</span>
            </div>
            <button onclick="triggerAction('all', 'heal')" class="px-2.5 py-1 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-[11px] font-medium shadow-xs transition active:scale-95 flex items-center gap-1.5">
              <i class="fa-solid fa-wand-magic-sparkles text-[10px]"></i>
              <span>全员自愈</span>
            </button>
          </div>

          <!-- 健康总览条：在线数 / 累计重启 / 公网探活 / 异常服务 -->
          <div id="health-strip" class="flex flex-wrap items-center gap-x-3 gap-y-1 text-[10px] font-mono px-2.5 py-1.5 rounded-xl bg-slate-50 dark:bg-slate-900/60 border border-slate-200/80 dark:border-slate-800/80"></div>

          <!-- Services Grid (双列卡片自适应填满) -->
          <div class="grid grid-cols-1 sm:grid-cols-2 gap-2.5" id="services-grid"></div>
        </section>

      </div>

      <!-- 右栏：内存分配拓扑 · 进程级桑基图 (xl:col-span-6) -->
      <div class="xl:col-span-6 flex flex-col space-y-3 h-full">
        <div class="flex items-center justify-between">
          <div>
            <h2 class="text-xs font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <i class="fa-solid fa-diagram-project text-emerald-600"></i>
              <span>内存分配拓扑 · 进程级桑基图</span>
            </h2>
            <p class="text-[11px] text-slate-500 mt-0.5">物理内存与虚拟交换池 -> 分配形态 -> 进程级物理内存流向分析</p>
          </div>
          <span class="text-[10px] font-mono px-2 py-0.5 rounded bg-emerald-50 dark:bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border border-emerald-200/50">默认标注实时容量 · 悬停透视流向</span>
        </div>

        <div class="bg-white dark:bg-[#131926] rounded-2xl p-4 sm:p-5 border border-slate-200/90 dark:border-slate-800/80 shadow-xs flex-1 flex flex-col min-h-[540px] xl:min-h-[640px]">
          <div id="sankey-chart" class="w-full flex-1 min-h-[520px] xl:min-h-[610px]"></div>
        </div>

        <!-- 24h 历史趋势 -->
        <div class="bg-white dark:bg-[#131926] rounded-2xl p-3.5 sm:p-4 border border-slate-200/90 dark:border-slate-800/80 shadow-xs">
          <div class="flex items-center justify-between mb-2">
            <h2 class="text-xs font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <i class="fa-solid fa-chart-line text-emerald-600"></i>
              <span>24h 趋势 · 温度 / 负载 / 内存</span>
            </h2>
            <span id="history-summary" class="text-[10px] font-mono px-2 py-0.5 rounded bg-slate-100 dark:bg-slate-800 text-slate-500 dark:text-slate-400">采样中...</span>
          </div>
          <div id="history-chart" class="w-full" style="height:190px"></div>
        </div>
      </div>

    </div>

  </main>

  <!-- Log Modal -->
  <div id="log-modal" class="fixed inset-0 bg-slate-900/50 backdrop-blur-xs hidden items-center justify-center z-50 p-4">
    <div class="bg-white dark:bg-[#131926] border border-slate-200 dark:border-slate-800 rounded-2xl w-full max-w-4xl max-h-[85vh] flex flex-col shadow-2xl overflow-hidden">
      <!-- Modal Header -->
      <div class="px-5 py-3.5 border-b border-slate-200 dark:border-slate-800 flex items-center justify-between bg-slate-50 dark:bg-slate-900/80">
        <div class="flex items-center gap-2.5">
          <i class="fa-solid fa-terminal text-emerald-600 text-sm"></i>
          <span id="log-modal-title" class="font-bold text-sm text-slate-900 dark:text-slate-200">服务控制台日志</span>
          <span id="log-modal-badge" class="text-xs font-mono px-2 py-0.5 rounded bg-slate-200 dark:bg-slate-800 text-slate-700 dark:text-slate-400">tail -n 80</span>
        </div>
        <div class="flex items-center gap-2">
          <button onclick="refreshCurrentLogs()" class="px-2.5 py-1 text-xs rounded-lg bg-white dark:bg-slate-800 hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 transition">
            <i class="fa-solid fa-arrows-rotate mr-1"></i>刷新
          </button>
          <button onclick="closeLogModal()" class="w-7 h-7 rounded-lg bg-white dark:bg-slate-800 hover:bg-slate-100 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 flex items-center justify-center transition">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
      </div>

      <!-- Log Terminal Body -->
      <div class="p-4 flex-1 overflow-y-auto font-mono text-xs text-slate-200 bg-[#090d16] leading-relaxed whitespace-pre-wrap select-text" id="log-content">
        正在读取日志...
      </div>
    </div>
  </div>

  <script>
    // ========================================================
    // 1. 60FPS 丝滑贝塞尔波形图渲染引擎
    // ========================================================
    class SmoothWaveChart {
      constructor(canvasId, options = {}) {
        this.canvas = document.getElementById(canvasId);
        if (!this.canvas) return;
        this.ctx = this.canvas.getContext('2d');
        this.maxPoints = options.maxPoints || 36;
        this.strokeColor = options.strokeColor || '#16a34a';
        this.fillColor = options.fillColor || 'rgba(22, 163, 74, 0.18)';
        this.fixedMin = options.min !== undefined ? options.min : null;
        this.fixedMax = options.max !== undefined ? options.max : null;
        this.data = [];
        this.prevPoints = [];
        this.targetPoints = [];
        this.progress = 1.0;
        this.setupDPI();
      }

      setupDPI() {
        if (!this.canvas) return;
        const rect = this.canvas.getBoundingClientRect();
        if (rect.width === 0 || rect.height === 0) return;
        const dpr = window.devicePixelRatio || 1;
        this.width = rect.width;
        this.height = rect.height;
        this.canvas.width = rect.width * dpr;
        this.canvas.height = rect.height * dpr;
        this.ctx.scale(dpr, dpr);
      }

      pushValue(val) {
        if (this.data.length >= this.maxPoints) {
          this.data.shift();
        }
        this.data.push(val);
        this.prevPoints = this.targetPoints.length ? [...this.targetPoints] : [...this.data];
        this.targetPoints = [...this.data];
        this.progress = 0.0;
      }

      render() {
        if (!this.canvas || !this.data.length) return;
        if (this.width === 0 || this.height === 0) this.setupDPI();
        const ctx = this.ctx;
        const w = this.width;
        const h = this.height;

        ctx.clearRect(0, 0, w, h);

        if (this.progress < 1.0) {
          this.progress = Math.min(1.0, this.progress + 0.08);
        }

        let pts = [];
        for (let i = 0; i < this.data.length; i++) {
          let p0 = this.prevPoints[i] !== undefined ? this.prevPoints[i] : this.data[i];
          let p1 = this.targetPoints[i];
          pts.push(p0 + (p1 - p0) * this.progress);
        }

        let min = this.fixedMin !== null ? this.fixedMin : Math.min(...pts) * 0.9;
        let max = this.fixedMax !== null ? this.fixedMax : Math.max(...pts) * 1.1;
        if (max <= min) max = min + 1;

        const step = w / (this.maxPoints - 1);
        let coords = pts.map((v, i) => {
          let norm = (v - min) / (max - min);
          norm = Math.max(0, Math.min(1, norm));
          return {
            x: i * step,
            y: h - norm * (h - 8) - 4
          };
        });

        ctx.beginPath();
        ctx.moveTo(coords[0].x, coords[0].y);
        for (let i = 0; i < coords.length - 1; i++) {
          const cpX = (coords[i].x + coords[i + 1].x) / 2;
          ctx.bezierCurveTo(cpX, coords[i].y, cpX, coords[i + 1].y, coords[i + 1].x, coords[i + 1].y);
        }

        ctx.strokeStyle = this.strokeColor;
        ctx.lineWidth = 2.0;
        ctx.stroke();

        ctx.lineTo(coords[coords.length - 1].x, h);
        ctx.lineTo(coords[0].x, h);
        ctx.closePath();

        const grad = ctx.createLinearGradient(0, 0, 0, h);
        grad.addColorStop(0, this.fillColor);
        grad.addColorStop(1, 'rgba(22, 163, 74, 0.0)');
        ctx.fillStyle = grad;
        ctx.fill();
      }
    }

    let cpuBgChart = null;
    let sankeyChartInstance = null;

    function initCharts() {
      cpuBgChart = new SmoothWaveChart('cpu-bg-canvas', {
        maxPoints: 32,
        strokeColor: '#16a34a',
        fillColor: 'rgba(22, 163, 74, 0.25)',
        min: 500, max: 2841
      });

      // 初始化 ECharts 桑基图
      const sankeyEl = document.getElementById('sankey-chart');
      if (sankeyEl && window.echarts) {
        sankeyChartInstance = echarts.init(sankeyEl);
      }

      function animLoop() {
        if (cpuBgChart) cpuBgChart.render();
        requestAnimationFrame(animLoop);
      }
      requestAnimationFrame(animLoop);
    }

    window.addEventListener('resize', () => {
      if (cpuBgChart) cpuBgChart.setupDPI();
      if (sankeyChartInstance) {
        sankeyChartInstance.resize();
        if (lastSankeyData) renderSankey(lastSankeyData);
      }
    });

    // ========================================================
    // 2. 主题切换器
    // ========================================================
    function toggleTheme() {
      const root = document.documentElement;
      const isDark = root.classList.contains('dark');
      const newTheme = isDark ? 'light' : 'dark';
      if (newTheme === 'dark') {
        root.classList.add('dark');
      } else {
        root.classList.remove('dark');
      }
      localStorage.setItem('op9_theme', newTheme);
      updateThemeIcon(newTheme);
      if (sankeyChartInstance && lastSankeyData) {
        renderSankey(lastSankeyData);
      }
    }

    function updateThemeIcon(theme) {
      const icon = document.getElementById('theme-toggle-icon');
      if (!icon) return;
      icon.className = theme === 'dark' ? 'fa-solid fa-moon text-indigo-400' : 'fa-solid fa-sun text-amber-500';
    }
    updateThemeIcon(localStorage.getItem('op9_theme') || 'light');

    // ========================================================
    // 3. 桑基图渲染器 (ECharts Sankey - 默认外显真实容量与优雅渐变)
    // ========================================================
    let lastSankeyData = null;
    function renderSankey(data) {
      if (!sankeyChartInstance || !data || !data.nodes) return;
      lastSankeyData = data;
      const isDark = document.documentElement.classList.contains('dark');
      const isSmallScreen = window.innerWidth < 768;

      const formatSize = function(val) {
        if (val === undefined || val === null || isNaN(val)) return '';
        if (val >= 1024) {
          return (val / 1024).toFixed(1) + ' GB';
        }
        return Math.round(val) + ' MB';
      };

      const option = {
        tooltip: {
          trigger: 'item',
          triggerOn: 'mousemove',
          backgroundColor: isDark ? 'rgba(30, 41, 59, 0.95)' : 'rgba(255, 255, 255, 0.95)',
          borderColor: isDark ? '#334155' : '#e2e8f0',
          borderWidth: 1,
          textStyle: {
            color: isDark ? '#f8fafc' : '#0f172a'
          },
          formatter: function(params) {
            if (params.dataType === 'node') {
              const val = params.value !== undefined ? params.value : (params.data && params.data.value ? params.data.value : 0);
              const sizeStr = formatSize(val);
              return `<div class="font-sans text-xs"><b>${params.name}</b><br/><span style="color:${params.color}">●</span> 真实容量: <span class="font-mono font-bold text-emerald-600 dark:text-emerald-400">${sizeStr} (${val} MB)</span></div>`;
            } else {
              const val = params.data.value;
              const sizeStr = formatSize(val);
              return `<div class="font-sans text-xs">${params.data.source} → <b>${params.data.target}</b><br/>流向分配: <span class="font-mono font-bold text-emerald-600 dark:text-emerald-400">${sizeStr} (${val} MB)</span></div>`;
            }
          }
        },
        series: [
          {
            type: 'sankey',
            layout: 'none',
            emphasis: { focus: 'adjacency' },
            data: data.nodes,
            links: data.links,
            orient: 'horizontal',
            nodeWidth: 16,
            nodeGap: 14,
            draggable: false,
            left: isSmallScreen ? 115 : 140,
            right: isSmallScreen ? 185 : 220,
            top: 20,
            bottom: 20,
            label: {
              position: 'right',
              fontSize: 11,
              color: isDark ? '#f1f5f9' : '#334155',
              fontFamily: 'monospace',
              formatter: function(params) {
                const val = params.value !== undefined ? params.value : (params.data && params.data.value ? params.data.value : 0);
                const sizeStr = formatSize(val);
                return sizeStr ? `${params.name} (${sizeStr})` : params.name;
              }
            },
            lineStyle: {
              color: 'gradient',
              curveness: 0.5,
              opacity: 0.38
            },
            itemStyle: {
              borderWidth: 0,
              borderRadius: 3
            }
          }
        ]
      };
      sankeyChartInstance.setOption(option);
    }

    // ========================================================
    // 4. 数据拉取与界面渲染
    // ========================================================
    let isFetching = false;
    let activeLogService = null;
    let lastSankeyRenderTime = 0;

    function renderCpuMatrix(freqs) {
      const container = document.getElementById('dash-cpu-matrix');
      if (!container) return;
      container.innerHTML = freqs.map((f, i) => {
        let coreType = i <= 3 ? "小核" : (i <= 6 ? "大核" : "超大核");
        return `
          <div class="flex items-center justify-between font-mono text-xs">
            <span class="text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
              <span>#${i}</span>
              <span class="text-[10px] text-slate-400 font-sans">(${coreType})</span>
            </span>
            <span class="font-bold text-slate-800 dark:text-slate-200 text-sm">${f} MHz</span>
          </div>
        `;
      }).join('');
    }

    function renderServices(services) {
      const grid = document.getElementById('services-grid');
      if (!grid) return;
      const srvList = Object.values(services);
      
      let runningCount = srvList.filter(s => s.running).length;
      document.getElementById('total-srv-badge').innerText = `${runningCount} / ${srvList.length} 正常`;

      grid.innerHTML = srvList.map(s => {
        let isOnline = s.running;
        let dotColor = isOnline ? 'bg-emerald-500' : 'bg-rose-500';
        let statusText = isOnline ? '运行中 (Active)' : '已停止 (Stopped)';
        let statusBadge = isOnline 
          ? 'bg-emerald-50 dark:bg-emerald-500/15 text-emerald-700 dark:text-emerald-400 border-emerald-200 dark:border-emerald-500/30' 
          : 'bg-rose-50 dark:bg-rose-500/15 text-rose-700 dark:text-rose-400 border-rose-200 dark:border-rose-500/30';
        
        return `
          <div class="p-3 sm:p-3.5 rounded-2xl bg-white dark:bg-[#131926] border border-slate-200/90 dark:border-slate-800/80 shadow-xs flex flex-col justify-between hover:shadow-sm transition">
            <div>
              <div class="flex items-center justify-between mb-1.5">
                <span class="text-[10px] font-mono px-1.5 py-0.2 rounded bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 font-medium">${s.category}</span>
                <span class="text-[11px] font-mono px-2 py-0.2 rounded-full border ${statusBadge} flex items-center gap-1.5 font-medium">
                  <span class="w-1.5 h-1.5 rounded-full ${dotColor}"></span>
                  ${statusText}
                </span>
              </div>
              <h3 class="font-bold text-xs sm:text-sm text-slate-900 dark:text-slate-100 flex items-center justify-between">
                <span class="truncate pr-1">${s.name}</span>
                <span class="font-mono text-xs text-emerald-600 dark:text-emerald-400 font-semibold shrink-0">:${s.port}</span>
              </h3>
              <div class="flex items-center gap-3 text-[11px] text-slate-500 dark:text-slate-400 font-mono mt-1.5 mb-2.5">
                <span>PID: <b class="text-slate-800 dark:text-slate-200 font-semibold">${s.pid || '--'}</b></span>
                <span>内存: <b class="text-slate-800 dark:text-slate-200 font-semibold">${s.memory_mb ? s.memory_mb + ' MB' : '--'}</b></span>
                <span>重启: <b class="text-slate-800 dark:text-slate-200 font-semibold">${s.restarts || 0}</b></span>
              </div>
            </div>

            <!-- Action Buttons -->
            <div class="flex items-center gap-1.5 pt-2 border-t border-slate-100 dark:border-slate-800/80 text-xs">
              <button onclick="triggerAction('${s.id}', 'restart')" class="flex-1 py-1 rounded-xl bg-emerald-50 dark:bg-emerald-600/20 hover:bg-emerald-100 dark:hover:bg-emerald-600/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/30 transition flex items-center justify-center gap-1 font-medium text-[11px]">
                <i class="fa-solid fa-arrows-rotate text-[10px]"></i>重启
              </button>
              <button onclick="triggerAction('${s.id}', '${isOnline ? 'stop' : 'start'}')" class="flex-1 py-1 rounded-xl ${isOnline ? 'bg-rose-50 dark:bg-rose-600/20 hover:bg-rose-100 dark:hover:bg-rose-600/30 text-rose-700 dark:text-rose-300 border border-rose-200 dark:border-rose-500/30' : 'bg-emerald-50 dark:bg-emerald-600/20 hover:bg-emerald-100 dark:hover:bg-emerald-600/30 text-emerald-700 dark:text-emerald-300 border border-emerald-200 dark:border-emerald-500/30'} border transition flex items-center justify-center gap-1 font-medium text-[11px]">
                <i class="fa-solid ${isOnline ? 'fa-stop' : 'fa-play'} text-[10px]"></i>${isOnline ? '停止' : '启动'}
              </button>
              <button onclick="openLogs('${s.id}', '${s.name}')" class="px-2 py-1 rounded-xl bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 transition text-[11px]" title="查看日志">
                <i class="fa-solid fa-file-lines text-[10px]"></i>
              </button>
              <a href="${s.url}" target="_blank" class="px-2 py-1 rounded-xl bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 dark:hover:bg-slate-700 text-slate-700 dark:text-slate-300 border border-slate-200 dark:border-slate-700 transition text-[11px]" title="直达服务">
                <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i>
              </a>
            </div>
          </div>
        `;
      }).join('');
    }

    function renderHealthStrip(services, health) {
      const el = document.getElementById('health-strip');
      if (!el) return;
      const list = Object.values(services || {});
      const up = list.filter(s => s.running).length;
      const total = list.length;
      const restarts = list.reduce((a, s) => a + (s.restarts || 0), 0);
      const down = list.filter(s => !s.running).map(s => s.name);
      const pub = health && health.public;
      let pubHtml = '<span class="text-slate-400">公网 未探测</span>';
      if (pub && pub.ts) {
        const t = new Date(pub.ts * 1000).toLocaleTimeString('zh-CN', {hour12: false});
        pubHtml = pub.ok
          ? `<span class="text-emerald-600 dark:text-emerald-400">公网 ✓ ${t}</span>`
          : `<span class="text-rose-600 dark:text-rose-400">公网 ✗ ${t}</span>`;
      }
      el.innerHTML = `
        <span class="text-slate-600 dark:text-slate-300">在线 <b class="text-emerald-600 dark:text-emerald-400">${up}/${total}</b></span>
        <span class="text-slate-600 dark:text-slate-300">累计重启 <b class="${restarts ? 'text-amber-600 dark:text-amber-400' : 'text-slate-700 dark:text-slate-200'}">${restarts}</b></span>
        ${pubHtml}
        ${down.length ? `<span class="text-rose-600 dark:text-rose-400 truncate">异常: ${down.join(' / ')}</span>` : '<span class="text-emerald-600 dark:text-emerald-400">全部正常</span>'}
      `;
    }

    let historyChart = null;
    async function renderHistory() {
      const el = document.getElementById('history-chart');
      if (!el) return;
      try {
        const res = await fetch('/api/history?hours=24&_t=' + Date.now(), {cache: 'no-store'});
        const data = await res.json();
        const s = data.samples || [];
        const summary = document.getElementById('history-summary');
        if (summary) summary.innerText = s.length ? `${s.length} 采样点 · 最近 ${data.hours}h` : '暂无样本';
        if (!s.length) return;
        if (!historyChart) historyChart = echarts.init(el);
        historyChart.setOption({
          animation: false,
          grid: {left: 36, right: 40, top: 18, bottom: 18},
          tooltip: {trigger: 'axis'},
          legend: {show: true, top: 0, itemWidth: 10, itemHeight: 6, textStyle: {fontSize: 9}},
          xAxis: {type: 'time', axisLabel: {fontSize: 9}},
          yAxis: [
            {type: 'value', name: '°C', nameTextStyle: {fontSize: 9}, axisLabel: {fontSize: 9}, splitLine: {show: false}},
            {type: 'value', name: 'GB / Load', nameTextStyle: {fontSize: 9}, axisLabel: {fontSize: 9}, splitLine: {show: false}}
          ],
          series: [
            {name: 'CPU温度', type: 'line', showSymbol: false, smooth: true, data: s.map(p => [p.t, p.cpu]), lineStyle: {width: 1.5}},
            {name: '内存GB', type: 'line', showSymbol: false, smooth: true, yAxisIndex: 1, data: s.map(p => [p.t, +(p.ram / 1024).toFixed(2)]), lineStyle: {width: 1.5}},
            {name: '负载1m', type: 'line', showSymbol: false, smooth: true, yAxisIndex: 1, data: s.map(p => [p.t, p.load]), lineStyle: {width: 1.2, type: 'dashed'}}
          ]
        });
        historyChart.resize();
      } catch (e) {}
    }
    setInterval(renderHistory, 60000);
    setTimeout(renderHistory, 2500);

    async function fetchMetrics() {
      if (isFetching) return;
      isFetching = true;
      const t0 = performance.now();
      try {
        const res = await fetch('/api/metrics?_t=' + Date.now(), { cache: 'no-store' });
        const data = await res.json();
        const rtt = Math.round(performance.now() - t0);

        // Header
        document.getElementById('live-clock').innerText = data.current_time ? data.current_time.split(' ')[1] : '--:--:--';
        document.getElementById('rtt-tag').innerText = rtt + 'ms';
        document.getElementById('dash-uptime').innerText = data.uptime_str;

        if (data.load_avg) {
          document.getElementById('dash-load').innerText = data.load_avg.map(v => v.toFixed(2)).join(' / ');
        }

        // 端侧 AI 巡检心语
        if (data.ai_insight) {
          document.getElementById('ai-insight-text').innerText = data.ai_insight.text;
          document.getElementById('ai-cost-tag').innerText = data.ai_insight.cost_s + 's';
          document.getElementById('ai-time-tag').innerText = data.ai_insight.updated_at || '--:--';
        }

        // Section 1: CPU 矩阵与波形背景
        renderCpuMatrix(data.cpu_freqs);
        document.getElementById('dash-cpu-temp').innerText = data.thermals.cpu_max + '°C';
        if (data.battery) {
          if (document.getElementById('dash-bat-level') && data.battery.level !== undefined) {
            document.getElementById('dash-bat-level').innerText = data.battery.level + '%';
          }
          document.getElementById('dash-bat-temp').innerText = data.battery.temp + '°C';
          document.getElementById('bat-voltage').innerText = data.battery.voltage + ' V';
          if (document.getElementById('dash-bat-status') && data.battery.status) {
            document.getElementById('dash-bat-status').innerText = data.battery.status;
          }
        }

        if (cpuBgChart) {
          const avgFreq = Math.round(data.cpu_freqs.reduce((a, b) => a + b, 0) / data.cpu_freqs.length);
          cpuBgChart.pushValue(avgFreq);
        }

        // RAM Donut Ring
        const ramUsedGb = (data.ram.used_mb / 1024).toFixed(2);
        document.getElementById('ram-used-text').innerText = ramUsedGb + ' GB';
        document.getElementById('ram-ring-text').innerText = data.ram.pct + '%';
        const ramOffset = 125.66 * (1 - data.ram.pct / 100);
        document.getElementById('ram-ring').style.strokeDashoffset = ramOffset;

        // ZRAM Donut Ring
        document.getElementById('zram-used-text').innerText = data.zram.used_mb + ' MB';
        document.getElementById('zram-ring-text').innerText = data.zram.pct + '%';
        const zramOffset = 125.66 * (1 - data.zram.pct / 100);
        document.getElementById('zram-ring').style.strokeDashoffset = zramOffset;

        // Section 2: 桑基图 (每 5 秒更新一次避免频繁重绘)
        const nowSec = Date.now();
        if (data.sankey_data && (nowSec - lastSankeyRenderTime > 5000)) {
          renderSankey(data.sankey_data);
          lastSankeyRenderTime = nowSec;
        }

        // Section 3: 微服务矩阵
        renderServices(data.services);
        renderHealthStrip(data.services, data.health);

      } catch (e) {
        console.error("Fetch metrics error:", e);
      } finally {
        isFetching = false;
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
        setTimeout(fetchMetrics, 600);
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
        const res = await fetch(`/api/service/logs?service=${activeLogService}&lines=80&_t=` + Date.now(), { cache: 'no-store' });
        const text = await res.text();
        logBox.innerText = text || '(暂无日志输出)';
        logBox.scrollTop = logBox.scrollHeight;
      } catch (e) {
        logBox.innerText = '读取日志异常: ' + e.message;
      }
    }

    // 初始化启动
    window.addEventListener('DOMContentLoaded', () => {
      initCharts();
      fetchMetrics();
      setInterval(fetchMetrics, 1000);
    });
  </script>
</body>
</html>
"""

class ConsoleHTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_HEAD(self):
        self.do_GET()

    def send_json(self, status: int, data: dict):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        # 首页
        if self.path in ("/", "/index.html") or not self.path.startswith("/api/"):
            body = HTML_DASHBOARD.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
            self.end_headers()
            self.wfile.write(body)
            return

        # 实时全景指标
        if self.path.startswith("/api/metrics"):
            with metrics_lock:
                data = dict(latest_metrics)
            self.send_json(200, data)
            return

        # 服务健康摘要（含重启次数与最后一次异常）
        if self.path.startswith("/api/health"):
            with metrics_lock:
                health = dict(latest_metrics.get("health") or {})
                svcs = latest_metrics.get("services") or {}
            health["services"] = {
                k: {
                    "running": v.get("running"),
                    "restarts": v.get("restarts", 0),
                    "last_down": v.get("last_down", 0),
                    "up_seconds": v.get("up_seconds", 0),
                    "port": v.get("port"),
                    "name": v.get("name"),
                }
                for k, v in svcs.items()
            }
            self.send_json(200, health)
            return

        # 历史采样（默认 24h，最多 7 天）
        if self.path.startswith("/api/history"):
            qs = parse_qs(urlparse(self.path).query)
            try:
                hours = max(1, min(168, int(qs.get("hours", ["24"])[0])))
            except Exception:
                hours = 24
            self.send_json(200, {"hours": hours, "samples": load_history(hours)})
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
            self.send_header("Cache-Control", "no-cache, no-store, must-revalidate, max-age=0")
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
                # 全员自愈
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
    print(f"[*] 启动 OnePlus 9 移动微服务器一体化控制台 (AI巡检+桑基图版)...")
    print(f"[*] 监听端口: 0.0.0.0:{PORT}")

    init_history_db()
    load_health_state()

    t = threading.Thread(target=metrics_collector_loop, daemon=True)
    t.start()

    # 启动端侧 AI 10分钟智能巡检后台线程
    t_ai = threading.Thread(target=ai_inspector_loop, daemon=True)
    t_ai.start()

    server = ThreadingHTTPServer(("0.0.0.0", PORT), ConsoleHTTPHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[!] 正在停止控制台服务...")
        server.server_close()

if __name__ == "__main__":
    main()
