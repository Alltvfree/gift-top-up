-- Standard FreeRADIUS 3.x PostgreSQL schema (rlm_sql_postgresql), shared with the API.
-- FreeRADIUS reads radcheck/radreply/radusergroup/radgroup*, writes radacct/radpostauth,
-- and loads NAS clients from `nas` (read_clients = yes).

CREATE TABLE IF NOT EXISTS radcheck (
 id BIGSERIAL PRIMARY KEY, username TEXT NOT NULL DEFAULT '', attribute TEXT NOT NULL DEFAULT '',
 op VARCHAR(2) NOT NULL DEFAULT '==', value TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radcheck_username ON radcheck(username, attribute);

CREATE TABLE IF NOT EXISTS radreply (
 id BIGSERIAL PRIMARY KEY, username TEXT NOT NULL DEFAULT '', attribute TEXT NOT NULL DEFAULT '',
 op VARCHAR(2) NOT NULL DEFAULT '=', value TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radreply_username ON radreply(username, attribute);

CREATE TABLE IF NOT EXISTS radgroupcheck (
 id BIGSERIAL PRIMARY KEY, groupname TEXT NOT NULL DEFAULT '', attribute TEXT NOT NULL DEFAULT '',
 op VARCHAR(2) NOT NULL DEFAULT '==', value TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radgroupcheck_groupname ON radgroupcheck(groupname, attribute);

CREATE TABLE IF NOT EXISTS radgroupreply (
 id BIGSERIAL PRIMARY KEY, groupname TEXT NOT NULL DEFAULT '', attribute TEXT NOT NULL DEFAULT '',
 op VARCHAR(2) NOT NULL DEFAULT '=', value TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS radgroupreply_groupname ON radgroupreply(groupname, attribute);

CREATE TABLE IF NOT EXISTS radusergroup (
 id BIGSERIAL PRIMARY KEY, username TEXT NOT NULL DEFAULT '', groupname TEXT NOT NULL DEFAULT '',
 priority INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS radusergroup_username ON radusergroup(username);

CREATE TABLE IF NOT EXISTS radacct (
 radacctid BIGSERIAL PRIMARY KEY,
 acctsessionid TEXT NOT NULL, acctuniqueid TEXT NOT NULL UNIQUE,
 username TEXT, realm TEXT, nasipaddress INET NOT NULL, nasportid TEXT, nasporttype TEXT,
 acctstarttime TIMESTAMPTZ, acctupdatetime TIMESTAMPTZ, acctstoptime TIMESTAMPTZ,
 acctinterval BIGINT, acctsessiontime BIGINT, acctauthentic TEXT,
 connectinfo_start TEXT, connectinfo_stop TEXT,
 acctinputoctets BIGINT, acctoutputoctets BIGINT,
 calledstationid TEXT, callingstationid TEXT, acctterminatecause TEXT,
 servicetype TEXT, framedprotocol TEXT, framedipaddress INET,
 framedipv6address INET, framedipv6prefix INET, framedinterfaceid TEXT, delegatedipv6prefix INET,
 class TEXT
);
CREATE INDEX IF NOT EXISTS radacct_active_session_idx ON radacct(acctuniqueid) WHERE acctstoptime IS NULL;
CREATE INDEX IF NOT EXISTS radacct_bulk_close ON radacct(nasipaddress, acctstarttime) WHERE acctstoptime IS NULL;
CREATE INDEX IF NOT EXISTS radacct_start_user_idx ON radacct(acctstarttime, username);
CREATE INDEX IF NOT EXISTS radacct_username_open_idx ON radacct(username) WHERE acctstoptime IS NULL;

CREATE TABLE IF NOT EXISTS radpostauth (
 id BIGSERIAL PRIMARY KEY, username TEXT NOT NULL, pass TEXT, reply TEXT,
 calledstationid TEXT, callingstationid TEXT, authdate TIMESTAMPTZ NOT NULL DEFAULT now(), class TEXT
);
CREATE INDEX IF NOT EXISTS radpostauth_authdate_idx ON radpostauth(authdate DESC);

-- Written on Accounting-On/Off; simul_count_query joins it to ignore sessions from before a NAS reboot.
CREATE TABLE IF NOT EXISTS nasreload (
 nasipaddress INET PRIMARY KEY, reloadtime TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS nas (
 id SERIAL PRIMARY KEY, nasname TEXT NOT NULL UNIQUE, shortname TEXT NOT NULL,
 type TEXT NOT NULL DEFAULT 'other', ports INTEGER, secret TEXT NOT NULL,
 server TEXT, community TEXT, description TEXT,
 device_id UUID REFERENCES devices(id) ON DELETE CASCADE
);

-- The starter's placeholder table is replaced by radacct; drop it only if nothing was ever written.
DO $$
BEGIN
 IF to_regclass('public.radius_sessions') IS NOT NULL
    AND NOT EXISTS (SELECT 1 FROM radius_sessions) THEN
  DROP TABLE radius_sessions;
 END IF;
END $$;

-- Suspended customers: throttled and tagged so MikroTik redirects them to the payment page.
INSERT INTO radgroupreply (groupname, attribute, op, value)
SELECT 'suspended', a, ':=', v FROM (VALUES
 ('Mikrotik-Rate-Limit','256k/256k'),
 ('Mikrotik-Address-List','suspended')) t(a,v)
WHERE NOT EXISTS (SELECT 1 FROM radgroupreply WHERE groupname='suspended');
