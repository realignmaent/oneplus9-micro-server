import sqlite3
import datetime

conn = sqlite3.connect("/ql/data/db/database.sqlite")
cur = conn.cursor()

# Check if already exists
cur.execute("SELECT id, name FROM Crontabs WHERE command LIKE '%thermal_guard.py%'")
row = cur.fetchone()

now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S.000 +00:00")

if row:
    print(f"Task already exists: ID={row[0]}, Name={row[1]}")
else:
    sql = """
    INSERT INTO Crontabs (
        name, command, schedule, saved, status, isSystem, isDisabled, isPinned,
        labels, extra_schedules, allow_multiple_instances, createdAt, updatedAt
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """
    cur.execute(sql, (
        "一加9 硬件温度与健康巡检守护",
        "task thermal_guard.py",
        "*/15 * * * *",
        1,
        1,
        0,
        0,
        0,
        '["硬件守护"]',
        '[]',
        0,
        now_str,
        now_str
    ))
    conn.commit()
    print("Successfully added Crontab: 一加9 硬件温度与健康巡检守护 (*/15 * * * *)")

# Print all tasks
print("\nAll Crontab Tasks:")
for r in cur.execute("SELECT id, name, command, schedule, status, isDisabled FROM Crontabs").fetchall():
    print(r)

conn.close()
