import re
import socket
import subprocess
import time


def ping(host: str, count: int = 3, timeout_s: int = 1) -> dict:
    """ICMP reachability using the system ping (container has CAP_NET_RAW by default)."""
    try:
        out = subprocess.run(
            ["ping", "-n", "-q", "-c", str(count), "-W", str(timeout_s), host],
            capture_output=True, text=True, timeout=count * timeout_s + 5,
        ).stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return {"reachable": False, "latency_ms": None, "packet_loss_pct": 100.0}
    return parse_ping(out)


def parse_ping(out: str) -> dict:
    loss = re.search(r"([\d.]+)% packet loss", out)
    rtt = re.search(r"= [\d.]+/([\d.]+)/", out)
    loss_pct = float(loss.group(1)) if loss else 100.0
    return {
        "reachable": loss_pct < 100.0,
        "latency_ms": float(rtt.group(1)) if rtt else None,
        "packet_loss_pct": loss_pct,
    }


def tcp_ping(host: str, port: int, count: int = 3, timeout_s: float = 2.0) -> dict:
    """Reachability by TCP connect, for devices reached through a router's port forward (no ICMP path)."""
    times = []
    for _ in range(count):
        t = time.monotonic()
        try:
            socket.create_connection((host, port), timeout=timeout_s).close()
            times.append((time.monotonic() - t) * 1000)
        except OSError:
            pass
    return {"reachable": bool(times), "latency_ms": round(sum(times) / len(times), 2) if times else None,
            "packet_loss_pct": round(100.0 * (count - len(times)) / count, 1)}
