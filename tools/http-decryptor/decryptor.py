#!/usr/bin/env python3
"""Decrypt encrypted HTTP response bodies of YOUR OWN app, for testing.

Works with captures from HTTP Toolkit (File -> Export -> HAR), or a body you paste in.
Runs only on your computer: the web UI listens on 127.0.0.1 and keys never leave it.

  pip install cryptography
  python decryptor.py serve                       # web UI at http://127.0.0.1:8899
  python decryptor.py decrypt --har cap.har --list
  python decryptor.py decrypt --har cap.har --entry 3 --algo aes-cbc --key 'my32bytekey...' --iv-mode prefix
  python decryptor.py decrypt --body 'U2FsdGVk...' --algo aes-gcm --key-enc hex --key 00ff... --iv-mode prefix
"""
import argparse
import base64
import binascii
import hashlib
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

ALGOS = ["aes-cbc", "aes-ecb", "aes-ctr", "aes-gcm", "chacha20-poly1305"]


class DecryptError(Exception):
    pass


def decode(text: str, enc: str) -> bytes:
    """Bytes from text: base64 / base64url / hex / utf8 (raw)."""
    text = text.strip()
    try:
        if enc == "base64":
            return base64.b64decode(text + "=" * (-len(text) % 4), altchars=b"-_" if ("-" in text or "_" in text) else None)
        if enc == "hex":
            return binascii.unhexlify(text.replace(" ", "").replace(":", ""))
        if enc == "utf8":
            return text.encode()
    except (binascii.Error, ValueError) as exc:
        raise DecryptError(f"Not valid {enc}: {exc}") from None
    raise DecryptError(f"Unknown encoding {enc}")


def make_key(value: str, enc: str) -> bytes:
    if enc == "sha256":  # key = SHA-256(passphrase), a common app pattern
        return hashlib.sha256(value.encode()).digest()
    if enc == "md5":
        return hashlib.md5(value.encode()).digest()
    return decode(value, enc)


def decrypt_bytes(data: bytes, algo: str, key: bytes, iv: bytes | None = None, iv_mode: str = "prefix",
                  tag_mode: str = "suffix", aad: bytes | None = None, pad: bool = True) -> bytes:
    if algo not in ALGOS:
        raise DecryptError(f"Unknown algorithm {algo}")
    if algo.startswith("aes") and len(key) not in (16, 24, 32):
        raise DecryptError(f"AES key must be 16, 24 or 32 bytes, got {len(key)}")
    if algo == "chacha20-poly1305" and len(key) != 32:
        raise DecryptError(f"ChaCha20 key must be 32 bytes, got {len(key)}")
    iv_len = {"aes-cbc": 16, "aes-ctr": 16, "aes-gcm": 12, "chacha20-poly1305": 12, "aes-ecb": 0}[algo]
    if iv_len:
        if iv_mode == "prefix":
            if len(data) <= iv_len:
                raise DecryptError("Body is shorter than the IV")
            iv, data = data[:iv_len], data[iv_len:]
        elif iv_mode == "key":
            iv = key[:iv_len]  # some apps reuse the key (or its start) as IV
        elif iv_mode == "zero":
            iv = bytes(iv_len)
        elif iv is None or len(iv) != iv_len:
            raise DecryptError(f"IV must be {iv_len} bytes (give it, or use iv-mode prefix)")
    try:
        if algo in ("aes-gcm", "chacha20-poly1305"):
            cls = AESGCM if algo == "aes-gcm" else ChaCha20Poly1305
            if tag_mode == "prefix":  # tag first: rearrange to ciphertext||tag
                data = data[16:] + data[:16]
            return cls(key).decrypt(iv, data, aad)
        mode = {"aes-cbc": modes.CBC(iv) if iv_len else None, "aes-ctr": modes.CTR(iv) if iv_len else None,
                "aes-ecb": modes.ECB()}[algo]
        dec = Cipher(algorithms.AES(key), mode).decryptor()
        if algo in ("aes-cbc", "aes-ecb") and len(data) % 16:
            raise DecryptError(f"Ciphertext length {len(data)} is not a multiple of 16: wrong encoding, or an IV/tag still attached")
        out = dec.update(data) + dec.finalize()
        if algo in ("aes-cbc", "aes-ecb") and pad:
            un = padding.PKCS7(128).unpadder()
            try:
                out = un.update(out) + un.finalize()
            except ValueError:
                raise DecryptError("Bad padding: wrong key or IV (or the data is not PKCS7-padded: try pad=off)") from None
        return out
    except DecryptError:
        raise
    except Exception as exc:  # InvalidTag etc.
        raise DecryptError(f"Decryption failed ({type(exc).__name__}): wrong key/IV/tag, or wrong layout") from None


def pick_field(body: str, path: str) -> str:
    """Encrypted text may sit inside JSON, e.g. {"data":"..."}: path like data or result.payload."""
    if not path:
        return body
    try:
        node = json.loads(body)
    except ValueError:
        raise DecryptError("Body is not JSON, so the field path cannot be used") from None
    for part in path.split("."):
        try:
            node = node[int(part)] if isinstance(node, list) else node[part]
        except (KeyError, IndexError, ValueError):
            raise DecryptError(f"Field '{path}' not found in the JSON body") from None
    return node if isinstance(node, str) else json.dumps(node)


def decrypt_text(body: str, *, algo: str, key: str, key_enc: str = "utf8", body_enc: str = "base64", iv: str = "",
                 iv_enc: str = "base64", iv_mode: str = "prefix", tag_mode: str = "suffix", aad: str = "",
                 field: str = "", pad: bool = True) -> dict:
    cipher = decode(pick_field(body, field.strip()), body_enc)
    plain = decrypt_bytes(cipher, algo, make_key(key, key_enc), decode(iv, iv_enc) if iv.strip() else None, iv_mode,
                          tag_mode, aad.encode() if aad else None, pad)
    text = plain.decode("utf-8", "replace")
    pretty = None
    try:
        pretty = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
    except ValueError:
        pass
    return {"text": pretty or text, "json": pretty is not None, "bytes": len(plain), "hex": plain[:64].hex()}


def load_har(raw: str | bytes) -> list[dict]:
    """Entries of an HTTP Toolkit / browser HAR export: index, method, url, status, response body text."""
    try:
        log = json.loads(raw)["log"]
    except (ValueError, KeyError, TypeError):
        raise DecryptError("Not a HAR file (in HTTP Toolkit: Export -> Export as HAR)") from None
    out = []
    for i, e in enumerate(log.get("entries", [])):
        c = e.get("response", {}).get("content", {})
        text = c.get("text") or ""
        if c.get("encoding") == "base64":
            text = base64.b64decode(text).decode("utf-8", "replace")
        out.append({"index": i, "method": e["request"]["method"], "url": e["request"]["url"], "status": e["response"]["status"],
                    "mime": c.get("mimeType", ""), "size": len(text), "body": text})
    return out


# ---------------------------------------------------------------- web UI
class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype="application/json"):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'unsafe-inline'; script-src 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, Path(__file__).with_name("ui.html").read_text(), "text/html; charset=utf-8")
        self._send(404, '{"error":"not found"}')

    def do_POST(self):
        # Only the page we serve may call this (blocks other websites from reaching localhost).
        if self.headers.get("X-Decryptor") != "1" or self.headers.get("Host", "").split(":")[0] not in ("127.0.0.1", "localhost"):
            return self._send(403, '{"error":"forbidden"}')
        try:
            body = json.loads(self.rfile.read(min(int(self.headers.get("Content-Length", 0)), 50_000_000)))
            if self.path == "/api/har":
                entries = load_har(body["har"])
                return self._send(200, json.dumps([{k: v for k, v in e.items() if k != "body"} | {"body": e["body"][:200000]} for e in entries]))
            if self.path == "/api/decrypt":
                return self._send(200, json.dumps(decrypt_text(**body)))
            self._send(404, '{"error":"not found"}')
        except DecryptError as exc:
            self._send(200, json.dumps({"error": str(exc)}))
        except (TypeError, KeyError, ValueError) as exc:
            self._send(400, json.dumps({"error": f"bad request: {exc}"}))

    def log_message(self, *a):  # keep keys/bodies out of the console
        pass


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve")
    s.add_argument("--port", type=int, default=8899)
    d = sub.add_parser("decrypt")
    d.add_argument("--har")
    d.add_argument("--entry", type=int)
    d.add_argument("--list", action="store_true")
    d.add_argument("--body", help="encrypted body text (or - for stdin)")
    d.add_argument("--algo", choices=ALGOS, default="aes-cbc")
    d.add_argument("--key")
    d.add_argument("--key-enc", choices=["utf8", "hex", "base64", "sha256", "md5"], default="utf8")
    d.add_argument("--body-enc", choices=["base64", "hex", "utf8"], default="base64")
    d.add_argument("--iv", default="")
    d.add_argument("--iv-enc", choices=["base64", "hex", "utf8"], default="base64")
    d.add_argument("--iv-mode", choices=["prefix", "given", "key", "zero"], default="prefix")
    d.add_argument("--tag-mode", choices=["suffix", "prefix"], default="suffix")
    d.add_argument("--aad", default="")
    d.add_argument("--field", default="", help="JSON path of the encrypted text, e.g. data or result.payload")
    d.add_argument("--no-pad", action="store_true")
    a = ap.parse_args()
    if a.cmd == "serve":
        print(f"Open http://127.0.0.1:{a.port}  (Ctrl+C to stop)")
        ThreadingHTTPServer(("127.0.0.1", a.port), Handler).serve_forever()
        return
    try:
        if a.har:
            entries = load_har(Path(a.har).read_text())
            if a.list or a.entry is None:
                for e in entries:
                    print(f'{e["index"]:>4}  {e["status"]}  {e["method"]:<6} {e["size"]:>8}  {e["url"][:100]}')
                return
            body = entries[a.entry]["body"]
        else:
            body = sys.stdin.read() if a.body == "-" else a.body
        if not body or not a.key:
            sys.exit("Need --body (or --har --entry) and --key")
        r = decrypt_text(body, algo=a.algo, key=a.key, key_enc=a.key_enc, body_enc=a.body_enc, iv=a.iv, iv_enc=a.iv_enc,
                         iv_mode=a.iv_mode, tag_mode=a.tag_mode, aad=a.aad, field=a.field, pad=not a.no_pad)
        print(r["text"])
    except DecryptError as exc:
        sys.exit(f"error: {exc}")


if __name__ == "__main__":
    main()
