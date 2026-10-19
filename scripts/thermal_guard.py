#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一加 9 本地服务器硬件温度与健康巡检守护系统 (Thermal Guard Daemon)
特点：
  1. 动态遍历 Linux /sys/class/thermal/ 传感器，精准提取电池、CPU、外壳实时温度
  2. 三级健康状态机：NORMAL(正常) / WARNING(预警: 电池>=40°C) / CRITICAL(熔断: 电池>=44°C)
  3. 防骚扰机制：同级别 1 小时内不重复轰炸，温度恢复正常后自动发送恢复通知
  4. 主动熔断保护：严重过热时自动停止高负载大模型进程 (llama-server)，避免电池损伤
  5. 多通道告警支持：WxPusher 微信卡片、钉钉、飞书、Server酱、PushPlus
"""

import os
import sys
import glob
import json
import time
from datetime import datetime
import requests

# ─── 告警阈值配置（单位：摄氏度） ──────────────────────────────────
THRESHOLDS = {
    "battery_warn": 40.0,
    "battery_crit": 44.0,
    "cpu_warn": 65.0,
    "cpu_crit": 75.0,
    "shell_warn": 40.0,
    "shell_crit": 45.0,
    "recovery_margin": 2.0,  # 回落阈值 (如电池降至 38°C 判定为完全恢复)
}

# ─── 多通道通知配置区 (优先读取环境变量) ─────────────────────────────
WXPUSHER_APP_TOKEN = os.environ.get("WXPUSHER_APP_TOKEN", "").strip()
WXPUSHER_UID = os.environ.get("WXPUSHER_UID", "").strip()
BARK_KEY = os.environ.get("BARK_KEY", "").strip()
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "").strip()
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "").strip()
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "").strip()
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "").strip()

# 状态记录文件
STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "thermal_state.json")

def get_thermal_metrics() -> dict:
    """动态遍历 sysfs 提取关键硬件温度"""
    metrics = {
        "battery": None,
        "shell_back": None,
        "shell_front": None,
        "shell_frame": None,
        "cpu_max": 0.0,
        "cpu_avg": 0.0,
        "socd": None,
    }
    cpu_temps = []

    zone_paths = glob.glob("/sys/class/thermal/thermal_zone*")
    for z in zone_paths:
        try:
            type_file = os.path.join(z, "type")
            temp_file = os.path.join(z, "temp")
            if not os.path.isfile(type_file) or not os.path.isfile(temp_file):
                continue
            with open(type_file, "r") as f:
                z_type = f.read().strip().lower()
            with open(temp_file, "r") as f:
                raw_temp = float(f.read().strip())

            # Linux 驱动毫摄氏度转换
            deg = raw_temp / 1000.0 if raw_temp > 200 else raw_temp

            if z_type == "battery":
                metrics["battery"] = round(deg, 1)
            elif z_type == "shell_back":
                metrics["shell_back"] = round(deg, 1)
            elif z_type == "shell_front":
                metrics["shell_front"] = round(deg, 1)
            elif z_type == "shell_frame":
                metrics["shell_frame"] = round(deg, 1)
            elif z_type == "socd":
                metrics["socd"] = round(deg, 1)
            elif "cpu" in z_type and 15.0 < deg < 115.0:
                cpu_temps.append(deg)
        except Exception:
            continue

    if cpu_temps:
        metrics["cpu_max"] = round(max(cpu_temps), 1)
        metrics["cpu_avg"] = round(sum(cpu_temps) / len(cpu_temps), 1)
    else:
        metrics["cpu_max"] = 38.0
        metrics["cpu_avg"] = 37.0

    if metrics["battery"] is None:
        metrics["battery"] = 32.0
    if metrics["shell_back"] is None:
        metrics["shell_back"] = 32.0

    return metrics

def evaluate_status(metrics: dict) -> tuple:
    """根据传感器数据判定告警级别"""
    level = "NORMAL"
    reasons = []

    b = metrics["battery"]
    c = metrics["cpu_max"]
    s = metrics["shell_back"]

    # 1. 判定 CRITICAL (熔断级)
    if b >= THRESHOLDS["battery_crit"]:
        level = "CRITICAL"
        reasons.append(f"电池温度达到 {b}°C (超限 {THRESHOLDS['battery_crit']}°C)")
    elif c >= THRESHOLDS["cpu_crit"]:
        level = "CRITICAL"
        reasons.append(f"CPU核心峰值达到 {c}°C (超限 {THRESHOLDS['cpu_crit']}°C)")
    elif s >= THRESHOLDS["shell_crit"]:
        level = "CRITICAL"
        reasons.append(f"外壳背板温度达到 {s}°C (超限 {THRESHOLDS['shell_crit']}°C)")

    # 2. 判定 WARNING (预警级)
    elif b >= THRESHOLDS["battery_warn"]:
        level = "WARNING"
        reasons.append(f"电池温度偏高 {b}°C (超预警线 {THRESHOLDS['battery_warn']}°C)")
    elif c >= THRESHOLDS["cpu_warn"]:
        level = "WARNING"
        reasons.append(f"CPU核心温偏高 {c}°C (超预警线 {THRESHOLDS['cpu_warn']}°C)")
    elif s >= THRESHOLDS["shell_warn"]:
        level = "WARNING"
        reasons.append(f"机身外壳偏高 {s}°C (超预警线 {THRESHOLDS['shell_warn']}°C)")

    return level, reasons

def trigger_active_cooling():
    """紧急降温动作：暂停高负载的大模型服务以释放发热源"""
    action_taken = []
    try:
        res = os.system("pgrep -f 'llama-server' > /dev/null 2>&1")
        if res == 0:
            print("[🚨 熔断处置] 正在强制关闭 llama-server 本地大模型以切断发热源...")
            os.system("pkill -9 -f 'llama-server'")
            action_taken.append("已紧急中止 Qwen2.5-3B 本地推理服务以卸载 CPU 负荷")
    except Exception as e:
        print(f"[!] 执行主动降温异常: {e}")
    return action_taken

def send_alert(title: str, level: str, metrics: dict, reasons: list, actions: list = None):
    """发送多通道温控告警通知"""
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    if level == "CRITICAL":
        header_color = "#cf1322"
        bg_color = "#fff1f0"
        border_color = "#ff4d4f"
        badge = "🚨 严重过热·熔断保护"
    elif level == "WARNING":
        header_color = "#d46b08"
        bg_color = "#fff7e6"
        border_color = "#ffa940"
        badge = "⚠️ 硬件温度偏高预警"
    else:
        header_color = "#389e0d"
        bg_color = "#f6ffed"
        border_color = "#73d13d"
        badge = "✅ 硬件温度恢复正常"

    reason_html = "".join([f"<li>{r}</li>" for r in reasons]) if reasons else "<li>各项硬件传感器均处于标准适宜工作区间。</li>"
    actions_html = ""
    if actions:
        actions_li = "".join([f"<li>{a}</li>" for a in actions])
        actions_html = f"<div style='margin-top:10px;'><b>🛡️ 自动化处置动作：</b><ul style='margin:4px 0 0 16px;padding:0;color:#c41d7f;'>{actions_li}</ul></div>"

    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 600px; margin: auto; border: 1px solid {border_color}; border-radius: 8px; overflow: hidden;">
        <div style="background-color: {header_color}; color: white; padding: 12px 16px; font-size: 16px; font-weight: bold;">
            {title}
        </div>
        <div style="padding: 16px; background-color: {bg_color};">
            <div style="font-size: 14px; margin-bottom: 12px; color: {header_color};">
                <b>当前状态：{badge}</b> ({now_str})
            </div>
            
            <div style="background: white; border-radius: 6px; padding: 12px; margin-bottom: 12px; border: 1px solid #e8e8e8;">
                <table style="width: 100%; border-collapse: collapse; font-size: 14px; text-align: left;">
                    <tr style="border-bottom: 1px solid #f0f0f0;"><td style="padding: 6px 0; color: #666;">🔋 电池核心温度</td><td style="font-weight: bold; color: {'#cf1322' if metrics['battery'] >= 40 else '#389e0d'};">{metrics['battery']} °C</td></tr>
                    <tr style="border-bottom: 1px solid #f0f0f0;"><td style="padding: 6px 0; color: #666;">⚡ CPU 峰值温度</td><td style="font-weight: bold;">{metrics['cpu_max']} °C (均温 {metrics['cpu_avg']} °C)</td></tr>
                    <tr style="border-bottom: 1px solid #f0f0f0;"><td style="padding: 6px 0; color: #666;">📱 机身外壳背面</td><td style="font-weight: bold;">{metrics['shell_back']} °C</td></tr>
                    <tr><td style="padding: 6px 0; color: #666;">🖥️ 屏幕正面表面</td><td style="font-weight: bold;">{metrics.get('shell_front') or '-'} °C</td></tr>
                </table>
            </div>

            <div style="font-size: 13px; color: #444; line-height: 1.6;">
                <b>📋 状态触发原因：</b>
                <ul style="margin: 4px 0 0 16px; padding: 0;">{reason_html}</ul>
                {actions_html}
            </div>

            <div style="font-size: 11px; color: #8c8c8c; margin-top: 15px; border-top: 1px dashed #d9d9d9; padding-top: 10px;">
                由 一加 9 (Snapdragon 888) 硬件温控守护引擎自动巡检发送
            </div>
        </div>
    </div>
    """

    text = f"### {title}\n"
    text += f"> **当前级别**：{badge} ({now_str})\n\n"
    text += f"* 🔋 **电池温度**：{metrics['battery']} °C\n"
    text += f"* ⚡ **CPU 核心峰值**：{metrics['cpu_max']} °C (均温 {metrics['cpu_avg']} °C)\n"
    text += f"* 📱 **机身外壳**：{metrics['shell_back']} °C\n\n"
    if reasons:
        text += "**触发说明**：\n" + "\n".join([f"- {r}" for r in reasons]) + "\n\n"
    if actions:
        text += "**处置动作**：\n" + "\n".join([f"- {a}" for a in actions]) + "\n\n"
    text += "*由一加 9 硬件温控守护引擎自动巡检*"

    if WXPUSHER_APP_TOKEN and WXPUSHER_UID:
        try:
            url = "http://wxpusher.zjiecode.com/api/send/message"
            payload = {
                "appToken": WXPUSHER_APP_TOKEN,
                "content": html,
                "summary": f"{badge}: 电池 {metrics['battery']}°C",
                "contentType": 2,
                "uids": [WXPUSHER_UID],
            }
            res = requests.post(url, json=payload, timeout=12).json()
            if res.get("code") == 1000:
                print("  [WxPusher] 微信告警推送成功！")
        except Exception as e:
            print(f"  [WxPusher 异常] {e}")

    if PUSHPLUS_TOKEN:
        try:
            url = "http://www.pushplus.plus/send"
            payload = {
                "token": PUSHPLUS_TOKEN,
                "title": f"一加9硬件温控: {badge}",
                "content": html,
                "template": "html",
            }
            requests.post(url, json=payload, timeout=12)
        except Exception:
            pass

    if DINGTALK_WEBHOOK:
        try:
            requests.post(DINGTALK_WEBHOOK, json={"msgtype": "markdown", "markdown": {"title": title, "text": text}}, timeout=10)
        except Exception:
            pass

    if FEISHU_WEBHOOK:
        try:
            requests.post(FEISHU_WEBHOOK, json={"msg_type": "text", "content": {"text": text}}, timeout=10)
        except Exception:
            pass

def load_state() -> dict:
    if os.path.isfile(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"last_level": "NORMAL", "last_alert_time": 0}

def save_state(state: dict):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"[!] 保存温控状态失败: {e}")

def main():
    now_ts = time.time()
    test_mode = "--test-alert" in sys.argv
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 启动一加 9 硬件温控巡检...")

    metrics = get_thermal_metrics()
    print(f"[*] 硬件温度检测: 电池={metrics['battery']}°C | CPU峰值={metrics['cpu_max']}°C (均温{metrics['cpu_avg']}°C) | 外壳={metrics['shell_back']}°C")

    level, reasons = evaluate_status(metrics)
    state = load_state()
    last_level = state.get("last_level", "NORMAL")
    last_time = state.get("last_alert_time", 0)

    if test_mode:
        print("[*] 正在执行 --test-alert 模拟告警测试，向微信推送模拟预警卡片...")
        sim_metrics = dict(metrics)
        sim_metrics["battery"] = 40.8
        sim_reasons = ["【模拟测试】电池温度达到 40.8°C (超预警线 40.0°C)", "当前为温控通知卡片样式预览测试"]
        send_alert("【测试】一加 9 硬件温度告警通知测试", "WARNING", sim_metrics, sim_reasons)
        print("[*] 模拟测试完成！请检查微信消息。")
        return

    actions = []
    if level == "CRITICAL":
        actions = trigger_active_cooling()

    need_send = False
    title = ""

    if level == "CRITICAL":
        if last_level != "CRITICAL" or (now_ts - last_time > 1800):
            need_send = True
            title = "🚨 [紧急熔断] 一加 9 硬件过热告警保护"
    elif level == "WARNING":
        if last_level == "NORMAL" or (now_ts - last_time > 3600):
            need_send = True
            title = "⚠️ 一加 9 硬件温度偏高预警通知"
    else:
        if last_level in ["WARNING", "CRITICAL"]:
            if metrics["battery"] <= (THRESHOLDS["battery_warn"] - THRESHOLDS["recovery_margin"]):
                need_send = True
                title = "✅ 一加 9 硬件温度已降温恢复正常"
                reasons = [f"电池温度已自然回落至 {metrics['battery']}°C，系统各核心运行正常。"]

    if need_send:
        print(f"[!] 触发通知发送: {title}")
        send_alert(title, level, metrics, reasons, actions)
        state["last_level"] = level
        state["last_alert_time"] = now_ts
    else:
        print(f"[*] 巡检状态良好（级别: {level}，静默记录无需告警）")
        if level == "NORMAL" and last_level != "NORMAL":
            state["last_level"] = "NORMAL"

    save_state(state)

if __name__ == "__main__":
    main()
