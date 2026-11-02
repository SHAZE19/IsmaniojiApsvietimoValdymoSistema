"""Independent Arduino simulator using the same authenticated HTTP API as the UNO.

No third-party packages. Run from the project root with --help for options.
This process represents the single physical controller: stop it before using UNO.
"""
from dataclasses import dataclass
from pathlib import Path
from queue import Empty, Queue
from threading import Thread
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPCookieProcessor
import argparse
import json
import os
import time

ROOT = Path(__file__).resolve().parents[1]
DEMO_UID = "D3A01234"


@dataclass
class VirtualController:
    mode: str = "auto"
    brightness: int = 100
    dim_brightness: int = 25
    dim_after: int = 60
    off_after: int = 120
    actual_brightness: int = 0
    motion: bool = False
    last_activity: float | None = None
    last_sync: float | None = None

    def apply(self, data: dict, now: float):
        self.mode = data["mode"]
        self.brightness = data["brightness"]
        self.dim_brightness = data["dim_brightness"]
        self.dim_after = data["dim_after_seconds"]
        self.off_after = data["off_after_seconds"]
        self.actual_brightness = data["desired_brightness"]
        remaining = data.get("remaining_seconds") or 0
        self.last_activity = now - (self.off_after - remaining) if self.mode == "auto" and self.actual_brightness else None
        self.last_sync = now

    def tick(self, now: float):
        if self.mode == "off":
            self.actual_brightness = 0
        elif self.mode == "on":
            self.actual_brightness = self.brightness if self.last_sync is not None and now - self.last_sync < self.off_after else 0
        elif self.last_activity is not None:
            if self.motion:
                self.last_activity = now
            elapsed = now - self.last_activity
            if elapsed >= self.off_after:
                self.actual_brightness, self.last_activity = 0, None
            else:
                self.actual_brightness = min(self.brightness, self.dim_brightness) if elapsed >= self.dim_after else self.brightness
        else:
            self.actual_brightness = 0


class Server:
    def __init__(self, url: str, key: str):
        self.url, self.key = url.rstrip("/"), key
        self.opener = build_opener(HTTPCookieProcessor())

    def request(self, path: str, data=None, *, browser=False, method=None):
        headers = {"Content-Type": "application/json"}
        headers["X-Requested-With" if browser else "X-Device-Key"] = "LightingApp" if browser else self.key
        req = Request(self.url + path, data=json.dumps(data).encode() if data is not None else None,
                      headers=headers, method=method)
        with self.opener.open(req, timeout=3) as response:
            return json.load(response)

    def prepare_demo(self, credentials_file: Path):
        password = os.environ.get("LIGHTING_ADMIN_PASSWORD")
        if not password:
            text = credentials_file.read_text(encoding="utf-8")
            password = next(line.split(": ", 1)[1] for line in text.splitlines() if line.startswith("Slaptažodis: "))
        admin = self.request("/api/auth/login", {"username": "admin", "password": password}, browser=True)
        try:
            cards = self.request("/api/cards", browser=True)
            existing = next((c for c in cards if c["card_id"] == DEMO_UID), None)
            if existing:
                print(f"Demo UID {DEMO_UID} jau yra. Korteles ir savininko aktyvuma patikrinkite WEB.", flush=True)
            else:
                self.request("/api/cards", {"card_id": DEMO_UID, "label": "Demonstracinė kortelė", "user_id": admin["id"]}, browser=True)
                print(f"Prideta demonstracine kortele {DEMO_UID} (administratorius).", flush=True)
        finally:
            self.request("/api/auth/logout", {}, browser=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8001")
    parser.add_argument("--data-dir", type=Path, default=Path(os.environ.get("LIGHTING_DATA_DIR", ROOT / "backend" / "data")))
    parser.add_argument("--demo", action="store_true", help="Prideti demonstracine kortele D3A01234, jei jos nera")
    parser.add_argument("--card", default=DEMO_UID, help="UID komandai 'card'")
    parser.add_argument("--duration", type=float, default=0, help="Baigti po tiek sekundziu (0 = iki quit)")
    args = parser.parse_args()
    try:
        key = os.environ.get("LIGHTING_DEVICE_KEY") or (args.data_dir / "device-secret.txt").read_text(encoding="utf-8").strip()
        server = Server(args.url, key)
        if args.demo:
            server.prepare_demo(args.data_dir / "initial-credentials.txt")
        controller = VirtualController()
        controller.apply(server.request("/api/device/state"), time.monotonic())
    except (OSError, ValueError, StopIteration) as error:
        parser.exit(1, f"Nepavyko prisijungti. Paleiskite serveri ir patikrinkite duomenu aplanka. {error}\n")

    print("SIMULIATORIUS (be fizines irangos). Komandos, po kiekvienos Enter:", flush=True)
    print(f"card [UID]  |  motion on  |  motion off  |  disconnect  |  connect  |  status  |  quit\nNumatyta kortele: {args.card}", flush=True)
    commands: Queue[str] = Queue()

    def read_commands():
        while True:
            try:
                commands.put(input().strip())
            except EOFError:
                return

    Thread(target=read_commands, daemon=True).start()
    connected, pending_motion = True, False
    start = time.monotonic()
    next_sync, last_output, last_error = 0.0, None, ""
    try:
        while not args.duration or time.monotonic() - start < args.duration:
            now = time.monotonic()
            try:
                command = commands.get_nowait().split()
            except Empty:
                command = []
            if command:
                action = command[0].lower()
                if action in {"quit", "q", "exit"}:
                    break
                elif action == "motion" and len(command) == 2 and command[1] in {"on", "off"}:
                    controller.motion = command[1] == "on"
                    print("PIR:", "judesys" if controller.motion else "judesio nera", flush=True)
                elif action in {"disconnect", "connect"}:
                    connected = action == "connect"
                    next_sync = 0
                    print("Rysys:", "ijungtas" if connected else "atjungtas", flush=True)
                elif action == "card":
                    if not connected:
                        print("Be serverio nauja prieiga nesuteikiama.", flush=True)
                    else:
                        try:
                            result = server.request("/api/nfc/authorize", {"card_id": command[1] if len(command)>1 else args.card})
                            controller.apply(result, time.monotonic())
                            print("NFC:", "prieiga suteikta" if result["authorized"] else "prieiga atmesta", flush=True)
                        except (HTTPError, URLError, TimeoutError, OSError) as error:
                            print("NFC uzklausa nepavyko:", error, flush=True)
                elif action == "status":
                    print(f"Rezimas={controller.mode}, PWM={controller.actual_brightness}%, PIR={controller.motion}, rysys={connected}", flush=True)
                else:
                    print("Nezinoma komanda. Naudokite card, motion on/off, disconnect, connect, status arba quit.", flush=True)
            controller.tick(time.monotonic())
            pending_motion = pending_motion or controller.motion
            if connected and now >= next_sync:
                next_sync = now + 2
                try:
                    data = server.request("/api/device/telemetry", {"motion": pending_motion,
                        "actual_brightness": controller.actual_brightness, "source": "simulator"})
                    controller.apply(data, time.monotonic())
                    pending_motion, last_error = False, ""
                except (HTTPError, URLError, TimeoutError, OSError) as error:
                    if str(error) != last_error:
                        print("Rysio klaida:", error, flush=True)
                        last_error = str(error)
            if controller.actual_brightness != last_output:
                last_output = controller.actual_brightness
                print(f"SIMULIUOJAMAS LED: {last_output}%", flush=True)
            time.sleep(0.05)
    except KeyboardInterrupt:
        pass
    print("Simuliatorius sustabdytas. WEB rysys po 15 s bus rodomas neprisijunges.", flush=True)


if __name__ == "__main__":
    main()
