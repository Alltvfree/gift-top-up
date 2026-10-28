"""SSH host-key pinning shared by the OLT adapter. Unknown keys are refused, never auto-trusted."""
import base64
import hashlib

import paramiko


class HostKeyMismatch(Exception):
    pass


def fingerprint(key: paramiko.PKey) -> str:
    return "SHA256:" + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")


class PinnedKeyPolicy(paramiko.MissingHostKeyPolicy):
    def __init__(self, expected: str | None):
        self.expected = (expected or "").strip()

    def missing_host_key(self, client, hostname, key):
        fp = fingerprint(key)
        if not self.expected:
            raise HostKeyMismatch(f"No pinned host key for {hostname}. Verify on the console, then pin: {fp}")
        if fp != self.expected:
            raise HostKeyMismatch(f"HOST KEY CHANGED for {hostname}: got {fp}, pinned {self.expected}")
