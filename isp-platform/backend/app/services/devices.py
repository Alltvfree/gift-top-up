"""Open the right adapter for a device row, using its decrypted credentials."""
from contextlib import contextmanager

from ..adapters.huawei import HuaweiOLT
from ..adapters.mikrotik import RouterOS
from ..security import decrypt_json


class NoCredentials(Exception):
    pass


def creds(device: dict) -> dict:
    c = decrypt_json(device.get("credentials_enc"))
    if not c.get("username"):
        raise NoCredentials(f"{device['name']}: no credentials stored")
    return c


@contextmanager
def mikrotik(device: dict):
    c = creds(device)
    with RouterOS(str(device["management_ip"]), c["username"], c["password"], device.get("mgmt_port"),
                  verify_tls=(device.get("settings") or {}).get("ca_bundle") or False) as ros:
        yield ros


@contextmanager
def olt(device: dict):
    from .olt_access import endpoint  # OLTs behind an island router are reached through its forward port
    c = creds(device)
    host, port = endpoint(device)
    with HuaweiOLT(host, c["username"], c["password"], port, host_key=device.get("ssh_host_key")) as h:
        yield h
