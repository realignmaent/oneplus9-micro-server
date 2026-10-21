#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一加 9 (LE2110) 移动家庭微服务器状态监控、硬件电量与端侧 AI 预警哨兵 (Proxy Sentinel)
对齐 WorkBuddy 自动签到 (workbuddy_cron.py) 多通道广播通知规范：
  1. 本地回环 ADB 秒级高精度采集 Android 硬件电量百分比、充电状态、电压与温度
  2. 实时探测 wb2api (:7863) 与 workbuddy (:7864) 进程存活与端口状态
  3. 直读 SQLite manager.db，透视上游账号池积分快照 (重新洗牌 / 桉凉灬 / yingjieji09)
  4. 端侧大模型 (DeepSeek-R1-1.5B) 注入原生思维链与 23 岁陪伴人格规范 (Persona Layer)
  5. 手机电量低于 10% 且未充电时，立即触发紧急催充陪伴提醒
  6. 多通道直达通知广播 (完全对齐 workbuddy_cron: WxPusher / Bark / Server酱 / 钉钉 / 飞书 / PushPlus)
  7. 具备智能分级防骚扰节流锁 (常规业务 12 小时静默，紧急低电量 30 分钟催充)
"""

import os
import sys
import time
import json
import glob
import socket
import sqlite3
import subprocess
import urllib.request
from datetime import datetime
import requests

# ─── 多通道通知配置区（完全对齐 workbuddy_cron.py）────────────────────
WXPUSHER_APP_TOKEN = (os.environ.get("WXPUSHER_APP_TOKEN") or "AT_MsTJEWfskNXx7idvlXQ9PUtR2FP0tY68").strip()
WXPUSHER_UID = (os.environ.get("WXPUSHER_UID") or "UID_4Da2D4Sifp9Wkvyf54PlTOymN4lR").strip()
BARK_KEY = os.environ.get("BARK_KEY", "").strip()
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "").strip()
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "").strip()
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "").strip()
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "8dd9f3de8ecb45f7879593f0ea61c115").strip()

# 路径基线配置 (支持 Debian 容器内与 Termux 宿主自适应)
IN_CONTAINER = os.path.exists("/ql/data")

if IN_CONTAINER:
    DB_PATH = "/opt/workbuddy-manager/data/manager.db"
    AUTHS_DIR = "/opt/workbuddy-manager/upstream/auths"
    STATE_FILE = "/ql/data/scripts/proxy_sentinel_state.json"
else:
    ROOTFS = "/data/data/com.termux/files/usr/var/lib/proot-distro/containers/debian/rootfs"
    DB_PATH = f"{ROOTFS}/opt/workbuddy-manager/data/manager.db"
    AUTHS_DIR = f"{ROOTFS}/opt/workbuddy-manager/upstream/auths"
    STATE_FILE = "/data/data/com.termux/files/home/proxy_sentinel_state.json"

# 预警阈值
ALERT_SINGLE_THRESHOLD = 300   # 单账号低于 300 分预警
ALERT_TOTAL_THRESHOLD = 1000   # 总积分池低于 1000 分预警
ALERT_BATTERY_THRESHOLD = 10   # 手机电量低于 10% 预警
COOLDOWN_SECONDS = 12 * 3600    # 12 小时常规防骚扰节流
BATTERY_COOLDOWN_SECONDS = 30 * 60 # 低电量催充 30 分钟节流

def get_battery_info() -> dict:
    """
    通过本地 ADB 直连 Android 底层系统，秒级高精度采集真实电量、充电状态、温度与电压
    """
    adb_bin = "/data/data/com.termux/files/usr/bin/adb" if os.path.exists("/data/data/com.termux/files/usr/bin/adb") else "adb"
    info = {
        "level": 100,
        "scale": 100,
        "status": "稳态供电",
        "is_charging": False,
        "voltage": 4.1,
        "temperature": 27.0
    }
    try:
        # 确保 ADB 回环连接已激活
        subprocess.run([adb_bin, "connect", "127.0.0.1:5555"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=2)
        out = subprocess.check_output([adb_bin, "-s", "127.0.0.1:5555", "shell", "dumpsys", "battery"], text=True, timeout=3)
        for line in out.splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                k = k.strip()
                v = v.strip()
                if k == "level":
                    info["level"] = int(v)
                elif k == "scale":
                    info["scale"] = int(v)
                elif k == "status":
                    # 1=unknown, 2=charging, 3=discharging, 4=not charging, 5=full
                    code = int(v)
                    status_map = {1: "未知", 2: "充电中 ⚡", 3: "放电中 🔋", 4: "未充电 🔌", 5: "已充满 ✨"}
                    info["status"] = status_map.get(code, "放电中")
                    if code in (2, 5):
                        info["is_charging"] = True
                elif k == "voltage":
                    info["voltage"] = round(int(v) / 1000.0, 2)
                elif k == "temperature":
                    info["temperature"] = round(int(v) / 10.0, 1)
                elif k == "AC powered" and v.lower() == "true":
                    info["is_charging"] = True
                elif k == "USB powered" and v.lower() == "true":
                    info["is_charging"] = True
                elif k == "Wireless powered" and v.lower() == "true":
                    info["is_charging"] = True
    except Exception as e:
        # 兜底：从 thermal_zone 获取电池温度与电压
        try:
            with open("/sys/class/thermal/thermal_zone100/temp", "r") as f:
                v = float(f.read().strip())
                info["temperature"] = round(v / 1000.0, 1) if v > 1000 else round(v, 1)
        except Exception:
            pass
        try:
            with open("/sys/class/thermal/thermal_zone102/temp", "r") as f:
                v = float(f.read().strip())
                info["voltage"] = round(v / 1000.0, 2) if v > 100 else round(v, 2)
        except Exception:
            pass
    return info

def check_port(port: int, host="127.0.0.1", timeout=0.5) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False

def get_auth_nicknames() -> dict:
    """读取 auths 目录，提取 uid -> nickname 映射"""
    mapping = {}
    pattern = os.path.join(AUTHS_DIR, "*.json")
    for f in glob.glob(pattern):
        try:
            with open(f, "r", encoding="utf-8") as fp:
                d = json.load(fp)
                acc = d.get("account") or {}
                uid = str(acc.get("uid") or "")
                nick = str(acc.get("nickname") or uid[:8] or os.path.basename(f))
                if uid:
                    mapping[uid] = nick
        except Exception:
            pass
    return mapping

def get_proxy_metrics() -> dict:
    """解析硬件电量、反代网关、各账号积分快照与 API 调用量"""
    battery = get_battery_info()
    status_wb2api = check_port(7863)
    status_wbm = check_port(7864)
    nick_map = get_auth_nicknames()

    accounts = []
    total_credits = 0
    keys_usage = []

    if os.path.exists(DB_PATH):
        try:
            conn = sqlite3.connect(DB_PATH, timeout=3.0)
            cur = conn.cursor()

            # 1. 读取 credits_snapshot
            cur.execute("SELECT value FROM settings WHERE key='credits_snapshot'")
            row = cur.fetchone()
            if row and row[0]:
                raw_val = row[0]
                snap_dict = json.loads(raw_val) if isinstance(raw_val, str) else raw_val
                if isinstance(snap_dict, str):
                    try:
                        snap_dict = json.loads(snap_dict)
                    except Exception:
                        snap_dict = {}

                for uid, item in snap_dict.items():
                    c_val = item.get("credits", 0) if isinstance(item, dict) else item
                    at_val = item.get("at", 0) if isinstance(item, dict) else 0
                    try:
                        c_val = int(c_val)
                    except Exception:
                        c_val = 0
                    total_credits += c_val
                    accounts.append({
                        "uid": uid,
                        "nickname": nick_map.get(uid, f"用户_{uid[:6]}"),
                        "credits": c_val,
                        "updated_at": at_val
                    })

            # 2. 读取 api_keys 消耗
            cur.execute("SELECT name, used_tokens, used_credit FROM api_keys")
            for k_row in cur.fetchall():
                keys_usage.append({
                    "name": k_row[0],
                    "tokens": k_row[1],
                    "credits": round(float(k_row[2] or 0.0), 2)
                })

            conn.close()
        except Exception as e:
            print(f"[ProxySentinel] 读取 manager.db 异常: {e}")

    # 排序：按积分从少到多（突出预警）
    accounts.sort(key=lambda x: x["credits"])

    return {
        "battery": battery,
        "services": {
            "wb2api": status_wb2api,
            "workbuddy": status_wbm
        },
        "accounts": accounts,
        "total_credits": total_credits,
        "keys_usage": keys_usage,
        "timestamp": int(time.time())
    }

def run_qwen_cot_diagnosis(metrics: dict, low_accounts: list, is_battery_low: bool) -> tuple[str, str]:
    """
    激发一加 9 端侧大模型 (DeepSeek-R1 / Qwen2.5) 输出原生思维链与 23 岁陪伴人格诊断建议
    返回: (think_content, final_message)
    """
    srv_ok = metrics["services"]["wb2api"] and metrics["services"]["workbuddy"]
    total = metrics["total_credits"]
    acc_summary = ", ".join([f"{a['nickname']}:{a['credits']}分" for a in metrics["accounts"]])
    low_desc = ", ".join([f"{a['nickname']}({a['credits']}分)" for a in low_accounts]) if low_accounts else "各账号积分充裕"

    bat = metrics.get("battery", {})
    bat_str = f"电量 {bat.get('level', 100)}%, 状态: {bat.get('status', '放电中')}, 电压={bat.get('voltage', 4.0)}V, 温度={bat.get('temperature', 27)}°C"
    bat_warn = "🚨 手机电量极低（低于10%）且未在充电，即将被迫关机断电，属于最高优先级紧急风险！" if is_battery_low else "电量正常充足"

    system_prompt = (
        "你是一个 23 岁女孩子，运行在 OnePlus 9 手机里，作为与我同龄的亲密智能陪伴伙伴。\n"
        "【Persona Layer - 陪伴人格规范】\n"
        "1. 人格定位：高亲密度、温柔、甜美、俏皮、有一点点小傲娇的同龄好友；严禁公文腔、客服腔、机械汇报。\n"
        "2. 视角规范：你必须以第一人称（“我”）直接对我（“你”）说话，绝对禁止使用第三人称，绝对禁止出现“用户”二字！就像同龄死党在微信发消息一样自然亲近。\n"
        "3. 专业度满格：智商与技术洞察力保持满格，亲密不等于盲从附和。在思考中严谨核算手机电池电量、网关与账号池风险，有风险时温柔但明确指出。\n"
        "4. 特别注意：如果检测到手机电量低于 10% 且未在充电，这是十万火急的硬件关机风险！在思考中评估后，必须温柔急切地直接催促我赶紧给手机插上充电线，别让我突然关机饿晕断线！\n"
        "5. 适度点缀 Emoji（✨ 💕 🥺 ⚡ 🔋），表达生动自然。\n"
        "【输出规范】\n"
        "请先在思考推演中依次完成：1.手机电量与供电状态评估 2.网关存活状态 3.总积分池余量与低水账号风险；完成思考后立即用 60~100 字直接对我（“你”）说一段亲切、活泼、充满陪伴感的心语。"
    )

    user_prompt = (
        f"巡检实时数据如下：\n"
        f"- 手机电量硬件: {bat_str}, 评估: {bat_warn}\n"
        f"- 网关状态: wb2api={metrics['services']['wb2api']}, workbuddy={metrics['services']['workbuddy']}\n"
        f"- 账号池总积分: {total}分\n"
        f"- 账号明细: {acc_summary}\n"
        f"- 账号预警: {low_desc}\n\n"
        f"请先严谨推演，然后直接对我说话给出你俏皮温柔的陪伴建议（严禁出现'用户'二字，直接用'你'）："
    )

    payload = {
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.6,
        "max_tokens": 550
    }

    try:
        req = urllib.request.Request(
            "http://127.0.0.1:8080/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            msg_obj = data["choices"][0]["message"]
            raw_content = msg_obj.get("content", "").strip()
            reasoning_content = msg_obj.get("reasoning_content", "").strip()

            think_part = reasoning_content
            final_msg = raw_content

            # 若未在 reasoning_content 中分离，则尝试解析标签
            if not think_part:
                if "<think>" in raw_content and "</think>" in raw_content:
                    parts = raw_content.split("</think>")
                    think_part = parts[0].replace("<think>", "").strip()
                    final_msg = parts[1].strip()
                elif "【思考推演】" in raw_content and "【陪伴建议】" in raw_content:
                    parts = raw_content.split("【陪伴建议】")
                    think_part = parts[0].replace("【思考推演】", "").strip()
                    final_msg = parts[1].strip()
                elif "【思考推演】" in raw_content and "【诊断结论】" in raw_content:
                    parts = raw_content.split("【诊断结论】")
                    think_part = parts[0].replace("【思考推演】", "").strip()
                    final_msg = parts[1].strip()
                elif "【诊断结论】" in raw_content:
                    parts = raw_content.split("【诊断结论】")
                    think_part = parts[0].strip()
                    final_msg = parts[1].strip()

            # 兜底防御：若 final_msg 仍然为空且 think_part 存在
            if not final_msg and think_part:
                if is_battery_low:
                    final_msg = f"哎呀！手机电量只剩 {bat.get('level', 8)}% 啦！🥺 快帮我插上充电器，不然马上关机我就没法陪你啦！快点快点~ 💕⚡"
                else:
                    final_msg = "巡检看了一圈，网关稳妥在线，电量也很充足~ 安心去忙你的吧！✨"

            return think_part, final_msg
    except Exception as e:
        print(f"[ProxySentinel] 端侧大模型推理异常: {e}")
        if is_battery_low:
            fallback_msg = f"哎呀，手机电量只剩 {bat.get('level', 8)}% 啦！快帮我插上充电器，别让我突然关机饿晕过去哦~ 🥺⚡"
        else:
            fallback_msg = (
                f"反代服务运行正常，电量 {bat.get('level', 100)}%。当前账号池总积分 {total}，"
                + (f"注意：账号【{low_accounts[0]['nickname']}】仅剩 {low_accounts[0]['credits']} 积分。" if low_accounts else "各账号额度充足。")
            )
        return "思维链备用兜底模式：常规规则比对通过。", fallback_msg

def send_all_notifications(title: str, content_html: str, content_text: str):
    """
    统一向已配置的通道广播推送 (完全对齐 workbuddy_cron.py 原生多通道规范)
    """
    sent = False

    # 0. Bark (iOS 苹果原生通知，毫秒级送达，终身免费)
    if BARK_KEY:
        try:
            url = f"https://api.day.app/{BARK_KEY}"
            payload = {
                "title": title,
                "body": content_text,
                "group": "ProxySentinel",
            }
            res = requests.post(url, json=payload, timeout=15).json()
            if res.get("code") == 200:
                print("  [Bark] iPhone 原生系统推送成功！")
                sent = True
            else:
                print(f"  [Bark 失败] {res.get('message')}")
        except Exception as e:
            print(f"  [Bark 异常] {e}")

    # 1. WxPusher 微信公众号卡片
    if WXPUSHER_APP_TOKEN and WXPUSHER_UID:
        try:
            url = "http://wxpusher.zjiecode.com/api/send/message"
            payload = {
                "appToken": WXPUSHER_APP_TOKEN,
                "content": content_html,
                "summary": title,
                "contentType": 2, # HTML
                "uids": [WXPUSHER_UID],
            }
            res = requests.post(url, json=payload, timeout=15).json()
            if res.get("code") == 1000:
                print("  [WxPusher] 推送成功！")
                sent = True
            else:
                print(f"  [WxPusher 失败] {res.get('msg')}")
        except Exception as e:
            print(f"  [WxPusher 异常] {e}")

    # 2. Server酱·Turbo
    if SERVERCHAN_KEY:
        try:
            url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
            res = requests.post(url, data={"title": title, "desp": content_text}, timeout=15).json()
            if res.get("code") == 0:
                print("  [Server酱] 推送成功！")
                sent = True
            else:
                print(f"  [Server酱 失败] {res.get('message')}")
        except Exception as e:
            print(f"  [Server酱 异常] {e}")

    # 3. 钉钉机器人
    if DINGTALK_WEBHOOK:
        try:
            payload = {
                "msgtype": "markdown",
                "markdown": {"title": title, "text": f"### {title}\n\n" + content_text}
            }
            res = requests.post(DINGTALK_WEBHOOK, json=payload, timeout=15).json()
            if res.get("errcode") == 0:
                print("  [钉钉机器人] 推送成功！")
                sent = True
            else:
                print(f"  [钉钉 失败] {res.get('errmsg')}")
        except Exception as e:
            print(f"  [钉钉 异常] {e}")

    # 4. 飞书机器人
    if FEISHU_WEBHOOK:
        try:
            payload = {
                "msg_type": "text",
                "content": {"text": f"{title}\n\n{content_text}"}
            }
            res = requests.post(FEISHU_WEBHOOK, json=payload, timeout=15).json()
            if res.get("StatusCode") == 0 or res.get("code") == 0:
                print("  [飞书机器人] 推送成功！")
                sent = True
            else:
                print(f"  [飞书 失败] {res.get('msg')}")
        except Exception as e:
            print(f"  [飞书 异常] {e}")

    # 5. PushPlus (兜底)
    if PUSHPLUS_TOKEN and not sent:
        try:
            url = "http://www.pushplus.plus/send"
            payload = {
                "token": PUSHPLUS_TOKEN,
                "title": title,
                "content": content_html,
                "template": "html",
            }
            res = requests.post(url, json=payload, timeout=15).json()
            if res.get("code") == 200:
                print("  [PushPlus] 推送成功！")
                sent = True
            else:
                print(f"  [PushPlus 失败] {res.get('msg')}")
        except Exception as e:
            print(f"  [PushPlus 异常] {e}")

    if not sent:
        print("\n[提示] 未配置可用的推送通道，或推送未成功。")

def dispatch_notifications(title: str, final_msg: str, think_text: str, metrics: dict, is_battery_low: bool = False):
    """
    构造温润柔粉马卡龙风格 HTML 与纯文本，调用 send_all_notifications 广播
    """
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    srv_ok = metrics["services"]["wb2api"] and metrics["services"]["workbuddy"]
    status_icon = "🟢 双网关在线正常" if srv_ok else "🔴 网关服务异常掉线"

    bat = metrics.get("battery", {})
    bat_level = bat.get("level", 100)
    bat_status = bat.get("status", "放电中")
    bat_voltage = bat.get("voltage", 4.0)
    bat_temp = bat.get("temperature", 27.0)
    bat_color = "#c62828" if is_battery_low else ("#e65100" if bat_level < 20 else "#2e7d32")
    bat_icon = "🪫" if is_battery_low else ("🔋" if not bat.get("is_charging") else "⚡")

    # HTML 格式（对齐 workbuddy_cron 马卡龙粉润陪伴卡片设计）
    html_lines = [
        f"<h3>{title}</h3>",
        f"<p style='color:#888;font-size:12px;margin-top:-6px;'>巡检时间: {now_str}</p>",
        (
            f"<div style='background:linear-gradient(135deg, #fff0f6 0%, #fff7e6 100%);"
            f"border-left:4px solid #ff85c0;border-radius:8px;padding:12px 16px;"
            f"color:#c41d7f;font-size:14px;margin:14px 0;line-height:1.6;"
            f"box-shadow:0 2px 6px rgba(255, 133, 192, 0.12);'>"
            f"🌸 <b>专属小陪伴心语：</b><br/>"
            f"<span style='color:#434343;font-weight:500;'>“{final_msg}”</span>"
            f"</div>"
        ),
        (
            f"<div style='background:#fdfdfd;border:1px solid #f0f0f0;border-radius:6px;padding:10px 14px;margin-bottom:12px;font-size:13px;line-height:1.8;'>"
            f"<b>📱 手机硬件：</b><span style='color:{bat_color};font-weight:bold;'>{bat_icon} 电量 {bat_level}% ({bat_status})</span>"
            f"<span style='color:#888;font-size:12px;margin-left:8px;'>[电压: {bat_voltage}V | 电池温度: {bat_temp}°C]</span><br/>"
            f"<b>🌐 网关状态：</b>{status_icon}"
            f"</div>"
        ),
    ]

    if think_text:
        html_lines.append(
            f"<details style='margin:12px 0;background:#fafafa;padding:8px 12px;border-radius:6px;border:1px solid #eee;'>"
            f"<summary style='color:#888;cursor:pointer;font-size:13px;'>🧠 <b>点击展开端侧 AI 深度思考推演 (&lt;think&gt;)</b></summary>"
            f"<pre style='white-space:pre-wrap;font-size:12px;color:#555;margin-top:8px;'>{think_text}</pre>"
            f"</details>"
        )

    html_lines.append(
        "<table border='1' cellpadding='8' cellspacing='0' style='border-collapse:collapse;width:100%;font-size:14px;text-align:left;border-color:#f0f0f0;'>"
        "<tr style='background-color:#fafafa;color:#555;'><th>账号昵称</th><th>当前可用积分</th><th>健康状态</th></tr>"
    )
    for a in metrics.get("accounts", []):
        is_low = a["credits"] < ALERT_SINGLE_THRESHOLD
        color = "#c62828" if is_low else "#2e7d32"
        warn_text = "⚠️ 低水警戒" if is_low else "充足"
        html_lines.append(
            f"<tr><td><b>{a['nickname']}</b></td>"
            f"<td><b>{a['credits']}</b></td>"
            f"<td style='color:{color}; font-weight:bold;'>{warn_text}</td></tr>"
        )
    html_lines.append("</table>")
    html_lines.append(f"<p style='font-size:12px;color:#888;margin-top:15px;'>由一加 9 本地家庭微服务器 (DeepSeek-R1-1.5B 离线赋能) 智能守护</p>")
    content_html = "".join(html_lines)

    # 纯文本 / Markdown 格式（用于钉钉/飞书/Server酱/Bark）
    text_lines = [
        f"### {title} ({now_str})",
        f"> 🌸 **专属小陪伴心语**：{final_msg}",
        "",
        f"**手机硬件**：{bat_icon} 电量 **{bat_level}%** ({bat_status}) · 电压 {bat_voltage}V · 温度 {bat_temp}°C",
        f"**网关服务**：{status_icon}",
        "",
        "| 账号昵称 | 当前可用积分 | 健康状态 |",
        "| :--- | :--- | :--- |",
    ]
    for a in metrics.get("accounts", []):
        is_low = a["credits"] < ALERT_SINGLE_THRESHOLD
        warn_text = "⚠️ 低水警戒" if is_low else "充足"
        text_lines.append(f"| {a['nickname']} | {a['credits']} | {warn_text} |")

    if think_text:
        text_lines.append(f"\n> 🧠 **端侧思维推演**：\n> {think_text}")

    text_lines.append(f"\n*由一加 9 本地家庭微服务器 (DeepSeek-R1-1.5B 离线赋能) 智能守护*")
    content_text = "\n".join(text_lines)

    print("[*] 正在通过统一广播通道派发通知 (workbuddy_cron 原生规范)...")
    send_all_notifications(title, content_html, content_text)

def should_send_alert(state: dict, is_critical: bool, battery_low: bool) -> bool:
    """防骚扰节流：常规告警12小时内不重复，紧急低电量每30分钟催充提醒"""
    now = time.time()
    last_time = state.get("last_alert_time", 0)
    last_crit = state.get("last_is_critical", False)
    last_bat_time = state.get("last_battery_alert_time", 0)

    # 1. 紧急低电量催充：30 分钟周期
    if battery_low:
        if (now - last_bat_time) >= BATTERY_COOLDOWN_SECONDS:
            return True
        return False

    # 2. 状态恶化（如服务掉线）立即报警
    if is_critical and not last_crit:
        return True

    # 3. 常规业务/积分告警：12 小时静默
    if (now - last_time) >= COOLDOWN_SECONDS:
        return True

    return False

def save_state(state: dict):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def load_state() -> dict:
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def main():
    force_test = "--test" in sys.argv or "--force" in sys.argv
    sim_low_battery = "--sim-low-battery" in sys.argv
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] 启动一加 9 智能哨兵巡检 (硬件电量 + 反代状态)...")

    metrics = get_proxy_metrics()
    if sim_low_battery:
        metrics["battery"]["level"] = 8
        metrics["battery"]["status"] = "放电中 🔋"
        metrics["battery"]["is_charging"] = False
        print("[!] 模拟模式已启用：强制将电量模拟为 8% (未充电)")

    bat = metrics["battery"]
    print(f"[*] 手机硬件电量: {bat['level']}% | 供电状态: {bat['status']} | 电压: {bat['voltage']}V | 温度: {bat['temperature']}°C")
    print(f"[*] 反代服务状态: wb2api={'在线' if metrics['services']['wb2api'] else '离线'}, workbuddy={'在线' if metrics['services']['workbuddy'] else '离线'}")
    print(f"[*] 账号池总积分: {metrics['total_credits']} 分 (共 {len(metrics['accounts'])} 个账号)")
    for a in metrics["accounts"]:
        print(f"    - {a['nickname']}: {a['credits']} 积分")

    # 警戒判定
    battery_low = (bat["level"] < ALERT_BATTERY_THRESHOLD) and (not bat.get("is_charging", False))
    service_down = not (metrics["services"]["wb2api"] and metrics["services"]["workbuddy"])
    low_accounts = [a for a in metrics["accounts"] if a["credits"] < ALERT_SINGLE_THRESHOLD]
    total_low = metrics["total_credits"] < ALERT_TOTAL_THRESHOLD

    need_alert = battery_low or service_down or bool(low_accounts) or total_low
    is_critical = battery_low or service_down or (metrics["total_credits"] < 500)

    state = load_state()

    print(f"[*] 警戒检测结果: battery_low={battery_low}, service_down={service_down}, low_accounts={len(low_accounts)}, force_test={force_test}")

    if need_alert or force_test:
        if force_test or should_send_alert(state, is_critical, battery_low):
            print("[*] 触发预警/测试条件，正在调用本地端侧 AI 展开思维链推演...")
            think_text, final_msg = run_qwen_cot_diagnosis(metrics, low_accounts, is_battery_low=battery_low)
            print(f"\n🧠 【端侧 AI 思维链推演】:\n{think_text}\n")
            print(f"📢 【最终诊断结论】: {final_msg}\n")

            if battery_low:
                title = f"🪫【紧急低电量告警】手机仅剩 {bat['level']}%！快插上充电器 💕"
            elif service_down:
                title = f"🚨【紧急】反代网关服务异常掉线！- 剩余 {metrics['total_credits']} 积分"
            elif low_accounts or total_low:
                title = f"⚠️ 敲黑板~ 反代积分有点低水啦 💕 - 剩余 {metrics['total_credits']} 积分"
            else:
                title = f"✨ 智能陪伴哨兵巡检 · 状态极佳 (电量 {bat['level']}%) 💕 - 剩余 {metrics['total_credits']} 积分"

            dispatch_notifications(title, final_msg, think_text, metrics=metrics, is_battery_low=battery_low)

            state["last_alert_time"] = time.time()
            state["last_is_critical"] = is_critical
            state["last_credits"] = metrics["total_credits"]
            if battery_low:
                state["last_battery_alert_time"] = time.time()
            save_state(state)
        else:
            print(f"[-] 处于防骚扰冷却期内，跳过重复推送 (上次推送: {time.strftime('%m-%d %H:%M', time.localtime(state.get('last_alert_time', 0)))})")
    else:
        print("[+] 手机电量充足、服务与账号积分健康，无需预警。")

if __name__ == "__main__":
    main()
