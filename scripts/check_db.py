import sqlite3
conn = sqlite3.connect("vnstock_market.db")
cur = conn.cursor()
cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
tables = [r[0] for r in cur.fetchall()]
print(f"Tables ({len(tables)}):")
for t in tables:
    print(f"  - {t}")

# Check if api_users table exists
if "api_users" in tables:
    cur.execute("SELECT id, email, tier FROM api_users")
    users = cur.fetchall()
    print(f"\nAPI Users ({len(users)}):")
    for u in users:
        print(f"  id={u[0]} email={u[1]} tier={u[2]}")
else:
    print("\n[!] api_users table NOT found")

if "api_keys" in tables:
    cur.execute("SELECT id, user_id, key_prefix, is_active FROM api_keys")
    keys = cur.fetchall()
    print(f"\nAPI Keys ({len(keys)}):")
    for k in keys:
        print(f"  id={k[0]} user_id={k[1]} prefix={k[2]} active={k[3]}")
else:
    print("[!] api_keys table NOT found")

conn.close()
