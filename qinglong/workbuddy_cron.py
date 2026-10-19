#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 多账号自动化签到与多通道消息推送脚本 (带本地端侧 Qwen2.5-3B AI 晨报生成)
支持：
  1. 自动扫描 auths/ 目录下所有账号凭证
  2. 智能 Token 自动续期（当即将过期时用 refreshToken 自动刷新并回写文件，避免失效）
  3. 每日自动签到（精准对齐腾讯 10001 幂等已签到与 0 成功状态）
  4. 自动查询账户实时积分余额与套餐到期时间
  5. 本地端侧 Qwen2.5-3B 离线生成早安寄语
  6. 多通道完全免费通知 (WxPusher / Bark / Server酱 / 钉钉 / 飞书 / PushPlus)
"""

import os
import sys
import glob
import json
import time
import hashlib
from datetime import datetime
import requests

# ─── 多通道通知配置区（优先读取环境变量，保护隐私）───────────────────
WXPUSHER_APP_TOKEN = os.environ.get("WXPUSHER_APP_TOKEN", "").strip()
WXPUSHER_UID = os.environ.get("WXPUSHER_UID", "").strip()
BARK_KEY = os.environ.get("BARK_KEY", "").strip()
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "").strip()
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "").strip()
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "").strip()
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "").strip()

# 账号凭据目录（留空则自动探测）
AUTHS_DIR = os.environ.get("AUTHS_DIR", "").strip()

CN_CHAT_BASE = "https://copilot.tencent.com"
CN_BILLING_BASE = "https://www.codebuddy.cn"

UA_WORKBUDDY = "WorkBuddy/2.137.1"

def get_auths_dir() -> str:
    """智能查找 auths 凭证目录"""
    if AUTHS_DIR and os.path.isdir(AUTHS_DIR):
        return AUTHS_DIR
    candidates = [
        os.path.join(os.path.dirname(__file__), "upstream", "auths"),
        os.path.join(os.path.dirname(__file__), "auths"),
        "/ql/data/scripts/workbuddy/auths",
        "/ql/data/scripts/auths",
    ]
    for c in candidates:
        if os.path.isdir(c):
            return c
    return os.path.join(os.path.dirname(__file__), "auths")

def refresh_token_if_needed(fpath: str, raw: dict) -> tuple:
    """检查 Token 是否快过期，若过期则使用 refreshToken 换新并回写文件"""
    auth = raw.get("auth") or {}
    token = auth.get("accessToken") or ""
    refresh_token = auth.get("refreshToken") or ""
    expire_at = auth.get("expireAt") or 0

    now = int(time.time())
    if expire_at and (expire_at - now > 86400) and token:
        return token, False

    if not refresh_token:
        return token, False

    print("  [*] AccessToken 即将过期或已失效，尝试通过 refreshToken 自动续期...")
    url = f"{CN_CHAT_BASE}/api/v1/auth/refresh"
    headers = {"User-Agent": UA_WORKBUDDY, "Content-Type": "application/json"}
    payload = {"refreshToken": refresh_token}

    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15).json()
        if res.get("code") == 0 and res.get("data"):
            d = res["data"]
            auth["accessToken"] = d.get("accessToken", token)
            auth["refreshToken"] = d.get("refreshToken", refresh_token)
            auth["expireAt"] = d.get("expireAt", now + 7 * 86400)
            raw["auth"] = auth
            with open(fpath, "w", encoding="utf-8") as f:
                json.dump(raw, f, ensure_ascii=False, indent=2)
            print("  [✓] Token 续期成功，已回写至凭据文件！")
            return auth["accessToken"], True
        else:
            print(f"  [!] 续期返回异常: {res.get('msg')}")
    except Exception as e:
        print(f"  [!] 续期请求异常: {e}")

    return token, False

def do_checkin(token: str, uid: str) -> tuple:
    """调用签到接口打卡"""
    url = f"{CN_CHAT_BASE}/api/v1/user/checkin"
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": UA_WORKBUDDY,
        "Content-Type": "application/json"
    }
    try:
        res = requests.post(url, json={}, headers=headers, timeout=15).json()
        code = res.get("code")
        if code == 0:
            return True, "签到成功"
        elif code == 10001 or "已经签到" in str(res.get("msg")):
            return True, "今日已签到 (幂等成功)"
        else:
            return False, f"签到失败: {res.get('msg')} (code: {code})"
    except Exception as e:
        return False, f"网络请求异常: {e}"

def get_credits(token: str, uid: str) -> tuple:
    """查询账户积分余额与最近到期时间"""
    url = f"{CN_BILLING_BASE}/api/v1/billing/user-account-detail"
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": UA_WORKBUDDY,
        "Content-Type": "application/json"
    }
    try:
        res = requests.get(url, headers=headers, timeout=15).json()
        if res.get("code") != 0 or not res.get("data"):
            return "-", "查询失败"
        data = res["data"]
        accounts = data.get("Accounts") or []
        if not accounts:
            return "0", "无有效套餐"

        total_remain = 0.0
        min_expire = ""
        for item in accounts:
            if not isinstance(item, dict):
                continue
            size = float(item.get("CycleCapacitySize") or 0)
            if size > 0:
                rem = min(max(float(item.get("CycleCapacityRemain") or 0), 0.0), size)
                used = size - rem
                c_used = float(item.get("CycleCapacityUsed") or 0)
                if c_used > used:
                    used = c_used
                    if size >= used:
                        rem = size - used
            else:
                rem = float(item.get("CapacityRemain") or 0)
            
            if rem > 0:
                total_remain += rem
                exp = item.get("CycleEndTime") or item.get("EndTime")
                if exp and (not min_expire or exp < min_expire):
                    min_expire = exp

        display_credits = int(total_remain) if float(total_remain).is_integer() else round(total_remain, 1)
        return str(display_credits), min_expire or "长期有效"
    except Exception as e:
        return "查询异常", "未知"

def send_all_notifications(title: str, content_html: str, content_text: str):
    """统一向已配置的通道广播推送"""
    sent = False

    # 1. WxPusher 微信推送
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
                print("  [WxPusher] 微信推送成功！")
                sent = True
            else:
                print(f"  [WxPusher 失败] {res.get('msg')}")
        except Exception as e:
            print(f"  [WxPusher 异常] {e}")

    # 2. Server酱
    if SERVERCHAN_KEY:
        try:
            url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
            res = requests.post(url, data={"title": title, "desp": content_text}, timeout=15).json()
            if res.get("code") == 0:
                print("  [Server酱] 微信推送成功！")
                sent = True
        except Exception:
            pass

    # 3. 钉钉机器人
    if DINGTALK_WEBHOOK:
        try:
            payload = {"msgtype": "markdown", "markdown": {"title": title, "text": f"### {title}\n\n" + content_text}}
            res = requests.post(DINGTALK_WEBHOOK, json=payload, timeout=15).json()
            if res.get("errcode") == 0:
                print("  [钉钉机器人] 推送成功！")
                sent = True
        except Exception:
            pass

    # 4. 飞书机器人
    if FEISHU_WEBHOOK:
        try:
            payload = {"msg_type": "text", "content": {"text": f"{title}\n\n{content_text}"}}
            res = requests.post(FEISHU_WEBHOOK, json=payload, timeout=15).json()
            if res.get("StatusCode") == 0 or res.get("code") == 0:
                print("  [飞书机器人] 推送成功！")
                sent = True
        except Exception:
            pass

    # 5. PushPlus
    if PUSHPLUS_TOKEN and not sent:
        try:
            url = "http://www.pushplus.plus/send"
            payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content_html, "template": "html"}
            res = requests.post(url, json=payload, timeout=15).json()
            if res.get("code") == 200:
                print("  [PushPlus] 推送成功！")
                sent = True
        except Exception:
            pass

    if not sent:
        print("\n[提示] 未配置可用的免费推送通道，或推送未成功。")

def generate_qwen_daily_quote(results: list) -> str:
    """调用一加9本地 Qwen2.5-3B 端侧大模型生成个性化晨报寄语"""
    try:
        url = "http://127.0.0.1:8080/v1/chat/completions"
        summary_text = "，".join([f"{r['nick']}: {r['msg']}(当前积分{r['credits']})" for r in results])
        prompt = f"今天账号签到状态：{summary_text}。请作为一加9微服务器的AI智能管家，用温暖幽默、积极向上的语气写一句简短晨报寄语（25字以内，不要多余解释或引号）。"
        payload = {
            "messages": [
                {"role": "system", "content": "你是一加9手机本地微服务器的AI管家，说话幽默得体、充满正能量。"},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.8,
            "max_tokens": 60
        }
        res = requests.post(url, json=payload, timeout=10).json()
        quote = res["choices"][0]["message"]["content"].strip().strip('"').strip('“').strip('”')
        print(f"[*] 端侧 Qwen2.5-3B 生成寄语: {quote}")
        return quote
    except Exception as e:
        print(f"[!] 本地大模型暂未响应，使用兜底寄语: {e}")
        return "新的一天，步履不停，心怀热爱，奔赴山海！"

def main():
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 启动 WorkBuddy 每日自动签到任务...")
    auth_dir = get_auths_dir()
    print(f"[*] 账号凭据目录: {auth_dir}")
    if not os.path.isdir(auth_dir):
        print(f"[-] 错误: 找不到凭据目录 {auth_dir}")
        sys.exit(1)

    json_files = glob.glob(os.path.join(auth_dir, "*.json"))
    if not json_files:
        print(f"[-] 警告: 目录 {auth_dir} 下未找到任何 *.json 账号文件！")
        sys.exit(0)

    print(f"[*] 共扫描到 {len(json_files)} 个账号文件\n" + "-"*50)

    results = []
    all_ok = True

    for fpath in json_files:
        fname = os.path.basename(fpath)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except Exception as e:
            print(f"[!] 读取 {fname} 失败: {e}")
            continue

        acct = raw.get("account") or {}
        auth = raw.get("auth") or {}
        uid = str(acct.get("uid") or "")
        nick = str(acct.get("nickname") or uid[:8] or fname)

        print(f"-> 正在处理账号: {nick} (UID: {uid[:8]}...)")
        token, was_refreshed = refresh_token_if_needed(fpath, raw)
        if not token:
            print("  [!] 缺失有效 accessToken，跳过")
            results.append({"nick": nick, "uid": uid, "ok": False, "msg": "缺失 Token", "credits": "-", "expire": "-"})
            all_ok = False
            continue

        ok, msg = do_checkin(token, uid)
        print(f"  [签到状态] {msg}")
        if not ok:
            all_ok = False

        credits_str, expire_str = get_credits(token, uid)
        print(f"  [可用积分] {credits_str} | [最近到期] {expire_str}")
        results.append({
            "nick": nick,
            "uid": uid,
            "ok": ok,
            "msg": msg,
            "credits": credits_str,
            "expire": expire_str,
        })
        time.sleep(1)

    print("-" * 50)
    print("签到全部完成！")

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
    status_icon = "全部成功" if all_ok else "部分失败"
    title = f"WorkBuddy打卡: {status_icon} ({len(results)}个账号)"

    # 调用本地大模型生成每日寄语
    ai_quote = generate_qwen_daily_quote(results)

    # 读取硬件健康温度
    bat_str = ""
    try:
        with open("/sys/class/thermal/thermal_zone100/temp", "r") as f:
            t = float(f.read().strip())
            bat_str = f" | 🔋 电池 {t/1000.0:.1f}°C 正常"
    except Exception:
        pass

    # HTML 格式
    html_lines = [
        f"<h3>WorkBuddy 自动打卡结果报告 ({now_str})</h3>",
        f"<div style='background-color:#f0f7ff;border-left:4px solid #1677ff;padding:10px 14px;border-radius:4px;color:#1d39c4;font-size:14px;margin:12px 0;'>🤖 <b>Qwen2.5 端侧AI寄语：</b>{ai_quote}</div>",
        f"<p><b>状态：</b>{status_icon}</p>",
        "<table border='1' cellpadding='8' cellspacing='0' style='border-collapse:collapse;width:100%;font-size:14px;text-align:left;'>",
        "<tr style='background-color:#f2f2f2;'><th>账号昵称</th><th>打卡状态</th><th>当前积分</th><th>到期时间</th></tr>"
    ]
    for r in results:
        color = "#2e7d32" if r["ok"] else "#c62828"
        html_lines.append(
            f"<tr><td><b>{r['nick']}</b></td>"
            f"<td style='color:{color}; font-weight:bold;'>{r['msg']}</td>"
            f"<td><b>{r['credits']}</b></td>"
            f"<td>{r['expire']}</td></tr>"
        )
    html_lines.append("</table>")
    html_lines.append(f"<p style='font-size:12px;color:#888;margin-top:15px;'>由一加 9 本地家庭微服务器 (Qwen2.5-3B 离线赋能{bat_str}) 自动调度执行</p>")
    content_html = "".join(html_lines)

    # 纯文本 / Markdown
    text_lines = [
        f"### 状态：{status_icon} ({now_str})",
        f"> 🤖 **Qwen2.5 端侧AI寄语**：{ai_quote}",
        "",
        "| 账号昵称 | 打卡状态 | 当前积分 | 到期时间 |",
        "| :--- | :--- | :--- | :--- |",
    ]
    for r in results:
        text_lines.append(f"| {r['nick']} | {r['msg']} | {r['credits']} | {r['expire']} |")
    text_lines.append(f"\n*由一加 9 本地家庭微服务器 (Qwen2.5-3B 离线赋能{bat_str}) 自动调度执行*")
    content_text = "\n".join(text_lines)

    send_all_notifications(title, content_html, content_text)

if __name__ == "__main__":
    main()
