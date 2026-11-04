# HTTP Response Decryptor

Decrypts encrypted HTTP response bodies of **your own app** for testing. Captures come from
[HTTP Toolkit](https://httptoolkit.com) (**Export → Export as HAR**) or are pasted in. Everything runs locally:
the UI listens on 127.0.0.1 only, only its own page may call the API, and keys are never stored or logged.

```bash
pip install cryptography
python decryptor.py serve            # open http://127.0.0.1:8899
```

Supports AES-CBC / ECB / CTR / GCM and ChaCha20-Poly1305; the key as text, hex, base64 or SHA-256/MD5 of a passphrase;
the IV from the start of the body, given separately, equal to the key, or zero; base64 / hex bodies; and encrypted text
inside a JSON field (`data`, `result.payload`). **Try common layouts** tests the usual combinations for you.

Command line:
```bash
python decryptor.py decrypt --har capture.har --list
python decryptor.py decrypt --har capture.har --entry 3 --field data --algo aes-cbc --key 'your-key' --iv-mode prefix
```
Tests: `pytest test_decryptor.py`.
