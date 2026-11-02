import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from urllib.request import urlopen

from tools.device_simulator import VirtualController


def command(mode="auto", desired=80, remaining=30):
    return {"mode":mode,"brightness":80,"desired_brightness":desired,"remaining_seconds":remaining,
            "dim_after_seconds":10,"off_after_seconds":30,"dim_brightness":20}


def test_local_timer_survives_connection_loss():
    device = VirtualController()
    device.apply(command(), 100)
    device.tick(111)
    assert device.actual_brightness == 20
    device.tick(131)
    assert device.actual_brightness == 0
    device.motion = True
    device.tick(132)
    assert device.actual_brightness == 0  # PIR cannot authorize a new session.


def test_local_motion_extends_active_timer():
    device = VirtualController()
    device.apply(command(), 100)
    device.motion = True
    device.tick(109)
    device.motion = False
    device.tick(115)
    assert device.actual_brightness == 80
    device.tick(120)
    assert device.actual_brightness == 20
    device.tick(140)
    assert device.actual_brightness == 0


def test_manual_on_failsafe_and_off_override():
    device = VirtualController()
    device.apply(command("on", remaining=None), 100)
    device.tick(129)
    assert device.actual_brightness == 80
    device.tick(131)
    assert device.actual_brightness == 0
    device.apply(command("off", desired=0, remaining=None), 132)
    device.motion = True
    device.tick(133)
    assert device.actual_brightness == 0


def test_sync_preserves_remaining_time_instead_of_restarting_it():
    device = VirtualController()
    device.apply(command(remaining=5, desired=20), 100)
    device.tick(106)
    assert device.actual_brightness == 0


def test_real_http_simulator_roundtrip(tmp_path):
    """Run both actual processes; do not replace transport with a mock."""
    root = Path(__file__).resolve().parents[1]
    with socket.socket() as sock:
        sock.bind(("127.0.0.1",0))
        port = sock.getsockname()[1]
    url = f"http://127.0.0.1:{port}"
    key = "sim-test-device-key-" + "c"*32
    env = {**os.environ,"LIGHTING_DATA_DIR":str(tmp_path),"LIGHTING_ADMIN_PASSWORD":"Simulator-test-password-2026",
           "LIGHTING_DEVICE_KEY":key,"PYTHONIOENCODING":"utf-8"}
    server = subprocess.Popen([sys.executable,"-m","uvicorn","backend.main:app","--port",str(port)],
                              cwd=root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            try:
                with urlopen(url,timeout=1) as response:
                    if response.status == 200: break
            except OSError:
                time.sleep(.1)
        else:
            raise AssertionError("Test server did not start")
        simulator = subprocess.run([sys.executable,"tools/device_simulator.py","--url",url,"--demo","--duration","3"],
                                   input="card\nmotion on\nstatus\n",cwd=root,env=env,text=True,
                                   encoding="utf-8",capture_output=True,timeout=20)
        assert simulator.returncode == 0, simulator.stderr
        assert "prieiga suteikta" in simulator.stdout
        assert "SIMULIUOJAMAS LED: 100%" in simulator.stdout
        from urllib.request import Request
        with urlopen(Request(url+"/api/device/state", headers={"X-Device-Key":key})) as response:
            assert json.load(response)["desired_brightness"] == 100
        import sqlite3
        with sqlite3.connect(tmp_path / "lighting.sqlite3") as conn:
            assert conn.execute("SELECT source FROM device_info").fetchone()[0] == "simulator"
            assert conn.execute("SELECT actual_brightness FROM lighting").fetchone()[0] == 100
    finally:
        server.terminate()
        server.wait(timeout=10)
