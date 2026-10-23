#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""外部可用性探活：本机 8 个端口 + 公网 /health，失败时多通道告警（30 分钟节流）。"""
import json
import os
import socket
import time
import urllib.request

HOME = "/data/data/com.termux/files/home"
PORTS = {
    "qinglong": 5700,
    "dashboard": 5701,
    "wb2api": 7863,
    "workbuddy": 7864,
    "llama": 8080,
    "gateway": 8081,
    "qodergateway": 5050,
    "ssh": 8022,
}
STATE = os.path.join(HOME, "logs", "health_probe.json")
ALERT_STATE = os.path.join(HOME, "logs", "health_probe_alert.ts")
COOLDOWN = 30 * 60


def port_ok(port, timeout=1.5):
    try:
        with socket.socket() as s:
            s.settimeout(timeout)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except Exception:
        return False


def public_probe():
    try:
        url = open(os.path.join(HOME, "public_url.txt"), encoding="utf-8").read().strip().rstrip("/")
    except Exception:
        return {"ok": False, "error": "no public_url.txt", "url": None}
    if not url:
        return {"ok": False, "error": "empty public_url.txt", "url": None}
    try:
        req = urllib.request.Request(url + "/health", headers={"User-Agent": "op9-health-probe/1.0"})
        with urllib.request.urlopen(req, timeout=20) as r:
            body = r.read(200).decode("utf-8", "ignore")
            return {"ok": r.status == 200, "status": r.status, "url": url, "body": body[:120]}
    except Exception as e:
        return {"ok": False, "error": str(e), "url": url}


def notify(title, text):
    try:
        last = float(open(ALERT_STATE).read().strip())
    except Exception:
        last = 0
    if time.time() - last < COOLDOWN:
        return "throttled"
    try:
        from proxy_sentinel import send_all_notifications

        send_all_notifications(title, "<p>" + text + "</p>", text)
        with open(ALERT_STATE, "w") as f:
            f.write(str(int(time.time())))
        return "sent"
    except Exception as e:
        return "error: " + str(e)


def main():
    local = {name: port_ok(port) for name, port in PORTS.items()}
    pub = public_probe()
    ts = int(time.time())
    result = {"ts": ts, "ok": all(local.values()) and pub.get("ok", False), "local": local, "public": pub}
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False)
    if not result["ok"]:
        down = [k for k, v in local.items() if not v]
        parts = []
        if down:
            parts.append("本地端口异常: " + ", ".join("%s(:%d)" % (k, PORTS[k]) for k in down))
        if not pub.get("ok"):
            parts.append("公网探活失败: " + str(pub.get("error") or pub.get("status")))
        msg = " | ".join(parts)
        print("[%s] FAIL %s" % (time.strftime("%F %T"), msg))
        print("notify:", notify("OnePlus 9 服务异常", msg))
    else:
        print("[%s] OK 8/8 端口 + 公网" % time.strftime("%F %T"))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
