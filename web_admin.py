from flask import Flask, jsonify, request, send_from_directory, abort
from pathlib import Path
import json
import time
import threading

APP_ROOT = Path(__file__).resolve().parent
WEB_DIR = APP_ROOT / "frontend"
CONFIG_DIR = APP_ROOT / "config"
RESULTS_DIR = APP_ROOT / "result"
RUN_SINGLE_FILE = RESULTS_DIR / "_run_single.json"

QUERIES_FILE = CONFIG_DIR / "querys.json"
RUN_NOW_FLAG = RESULTS_DIR / "_run_now.flag"   # señal simple para el worker

app = Flask(__name__, static_folder=None)

def _read_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))

def _write_json_atomic(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=4, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)

def _validate_queries(payload):
    # payload esperado: {"queries":[{"q":"...", "type":"domain|keyword|email|auto"}]}
    if not isinstance(payload, dict):
        return False, "Payload debe ser un objeto JSON."
    qs = payload.get("queries")
    if not isinstance(qs, list):
        return False, "Falta 'queries' o no es una lista."

    out = []
    for i, it in enumerate(qs):
        if not isinstance(it, dict):
            return False, f"queries[{i}] no es objeto."
        q = str(it.get("q", "")).strip()
        t = str(it.get("type", "auto")).strip().lower() or "auto"
        if not q:
            return False, f"queries[{i}].q está vacío."
        if t not in ("domain", "keyword", "email", "auto"):
            return False, f"queries[{i}].type inválido: {t}"
        out.append({"q": q, "type": t})
    return True, {"queries": out}

def _latest_leak_files():
    # Devuelve lista de paths leaks_*.json más recientes, por carpeta (query)
    if not RESULTS_DIR.exists():
        return []
    files = []
    for folder in RESULTS_DIR.iterdir():
        if folder.is_dir():
            snaps = sorted(folder.glob("leaks_*.json"), reverse=True)
            if snaps:
                files.append(snaps[0])
    return files

def _extract_source_info(row: dict) -> dict:
    # intenta detectar campos habituales
    # adapta nombres si en tu JSON son distintos
    source = row.get("source") or row.get("breach") or row.get("database") or row.get("name")
    date = row.get("date") or row.get("breach_date") or row.get("last_update") or row.get("created")
    return {"source": source, "date": date}

def _extract_creds(row: dict) -> dict:
    email = row.get("email") or row.get("mail")
    user = row.get("username") or row.get("user") or row.get("login")
    password = row.get("password") or row.get("pass")
    return {"email": email, "username": user, "password": password}

def _build_leaks_view():
    items = []
    for fp in _latest_leak_files():
        data = _read_json(fp) or {}
        folder = fp.parent.name
        if "__" in folder:
            entity_type, entity = folder.split("__", 1)
        else:
            entity_type, entity = "auto", folder

        rows = data.get("result", []) or []
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue

            creds = _extract_creds(row)
            src = _extract_source_info(row)

            # enmascarado
            email_m = mask_email(creds["email"]) if creds.get("email") else None
            user_m = mask_text(creds["username"]) if creds.get("username") else None
            pass_m = mask_password(creds["password"]) if creds.get("password") else None

            items.append({
                "id": f"{folder}:{fp.name}:{i}",
                "status": "new",  # “new/deleted” real lo hacemos con diff (si quieres lo dejamos para el siguiente paso)
                "entityType": entity_type,
                "entity": entity,
                "foundAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(fp.stat().st_mtime)),
                "summary": f"{src.get('source') or 'unknown'}" + (f" ({src.get('date')})" if src.get("date") else ""),
                "details": {
                    "source": src.get("source"),
                    "breach_date": src.get("date"),
                    "email": email_m,
                    "username": user_m,
                    "password": pass_m,
                    # si quieres ver más campos sin credenciales:
                    "raw_keys": sorted(list(row.keys()))[:30],
                }
            })
    return items


# Helpers de mascaramiento
def mask_email(s: str) -> str:
    if "@" not in s: 
        return mask_text(s)
    user, dom = s.split("@", 1)
    user_m = (user[:2] + "***") if len(user) > 2 else "***"
    dom_m = dom[:1] + "***"
    return f"{user_m}@{dom_m}"

def mask_text(s: str) -> str:
    s = str(s)
    if len(s) <= 2: 
        return "***"
    return s[:1] + "***" + s[-1:]

def mask_password(p: str) -> str:
    if not p:
        return ""
    # nunca en claro: solo longitud + 1-2 chars
    p = str(p)
    return f"{p[:1]}***{p[-1:]} (len={len(p)})"

# ----------------------
# Frontend (estático)
# ----------------------
@app.get("/")
def home():
    return send_from_directory(WEB_DIR, "html/index.html")

@app.get("/leaks")
def leaks_page():
    return send_from_directory(WEB_DIR, "html/leaks.html")

@app.get("/js/<path:filename>")
def js_files(filename):
    return send_from_directory(WEB_DIR / "js", filename)

@app.get("/css/<path:filename>")
def css_files(filename):
    return send_from_directory(WEB_DIR / "css", filename)

# ----------------------
# API
# ----------------------
@app.get("/api/queries")
def api_get_queries():
    data = _read_json(QUERIES_FILE)
    return jsonify(data or {"queries": []})

@app.put("/api/queries")
def api_put_queries():
    payload = request.get_json(silent=True)
    ok, norm = _validate_queries(payload)
    if not ok:
        return jsonify({"ok": False, "error": norm}), 400
    _write_json_atomic(QUERIES_FILE, norm)
    return jsonify({"ok": True, "queries": norm["queries"]})

@app.get("/api/leaks")
def api_get_leaks():
    return jsonify({"ok": True, "items": _build_leaks_view()})

@app.post("/api/run-now")
def api_run_now():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    RUN_NOW_FLAG.write_text(str(time.time()), encoding="utf-8")
    return jsonify({"ok": True, "message": "Run-now flag escrito"})
# ----------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8081)
