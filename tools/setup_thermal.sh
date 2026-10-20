#!/data/data/com.termux/files/usr/bin/bash
echo "=== Step 1: Copy script to Qinglong scripts ==="
proot-distro login debian -- bash -c 'cp /sdcard/workbuddy/thermal_guard.py /ql/data/scripts/thermal_guard.py && chmod +x /ql/data/scripts/thermal_guard.py'

echo "=== Step 2: Test hardware sensor reading and test WeChat alert ==="
proot-distro login debian -- bash -c 'python3 /ql/data/scripts/thermal_guard.py --test-alert'

echo "=== Step 3: Test normal thermal evaluation ==="
proot-distro login debian -- bash -c 'python3 /ql/data/scripts/thermal_guard.py'

echo "=== Step 4: Add task into Qinglong Database ==="
proot-distro login debian -- python3 -c '
import sqlite3, datetime
conn = sqlite3.connect("/ql/data/db/database.sqlite")
cur = conn.cursor()
cur.execute("SELECT id FROM Crons WHERE command LIKE \"%thermal_guard.py%\"")
row = cur.fetchone()
now = datetime.datetime.now().isoformat()
if not row:
    cols = [x[1] for x in cur.execute("PRAGMA table_info(Crons)").fetchall()]
    print("Crons columns:", cols)
    fields = ["name", "command", "schedule", "status", "createdAt", "updatedAt"]
    vals = ["一加9 硬件温度与健康巡检守护", "task thermal_guard.py", "*/15 * * * *", 0, now, now]
    valid_fields = [f for f in fields if f in cols]
    valid_vals = [vals[i] for i, f in enumerate(fields) if f in cols]
    qmarks = ",".join(["?"] * len(valid_fields))
    col_str = ",".join(valid_fields)
    cur.execute(f"INSERT INTO Crons ({col_str}) VALUES ({qmarks})", valid_vals)
    conn.commit()
    print("成功插入青龙定时任务: thermal_guard.py (每15分钟)")
else:
    print("定时任务已存在，ID:", row[0])
conn.close()
'
echo "=== All steps finished ==="
