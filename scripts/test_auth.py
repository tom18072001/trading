try:
    from passlib.hash import bcrypt
    h = bcrypt.hash("test123")
    print(f"bcrypt OK: {h[:20]}...")
    print(f"verify: {bcrypt.verify('test123', h)}")
except Exception as e:
    print(f"bcrypt FAILED: {e}")
    import traceback
    traceback.print_exc()
