# Moving from DMA Softlab Radius Manager

The plan: copy DMA's data into SatLink and keep it fresh, while **DMA stays in charge** of logins and billing.
Switch islands over to SatLink's RADIUS one at a time, later, when you decide.

## 1. Export from DMA
Either export users and NAS as CSV from the DMA web panel, or, to make sure **passwords** are included
(needed later, so customers' ONTs keep working when RADIUS moves), export straight from DMA's MySQL on the DMA server:

```bash
mysql -u root -p radius -B -e "
  SELECT u.username,
         (SELECT c.value FROM radcheck c WHERE c.username=u.username AND c.attribute='Cleartext-Password' LIMIT 1) AS password,
         u.firstname, u.lastname, u.mobile, u.phone, u.address, u.city,
         s.srvname, u.expiration, u.enableuser, u.staticipcpe
  FROM rm_users u LEFT JOIN rm_services s ON s.srvid = u.srvid" > dma_users.tsv

mysql -u root -p radius -B -e "SELECT nasname, shortname, secret, type, description FROM nas" > dma_nas.tsv
```
If MySQL says a column doesn't exist, your DMA version names it differently: run `DESCRIBE rm_users;` and adjust.
These files contain every customer's password and every RADIUS secret: copy them over an encrypted link
(scp), and delete them (`shred -u dma_*.tsv`) after importing.

## 2. Import into SatLink
*Admin → Import*: pick **Subscribers**, choose the file, optionally an island for users without one, **Preview**.
The preview writes nothing and shows which columns it recognised, how many are new/updated, status counts
(enabled + not expired → active, expired or disabled → suspended, no plan → pending), plans that don't exist yet,
users without a password and invalid mobiles. Fix what you need (create the plans under *Plans* with the right
speeds and prices, or tick *Create missing plans*), Preview again, then **Import**. Do the same for **NAS clients**,
then `docker compose restart radius`.

Re-importing later updates the same customers (matched by PPPoE username, case-sensitive) instead of duplicating them.

## What "managed by DMA" means
Imported customers show **DMA** in the *Billing* column. For them SatLink does **not** create invoices, mark overdue,
suspend for non-payment, or send billing SMS — DMA does that. You can still see them, their sessions, send them
manual SMS and include them in outage notices.

## SMS (MessageOwl)
Put your MessageOwl access key and approved sender ID in `.env` (`MSGOWL_ACCESS_KEY`, `MSGOWL_SENDER_ID`), then
`docker compose up -d`. *SMS → Test the gateway* sends one message immediately and shows MessageOwl's answer.
Automatic messages (invoice, reminder, payment, suspended, restored) are editable under *SMS* and only go to customers
billed by SatLink. *Islands → Notify* or *SMS → Write notice* sends an outage notice to a whole island.
