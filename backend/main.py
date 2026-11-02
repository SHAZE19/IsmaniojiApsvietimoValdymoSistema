"""Single-room lighting system. Run from project root: uvicorn backend.main:app."""
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Literal
import hashlib
import hmac
import math
import os
import re
import secrets
import sqlite3
import time

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[1]
SESSION_SECONDS = 8 * 3600


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()
    return f"{salt}:{digest}"


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class NewUser(BaseModel):
    username: str = Field(pattern=r"^[a-zA-Z0-9_.-]{3,64}$")
    display_name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=12, max_length=256)
    role: Literal["user", "admin"] = "user"


class Enabled(BaseModel):
    enabled: bool = Field(strict=True)


class CardInput(BaseModel):
    card_id: str

    @field_validator("card_id")
    @classmethod
    def valid_uid(cls, value: str) -> str:
        value = value.strip().upper()
        if not re.fullmatch(r"(?:[0-9A-F]{8}|[0-9A-F]{14}|[0-9A-F]{20})", value):
            raise ValueError("UID: 8, 14 arba 20 šešioliktainių simbolių be tarpų")
        return value


class NewCard(CardInput):
    label: str = Field(min_length=1, max_length=100)
    user_id: int = Field(gt=0)


class Command(BaseModel):
    mode: Literal["auto", "on", "off"]
    brightness: int = Field(default=100, ge=1, le=100, strict=True)


class Settings(BaseModel):
    dim_after_seconds: int = Field(ge=5, le=86400, strict=True)
    off_after_seconds: int = Field(ge=10, le=86400, strict=True)
    dim_brightness: int = Field(ge=1, le=50, strict=True)

    @model_validator(mode="after")
    def ordered_timers(self):
        if self.off_after_seconds <= self.dim_after_seconds:
            raise ValueError("Išjungimo laikas turi būti ilgesnis už pritemdymo laiką")
        return self


class Telemetry(BaseModel):
    motion: bool = Field(strict=True)
    actual_brightness: int = Field(ge=0, le=100, strict=True)
    source: Literal["arduino", "simulator"] = "arduino"


def create_app(data_dir: Path | None = None) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("LIGHTING_DATA_DIR", ROOT / "backend" / "data"))
    db_path = data_dir / "lighting.sqlite3"
    dummy_hash = password_hash(secrets.token_urlsafe(24))

    @contextmanager
    def db():
        conn = sqlite3.connect(db_path, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def event(conn, kind, actor, detail):
        conn.execute("INSERT INTO events(at,kind,actor,detail) VALUES(?,?,?,?)", (time.time(), kind, actor, detail))

    @asynccontextmanager
    async def lifespan(application):
        data_dir.mkdir(parents=True, exist_ok=True)
        secret_file = data_dir / "device-secret.txt"
        key = os.environ.get("LIGHTING_DEVICE_KEY")
        if not key:
            if not secret_file.exists():
                secret_file.write_text(secrets.token_hex(32), encoding="utf-8")
            key = secret_file.read_text(encoding="utf-8").strip()
        if len(key) < 32:
            raise RuntimeError("LIGHTING_DEVICE_KEY turi turėti bent 32 simbolius")
        application.state.device_key = key
        with db() as conn:
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL COLLATE NOCASE,
                    display_name TEXT NOT NULL, password_hash TEXT NOT NULL,
                    role TEXT NOT NULL CHECK(role IN ('admin','user')), enabled INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS sessions (
                    token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS cards (
                    card_id TEXT PRIMARY KEY, label TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id),
                    enabled INTEGER NOT NULL DEFAULT 1, created_at REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY, at REAL NOT NULL, kind TEXT NOT NULL, actor TEXT NOT NULL, detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS settings (
                    id INTEGER PRIMARY KEY CHECK(id=1), dim_after_seconds INTEGER NOT NULL,
                    off_after_seconds INTEGER NOT NULL, dim_brightness INTEGER NOT NULL);
                INSERT OR IGNORE INTO settings VALUES(1,60,120,25);
                CREATE TABLE IF NOT EXISTS lighting (
                    id INTEGER PRIMARY KEY CHECK(id=1), mode TEXT NOT NULL, brightness INTEGER NOT NULL,
                    last_activity REAL, last_seen REAL, motion INTEGER NOT NULL DEFAULT 0,
                    actual_brightness INTEGER, last_card TEXT);
                INSERT OR IGNORE INTO lighting(id,mode,brightness) VALUES(1,'auto',100);
                CREATE INDEX IF NOT EXISTS events_kind_id ON events(kind,id);
                CREATE TABLE IF NOT EXISTS device_info (id INTEGER PRIMARY KEY CHECK(id=1), source TEXT NOT NULL);
                INSERT OR IGNORE INTO device_info VALUES(1,'arduino');
            """)
            if not conn.execute("SELECT 1 FROM users LIMIT 1").fetchone():
                password = os.environ.get("LIGHTING_ADMIN_PASSWORD") or secrets.token_urlsafe(18)
                if len(password) < 12:
                    raise RuntimeError("LIGHTING_ADMIN_PASSWORD turi turėti bent 12 simbolių")
                conn.execute("INSERT INTO users(username,display_name,password_hash,role) VALUES(?,?,?,'admin')",
                             ("admin", "Administratorius", password_hash(password)))
                (data_dir / "initial-credentials.txt").write_text(
                    f"Prisijungimas: admin\nSlaptažodis: {password}\nSaugokite vietoje. Nesiųskite į Git.\n", encoding="utf-8")
                event(conn, "system", "Sistema", "Sukurta duomenų bazė ir administratorius")
        yield

    app = FastAPI(title="Išmanioji apšvietimo valdymo sistema", version="2.0.0", lifespan=lifespan,
                  docs_url=None, redoc_url=None)

    @app.middleware("http")
    async def browser_security(request: Request, call_next):
        path = request.url.path
        if request.method in {"POST", "PATCH", "PUT", "DELETE"} and path.startswith("/api/"):
            is_device = path.startswith("/api/device/") or path == "/api/nfc/authorize"
            if not is_device and request.headers.get("x-requested-with") != "LightingApp":
                return Response(content='{"detail":"Trūksta apsaugos antraštės"}', status_code=403,
                                media_type="application/json")
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")
        if path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    def current_user(request: Request):
        token_hash = hashlib.sha256(request.cookies.get("lighting_session", "").encode()).hexdigest()
        with db() as conn:
            user = conn.execute("""SELECT u.id,u.username,u.display_name,u.role,u.enabled FROM sessions s
                JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.enabled=1""",
                                (token_hash, time.time())).fetchone()
        if not user:
            raise HTTPException(401, "Prisijunkite prie sistemos")
        return dict(user)

    def admin(user=Depends(current_user)):
        if user["role"] != "admin":
            raise HTTPException(403, "Reikalingos administratoriaus teisės")
        return user

    def device(x_device_key: str = Header(default="")):
        if not hmac.compare_digest(x_device_key.encode(), app.state.device_key.encode()):
            raise HTTPException(401, "Neteisingas įrenginio raktas")

    def state(conn):
        row = dict(conn.execute("SELECT * FROM lighting WHERE id=1").fetchone())
        settings = dict(conn.execute("SELECT * FROM settings WHERE id=1").fetchone())
        now = time.time()
        elapsed = now - row["last_activity"] if row["last_activity"] else settings["off_after_seconds"]
        if row["mode"] == "auto" and row["last_activity"] is not None and elapsed >= settings["off_after_seconds"]:
            conn.execute("UPDATE lighting SET last_activity=NULL WHERE id=1")
            row["last_activity"] = None
        desired, stage = 0, "off"
        if row["mode"] == "on":
            desired, stage = row["brightness"], "on"
        elif row["mode"] == "auto" and elapsed < settings["off_after_seconds"]:
            desired, stage = (min(row["brightness"], settings["dim_brightness"]), "dimmed") if elapsed >= settings["dim_after_seconds"] else (row["brightness"], "on")
        online = row["last_seen"] is not None and now - row["last_seen"] < 15
        return {"mode": row["mode"], "brightness": row["brightness"], "desired_brightness": desired,
                "device_source": conn.execute("SELECT source FROM device_info WHERE id=1").fetchone()[0],
                "stage": stage, "actual_brightness": row["actual_brightness"], "online": online,
                "motion": bool(row["motion"]) if online else False, "last_seen": row["last_seen"],
                "last_activity": row["last_activity"], "last_card": row["last_card"],
                "remaining_seconds": max(0, math.ceil(settings["off_after_seconds"] - elapsed)) if row["mode"] == "auto" and desired else None,
                "dim_after_seconds": settings["dim_after_seconds"], "off_after_seconds": settings["off_after_seconds"],
                "dim_brightness": settings["dim_brightness"], "server_time": now}

    def device_state(conn):
        current = state(conn)
        return {k: current[k] for k in ("mode", "brightness", "desired_brightness", "remaining_seconds", "dim_after_seconds", "off_after_seconds", "dim_brightness")}

    @app.post("/api/auth/login")
    def login(data: Login, response: Response):
        now = time.time()
        with db() as conn:
            user = conn.execute("SELECT * FROM users WHERE username=?", (data.username,)).fetchone()
            encoded = user["password_hash"] if user else dummy_hash
            valid = hmac.compare_digest(password_hash(data.password, encoded.split(":")[0]), encoded)
            if not user or not valid or not user["enabled"]:
                event(conn, "login_denied", data.username[:64], "Nesėkmingas prisijungimas")
            else:
                token = secrets.token_urlsafe(32)
                conn.execute("DELETE FROM sessions WHERE expires<=?", (now,))
                conn.execute("INSERT INTO sessions VALUES(?,?,?)", (hashlib.sha256(token.encode()).hexdigest(), user["id"], now + SESSION_SECONDS))
                event(conn, "login", user["username"], "Prisijungta prie WEB sąsajos")
        if not user or not valid or not user["enabled"]:
            raise HTTPException(401, "Neteisingi prisijungimo duomenys")
        response.set_cookie("lighting_session", token, httponly=True, samesite="strict",
                            secure=os.environ.get("LIGHTING_COOKIE_SECURE", "0") == "1", max_age=SESSION_SECONDS)
        return {k: user[k] for k in ("id", "username", "display_name", "role")}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response, user=Depends(current_user)):
        token_hash = hashlib.sha256(request.cookies.get("lighting_session", "").encode()).hexdigest()
        with db() as conn:
            conn.execute("DELETE FROM sessions WHERE token_hash=?", (token_hash,))
        response.delete_cookie("lighting_session")
        return {"ok": True}

    @app.get("/api/auth/me")
    def me(user=Depends(current_user)):
        return user

    @app.get("/api/health")
    def health():
        return {"service": "sviesa-lighting", "version": "2.0.0", "ok": True}

    @app.get("/api/lighting")
    def lighting(user=Depends(current_user)):
        with db() as conn:
            return state(conn)

    @app.put("/api/lighting")
    def command(data: Command, user=Depends(current_user)):
        with db() as conn:
            conn.execute("UPDATE lighting SET mode=?,brightness=?,last_activity=NULL WHERE id=1", (data.mode, data.brightness))
            event(conn, "lighting_command", user["username"], f"Režimas: {data.mode}; ryškumas: {data.brightness}%")
            return state(conn)

    @app.get("/api/settings")
    def get_settings(user=Depends(admin)):
        with db() as conn:
            return dict(conn.execute("SELECT * FROM settings WHERE id=1").fetchone())

    @app.put("/api/settings")
    def put_settings(data: Settings, user=Depends(admin)):
        with db() as conn:
            state(conn)  # Expire the previous lease before increasing a timeout.
            conn.execute("UPDATE settings SET dim_after_seconds=?,off_after_seconds=?,dim_brightness=? WHERE id=1", (data.dim_after_seconds, data.off_after_seconds, data.dim_brightness))
            event(conn, "settings", user["username"], f"Pritemdyti po {data.dim_after_seconds} s, išjungti po {data.off_after_seconds} s")
        return data

    @app.get("/api/users")
    def users(user=Depends(admin)):
        with db() as conn:
            return [dict(r) for r in conn.execute("SELECT id,username,display_name,role,enabled FROM users ORDER BY id")]

    @app.post("/api/users", status_code=201)
    def add_user(data: NewUser, user=Depends(admin)):
        try:
            with db() as conn:
                cursor = conn.execute("INSERT INTO users(username,display_name,password_hash,role) VALUES(?,?,?,?)", (data.username, data.display_name, password_hash(data.password), data.role))
                event(conn, "user_created", user["username"], f"Sukurtas vartotojas {data.username}")
                return {"id": cursor.lastrowid, "username": data.username, "role": data.role}
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Toks vartotojo vardas jau yra")

    @app.patch("/api/users/{user_id}")
    def update_user(user_id: int, data: Enabled, user=Depends(admin)):
        with db() as conn:
            target = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
            if not target:
                raise HTTPException(404, "Vartotojas nerastas")
            if user_id == user["id"] and not data.enabled:
                raise HTTPException(400, "Negalite užblokuoti savo paskyros")
            conn.execute("UPDATE users SET enabled=? WHERE id=?", (data.enabled, user_id))
            if not data.enabled:
                conn.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
                conn.execute("UPDATE lighting SET last_activity=NULL WHERE last_card IN (SELECT card_id FROM cards WHERE user_id=?)", (user_id,))
            event(conn, "user_updated", user["username"], f"{target['username']}: aktyvus={data.enabled}")
        return {"ok": True}

    @app.get("/api/cards")
    def cards(user=Depends(admin)):
        with db() as conn:
            return [dict(r) for r in conn.execute("SELECT c.*,u.display_name AS owner FROM cards c JOIN users u ON u.id=c.user_id ORDER BY c.created_at DESC")]

    @app.post("/api/cards", status_code=201)
    def add_card(data: NewCard, user=Depends(admin)):
        try:
            with db() as conn:
                if not conn.execute("SELECT 1 FROM users WHERE id=? AND enabled=1", (data.user_id,)).fetchone():
                    raise HTTPException(400, "Pasirinkite aktyvų vartotoją")
                conn.execute("INSERT INTO cards VALUES(?,?,?,?,?)", (data.card_id, data.label, data.user_id, 1, time.time()))
                event(conn, "card_created", user["username"], f"Užregistruota kortelė {data.card_id}")
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Kortelė jau užregistruota")
        return data

    @app.patch("/api/cards/{card_id}")
    def update_card(card_id: str, data: Enabled, user=Depends(admin)):
        with db() as conn:
            if not conn.execute("UPDATE cards SET enabled=? WHERE card_id=?", (data.enabled, card_id)).rowcount:
                raise HTTPException(404, "Kortelė nerasta")
            if not data.enabled:
                conn.execute("UPDATE lighting SET last_activity=NULL WHERE last_card=?", (card_id,))
            event(conn, "card_updated", user["username"], f"Kortelė {card_id}: aktyvi={data.enabled}")
        return {"ok": True}

    @app.delete("/api/cards/{card_id}")
    def delete_card(card_id: str, user=Depends(admin)):
        with db() as conn:
            if not conn.execute("DELETE FROM cards WHERE card_id=?", (card_id,)).rowcount:
                raise HTTPException(404, "Kortelė nerasta")
            conn.execute("UPDATE lighting SET last_activity=NULL WHERE last_card=?", (card_id,))
            event(conn, "card_deleted", user["username"], f"Pašalinta kortelė {card_id}")
        return {"ok": True}

    @app.get("/api/events")
    def events(limit: int = 50, before_id: int | None = None, kind: str | None = None, user=Depends(admin)):
        if not 1 <= limit <= 200:
            raise HTTPException(422, "Leidžiama nuo 1 iki 200 įvykių")
        clauses, args = [], []
        if before_id is not None:
            clauses.append("id < ?")
            args.append(before_id)
        if kind:
            clauses.append("kind = ?")
            args.append(kind)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with db() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM events" + where + " ORDER BY id DESC LIMIT ?", (*args, limit))]

    @app.post("/api/nfc/authorize", dependencies=[Depends(device)])
    def authorize_card(data: CardInput):
        with db() as conn:
            card = conn.execute("SELECT c.*,u.username FROM cards c JOIN users u ON u.id=c.user_id WHERE c.card_id=? AND c.enabled=1 AND u.enabled=1", (data.card_id,)).fetchone()
            if card:
                conn.execute("UPDATE lighting SET mode='auto',last_activity=?,last_card=? WHERE id=1", (time.time(), data.card_id))
            event(conn, "nfc_granted" if card else "nfc_denied", card["username"] if card else "Nežinoma kortelė", f"NFC {data.card_id}: {'prieiga suteikta' if card else 'prieiga atmesta'}")
            return {"card_id": data.card_id, "authorized": card is not None,
                    "message": "Access granted" if card else "Access denied", **device_state(conn)}

    @app.get("/api/device/state", dependencies=[Depends(device)])
    def get_device_state():
        with db() as conn:
            return device_state(conn)

    @app.post("/api/device/telemetry", dependencies=[Depends(device)])
    def telemetry(data: Telemetry):
        with db() as conn:
            old = conn.execute("SELECT * FROM lighting WHERE id=1").fetchone()
            current = state(conn)
            actor = "Simuliatorius" if data.source == "simulator" else "Arduino"
            if current["device_source"] != data.source:
                event(conn, "system", actor, "Pakeistas telemetrijos šaltinis")
            conn.execute("UPDATE device_info SET source=? WHERE id=1", (data.source,))
            if data.motion and current["mode"] == "auto" and current["desired_brightness"] > 0:
                conn.execute("UPDATE lighting SET last_activity=? WHERE id=1", (time.time(),))
            if data.motion and not old["motion"]:
                event(conn, "motion", actor, "Aptiktas judesys")
            if old["actual_brightness"] != data.actual_brightness:
                event(conn, "lighting_actual", actor, f"Praneštas išėjimo ryškumas: {data.actual_brightness}%")
            conn.execute("UPDATE lighting SET last_seen=?,motion=?,actual_brightness=? WHERE id=1", (time.time(), data.motion, data.actual_brightness))
            return device_state(conn)

    app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")

    @app.get("/", include_in_schema=False)
    def home():
        return FileResponse(ROOT / "frontend" / "index.html")

    return app


app = create_app()
