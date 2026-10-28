-- FreeRADIUS connects as its own least-privilege role. The API sets its password at start-up
-- from RADIUS_DB_PASSWORD (see app/migrate.py); until then it cannot log in.
DO $$
BEGIN
 IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'radius') THEN
  CREATE ROLE radius NOLOGIN;
 END IF;
END $$;
GRANT USAGE ON SCHEMA public TO radius;
GRANT SELECT ON radcheck, radreply, radgroupcheck, radgroupreply, radusergroup, nas TO radius;
GRANT SELECT, INSERT, UPDATE ON radacct TO radius;
GRANT INSERT ON radpostauth TO radius;
GRANT SELECT, INSERT, UPDATE ON nasreload TO radius;
GRANT USAGE ON SEQUENCE radacct_radacctid_seq, radpostauth_id_seq TO radius;
