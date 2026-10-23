import subprocess, time, os

# 设备序列号不入库：从环境变量注入（export OP9_ADB_SERIAL=xxxx）
ADB_TARGET_ARGS = ["-s", os.environ["OP9_ADB_SERIAL"]] if os.environ.get("OP9_ADB_SERIAL") else []

PACKAGES_TO_DISABLE = [
    # 1. 商业推广与金融借贷
    "com.finshell.wallet",
    "com.opos.ads",
    "com.oplus.appdetail",
    "com.heytap.pictorial",
    "com.heytap.themestore",
    "com.heytap.browser",
    "com.heytap.yoli",
    "com.heytap.reader",
    
    # 2. 运动计步与健康
    "com.heytap.health",
    "com.oplus.healthservice",
    
    # 3. 蓝牙手环穿戴与智能家居
    "com.heytap.accessory",
    "com.heytap.mydevices",
    
    # 4. 全局搜索、语音与负一屏卡片
    "com.heytap.quicksearchbox",
    "com.heytap.speechassist",
    "com.coloros.assistantscreen",
    "com.coloros.sceneservice",
    
    # 5. 遥测统计与冗余原厂服务
    "com.oplus.statistics.rom",
    "com.oplus.aiunit",
    "com.microsoft.appmanager",
    "com.oplus.remotecontrol",
    "com.coloros.smartsidebar",
    "com.unionpay.tsmservice"
]

APPS_TO_STOP = [
    "com.android.vending",
    "com.coloros.filemanager",
    "com.android.settings",
    "org.fdroid.fdroid"
]

def get_mem():
    out = subprocess.check_output(["adb", *ADB_TARGET_ARGS, "shell", "cat", "/proc/meminfo"]).decode()
    total = 0
    avail = 0
    free = 0
    cached = 0
    for line in out.splitlines():
        if line.startswith("MemTotal:"):
            total = int(line.split()[1]) / 1024.0 # MB
        elif line.startswith("MemAvailable:"):
            avail = int(line.split()[1]) / 1024.0
        elif line.startswith("MemFree:"):
            free = int(line.split()[1]) / 1024.0
        elif line.startswith("Cached:"):
            cached = int(line.split()[1]) / 1024.0
    return total, avail, free, cached

print("=== 正在读取优化前内存数据 ===")
tot_before, avail_before, free_before, cache_before = get_mem()
print(f"总内存: {tot_before:.1f} MB | 可用内存: {avail_before:.1f} MB | 物理空闲: {free_before:.1f} MB\n")

print("=== 开始批量冻结/停用冗余系统预装组件 (pm disable-user --user 0) ===")
disabled_success = []
for pkg in PACKAGES_TO_DISABLE:
    res = subprocess.run(["adb", *ADB_TARGET_ARGS, "shell", f"pm disable-user --user 0 {pkg}"], capture_output=True, text=True)
    out = res.stdout.strip() or res.stderr.strip()
    if "disabled" in out or "new state" in out:
        print(f"[OK] 已成功冻结: {pkg}")
        disabled_success.append(pkg)
    elif "not found" in out:
        print(f"[SKIP] 该机型未安装: {pkg}")
    else:
        print(f"[+] 处置结果 {pkg}: {out}")

print("\n=== 正在关闭前台残留无用应用 ===")
for app in APPS_TO_STOP:
    subprocess.run(["adb", *ADB_TARGET_ARGS, "shell", f"am force-stop {app}"])
    print(f"[OK] 已终止残留应用: {app}")

# 强制触发一次 trim memory
subprocess.run(["adb", *ADB_TARGET_ARGS, "shell", "echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true"])
time.sleep(3)

print("\n=== 正在读取优化后内存数据 ===")
tot_after, avail_after, free_after, cache_after = get_mem()
freed_mb = avail_after - avail_before

print(f"\n==========================================")
print(f"优化前可用内存: {avail_before:.1f} MB ({avail_before/1024:.2f} GB)")
print(f"优化后可用内存: {avail_after:.1f} MB ({avail_after/1024:.2f} GB)")
print(f"本次净释放物理内存: {freed_mb:+.1f} MB ({freed_mb/1024:+.2f} GB)")
print(f"==========================================")
