import sqlite3, glob, os

print("Files in /ql/data/db/:", os.listdir("/ql/data/db") if os.path.exists("/ql/data/db") else "None")
db_paths = glob.glob("/ql/data/db/*.sqlite") + glob.glob("/ql/data/db/*.db") + glob.glob("/ql/data/config/*.sqlite")
for p in db_paths:
    print(f"\n--- Checking {p} ---")
    try:
        conn = sqlite3.connect(p)
        tables = [x[0] for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        print("Tables:", tables)
        conn.close()
    except Exception as e:
        print("Error:", e)
