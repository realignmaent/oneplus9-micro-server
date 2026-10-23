import subprocess, json, re, os

# 设备序列号不入库：从环境变量注入（export OP9_ADB_SERIAL=xxxx）
ADB_TARGET_ARGS = ['-s', os.environ['OP9_ADB_SERIAL']] if os.environ.get('OP9_ADB_SERIAL') else []

mem_out = subprocess.check_output(['adb', *ADB_TARGET_ARGS, 'shell', 'dumpsys', 'meminfo']).decode('utf-8', errors='ignore')
top_out = subprocess.check_output(['adb', *ADB_TARGET_ARGS, 'shell', 'top', '-b', '-n', '1']).decode('utf-8', errors='ignore')

# parse top cpu
cpu_map = {}
for line in top_out.splitlines():
    parts = line.split()
    if len(parts) >= 12 and parts[0].isdigit():
        pid = parts[0]
        cpu = parts[8]
        args = parts[11]
        cpu_map[args] = cpu
        cpu_map[pid] = cpu

# Find "Total RSS by process:" section
rss_section = ""
if "Total RSS by process:" in mem_out:
    rss_section = mem_out.split("Total RSS by process:")[1].split("Total PSS by process:")[0]

KNOWLEDGE_BASE = {
    # Micro-server
    "llama-server": ("Qwen2.5-3B 本地推理服务", "核心服务", "端侧 AI 离线推理引擎 (提供 OpenAI API)", False, ""),
    "com.termux": ("Termux Linux 终端底座", "核心服务", "PRoot Debian 容器与后台自愈底座", False, ""),
    "node": ("青龙面板 Node.js 服务", "核心服务", "定时自动化打卡与脚本调度系统", False, ""),
    "crond": ("宿主 Crond 守护进程", "核心服务", "负责每分钟双进程自愈与温控巡检", False, ""),
    
    # Bloatware (safe to freeze/disable)
    "com.finshell.wallet": ("欢太金融 / 钱包", "冗余预装", "金融借贷推广与绑卡常驻，微服务器完全无用", True, "pm disable-user --user 0 com.finshell.wallet"),
    "com.heytap.quicksearchbox": ("全局搜索", "冗余预装", "桌面下拉全局搜索框，常驻占用近200MB", True, "pm disable-user --user 0 com.heytap.quicksearchbox"),
    "com.heytap.health": ("欢太健康 / 计步服务", "冗余预装", "手机放在桌上当服务器，不需要计步与健康监测", True, "pm disable-user --user 0 com.heytap.health"),
    "com.oplus.healthservice": ("健康服务组件", "冗余预装", "后台常驻传感器计步监听", True, "pm disable-user --user 0 com.oplus.healthservice"),
    "com.heytap.accessory": ("智能穿戴设备服务", "冗余预装", "蓝牙耳机/智能手表手环联动常驻", True, "pm disable-user --user 0 com.heytap.accessory"),
    "com.heytap.mydevices": ("我的设备 / 智能家居", "冗余预装", "OPPO 生态智能家居配对常驻服务", True, "pm disable-user --user 0 com.heytap.mydevices"),
    "com.opos.ads": ("OPPO 商业广告服务", "冗余预装", "系统广告分发与推送常驻", True, "pm disable-user --user 0 com.opos.ads"),
    "com.oplus.statistics.rom": ("ROM 遥测数据统计", "冗余预装", "后台收集系统使用日志频繁唤醒上报", True, "pm disable-user --user 0 com.oplus.statistics.rom"),
    "com.oplus.aiunit": ("OPPO 原厂 AI 单元", "冗余预装", "原厂旧版离线语音/图库识别，已有 Qwen2.5 覆盖", True, "pm disable-user --user 0 com.oplus.aiunit"),
    "com.coloros.assistantscreen": ("Breeno 速览 / 负一屏", "冗余预装", "桌面最左侧负一屏信息流卡片", True, "pm disable-user --user 0 com.coloros.assistantscreen"),
    "com.microsoft.appmanager": ("连接至 Windows", "冗余预装", "微软手机连接跨屏协作后台", True, "pm disable-user --user 0 com.microsoft.appmanager"),
    "com.coloros.smartsidebar": ("智能侧边栏", "冗余预装", "屏幕边缘滑出的浮窗侧边栏", True, "pm disable-user --user 0 com.coloros.smartsidebar"),
    "com.coloros.sceneservice": ("场景服务 / 智慧出行", "冗余预装", "常驻扫描火车航班快递等出行场景", True, "pm disable-user --user 0 com.coloros.sceneservice"),
    "com.oplus.cast": ("无线投屏服务", "冗余预装", "手机无线投屏常驻服务", True, "pm disable-user --user 0 com.oplus.cast"),
    "com.unionpay.tsmservice": ("银联可信服务", "冗余预装", "银联 NFC 刷卡常驻", True, "pm disable-user --user 0 com.unionpay.tsmservice"),
    "com.heytap.pictorial": ("乐划锁屏广告", "冗余预装", "轮播锁屏壁纸与广告推送", True, "pm disable-user --user 0 com.heytap.pictorial"),
    "com.heytap.speechassist": ("小布语音助手", "冗余预装", "语音唤醒与监听服务", True, "pm disable-user --user 0 com.heytap.speechassist"),
    "com.heytap.themestore": ("主题商店", "冗余预装", "壁纸铃声推送", True, "pm disable-user --user 0 com.heytap.themestore"),
    "com.heytap.market": ("OPPO 软件商店", "冗余预装", "官方应用商店后台下载更新常驻", True, "pm disable-user --user 0 com.heytap.market"),
    "com.heytap.browser": ("OPPO 自带浏览器", "冗余预装", "自带资讯流推送浏览器", True, "pm disable-user --user 0 com.heytap.browser"),
    "com.heytap.yoli": ("小视频服务", "冗余预装", "短视频推荐与缓存", True, "pm disable-user --user 0 com.heytap.yoli"),
    "com.heytap.reader": ("欢太阅读", "冗余预装", "电子书推送常驻", True, "pm disable-user --user 0 com.heytap.reader"),
    "com.oplus.appdetail": ("应用详情推荐服务", "冗余预装", "安装App时推荐其他软件广告", True, "pm disable-user --user 0 com.oplus.appdetail"),
    "com.oplus.remotecontrol": ("红外遥控服务", "冗余预装", "红外遥控常驻", True, "pm disable-user --user 0 com.oplus.remotecontrol"),
    
    # Recents / Third-party apps
    "com.android.vending": ("Google Play 商店", "前台残留", "应用商店后台进程，可划掉退出", True, "am force-stop com.android.vending"),
    "com.android.settings": ("系统设置", "前台残留", "设置界面残留后台，可划掉退出", True, "am force-stop com.android.settings"),
    "com.coloros.filemanager": ("文件管理器", "前台残留", "文件管理器残留后台，可划掉退出", True, "am force-stop com.coloros.filemanager"),
    "org.fdroid.fdroid": ("F-Droid 商店", "前台残留", "开源商店残留后台，可划掉退出", True, "am force-stop org.fdroid.fdroid"),
    "com.follow.clash": ("Clash 代理客户端", "用户应用", "代理客户端（若需要科学上网请保留）", False, ""),
    
    # System core
    "system": ("Android 系统核心 (SystemServer)", "系统底层", "Android 核心管理系统", False, ""),
    "com.android.systemui": ("系统界面 (SystemUI)", "系统底层", "状态栏、通知栏与导航栏核心", False, ""),
    "com.android.launcher": ("系统桌面启动器", "系统底层", "手机主屏幕桌面", False, ""),
    "com.android.phone": ("电话与网络通信底层", "系统底层", "基带与通话短信数据服务", False, ""),
    "surfaceflinger": ("SurfaceFlinger 合成器", "系统底层", "屏幕画面渲染与图层合成", False, ""),
    "com.baidu.input_oppo": ("百度输入法定制版", "系统输入", "手机当前默认输入法", False, ""),
}

procs = []
seen = set()

for line in rss_section.splitlines():
    line = line.strip()
    m = re.search(r'([0-9,]+)K:\s+(.+?)\s+\(pid\s+(\d+)', line)
    if not m:
        continue
    raw_name = m.group(2).strip()
    pid = m.group(3).strip()
    if raw_name in seen:
        continue
    seen.add(raw_name)
    rss_kb = int(m.group(1).replace(',', ''))
    rss_mb = round(rss_kb / 1024, 1)
    if rss_mb < 2.0:
        continue
    cpu_val = cpu_map.get(raw_name, cpu_map.get(pid, '0.0'))
    try:
        cpu_float = float(cpu_val.replace('%', ''))
    except Exception:
        cpu_float = 0.0

    matched_info = None
    for k, v in KNOWLEDGE_BASE.items():
        if k in raw_name:
            matched_info = v
            break
            
    if matched_info:
        title, cat, desc, safe, cmd = matched_info
    else:
        if raw_name.startswith("com.android."):
            clean_n = raw_name.replace("com.android.", "")
            title, cat, desc, safe, cmd = (f"Android: {clean_n}", "系统底层", "Android 原生组件", False, "")
        elif raw_name.startswith("com.oplus.") or raw_name.startswith("com.heytap.") or raw_name.startswith("com.coloros."):
            clean_n = raw_name.split(".")[-1]
            title, cat, desc, safe, cmd = (f"ColorOS: {clean_n}", "系统厂商服务", "ColorOS 系统常驻服务", False, "")
        else:
            title, cat, desc, safe, cmd = (raw_name, "其他进程", "后台驻留进程", False, "")

    procs.append({
        "raw_name": raw_name,
        "title": title,
        "category": cat,
        "desc": desc,
        "pid": pid,
        "mem_mb": rss_mb,
        "cpu": f"{cpu_float}%",
        "cpu_float": cpu_float,
        "safe_disable": safe,
        "cmd": cmd
    })

procs.sort(key=lambda x: x['mem_mb'], reverse=True)

with open("scratch/clean_procs.json", "w", encoding="utf-8") as f:
    json.dump(procs, f, indent=2, ensure_ascii=False)

bloat = [p for p in procs if p['safe_disable']]
bloat_mem = sum(p['mem_mb'] for p in bloat)
print(f"Total extracted real processes: {len(procs)}")
print(f"Bloatware / Unused processes: {len(bloat)}")
print(f"Total potential RAM savings: {bloat_mem:.1f} MB (~{bloat_mem/1024:.2f} GB)")
print("\nTop 15 Bloatware to disable:")
for b in bloat[:15]:
    print(f"[{b['mem_mb']:>6.1f} MB] {b['title']:<20} | {b['raw_name']}")
