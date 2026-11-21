-- Optional DBA script. Execute with the project database selected.
CREATE ROLE IF NOT EXISTS 'charge_api';
SET @charge_schema = CONCAT('`', REPLACE(DATABASE(), '`', '``'), '`');
SET @charge_grant = CONCAT('GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON ', @charge_schema, '.* TO \'charge_api\'');
PREPARE charge_grant FROM @charge_grant;
EXECUTE charge_grant;
DEALLOCATE PREPARE charge_grant;
