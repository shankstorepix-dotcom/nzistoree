import base64
import io
import sqlite3
import time

import pytest
from PIL import Image
from server import create_app, new_password, new_pin

ORIGIN = {'Origin': 'http://localhost:8000'}

@pytest.fixture
def app(tmp_path):
    instance = create_app({'TESTING': True, 'DATA_DIR': str(tmp_path/'data'), 'UPLOAD_DIR': str(tmp_path/'uploads'), 'DB_KEY': 'ab'*32})
    outbox = {}
    instance.extensions['otp_sender'] = lambda email, code: outbox.__setitem__(email, code)
    instance.extensions['otp_outbox'] = outbox
    return instance

@pytest.fixture
def client(app):
    return app.test_client()

def post(client, path, body=None, csrf=None):
    return client.post(path, json=body or {}, headers={**ORIGIN, **({'X-CSRF-Token':csrf} if csrf else {})})

def admin(app, client):
    with app.extensions['db']() as c:
        c.execute("INSERT INTO users(email,password,role) VALUES('admin',?,'admin')", (new_password('long-admin-password'),))
    with app.extensions['db']() as c:
        c.execute("INSERT INTO admin_credentials SELECT id,? FROM users WHERE role='admin'", (new_pin('123456'),))
    response = post(client,'/api/login',{'username':'admin','password':'long-admin-password','pin':'123456'})
    assert response.status_code == 200
    return response.json['csrf']

def test_private_files_and_host(client):
    for path in ['/server.py','/data/secure.db','/data/.database-key','/.env','/static/../server.py','/uploads/../data/secure.db']:
        assert client.get(path).status_code == 404
        assert client.head(path).status_code == 404
    assert client.get('/api/products',headers={'Host':'evil.test'}).status_code == 400

def test_csrf_and_authorization(app, client):
    assert post(client,'/api/products').status_code == 401
    assert post(client,'/api/setup').status_code == 403
    csrf = admin(app,client)
    assert post(client,'/api/products').status_code == 403
    assert client.post('/api/logout',json={},headers={'Origin':'https://evil.test','X-CSRF-Token':csrf}).status_code == 403
    product = dict(name='<script>alert(1)</script>',description='',price=100,category='Robux',image='')
    assert post(client,'/api/products',product,csrf).status_code == 200
    assert client.get('/api/products').json[0]['name'] == product['name']
    assert post(client,'/api/logout',csrf=csrf).status_code == 200
    assert post(client,'/api/products',product,csrf).status_code == 401

def test_customer_cannot_admin_and_password_revokes(app,client):
    body = {'email':'user@example.com','password':'a-long-password','role':'admin'}
    reg = post(client,'/api/auth/register',body)
    assert reg.status_code == 200 and reg.json == {'ok': True, 'verification_required': True}
    # Unconfirmed account login returns 200 with verification_required=True and does NOT authenticate
    unverified_login = post(client,'/api/auth/login',body)
    assert unverified_login.status_code == 200 and unverified_login.json == {'ok': True, 'verification_required': True}
    assert client.get('/api/auth/me').status_code == 401
    otp = app.extensions['otp_outbox']['user@example.com']
    with app.extensions['db']() as c:
        assert c.execute('SELECT code_hash FROM email_otps WHERE email=?', ('user@example.com',)).fetchone()[0] != otp
    response = post(client,'/api/auth/verify-otp',{'email':'user@example.com','otp':otp})
    assert response.status_code == 200
    csrf = response.json['csrf']
    assert 'HttpOnly' in response.headers['Set-Cookie']
    assert 'SameSite=Strict' in response.headers['Set-Cookie']
    token = client.get_cookie('session').value
    with app.extensions['db']() as c:
        assert c.execute('SELECT token FROM sessions').fetchone()[0] != token
    assert post(client,'/api/products',csrf=csrf).status_code == 403
    assert set(client.get('/api/auth/me').json) == {'authenticated','csrf','email','nickname','nickname_change_available_at'}
    assert post(client,'/api/auth/password',{'currentPassword':body['password'],'password':'new-long-password'},csrf).status_code == 200
    client.set_cookie('session',token)
    assert client.get('/api/auth/me').status_code == 401

def test_expiry(app,client):
    admin(app,client)
    with app.extensions['db']() as c:
        c.execute('UPDATE sessions SET expires=?',(int(time.time())-1,))
    assert client.get('/api/status').json['authenticated'] is False

def test_limit_shared_across_clients(app,client):
    for _ in range(10):
        assert post(client,'/api/login',{'password':'wrong'}).status_code == 401
    assert post(app.test_client(),'/api/login',{'password':'wrong'}).status_code == 429

def test_encrypted_database(app):
    path = app.config['DATA_DIR']+'/secure.db'
    c = sqlite3.connect(path)
    with pytest.raises(sqlite3.DatabaseError):
        c.execute('SELECT * FROM users').fetchall()
    c.close()

def test_upload_validation(app,client):
    csrf = admin(app,client)
    assert post(client,'/api/upload',{'data':base64.b64encode(b'\x89PNG\r\n\x1a\n<script>bad</script>').decode()},csrf).status_code == 400
    stream = io.BytesIO()
    Image.new('RGB',(2,2)).save(stream,'PNG')
    result = post(client,'/api/upload',{'data':base64.b64encode(stream.getvalue()).decode()},csrf)
    assert result.status_code == 200
    assert client.get(result.json['url']).mimetype == 'image/webp'

def test_production_requires_config(tmp_path):
    with pytest.raises(RuntimeError):
        create_app({'PRODUCTION':True,'DATA_DIR':str(tmp_path)})

def test_migration(tmp_path):
    c = sqlite3.connect(tmp_path/'store.db')
    c.executescript("CREATE TABLE products(id INTEGER PRIMARY KEY,name TEXT,description TEXT,price INTEGER,category TEXT,image TEXT); CREATE TABLE settings(key TEXT,value TEXT); INSERT INTO products VALUES(42,'Existing','Description',100,'Robux','');")
    c.execute("INSERT INTO settings VALUES('password',?)",(new_password('legacy-password'),))
    c.commit(); c.close()
    config = {'TESTING':True,'DATA_DIR':str(tmp_path),'UPLOAD_DIR':str(tmp_path/'uploads'),'DB_KEY':'ab'*32}
    for _ in range(2):
        app = create_app(config)
        client = app.test_client()
        assert client.get('/api/products').json[0]['id'] == 42
        assert post(client,'/api/login',{'username':'admin','password':'legacy-password'}).status_code == 401

def test_production_cookie_and_headers(tmp_path):
    app = create_app({'TESTING':True,'PRODUCTION':True,'PUBLIC_ORIGIN':'https://shop.example.com','DB_KEY':'cd'*32,'DATA_DIR':str(tmp_path/'data'),'UPLOAD_DIR':str(tmp_path/'uploads')})
    with app.extensions['db']() as c:
        c.execute("INSERT INTO users(email,password,role) VALUES('admin',?,'admin')",(new_password('long-admin-password'),))
    with app.extensions['db']() as c:
        c.execute("INSERT INTO admin_credentials SELECT id,? FROM users WHERE role='admin'", (new_pin('123456'),))
    client = app.test_client()
    response = client.post('/api/login',base_url='https://shop.example.com',headers={'Origin':'https://shop.example.com'},json={'username':'admin','password':'long-admin-password','pin':'123456'})
    assert response.status_code == 200
    assert 'Secure;' in response.headers['Set-Cookie']
    assert response.headers['Strict-Transport-Security'] == 'max-age=31536000'
    assert response.headers['Cache-Control'] == 'no-store'
    assert "script-src 'self'" in response.headers['Content-Security-Policy']

def test_logout_replay_and_body_limits(app,client):
    csrf = admin(app,client)
    token = client.get_cookie('session').value
    assert post(client,'/api/logout',csrf=csrf).status_code == 200
    client.set_cookie('session',token)
    assert client.get('/api/auth/me').status_code == 401
    assert client.post('/api/auth/login',headers=ORIGIN,json=[]).status_code == 400
    assert client.post('/api/auth/login',headers=ORIGIN,data='{}').status_code == 415
    assert client.post('/api/auth/login',headers=ORIGIN,json={'password':'a'*7_000_000}).status_code == 413


def test_admin_pin_required_on_every_login_route(app,client):
    admin(app,client)
    for route in ['/api/login','/api/auth/login']:
        for pin in ['', '000000', '12345x', 123456]:
            other=app.test_client()
            response=post(other,route,{'username':'admin','email':'admin','password':'long-admin-password','pin':pin})
            assert response.status_code==401
    with app.extensions['db']() as c:
        assert c.execute('SELECT pin_hash FROM admin_credentials').fetchone()[0]!='123456'


def test_admin_cli_revokes_old_sessions(app,client):
    admin(app,client)
    result=app.test_cli_runner().invoke(args=['create-admin','--username','owner','--password','new-admin-password','--pin','654321'])
    assert result.exit_code==0,result.output
    assert client.get('/api/status').json['authenticated'] is False
    other=app.test_client()
    assert post(other,'/api/login',{'username':'owner','password':'new-admin-password','pin':'654321'}).status_code==200
    assert other.get('/api/status').json['authenticated'] is True


def test_legacy_admin_session_cannot_bypass_pin(app,client):
    csrf=admin(app,client)
    with app.extensions['db']() as c:
        c.execute('DELETE FROM admin_sessions')
    assert client.get('/api/status').json['authenticated'] is False
    assert post(client,'/api/products',{},csrf).status_code==401


def test_product_page_routes(app,client):
    products=client.get('/api/products').json
    assert client.get('/produto/'+str(products[0]['id'])).status_code==200
    assert client.get('/produto/999999999').status_code==404


def test_otp_single_use_attempts_cooldown_and_anti_enumeration(app, client):
    body = {'email': 'otpuser@example.com', 'password': 'a-long-password'}
    res1 = post(client, '/api/auth/register', body)
    assert res1.status_code == 200 and res1.json == {'ok': True, 'verification_required': True}
    otp = app.extensions['otp_outbox']['otpuser@example.com']
    # Cooldown prevents immediate resend for the same email
    assert post(client, '/api/auth/resend-otp', {'email': 'otpuser@example.com'}).status_code == 429
    # Verify OTP once -> succeeds and logs in, immediate reuse -> fails (400)
    v_res = post(client, '/api/auth/verify-otp', {'email': 'otpuser@example.com', 'otp': otp})
    assert v_res.status_code == 200 and 'csrf' in v_res.json
    assert post(client, '/api/auth/verify-otp', {'email': 'otpuser@example.com', 'otp': otp}, v_res.json['csrf']).status_code == 400
    # Clear cooldown to test anti-enumeration when registering an already-verified email
    with app.extensions['db']() as c:
        c.execute('DELETE FROM limits')
    app.extensions['otp_outbox'].clear()
    anon = app.test_client()
    res_dup = post(anon, '/api/auth/register', {'email': 'otpuser@example.com', 'password': 'another-long-password'})
    assert res_dup.status_code == 200 and res_dup.json == {'ok': True, 'verification_required': True}
    assert 'otpuser@example.com' not in app.extensions['otp_outbox']
    # Original password still works, attacker's password does not
    assert post(anon, '/api/auth/login', {'email': 'otpuser@example.com', 'password': 'another-long-password'}).status_code == 401
    assert post(anon, '/api/auth/login', body).status_code == 200

    # Max attempts (5) invalidates the OTP challenge
    client2 = app.test_client()
    body2 = {'email': 'brute@example.com', 'password': 'a-long-password'}
    assert post(client2, '/api/auth/register', body2).status_code == 200
    real_otp = app.extensions['otp_outbox']['brute@example.com']
    wrong_otp = '999999' if real_otp != '999999' else '000000'
    for _ in range(5):
        assert post(client2, '/api/auth/verify-otp', {'email': 'brute@example.com', 'otp': wrong_otp}).status_code == 400
    # Even the real OTP is now rejected because the challenge was destroyed after 5 attempts
    assert post(client2, '/api/auth/verify-otp', {'email': 'brute@example.com', 'otp': real_otp}).status_code == 400


def test_single_active_session_revokes_previous_device(app):
    with app.extensions['db']() as c:
        c.execute("INSERT INTO users(email,password,role,email_verified) VALUES('single@example.com',?,'customer',1)",
                  (new_password('long-customer-pass'),))
    device1 = app.test_client()
    device2 = app.test_client()
    r1 = post(device1, '/api/auth/login', {'email': 'single@example.com', 'password': 'long-customer-pass'})
    assert r1.status_code == 200
    assert device1.get('/api/auth/me').status_code == 200
    # Login on device2 must revoke device1's session server-side
    r2 = post(device2, '/api/auth/login', {'email': 'single@example.com', 'password': 'long-customer-pass'})
    assert r2.status_code == 200
    assert device2.get('/api/auth/me').status_code == 200
    assert device1.get('/api/auth/me').status_code == 401
    with app.extensions['db']() as c:
        assert c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 1
        assert c.execute("SELECT 1 FROM audit WHERE event='session_replaced'").fetchone() is not None


def test_refresh_token_rotation_and_reuse_detection(app):
    with app.extensions['db']() as c:
        c.execute("INSERT INTO users(email,password,role,email_verified) VALUES('rotate@example.com',?,'customer',1)",
                  (new_password('long-customer-pass'),))
    client = app.test_client()
    r = post(client, '/api/auth/login', {'email': 'rotate@example.com', 'password': 'long-customer-pass'})
    assert r.status_code == 200
    old_access = client.get_cookie('session').value
    old_refresh = client.get_cookie('refresh').value
    assert old_access and old_refresh

    # Expire the short-lived access token while keeping absolute_expires in the future
    with app.extensions['db']() as c:
        c.execute('UPDATE sessions SET expires=?', (int(time.time()) - 1,))
    assert client.get('/api/auth/me').status_code == 401

    # Rotate via /api/auth/refresh -> issues new access, refresh, and csrf tokens
    rot = post(client, '/api/auth/refresh')
    assert rot.status_code == 200 and rot.json['authenticated'] is True
    new_access = client.get_cookie('session').value
    new_refresh = client.get_cookie('refresh').value
    assert new_access != old_access and new_refresh != old_refresh
    assert client.get('/api/auth/me').status_code == 200

    # Replay the old refresh token from an attacker client -> triggers reuse detection and revokes the active session!
    attacker = app.test_client()
    attacker.set_cookie('refresh', old_refresh)
    assert post(attacker, '/api/auth/refresh').status_code == 401
    assert client.get('/api/auth/me').status_code == 401
    with app.extensions['db']() as c:
        assert c.execute('SELECT COUNT(*) FROM sessions').fetchone()[0] == 0
        assert c.execute("SELECT 1 FROM audit WHERE event='refresh_token_reuse_detected'").fetchone() is not None


def test_admin_audit_and_endpoint_payload_limits(app, client):
    assert client.get('/api/admin/audit').status_code == 401
    csrf = admin(app, client)
    audit_res = client.get('/api/admin/audit')
    assert audit_res.status_code == 200 and len(audit_res.json['events']) >= 1
    # Non-upload endpoints enforce 64 KiB body limit
    assert post(client, '/api/products', {'name': 'x' * 70000}, csrf).status_code == 413


def test_generated_profile_and_nickname_cooldown(app,client):
    body={'email':'Maria.Silva+loja@example.com','password':'a-long-password','nickname':'Ignored'}
    assert post(client,'/api/auth/register',body).status_code==200
    email=body['email'].lower()
    otp=app.extensions['otp_outbox'][email]
    session=post(client,'/api/auth/verify-otp',{'email':email,'otp':otp})
    assert session.status_code==200
    profile=client.get('/api/auth/me').json
    assert profile['email']==email and profile['nickname']=='maria.silvaloja'
    assert profile['nickname_change_available_at']==0
    csrf=profile['csrf']
    assert post(client,'/api/auth/profile',{'nickname':'NomeNovo'}).status_code==403
    assert post(client,'/api/auth/profile',{'nickname':'<script>'},csrf).status_code==400
    assert post(client,'/api/auth/profile',{'nickname':'NomeNovo','user_id':999},csrf).status_code==400
    changed=post(client,'/api/auth/profile',{'nickname':'NomeNovo'},csrf)
    assert changed.status_code==200 and changed.json['nickname']=='NomeNovo'
    retry=post(client,'/api/auth/profile',{'nickname':'OutroNome'},csrf)
    assert retry.status_code==429 and int(retry.headers['Retry-After'])>86000
    assert post(client,'/api/auth/profile',{'nickname':'NomeNovo'},csrf).status_code==200
    assert client.get('/api/auth/me').json['nickname']=='NomeNovo'
    with app.extensions['db']() as c:c.execute('UPDATE user_profiles SET changed_at=?',(int(time.time())-86401,))
    assert post(client,'/api/auth/profile',{'nickname':'OutroNome'},csrf).status_code==200
    assert post(client,'/api/auth/logout',csrf=csrf).status_code==200
    assert client.get('/api/auth/me').status_code==401
    assert post(client,'/api/auth/profile',{'nickname':'Anonimo'}).status_code==401


def test_profile_existing_accounts_migration(app):
    with app.extensions['db']() as c:
        c.execute("INSERT INTO users(email,password,role) VALUES('old.user@example.com',?,'customer')",(new_password('long-user-password'),))
    restarted=create_app(dict(TESTING=True,DATA_DIR=app.config['DATA_DIR'],UPLOAD_DIR=app.config['UPLOAD_DIR'],DB_KEY='ab'*32))
    with restarted.extensions['db']() as c:
        row=c.execute('SELECT nickname,changed_at FROM user_profiles JOIN users ON user_profiles.user_id=users.id WHERE email=?',('old.user@example.com',)).fetchone()
        assert row['nickname']=='old.user' and row['changed_at']==0
    client=restarted.test_client()
    assert post(client,'/api/auth/login',{'email':'old.user@example.com','password':'long-user-password'}).status_code==200
    assert client.get('/api/auth/me').json['email']=='old.user@example.com'


def test_category_jpeg_upload_and_constellation_asset(app, client):
    assert client.get('/static/constellation.js').status_code == 200
    csrf = admin(app, client)
    stream = io.BytesIO()
    Image.new('RGB', (2400, 1600), (180, 20, 30)).save(stream, 'JPEG', quality=92)
    up = post(client, '/api/upload', {'data': base64.b64encode(stream.getvalue()).decode()}, csrf)
    assert up.status_code == 200
    url = up.json['url']
    cat_res = client.put('/api/admin/categories/robux', json={'title': 'Robux Oficial', 'image': url},
                         headers={**ORIGIN, 'X-CSRF-Token': csrf})
    assert cat_res.status_code == 200
    cats = client.get('/api/categories').json
    robux = next(c for c in cats if c['slug'] == 'robux')
    assert robux['title'] == 'Robux Oficial' and robux['image'] == url


def test_google_and_discord_oauth_flow(tmp_path):
    from urllib.parse import parse_qs, urlsplit
    app = create_app({
        'TESTING': True,
        'DATA_DIR': str(tmp_path / 'data'),
        'UPLOAD_DIR': str(tmp_path / 'uploads'),
        'DB_KEY': 'ab' * 32,
        'GOOGLE_CLIENT_ID': 'google-id',
        'GOOGLE_CLIENT_SECRET': 'google-secret',
        'DISCORD_CLIENT_ID': 'discord-id',
        'DISCORD_CLIENT_SECRET': 'discord-secret',
    })
    with app.extensions['db']() as c:
        c.execute("INSERT INTO users(email,password,role,email_verified) VALUES('admin@example.com',?,'admin',1)",
                  (new_password('long-admin-password'),))
    client = app.test_client()
    assert client.get('/api/auth/oauth/providers').json == {'google': True, 'discord': True}

    # Start Google OAuth -> sets HttpOnly state cookie and redirects to Google with PKCE S256
    start_res = client.get('/api/auth/oauth/google/start')
    assert start_res.status_code == 302
    assert start_res.headers['Location'].startswith('https://accounts.google.com/o/oauth2/v2/auth?')
    qs = parse_qs(urlsplit(start_res.headers['Location']).query)
    state = qs['state'][0]
    assert qs['code_challenge_method'] == ['S256']

    # Tampered state must fail
    bad_cb = client.get(f'/api/auth/oauth/google/callback?code=test-code&state=wrong-state')
    assert bad_cb.status_code == 302 and 'oauth_error=invalid_state' in bad_cb.headers['Location']

    # Valid Google OAuth callback creates verified customer and logs in
    start_res = client.get('/api/auth/oauth/google/start')
    state = parse_qs(urlsplit(start_res.headers['Location']).query)['state'][0]
    app.extensions['oauth_exchange'] = lambda provider, code, verifier, uri: {
        'id': 'google-sub-123',
        'email': 'gamer@example.com',
        'verified': True,
    }
    cb_res = client.get(f'/api/auth/oauth/google/callback?code=valid-code&state={state}')
    assert cb_res.status_code == 302 and cb_res.headers['Location'].endswith('/conta')
    me = client.get('/api/auth/me')
    assert me.status_code == 200 and me.json['email'] == 'gamer@example.com'

    # Replaying the same state must fail (single-use state)
    client.set_cookie('oauth_state', state, path='/api/auth/oauth')
    replay_cb = client.get(f'/api/auth/oauth/google/callback?code=valid-code&state={state}')
    assert 'oauth_error=invalid_state' in replay_cb.headers['Location']

    # Admin account cannot be logged into via OAuth (must use /admin with password + PIN)
    admin_client = app.test_client()
    s_admin = admin_client.get('/api/auth/oauth/discord/start')
    st_admin = parse_qs(urlsplit(s_admin.headers['Location']).query)['state'][0]
    app.extensions['oauth_exchange'] = lambda provider, code, verifier, uri: {
        'id': 'discord-admin-999',
        'email': 'admin@example.com',
        'verified': True,
    }
    cb_admin = admin_client.get(f'/api/auth/oauth/discord/callback?code=code2&state={st_admin}')
    assert 'oauth_error=admin_forbidden' in cb_admin.headers['Location']
    assert admin_client.get('/api/auth/me').status_code == 401


def test_password_8_to_24_dashboard_route_and_aes256_gcm_vault(app, client):
    from crypto_vault import seal, unseal
    # 1. Password length must be 8..24 characters
    short_res = post(client, '/api/auth/register', {'email': 'p1@example.com', 'password': '1234567'})
    assert short_res.status_code == 400 and '8 e 24' in short_res.json['error']
    long_res = post(client, '/api/auth/register', {'email': 'p1@example.com', 'password': 'a' * 25})
    assert long_res.status_code == 400 and '8 e 24' in long_res.json['error']
    ok_res = post(client, '/api/auth/register', {'email': 'p1@example.com', 'password': '12345678'})
    assert ok_res.status_code == 200 and ok_res.json['verification_required'] is True

    # 2. /admin is replaced by /dashboard and raw HTML templates are never exposed directly
    assert client.get('/admin').status_code == 404
    dash = client.get('/dashboard')
    assert dash.status_code == 200 and dash.headers['Cache-Control'] == 'no-store'
    for hidden in ('/index.html', '/static/admin.html', '/static/account.html', '/static/orders.html', '/templates/index.html'):
        assert client.get(hidden).status_code == 404
    store_js = client.get('/static/store.js').get_data(as_text=True)
    assert 'Área do administrador' not in store_js

    # 3. AES-256-GCM envelope encryption (crypto_vault.py)
    key_hex = 'ab' * 32
    token = seal('dados-ultra-secretos', key_hex, 'delivery_stock')
    assert token.startswith('enc:gcm1:')
    assert 'dados-ultra-secretos' not in token
    assert unseal(token, key_hex, 'delivery_stock') == 'dados-ultra-secretos'
    with pytest.raises(ValueError):
        unseal(token, key_hex, 'wrong_context')
    with pytest.raises(ValueError):
        unseal(token[:-4] + 'AAAA', key_hex, 'delivery_stock')


def test_password_recovery_single_use_and_attempt_limit(app):
    client=app.test_client();outbox=app.extensions['otp_outbox']
    with app.extensions['db']() as c:
        c.execute("INSERT INTO users(email,password,role,email_verified) VALUES(?,?,'customer',1)",('recover@example.com',new_password('old-password-123')))
    def post(path,body):return client.post('/api/auth/'+path,json=body,headers=ORIGIN)
    assert post('forgot-password',{'email':'missing@example.com'}).status_code==200
    assert not outbox
    assert post('forgot-password',{'email':'recover@example.com'}).status_code==200
    code=outbox['recover@example.com']
    assert post('forgot-password',{'email':'recover@example.com'}).status_code==429
    payload={'email':'recover@example.com','code':code,'password':'new-password-123'}
    assert post('reset-password',payload).status_code==200
    assert post('reset-password',payload).status_code==400
    from server import verify
    with app.extensions['db']() as c:
        assert verify('new-password-123',c.execute("SELECT password FROM users WHERE email='recover@example.com'").fetchone()[0])
        c.execute('DELETE FROM limits')
    assert post('forgot-password',{'email':'recover@example.com'}).status_code==200
    code=outbox['recover@example.com'];wrong='000000' if code!='000000' else '999999'
    for _ in range(5):assert post('reset-password',{**payload,'code':wrong}).status_code==400
    assert post('reset-password',{**payload,'code':code}).status_code==400
