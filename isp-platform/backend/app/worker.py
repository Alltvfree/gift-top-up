"""Background worker: device polling every POLL_INTERVAL_S, billing enforcement once a day."""
import logging
import time
from datetime import date

from . import config, db
from .migrate import migrate
from .services import billing, monitor, radius_sync, sms

log = logging.getLogger("worker")


def daily_billing():
    with db.connect() as conn:
        # Invoices go out on the 1st; generate_invoices is idempotent so re-running is harmless.
        created = billing.generate_invoices(conn, date.today(), "system") if date.today().day == 1 else 0
        suspended = billing.enforce_overdue(conn, "system")
        reminders = sms.queue_due_reminders(conn)
    with db.connect() as conn:
        for username in suspended:
            radius_sync.disconnect(conn, username)
    log.info("billing: %s invoices, %s suspended, %s reminders queued", created, len(suspended), reminders)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    migrate()
    cycle, last_billing = 0, None
    while True:
        started = time.monotonic()
        try:
            monitor.sweep(cycle)
        except Exception:
            log.exception("poll sweep failed")
        try:
            with db.connect() as conn:
                result = sms.send_pending(conn)
            if result["posts"]:
                log.info("sms: %s", result)
        except Exception:
            log.exception("sms sending failed")
        if last_billing != date.today():
            try:
                daily_billing()
                last_billing = date.today()
            except Exception:
                log.exception("billing run failed")
        cycle += 1
        time.sleep(max(5.0, config.POLL_INTERVAL_S - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
