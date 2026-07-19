@echo off
title VN Trading - Sector Money-Flow
color 0A
echo.
echo  ====================================================
echo    VN Sector Money-Flow Trading System
echo    Backend: FastAPI :8000  ^|  Frontend: Vite :5173
echo  ====================================================
echo.

:: Auto-detect project directory (where this .bat lives)
set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"

:: Kill any existing instances first — by window title AND by port. The
:: title-only kill missed backends started manually or orphaned --reload
:: child processes; they accumulated and several uvicorn servers ended up
:: bound to :8000 at once, all thrashing CPU + the SQLite WAL. That — not
:: request-time compute — was what made every page load 5-9x slower
:: (diagnosed 2026-06-19). Killing by port guarantees a single backend.
taskkill /FI "WINDOWTITLE eq Backend - FastAPI" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Frontend - Vite" /F >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr "127.0.0.1:8000 .*LISTENING"') do taskkill /F /PID %%a >nul 2>&1
for /f "tokens=5" %%a in ('netstat -ano ^| findstr "127.0.0.1:5173 .*LISTENING"') do taskkill /F /PID %%a >nul 2>&1

:: Start Backend (FastAPI on port 8000)
echo [1/2] Starting Backend (FastAPI :8000)...
:: --reload-dir scopes the file watcher to Python source dirs ONLY. Watching
:: the whole project (uvicorn's default) makes the watcher recurse .venv,
:: node_modules and the live vnstock_market.db + -wal (20MB, mutating every
:: tick), which starves the request handler and made every page load 5-9x
:: slower (2026-06-19 fix). config.py edits at root now need a manual restart.
:: `uv run` resolves the project venv (Python 3.13 from .python-version +
:: uv.lock) and rebuilds it if broken. Bare `python` here silently picked up
:: the MS Store 3.11 with global packages - a different env than the jobs.
start "Backend - FastAPI" cmd /k "cd /d "%PROJECT_DIR%" && uv run python -m uvicorn api.main:app --reload --reload-dir api --reload-dir services --reload-dir analysis --reload-dir models --reload-dir database --reload-dir utils --port 8000"

:: Wait for backend to initialize
timeout /t 3 /nobreak >nul

:: Start Frontend (Vite on port 5173)
echo [2/2] Starting Frontend (Vite :5173)...
start "Frontend - Vite" cmd /k "cd /d "%PROJECT_DIR%\frontend" && npm run dev"

:: Wait for frontend to initialize
timeout /t 4 /nobreak >nul

:: Open browser
echo.
echo Opening http://localhost:5173 ...
start http://localhost:5173

echo.
echo  ====================================================
echo    Frontend : http://localhost:5173
echo    Backend  : http://localhost:8000/docs
echo  ====================================================
echo.
echo  Press any key to STOP all servers...
pause >nul

:: Kill servers on exit
taskkill /FI "WINDOWTITLE eq Backend - FastAPI" /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Frontend - Vite" /F >nul 2>&1
echo.
echo  Servers stopped. Goodbye!
timeout /t 2 >nul
