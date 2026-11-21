"""Local MySQL configuration; credentials are protected with Windows DPAPI."""
import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import runpy
import secrets
import sys
from project_paths import PROJECT_ROOT

ROOT = Path(__file__).resolve().parent
PRIVATE = ROOT / '.local' / 'runtime.dpapi'
SCHEMA = 'charge_course_20261114'


class Blob(ctypes.Structure):
    _fields_ = [('length', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_byte))]


def protected(data, decrypt=False):
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    target = Blob()
    api = ctypes.windll.crypt32
    if decrypt:
        ok = api.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        ok = api.CryptProtectData(ctypes.byref(source), 'Charging course local runtime', None, None,
                                  None, 1, ctypes.byref(target))
    if not ok:
        raise ctypes.WinError()
    try:
        return ctypes.string_at(target.data, target.length)
    finally:
        ctypes.windll.kernel32.LocalFree(target.data)


def load_runtime():
    if not PRIVATE.exists():
        return
    values = json.loads(protected(PRIVATE.read_bytes(), decrypt=True))
    for key, value in values.items():
        os.environ.setdefault(key, value)
    os.environ.setdefault('CHARGE_ADMIN_DSN', os.environ['CHARGE_DATABASE_URL'])


def configure():
    from cryptography.fernet import Fernet
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL
    if PRIVATE.exists():
        raise RuntimeError('Local configuration already exists; use status instead of replacing credentials.')
    from getpass import getpass
    root_password = os.environ.pop('CHARGE_ROOT_PASSWORD', None) or getpass('MySQL root password (not saved): ')
    admin = URL.create('mysql+pymysql', username='root', password=root_password,
                       host='127.0.0.1', port=3307, query={'charset': 'utf8mb4'})
    login = 'charge_api_' + secrets.token_hex(4)
    password = secrets.token_urlsafe(32)
    engine = create_engine(admin)
    with engine.connect() as db:
        if db.execute(text('SELECT 1 FROM information_schema.SCHEMATA WHERE SCHEMA_NAME=:s'),
                      {'s': SCHEMA}).scalar():
            raise RuntimeError('Target schema already exists; refusing to overwrite it.')
        db.exec_driver_sql(f'CREATE DATABASE `{SCHEMA}` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci')
        db.exec_driver_sql('CREATE USER %s@\'localhost\' IDENTIFIED BY %s', (login, password))
        db.exec_driver_sql(f'GRANT SELECT, INSERT, UPDATE, DELETE, EXECUTE ON `{SCHEMA}`.* TO %s@\'localhost\'', (login,))
        db.commit()
    app_url = URL.create('mysql+pymysql', username=login, password=password, host='127.0.0.1',
                         port=3307, database=SCHEMA, query={'charset': 'utf8mb4'})
    values = {'CHARGE_DATABASE_URL': app_url.render_as_string(hide_password=False),
              'CHARGE_SESSION_SECRET': secrets.token_urlsafe(48),
              'CHARGE_PII_KEY': Fernet.generate_key().decode(),
              'CHARGE_DEMO_PASSWORD': secrets.token_urlsafe(15)}
    PRIVATE.parent.mkdir(exist_ok=True)
    PRIVATE.write_bytes(protected(json.dumps(values).encode()))
    print(json.dumps({'database': SCHEMA, 'server': '127.0.0.1:3307', 'app_user': login,
                      'credentials': 'Windows DPAPI; root password was not saved'}, ensure_ascii=False))


def configure_existing():
    """Configure another Windows user's authorized connection without changing DB rows."""
    if PRIVATE.exists():
        raise RuntimeError('Local configuration already exists; refusing to replace it.')
    from getpass import getpass
    from cryptography.fernet import Fernet, InvalidToken
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import URL
    from auth import verify
    host = input('MySQL host [127.0.0.1]: ').strip() or '127.0.0.1'
    username = input('Authorized application database user: ').strip()
    password = getpass('Application database password: ')
    pii_key = getpass('Existing project PII key (from administrator): ').strip()
    demo_password = getpass('Existing synthetic demo account password: ')
    if not username or len(demo_password) < 10:
        raise RuntimeError('An application user and the existing demo password are required.')
    try:
        cipher = Fernet(pii_key.encode())
    except (ValueError, TypeError):
        raise RuntimeError('The supplied PII key is invalid; no configuration saved.') from None
    url = URL.create('mysql+pymysql', username=username, password=password,
                     host=host, port=3307, database=SCHEMA, query={'charset': 'utf8mb4'})
    engine = create_engine(url)
    try:
        with engine.connect() as db:
            hashed = db.execute(text("SELECT password_hash FROM account WHERE login='admin'")).scalar_one_or_none()
            if hashed is None or not verify(demo_password, hashed):
                raise RuntimeError('The demo password does not match this database; no configuration saved.')
            encrypted = db.execute(text('SELECT phone_cipher FROM account WHERE phone_cipher IS NOT NULL LIMIT 1')).scalar()
            if not encrypted:
                encrypted = db.execute(text('SELECT plate_cipher FROM vehicle WHERE plate_cipher IS NOT NULL LIMIT 1')).scalar()
            if encrypted:
                try:
                    cipher.decrypt(bytes(encrypted))
                except InvalidToken:
                    raise RuntimeError('The PII key does not match existing data; no configuration saved.') from None
            else:
                print('No encrypted sample is available; only key format was checked. Use the existing administrator-provided project key.')
    finally:
        engine.dispose()
    values = {'CHARGE_DATABASE_URL': url.render_as_string(hide_password=False),
              'CHARGE_SESSION_SECRET': secrets.token_urlsafe(48),
              'CHARGE_PII_KEY': pii_key, 'CHARGE_DEMO_PASSWORD': demo_password}
    PRIVATE.parent.mkdir(exist_ok=True)
    encrypted_values = protected(json.dumps(values).encode())
    with PRIVATE.open('xb') as config_file:
        config_file.write(encrypted_values)
    print('Authorized local configuration saved with Windows DPAPI. Database rows were not modified.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['configure', 'connect-existing', 'run', 'status', 'demo-login'])
    parser.add_argument('script', nargs='?')
    args, rest = parser.parse_known_args()
    if args.action == 'configure':
        configure()
        return
    if args.action == 'connect-existing':
        try:
            configure_existing()
        except Exception as error:
            # Database exceptions can include URLs or SQL parameters; never echo them.
            print('Connection setup failed (' + type(error).__name__ + '). No existing configuration or database rows were replaced.', file=sys.stderr)
            raise SystemExit(1)
        return
    load_runtime()
    if args.action == 'demo-login':
        print('Local synthetic demo accounts: driver1, admin, tech1, settlement, operator1, fleet1')
        print('Demo password:', os.environ['CHARGE_DEMO_PASSWORD'])
    elif args.action == 'status':
        from sqlalchemy import create_engine, text
        with create_engine(os.environ['CHARGE_DATABASE_URL']).connect() as db:
            print(json.dumps(dict(db.execute(text('SELECT VERSION() version,DATABASE() db,@@port port')).mappings().one()), ensure_ascii=False))
    else:
        if not args.script:
            parser.error('run requires a script path')
        candidate = Path(args.script)
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate if (PROJECT_ROOT / candidate).is_file() else ROOT / candidate
        script = candidate.resolve()
        if PROJECT_ROOT not in script.parents or script.suffix != '.py':
            parser.error('script must be a Python file inside this project')
        sys.path.insert(0, str(ROOT))
        sys.argv = [str(script), *rest]
        runpy.run_path(str(script), run_name='__main__')


if __name__ == '__main__':
    main()
