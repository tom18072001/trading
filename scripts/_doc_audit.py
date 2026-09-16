import pathlib
import re

from fastapi.testclient import TestClient

from api.main import app

live = set(TestClient(app).get("/openapi.json").json()["paths"])


def norm(p: str) -> str:
    return re.sub(r"\{[^}]+\}", "{}", p.rstrip(".,`)*_ "))


def expand(p: str) -> list[str]:
    """`/a/{x,y}` is brace shorthand for two paths, not a path parameter.

    Without this every doc that writes `/api/flow/{series,heat}` — the compact
    form these tables use — is reported as one ghost route. Distinguished by the
    comma: FastAPI path params cannot contain one.
    """
    m = re.search(r"\{([^}]*,[^}]*)\}", p)
    if not m:
        return [p]
    return [
        q
        for alt in m.group(1).split(",")
        for q in expand(p[: m.start()] + alt.strip() + p[m.end() :])
    ]


live_n = {norm(p) for p in live}
pat = re.compile(r"(?:GET|POST|PATCH|DELETE)[`\s]+(/api/[A-Za-z0-9/_{},*-]+)")

for f in sorted(pathlib.Path(".").rglob("*.md")):
    s = str(f)
    if ".venv" in s or "node_modules" in s:
        continue
    txt = f.read_text(encoding="utf-8", errors="ignore")
    claimed = {norm(q) for m in pat.finditer(txt) for q in expand(m.group(1))}
    ghosts = sorted(c for c in claimed if c not in live_n and "*" not in c)
    if ghosts:
        print(f"{f}:")
        for g in ghosts:
            print(f"    {g}")
