import base64
import json
import os
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM, ChaCha20Poly1305

import decryptor as d

KEY = b"0123456789abcdef0123456789abcdef"
PLAIN = json.dumps({"balance": 120.5, "user": "ahmed"}).encode()


def enc_cbc(key=KEY, iv=None, prefix=True):
    iv = iv or os.urandom(16)
    p = padding.PKCS7(128).padder()
    c = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
    ct = c.update(p.update(PLAIN) + p.finalize()) + c.finalize()
    return (iv + ct if prefix else ct), iv


def b64(b):
    return base64.b64encode(b).decode()


def test_cbc_prefix_and_given_iv():
    body, iv = enc_cbc()
    r = d.decrypt_text(b64(body), algo="aes-cbc", key=KEY.decode())
    assert json.loads(r["text"]) == json.loads(PLAIN) and r["json"]
    ct, iv = enc_cbc(prefix=False)
    r = d.decrypt_text(b64(ct), algo="aes-cbc", key=KEY.hex(), key_enc="hex", iv=iv.hex(), iv_enc="hex", iv_mode="given")
    assert json.loads(r["text"])["user"] == "ahmed"


def test_key_as_iv_and_sha256_key():
    key = d.make_key("my passphrase", "sha256")
    ct, _ = enc_cbc(key=key, iv=key[:16], prefix=False)
    assert json.loads(d.decrypt_text(b64(ct), algo="aes-cbc", key="my passphrase", key_enc="sha256", iv_mode="key")["text"])["balance"] == 120.5


def test_gcm_chacha_ctr_ecb():
    iv = os.urandom(12)
    gcm = iv + AESGCM(KEY).encrypt(iv, PLAIN, b"v1")
    assert json.loads(d.decrypt_text(b64(gcm), algo="aes-gcm", key=KEY.decode(), aad="v1")["text"])["user"] == "ahmed"
    tag_first = iv + (lambda ct: ct[-16:] + ct[:-16])(AESGCM(KEY).encrypt(iv, PLAIN, None))
    assert json.loads(d.decrypt_text(b64(tag_first), algo="aes-gcm", key=KEY.decode(), tag_mode="prefix")["text"])["user"] == "ahmed"
    cc = iv + ChaCha20Poly1305(KEY).encrypt(iv, PLAIN, None)
    assert json.loads(d.decrypt_text(b64(cc), algo="chacha20-poly1305", key=KEY.decode())["text"])["user"] == "ahmed"
    iv16 = os.urandom(16)
    ctr = iv16 + (lambda e: e.update(PLAIN) + e.finalize())(Cipher(algorithms.AES(KEY), modes.CTR(iv16)).encryptor())
    assert json.loads(d.decrypt_text(b64(ctr), algo="aes-ctr", key=KEY.decode())["text"])["user"] == "ahmed"
    p = padding.PKCS7(128).padder()
    e = Cipher(algorithms.AES(KEY), modes.ECB()).encryptor()
    ecb = e.update(p.update(PLAIN) + p.finalize()) + e.finalize()
    assert json.loads(d.decrypt_text(ecb.hex(), algo="aes-ecb", key=KEY.decode(), body_enc="hex")["text"])["user"] == "ahmed"


def test_json_field_and_errors():
    body, _ = enc_cbc()
    wrapped = json.dumps({"code": 0, "result": {"payload": b64(body)}})
    assert d.decrypt_text(wrapped, algo="aes-cbc", key=KEY.decode(), field="result.payload")["json"]
    with pytest.raises(d.DecryptError, match="Bad padding"):
        d.decrypt_text(b64(body), algo="aes-cbc", key="x" * 32)
    with pytest.raises(d.DecryptError, match="16, 24 or 32"):
        d.decrypt_text(b64(body), algo="aes-cbc", key="short")
    with pytest.raises(d.DecryptError, match="not found"):
        d.decrypt_text(wrapped, algo="aes-cbc", key=KEY.decode(), field="result.nope")
    gcm = os.urandom(12)
    with pytest.raises(d.DecryptError, match="wrong key"):
        d.decrypt_text(b64(gcm + AESGCM(KEY).encrypt(gcm, PLAIN, None)), algo="aes-gcm", key="y" * 32)
    with pytest.raises(d.DecryptError, match="Not valid base64"):
        d.decrypt_text("%%%not base64%%%", algo="aes-cbc", key=KEY.decode())


def test_har_and_server():
    body, _ = enc_cbc()
    har = {"log": {"entries": [
        {"request": {"method": "GET", "url": "https://api.example.com/plain"}, "response": {"status": 200, "content": {"text": "hello", "mimeType": "text/plain"}}},
        {"request": {"method": "POST", "url": "https://api.example.com/wallet"},
         "response": {"status": 200, "content": {"text": b64(b64(body).encode()), "encoding": "base64", "mimeType": "text/plain"}}}]}}
    entries = d.load_har(json.dumps(har))
    assert [e["status"] for e in entries] == [200, 200] and entries[1]["body"] == b64(body)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), d.Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_port}"

    def post(path, obj, hdr=True):
        req = urllib.request.Request(base + path, json.dumps(obj).encode(), {"Content-Type": "application/json", **({"X-Decryptor": "1"} if hdr else {})})
        try:
            return json.load(urllib.request.urlopen(req))
        except urllib.error.HTTPError as exc:
            return {"http": exc.code}
    assert b"HTTP Response Decryptor" in urllib.request.urlopen(base + "/").read()
    listed = post("/api/har", {"har": json.dumps(har)})
    assert listed[1]["url"].endswith("/wallet")
    out = post("/api/decrypt", {"body": listed[1]["body"], "algo": "aes-cbc", "key": KEY.decode()})
    assert json.loads(out["text"])["user"] == "ahmed"
    assert post("/api/decrypt", {"body": "x", "algo": "aes-cbc", "key": "k"}, hdr=False) == {"http": 403}  # other sites cannot call it
    assert "error" in post("/api/decrypt", {"body": listed[1]["body"], "algo": "aes-cbc", "key": "z" * 32})
    srv.shutdown()
