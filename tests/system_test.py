"""End-to-end system test.

Starts the REAL broker and REAL subscriber processes (on free ports), drives
them through the REST API and verifies delivery by reading each subscriber's
terminal output - exactly what you would check by eye during the demo.

Run from the project root (with the virtual environment active):
    python tests/system_test.py
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
PASSED = 0
FAILED = 0


def check(condition: bool, label: str) -> None:
    global PASSED, FAILED
    if condition:
        PASSED += 1
        print(f"  [PASS] {label}")
    else:
        FAILED += 1
        print(f"  [FAIL] {label}")


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Proc:
    """A child process whose stdout/stderr are written to a log file."""

    def __init__(self, name: str, cmd: list, log_dir: Path, env=None) -> None:
        self.name = name
        self.log_path = log_dir / f"{name}.log"
        self._log = open(self.log_path, "w")
        self.p = subprocess.Popen(
            cmd, cwd=ROOT, stdout=self._log, stderr=subprocess.STDOUT,
            env={**os.environ, **(env or {})},
        )

    def log(self) -> str:
        return self.log_path.read_text()

    def got(self, message: str) -> bool:
        return f"Message: {message}" in self.log()

    def stop(self) -> None:
        if self.p.poll() is None:
            self.p.terminate()
            try:
                self.p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.p.kill()
        self._log.close()


def wait_ready(url: str, timeout: float = 15.0) -> None:
    end = time.time() + timeout
    while time.time() < end:
        try:
            if httpx.get(url, timeout=1.0).status_code == 200:
                return
        except httpx.HTTPError:
            time.sleep(0.2)
    raise RuntimeError(f"Service did not start: {url}")


def main() -> int:
    log_dir = Path(tempfile.mkdtemp(prefix="pubsub-test-"))
    broker_port = free_port()
    ports = {"A": free_port(), "B": free_port(), "C": free_port(), "D": free_port()}
    base = f"http://127.0.0.1:{broker_port}"
    procs: list = []

    def start_sub(letter: str, delay: float = 0.0) -> Proc:
        cmd = [sys.executable, "-m", "subscribers.subscriber",
               "--id", f"student_{letter}", "--port", str(ports[letter])]
        if delay:
            cmd += ["--delay", str(delay)]
        proc = Proc(f"sub_{letter}", cmd, log_dir)
        procs.append(proc)
        wait_ready(f"http://127.0.0.1:{ports[letter]}/health")
        return proc

    def url(letter: str) -> str:
        return f"http://127.0.0.1:{ports[letter]}/notify"

    def publish(**body) -> httpx.Response:
        return httpx.post(f"{base}/publish", json=body, timeout=20)

    try:
        print(f"Logs: {log_dir}\n")
        broker = Proc(
            "broker",
            [sys.executable, "-m", "uvicorn", "broker.main:app",
             "--host", "127.0.0.1", "--port", str(broker_port)],
            log_dir, env={"PUBSUB_CALLBACK_TIMEOUT": "2"},
        )
        procs.append(broker)
        wait_ready(f"{base}/")
        sub = {letter: start_sub(letter) for letter in "ABC"}

        print("1. Registration")
        for letter in "ABC":
            r = httpx.post(f"{base}/subscribe",
                           json={"subscriber_id": f"student_{letter}", "callback_url": url(letter)})
            check(r.status_code == 201, f"register student_{letter} -> 201")
        r = httpx.post(f"{base}/subscribe",
                       json={"subscriber_id": "student_A", "callback_url": url("A")})
        check(r.status_code == 409, "duplicate registration -> 409")
        r = httpx.post(f"{base}/subscribe", json={"subscriber_id": "x", "callback_url": "not-a-url"})
        check(r.status_code == 422, "invalid callback URL -> 422")
        r = httpx.post(f"{base}/subscribe", json={"subscriber_id": "x"})
        check(r.status_code == 422, "missing field -> 422")

        print("2. Registry listing")
        data = httpx.get(f"{base}/subscribers").json()
        check(data["total"] == 3, "3 subscribers listed")
        check({s["subscriber_id"] for s in data["subscribers"]} ==
              {"student_A", "student_B", "student_C"}, "IDs match")

        print("3. Request validation")
        r = publish(event_type="e", message="m", mode="anycast")
        check(r.status_code == 422, "invalid mode -> 422")
        r = publish(event_type="e", mode="broadcast")
        check(r.status_code == 422, "missing message -> 422")
        r = publish(event_type="e", message="m", mode="unicast", recipients=["student_A", "student_B"])
        check(r.status_code == 400, "unicast with 2 recipients -> 400")
        r = publish(event_type="e", message="m", mode="unicast")
        check(r.status_code == 400, "unicast without recipients -> 400")
        r = publish(event_type="e", message="m", mode="unicast", recipients=["ghost"])
        check(r.status_code == 404, "unicast to unknown subscriber -> 404")
        r = publish(event_type="e", message="m", mode="multicast", recipients=["ghost"])
        check(r.status_code == 404, "multicast with only unknown IDs -> 404")
        r = publish(event_type="e", message="m", mode="multicast")
        check(r.status_code == 400, "multicast without recipients -> 400")

        print("4. Unicast (only A)")
        r = publish(event_type="fee_reminder", message="uni-1", mode="unicast", recipients=["student_A"])
        body = r.json()
        check(r.status_code == 200 and body["successful_deliveries"] == 1, "broker reports 1 success")
        check(sub["A"].got("uni-1"), "A received it")
        check(not sub["B"].got("uni-1") and not sub["C"].got("uni-1"), "B and C did NOT receive it")

        print("5. Multicast (A and C, plus an unknown ID)")
        r = publish(event_type="hackathon_update", message="multi-1", mode="multicast",
                    recipients=["student_A", "student_C", "ghost"])
        body = r.json()
        check(r.status_code == 200 and body["total_recipients"] == 2, "2 recipients delivered")
        check(body["invalid_recipients"] == ["ghost"], "unknown ID reported clearly")
        check(sub["A"].got("multi-1") and sub["C"].got("multi-1"), "A and C received it")
        check(not sub["B"].got("multi-1"), "B did NOT receive it")

        print("6. Broadcast (A, B, C)")
        r = publish(event_type="general_announcement", message="bcast-1", mode="broadcast")
        body = r.json()
        check(body["total_recipients"] == 3 and body["successful_deliveries"] == 3, "3/3 delivered")
        check(all(sub[l].got("bcast-1") for l in "ABC"), "A, B and C all received it")

        print("7. Offline subscriber (B stopped)")
        sub["B"].stop()
        time.sleep(0.5)
        r = publish(event_type="general_announcement", message="bcast-2", mode="broadcast")
        body = r.json()
        by_id = {x["subscriber_id"]: x for x in body["results"]}
        check(body["successful_deliveries"] == 2 and body["failed_deliveries"] == 1, "2 success, 1 failed")
        check(by_id["student_B"]["status"] == "failed" and "error" in by_id["student_B"],
              "B reported as failed with an error message")
        check(sub["A"].got("bcast-2") and sub["C"].got("bcast-2"), "A and C still notified")

        print("8. Unregister C")
        r = httpx.delete(f"{base}/unsubscribe/student_C")
        check(r.status_code == 200, "unsubscribe C -> 200")
        r = httpx.delete(f"{base}/unsubscribe/student_C")
        check(r.status_code == 404, "unsubscribe unknown -> 404")
        r = publish(event_type="general_announcement", message="bcast-3", mode="broadcast")
        check(sub["A"].got("bcast-3"), "A received broadcast")
        check(not sub["C"].got("bcast-3"), "C (unregistered) did NOT receive broadcast")
        check(r.json()["total_recipients"] == 2, "broadcast targeted 2 remaining subscribers")

        print("9. Timeout (slow subscriber D, broker timeout 2s)")
        start_sub("D", delay=10)
        httpx.post(f"{base}/subscribe", json={"subscriber_id": "student_D", "callback_url": url("D")})
        t0 = time.time()
        r = publish(event_type="slow", message="slow-1", mode="multicast", recipients=["student_A", "student_D"])
        elapsed = time.time() - t0
        by_id = {x["subscriber_id"]: x for x in r.json()["results"]}
        check(by_id["student_D"]["status"] == "failed" and "Timeout" in by_id["student_D"]["error"],
              "slow subscriber reported as timeout")
        check(by_id["student_A"]["status"] == "success", "A still delivered")
        check(elapsed < 6, f"broker did not wait indefinitely ({elapsed:.1f}s)")

        print("10. Broadcast with nobody registered")
        for sid in ("student_A", "student_B", "student_D"):
            httpx.delete(f"{base}/unsubscribe/{sid}")
        r = publish(event_type="e", message="nobody", mode="broadcast")
        check(r.status_code == 200 and r.json()["total_recipients"] == 0, "empty broadcast handled gracefully")

    finally:
        for proc in procs:
            proc.stop()

    print(f"\nResult: {PASSED} passed, {FAILED} failed")
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
