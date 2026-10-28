import re
import subprocess


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
