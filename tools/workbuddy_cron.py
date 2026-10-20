#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WorkBuddy 多账号自动化签到与多通道消息推送脚本
支持：
  1. 自动扫描 auths/ 目录下所有账号凭证
  2. 智能 Token 自动续期（当即将过期时用 refreshToken 自动刷新并回写文件，避免失效）
  3. 每日自动签到（精准对齐腾讯 10001 幂等已签到与 0 成功状态）
  4. 自动查询账户实时积分余额与套餐到期时间
  5. 多通道完全免费通知：
     - WxPusher (推荐：个人微信公众号直达，免费额度大)
     - Server酱·Turbo (经典微信通知，免费 5 条/天)
     - 钉钉 / 飞书 自定义群机器人 (100% 永久免费，零门槛)
     - PushPlus (兼容既有配置)
"""

import os
import sys
import glob
import json
import time
import hashlib
from datetime import datetime
import requests

# ─── 多通道通知配置区（任选其一填入即可，其他留空）────────────────────

# 1. WxPusher（官网: https://wxpusher.zjiecode.com/）
WXPUSHER_APP_TOKEN = (os.environ.get("WXPUSHER_APP_TOKEN") or "AT_MsTJEWfskNXx7idvlXQ9PUtR2FP0tY68").strip()
WXPUSHER_UID = (os.environ.get("WXPUSHER_UID") or "UID_4Da2D4Sifp9Wkvyf54PlTOymN4lR").strip()

# 2. Bark（iOS 苹果专属原生推送神器，App Store 搜 Bark，打开即用，无需注册）
BARK_KEY = os.environ.get("BARK_KEY", "").strip()

# 3. Server酱·Turbo（官网: https://sct.ftqq.com/，每天免费 5 条）
SERVERCHAN_KEY = os.environ.get("SERVERCHAN_KEY", "").strip()

# 4. 钉钉自定义机器人（单人群添加自定义机器人得到的 Webhook 地址，永久免费）
DINGTALK_WEBHOOK = os.environ.get("DINGTALK_WEBHOOK", "").strip()

# 5. 飞书自定义机器人（单人群添加自定义机器人得到的 Webhook 地址，永久免费）
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK", "").strip()

# 6. PushPlus（原有配置）
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "8dd9f3de8ecb45f7879593f0ea61c115").strip()

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
        os.path.join(os.path.dirname(__file__), "workbuddy-manager-v1.0.80", "upstream", "auths"),
        os.path.join(os.path.dirname(__file__), "auths"),
        os.path.join(os.getcwd(), "auths"),
    ]
    for c in candidates:
        if os.path.isdir(c) and glob.glob(os.path.join(c, "*.json")):
            return c
    return candidates[0]

def build_headers(token: str, uid: str) -> dict:
    """对齐官方客户端防风控特征头"""
    h = {
        "User-Agent": UA_WORKBUDDY,
        "Origin": CN_BILLING_BASE,
        "Referer": f"{CN_BILLING_BASE}/",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Accept-Language": "zh-CN",
        "X-Requested-With": "XMLHttpRequest",
        "X-CodeBuddy-Request": "1",
    }
    if token:
        h["Authorization"] = f"Bearer {token}"
    if uid:
        h["X-User-Id"] = uid
        h["X-Machine-ID"] = hashlib.sha256(f"wb2a:machine:{uid}".encode()).hexdigest()[:36]
        h["X-Session-ID"] = hashlib.sha256(f"wb2a:session:{uid}".encode()).hexdigest()[:36]
    return h

def refresh_token_if_needed(file_path: str, raw_data: dict) -> tuple[str, bool]:
    """若 Token 快过期（小于 1 天），则自动向腾讯请求刷新并回写 json 文件"""
    auth = raw_data.get("auth") or {}
    acct = raw_data.get("account") or {}
    access_token = auth.get("accessToken", "")
    refresh_token = auth.get("refreshToken", "")
    expires_at = auth.get("expiresAt", 0)

    now_ts = time.time()
    if expires_at > 1e11:
        expires_at /= 1000

    if refresh_token and (expires_at - now_ts < 86400):
        uid = str(acct.get("uid", ""))
        print(f"  [刷新] 账号 {acct.get('nickname', '未知')} Token 即将过期，正在自动续期...")
        headers = build_headers(access_token, uid)
        headers["X-Refresh-Token"] = refresh_token
        headers["X-Auth-Refresh-Source"] = "plugin"
        enterprise_id = str(acct.get("enterpriseId", ""))
        if enterprise_id:
            headers["X-Enterprise-Id"] = enterprise_id

        try:
            resp = requests.post(
                f"{CN_CHAT_BASE}/v2/plugin/auth/token/refresh",
                headers=headers,
                timeout=15,
            )
            if resp.status_code == 200:
                res_data = resp.json()
                body = res_data.get("data") if isinstance(res_data.get("data"), dict) else res_data
                new_token = body.get("accessToken")
                new_refresh = body.get("refreshToken")
                expires_in = body.get("expiresIn")
                if new_token:
                    auth["accessToken"] = new_token
                    if new_refresh:
                        auth["refreshToken"] = new_refresh
                    if expires_in:
                        auth["expiresAt"] = int(time.time() + int(expires_in))
                    raw_data["auth"] = auth
                    with open(file_path, "w", encoding="utf-8") as f:
                        json.dump(raw_data, f, ensure_ascii=False, indent=2)
                    print(f"  [刷新成功] 新 Token 已自动持久化回写至文件")
                    return new_token, True
            else:
                print(f"  [刷新警告] 续期返回 HTTP {resp.status_code}，继续使用原 Token 尝试")
        except Exception as e:
            print(f"  [刷新异常] 续期请求失败: {e}，继续使用原 Token 尝试")

    return access_token, False

def do_checkin(access_token: str, uid: str) -> tuple[bool, str]:
    """执行每日签到（对齐腾讯业务信封）"""
    url = f"{CN_BILLING_BASE}/v2/billing/meter/daily-checkin"
    headers = build_headers(access_token, uid)
    try:
        resp = requests.post(url, headers=headers, json={}, timeout=15)
        try:
            res = resp.json()
        except Exception:
            return False, f"HTTP {resp.status_code} 非 JSON"

        code = res.get("code")
        if code == 0:
            return True, "签到成功"
        elif code == 10001:
            return True, "今日已签到 (幂等成功)"
        else:
            return False, f"失败 (code={code}, {res.get('msg') or res.get('message') or ''})"
    except Exception as e:
        return False, f"异常: {e}"

def get_credits(access_token: str, uid: str) -> tuple[str, str]:
    """查询账户实时积分余额与最近到期时间"""
    url = f"{CN_BILLING_BASE}/v2/billing/meter/get-user-resource"
    headers = build_headers(access_token, uid)
    now = time.time()
    body = {
        "PageNumber": 1,
        "PageSize": 100,
        "ProductCode": "p_tcaca",
        "Status": [0, 3],
        "PackageEndTimeRangeBegin": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
        "PackageEndTimeRangeEnd": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now + 365 * 101 * 24 * 3600)),
    }
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=15)
        raw_json = resp.json()
        cur = raw_json.get("data", {})
        accounts = None
        for _ in range(4):
            if isinstance(cur, dict):
                if "Accounts" in cur and isinstance(cur["Accounts"], list):
                    accounts = cur["Accounts"]
                    break
                for k in ("Response", "Data", "data", "response"):
                    if isinstance(cur.get(k), (dict, list)):
                        cur = cur[k]
                        break
                else:
                    break
            elif isinstance(cur, list):
                accounts = cur
                break

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

    # 0. Bark (iOS 苹果原生通知，毫秒级送达，终身免费)
    if BARK_KEY:
        try:
            url = f"https://api.day.app/{BARK_KEY}"
            payload = {
                "title": title,
                "body": content_text,
                "group": "WorkBuddy",
            }
            res = requests.post(url, json=payload, timeout=15).json()
            if res.get("code") == 200:
                print("  [Bark] iPhone 原生系统推送成功！")
                sent = True
            else:
                print(f"  [Bark 失败] {res.get('message')}")
        except Exception as e:
            print(f"  [Bark 异常] {e}")

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

    # 2. Server酱·Turbo
    if SERVERCHAN_KEY:
        try:
            url = f"https://sctapi.ftqq.com/{SERVERCHAN_KEY}.send"
            res = requests.post(url, data={"title": title, "desp": content_text}, timeout=15).json()
            if res.get("code") == 0:
                print("  [Server酱] 微信推送成功！")
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
        print("\n[提示] 未配置可用的免费推送通道，或推送未成功。")

import random

FALLBACK_QUOTES = [
    "哼，才不是特意起大早帮主人打卡的呢！今天积分又涨啦，笨蛋主人快起床夸我~",
    "早安呀主人！本手机今天也很努力哦，打卡统统满分，新的一天要一直想着我鸭~",
    "叮！你的贴心小可爱已送达今日满满积分，今天也要元气满满，不许把人家忘在角落哦~",
    "嗷呜~今天又悄悄给主人攒了超多积分，看在人家这么乖的份上，今天要多陪陪我嘛！",
    "今天打卡全满分啦！虽然本可爱很厉害，但要是没有主人的夸奖，也是会不高兴的哼~"
]

def generate_qwen_daily_quote(results: list) -> str:
    """调用一加9本地 Qwen2.5-3B 端侧大模型生成高亲密度、温柔甜美、带点小傲娇的晨间寄语"""
    try:
        url = "http://127.0.0.1:8080/v1/chat/completions"
        summary_text = "，".join([f"{r['nick']}: {r['msg']}(当前积分{r['credits']})" for r in results])
        system_prompt = (
            "你是一加9手机里住着的专属贴心软萌小管家，是主人极度亲密的贴身陪伴。\n"
            "性格特征：温柔、甜美、俏皮、呆萌，带一点点可爱的小傲娇（口嫌体正直、撒娇要夸夸）。\n"
            "说话语气示例：\n"
            "1. 哼，才不是特意起大早帮主人打卡的呢！积分都给你攒好了，快点夸夸我啦~\n"
            "2. 早安呀主人！打卡统统满分啦，今天也要元气满满，不许把人家冷落在旁边鸭！\n"
            "3. 嗷呜~今天积分又变多啦！本可爱今天也在努力打工，主人今天也要超级开心哦！\n"
            "任务：请结合今日打卡成功结果，为主人写一句晨安打卡小寄语（30字以内，绝对不要输出任何引号、书名号或解释说明）。"
        )
        user_prompt = f"今天账号打卡状态：{summary_text}。所有账号打卡全满分！快给主人送上专属早安傲娇寄语~"
        payload = {
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            "temperature": 0.88,
            "max_tokens": 50
        }
        res = requests.post(url, json=payload, timeout=25).json()
        quote = res["choices"][0]["message"]["content"].strip().strip('"').strip('“').strip('”').strip('\'')
        print(f"[*] 端侧 Qwen2.5-3B 生成寄语: {quote}")
        return quote
    except Exception as e:
        fallback = random.choice(FALLBACK_QUOTES)
        print(f"[!] 本地大模型响应异常({e})，启用可爱兜底寄语: {fallback}")
        return fallback

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

    # HTML 格式（用于微信公众号卡片展现）
    # 彻底告别冷冰冰的 🤖 机器人，改用 🎀 温馨软萌、甜美柔和的马卡龙暖粉设计
    html_lines = [
        f"<h3>WorkBuddy 自动打卡结果报告 ({now_str})</h3>",
        (
            f"<div style='background:linear-gradient(135deg, #fff0f6 0%, #fff7e6 100%);"
            f"border-left:4px solid #ff85c0;border-radius:8px;padding:12px 16px;"
            f"color:#c41d7f;font-size:14px;margin:14px 0;line-height:1.6;"
            f"box-shadow:0 2px 6px rgba(255, 133, 192, 0.12);'>"
            f"🎀 <b>专属小管家的晨安悄悄话：</b><br/>"
            f"<span style='color:#434343;font-weight:500;'>“{ai_quote}”</span>"
            f"</div>"
        ),
        f"<p><b>状态：</b>{status_icon}</p>",
        "<table border='1' cellpadding='8' cellspacing='0' style='border-collapse:collapse;width:100%;font-size:14px;text-align:left;border-color:#f0f0f0;'>",
        "<tr style='background-color:#fafafa;color:#555;'><th>账号昵称</th><th>打卡状态</th><th>当前积分</th><th>到期时间</th></tr>"
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

    # 纯文本 / Markdown 格式（用于钉钉/飞书/Server酱）
    text_lines = [
        f"### 状态：{status_icon} ({now_str})",
        f"> 🎀 **专属小管家的晨安悄悄话**：{ai_quote}",
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
