import sqlite3, json, pathlib
con = sqlite3.connect(str(pathlib.Path(__file__).resolve().parent.parent / "vnstock_market.db"))
r = con.execute("SELECT id,model_name,train_size,test_size,metrics FROM model_runs ORDER BY id DESC LIMIT 1").fetchone()
print("id", r[0], "|", r[1], "| train", r[2], "| test", r[3])
m = json.loads(r[4] or "{}")
for k in ("backend","top1_excess_hit","ndcg_at_3","decile_monotonic","quintile_means","embargo_days","purged_dates","n_eval_days"):
    print(f"  {k:<18} {m.get(k)}")
