"""Orders, private support chat, one-use fulfillment and payment integrations."""
import csv
import base64
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import time
import urllib.error
import urllib.request
from decimal import Decimal, InvalidOperation
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Blueprint, abort, g, jsonify, request, send_file
from itsdangerous import URLSafeTimedSerializer, BadSignature
from crypto_vault import seal, unseal


class IntegrationError(Exception):
    pass


class PaymentRequestRejected(IntegrationError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def post_json(url, payload, headers=None, method=None):
    """Bounded requests; do not follow redirects with credentials or log responses."""
    req = urllib.request.Request(url, None if method=='GET' else json.dumps(payload).encode(),
                                 {'Content-Type': 'application/json', 'User-Agent': 'NziStore/1.0', **(headers or {})}, method=method)
    try:
        with urllib.request.build_opener(NoRedirect).open(req, timeout=12) as response:
            raw = response.read(1_000_001)
            if len(raw) > 1_000_000:
                raise IntegrationError('Resposta muito grande.')
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if exc.code in (400, 422):
            raise PaymentRequestRejected('Solicitação recusada pelo serviço.') from exc
        raise IntegrationError('Serviço externo indisponível.') from exc
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise IntegrationError('Serviço externo indisponível.') from exc


def install_commerce(app, db, key, data, require_admin, limit, audit):
    bp = Blueprint('commerce', __name__)
    signer = URLSafeTimedSerializer(key, salt='roblox-recipient-v1')
    app.extensions['roblox_signer'] = signer
    for name in ('MISTIC_CLIENT_ID', 'MISTIC_CLIENT_SECRET', 'DISCORD_WEBHOOK_URL', 'UTMIFY_API_TOKEN', 'PANTERA_API_KEY'):
        app.config.setdefault(name, os.getenv(name, ''))
    app.config.setdefault('PAYMENT_PROVIDER',os.getenv('PAYMENT_PROVIDER','mistic'))
    if app.config['PAYMENT_PROVIDER'] not in ('mistic','pantera'):raise RuntimeError('PAYMENT_PROVIDER inválido.')
    webhook = app.config['DISCORD_WEBHOOK_URL']
    if webhook:
        if not re.fullmatch(r'https://discord\.com/api/webhooks/[0-9]+/[A-Za-z0-9_.-]+', webhook):
            if '...' in webhook or 'SEU_' in webhook or 'example' in webhook:
                app.config['DISCORD_WEBHOOK_URL'] = ''
            else:
                raise RuntimeError('DISCORD_WEBHOOK_URL deve ser um webhook HTTPS de discord.com, sem parâmetros.')
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS payment_terms(order_id TEXT PRIMARY KEY REFERENCES orders(id),accepted_at INTEGER NOT NULL,terms_path TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS store_coupon (id INTEGER PRIMARY KEY CHECK(id=1),code TEXT NOT NULL,percent INTEGER NOT NULL,enabled INTEGER NOT NULL);
        INSERT OR IGNORE INTO store_coupon VALUES(1,'DESCONTO10',10,1);
        CREATE TABLE IF NOT EXISTS order_tracking (order_id TEXT PRIMARY KEY REFERENCES orders(id),parameters TEXT NOT NULL,payer_name TEXT,consent INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS chat_presence (order_id TEXT NOT NULL REFERENCES orders(id),role TEXT NOT NULL,seen INTEGER NOT NULL,typing_until INTEGER NOT NULL DEFAULT 0,read_id INTEGER NOT NULL DEFAULT 0,PRIMARY KEY(order_id,role));
        CREATE TABLE IF NOT EXISTS product_delivery (
          product_id INTEGER PRIMARY KEY REFERENCES products(id) ON DELETE CASCADE,
          mode TEXT NOT NULL CHECK(mode IN ('manual','automatic')), robux_quantity INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS orders (
          id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), email TEXT NOT NULL,
          request_key TEXT NOT NULL, request_hash TEXT NOT NULL, total INTEGER NOT NULL,
          payment TEXT NOT NULL DEFAULT 'nao_iniciado', provider_id TEXT UNIQUE, pix_code TEXT,
          roblox_id INTEGER, roblox_username TEXT, roblox_display_name TEXT,
          created INTEGER NOT NULL, paid_at INTEGER, UNIQUE(user_id,request_key));
        CREATE TABLE IF NOT EXISTS order_coupons (order_id TEXT PRIMARY KEY REFERENCES orders(id), code TEXT NOT NULL, discount INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS order_items (
          id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL REFERENCES orders(id),
          product_id INTEGER NOT NULL, name TEXT NOT NULL, category TEXT NOT NULL,
          unit_price INTEGER NOT NULL, quantity INTEGER NOT NULL, mode TEXT NOT NULL,
          robux_quantity INTEGER NOT NULL, delivered_at INTEGER, delivery_text TEXT);
        CREATE TABLE IF NOT EXISTS delivery_stock (
          id INTEGER PRIMARY KEY AUTOINCREMENT, product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE RESTRICT,
          content TEXT NOT NULL, fingerprint TEXT NOT NULL, created INTEGER NOT NULL,
          item_id INTEGER REFERENCES order_items(id), UNIQUE(product_id,fingerprint));
        CREATE TABLE IF NOT EXISTS order_messages (
          id INTEGER PRIMARY KEY AUTOINCREMENT, order_id TEXT NOT NULL REFERENCES orders(id),
          user_id INTEGER NOT NULL REFERENCES users(id), role TEXT NOT NULL,
          text TEXT NOT NULL, request_key TEXT NOT NULL, created INTEGER NOT NULL,
          UNIQUE(user_id,order_id,request_key));
        CREATE INDEX IF NOT EXISTS order_messages_order ON order_messages(order_id,id);
        CREATE INDEX IF NOT EXISTS orders_customer ON orders(user_id,created);
        CREATE INDEX IF NOT EXISTS stock_available ON delivery_stock(product_id,item_id);
        CREATE TABLE IF NOT EXISTS commerce_jobs (
          id INTEGER PRIMARY KEY AUTOINCREMENT, job_key TEXT UNIQUE NOT NULL,
          kind TEXT NOT NULL, order_id TEXT, payload TEXT NOT NULL DEFAULT '{}',
          attempts INTEGER NOT NULL DEFAULT 0, next_at INTEGER NOT NULL DEFAULT 0,
          lease TEXT, leased_until INTEGER NOT NULL DEFAULT 0, done INTEGER NOT NULL DEFAULT 0,
          last_error TEXT);
        ''')

    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if 'payment_provider' not in {r['name'] for r in c.execute('PRAGMA table_info(orders)')}:
            c.execute("ALTER TABLE orders ADD COLUMN payment_provider TEXT NOT NULL DEFAULT 'mistic'")
        columns={r['name'] for r in c.execute('PRAGMA table_info(orders)')}
        for column in ('payment_started_at','pix_expires_at'):
            if column not in columns:c.execute('ALTER TABLE orders ADD COLUMN '+column+' INTEGER')
        c.execute("UPDATE orders SET payment_started_at=?,pix_expires_at=? WHERE payment IN ('pendente','criando','revisao') AND pix_expires_at IS NULL",(int(time.time()),int(time.time())+900))

    def signed_callback(order_id):
        return hmac.new(key.encode(), ('mistic:' + order_id).encode(), hashlib.sha256).hexdigest()

    def configured(provider=None):
        provider=provider or app.config['PAYMENT_PROVIDER']
        if provider=='pantera':return bool(app.config['PANTERA_API_KEY'])
        return bool(app.config['MISTIC_CLIENT_ID'] and app.config['MISTIC_CLIENT_SECRET']
                    and app.config['PUBLIC_ORIGIN'].startswith('https://'))

    def mistic(path, body):
        if not configured('mistic'):
            raise IntegrationError('Mistic Pay ainda não configurada.')
        token = base64.b64encode((app.config['MISTIC_CLIENT_ID'] + ':' + app.config['MISTIC_CLIENT_SECRET']).encode()).decode()
        return post_json('https://api.misticpay.com/api/transactions/' + path, body,
                         {'Authorization': 'Basic ' + token})

    def require_user():
        if not g.user:
            abort(401, 'Entre na sua conta para acompanhar o pedido.')

    def owned_order(c, order_id):
        require_user()
        if not isinstance(order_id, str) or not re.fullmatch(r'[a-f0-9]{32}', order_id):
            abort(404, 'Pedido não encontrado.')
        row = c.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
        if not row or (row['user_id'] != g.user['id'] and g.user['role'] != 'admin'):
            abort(404, 'Pedido não encontrado.')
        return row

    def queue_check(c, order_id, delay=0):
        c.execute('''INSERT INTO commerce_jobs(job_key,kind,order_id,next_at) VALUES(?,'payment',?,?)
                     ON CONFLICT(job_key) DO UPDATE SET done=0,next_at=MIN(next_at,excluded.next_at)''',
                  ('payment:' + order_id, order_id, int(time.time()) + delay))

    def notify(c, order, item, status):
        event_id = f"{order['id']}:{item['id']}:{status}"
        payload = dict(event_id=event_id, email=order['email'], id_product=item['product_id'],
                       product=item['name'], price=format(Decimal(item['unit_price'] * item['quantity']) / 100, '.2f'),
                       quantity=item['quantity'], id_dacompra=order['id'], status=status)
        if item['category'] == 'Robux':
            payload.update(nickname_roblox=order['roblox_username'], robux_quantity=item['robux_quantity'] * item['quantity'])
        c.execute('INSERT OR IGNORE INTO commerce_jobs(job_key,kind,order_id,payload) VALUES(?,?,?,?)',
                  ('discord:' + event_id, 'discord', order['id'], json.dumps(payload, ensure_ascii=False)))

    def fulfill(c, order):
        """Call only within BEGIN IMMEDIATE. Each stock row is assigned exactly once."""
        if order['payment'] != 'pago':
            return
        for item in c.execute("SELECT * FROM order_items WHERE order_id=? AND delivered_at IS NULL AND mode='automatic' ORDER BY id", (order['id'],)).fetchall():
            stock = c.execute('SELECT * FROM delivery_stock WHERE product_id=? AND item_id IS NULL ORDER BY id LIMIT ?',
                              (item['product_id'], item['quantity'])).fetchall()
            if len(stock) < item['quantity']:
                continue
            content = '\n\n'.join(f"Unidade {i+1}\n{unseal(unit['content'], key, 'delivery_stock')}" for i, unit in enumerate(stock))
            for unit in stock:
                c.execute('UPDATE delivery_stock SET item_id=? WHERE id=? AND item_id IS NULL', (item['id'], unit['id']))
            c.execute('UPDATE order_items SET delivered_at=?,delivery_text=? WHERE id=? AND delivered_at IS NULL',
                      (int(time.time()), seal(content, key, 'order_delivery'), item['id']))
            notify(c, order, item, 'entregue')

    def expire_pix(c,order):
        if order['payment']=='pendente' and order['pix_expires_at'] and order['pix_expires_at']<=int(time.time()):
            c.execute("UPDATE orders SET payment='expirado' WHERE id=? AND payment='pendente'",(order['id'],))
            return c.execute('SELECT * FROM orders WHERE id=?',(order['id'],)).fetchone()
        return order

    def order_json(c, order):
        order=expire_pix(c,order)
        items = [dict(r) for r in c.execute('''SELECT id,product_id,name,category,unit_price,quantity,mode,
                       robux_quantity,delivered_at FROM order_items WHERE order_id=? ORDER BY id''', (order['id'],))]
        coupon = c.execute('SELECT code,discount FROM order_coupons WHERE order_id=?', (order['id'],)).fetchone()
        return dict(pix_expires_at=order['pix_expires_at'],chat_enabled=order['paid_at'] is not None, coupon=dict(coupon) if coupon else None, id=order['id'], total=order['total'], payment=order['payment'], created=order['created'],
                    status='entregue' if items and all(i['delivered_at'] for i in items) else 'aguardando',
                    email=order['email'] if g.user['role'] == 'admin' else None,
                    roblox_username=order['roblox_username'], roblox_id=order['roblox_id'],
                    pix_code=order['pix_code'] if order['payment'] == 'pendente' else None, items=items)

    @bp.get('/api/checkout/config')
    def checkout_config():
        limit('catalog:' + (request.remote_addr or ''), 120, 60)
        return jsonify(mistic_ready=configured(),payment_ready=configured(),payment_provider=app.config['PAYMENT_PROVIDER'])

    @bp.get('/api/admin/commerce/status')
    def integrations_status():
        require_admin()
        limit('admin:' + str(g.user['id']), 60, 60)
        with db() as c:
            jobs = [dict(r) for r in c.execute('''SELECT kind,COUNT(*) AS pending,SUM(attempts>0) AS retried
                FROM commerce_jobs WHERE done=0 GROUP BY kind''')]
        google_oauth = bool(app.config.get('GOOGLE_CLIENT_ID', '').strip() and app.config.get('GOOGLE_CLIENT_SECRET', '').strip())
        discord_oauth = bool(app.config.get('DISCORD_CLIENT_ID', '').strip() and app.config.get('DISCORD_CLIENT_SECRET', '').strip())
        return jsonify(mistic_ready=configured('mistic'),pantera_ready=configured('pantera'),payment_provider=app.config['PAYMENT_PROVIDER'], discord_ready=bool(webhook), utmify_ready=bool(app.config['UTMIFY_API_TOKEN']),
                       google_oauth_ready=google_oauth, discord_oauth_ready=discord_oauth, jobs=jobs)

    def coupon_config(c):
        return dict(c.execute('SELECT code,percent,enabled FROM store_coupon WHERE id=1').fetchone())

    @bp.get('/api/coupon')
    def public_coupon():
        with db() as c:
            config = coupon_config(c)
        return jsonify(coupon=config if config['enabled'] else None)

    @bp.route('/api/admin/coupon', methods=['GET','PUT'])
    def edit_coupon():
        require_admin()
        with db() as c:
            if request.method == 'PUT':
                body = data()
                code, percent, enabled = body.get('code'),body.get('percent'),body.get('enabled')
                if not isinstance(code,str) or not re.fullmatch(r'[A-Z0-9_-]{3,32}',code) or type(percent) is not int or not 1<=percent<=90 or type(enabled) is not bool:
                    abort(400,'Use código de 3 a 32 caracteres (A-Z, 0-9, _ ou -), desconto de 1 a 90% e estado válido.')
                c.execute('UPDATE store_coupon SET code=?,percent=?,enabled=? WHERE id=1',(code,percent,int(enabled)))
                audit(c,'coupon_updated',g.user['id'])
            return jsonify(coupon=coupon_config(c))

    @bp.get('/api/admin/sales/emails.csv')
    def email_report():
        require_admin()
        limit('email-export:'+str(g.user['id']),10,60)
        try:
            start=datetime.strptime(request.args.get('from',''),'%Y-%m-%d').replace(tzinfo=ZoneInfo('America/Sao_Paulo'))
            end=datetime.strptime(request.args.get('to',''),'%Y-%m-%d').replace(tzinfo=ZoneInfo('America/Sao_Paulo'))+timedelta(days=1)
        except ValueError:
            abort(400,'Informe as datas inicial e final.')
        if not timedelta(0)<end-start<=timedelta(days=366):
            abort(400,'Selecione um período de até 366 dias.')
        with db() as c:
            rows=c.execute("SELECT email,COUNT(*) AS purchases,SUM(total) AS total FROM orders WHERE payment='pago' AND paid_at>=? AND paid_at<? GROUP BY email ORDER BY email",(int(start.timestamp()),int(end.timestamp()))).fetchall()
            audit(c,'emails_exported',g.user['id'])
        output=io.StringIO();writer=csv.writer(output,delimiter=';');writer.writerow(['email','compras_pagas','total_pago_brl'])
        for row in rows:
            email=row['email']
            if email.lstrip().startswith(('=','+','-','@')): email="'"+email
            writer.writerow([email,row['purchases'],format(Decimal(row['total'])/100,'.2f')])
        return send_file(io.BytesIO(('\ufeff'+output.getvalue()).encode('utf-8')),mimetype='text/csv',as_attachment=True,download_name='emails-vendas.csv',max_age=0)

    def require_chat(c,order_id):
        order=owned_order(c,order_id)
        if order['paid_at'] is None:
            abort(409,'O chat é liberado após a confirmação do pagamento.')
        return order

    @bp.post('/api/orders/<order_id>/chat-state')
    def chat_state(order_id):
        require_user()
        limit('presence:'+str(g.user['id']),120,60)
        body=data();read=body.get('read_id',0);typing=body.get('typing',False)
        if type(read) is not int or read<0 or type(typing) is not bool: abort(400)
        with db() as c:
            require_chat(c,order_id)
            last=c.execute('SELECT COALESCE(MAX(id),0) FROM order_messages WHERE order_id=?',(order_id,)).fetchone()[0]
            now=int(time.time())
            c.execute("INSERT INTO chat_presence VALUES(?,?,?,?,?) ON CONFLICT(order_id,role) DO UPDATE SET seen=excluded.seen,typing_until=excluded.typing_until,read_id=MAX(chat_presence.read_id,excluded.read_id)",(order_id,g.user['role'],now,now+5 if typing else 0,min(read,last)))
        return jsonify(ok=True)

    def queue_utmify(c,order_id,status):
        tracking=c.execute('SELECT * FROM order_tracking WHERE order_id=?',(order_id,)).fetchone()
        if not tracking or not tracking['consent'] or not app.config['UTMIFY_API_TOKEN'] or not tracking['payer_name']: return
        order=c.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
        stamp=lambda n: datetime.fromtimestamp(n,timezone.utc).strftime('%Y-%m-%d %H:%M:%S') if n else None
        payload=dict(orderId=order_id,platform='NziStore',paymentMethod='pix',status=status,createdAt=stamp(order['created']),approvedDate=stamp(order['paid_at']),refundedAt=stamp(int(time.time())) if status=='refunded' else None,
            customer=dict(name=tracking['payer_name'],email=order['email'],phone=None,document=None),
            products=[dict(id=str(i['product_id']),name=i['name'],planId=None,planName=None,quantity=i['quantity'],priceInCents=i['unit_price']) for i in c.execute('SELECT * FROM order_items WHERE order_id=?',(order_id,))],
            trackingParameters=json.loads(tracking['parameters']),commission=dict(totalPriceInCents=order['total'],gatewayFeeInCents=0,userCommissionInCents=order['total'],currency='BRL'))
        c.execute("INSERT OR IGNORE INTO commerce_jobs(job_key,kind,order_id,payload) VALUES(?,'utmify',?,?)",('utmify:'+order_id+':'+status,order_id,json.dumps(payload)))

    @bp.get('/api/admin/metrics')
    def admin_metrics():
        require_admin()
        try:
            days = int(request.args.get('days', 7))
        except ValueError:
            abort(400)
        if days not in (1, 7, 30, 90):
            abort(400, 'Período inválido.')
        tz = ZoneInfo('America/Sao_Paulo')
        today = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        start = today - timedelta(days=days-1)
        end = today + timedelta(days=1)
        previous = start - timedelta(days=days)
        with db() as c:
            paid_rows = c.execute("SELECT total,paid_at FROM orders WHERE payment='pago' AND paid_at>=? AND paid_at<?", (int(previous.timestamp()),int(end.timestamp()))).fetchall()
            created = c.execute("SELECT COUNT(*) AS orders,COALESCE(SUM(payment='pago'),0) AS approved FROM orders WHERE created>=? AND created<?", (int(start.timestamp()),int(end.timestamp()))).fetchone()
            pending = c.execute("SELECT COUNT(*) FROM orders o WHERE payment='pago' AND EXISTS(SELECT 1 FROM order_items i WHERE i.order_id=o.id AND delivered_at IS NULL)").fetchone()[0]
            waiting = c.execute("SELECT COUNT(*) FROM order_messages m WHERE role='customer' AND order_id IN (SELECT id FROM orders WHERE paid_at IS NOT NULL) AND id=(SELECT MAX(id) FROM order_messages m2 WHERE m2.order_id=m.order_id)").fetchone()[0]
            customers = c.execute("SELECT COUNT(*) FROM users WHERE role='customer'").fetchone()[0]
            coupon = c.execute("SELECT COUNT(*) AS uses,COALESCE(SUM(c.discount),0) AS discount FROM order_coupons c JOIN orders o ON o.id=c.order_id WHERE o.payment='pago' AND o.paid_at>=? AND o.paid_at<?", (int(start.timestamp()),int(end.timestamp()))).fetchone()
            insights=app.extensions['insights_summary'](c,start,end)
            segments=c.execute("SELECT COUNT(*) AS buyers,COALESCE(SUM(n>1),0) AS recurring FROM (SELECT o.user_id,COUNT(*) AS n FROM orders o WHERE o.payment='pago' AND o.paid_at<? AND EXISTS(SELECT 1 FROM orders p WHERE p.user_id=o.user_id AND p.payment='pago' AND p.paid_at>=? AND p.paid_at<?) GROUP BY o.user_id)",(int(end.timestamp()),int(start.timestamp()),int(end.timestamp()))).fetchone()
            top_products=[dict(r) for r in c.execute("SELECT i.product_id,i.name,SUM(i.quantity) AS quantity,SUM(i.unit_price*i.quantity) AS revenue FROM order_items i JOIN orders o ON o.id=i.order_id WHERE o.payment='pago' AND o.paid_at>=? AND o.paid_at<? GROUP BY i.product_id,i.name ORDER BY revenue DESC LIMIT 10",(int(start.timestamp()),int(end.timestamp())))]
        series = {(start+timedelta(days=i)).date().isoformat():dict(revenue=0,sales=0) for i in range(days)}
        previous_revenue = 0
        for row in paid_rows:
            date = datetime.fromtimestamp(row['paid_at'],tz).date().isoformat()
            if date in series:
                series[date]['revenue'] += row['total']
                series[date]['sales'] += 1
            else:
                previous_revenue += row['total']
        revenue = sum(day['revenue'] for day in series.values())
        sales = sum(day['sales'] for day in series.values())
        return jsonify(**insights,buyers=segments['buyers'],recurring=segments['recurring'],top_products=top_products,days=days,timezone=str(tz),revenue=revenue,sales=sales,orders=created['orders'],
                       approval_rate=round(created['approved']/created['orders']*100,1) if created['orders'] else 0,
                       average_ticket=round(revenue/sales) if sales else 0,
                       revenue_change=round((revenue-previous_revenue)/previous_revenue*100,1) if previous_revenue else None,
                       pending_deliveries=pending,waiting_conversations=waiting,customers=customers,
                       coupon=dict(coupon),series=[dict(date=date,**values) for date,values in series.items()])

    def admin_page_number():
        try:
            page = int(request.args.get('page',1))
        except ValueError:
            abort(400)
        if not 1 <= page <= 100000:
            abort(400)
        return page

    @bp.get('/api/admin/conversations')
    def admin_conversations():
        require_admin()
        page = admin_page_number()
        query = request.args.get('q','').strip()[:120]
        waiting = request.args.get('waiting') == '1'
        with db() as c:
            rows = c.execute("""SELECT o.id,o.email,o.total,o.payment,o.created,m.id AS message_id,m.role AS last_role,
                m.text AS preview,m.created AS message_at
                FROM orders o LEFT JOIN order_messages m ON m.id=(SELECT MAX(id) FROM order_messages WHERE order_id=o.id)
                WHERE o.paid_at IS NOT NULL AND (instr(lower(o.email),lower(?))>0 OR instr(o.id,?)>0)
                AND (?=0 OR m.role='customer')
                ORDER BY COALESCE(m.created,o.created) DESC,o.id DESC LIMIT 21 OFFSET ?""", (query,query,int(waiting),(page-1)*20)).fetchall()
            waiting_count = c.execute("SELECT COUNT(*) FROM order_messages m WHERE m.role='customer' AND m.order_id IN (SELECT id FROM orders WHERE paid_at IS NOT NULL) AND m.id=(SELECT MAX(id) FROM order_messages WHERE order_id=m.order_id)").fetchone()[0]
        convs = []
        for r in rows[:20]:
            d = dict(r)
            if d.get('preview'):
                d['preview'] = unseal(d['preview'], key, 'order_chat')[:160]
            convs.append(d)
        return jsonify(conversations=convs,has_more=len(rows)>20,waiting_count=waiting_count)

    @bp.get('/api/admin/customers')
    def admin_customers():
        require_admin()
        page = admin_page_number()
        with db() as c:
            rows = c.execute("""SELECT u.id,u.email,COUNT(o.id) AS orders,
                COALESCE(SUM(CASE WHEN o.payment='pago' THEN o.total ELSE 0 END),0) AS paid_total
                FROM users u LEFT JOIN orders o ON o.user_id=u.id WHERE u.role='customer'
                GROUP BY u.id ORDER BY u.id DESC LIMIT 21 OFFSET ?""", ((page-1)*20,)).fetchall()
        return jsonify(customers=[dict(r) for r in rows[:20]],has_more=len(rows)>20)

    @bp.get('/api/admin/products/<int:product_id>/delivery')
    def delivery_config(product_id):
        require_admin()
        limit('admin:' + str(g.user['id']), 60, 60)
        with db() as c:
            if not c.execute('SELECT 1 FROM products WHERE id=?', (product_id,)).fetchone():
                abort(404)
            config = c.execute('SELECT mode,robux_quantity FROM product_delivery WHERE product_id=?', (product_id,)).fetchone()
            stock = [dict(r) for r in c.execute('SELECT id,created FROM delivery_stock WHERE product_id=? AND item_id IS NULL ORDER BY id LIMIT 500', (product_id,))]
            available = c.execute('SELECT COUNT(*) FROM delivery_stock WHERE product_id=? AND item_id IS NULL', (product_id,)).fetchone()[0]
        return jsonify(**(dict(config) if config else dict(mode='manual', robux_quantity=0)), stock=stock, available=available)

    @bp.post('/api/admin/products/<int:product_id>/stock')
    def add_stock(product_id):
        require_admin()
        limit('admin:' + str(g.user['id']), 60, 60)
        body = data()
        content = body.get('content')
        if not isinstance(content, str) or not content.strip() or len(content) > 20000 or '\x00' in content:
            abort(400, 'Informe o texto da unidade, até 20.000 caracteres.')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            if not c.execute('SELECT 1 FROM products WHERE id=?', (product_id,)).fetchone():
                abort(404)
            try:
                stock_fp = hmac.new(key.encode(), ('stock:' + content.strip()).encode(), hashlib.sha256).hexdigest()
                c.execute('INSERT INTO delivery_stock(product_id,content,fingerprint,created) VALUES(?,?,?,?)',
                          (product_id, seal(content, key, 'delivery_stock'), stock_fp, int(time.time())))
            except Exception as exc:
                if 'UNIQUE constraint' in str(exc):
                    abort(409, 'Esse conteúdo já foi cadastrado para este produto.')
                raise
            for order in c.execute("SELECT DISTINCT o.* FROM orders o JOIN order_items i ON i.order_id=o.id WHERE o.payment='pago' AND i.product_id=? AND i.delivered_at IS NULL ORDER BY o.created,o.id", (product_id,)).fetchall():
                fulfill(c, order)
            audit(c, 'stock_added', g.user['id'])
        return jsonify(ok=True), 201

    @bp.get('/api/admin/products/<int:product_id>/stock/<int:stock_id>')
    def get_stock_unit(product_id, stock_id):
        require_admin()
        limit('admin:' + str(g.user['id']), 60, 60)
        with db() as c:
            row = c.execute('SELECT id,content,created FROM delivery_stock WHERE id=? AND product_id=? AND item_id IS NULL', (stock_id, product_id)).fetchone()
            if not row:
                abort(404, 'Unidade não encontrada ou já entregue.')
            return jsonify(id=row['id'], content=unseal(row['content'], key, 'delivery_stock'), created=row['created'])

    @bp.put('/api/admin/products/<int:product_id>/stock/<int:stock_id>')
    def update_stock_unit(product_id, stock_id):
        require_admin()
        limit('admin:' + str(g.user['id']), 60, 60)
        body = data()
        content = body.get('content')
        if not isinstance(content, str) or not content.strip() or len(content) > 20000 or '\x00' in content:
            abort(400, 'Informe o texto da unidade, até 20.000 caracteres.')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            row = c.execute('SELECT id FROM delivery_stock WHERE id=? AND product_id=? AND item_id IS NULL', (stock_id, product_id)).fetchone()
            if not row:
                abort(409, 'Unidade não encontrada ou já entregue.')
            try:
                stock_fp = hmac.new(key.encode(), ('stock:' + content.strip()).encode(), hashlib.sha256).hexdigest()
                c.execute('UPDATE delivery_stock SET content=?,fingerprint=? WHERE id=? AND product_id=? AND item_id IS NULL',
                          (seal(content, key, 'delivery_stock'), stock_fp, stock_id, product_id))
            except Exception as exc:
                if 'UNIQUE constraint' in str(exc):
                    abort(409, 'Esse conteúdo já foi cadastrado para este produto.')
                raise
            audit(c, 'stock_updated', g.user['id'])
        return jsonify(ok=True)

    @bp.delete('/api/admin/products/<int:product_id>/stock/<int:stock_id>')
    def remove_stock(product_id, stock_id):
        require_admin()
        limit('admin:' + str(g.user['id']), 60, 60)
        with db() as c:
            result = c.execute('DELETE FROM delivery_stock WHERE id=? AND product_id=? AND item_id IS NULL', (stock_id, product_id))
            if not result.rowcount:
                abort(409, 'Unidade não encontrada ou já entregue.')
            audit(c, 'stock_removed', g.user['id'])
        return jsonify(ok=True)

    @bp.post('/api/orders')
    def create_order():
        require_user()
        limit('orders-burst:' + str(g.user['id']), 5, 60)
        limit('orders:' + str(g.user['id']), 12, 3600)
        limit('orders-ip:' + (request.remote_addr or 'unknown'), 20, 600)
        body = data()
        if not set(body.keys()) <= {'items', 'expected_total', 'request_key', 'coupon', 'roblox_confirmed', 'roblox_ticket', 'tracking', 'payer_name', 'payer_email'}:
            abort(400, 'Dados inválidos.')
        raw_payer_name = body.get('payer_name')
        raw_payer_email = body.get('payer_email')
        if raw_payer_name is not None and (not isinstance(raw_payer_name, str) or not 3 <= len(raw_payer_name.strip()) <= 120):
            abort(400, 'Informe seu nome completo (3 a 120 caracteres) para identificação no pagamento.')
        if raw_payer_email is not None and (not isinstance(raw_payer_email, str) or len(raw_payer_email) > 254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', raw_payer_email)):
            abort(400, 'Informe um e-mail válido.')
        request_key = body.get('request_key', '')
        if not isinstance(request_key, str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}', request_key):
            abort(400, 'Identificador de checkout inválido. Atualize a página.')
        raw_items = body.get('items')
        if not isinstance(raw_items, list) or not 1 <= len(raw_items) <= 20:
            abort(400, 'Carrinho inválido.')
        items = {}
        for item in raw_items:
            if not isinstance(item, dict) or not set(item.keys()) <= {'product_id', 'quantity', 'variant_id'}:
                abort(400, 'Itens inválidos.')
            pid = item.get('product_id')
            qty = item.get('quantity')
            vid = item.get('variant_id')
            if type(pid) is not int or type(qty) is not int or not 1 <= qty <= 99 or (vid is not None and type(vid) is not int):
                abort(400, 'Itens inválidos.')
            item_key = (pid, vid)
            if item_key in items:
                abort(400, 'Produto duplicado no carrinho.')
            items[item_key] = qty
        if sum(items.values()) > 100:
            abort(400, 'Limite de 100 unidades por pedido.')
        fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            existing = c.execute('SELECT * FROM orders WHERE user_id=? AND request_key=?', (g.user['id'], request_key)).fetchone()
            if existing:
                if existing['request_hash'] != fingerprint:
                    abort(409, 'Esse checkout já foi utilizado com outro carrinho.')
                return jsonify(order=order_json(c, existing)), 200
            products = []
            for (product_id, variant_id), quantity in items.items():
                p = c.execute('''SELECT p.*,COALESCE(d.mode,'manual') AS mode,COALESCE(d.robux_quantity,0) AS robux_quantity
                                 FROM products p LEFT JOIN product_delivery d ON d.product_id=p.id WHERE p.id=?''', (product_id,)).fetchone()
                if not p:
                    abort(409, 'Um produto saiu do catálogo. Atualize o carrinho.')
                min_q = p['min_quantity'] if 'min_quantity' in p.keys() and p['min_quantity'] else 1
                max_q = p['max_quantity'] if 'max_quantity' in p.keys() and p['max_quantity'] else 99
                if not min_q <= quantity <= max_q:
                    abort(400, f"A quantidade para {p['name']} deve ser entre {min_q} e {max_q}.")
                if p['category'] == 'Robux' and p['robux_quantity'] <= 0:
                    abort(409, 'Este pacote de Robux ainda precisa ser configurado pela loja.')
                resolved = dict(p)
                has_variants = bool(p['has_variants']) if 'has_variants' in p.keys() else False
                if has_variants:
                    if variant_id is None:
                        abort(400, f"Selecione uma opção para {p['name']}.")
                    variant = c.execute('SELECT * FROM product_variants WHERE id=? AND product_id=?', (variant_id, product_id)).fetchone()
                    if not variant:
                        abort(409, 'A variação selecionada mudou ou saiu do catálogo. Atualize a página.')
                    if variant['stock'] < quantity:
                        abort(409, f"Estoque insuficiente para {p['name']} ({variant['name']})")
                    resolved['price'] = variant['price']
                    resolved['name'] = f"{p['name']} — {variant['name']}"
                    resolved['variant_id'] = variant['id']
                else:
                    if variant_id is not None:
                        abort(400, 'Este produto não possui variações.')
                    resolved['variant_id'] = None
                    if p['mode'] == 'automatic':
                        available = c.execute('SELECT COUNT(*) FROM delivery_stock WHERE product_id=? AND item_id IS NULL', (product_id,)).fetchone()[0]
                        if available < quantity:
                            abort(409, 'Estoque insuficiente para ' + p['name'])
                products.append((resolved, quantity))
            coupon = body.get('coupon', '')
            config=coupon_config(c)
            if not isinstance(coupon, str) or (coupon and (not config['enabled'] or coupon != config['code'])):
                abort(400, 'Cupom inválido.')
            subtotal = sum(p['price'] * q for p, q in products)
            discount = sum((p['price'] * config['percent'] // 100) * q for p, q in products) if coupon else 0
            total = subtotal - discount
            if type(body.get('expected_total')) is not int or body['expected_total'] != total:
                abort(409, 'O preço mudou. Atualize a loja antes de continuar.')
            roblox = {}
            if any(p['category'] == 'Robux' for p, _ in products):
                if body.get('roblox_confirmed') is not True:
                    abort(400, 'Confirme o usuário do Roblox.')
                try:
                    roblox = signer.loads(body.get('roblox_ticket', ''), max_age=900)
                except (BadSignature, TypeError):
                    abort(400, 'Consulte e confirme seu usuário do Roblox novamente.')
            now = int(time.time())
            pending_orders = c.execute(
                "SELECT COUNT(*) FROM orders WHERE user_id=? AND payment IN ('nao_iniciado','criando','pendente','revisao') AND created>?",
                (g.user['id'], now - 1800)
            ).fetchone()[0]
            if pending_orders >= 3:
                abort(429, 'Você já possui pedidos pendentes de pagamento. Conclua o pagamento em Meus pedidos ou aguarde antes de criar outro.')
            order_id = secrets.token_hex(16)
            email = c.execute('SELECT email FROM users WHERE id=?', (g.user['id'],)).fetchone()['email']
            c.execute('''INSERT INTO orders(id,user_id,email,request_key,request_hash,total,roblox_id,roblox_username,roblox_display_name,created)
                         VALUES(?,?,?,?,?,?,?,?,?,?)''', (order_id, g.user['id'], email, request_key, fingerprint, total,
                         roblox.get('id'), roblox.get('username'), roblox.get('displayName'), now))
            tracking=body.get('tracking',{})
            allowed=('src','sck','utm_source','utm_campaign','utm_medium','utm_content','utm_term')
            if not isinstance(tracking,dict) or any(k not in allowed or not isinstance(v,str) or len(v)>250 for k,v in tracking.items()): abort(400,'Parâmetros de campanha inválidos.')
            try:
                from urllib.parse import unquote
                preferences=json.loads(unquote(request.cookies.get('nzi-cookie-preferences','{}')))
                consent=preferences.get('version')==2 and preferences.get('analytics') is True
            except (ValueError,AttributeError): consent=False
            c.execute('INSERT INTO order_tracking(order_id,parameters,payer_name,consent) VALUES(?,?,?,?)',(order_id,json.dumps({k:tracking.get(k) if consent else None for k in allowed}),raw_payer_name.strip() if isinstance(raw_payer_name, str) else None,int(consent)))
            if coupon:
                c.execute('INSERT INTO order_coupons(order_id,code,discount) VALUES(?,?,?)', (order_id,coupon,discount))
            for p, quantity in products:
                if p.get('variant_id'):
                    c.execute('UPDATE product_variants SET stock=stock-? WHERE id=? AND stock>=?', (quantity, p['variant_id'], quantity))
                c.execute('''INSERT INTO order_items(order_id,product_id,name,category,unit_price,quantity,mode,robux_quantity)
                             VALUES(?,?,?,?,?,?,?,?)''', (order_id, p['id'], p['name'], p['category'], p['price'] - (p['price']*config['percent']//100 if coupon else 0), quantity, p['mode'], p['robux_quantity']))
            audit(c, 'order_created', g.user['id'])
            return jsonify(order=order_json(c, owned_order(c, order_id))), 201

    @bp.get('/api/orders')
    def list_orders():
        require_user()
        try:
            page = max(1, min(100000, int(request.args.get('page', '1'))))
        except ValueError:
            abort(400)
        offset = (page - 1) * 20
        with db() as c:
            if g.user['role'] == 'admin':
                rows = c.execute('SELECT * FROM orders ORDER BY created DESC,id DESC LIMIT 21 OFFSET ?', (offset,)).fetchall()
            else:
                rows = c.execute('SELECT * FROM orders WHERE user_id=? ORDER BY created DESC,id DESC LIMIT 21 OFFSET ?', (g.user['id'], offset)).fetchall()
            return jsonify(orders=[order_json(c, r) for r in rows[:20]], has_more=len(rows)>20, admin=g.user['role']=='admin')

    @bp.get('/api/orders/<order_id>')
    def get_order(order_id):
        with db() as c:
            return jsonify(order=order_json(c, owned_order(c, order_id)))

    @bp.get('/api/orders/<order_id>/pix.png')
    def pix_image(order_id):
        import qrcode
        with db() as c:
            order=expire_pix(c,owned_order(c,order_id))
        if order['payment']!='pendente' or not order['pix_code']:abort(404)
        output=io.BytesIO()
        qr=qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M,box_size=7,border=4)
        qr.add_data(order['pix_code']);qr.make(fit=True)
        qr.make_image(fill_color='black',back_color='white').save(output,format='PNG');output.seek(0)
        return send_file(output,mimetype='image/png',max_age=0)

    @bp.post('/api/orders/<order_id>/payment')
    def create_payment(order_id):
        body = data()
        with db() as c:
            order = owned_order(c, order_id)
        if order['user_id'] != g.user['id']:
            abort(403, 'Apenas o titular do pedido pode gerar o pagamento.')
        limit('payment-create:' + str(g.user['id']), 10, 300)
        if not configured():
            abort(503, 'Pagamento Pix ainda não configurado. Tente novamente mais tarde.')
        provider=app.config['PAYMENT_PROVIDER']
        if body.get('terms_accepted') is not True:abort(400,'Aceite os termos e condições para gerar o Pix.')
        email=body.get('payer_email');confirmation=body.get('payer_email_confirmation')
        if not isinstance(email,str) or len(email)>254 or not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+',email.strip()):abort(400,'Informe um e-mail válido.')
        email=email.strip().lower()
        if not isinstance(confirmation,str) or confirmation.strip().lower()!=email:abort(400,'Os e-mails precisam ser iguais.')
        name=body.get('payer_name')
        if provider=='mistic' and (not isinstance(name,str) or not 3<=len(name.strip())<=120):abort(400,'A integração Mistic exige nome do pagador. Use o checkout Pantera sem nome.')
        name=name.strip() if isinstance(name,str) else ''
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            order = expire_pix(c,owned_order(c, order_id))
            if order['payment'] != 'nao_iniciado':
                return jsonify(order=order_json(c, order))
            now=int(time.time())
            c.execute("UPDATE orders SET payment='expirado' WHERE user_id=? AND payment='pendente' AND pix_expires_at<=?",(g.user['id'],now))
            active=c.execute("SELECT id,pix_expires_at FROM orders WHERE user_id=? AND id!=? AND payment IN ('criando','pendente','revisao') ORDER BY created LIMIT 1",(g.user['id'],order_id)).fetchone()
            if active:
                response=jsonify(error='Você já tem um Pix em andamento. Abra o pagamento existente para continuar.',active_order_id=active['id'])
                response.status_code=429;response.headers['Retry-After']=str(max(1,(active['pix_expires_at'] or now+60)-now));return response
            count=c.execute('SELECT COUNT(*) FROM orders WHERE user_id=? AND payment_started_at>?',(g.user['id'],now-3600)).fetchone()[0]
            if count>=4:
                response=jsonify(error='Limite de 4 gerações de Pix por hora. Aguarde para tentar novamente.');response.status_code=429;response.headers['Retry-After']='900';return response
            c.execute("UPDATE orders SET payment='criando',payment_provider=?,payment_started_at=?,pix_expires_at=? WHERE id=?", (provider,now,now+900,order_id))
            c.execute('INSERT OR IGNORE INTO payment_terms VALUES(?,?,?)',(order_id,now,'/terms'))
            audit(c,'payment_terms_accepted',g.user['id'])
            c.execute('UPDATE order_tracking SET payer_name=? WHERE order_id=?',(name or None,order_id))
            queue_check(c, order_id, 30)
        try:
            if provider=='pantera':
                if order['total']<50:raise PaymentRequestRejected('Mínimo Pix: R$ 0,50.')
                payload={'amount':order['total']}
                origin=app.config['PUBLIC_ORIGIN'].rstrip('/')
                if origin.startswith('https://'):payload['webhook']=origin+'/api/payments/pantera/'+order_id+'/'+signed_callback(order_id)
                result=post_json('https://panterapay-production.up.railway.app/transactions',payload,{'Authorization':app.config['PANTERA_API_KEY']})
                provider_id,pix=str(result['id']),result['copyPaste']
                if type(result['amount']) is not int or result['amount']!=order['total']:raise IntegrationError('Valor da cobrança inválido.')
                if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',provider_id):raise IntegrationError('Identificador inválido.')
            else:
                result = mistic('create', dict(amount=float(Decimal(order['total'])/100), payerName=name.strip(),
                                transactionId=order_id, description='Pedido NziStore ' + order_id + ' | ' + email,
                                projectWebhook=app.config['PUBLIC_ORIGIN'].rstrip('/') + '/api/payments/mistic/' + order_id + '/' + signed_callback(order_id)))
                payment = result['data']
                provider_id, pix = str(payment['transactionId']), payment['copyPaste']
            if not provider_id or len(provider_id) > 128 or not isinstance(pix, str) or not 20 <= len(pix) <= 5000:
                raise IntegrationError('Resposta inválida.')
            with db() as c:
                c.execute("UPDATE orders SET provider_id=?,pix_code=?,payment=CASE WHEN payment='criando' THEN 'pendente' ELSE payment END WHERE id=?", (provider_id, pix, order_id))
                current=c.execute('SELECT payment FROM orders WHERE id=?',(order_id,)).fetchone()
                if current['payment']=='pendente': queue_utmify(c,order_id,'waiting_payment')
        except PaymentRequestRejected:
            with db() as c:
                c.execute("UPDATE orders SET payment='revisao' WHERE id=? AND payment='criando'", (order_id,))
            abort(502, 'O provedor recusou a cobrança sem CPF. Nenhum Pix foi disponibilizado; consulte o suporte.')
        except (IntegrationError, KeyError, TypeError, ValueError):
            with db() as c:
                c.execute("UPDATE orders SET payment='revisao' WHERE id=? AND payment='criando'", (order_id,))
            abort(503, 'A cobrança está em verificação. Abra o pedido antes de tentar pagar novamente.')
        with db() as c:
            return jsonify(order=order_json(c, owned_order(c, order_id)))

    @bp.post('/api/orders/<order_id>/payment/check')
    def request_check(order_id):
        with db() as c:
            order = owned_order(c, order_id)
        limit('payment-check:' + str(g.user['id']), 10, 60)
        if order['payment'] == 'nao_iniciado':
            abort(409, 'Gere o Pix primeiro.')
        if not configured(order['payment_provider']):
            abort(503, 'Integração ainda não configurada.')
        try:
            check_payment(order_id)
        except IntegrationError:
            abort(503, 'Não foi possível confirmar agora. Tente novamente em instantes.')
        with db() as c:
            return jsonify(order=order_json(c, owned_order(c, order_id)))

    @bp.post('/api/payments/pantera/<order_id>/<token>')
    @bp.post('/api/payments/mistic/<order_id>/<token>')
    def mistic_callback(order_id, token):
        limit('webhook:' + (request.remote_addr or ''), 60, 60)
        if not isinstance(order_id, str) or not re.fullmatch(r'[a-f0-9]{32}', order_id):
            abort(404)
        if not hmac.compare_digest(token, signed_callback(order_id)):
            abort(404)
        data()  # Parse under the 16 KiB request limit; fields are intentionally ignored.
        # Callback data is only a wake-up signal. No payment/amount is trusted here.
        with db() as c:
            row = c.execute('SELECT payment FROM orders WHERE id=?', (order_id,)).fetchone()
            if not row:
                abort(404)
            if row['payment'] != 'nao_iniciado':
                queue_check(c, order_id)
        return jsonify(accepted=True), 202

    def check_payment(order_id):
        with db() as c:
            order = c.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
        if not order or order['payment'] == 'nao_iniciado':
            return True
        if not configured(order['payment_provider']):raise IntegrationError('Provedor não configurado.')
        if order['payment_provider']=='pantera':
            pid=order['provider_id']
            if not pid or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',pid):raise IntegrationError('Cobrança sem identificador; revisão necessária.')
            tx=post_json('https://panterapay-production.up.railway.app/transactions/'+pid+'?nocache=1',None,{'Authorization':app.config['PANTERA_API_KEY']},method='GET')
            if not isinstance(tx,dict):raise IntegrationError('Resposta inválida.')
            if tx.get('id')!=pid or type(tx.get('amount')) is not int or tx['amount']!=order['total'] or tx.get('type')!='DEPOSIT' or tx.get('reason')!='PIX_PAYMENT':raise IntegrationError('Cobrança não confere.')
            states={'PAID':'COMPLETO','PENDING':'PENDENTE','FAILED':'FALHA','CANCELLED':'CANCELADO','EXPIRED':'EXPIRADO','REFUNDED':'DEVOLVIDO'}
            if str(tx.get('status','')).upper() not in states:raise IntegrationError('Status desconhecido.')
            response={'transaction':{'value':Decimal(tx['amount'])/100,'transactionId':pid,'transactionType':'DEPOSITO','transactionMethod':'PIX','transactionState':states[str(tx['status']).upper()]}}
        else:response = mistic('check', {'transactionId': order_id})
        try:
            tx = response['transaction']
            cents = Decimal(str(tx['value'])) * 100
            if not cents.is_finite() or cents != order['total'] or tx['transactionType'] != 'DEPOSITO' or tx['transactionMethod'] != 'PIX':
                raise IntegrationError('Valor ou tipo da transação não confere.')
            provider_id = str(tx['transactionId'])
            if not provider_id or len(provider_id)>128 or (order['provider_id'] and provider_id != order['provider_id']):
                raise IntegrationError('Identificador da transação não confere.')
            status = tx['transactionState']
        except (KeyError, TypeError, InvalidOperation, ValueError) as exc:
            raise IntegrationError('Resposta de pagamento inválida.') from exc
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            order = c.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
            if order['payment'] == 'reembolsado':
                return True
            if status in ('DEVOLVIDO', 'DEVOLVIDO_PARCIAL'):
                c.execute("UPDATE orders SET payment='reembolsado' WHERE id=?", (order_id,))
                queue_utmify(c,order_id,'refunded')
                audit(c, 'payment_refunded', order['user_id'])
                return True
            if status == 'COMPLETO':
                if order['payment'] != 'pago':
                    c.execute("UPDATE orders SET payment='pago',paid_at=?,provider_id=? WHERE id=?", (int(time.time()), provider_id, order_id))
                    for item in c.execute('SELECT * FROM order_items WHERE order_id=?', (order_id,)).fetchall():
                        notify(c, order, item, 'aguardando')
                    queue_utmify(c,order_id,'paid')
                    audit(c, 'payment_confirmed', order['user_id'])
                order = c.execute('SELECT * FROM orders WHERE id=?', (order_id,)).fetchone()
                fulfill(c, order)
                return True
            if status=='EXPIRADO' and order['payment']!='pago':
                c.execute("UPDATE orders SET payment='expirado' WHERE id=?",(order_id,));return True
            if status in ('FALHA', 'CANCELADO') and order['payment'] != 'pago':
                c.execute("UPDATE orders SET payment='falha' WHERE id=?", (order_id,))
                queue_utmify(c,order_id,'refused')
                return True
        with db() as c:
            expire_pix(c,c.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone())
        return False

    @bp.post('/api/admin/orders/<order_id>/items/<int:item_id>/deliver')
    def manual_delivery(order_id, item_id):
        require_admin()
        limit('admin:' + str(g.user['id']), 60, 60)
        body = data()
        content = body.get('content')
        if not isinstance(content, str) or not content.strip() or len(content)>20000 or '\x00' in content:
            abort(400, 'Informe o conteúdo da entrega, até 20.000 caracteres.')
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            order = owned_order(c, order_id)
            if order['payment'] != 'pago':
                abort(409, 'O pagamento precisa estar confirmado pela Mistic Pay.')
            item = c.execute('SELECT * FROM order_items WHERE order_id=? AND id=?', (order_id, item_id)).fetchone()
            if not item or item['mode'] != 'manual':
                abort(409, 'Use o estoque para os itens automáticos.')
            if item['delivered_at']:
                abort(409, 'Este item já foi entregue.')
            c.execute('UPDATE order_items SET delivered_at=?,delivery_text=? WHERE id=?',
                      (int(time.time()), seal(content, key, 'order_delivery'), item_id))
            notify(c, order, item, 'entregue')
            audit(c, 'manual_delivery', g.user['id'])
        return jsonify(ok=True)

    @bp.get('/api/orders/<order_id>/items/<int:item_id>/download')
    def download(order_id, item_id):
        with db() as c:
            order = owned_order(c, order_id)
            item = c.execute('SELECT * FROM order_items WHERE order_id=? AND id=?', (order_id, item_id)).fetchone()
            if not item or not item['delivered_at'] or order['payment'] != 'pago':
                abort(404, 'Entrega ainda não disponível.')
            plaintext_delivery = unseal(item['delivery_text'], key, 'order_delivery')
            content = f"NziStore — pedido {order_id}\n{item['name']}\n\n{plaintext_delivery}\n"
        return send_file(io.BytesIO(content.encode('utf-8')), mimetype='text/plain; charset=utf-8',
                         as_attachment=True, download_name=f'pedido-{order_id}-{item_id}.txt', max_age=0)

    @bp.get('/api/orders/<order_id>/messages')
    def get_messages(order_id):
        try:
            after = max(0, int(request.args.get('after', 0)))
        except ValueError:
            abort(400)
        with db() as c:
            require_chat(c, order_id)
            peer=c.execute('SELECT * FROM chat_presence WHERE order_id=? AND role=?',(order_id,'customer' if g.user['role']=='admin' else 'admin')).fetchone()
            rows = c.execute('SELECT id,role,text,created FROM order_messages WHERE order_id=? AND id>? ORDER BY id LIMIT 100', (order_id, after)).fetchall()
            messages = [{**dict(r), 'text': unseal(r['text'], key, 'order_chat')} for r in rows]
        return jsonify(messages=messages, has_more=len(messages)==100, peer=dict(online=bool(peer and peer['seen']>time.time()-15),typing=bool(peer and peer['typing_until']>time.time()),read_id=peer['read_id'] if peer else 0))

    @bp.post('/api/orders/<order_id>/messages')
    def send_message(order_id):
        require_user()
        body = data()
        text, request_key = body.get('text'), body.get('request_key', '')
        if not isinstance(text, str) or not text.strip() or len(text)>2000:
            abort(400, 'Escreva uma mensagem de até 2.000 caracteres.')
        if not isinstance(request_key, str) or not re.fullmatch(r'[a-zA-Z0-9-]{16,80}', request_key):
            abort(400)
        limit('chat:' + str(g.user['id']), 20, 60)
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            require_chat(c, order_id)
            c.execute('INSERT OR IGNORE INTO order_messages(order_id,user_id,role,text,request_key,created) VALUES(?,?,?,?,?,?)',
                      (order_id, g.user['id'], g.user['role'], seal(text.strip(), key, 'order_chat'), request_key, int(time.time())))
        return jsonify(ok=True), 201

    def process_jobs(batch=10):
        """Durable outbox with leases. Retry without holding DB locks during HTTP."""
        for _ in range(batch):
            lease = secrets.token_hex(16)
            now = int(time.time())
            with db() as c:
                c.execute('BEGIN IMMEDIATE')
                job = c.execute('''SELECT * FROM commerce_jobs WHERE done=0 AND next_at<=? AND leased_until<=?
                                   AND (kind!='discord' OR ?=1) AND (kind!='payment' OR ?=1) AND (kind!='utmify' OR ?=1)
                                   AND (kind!='utmify' OR NOT EXISTS(SELECT 1 FROM commerce_jobs older WHERE older.kind='utmify' AND older.order_id=commerce_jobs.order_id AND older.id<commerce_jobs.id AND older.done=0)) ORDER BY id LIMIT 1''',
                                (now, now, bool(webhook), configured('mistic') or configured('pantera'), bool(app.config['UTMIFY_API_TOKEN']))).fetchone()
                if not job:
                    return
                c.execute('UPDATE commerce_jobs SET lease=?,leased_until=? WHERE id=?', (lease, now+60, job['id']))
            error, done, delay = None, False, 30
            try:
                if job['kind'] == 'payment':
                    done = check_payment(job['order_id'])
                    delay = 60
                elif job['kind']=='utmify':
                    post_json('https://api.utmify.com.br/api-credentials/orders',json.loads(job['payload']),{'x-api-token':app.config['UTMIFY_API_TOKEN']})
                    done=True
                else:
                    payload = json.loads(job['payload'])
                    content = json.dumps(payload, ensure_ascii=False, indent=2)
                    post_json(webhook + '?wait=true', {'content': content, 'allowed_mentions': {'parse': []}})
                    done = True
            except IntegrationError:
                error = 'Falha na integração; nova tentativa agendada.'
                delay = min(3600, 30 * 2 ** min(job['attempts'], 7))
            except Exception:
                error = 'Processamento interrompido; nova tentativa agendada.'
                delay = 300
                app.logger.error('Falha no job %s (%s)', job['id'], job['kind'])
            with db() as c:
                c.execute('''UPDATE commerce_jobs SET done=?,attempts=attempts+1,next_at=?,last_error=?,lease=NULL,leased_until=0
                             WHERE id=? AND lease=?''', (done, int(time.time())+delay, error, job['id'], lease))

    app.extensions['commerce'] = dict(check_payment=check_payment, process_jobs=process_jobs, fulfill=fulfill)
    app.register_blueprint(bp)
