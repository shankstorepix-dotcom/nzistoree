"""NziStore: encrypted storage, opaque server sessions and explicit authorization."""
import unicodedata
import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import smtplib
import sqlite3
import time
import urllib.request
import urllib.error
from email.message import EmailMessage
from urllib.parse import urlencode, urlsplit
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, abort, g, jsonify, redirect, request, send_from_directory
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlcipher3 import dbapi2 as sqlcipher
from werkzeug.exceptions import HTTPException

ROOT = Path(__file__).resolve().parent
CATEGORIES = ['Robux', 'Painel (login)', 'Streamings', 'Contas Discord', 'Contas Roblox']
CATEGORY_DEFAULTS = [
    ('robux', 'Robux', 'Robux'), ('painel', 'Painel (login)', 'Painéis'),
    ('streaming', 'Streamings', 'Streamings'), ('contas-discord', 'Contas Discord', 'Contas Discord'),
    ('contas-roblox', 'Contas Roblox', 'Roblox')]
ACCESS_TTL = 2 * 3600
SESSION_TTL = 8 * 3600
OTP_TTL = 10 * 60
OTP_RESEND_COOLDOWN = 60
OTP_MAX_ATTEMPTS = 5

def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()

def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1).hex()

def new_password(password):
    if not isinstance(password, str) or not 8 <= len(password) <= 24:
        abort(400, 'Crie uma senha com caracteres entre 8 e 24 caracteres.')
    salt = secrets.token_hex(16)
    return salt + ':' + password_hash(password, salt)

def new_pin(pin):
    if not isinstance(pin, str) or not re.fullmatch(r"[0-9]{6}", pin):
        raise ValueError("O PIN precisa ter exatamente seis dígitos.")
    salt = secrets.token_hex(16)
    return salt + ":" + password_hash(pin, salt)

def verify(password, stored):
    salt, hashed = stored.split(':')
    return hmac.compare_digest(password_hash(password, salt), hashed)

def default_nickname(email):
    local = unicodedata.normalize('NFKD', email.split('@', 1)[0]).encode('ascii', 'ignore').decode()
    name = re.sub(r'[^a-zA-Z0-9_.-]', '', local).strip('._-')[:32]
    return name if len(name) >= 3 else (name + '_user' if name else 'usuario')

def create_app(config=None):
    # Explicit test configurations remain isolated from local service credentials.
    if config is None:
        load_dotenv(ROOT / '.env', override=False, interpolate=False)
    app = Flask(__name__, static_folder=None)
    production = os.getenv('APP_ENV') == 'production'
    is_vercel = bool(os.getenv('VERCEL'))
    base_storage = Path('/tmp/nzistore') if is_vercel else ROOT
    vercel_host = os.getenv('VERCEL_PROJECT_PRODUCTION_URL') or os.getenv('VERCEL_URL') or ''
    default_origin = f"https://{vercel_host}" if is_vercel and vercel_host else 'http://localhost:8000'
    raw_origin = (os.getenv('APP_URL') or os.getenv('PUBLIC_ORIGIN') or os.getenv('SITE_URL') or default_origin).strip()
    if raw_origin and not raw_origin.startswith(('http://', 'https://')):
        raw_origin = f"https://{raw_origin}"
    app.config.update(DATA_DIR=str(base_storage/'data'), UPLOAD_DIR=str(base_storage/'uploads'),
                      PRODUCTION=production, MAX_CONTENT_LENGTH=7_000_000,
                      PUBLIC_ORIGIN=raw_origin,
                      TRUSTED_HOSTS=['localhost', '127.0.0.1'] if not production else [],
                      DB_KEY=os.getenv('DATABASE_KEY', '').strip())
    if config:
        app.config.update(config)
    origin = app.config['PUBLIC_ORIGIN']
    from urllib.parse import urlsplit
    parsed = urlsplit(origin)
    allowed_origins = {origin}
    if not app.config['PRODUCTION'] and parsed.hostname in ('localhost', '127.0.0.1'):
        port_suffix = f':{parsed.port}' if parsed.port else ''
        allowed_origins |= {f'{parsed.scheme}://localhost{port_suffix}', f'{parsed.scheme}://127.0.0.1{port_suffix}'}
    data_dir = Path(app.config['DATA_DIR'])
    uploads = Path(app.config['UPLOAD_DIR'])
    data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    uploads.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(data_dir, 0o700)
    os.chmod(uploads, 0o700)
    for name in ('SMTP_HOST', 'SMTP_PORT', 'SMTP_USER', 'SMTP_PASSWORD', 'SMTP_FROM', 'SMTP_TLS',
                 'GOOGLE_CLIENT_ID', 'GOOGLE_CLIENT_SECRET', 'DISCORD_CLIENT_ID', 'DISCORD_CLIENT_SECRET'):
        app.config.setdefault(name, os.getenv(name, ''))
    key = app.config['DB_KEY']
    if not key:
        key_path = data_dir/'.database-key'
        if not key_path.exists():
            try:
                fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, 'w') as f:
                    f.write(secrets.token_hex(32))
            except FileExistsError:
                pass
        os.chmod(key_path, 0o600)
        key = key_path.read_text().strip()
        app.config['DB_KEY'] = key
    if not re.fullmatch(r'[a-fA-F0-9]{64}', key):
        raise RuntimeError('DATABASE_KEY deve ter exatamente 64 caracteres hexadecimais.')
    if app.config['PRODUCTION']:
        if not is_vercel and (parsed.scheme != 'https' or not parsed.hostname or not app.config['DB_KEY']):
            raise RuntimeError('Produção exige PUBLIC_ORIGIN=https://dominio e DATABASE_KEY (64 hex).')
        if is_vercel:
            app.config['TRUSTED_HOSTS'] = [parsed.hostname or 'localhost', '.vercel.app', 'nzistoree.vercel.app']
            if parsed.hostname:
                allowed_origins.add(f"https://{parsed.hostname}")
            allowed_origins.add('https://nzistoree.vercel.app')
        else:
            app.config['TRUSTED_HOSTS'] = [parsed.hostname]
    db_path = data_dir/'secure.db'

    @contextmanager
    def db():
        conn = sqlcipher.connect(str(db_path), timeout=10)
        conn.row_factory = sqlcipher.Row
        conn.execute(f"PRAGMA key = \"x'{key}'\"")
        conn.execute('PRAGMA foreign_keys=ON')
        conn.execute('PRAGMA trusted_schema=OFF')
        try:
            with conn:
                yield conn
        finally:
            conn.close()
    app.extensions['db'] = db
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL, price INTEGER NOT NULL, category TEXT NOT NULL, image TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, email TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','customer')), email_verified INTEGER NOT NULL DEFAULT 1 CHECK(email_verified IN (0,1)));
        CREATE TABLE IF NOT EXISTS roblox_subcategories(id INTEGER PRIMARY KEY AUTOINCREMENT,slug TEXT UNIQUE NOT NULL,title TEXT NOT NULL,image TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS product_subcategories(product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,subcategory_id INTEGER NOT NULL REFERENCES roblox_subcategories(id) ON DELETE RESTRICT);
        CREATE TABLE IF NOT EXISTS user_profiles(user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,nickname TEXT NOT NULL,changed_at INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, csrf TEXT NOT NULL, expires INTEGER NOT NULL, refresh_token TEXT UNIQUE, absolute_expires INTEGER);
        CREATE TABLE IF NOT EXISTS used_refresh_tokens(token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS email_otps(email TEXT PRIMARY KEY, code_hash TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, expires INTEGER NOT NULL, sent_at INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS password_resets(email TEXT PRIMARY KEY,code_hash TEXT NOT NULL,attempts INTEGER NOT NULL DEFAULT 0,expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS oauth_states(state_hash TEXT PRIMARY KEY, provider TEXT NOT NULL, verifier TEXT NOT NULL, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS oauth_accounts(provider TEXT NOT NULL, provider_user_id TEXT NOT NULL, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, email TEXT NOT NULL, created INTEGER NOT NULL, PRIMARY KEY(provider, provider_user_id));
        CREATE TABLE IF NOT EXISTS admin_credentials(user_id INTEGER PRIMARY KEY REFERENCES users(id), pin_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS admin_sessions(token TEXT PRIMARY KEY REFERENCES sessions(token) ON DELETE CASCADE);
        CREATE TABLE IF NOT EXISTS limits(bucket TEXT PRIMARY KEY, count INTEGER NOT NULL, expires INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, event TEXT NOT NULL, actor INTEGER, created INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        ''')
        user_cols = {r['name'] for r in c.execute('PRAGMA table_info(users)').fetchall()}
        if 'email_verified' not in user_cols:
            c.execute('ALTER TABLE users ADD COLUMN email_verified INTEGER NOT NULL DEFAULT 1 CHECK(email_verified IN (0,1))')
        prod_cols = {r['name'] for r in c.execute('PRAGMA table_info(products)').fetchall()}
        if 'compare_price' not in prod_cols:
            c.execute('ALTER TABLE products ADD COLUMN compare_price INTEGER NOT NULL DEFAULT 0')
        if 'video_url' not in prod_cols:
            c.execute("ALTER TABLE products ADD COLUMN video_url TEXT NOT NULL DEFAULT ''")
        if 'min_quantity' not in prod_cols:
            c.execute('ALTER TABLE products ADD COLUMN min_quantity INTEGER NOT NULL DEFAULT 1')
        if 'max_quantity' not in prod_cols:
            c.execute('ALTER TABLE products ADD COLUMN max_quantity INTEGER NOT NULL DEFAULT 99')
        if 'has_variants' not in prod_cols:
            c.execute('ALTER TABLE products ADD COLUMN has_variants INTEGER NOT NULL DEFAULT 0')
        c.execute('''CREATE TABLE IF NOT EXISTS product_variants(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            compare_price INTEGER NOT NULL DEFAULT 0,
            stock INTEGER NOT NULL DEFAULT 0,
            position INTEGER NOT NULL DEFAULT 0
        )''')
        sess_cols = {r['name'] for r in c.execute('PRAGMA table_info(sessions)').fetchall()}
        if 'refresh_token' not in sess_cols:
            c.execute('ALTER TABLE sessions ADD COLUMN refresh_token TEXT')
        if 'absolute_expires' not in sess_cols:
            c.execute('ALTER TABLE sessions ADD COLUMN absolute_expires INTEGER')
        c.execute('DELETE FROM sessions WHERE rowid NOT IN (SELECT MAX(rowid) FROM sessions GROUP BY user_id)')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS sessions_single_user ON sessions(user_id)')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS sessions_refresh_unique ON sessions(refresh_token) WHERE refresh_token IS NOT NULL')
        c.execute("CREATE TABLE IF NOT EXISTS store_categories(slug TEXT PRIMARY KEY,name TEXT UNIQUE NOT NULL,title TEXT NOT NULL,image TEXT NOT NULL DEFAULT '',position INTEGER NOT NULL)")
        c.executemany('INSERT OR IGNORE INTO store_categories(slug,name,title,position) VALUES(?,?,?,?)',
                      [(slug, name, title, position) for position, (slug, name, title) in enumerate(CATEGORY_DEFAULTS)])
        c.execute("UPDATE store_categories SET title='Roblox' WHERE name='Contas Roblox' AND title='Contas Roblox'")
        legacy = data_dir/'store.db'
        if legacy.exists():
            os.chmod(legacy, 0o600)
        if not c.execute("SELECT 1 FROM metadata WHERE key='migrated'").fetchone():
            if legacy.exists():
                old = sqlite3.connect(f'file:{legacy}?mode=ro', uri=True)
                try:
                    c.executemany('INSERT INTO products(id,name,description,price,category,image) VALUES(?,?,?,?,?,?)', old.execute('SELECT * FROM products').fetchall())
                    row = old.execute("SELECT value FROM settings WHERE key='password'").fetchone()
                    if row:
                        c.execute("INSERT INTO users(email,password,role) VALUES('admin',?,'admin')", (row[0],))
                finally:
                    old.close()
            else:
                c.executemany('INSERT INTO products(name,description,price,category,image) VALUES(?,?,?,?,?)', [
                    ('iSeek • 30 dias', 'Acesso ao iSeek com duração de 30 dias.', 9000, 'Painel (login)', ''),
                    ('Mind-7 • 30 dias', 'Acesso ao Mind-7 com duração de 30 dias.', 2500, 'Painel (login)', '')])
            c.execute("INSERT INTO metadata VALUES('migrated','1')")
        for user in c.execute('SELECT id,email FROM users WHERE id NOT IN (SELECT user_id FROM user_profiles)').fetchall():
            c.execute('INSERT INTO user_profiles(user_id,nickname) VALUES(?,?)',(user['id'],default_nickname(user['email'])))
    os.chmod(db_path, 0o600)
    dummy_password = new_password(secrets.token_urlsafe(16)[:24])
    dummy_otp_hash = hmac.new(key.encode(), b'dummy-otp-comparison', hashlib.sha256).hexdigest()

    def otp_digest(email, code):
        return hmac.new(key.encode(), f'otp:{email}:{code}'.encode(), hashlib.sha256).hexdigest()

    def issue_otp(c, email, actor=None):
        code = f'{secrets.randbelow(1_000_000):06d}'
        now = int(time.time())
        c.execute('''INSERT INTO email_otps(email,code_hash,attempts,expires,sent_at) VALUES(?,?,0,?,?)
                     ON CONFLICT(email) DO UPDATE SET code_hash=excluded.code_hash,attempts=0,expires=excluded.expires,sent_at=excluded.sent_at''',
                  (email, otp_digest(email, code), now + OTP_TTL, now))
        audit(c, 'otp_issued', actor)
        return code

    def send_otp_email(email, code):
        sender_hook = app.extensions.get('otp_sender')
        if callable(sender_hook):
            sender_hook(email, code)
            return
        host = app.config.get('SMTP_HOST', '').strip()
        if not host:
            return
        port = int(app.config.get('SMTP_PORT') or 587)
        from_addr = (app.config.get('SMTP_FROM') or app.config.get('SMTP_USER') or 'no-reply@localhost').strip()
        msg = EmailMessage()
        msg['Subject'] = 'Seu código de verificação · NziStore'
        msg['From'] = from_addr
        msg['To'] = email
        msg.set_content(f'Seu código de verificação único da NziStore é: {code}\nEste código expira em 10 minutos e só pode ser utilizado uma vez.')
        try:
            with smtplib.SMTP(host, port, timeout=10) as smtp:
                if str(app.config.get('SMTP_TLS', '1')).lower() not in ('0', 'false', 'no'):
                    smtp.starttls()
                if app.config.get('SMTP_USER') and app.config.get('SMTP_PASSWORD'):
                    smtp.login(app.config['SMTP_USER'], app.config['SMTP_PASSWORD'])
                smtp.send_message(msg)
        except OSError:
            app.logger.error('Falha ao entregar e-mail de verificação via SMTP.')

    def audit(c, event, actor=None):
        c.execute('INSERT INTO audit(event,actor,created) VALUES(?,?,?)', (event, actor, int(time.time())))

    def limit(bucket, maximum, seconds):
        now = int(time.time())
        with db() as c:
            c.execute('DELETE FROM limits WHERE expires<=?', (now,))
            c.execute('INSERT INTO limits VALUES(?,1,?) ON CONFLICT(bucket) DO UPDATE SET count=count+1', (digest(bucket), now+seconds))
            row = c.execute('SELECT count FROM limits WHERE bucket=?', (digest(bucket),)).fetchone()
        if row['count'] > maximum:
            abort(429, 'Muitas requisições. Aguarde e tente novamente.')

    @app.before_request
    def protect():
        g.user = None
        g.session = None
        if not request.path.startswith('/api/'):
            return
        # Forwarded/CF headers are deliberately not trusted. Edge limits belong at the proxy.
        limit('all:' + (request.remote_addr or 'unknown'), 240, 60)
        if request.endpoint == 'commerce.mistic_callback':
            request.max_content_length = 16384
            if not request.is_json:
                abort(415)
            return
        if request.endpoint == 'upload':
            request.max_content_length = 16_000_000
        else:
            request.max_content_length = 65536
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if request.headers.get('Origin') not in allowed_origins or request.headers.get('Sec-Fetch-Site') == 'cross-site':
                abort(403, 'Origem inválida.')
            if not request.is_json:
                abort(415, 'Envie application/json.')
        token = request.cookies.get('session', '')
        if token:
            now = int(time.time())
            with db() as c:
                c.execute('DELETE FROM sessions WHERE COALESCE(absolute_expires, expires)<=?', (now,))
                c.execute('DELETE FROM used_refresh_tokens WHERE expires<=?', (now,))
                row = c.execute(
                    'SELECT s.*,u.role,u.email_verified FROM sessions s JOIN users u ON u.id=s.user_id '
                    'WHERE s.token=? AND s.expires>? AND COALESCE(s.absolute_expires, s.expires)>?',
                    (digest(token), now, now)
                ).fetchone()
                if row and row['role'] == 'admin' and not c.execute('SELECT 1 FROM admin_sessions WHERE token=?', (row['token'],)).fetchone():
                    row = None
                if row and not row['email_verified']:
                    row = None
            if row:
                g.session = dict(row)
                g.user = {'id': row['user_id'], 'role': row['role']}
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and g.session:
            if not hmac.compare_digest(request.headers.get('X-CSRF-Token', ''), g.session['csrf']):
                abort(403, 'Atualize a página e tente novamente.')

    @app.after_request
    def headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Permissions-Policy'] = 'camera=(), microphone=(), geolocation=()'
        response.headers['Cross-Origin-Opener-Policy'] = 'same-origin'
        response.headers['Cross-Origin-Resource-Policy'] = 'same-origin'
        response.headers['X-Permitted-Cross-Domain-Policies'] = 'none'
        if request.path.startswith('/uploads/'):
            response.headers['Content-Security-Policy'] = "default-src 'none'; style-src 'unsafe-inline'; sandbox"
        else:
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://*.rbxcdn.com; frame-src https://www.youtube.com https://www.youtube-nocookie.com https://streamable.com https://player.vimeo.com; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
        if request.path.startswith('/api/') or request.path in ('/dashboard', '/conta', '/pedidos'):
            response.headers['Cache-Control'] = 'no-store'
        if app.config['PRODUCTION']:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        if response.status_code == 429:
            response.headers.setdefault('Retry-After', '300')
        return response

    @app.errorhandler(HTTPException)
    def http_error(e):
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and 0 < (request.content_length or 0) <= 16_000_000:
            try:
                request.get_data(cache=False)
            except Exception:
                pass
        return jsonify(error=e.description), e.code

    @app.errorhandler(Exception)
    def unhandled_error(e):
        if isinstance(e, HTTPException):
            return jsonify(error=e.description), e.code
        app.logger.error('Erro interno em %s %s (%s)', request.method, request.path, type(e).__name__)
        return jsonify(error='Erro interno do servidor.'), 500

    def data():
        result = request.get_json(silent=True)
        if not isinstance(result, dict):
            abort(400, 'Dados inválidos.')
        return result

    def require_admin():
        if not g.user:
            abort(401, 'Entre no painel para continuar.')
        if g.user['role'] != 'admin':
            abort(403, 'Acesso restrito ao administrador.')

    def set_auth_cookies(response, access_token, refresh_token, max_age=SESSION_TTL):
        response.set_cookie('session', access_token, max_age=max_age, httponly=True,
                            secure=app.config['PRODUCTION'], samesite='Strict', path='/')
        response.set_cookie('refresh', refresh_token, max_age=max_age, httponly=True,
                            secure=app.config['PRODUCTION'], samesite='Strict', path='/')
        return response

    def clear_auth_cookies(response):
        response.delete_cookie('session', path='/', secure=app.config['PRODUCTION'], httponly=True, samesite='Strict')
        response.delete_cookie('refresh', path='/', secure=app.config['PRODUCTION'], httponly=True, samesite='Strict')
        return response

    def login_response(user, redirect_to=None):
        token, refresh, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        now = int(time.time())
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if g.session:
                c.execute('DELETE FROM sessions WHERE token=?', (g.session['token'],))
            c.execute('DELETE FROM sessions WHERE COALESCE(absolute_expires, expires)<=?', (now,))
            c.execute('DELETE FROM used_refresh_tokens WHERE expires<=?', (now,))
            revoked = c.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],)).rowcount
            c.execute('DELETE FROM used_refresh_tokens WHERE user_id=?', (user['id'],))
            if revoked:
                audit(c, 'session_replaced', user['id'])
            c.execute('INSERT INTO sessions(token,user_id,csrf,expires,refresh_token,absolute_expires) VALUES(?,?,?,?,?,?)',
                      (digest(token), user['id'], csrf, now + ACCESS_TTL, digest(refresh), now + SESSION_TTL))
            if user['role'] == 'admin':
                c.execute('INSERT INTO admin_sessions(token) VALUES(?)', (digest(token),))
            audit(c, 'login', user['id'])
        base = redirect(redirect_to, code=302) if redirect_to else jsonify(ok=True, csrf=csrf)
        return set_auth_cookies(base, token, refresh, SESSION_TTL)

    @app.get('/api/status')
    def status():
        limit('catalog:' + (request.remote_addr or ''), 120, 60)
        with db() as c:
            configured = bool(c.execute("SELECT 1 FROM users WHERE role='admin'").fetchone())
        return jsonify(configured=configured, authenticated=bool(g.user and g.user['role']=='admin'), csrf=g.session['csrf'] if g.session else None)

    @app.post('/api/setup')
    def setup():
        abort(403, 'Crie o administrador no terminal: .venv/bin/flask --app server create-admin')

    @app.post('/api/login')
    @app.post('/api/auth/login')
    def login():
        body = data()
        email = body.get('username', '') if request.path == '/api/login' else body.get('email', '')
        password = body.get('password', '')
        if not isinstance(email, str) or not isinstance(password, str) or len(email)>254 or len(password)>128:
            abort(400, 'Dados inválidos.')
        email = email.strip().lower()
        limit('login-ip:' + (request.remote_addr or ''), 10, 300)
        limit('login-account:' + email, 10, 300)
        with db() as c:
            row = c.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
        valid = verify(password, row['password'] if row else dummy_password)
        if not valid or not row or (request.path == '/api/login' and row['role'] != 'admin'):
            if row and row['role'] == 'admin':
                with db() as c:
                    audit(c, 'admin_login_failed', row['id'])
            abort(401, 'Credenciais inválidas.')
        if not row['email_verified']:
            otp_code = None
            now = int(time.time())
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                challenge = c.execute('SELECT sent_at, expires FROM email_otps WHERE email=?', (email,)).fetchone()
                if not challenge or challenge['expires'] <= now or (now - challenge['sent_at']) >= OTP_RESEND_COOLDOWN:
                    otp_code = issue_otp(c, email, row['id'])
            if otp_code:
                send_otp_email(email, otp_code)
            return jsonify(ok=True, verification_required=True), 200
        if row['role'] == 'admin':
            pin = body.get('pin', '')
            with db() as c:
                credential = c.execute('SELECT pin_hash FROM admin_credentials WHERE user_id=?', (row['id'],)).fetchone()
            pin_valid = isinstance(pin, str) and bool(re.fullmatch(r'[0-9]{6}', pin))
            verified = verify(pin if pin_valid else '', credential['pin_hash'] if credential else dummy_password)
            if not pin_valid or not credential or not verified:
                with db() as c:
                    audit(c, 'admin_login_failed', row['id'])
                abort(401, 'Credenciais inválidas. Configure usuário, senha e PIN pelo terminal se necessário.')
        return login_response(row)

    @app.post('/api/auth/register')
    def register():
        limit('register-global', 30, 3600)
        limit('register:' + (request.remote_addr or ''), 5, 3600)
        body = data()
        email = body.get('email', '')
        if not isinstance(email, str) or len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email.strip()):
            abort(400, 'Informe um e-mail válido.')
        email = email.strip().lower()
        hashed = new_password(body.get('password'))
        limit('otp-send-account:' + email, 5, 3600)
        limit('otp-cooldown:' + email, 1, OTP_RESEND_COOLDOWN)
        otp_code = None
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            existing = c.execute('SELECT id, email_verified, role FROM users WHERE email=?', (email,)).fetchone()
            if not existing:
                uid = c.execute("INSERT INTO users(email,password,role,email_verified) VALUES(?,?,'customer',0)", (email, hashed)).lastrowid
                c.execute('INSERT INTO user_profiles(user_id,nickname) VALUES(?,?)',(uid,default_nickname(email)))
                otp_code = issue_otp(c, email, uid)
                audit(c, 'register', uid)
            elif not existing['email_verified'] and existing['role'] == 'customer':
                c.execute('UPDATE users SET password=? WHERE id=?', (hashed, existing['id']))
                otp_code = issue_otp(c, email, existing['id'])
                audit(c, 'register_retry', existing['id'])
            else:
                audit(c, 'register_existing_attempt', existing['id'])
        if otp_code:
            send_otp_email(email, otp_code)
        return jsonify(ok=True, verification_required=True), 200

    @app.post('/api/auth/verify-otp')
    def verify_otp():
        limit('otp-verify-ip:' + (request.remote_addr or ''), 15, 900)
        body = data()
        email = body.get('email', '')
        otp = body.get('otp', '')
        if not isinstance(email, str) or len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email.strip()):
            abort(400, 'Informe o e-mail e o código de 6 dígitos.')
        if not isinstance(otp, str) or not re.fullmatch(r'[0-9]{6}', otp.strip()):
            abort(400, 'Informe o e-mail e o código de 6 dígitos.')
        email = email.strip().lower()
        otp = otp.strip()
        limit('otp-verify-account:' + email, 10, 900)
        expected = otp_digest(email, otp)
        now = int(time.time())
        verified = False
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM email_otps WHERE expires<=?', (now,))
            challenge = c.execute('SELECT * FROM email_otps WHERE email=?', (email,)).fetchone()
            user = c.execute("SELECT id, role, email_verified FROM users WHERE email=? AND role='customer'", (email,)).fetchone()
            matched = hmac.compare_digest(expected, challenge['code_hash'] if challenge else dummy_otp_hash)
            if challenge and user:
                if matched:
                    c.execute('DELETE FROM email_otps WHERE email=?', (email,))
                    c.execute('UPDATE users SET email_verified=1 WHERE id=?', (user['id'],))
                    audit(c, 'otp_verified', user['id'])
                    verified = True
                else:
                    attempts = challenge['attempts'] + 1
                    if attempts >= OTP_MAX_ATTEMPTS:
                        c.execute('DELETE FROM email_otps WHERE email=?', (email,))
                        audit(c, 'otp_max_attempts', user['id'])
                    else:
                        c.execute('UPDATE email_otps SET attempts=? WHERE email=?', (attempts, email))
                        audit(c, 'otp_failed', user['id'])
        if not verified:
            abort(400, 'Código inválido ou expirado.')
        return login_response(user)

    @app.post('/api/auth/resend-otp')
    def resend_otp():
        limit('otp-send-ip:' + (request.remote_addr or ''), 10, 3600)
        body = data()
        email = body.get('email', '')
        if not isinstance(email, str) or len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email.strip()):
            abort(400, 'Informe um e-mail válido.')
        email = email.strip().lower()
        limit('otp-send-account:' + email, 5, 3600)
        limit('otp-cooldown:' + email, 1, OTP_RESEND_COOLDOWN)
        otp_code = None
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            user = c.execute("SELECT id, email_verified, role FROM users WHERE email=?", (email,)).fetchone()
            if user and not user['email_verified'] and user['role'] == 'customer':
                otp_code = issue_otp(c, email, user['id'])
        if otp_code:
            send_otp_email(email, otp_code)
        return jsonify(ok=True, verification_required=True)

    @app.post('/api/auth/refresh')
    def refresh_session():
        limit('refresh-ip:' + (request.remote_addr or ''), 30, 300)
        data()
        refresh_cookie = request.cookies.get('refresh', '')
        if not refresh_cookie:
            abort(401, 'Sessão expirada. Entre novamente.')
        refresh_hash = digest(refresh_cookie)
        now = int(time.time())
        new_access, new_refresh, new_csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        rotated = False
        remaining_ttl = SESSION_TTL
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM sessions WHERE COALESCE(absolute_expires, expires)<=?', (now,))
            c.execute('DELETE FROM used_refresh_tokens WHERE expires<=?', (now,))
            used = c.execute('SELECT * FROM used_refresh_tokens WHERE token_hash=?', (refresh_hash,)).fetchone()
            if used:
                c.execute('DELETE FROM sessions WHERE user_id=?', (used['user_id'],))
                c.execute('DELETE FROM used_refresh_tokens WHERE user_id=?', (used['user_id'],))
                audit(c, 'refresh_token_reuse_detected', used['user_id'])
            else:
                row = c.execute(
                    'SELECT s.*,u.role,u.email_verified FROM sessions s JOIN users u ON u.id=s.user_id '
                    'WHERE s.refresh_token=? AND COALESCE(s.absolute_expires, s.expires)>?',
                    (refresh_hash, now)
                ).fetchone()
                if row and row['email_verified']:
                    if row['role'] == 'admin' and not c.execute('SELECT 1 FROM admin_sessions WHERE token=?', (row['token'],)).fetchone():
                        c.execute('DELETE FROM sessions WHERE token=?', (row['token'],))
                    else:
                        abs_exp = row['absolute_expires'] or (now + SESSION_TTL)
                        new_exp = min(now + ACCESS_TTL, abs_exp)
                        c.execute('INSERT INTO used_refresh_tokens(token_hash,user_id,expires) VALUES(?,?,?)',
                                  (refresh_hash, row['user_id'], abs_exp))
                        c.execute('UPDATE sessions SET token=?,refresh_token=?,csrf=?,expires=? WHERE user_id=?',
                                  (digest(new_access), digest(new_refresh), new_csrf, new_exp, row['user_id']))
                        if row['role'] == 'admin':
                            c.execute('DELETE FROM admin_sessions WHERE token=?', (row['token'],))
                            c.execute('INSERT INTO admin_sessions(token) VALUES(?)', (digest(new_access),))
                        audit(c, 'token_rotated', row['user_id'])
                        rotated = True
                        remaining_ttl = max(1, abs_exp - now)
        if not rotated:
            return clear_auth_cookies(jsonify(error='Sessão expirada ou revogada.')), 401
        return set_auth_cookies(jsonify(ok=True, authenticated=True, csrf=new_csrf), new_access, new_refresh, remaining_ttl)

    def profile_json(c):
        user=c.execute('SELECT email FROM users WHERE id=?',(g.user['id'],)).fetchone()
        profile=c.execute('SELECT nickname,changed_at FROM user_profiles WHERE user_id=?',(g.user['id'],)).fetchone()
        return dict(email=user['email'],nickname=profile['nickname'] if profile else default_nickname(user['email']),
                    nickname_change_available_at=profile['changed_at']+86400 if profile and profile['changed_at'] else 0)

    @app.post('/api/auth/profile')
    def update_profile():
        if not g.user: abort(401,'Entre na sua conta.')
        limit('profile-attempt:'+str(g.user['id']),20,60)
        body=data();nickname=body.get('nickname')
        if set(body)!={'nickname'} or not isinstance(nickname,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{2,31}',nickname):
            abort(400,'Use de 3 a 32 caracteres: letras, números, ponto, hífen ou sublinhado. Comece com letra ou número.')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            profile=profile_json(c)
            if nickname==profile['nickname']: return jsonify(**profile)
            now=int(time.time());available=profile['nickname_change_available_at']
            if now<available:
                response=jsonify(error='Você pode alterar o nome de usuário uma vez a cada 24 horas.',nickname_change_available_at=available)
                response.status_code=429;response.headers['Retry-After']=str(available-now)
                return response
            c.execute('INSERT INTO user_profiles(user_id,nickname,changed_at) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET nickname=excluded.nickname,changed_at=excluded.changed_at',(g.user['id'],nickname,now))
            audit(c,'nickname_changed',g.user['id'])
            return jsonify(**profile_json(c))

    @app.get('/api/auth/me')
    def me():
        if not g.user:
            abort(401, 'Entre na sua conta.')
        with db() as c:
            profile = profile_json(c)
        return jsonify(authenticated=True, csrf=g.session['csrf'], **profile)

    @app.post('/api/logout')
    @app.post('/api/auth/logout')
    def logout():
        if g.session:
            with db() as c:
                c.execute('DELETE FROM sessions WHERE token=?', (g.session['token'],))
                c.execute('DELETE FROM used_refresh_tokens WHERE user_id=?', (g.user['id'],))
                audit(c, 'logout', g.user['id'])
        return clear_auth_cookies(jsonify(ok=True))

    @app.post('/api/auth/password')
    def change_password():
        if not g.user:
            abort(401)
        limit('password:' + str(g.user['id']), 5, 300)
        body = data()
        current = body.get('currentPassword', '')
        if not isinstance(current, str) or len(current)>128:
            abort(400)
        new_hashed = new_password(body.get('password'))
        valid = False
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT password FROM users WHERE id=?', (g.user['id'],)).fetchone()
            if row and verify(current, row['password']):
                c.execute('UPDATE users SET password=? WHERE id=?', (new_hashed, g.user['id']))
                c.execute('DELETE FROM sessions WHERE user_id=?', (g.user['id'],))
                c.execute('DELETE FROM used_refresh_tokens WHERE user_id=?', (g.user['id'],))
                audit(c, 'password_changed', g.user['id'])
                valid = True
        if not valid:
            abort(401, 'Credenciais inválidas.')
        return clear_auth_cookies(jsonify(ok=True))

    def oauth_provider_ready(provider):
        if provider == 'google':
            return bool(app.config.get('GOOGLE_CLIENT_ID', '').strip() and app.config.get('GOOGLE_CLIENT_SECRET', '').strip())
        if provider == 'discord':
            return bool(app.config.get('DISCORD_CLIENT_ID', '').strip() and app.config.get('DISCORD_CLIENT_SECRET', '').strip())
        return False

    @app.get('/api/auth/oauth/providers')
    def oauth_providers():
        limit('catalog:' + (request.remote_addr or ''), 120, 60)
        return jsonify(google=oauth_provider_ready('google'), discord=oauth_provider_ready('discord'))

    @app.post('/api/auth/forgot-password')
    def forgot_password():
        body=data();email=body.get('email','')
        if not isinstance(email,str) or len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email):abort(400,'Informe um e-mail válido.')
        email=email.strip().lower()
        limit('reset-ip:'+(request.remote_addr or ''),10,3600)
        limit('reset-email:'+email,1,60)
        code=None;now=int(time.time())
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM password_resets WHERE expires<=?',(now,))
            user=c.execute("SELECT id FROM users WHERE email=? AND role='customer' AND email_verified=1",(email,)).fetchone()
            if user:
                code=f'{secrets.randbelow(1000000):06d}'
                hashed=hmac.new(key.encode(),('reset:'+email+':'+code).encode(),hashlib.sha256).hexdigest()
                c.execute('INSERT OR REPLACE INTO password_resets VALUES(?,?,0,?)',(email,hashed,now+600))
                audit(c,'password_reset_requested',user['id'])
        if code:send_otp_email(email,code)
        return jsonify(ok=True,message='Se houver uma conta elegível, enviaremos um código por e-mail. Confira também o spam.')

    @app.post('/api/auth/reset-password')
    def reset_password():
        body=data();email=body.get('email','');code=body.get('code','')
        if not isinstance(email,str) or len(email)>254 or not isinstance(code,str) or not re.fullmatch('[0-9]{6}',code):abort(400,'Código ou e-mail inválido.')
        email=email.strip().lower();limit('reset-verify:'+(request.remote_addr or ''),20,3600)
        hashed_password=new_password(body.get('password'));now=int(time.time());valid=False
        expected=hmac.new(key.encode(),('reset:'+email+':'+code).encode(),hashlib.sha256).hexdigest()
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT * FROM password_resets WHERE email=? AND expires>?',(email,now)).fetchone()
            user=c.execute("SELECT id FROM users WHERE email=? AND role='customer' AND email_verified=1",(email,)).fetchone()
            if row and user and hmac.compare_digest(expected,row['code_hash']):
                c.execute('UPDATE users SET password=? WHERE id=?',(hashed_password,user['id']))
                c.execute('DELETE FROM sessions WHERE user_id=?',(user['id'],))
                c.execute('DELETE FROM used_refresh_tokens WHERE user_id=?',(user['id'],))
                c.execute('DELETE FROM password_resets WHERE email=?',(email,))
                audit(c,'password_reset_completed',user['id']);valid=True
            elif row:
                if row['attempts']>=4:c.execute('DELETE FROM password_resets WHERE email=?',(email,))
                else:c.execute('UPDATE password_resets SET attempts=attempts+1 WHERE email=?',(email,))
        if not valid:abort(400,'Código inválido ou expirado. Solicite outro código.')
        return clear_auth_cookies(jsonify(ok=True))

    @app.get('/api/auth/oauth/<provider>/start')
    def oauth_start(provider):
        if provider not in ('google', 'discord'):
            abort(404)
        limit('oauth-start:' + (request.remote_addr or ''), 20, 300)
        if not oauth_provider_ready(provider):
            return redirect(f'/conta?oauth_error=not_configured&provider={provider}', code=302)
        state = secrets.token_urlsafe(32)
        verifier = secrets.token_urlsafe(48)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        now = int(time.time())
        with db() as c:
            c.execute('DELETE FROM oauth_states WHERE expires<=?', (now,))
            c.execute('INSERT INTO oauth_states(state_hash,provider,verifier,expires) VALUES(?,?,?,?)',
                      (digest(state), provider, verifier, now + 600))
        redirect_uri = f"{origin.rstrip('/')}/api/auth/oauth/{provider}/callback"
        if provider == 'google':
            params = {
                'client_id': app.config['GOOGLE_CLIENT_ID'].strip(),
                'redirect_uri': redirect_uri,
                'response_type': 'code',
                'scope': 'openid email profile',
                'state': state,
                'code_challenge': challenge,
                'code_challenge_method': 'S256',
                'prompt': 'select_account',
            }
            target_url = 'https://accounts.google.com/o/oauth2/v2/auth?' + urlencode(params)
        else:
            params = {
                'client_id': app.config['DISCORD_CLIENT_ID'].strip(),
                'redirect_uri': redirect_uri,
                'response_type': 'code',
                'scope': 'identify email',
                'state': state,
                'code_challenge': challenge,
                'code_challenge_method': 'S256',
                'prompt': 'none',
            }
            target_url = 'https://discord.com/oauth2/authorize?' + urlencode(params)
        resp = redirect(target_url, code=302)
        resp.set_cookie('oauth_state', state, max_age=600, httponly=True,
                        secure=app.config['PRODUCTION'], samesite='Lax', path='/api/auth/oauth')
        return resp

    def fetch_oauth_identity(provider, code, verifier, redirect_uri):
        hook = app.extensions.get('oauth_exchange')
        if callable(hook):
            return hook(provider, code, verifier, redirect_uri)
        if provider == 'google':
            token_url = 'https://oauth2.googleapis.com/token'
            user_url = 'https://openidconnect.googleapis.com/v1/userinfo'
            client_id = app.config['GOOGLE_CLIENT_ID'].strip()
            client_secret = app.config['GOOGLE_CLIENT_SECRET'].strip()
        else:
            token_url = 'https://discord.com/api/v10/oauth2/token'
            user_url = 'https://discord.com/api/v10/users/@me'
            client_id = app.config['DISCORD_CLIENT_ID'].strip()
            client_secret = app.config['DISCORD_CLIENT_SECRET'].strip()
        payload = urlencode({
            'client_id': client_id,
            'client_secret': client_secret,
            'code': code,
            'code_verifier': verifier,
            'grant_type': 'authorization_code',
            'redirect_uri': redirect_uri,
        }).encode()
        req = urllib.request.Request(
            token_url,
            data=payload,
            headers={'Content-Type': 'application/x-www-form-urlencoded', 'Accept': 'application/json', 'User-Agent': 'NziStore/1.0'}
        )
        with urllib.request.urlopen(req, timeout=10) as res:
            token_data = json.loads(res.read(65536))
        access_token = token_data.get('access_token', '')
        if not isinstance(access_token, str) or not access_token:
            raise ValueError('Token ausente.')
        ureq = urllib.request.Request(
            user_url,
            headers={'Authorization': f'Bearer {access_token}', 'Accept': 'application/json', 'User-Agent': 'NziStore/1.0'}
        )
        with urllib.request.urlopen(ureq, timeout=10) as ures:
            profile = json.loads(ures.read(65536))
        if provider == 'google':
            return {
                'id': str(profile.get('sub') or '').strip(),
                'email': str(profile.get('email') or '').strip().lower(),
                'verified': bool(profile.get('email_verified') is True),
            }
        return {
            'id': str(profile.get('id') or '').strip(),
            'email': str(profile.get('email') or '').strip().lower(),
            'verified': bool(profile.get('verified') is True),
        }

    @app.get('/api/auth/oauth/<provider>/callback')
    def oauth_callback(provider):
        if provider not in ('google', 'discord'):
            abort(404)
        limit('oauth-cb:' + (request.remote_addr or ''), 20, 300)

        def fail_redirect(reason):
            r = redirect(f'/conta?oauth_error={reason}&provider={provider}', code=302)
            r.delete_cookie('oauth_state', path='/api/auth/oauth', secure=app.config['PRODUCTION'], httponly=True, samesite='Lax')
            return r

        if not oauth_provider_ready(provider):
            return fail_redirect('not_configured')
        if request.args.get('error'):
            return fail_redirect('cancelled')
        code = request.args.get('code', '').strip()
        state = request.args.get('state', '').strip()
        cookie_state = request.cookies.get('oauth_state', '').strip()
        if not code or not state or not cookie_state or len(code) > 2048 or len(state) > 256:
            return fail_redirect('invalid_state')
        if not hmac.compare_digest(state, cookie_state):
            return fail_redirect('invalid_state')
        now = int(time.time())
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM oauth_states WHERE expires<=?', (now,))
            st = c.execute('SELECT * FROM oauth_states WHERE state_hash=? AND provider=? AND expires>?',
                           (digest(state), provider, now)).fetchone()
            if st:
                c.execute('DELETE FROM oauth_states WHERE state_hash=?', (digest(state),))
        if not st:
            return fail_redirect('invalid_state')
        redirect_uri = f"{origin.rstrip('/')}/api/auth/oauth/{provider}/callback"
        try:
            identity = fetch_oauth_identity(provider, code, st['verifier'], redirect_uri)
        except Exception:
            return fail_redirect('exchange_failed')
        provider_uid = str(identity.get('id') or '').strip()
        email = str(identity.get('email') or '').strip().lower()
        verified = bool(identity.get('verified') is True)
        if not provider_uid or len(provider_uid) > 128 or not email or len(email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
            return fail_redirect('exchange_failed')
        if not verified:
            return fail_redirect('unverified_email')
        user_row = None
        forbidden_admin = False
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            linked = c.execute('SELECT user_id FROM oauth_accounts WHERE provider=? AND provider_user_id=?',
                               (provider, provider_uid)).fetchone()
            if linked:
                user_row = c.execute('SELECT * FROM users WHERE id=?', (linked['user_id'],)).fetchone()
            if not user_row:
                user_row = c.execute('SELECT * FROM users WHERE email=?', (email,)).fetchone()
            if user_row and user_row['role'] == 'admin':
                audit(c, 'oauth_admin_blocked', user_row['id'])
                forbidden_admin = True
            elif not user_row:
                random_pw = new_password(secrets.token_urlsafe(16)[:24])
                uid = c.execute("INSERT INTO users(email,password,role,email_verified) VALUES(?,?,'customer',1)",
                                (email, random_pw)).lastrowid
                c.execute('INSERT INTO user_profiles(user_id,nickname) VALUES(?,?)', (uid, default_nickname(email)))
                c.execute('INSERT INTO oauth_accounts(provider,provider_user_id,user_id,email,created) VALUES(?,?,?,?,?)',
                          (provider, provider_uid, uid, email, now))
                audit(c, f'oauth_register_{provider}', uid)
                user_row = {'id': uid, 'role': 'customer', 'email': email, 'email_verified': 1}
            else:
                uid = user_row['id']
                if not user_row['email_verified']:
                    c.execute('UPDATE users SET email_verified=1 WHERE id=?', (uid,))
                    c.execute('DELETE FROM email_otps WHERE email=?', (email,))
                c.execute('''INSERT INTO oauth_accounts(provider,provider_user_id,user_id,email,created) VALUES(?,?,?,?,?)
                             ON CONFLICT(provider,provider_user_id) DO UPDATE SET user_id=excluded.user_id,email=excluded.email''',
                          (provider, provider_uid, uid, email, now))
                audit(c, f'oauth_login_{provider}', uid)
                user_row = {'id': uid, 'role': user_row['role'], 'email': user_row['email'], 'email_verified': 1}
        if forbidden_admin:
            return fail_redirect('admin_forbidden')
        resp = login_response(user_row, redirect_to='/conta')
        resp.delete_cookie('oauth_state', path='/api/auth/oauth', secure=app.config['PRODUCTION'], httponly=True, samesite='Lax')
        return resp

    @app.get('/api/roblox/user')
    def roblox_user():
        username = request.args.get('username', '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_]{3,20}', username):
            abort(400, 'Informe o username do Roblox, com 3 a 20 caracteres.')
        limit('roblox:' + (request.remote_addr or ''), 8, 60)
        limit('roblox-global', 30, 60)
        def fetch_json(url, payload=None):
            req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload else None,
                                         headers={'Content-Type': 'application/json', 'User-Agent': 'NziStore/1.0'})
            with urllib.request.urlopen(req, timeout=8) as response:
                return json.loads(response.read(200000))
        try:
            users = fetch_json('https://users.roblox.com/v1/usernames/users',
                               {'usernames': [username], 'excludeBannedUsers': True}).get('data', [])
            if not users:
                abort(404, 'Usuário não encontrado. Use o @username, não o nome de exibição.')
            user = users[0]
            user_id = int(user['id'])
            thumbnails = fetch_json(f'https://thumbnails.roblox.com/v1/users/avatar?userIds={user_id}&size=420x420&format=Png&isCircular=false').get('data', [])
            avatar = thumbnails[0].get('imageUrl') if thumbnails else None
            parsed = urlsplit(avatar or '')
            if parsed.scheme != 'https' or not (parsed.hostname or '').endswith('.rbxcdn.com'):
                avatar = None
            recipient = dict(id=user_id, username=user['name'], displayName=user['displayName'])
            return jsonify(**recipient, avatar=avatar, ticket=app.extensions['roblox_signer'].dumps(recipient))
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, TypeError):
            abort(503, 'O Roblox está indisponível no momento. Tente novamente em instantes.')

    @app.get('/api/roblox/subcategories')
    def subcategories():
        with db() as c:
            return jsonify([dict(r) for r in c.execute('SELECT id,slug,title,image FROM roblox_subcategories ORDER BY title,id')])

    @app.post('/api/admin/roblox/subcategories')
    @app.route('/api/admin/roblox/subcategories/<int:subcategory_id>',methods=['PUT','DELETE'])
    def edit_subcategory(subcategory_id=None):
        require_admin();limit('admin:'+str(g.user['id']),60,60);body=data()
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            old=c.execute('SELECT * FROM roblox_subcategories WHERE id=?',(subcategory_id,)).fetchone()
            if subcategory_id is not None and not old: abort(404)
            if request.method=='DELETE':
                if c.execute('SELECT 1 FROM product_subcategories WHERE subcategory_id=?',(subcategory_id,)).fetchone():abort(409,'Mova os produtos deste jogo antes de excluir.')
                c.execute('DELETE FROM roblox_subcategories WHERE id=?',(subcategory_id,))
            else:
                title,image=body.get('title'),body.get('image','')
                if not isinstance(title,str) or not 1<=len(title.strip())<=60:abort(400,'Informe um nome de até 60 caracteres.')
                if not isinstance(image,str) or (image and (not re.fullmatch(r'/uploads/[a-f0-9]{32}\.webp',image) or not (uploads/image.rsplit('/',1)[1]).is_file())):abort(400,'Envie a imagem pelo painel.')
                if old:c.execute('UPDATE roblox_subcategories SET title=?,image=? WHERE id=?',(title.strip(),image,subcategory_id))
                else:
                    base=re.sub('[^a-z0-9]+','-',unicodedata.normalize('NFKD',title).encode('ascii','ignore').decode().lower()).strip('-')[:60] or 'jogo'
                    slug=base
                    if c.execute('SELECT 1 FROM roblox_subcategories WHERE slug=?',(slug,)).fetchone():slug=base+'-'+secrets.token_hex(3)
                    subcategory_id=c.execute('INSERT INTO roblox_subcategories(slug,title,image) VALUES(?,?,?)',(slug,title.strip(),image)).lastrowid
            audit(c,'subcategory_'+request.method.lower(),g.user['id'])
        return jsonify(ok=True,id=subcategory_id)

    from insights import install_insights
    install_insights(app,db,key,data,limit)

    @app.get('/api/categories')
    def categories():
        limit('catalog:' + (request.remote_addr or ''), 120, 60)
        with db() as c:
            return jsonify([dict(r) for r in c.execute('SELECT slug,name,title,image FROM store_categories ORDER BY position')])

    @app.put('/api/admin/categories/<slug>')
    def edit_category(slug):
        require_admin()
        limit('admin:' + str(g.user['id']), 60, 60)
        body = data()
        title, image = body.get('title'), body.get('image', '')
        if not isinstance(title, str) or not 1 <= len(title.strip()) <= 60:
            abort(400, 'Informe um nome de até 60 caracteres.')
        if not isinstance(image, str) or (image and (not re.fullmatch(r'/uploads/[a-f0-9]{32}\.webp', image)
                or not (uploads/image.rsplit('/', 1)[1]).is_file())):
            abort(400, 'Envie a imagem da categoria pelo painel.')
        with db() as c:
            result = c.execute('UPDATE store_categories SET title=?,image=? WHERE slug=?', (title.strip(), image, slug))
            if not result.rowcount:
                abort(404, 'Categoria não encontrada.')
            audit(c, 'category_updated', g.user['id'])
        return jsonify(ok=True)

    @app.get('/api/admin/audit')
    def admin_audit():
        require_admin()
        limit('admin:' + str(g.user['id']), 60, 60)
        with db() as c:
            events = [dict(r) for r in c.execute('SELECT id,event,actor,created FROM audit ORDER BY id DESC LIMIT 100')]
        return jsonify(events=events)

    def normalize_video_url(raw):
        if raw is None:
            return ''
        if not isinstance(raw, str) or len(raw.strip()) > 500:
            abort(400, 'Link de vídeo inválido.')
        url = raw.strip()
        if not url:
            return ''
        yt = re.fullmatch(
            r'https://(?:(?:www\.|m\.)?youtube(?:-nocookie)?\.com/(?:watch\?v=|embed/|shorts/)|youtu\.be/)([A-Za-z0-9_-]{6,20})(?:[?&][^\s]*)?',
            url
        )
        if yt:
            return f'https://www.youtube-nocookie.com/embed/{yt.group(1)}'
        st = re.fullmatch(r'https://(?:www\.)?streamable\.com/(?:e/)?([A-Za-z0-9_-]{3,24})(?:[/?#][^\s]*)?', url)
        if st:
            return f'https://streamable.com/e/{st.group(1)}'
        vm = re.fullmatch(r'https://(?:(?:www\.)?vimeo\.com/|player\.vimeo\.com/video/)([0-9]{5,20})(?:[/?#][^\s]*)?', url)
        if vm:
            return f'https://player.vimeo.com/video/{vm.group(1)}'
        abort(400, 'Use um link HTTPS válido do YouTube, Streamable ou Vimeo.')

    @app.get('/api/products')
    def products():
        limit('catalog:' + (request.remote_addr or ''), 120, 60)
        with db() as c:
            rows = [dict(r) for r in c.execute("""
                SELECT p.id,p.name,p.description,p.price,p.compare_price,p.video_url,
                       p.min_quantity,p.max_quantity,p.has_variants,p.category,p.image,
                       COALESCE(d.mode,'manual') AS delivery_mode,s.subcategory_id,
                       (SELECT COUNT(*) FROM delivery_stock ds WHERE ds.product_id=p.id AND ds.item_id IS NULL) AS available_stock
                FROM products p
                LEFT JOIN product_delivery d ON d.product_id=p.id
                LEFT JOIN product_subcategories s ON s.product_id=p.id
                ORDER BY p.id DESC
            """)]
            variants_by_product = {}
            for v in c.execute('SELECT id,product_id,name,price,compare_price,stock,position FROM product_variants ORDER BY product_id,position,id'):
                variants_by_product.setdefault(v['product_id'], []).append(dict(v))
            for r in rows:
                r['has_variants'] = bool(r['has_variants'])
                r['variants'] = variants_by_product.get(r['id'], [])
            return jsonify(rows)

    @app.post('/api/products')
    @app.route('/api/products/<int:product_id>', methods=['PUT', 'DELETE'])
    def mutate_product(product_id=None):
        require_admin()
        limit('admin:' + str(g.user['id']), 60, 60)
        body = data()
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if product_id is not None and not c.execute('SELECT 1 FROM products WHERE id=?', (product_id,)).fetchone():
                abort(404)
            if request.method == 'DELETE':
                if c.execute('SELECT 1 FROM order_items WHERE product_id=? LIMIT 1', (product_id,)).fetchone() or c.execute('SELECT 1 FROM delivery_stock WHERE product_id=? LIMIT 1', (product_id,)).fetchone():
                    abort(409, 'Este produto tem pedidos ou estoque vinculado e não pode ser excluído.')
                c.execute('DELETE FROM products WHERE id=?', (product_id,))
            else:
                name, description, price, category, image = [body.get(k) for k in ('name','description','price','category','image')]
                has_variants = body.get('has_variants', False)
                if type(has_variants) is not bool:
                    abort(400, 'Tipo de produto inválido.')
                raw_variants = body.get('variants', [])
                if not isinstance(raw_variants, list) or len(raw_variants) > 30:
                    abort(400, 'Lista de variações inválida.')
                cleaned_variants = []
                if has_variants:
                    if not raw_variants:
                        abort(400, 'Adicione pelo menos uma variação para produto com variações.')
                    for idx, v in enumerate(raw_variants):
                        if not isinstance(v, dict):
                            abort(400, 'Variação inválida.')
                        v_name = v.get('name')
                        v_price = v.get('price')
                        v_compare = v.get('compare_price', 0)
                        v_stock = v.get('stock', 0)
                        if not isinstance(v_name, str) or not 1 <= len(v_name.strip()) <= 120:
                            abort(400, 'Informe o nome de cada variação (até 120 caracteres).')
                        if type(v_price) is not int or not 0 < v_price <= 100000000:
                            abort(400, 'Preço real inválido em uma das variações.')
                        if type(v_compare) is not int or not 0 <= v_compare <= 100000000 or (v_compare > 0 and v_compare <= v_price):
                            abort(400, 'O preço de comparação da variação deve ser maior que o preço real.')
                        if type(v_stock) is not int or not 0 <= v_stock <= 100000:
                            abort(400, 'Estoque da variação inválido.')
                        cleaned_variants.append((v_name.strip(), v_price, v_compare, v_stock, idx))
                    if type(price) is not int or price <= 0:
                        price = cleaned_variants[0][1]
                if not isinstance(name,str) or not 1<=len(name.strip())<=120 or not isinstance(description,str) or len(description)>5000:
                    abort(400, 'Nome ou descrição inválidos.')
                if type(price) is not int or not 0<price<=100000000 or category not in CATEGORIES:
                    abort(400, 'Preço ou categoria inválidos.')
                compare_price = body.get('compare_price', 0)
                if has_variants and (type(compare_price) is not int or compare_price <= 0):
                    compare_price = cleaned_variants[0][2] if cleaned_variants[0][2] > price else 0
                if type(compare_price) is not int or not 0 <= compare_price <= 100000000 or (compare_price > 0 and compare_price <= price):
                    abort(400, 'O preço de comparação deve ser maior que o preço real.')
                video_url = normalize_video_url(body.get('video_url', ''))
                min_quantity = body.get('min_quantity', 1)
                max_quantity = body.get('max_quantity', 99)
                if type(min_quantity) is not int or type(max_quantity) is not int or not 1 <= min_quantity <= max_quantity <= 99:
                    abort(400, 'Quantidade mínima e máxima devem estar entre 1 e 99.')
                if not isinstance(image,str) or (image and (not re.fullmatch(r'/uploads/[a-f0-9]{32}\.webp',image) or not (uploads/image.rsplit('/',1)[1]).is_file())):
                    # Existing legacy images may be retained, but no arbitrary path can be introduced.
                    old = c.execute('SELECT image FROM products WHERE id=?',(product_id,)).fetchone() if product_id else None
                    if not old or old['image'] != image:
                        abort(400, 'Envie a imagem pelo painel.')
                existing_delivery = c.execute('SELECT * FROM product_delivery WHERE product_id=?', (product_id,)).fetchone()
                mode = body.get('delivery_mode', existing_delivery['mode'] if existing_delivery else 'manual')
                robux_quantity = body.get('robux_quantity', existing_delivery['robux_quantity'] if existing_delivery else 0)
                if mode not in ('manual', 'automatic') or type(robux_quantity) is not int or not 0 <= robux_quantity <= 1000000000:
                    abort(400, 'Configuração de entrega inválida.')
                if category != 'Robux':
                    robux_quantity = 0
                subcategory_id=body.get('subcategory_id')
                if subcategory_id is not None and (type(subcategory_id) is not int or category!='Contas Roblox' or not c.execute('SELECT 1 FROM roblox_subcategories WHERE id=?',(subcategory_id,)).fetchone()):abort(400,'Selecione um jogo válido da categoria Roblox.')
                values = (name.strip(), description, price, compare_price, video_url, min_quantity, max_quantity, int(has_variants), category, image)
                if product_id is None:
                    product_id = c.execute(
                        'INSERT INTO products(name,description,price,compare_price,video_url,min_quantity,max_quantity,has_variants,category,image) VALUES(?,?,?,?,?,?,?,?,?,?)',
                        values
                    ).lastrowid
                else:
                    c.execute(
                        'UPDATE products SET name=?,description=?,price=?,compare_price=?,video_url=?,min_quantity=?,max_quantity=?,has_variants=?,category=?,image=? WHERE id=?',
                        values + (product_id,)
                    )
                c.execute('DELETE FROM product_variants WHERE product_id=?', (product_id,))
                if has_variants and cleaned_variants:
                    c.executemany(
                        'INSERT INTO product_variants(product_id,name,price,compare_price,stock,position) VALUES(?,?,?,?,?,?)',
                        [(product_id, vn, vp, vc, vs, pos) for vn, vp, vc, vs, pos in cleaned_variants]
                    )
                c.execute('DELETE FROM product_subcategories WHERE product_id=?',(product_id,))
                if subcategory_id is not None:c.execute('INSERT INTO product_subcategories VALUES(?,?)',(product_id,subcategory_id))
                c.execute('INSERT INTO product_delivery(product_id,mode,robux_quantity) VALUES(?,?,?) ON CONFLICT(product_id) DO UPDATE SET mode=excluded.mode,robux_quantity=excluded.robux_quantity', (product_id, mode, robux_quantity))
            audit(c, 'product_' + request.method.lower(), g.user['id'])
        return jsonify(ok=True, id=product_id)

    @app.post('/api/upload')
    def upload():
        require_admin()
        limit('upload:' + str(g.user['id']), 60, 3600)
        body = data()
        try:
            raw = base64.b64decode(body.get('data',''), validate=True)
            if len(raw)>10_000_000:
                abort(413, 'A imagem deve ter no máximo 10 MB.')
            with Image.open(io.BytesIO(raw)) as img:
                if img.format not in ('PNG','JPEG','WEBP','MPO') or img.width*img.height>36_000_000:
                    abort(400, 'Imagem inválida ou grande demais.')
                img.load()
                transposed = ImageOps.exif_transpose(img)
                rgba = transposed.convert('RGBA')
                if rgba.width > 1920 or rgba.height > 1920:
                    rgba.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
                name = secrets.token_hex(16)+'.webp'
                target = uploads/name
                rgba.save(target, 'WEBP', quality=88)
                os.chmod(target, 0o600)
        except (ValueError, TypeError, OSError, UnidentifiedImageError, Image.DecompressionBombError):
            abort(400, 'Envie uma imagem PNG, JPG ou WebP válida.')
        with db() as c:
            audit(c, 'image_uploaded', g.user['id'])
        return jsonify(url='/uploads/'+name)

    @app.get('/')
    @app.get('/checkout')
    @app.get('/terms')
    def home():
        return send_from_directory(ROOT/'templates', 'index.html')

    @app.get('/roblox')
    @app.get('/roblox/<slug>')
    def roblox_page(slug=None):
        if slug:
            with db() as c:
                if not c.execute('SELECT 1 FROM roblox_subcategories WHERE slug=?',(slug,)).fetchone():abort(404)
        return send_from_directory(ROOT/'templates','index.html')

    @app.get('/<category_slug>')
    def category_page(category_slug):
        if category_slug not in {'robux', 'painel', 'streaming', 'contas-discord', 'contas-roblox'}:
            abort(404)
        return send_from_directory(ROOT/'templates', 'index.html')

    @app.get('/produto/<int:product_id>')
    def product_page(product_id):
        with db() as c:
            if not c.execute('SELECT 1 FROM products WHERE id=?', (product_id,)).fetchone():
                abort(404)
        return send_from_directory(ROOT/'templates', 'index.html')

    @app.get('/dashboard')
    def dashboard():
        return send_from_directory(ROOT/'templates','dashboard.html')

    @app.get('/pagamento/<order_id>')
    def payment_page(order_id):
        if not re.fullmatch(r'[a-f0-9]{32}',order_id):abort(404)
        response=send_from_directory(ROOT/'templates','payment.html')
        response.headers['Cache-Control']='no-store'
        return response

    @app.get('/pedidos')
    def orders_page():
        return send_from_directory(ROOT/'templates', 'orders.html')

    @app.get('/conta')
    def account():
        return send_from_directory(ROOT/'templates','account.html')

    @app.get('/static/<path:filename>')
    def static_file(filename):
        allowed = {'icon-coupon.png','icon-secure.png','payment.js','payment.css','celebrations.js','icon-delivery.png','icon-support.png','icon-pix.png','icon-thunder.png','home-banner.png','admin.js','account.js','store.js','style.css','store.css','pix.png','cards.png','orders.js','orders.css','nzi-logo.png','halloween.gif','halloween.css','halloween.js','experience.js','experience.css','constellation.js','admin-workspace.js','admin-workspace.css','brazil-states.json','admin-icon-chart-histogram.png','admin-icon-shopping-bag.png','admin-icon-comment-alt.png','admin-icon-shopping-cart.png','admin-icon-user.png','admin-icon-star.png'}
        if filename not in allowed:
            abort(404)
        return send_from_directory(ROOT/'static',filename)

    @app.get('/uploads/<filename>')
    def uploaded_file(filename):
        if not re.fullmatch(r'[a-f0-9]{32}\.(?:webp|png|jpg)',filename):
            abort(404)
        return send_from_directory(uploads,filename)

    import click
    @app.cli.command('create-admin')
    @click.option('--username', prompt='Usuário do administrador')
    @click.password_option(confirmation_prompt=True)
    @click.option('--pin', prompt='PIN de seis dígitos', hide_input=True, confirmation_prompt=True)
    def create_admin(username, password, pin):
        """Configure the single administrator locally and revoke previous sessions."""
        username = username.strip().lower()
        if not re.fullmatch(r'[a-z0-9_.@-]{3,64}', username):
            raise click.ClickException('Usuário deve ter de 3 a 64 caracteres: letras, números, _, ., @ ou -.')
        try:
            hashed, pin_hash = new_password(password), new_pin(pin)
        except (ValueError, HTTPException) as exc:
            raise click.ClickException(str(exc))
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            existing = c.execute("SELECT id FROM users WHERE role='admin' ORDER BY id LIMIT 1").fetchone()
            conflict = c.execute('SELECT id FROM users WHERE email=?', (username,)).fetchone()
            if conflict and (not existing or conflict['id'] != existing['id']):
                raise click.ClickException('Este usuário já pertence a outra conta.')
            c.execute("DELETE FROM sessions WHERE user_id IN (SELECT id FROM users WHERE role='admin')")
            c.execute("DELETE FROM used_refresh_tokens WHERE user_id IN (SELECT id FROM users WHERE role='admin')")
            if existing:
                uid = existing['id']
                c.execute('UPDATE users SET email=?,password=?,email_verified=1 WHERE id=?', (username,hashed,uid))
            else:
                uid = c.execute("INSERT INTO users(email,password,role,email_verified) VALUES(?,?,'admin',1)", (username,hashed)).lastrowid
            c.execute('INSERT INTO admin_credentials VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET pin_hash=excluded.pin_hash', (uid,pin_hash))
            audit(c,'admin_credentials_reset',uid)
        click.echo('Usuário, senha e PIN configurados. Sessões anteriores revogadas.')
    from commerce import install_commerce
    install_commerce(app, db, key, data, require_admin, limit, audit)
    return app


if __name__ == '__main__':
    create_app().run(host='127.0.0.1', port=int(os.getenv('PORT','8000')), debug=False)
