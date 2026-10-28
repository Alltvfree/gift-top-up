-- Subscribers imported from DMA Radius Manager keep DMA as their billing system until switch-over:
-- automatic invoicing, overdue suspension and billing SMS only touch managed_by='platform'.
ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS managed_by TEXT NOT NULL DEFAULT 'platform';
ALTER TABLE subscribers DROP CONSTRAINT IF EXISTS subscribers_managed_by_check;
ALTER TABLE subscribers ADD CONSTRAINT subscribers_managed_by_check CHECK (managed_by IN ('platform','dma'));
ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS expires_at DATE;
ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS imported_at TIMESTAMPTZ;

-- SMS (MessageOwl). Every message is a row: queued by the API/billing, sent by the worker.
CREATE TABLE IF NOT EXISTS sms_templates (
 kind TEXT PRIMARY KEY,
 body TEXT NOT NULL,
 enabled BOOLEAN NOT NULL DEFAULT true,
 updated_by TEXT,
 updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO sms_templates(kind, body) VALUES
 ('invoice_issued',   'SatLink: Dear {name}, invoice {invoice} for MVR {amount} is due on {due}. Account {account}.'),
 ('due_reminder',     'SatLink: Reminder - MVR {amount} for account {account} is due on {due}. Please pay to avoid interruption.'),
 ('payment_received', 'SatLink: Payment of MVR {amount} received for account {account}. Thank you!'),
 ('suspended',        'SatLink: Internet for account {account} is suspended for non-payment. Balance MVR {balance}. Please pay to restore.'),
 ('restored',         'SatLink: Internet for account {account} is restored. Thank you!')
ON CONFLICT (kind) DO NOTHING;

CREATE TABLE IF NOT EXISTS sms_messages (
 id BIGSERIAL PRIMARY KEY,
 subscriber_id UUID REFERENCES subscribers(id) ON DELETE SET NULL,
 phone TEXT NOT NULL,
 kind TEXT NOT NULL,           -- a template kind, 'manual' or 'broadcast'
 ref TEXT,                     -- invoice id / broadcast id: (subscriber, kind, ref) is sent once
 body TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'queued' CHECK (status IN ('queued','sending','sent','failed','skipped')),
 provider_id TEXT,
 error TEXT,
 created_by TEXT NOT NULL,
 created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
 sent_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX IF NOT EXISTS sms_messages_once ON sms_messages(subscriber_id, kind, ref) WHERE ref IS NOT NULL;
CREATE INDEX IF NOT EXISTS sms_messages_queue ON sms_messages(id) WHERE status = 'queued';
CREATE INDEX IF NOT EXISTS sms_messages_created ON sms_messages(created_at DESC);
