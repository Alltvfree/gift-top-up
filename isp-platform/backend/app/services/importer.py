"""Import subscribers and NAS clients from CSV exports (DMA Softlab Radius Manager or any similar system).

Columns are recognised by name (see ALIASES), in any order, with , ; tab or | as separator.
Every import can run as a dry run first: same checks, nothing written.
Imported subscribers get managed_by='dma': DMA stays their billing system, so this platform
never invoices, suspends or texts them about billing until they are switched over.
"""
import csv
import io
import ipaddress
import re
from datetime import date, datetime

from .. import audit
from ..adapters.msgowl import normalize_phone
from . import radius_sync

ALIASES = {
    "subscribers": {
        "username": ["username", "user", "login", "pppoeusername", "pppoe", "loginname"],
        "password": ["password", "passwd", "pass", "pwd", "cleartextpassword"],
        "full_name": ["name", "fullname", "customername", "customer", "subscriber"],
        "first_name": ["firstname", "fname", "givenname"],
        "last_name": ["lastname", "lname", "surname", "familyname"],
        "phone": ["mobile", "phone", "gsm", "mobileno", "mobilenumber", "phoneno", "phonenumber", "contact", "contactno", "cell", "tel"],
        "address": ["address", "address1", "street", "houseaddress"],
        "city": ["city", "town"],
        "plan": ["srvname", "service", "servicename", "plan", "planname", "package", "profile", "srvid"],
        "expires": ["expiration", "expiry", "expirydate", "expires", "expire", "expirationdate", "validuntil"],
        "enabled": ["enableuser", "enabled", "active", "status", "enable"],
        "static_ip": ["staticipcpe", "staticip", "ipaddress", "ip", "framedipaddress", "framedip"],
        "account": ["account", "accountno", "accountnumber", "customerid", "customerno"],
        "island": ["island", "location", "site"],
    },
    "nas": {
        "nasname": ["nasname", "nasip", "ipaddress", "ip", "address", "host"],
        "shortname": ["shortname", "name", "nasidentifier", "identifier"],
        "secret": ["secret", "sharedsecret", "radiussecret", "nassecret"],
        "type": ["type", "nastype"],
        "description": ["description", "comment", "descr", "notes"],
    },
}
TRUE = {"1", "yes", "y", "true", "active", "enabled", "enable", "on"}
FALSE = {"0", "no", "n", "false", "inactive", "disabled", "disable", "off", "blocked", "suspended"}


def _key(header: str) -> str:
    return re.sub(r"[^a-z0-9]", "", header.lower())


def parse_csv(text: str) -> tuple[list[str], list[dict]]:
    text = text.lstrip("﻿")
    sample = text[:5000]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    # `mysql -B` exports write NULL for empty fields
    rows = [{k: "" if (v or "").strip().upper() == "NULL" else (v or "").strip() for k, v in r.items() if k is not None} for r in reader]
    return reader.fieldnames or [], rows


def map_columns(kind: str, headers: list[str]) -> tuple[dict, list[str]]:
    by_key = {_key(h): h for h in headers}
    mapping = {}
    for field, names in ALIASES[kind].items():
        for n in names:
            if n in by_key and by_key[n] not in mapping.values():
                mapping[field] = by_key[n]
                break
    unmapped = [h for h in headers if h not in mapping.values()]
    return mapping, unmapped


def parse_date(v: str) -> date | None:
    v = (v or "").strip()
    if not v or v.startswith("0000"):
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y", "%d/%m/%Y %H:%M", "%Y/%m/%d"):
        try:
            return datetime.strptime(v[:19] if "%H" in fmt else v[:10], fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date '{v}'")


def parse_bool(v: str) -> bool:
    v = (v or "").strip().lower()
    if v in FALSE:
        return False
    return True  # blank or anything else counts as enabled


def import_subscribers(conn, text: str, actor: str, dry_run=True, default_island_id=None, create_missing_plans=False) -> dict:
    headers, rows = parse_csv(text)
    mapping, unmapped = map_columns("subscribers", headers)
    report = {"kind": "subscribers", "dry_run": dry_run, "columns": mapping, "unmapped_columns": unmapped, "rows": len(rows),
              "new": 0, "updated": 0, "skipped": 0, "errors": [], "plans_missing": [], "status": {}, "invalid_phones": 0,
              "no_password": 0, "sample": []}
    if "username" not in mapping:
        report["errors"].append({"row": 1, "error": "No username column found (expected e.g. 'username')"})
        return report
    plans = {p["name"].lower(): p for p in conn.execute("SELECT * FROM service_plans")}
    islands = {}
    for i in conn.execute("SELECT id, code, name FROM islands"):
        islands[i["code"].lower()] = i["id"]
        islands[i["name"].lower()] = i["id"]
    get = lambda r, f: r.get(mapping[f], "") if f in mapping else ""  # noqa: E731
    seen, missing = set(), {}
    today = date.today()
    for n, r in enumerate(rows, start=2):  # row 1 is the header line
        try:
            user = get(r, "username")
            if not user:
                raise ValueError("empty username")
            if not re.fullmatch(r"[A-Za-z0-9._@-]{2,64}", user):
                raise ValueError(f"unsupported characters in username '{user}'")
            if user in seen:
                raise ValueError(f"username '{user}' appears twice in the file")
            seen.add(user)
            name = get(r, "full_name") or " ".join(x for x in (get(r, "first_name"), get(r, "last_name")) if x) or user
            address = ", ".join(x for x in (get(r, "address"), get(r, "city")) if x) or None
            phone = get(r, "phone") or None
            expires = parse_date(get(r, "expires"))
            enabled = parse_bool(get(r, "enabled")) if "enabled" in mapping else True
            static_ip = get(r, "static_ip") or None
            if static_ip:
                try:
                    static_ip = str(ipaddress.IPv4Address(static_ip))
                except ValueError:
                    static_ip = None  # DMA leaves odd values here for dynamic users
            plan_name = get(r, "plan")
            plan = plans.get(plan_name.lower()) if plan_name else None
            if plan_name and not plan:
                missing[plan_name] = missing.get(plan_name, 0) + 1
            island_val = get(r, "island").lower()
            island_id = islands.get(island_val) if island_val else None
            island_id = island_id or default_island_id
            if not enabled:
                status, reason = "suspended", "imported: disabled in DMA"
            elif expires and expires < today:
                status, reason = "suspended", "imported: expired in DMA"
            elif plan or (plan_name and create_missing_plans):
                status, reason = "active", None
            else:
                status, reason = "pending", None
            password = get(r, "password") or None
            report["status"][status] = report["status"].get(status, 0) + 1
            report["invalid_phones"] += phone is not None and normalize_phone(phone) is None
            report["no_password"] += password is None
            existing = conn.execute("SELECT * FROM subscribers WHERE pppoe_username=%s", (user,)).fetchone()
            if existing and existing["managed_by"] == "platform":
                report["skipped"] += 1
                continue
            if len(report["sample"]) < 5:
                report["sample"].append({"username": user, "name": name, "phone": phone, "plan": plan_name, "expires": str(expires or ""),
                                         "status": status, "has_password": password is not None})
            report["updated" if existing else "new"] += 1
            if dry_run:
                continue
            if plan_name and not plan and create_missing_plans:
                plan = conn.execute(
                    """INSERT INTO service_plans(name,download_mbps,upload_mbps,monthly_price_mvr,active) VALUES (%s,1,1,0,false)
                       ON CONFLICT (name) DO UPDATE SET name=EXCLUDED.name RETURNING *""", (plan_name,)).fetchone()
                plans[plan_name.lower()] = plan
                radius_sync.sync_plan(conn, plan)
            values = (name[:120], phone, address, island_id, plan["id"] if plan else None, static_ip, status, reason, expires)
            if existing:
                sub = conn.execute(
                    """UPDATE subscribers SET full_name=%s, phone=%s, address=%s, island_id=COALESCE(%s, island_id), plan_id=%s,
                       static_ip=%s, status=%s, suspended_reason=%s, expires_at=%s, imported_at=now() WHERE id=%s RETURNING *""",
                    (*values, existing["id"])).fetchone()
            else:
                account = get(r, "account") or user
                if conn.execute("SELECT 1 FROM subscribers WHERE account_number=%s", (account,)).fetchone():
                    account = f"{account}-{user}"[:60]
                sub = conn.execute(
                    """INSERT INTO subscribers(full_name,phone,address,island_id,plan_id,static_ip,status,suspended_reason,expires_at,
                                               account_number,pppoe_username,managed_by,imported_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'dma',now()) RETURNING *""",
                    (*values, account, user)).fetchone()
            radius_sync.sync_subscriber(conn, sub, password=password)
        except ValueError as exc:
            report["errors"].append({"row": n, "error": str(exc)})
    report["plans_missing"] = [{"name": k, "subscribers": v} for k, v in sorted(missing.items())]
    report["errors"] = report["errors"][:100]
    if not dry_run:
        audit.record(actor, "import.subscribers", detail={k: report[k] for k in ("rows", "new", "updated", "skipped")}, conn=conn)
    return report


def import_nas(conn, text: str, actor: str, dry_run=True) -> dict:
    headers, rows = parse_csv(text)
    mapping, unmapped = map_columns("nas", headers)
    report = {"kind": "nas", "dry_run": dry_run, "columns": mapping, "unmapped_columns": unmapped, "rows": len(rows),
              "new": 0, "updated": 0, "skipped": 0, "errors": [], "weak_secrets": 0, "sample": []}
    for need in ("nasname", "secret"):
        if need not in mapping:
            report["errors"].append({"row": 1, "error": f"No {need} column found"})
    if report["errors"]:
        return report
    get = lambda r, f: r.get(mapping[f], "") if f in mapping else ""  # noqa: E731
    for n, r in enumerate(rows, start=2):
        try:
            ip = str(ipaddress.ip_address(get(r, "nasname")))
            secret = get(r, "secret")
            if not secret:
                raise ValueError("empty secret")
            short = re.sub(r"[^A-Za-z0-9._-]", "-", get(r, "shortname") or ip)[:40]
            report["weak_secrets"] += len(secret) < 12
            exists = conn.execute("SELECT 1 FROM nas WHERE nasname=%s", (ip,)).fetchone()
            report["updated" if exists else "new"] += 1
            if len(report["sample"]) < 5:
                report["sample"].append({"nasname": ip, "shortname": short, "type": get(r, "type") or "other"})
            if dry_run:
                continue
            conn.execute(
                """INSERT INTO nas(nasname,shortname,type,secret,description) VALUES (%s,%s,%s,%s,%s)
                   ON CONFLICT (nasname) DO UPDATE SET shortname=EXCLUDED.shortname, type=EXCLUDED.type,
                   secret=EXCLUDED.secret, description=EXCLUDED.description""",
                (ip, short, (get(r, "type") or "other")[:30], secret, get(r, "description")[:200] or None))
        except ValueError as exc:
            report["errors"].append({"row": n, "error": str(exc)})
    report["errors"] = report["errors"][:100]
    if not dry_run:
        audit.record(actor, "import.nas", detail={k: report[k] for k in ("rows", "new", "updated")}, conn=conn)
    return report
