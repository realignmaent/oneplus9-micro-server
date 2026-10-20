import sqlite3
conn = sqlite3.connect("/ql/data/db/database.sqlite")
cur = conn.cursor()
cols = cur.execute("PRAGMA table_info(Crontabs)").fetchall()
print("Columns in Crontabs:")
for c in cols:
    print(c)
rows = cur.execute("SELECT * FROM Crontabs LIMIT 2").fetchall()
print("\nSample rows:")
for r in rows:
    print(r)
conn.close()
