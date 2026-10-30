#!/usr/bin/env python3
"""starboatthai - บันทึกรายละเอียดการทำงาน (รองรับทุกเครือข่าย + รหัสผ่าน)

  python starboatthai.py             เปิดโปรแกรม (http://0.0.0.0:8765) และสำรองให้ถ้าครบ 7 วัน
  python starboatthai.py --backup    สำรองข้อมูลทันทีแล้วจบการทำงาน
  python starboatthai.py --dir PATH  เปลี่ยนโฟลเดอร์สำรอง
"""
import argparse, base64, json, os, shutil, sys, threading, webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(errors="replace")
    except Exception:
        pass

APP = Path(__file__).resolve().parent
DATA = APP / "data.json"
STATE = APP / "backup_state.json"
PREFIX = "starboatthai-"
KEEP = 52
LOCK = threading.Lock()
cfg = {"dir": Path.home() / "StarboatthaiBackups", "port": 8765}

# กำหนดชื่อผู้ใช้และรหัสผ่านสำหรับเข้าใช้งานระบบ
AUTH_USER = "admin"
AUTH_PASS = "starboat123"


def say(*a):
    try:
        print(*a)
    except Exception:
        pass


def read_items():
    if not DATA.exists():
        return []
    try:
        d = json.loads(DATA.read_text(encoding="utf-8"))
        if isinstance(d, list):
            return d
        raise ValueError
    except (OSError, ValueError):
        try:
            os.replace(DATA, APP / f"data.corrupt-{datetime.now():%Y%m%d-%H%M%S}.json")
        except OSError:
            pass
        return []


def write_json(path, obj):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def save_items(items):
    if DATA.exists():
        try:
            shutil.copyfile(DATA, APP / "data.previous.json")
        except OSError:
            pass
    write_json(DATA, items)


def do_backup():
    dest = cfg["dir"]
    dest.mkdir(parents=True, exist_ok=True)
    now = datetime.now()
    path = dest / f"{PREFIX}{now:%Y-%m-%d_%H%M%S}.json"
    write_json(path, {"app": "worklog", "version": 2, "exportedAt": now.isoformat(), "items": read_items()})
    for old in sorted(dest.glob(PREFIX + "*.json"))[:-KEEP]:
        old.unlink(missing_ok=True)
    write_json(STATE, {"last": now.isoformat()})
    return path


def backup_due():
    try:
        last = datetime.fromisoformat(json.loads(STATE.read_text())["last"])
        return datetime.now() - last >= timedelta(days=7)
    except (OSError, ValueError, KeyError):
        return True


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def check_auth(self):
        auth = self.headers.get("Authorization")
        if not auth or not auth.startswith("Basic "):
            return False
        try:
            encoded = auth.split(" ")[1]
            decoded = base64.b64decode(encoded).decode("utf-8")
            user, pwd = decoded.split(":", 1)
            return user == AUTH_USER and pwd == AUTH_PASS
        except Exception:
            return False

    def unauthorized(self):
        body = b'{"ok": false, "error": "Unauthorized"}'
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="Starboatthai Secure Access"')
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        if not isinstance(body, bytes):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.check_auth():
            return self.unauthorized()
        if self.path in ("/", "/index.html"):
            return self.send(200, (APP / "index.html").read_bytes(), "text/html; charset=utf-8")
        if self.path == "/api/items":
            with LOCK:
                return self.send(200, read_items())
        self.send(404, {"ok": False})

    def do_PUT(self):
        if not self.check_auth() or self.path != "/api/items":
            return self.send(401 if not self.check_auth() else 403, {"ok": False})
        n = int(self.headers.get("Content-Length", 0))
        if n > 20_000_000:
            return self.send(413, {"ok": False})
        try:
            items = json.loads(self.rfile.read(n))
            assert isinstance(items, list)
        except (ValueError, AssertionError):
            return self.send(400, {"ok": False})
        with LOCK:
            save_items(items)
        self.send(200, {"ok": True})

    def do_POST(self):
        if not self.check_auth() or self.path != "/api/backup":
            return self.send(401 if not self.check_auth() else 403, {"ok": False})
        with LOCK:
            try:
                p = do_backup()
            except OSError as e:
                return self.send(500, {"ok": False, "error": str(e)})
        self.send(200, {"ok": True, "path": str(p)})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--backup", action="store_true")
    ap.add_argument("--dir")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true")
    a = ap.parse_args()
    if a.dir:
        cfg["dir"] = Path(a.dir).expanduser()
    cfg["port"] = a.port
    if a.backup:
        say("สำรองข้อมูลแล้ว:", do_backup())
        return
    if backup_due():
        try:
            say("ครบกำหนดสำรองข้อมูล สำรองแล้ว:", do_backup())
        except OSError as e:
            say("สำรองข้อมูลไม่สำเร็จ:", e)
            
    # เปลี่ยนมาผูกกับทุก Network Interface (0.0.0.0) เพื่อให้เครื่องอื่นในวง LAN เข้าถึงได้
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", a.port), H)
    except OSError:
        say(f"เปิดพอร์ต {a.port} ไม่ได้ (อาจมีโปรแกรมเปิดอยู่แล้ว) ลอง --port เลขอื่น")
        sys.exit(1)
        
    say("เปิดใช้งานที่พอร์ต", a.port, "(กด Ctrl+C เพื่อปิด)")
    url = f"http://127.0.0.1:{a.port}"
    if not a.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
