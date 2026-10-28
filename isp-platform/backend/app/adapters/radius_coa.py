"""RFC 5176 Disconnect-Request / CoA-Request sender (MikroTik: /radius incoming set accept=yes)."""
import hashlib
import ipaddress
import os
import socket
import struct

DISCONNECT_REQUEST, DISCONNECT_ACK, DISCONNECT_NAK = 40, 41, 42
COA_REQUEST, COA_ACK, COA_NAK = 43, 44, 45
USER_NAME, FRAMED_IP, ACCT_SESSION_ID, VENDOR_SPECIFIC = 1, 8, 44, 26
MIKROTIK_VENDOR, MIKROTIK_RATE_LIMIT = 14988, 8


def _attr(code: int, value: bytes) -> bytes:
    if len(value) > 253:
        raise ValueError("attribute too long")
    return struct.pack("!BB", code, len(value) + 2) + value


def _vsa(vendor: int, code: int, value: bytes) -> bytes:
    inner = struct.pack("!BB", code, len(value) + 2) + value
    return _attr(VENDOR_SPECIFIC, struct.pack("!I", vendor) + inner)


def build_packet(code: int, identifier: int, secret: bytes, *, username=None, session_id=None,
                 framed_ip=None, rate_limit=None) -> bytes:
    attrs = b""
    if username:
        attrs += _attr(USER_NAME, username.encode())
    if session_id:
        attrs += _attr(ACCT_SESSION_ID, session_id.encode())
    if framed_ip:
        attrs += _attr(FRAMED_IP, ipaddress.IPv4Address(framed_ip).packed)
    if rate_limit:
        attrs += _vsa(MIKROTIK_VENDOR, MIKROTIK_RATE_LIMIT, rate_limit.encode())
    length = 20 + len(attrs)
    header = struct.pack("!BBH", code, identifier, length)
    # Request Authenticator = MD5(Code+Identifier+Length+16 zero octets+Attributes+Secret)
    auth = hashlib.md5(header + b"\x00" * 16 + attrs + secret).digest()
    return header + auth + attrs


def verify_reply(reply: bytes, request: bytes, secret: bytes) -> bool:
    if len(reply) < 20 or reply[1] != request[1]:
        return False
    expected = hashlib.md5(reply[:4] + request[4:20] + reply[20:] + secret).digest()
    return expected == reply[4:20]


def send(nas_ip: str, secret: str, code=DISCONNECT_REQUEST, port=3799, timeout=3.0, **attrs) -> str:
    """Returns 'ack', 'nak' or 'timeout'."""
    identifier = os.urandom(1)[0]
    packet = build_packet(code, identifier, secret.encode(), **attrs)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.settimeout(timeout)
        for _ in range(2):
            sock.sendto(packet, (nas_ip, port))
            try:
                reply, _ = sock.recvfrom(4096)
            except socket.timeout:
                continue
            if not verify_reply(reply, packet, secret.encode()):
                continue
            return "ack" if reply[0] in (DISCONNECT_ACK, COA_ACK) else "nak"
    return "timeout"
