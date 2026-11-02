import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor

import pytest
import commerce
from server import create_app, new_password, new_pin

ORIGIN = {'Origin':'https://shop.example.com'}

@pytest.fixture
def shop(tmp_path, monkeypatch):
    app = create_app({'TESTING':True,'DATA_DIR':str(tmp_path/'data'),'UPLOAD_DIR':str(tmp_path/'uploads'),
                      'DB_KEY':'ab'*32,'PUBLIC_ORIGIN':'https://shop.example.com',
                      'MISTIC_CLIENT_ID':'pk_test','MISTIC_CLIENT_SECRET':'sk_test',
                      'DISCORD_WEBHOOK_URL':'https://discord.com/api/webhooks/123/test-token'})
    remote, sent = {}, []
    def external(url, payload, headers=None):
        if url.startswith('https://discord.com/'):
            sent.append(payload)
            return {'id':'message'}
        assert headers['Authorization'].startswith('Basic ')
        if url.endswith('/create'):
            assert 'payerDocument' not in payload
            assert 'cliente@example.com' in payload['description']
            oid=payload['transactionId']
            remote[oid]={'transactionId':'mistic-'+oid, 'value':payload['amount'], 'transactionType':'DEPOSITO',
                         'transactionMethod':'PIX', 'transactionState':'PENDENTE'}
            return {'data':{'transactionId':'mistic-'+oid,'copyPaste':'000201010212test-pix-code'}}
        return {'transaction':remote[payload['transactionId']]}
    monkeypatch.setattr(commerce,'post_json',external)
    with app.extensions['db']() as c:
        for email,role in [('admin','admin'),('alice@example.com','customer'),('bob@example.com','customer')]:
            c.execute('INSERT INTO users(email,password,role) VALUES(?,?,?)',(email,new_password('long-secret-password'),role))
        c.execute("INSERT INTO admin_credentials SELECT id,? FROM users WHERE role='admin'", (new_pin('123456'),))
    def login(email):
        client=app.test_client()
        response=client.post('/api/auth/login',json={'email':email,'password':'long-secret-password','pin':'123456'},headers=ORIGIN)
        assert response.status_code==200
        client.csrf=response.json['csrf']
        return client
    return app,login('admin'),login('alice@example.com'),login('bob@example.com'),remote,sent

def post(client,path,body=None,method='POST'):
    return client.open(path,method=method,json=body or {},headers={**ORIGIN,'X-CSRF-Token':client.csrf})

def product(admin,mode='automatic',category='Streamings',quantity=0):
    r=post(admin,'/api/products',dict(name='Produto teste',description='Descrição',price=1990,category=category,image='',delivery_mode=mode,robux_quantity=quantity))
    assert r.status_code==200,r.json
    return r.json['id']

def stock(admin,pid,content='segredo-login-1'):
    r=post(admin,f'/api/admin/products/{pid}/stock',{'content':content})
    assert r.status_code==201,r.json

def order(client,pid,**extra):
    body=dict(items=[{'product_id':pid,'quantity':1}],expected_total=1990,request_key='unique-checkout-00001',**extra)
    response=post(client,'/api/orders',body)
    assert response.status_code==201,response.json
    return response.json['order'],body

def start_payment(client,oid):
    r=post(client,f'/api/orders/{oid}/payment',{'payer_name':'Cliente Teste','payer_email':'cliente@example.com','payer_email_confirmation':'cliente@example.com','terms_accepted':True})
    assert r.status_code==200,r.json

def paid(shop,client,oid):
    app,_,_,_,remote,_=shop
    remote[oid]['transactionState']='COMPLETO'
    r=post(client,f'/api/orders/{oid}/payment/check')
    assert r.status_code==200,r.json
    return r.json['order']

def test_private_order_chat_and_delivery(shop):
    app,admin,alice,bob,remote,sent=shop
    pid=product(admin); stock(admin,pid)
    o,body=order(alice,pid); oid=o['id']; item=o['items'][0]['id']
    assert post(alice,'/api/orders',body).json['order']['id']==oid
    changed={**body,'expected_total':1}
    assert post(alice,'/api/orders',changed).status_code==409
    assert bob.get('/api/orders/'+oid).status_code==404
    assert bob.get('/api/orders/'+oid+'/messages').status_code==404
    assert post(bob,'/api/orders/'+oid+'/messages',{'text':'hack','request_key':'message-key-00001'}).status_code==404
    assert bob.get(f'/api/orders/{oid}/items/{item}/download').status_code==404
    assert alice.get(f'/api/orders/{oid}/items/{item}/download').status_code==404
    assert alice.get(f'/api/admin/products/{pid}/delivery').status_code==403
    assert 'segredo-login' not in alice.get('/api/products').get_data(as_text=True)
    start_payment(alice,oid)
    paid(shop,alice,oid)
    for who,text,key in [(alice,'Preciso de ajuda <script>','message-key-00001'),(admin,'Olá, vamos ajudar.','message-key-00002')]:
        assert post(who,f'/api/orders/{oid}/messages',{'text':text,'request_key':key}).status_code==201
    messages=alice.get(f'/api/orders/{oid}/messages').json['messages']
    assert [m['role'] for m in messages]==['customer','admin']
    start_payment(alice,oid)
    result=paid(shop,alice,oid)
    assert result['status']=='entregue'
    download=alice.get(f'/api/orders/{oid}/items/{item}/download')
    assert download.status_code==200 and 'segredo-login-1' in download.get_data(as_text=True)
    assert 'attachment' in download.headers['Content-Disposition']
    assert download.headers['Cache-Control']=='no-store'
    assert bob.get(f'/api/orders/{oid}/items/{item}/download').status_code==404
    assert 'segredo-login-1' not in alice.get('/api/orders/'+oid).get_data(as_text=True)
    with app.app_context():
        app.extensions['commerce']['process_jobs']()
    statuses=[json.loads(m['content'])['status'] for m in sent]
    assert statuses==['aguardando','entregue']
    assert all(m['allowed_mentions']=={'parse':[]} for m in sent)
    assert 'segredo-login-1' not in json.dumps(sent)
    paid(shop,alice,oid)
    with app.extensions['db']() as c:
        assert c.execute('SELECT COUNT(*) FROM commerce_jobs WHERE kind="discord"').fetchone()[0]==2


def test_payment_validation_and_forged_callback(shop):
    app,admin,alice,bob,remote,sent=shop
    pid=product(admin,'manual'); o,_=order(alice,pid); oid=o['id']
    assert post(alice,f'/api/orders/{oid}/payment',{'payer_name':'Test','payer_email':'invalido'}).status_code==400
    start_payment(alice,oid)
    remote[oid]['transactionState']='COMPLETO'
    remote[oid]['value']=.01
    assert post(alice,f'/api/orders/{oid}/payment/check').status_code==503
    assert alice.get('/api/orders/'+oid).json['order']['payment']=='pendente'
    assert app.test_client().post(f'/api/payments/mistic/{oid}/fake',json={'status':'COMPLETO'}).status_code==404
    token=hmac.new(('ab'*32).encode(),('mistic:'+oid).encode(),hashlib.sha256).hexdigest()
    assert app.test_client().post(f'/api/payments/mistic/{oid}/{token}',json={'status':'COMPLETO','value':1990}).status_code==202
    assert alice.get('/api/orders/'+oid).json['order']['payment']=='pendente'
    remote[oid]['value']=19.90; remote[oid]['transactionId']='wrong-id'
    assert post(alice,f'/api/orders/{oid}/payment/check').status_code==503


def test_manual_delivery_requires_payment_and_admin(shop):
    app,admin,alice,bob,remote,sent=shop
    pid=product(admin,'manual'); o,_=order(alice,pid); oid=o['id']; item=o['items'][0]['id']
    path=f'/api/admin/orders/{oid}/items/{item}/deliver'
    assert post(admin,path,{'content':'entrega manual'}).status_code==409
    assert post(alice,path,{'content':'entrega manual'}).status_code==403
    start_payment(alice,oid); result=paid(shop,alice,oid)
    assert result['status']=='aguardando'
    assert post(admin,path,{'content':'entrega manual'}).status_code==200
    assert post(admin,path,{'content':'outra entrega'}).status_code==409
    assert 'entrega manual' in alice.get(f'/api/orders/{oid}/items/{item}/download').get_data(as_text=True)
    remote[oid]['transactionState']='DEVOLVIDO'
    assert post(alice,f'/api/orders/{oid}/payment/check').status_code==200
    assert alice.get(f'/api/orders/{oid}/items/{item}/download').status_code==404


def test_robux_requires_signed_recipient_and_notifies_quantity(shop):
    app,admin,alice,bob,remote,sent=shop
    pid=product(admin,'manual','Robux',1000)
    body=dict(items=[{'product_id':pid,'quantity':2}],expected_total=3980,request_key='robux-checkout-0001',roblox_confirmed=True,roblox_ticket='fake')
    assert post(alice,'/api/orders',body).status_code==400
    body['roblox_ticket']=app.extensions['roblox_signer'].dumps({'id':156,'username':'builderman','displayName':'builderman'})
    r=post(alice,'/api/orders',body); assert r.status_code==201,r.json
    oid=r.json['order']['id']; start_payment(alice,oid); paid(shop,alice,oid)
    with app.app_context(): app.extensions['commerce']['process_jobs']()
    payload=json.loads(sent[0]['content'])
    assert payload['nickname_roblox']=='builderman' and payload['robux_quantity']==2000
    assert payload['price']=='39.80'


def test_concurrent_payment_cannot_reuse_stock_and_restock_fulfills(shop):
    app,admin,alice,bob,remote,sent=shop
    pid=product(admin); stock(admin,pid)
    a,_=order(alice,pid); b,_=order(bob,pid)
    for client,o in [(alice,a),(bob,b)]:
        start_payment(client,o['id']); remote[o['id']]['transactionState']='COMPLETO'
    def confirm(oid):
        with app.app_context(): return app.extensions['commerce']['check_payment'](oid)
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert all(pool.map(confirm,[a['id'],b['id']]))
    with app.extensions['db']() as c:
        assert c.execute('SELECT COUNT(*) FROM order_items WHERE delivered_at IS NOT NULL').fetchone()[0]==1
        assert c.execute('SELECT COUNT(*) FROM delivery_stock WHERE item_id IS NOT NULL').fetchone()[0]==1
    stock(admin,pid,'segredo-login-2')
    with app.extensions['db']() as c:
        rows=c.execute('SELECT delivery_text FROM order_items').fetchall()
        assert len(set(r['delivery_text'] for r in rows))==2
    assert post(admin,f'/api/admin/products/{pid}/stock',{'content':'segredo-login-1'}).status_code==409


def test_uncertain_payment_creation_is_not_repeated(shop,monkeypatch):
    app,admin,alice,bob,remote,sent=shop
    pid=product(admin,'manual'); o,_=order(alice,pid); oid=o['id']; calls=[]
    def fail(*args,**kwargs):
        calls.append(args); raise commerce.IntegrationError('timeout')
    monkeypatch.setattr(commerce,'post_json',fail)
    payload={'payer_name':'Teste Cliente','payer_email':'cliente@example.com','payer_email_confirmation':'cliente@example.com','terms_accepted':True}
    assert post(alice,f'/api/orders/{oid}/payment',payload).status_code==503
    assert post(alice,f'/api/orders/{oid}/payment',payload).status_code==200
    assert len(calls)==1
    assert alice.get('/api/orders/'+oid).json['order']['payment']=='revisao'


def test_discord_failure_does_not_rollback_delivery(shop,monkeypatch):
    app,admin,alice,bob,remote,sent=shop
    pid=product(admin); stock(admin,pid)
    o,_=order(alice,pid); start_payment(alice,o['id']); paid(shop,alice,o['id'])
    def fail(*args,**kwargs): raise commerce.IntegrationError('timeout')
    monkeypatch.setattr(commerce,'post_json',fail)
    with app.app_context(): app.extensions['commerce']['process_jobs']()
    with app.extensions['db']() as c:
        jobs=c.execute("SELECT done,attempts FROM commerce_jobs WHERE kind='discord'").fetchall()
        assert all(r['done']==0 and r['attempts']==1 for r in jobs)
    assert alice.get('/api/orders/'+o['id']).json['order']['status']=='entregue'

def test_stock_text_and_chat_csrf_never_public(shop):
    app,admin,alice,bob,remote,sent=shop
    pid=product(admin); stock(admin,pid,'very-private-content')
    o,_=order(alice,pid); oid=o['id']
    assert 'very-private-content' not in admin.get(f'/api/admin/products/{pid}/delivery').get_data(as_text=True)
    assert 'very-private-content' not in alice.get('/api/products').get_data(as_text=True)
    assert alice.post(f'/api/orders/{oid}/messages',json={'text':'no token','request_key':'message-no-token1'},headers=ORIGIN).status_code==403
    assert app.test_client().get(f'/api/orders/{oid}/messages').status_code==401
    assert app.test_client().get(f'/api/orders/{oid}/items/1/download').status_code==401


def test_price_tampering_and_missing_gateway(shop):
    app,admin,alice,bob,remote,sent=shop
    pid=product(admin,'manual')
    bad=dict(items=[{'product_id':pid,'quantity':1}],expected_total=1,request_key='bad-checkout-00001')
    assert post(alice,'/api/orders',bad).status_code==409
    o,_=order(alice,pid)
    app.config['MISTIC_CLIENT_SECRET']=''
    assert post(alice,f"/api/orders/{o['id']}/payment",{'payer_name':'Cliente Teste','payer_email':'cliente@example.com','payer_email_confirmation':'cliente@example.com','terms_accepted':True}).status_code==503
    assert not remote


def test_category_management_is_admin_only_and_preserves_robux_rules(shop):
    app,admin,alice,*_=shop
    payload={'title':'Robux personalizados','image':''}
    path='/api/admin/categories/robux'
    assert post(alice,path,payload,method='PUT').status_code==403
    assert admin.put(path,json=payload,headers=ORIGIN).status_code==403
    assert post(admin,path,{'title':'Teste','image':'https://example.com/image.png'},method='PUT').status_code==400
    assert post(admin,path,payload,method='PUT').status_code==200
    category=next(c for c in alice.get('/api/categories').json if c['slug']=='robux')
    assert category['title']=='Robux personalizados' and category['name']=='Robux'
    import base64
    from pathlib import Path
    photo=post(admin,'/api/upload',{'data':base64.b64encode(Path('static/pix.png').read_bytes()).decode()})
    assert photo.status_code==200
    assert post(admin,path,{**payload,'image':photo.json['url']},method='PUT').status_code==200
    assert alice.get(photo.json['url']).status_code==200
    assert next(c for c in alice.get('/api/categories').json if c['slug']=='robux')['image']==photo.json['url']
    pid=product(admin,'manual','Robux',1000)
    response=post(alice,'/api/orders',dict(items=[{'product_id':pid,'quantity':1}],expected_total=1990,request_key='category-robux-0001'))
    assert response.status_code==400


def test_gateway_rejection_without_cpf_is_reported(shop,monkeypatch):
    app,admin,alice,*_=shop
    pid=product(admin,'manual'); o,_=order(alice,pid)
    def reject(url,payload,headers=None):
        assert 'payerDocument' not in payload
        assert 'cliente@example.com' in payload['description']
        raise commerce.PaymentRequestRejected('validation')
    monkeypatch.setattr(commerce,'post_json',reject)
    response=post(alice,f"/api/orders/{o['id']}/payment",{'payer_name':'Cliente Teste','payer_email':'cliente@example.com','payer_email_confirmation':'cliente@example.com','terms_accepted':True})
    assert response.status_code==502 and 'sem CPF' in response.json['error']
    assert alice.get('/api/orders/'+o['id']).json['order']['payment']=='revisao'


def test_coupon_is_priced_on_server_and_payment_matches(shop):
    app,admin,alice,*_=shop
    pid=product(admin,'manual')
    body=dict(items=[{'product_id':pid,'quantity':2}],expected_total=3582,request_key='coupon-checkout-0001',coupon='DESCONTO10')
    response=post(alice,'/api/orders',body)
    assert response.status_code==201
    order=response.json['order']
    assert order['total']==3582 and order['coupon']['discount']==398
    assert order['items'][0]['unit_price']==1791
    start_payment(alice,order['id'])
    assert paid(shop,alice,order['id'])['payment']=='pago'
    assert post(alice,'/api/orders',{**body,'request_key':'coupon-checkout-0002','coupon':'FAKE'}).status_code==400
    assert post(alice,'/api/orders',{**body,'request_key':'coupon-checkout-0003','expected_total':1}).status_code==409
    assert post(alice,'/api/orders',body).json['order']['id']==order['id']


def test_bola_owner_only_payment_and_strict_schema(shop):
    app,admin,alice,bob,*_=shop
    pid=product(admin,'manual')
    o,_=order(alice,pid)
    oid=o['id']
    # Admin can view order for support, but cannot initiate payment on customer's order
    assert post(admin,f'/api/orders/{oid}/payment',{'payer_name':'Admin','payer_email':'admin@example.com'}).status_code==403
    # Bob cannot initiate payment or check payment on Alice's order
    assert post(bob,f'/api/orders/{oid}/payment',{'payer_name':'Bob','payer_email':'bob@example.com'}).status_code==404
    assert post(bob,f'/api/orders/{oid}/payment/check').status_code==404
    # Malformed order IDs are rejected with 404
    assert alice.get('/api/orders/not-a-valid-hex-order-id').status_code==404
    # Unexpected fields in order creation payload are rejected
    bad=dict(items=[{'product_id':pid,'quantity':1}],expected_total=1990,request_key='extra-field-00001',payment='pago')
    assert post(alice,'/api/orders',bad).status_code==400


def test_admin_metrics_excludes_unpaid_and_refunded_orders(shop):
    app,admin,alice,bob,remote,sent=shop
    pid=product(admin,'manual'); first,_=order(alice,pid)
    start_payment(alice,first['id']); paid(shop,alice,first['id'])
    second,_=order(bob,pid)
    response=admin.get('/api/admin/metrics?days=7')
    assert response.status_code==200
    metrics=response.json
    assert metrics['revenue']==1990 and metrics['sales']==1 and metrics['orders']==2
    assert metrics['buyers']==1 and metrics['recurring']==0
    assert metrics['top_products'][0]['quantity']==1
    assert metrics['top_products'][0]['revenue']==1990
    assert metrics['approval_rate']==50 and metrics['average_ticket']==1990
    assert metrics['pending_deliveries']==1 and metrics['customers']==2
    assert sum(day['revenue'] for day in metrics['series'])==1990
    assert len(metrics['series'])==7 and metrics['timezone']=='America/Sao_Paulo'
    with app.extensions['db']() as c:
        c.execute("UPDATE orders SET payment='reembolsado' WHERE id=?",(first['id'],))
    assert admin.get('/api/admin/metrics?days=7').json['revenue']==0
    assert admin.get('/api/admin/metrics?days=999').status_code==400
    for path in ['/api/admin/metrics','/api/admin/conversations','/api/admin/customers']:
        assert alice.get(path).status_code==403
        assert app.test_client().get(path).status_code==401


def test_admin_inbox_and_customer_directory(shop):
    app,admin,alice,bob,remote,sent=shop
    pid=product(admin,'manual'); o,_=order(alice,pid); oid=o['id']
    start_payment(alice,oid); paid(shop,alice,oid)
    assert post(alice,f'/api/orders/{oid}/messages',{'text':'Preciso de suporte','request_key':'inbox-message-key-001'}).status_code==201
    result=admin.get('/api/admin/conversations?waiting=1').json
    assert len(result['conversations'])==1 and result['conversations'][0]['last_role']=='customer'
    assert result['conversations'][0]['preview']=='Preciso de suporte'
    assert admin.get('/api/admin/metrics').json['waiting_conversations']==1
    assert admin.get('/api/admin/conversations?q=absent').json['conversations']==[]
    assert post(admin,f'/api/orders/{oid}/messages',{'text':'Vamos ajudar.','request_key':'inbox-response-key-001'}).status_code==201
    assert admin.get('/api/admin/conversations?waiting=1').json['conversations']==[]
    assert alice.get(f'/api/orders/{oid}/messages').json['messages'][-1]['text']=='Vamos ajudar.'
    assert bob.get(f'/api/orders/{oid}/messages').status_code==404
    directory=admin.get('/api/admin/customers').json['customers']
    assert len(directory)==2 and all(set(c)=={'id','email','orders','paid_total'} for c in directory)
    assert admin.get('/api/admin/customers?page=0').status_code==400
    assert admin.get('/api/admin/conversations?page=abc').status_code==400


def test_chat_requires_purchase_and_tracks_peer(shop):
    app,admin,alice,bob,remote,sent=shop
    pid=product(admin,'manual');o,_=order(alice,pid);oid=o['id']
    assert not o['chat_enabled']
    for client in (admin,alice):
        assert client.get(f'/api/orders/{oid}/messages').status_code==409
        assert post(client,f'/api/orders/{oid}/messages',{'text':'hello','request_key':'locked-message-key1'}).status_code==409
        assert post(client,f'/api/orders/{oid}/chat-state',{'typing':True}).status_code==409
    assert admin.get('/api/admin/conversations').json['conversations']==[]
    start_payment(alice,oid);paid(shop,alice,oid)
    assert alice.get('/api/orders/'+oid).json['order']['chat_enabled']
    assert post(alice,f'/api/orders/{oid}/messages',{'text':'Olá','request_key':'paid-message-key01'}).status_code==201
    mid=admin.get(f'/api/orders/{oid}/messages').json['messages'][0]['id']
    assert post(admin,f'/api/orders/{oid}/chat-state',{'typing':True,'read_id':mid}).status_code==200
    peer=alice.get(f'/api/orders/{oid}/messages').json['peer']
    assert peer=={'online':True,'typing':True,'read_id':mid}
    assert post(bob,f'/api/orders/{oid}/chat-state',{'typing':True}).status_code==404
    with app.extensions['db']() as c:
        c.execute("UPDATE orders SET payment='reembolsado' WHERE id=?",(oid,))
    assert alice.get(f'/api/orders/{oid}/messages').status_code==200


def test_edit_coupon_checkout_and_disable(shop):
    app,admin,alice,bob,remote,sent=shop
    config={'code':'NZI20','percent':20,'enabled':True}
    assert post(alice,'/api/admin/coupon',config,'PUT').status_code==403
    assert post(admin,'/api/admin/coupon',{**config,'percent':100},'PUT').status_code==400
    assert post(admin,'/api/admin/coupon',config,'PUT').status_code==200
    assert alice.get('/api/coupon').json['coupon']['code']=='NZI20'
    pid=product(admin,'manual')
    body={'items':[{'product_id':pid,'quantity':2}],'expected_total':3184,'coupon':'NZI20','request_key':'coupon-new-key-001'}
    result=post(alice,'/api/orders',body)
    assert result.status_code==201,result.json
    assert result.json['order']['items'][0]['unit_price']==1592
    assert post(admin,'/api/admin/coupon',{**config,'enabled':False},'PUT').status_code==200
    assert alice.get('/api/coupon').json['coupon'] is None
    assert post(alice,'/api/orders',body).status_code==200 # existing order is unchanged
    assert post(bob,'/api/orders',body).status_code==400


def test_email_report_only_paid_authorized_and_csv_safe(shop):
    from datetime import datetime
    from zoneinfo import ZoneInfo
    app,admin,alice,bob,remote,sent=shop
    pid=product(admin,'manual');o,_=order(alice,pid);order(bob,pid)
    start_payment(alice,o['id']);paid(shop,alice,o['id'])
    day=datetime.now(ZoneInfo('America/Sao_Paulo')).strftime('%Y-%m-%d')
    path=f'/api/admin/sales/emails.csv?from={day}&to={day}'
    assert alice.get(path).status_code==403
    assert app.test_client().get(path).status_code==401
    response=admin.get(path)
    assert response.status_code==200 and 'no-store' in response.headers['Cache-Control']
    csv=response.get_data(as_text=True)
    assert 'alice@example.com;1;19.90' in csv and 'bob@example.com' not in csv
    assert admin.get('/api/admin/sales/emails.csv?from=bad&to=bad').status_code==400
    with app.extensions['db']() as c: c.execute("UPDATE orders SET email='=cmd@example.com' WHERE id=?",(o['id'],))
    assert "'=cmd@example.com" in admin.get(path).get_data(as_text=True)


def test_utmify_consent_payload_retry_and_status_order(shop,monkeypatch):
    from urllib.parse import quote
    app,admin,alice,bob,remote,sent=shop
    app.config['UTMIFY_API_TOKEN']='test-utm-token'
    alice.set_cookie('nzi-cookie-preferences',quote(json.dumps({'version':2,'analytics':True})))
    pid=product(admin,'manual');o,_=order(alice,pid,tracking={'utm_source':'campaign-test'});oid=o['id']
    start_payment(alice,oid);paid(shop,alice,oid)
    original=commerce.post_json;received=[];fail=[True]
    def external(url,payload,headers=None):
        if 'api.utmify.com.br' not in url:return original(url,payload,headers)
        assert headers=={'x-api-token':'test-utm-token'}
        if fail[0]:raise commerce.IntegrationError('temporary')
        received.append(payload);return {}
    monkeypatch.setattr(commerce,'post_json',external)
    with app.app_context():app.extensions['commerce']['process_jobs'](10)
    assert not received
    with app.extensions['db']() as c:
        assert c.execute("SELECT attempts FROM commerce_jobs WHERE job_key=?",('utmify:'+oid+':paid',)).fetchone()[0]==0
        c.execute("UPDATE commerce_jobs SET next_at=0 WHERE kind='utmify'")
    fail[0]=False
    with app.app_context():app.extensions['commerce']['process_jobs'](10)
    assert [p['status'] for p in received]==['waiting_payment','paid']
    assert received[-1]['commission']['totalPriceInCents']==1990
    assert received[-1]['customer']['document'] is None
    assert received[-1]['trackingParameters']['utm_source']=='campaign-test'
    assert received[-1]['approvedDate'] and received[0]['approvedDate'] is None
    b,_=order(bob,pid,tracking={'utm_source':'ignored'})
    start_payment(bob,b['id']);paid(shop,bob,b['id'])
    with app.extensions['db']() as c:
        assert c.execute("SELECT COUNT(*) FROM commerce_jobs WHERE kind='utmify' AND order_id=?",(b['id'],)).fetchone()[0]==0


def test_roblox_games_and_product_assignment(shop):
    app,admin,alice,bob,_,_=shop
    endpoint='/api/admin/roblox/subcategories'
    assert post(alice,endpoint,{'title':'Blox Fruits'}).status_code==403
    assert post(admin,endpoint,{'title':'Blox Fruits','image':'https://evil.test/image'}).status_code==400
    result=post(admin,endpoint,{'title':'Blox Fruits','image':''});assert result.status_code==200
    gid=result.json['id']
    games=alice.get('/api/roblox/subcategories').json
    assert games[0]['slug']=='blox-fruits'
    assert alice.get('/roblox/blox-fruits').status_code==200
    assert alice.get('/roblox/missing').status_code==404
    assert alice.get('/roblox').status_code==200
    payload=dict(name='Conta Blox',description='Descrição',price=1990,category='Contas Roblox',image='',subcategory_id=gid)
    saved=post(admin,'/api/products',payload);assert saved.status_code==200
    pid=saved.json['id']
    assert next(p for p in alice.get('/api/products').json if p['id']==pid)['subcategory_id']==gid
    assert post(admin,endpoint+'/'+str(gid),{},'DELETE').status_code==409
    assert post(admin,'/api/products',{**payload,'category':'Streamings'}).status_code==400
    assert post(admin,'/api/products',{**payload,'subcategory_id':999999}).status_code==400
    assert post(admin,endpoint+'/'+str(gid),{'title':'Blox Fruits atualizado','image':''},'PUT').status_code==200
    assert alice.get('/api/roblox/subcategories').json[0]['slug']=='blox-fruits'
    assert post(admin,'/api/products/'+str(pid),{**payload,'subcategory_id':None},'PUT').status_code==200
    assert post(admin,endpoint+'/'+str(gid),{},'DELETE').status_code==200
    assert next(c for c in alice.get('/api/categories').json if c['name']=='Contas Roblox')['title']=='Roblox'


def test_consented_visits_and_geography(shop,monkeypatch):
    import insights
    from urllib.parse import quote
    app,admin,alice,_,_,_=shop
    visitor=app.test_client()
    visitor.csrf=""
    token='a'*32
    assert post(visitor,'/api/analytics/visit',{'visitor':token}).json=={'recorded':False}
    visitor.set_cookie('nzi-cookie-preferences',quote(json.dumps({'version':2,'analytics':True})))
    assert post(visitor,'/api/analytics/visit',{'visitor':'bad'}).status_code==400
    assert post(visitor,'/api/analytics/visit',{'visitor':token,'state':'SP'}).status_code==200
    assert post(visitor,'/api/analytics/visit',{'visitor':token}).status_code==200
    metrics=admin.get('/api/admin/metrics').json
    assert metrics['visits']==1 and metrics['geo_unknown']==1 and metrics['states']==[]
    class Reader:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,ip):return {'country':{'iso_code':'BR'},'subdivisions':[{'iso_code':'SP'}]}
    app.config['GEOIP_DATABASE_PATH']='/tmp/test.mmdb'
    monkeypatch.setattr(insights.maxminddb,'open_database',lambda path:Reader())
    r=visitor.post('/api/analytics/visit',json={'visitor':'b'*32},headers=ORIGIN,environ_overrides={'REMOTE_ADDR':'8.8.8.8'})
    assert r.status_code==200
    metrics=admin.get('/api/admin/metrics').json
    assert metrics['visits']==2 and metrics['states']==[{'state':'SP','visits':1}]
    with app.extensions['db']() as c:
        row=c.execute('SELECT * FROM daily_visits LIMIT 1').fetchone()
        assert set(row.keys())=={'day','visitor','state','country'} and row['visitor']!=token


def test_order_creation_pending_limit(shop):
    app, admin, alice, *_ = shop
    pid = product(admin, 'manual')
    for i in range(3):
        res = post(alice, '/api/orders', {
            'items': [{'product_id': pid, 'quantity': 1}],
            'expected_total': 1990,
            'request_key': f'pending-limit-key-{i:04d}'
        })
        assert res.status_code == 201
    # 4th unpaid order within the window must be rate-limited (429)
    blocked = post(alice, '/api/orders', {
        'items': [{'product_id': pid, 'quantity': 1}],
        'expected_total': 1990,
        'request_key': 'pending-limit-key-0099'
    })
    assert blocked.status_code == 429


def test_product_variants_compare_price_video_min_max_and_stock_edit(shop):
    app, admin, alice, *_ = shop
    # 1. Reject invalid compare_price (<= real price) and untrusted video URLs
    assert post(admin, '/api/products', {
        'name': 'Dragon ou Kitsune',
        'description': 'Conta Blox Fruits',
        'price': 1590,
        'compare_price': 1500,
        'category': 'Streamings',
        'image': ''
    }).status_code == 400
    assert post(admin, '/api/products', {
        'name': 'Dragon ou Kitsune',
        'description': 'Conta Blox Fruits',
        'price': 1590,
        'video_url': 'https://evil.example/video.mp4',
        'category': 'Streamings',
        'image': ''
    }).status_code == 400

    # 2. Save normal product with compare_price, YouTube video, min/max quantity, and automatic stock
    saved = post(admin, '/api/products', {
        'name': 'Dragon, Kitsune ou T-Rex + Level Máximo',
        'description': 'Entrega imediata.',
        'price': 1590,
        'compare_price': 2290,
        'video_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        'min_quantity': 2,
        'max_quantity': 4,
        'has_variants': False,
        'category': 'Streamings',
        'image': '',
        'delivery_mode': 'automatic'
    })
    assert saved.status_code == 200
    pid = saved.json['id']
    prod = next(p for p in alice.get('/api/products').json if p['id'] == pid)
    assert prod['compare_price'] == 2290
    assert prod['video_url'] == 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ'
    assert prod['min_quantity'] == 2 and prod['max_quantity'] == 4

    # 3. Add and edit stock unit via /dashboard endpoints
    for idx in range(4):
        assert post(admin, f'/api/admin/products/{pid}/stock', {'content': f'login-{idx}:senha-{idx}'}).status_code == 201
    delivery = admin.get(f'/api/admin/products/{pid}/delivery').json
    stock_id = delivery['stock'][0]['id']
    unit_res = admin.get(f'/api/admin/products/{pid}/stock/{stock_id}')
    assert unit_res.status_code == 200 and unit_res.json['content'] == 'login-0:senha-0'
    assert post(admin, f'/api/admin/products/{pid}/stock/{stock_id}', {'content': 'login-editado:nova-senha'}, 'PUT').status_code == 200
    assert admin.get(f'/api/admin/products/{pid}/stock/{stock_id}').json['content'] == 'login-editado:nova-senha'

    # 4. Enforce min_quantity and max_quantity on order creation
    assert post(alice, '/api/orders', {
        'items': [{'product_id': pid, 'quantity': 1}],
        'expected_total': 1590,
        'request_key': 'minmax-too-low-key-0001'
    }).status_code == 400
    assert post(alice, '/api/orders', {
        'items': [{'product_id': pid, 'quantity': 5}],
        'expected_total': 1590 * 5,
        'request_key': 'minmax-too-high-key-0002'
    }).status_code == 400

    # 5. Create variant product and test server-side variant pricing & stock deduction
    var_saved = post(admin, '/api/products', {
        'name': 'Amazon Prime Video',
        'description': 'Escolha o plano abaixo.',
        'price': 399,
        'compare_price': 3000,
        'video_url': 'https://streamable.com/abc123xyz',
        'has_variants': True,
        'variants': [
            {'name': 'AMAZON PRIME VIDEO (30 DIAS DE ACESSO)', 'price': 399, 'compare_price': 3000, 'stock': 6},
            {'name': 'CONTA PRIME VIDEO COMPLETA (FULL ACESSO) 30 DIAS', 'price': 799, 'compare_price': 3000, 'stock': 6}
        ],
        'category': 'Streamings',
        'image': '',
        'delivery_mode': 'manual'
    })
    assert var_saved.status_code == 200
    vpid = var_saved.json['id']
    vprod = next(p for p in alice.get('/api/products').json if p['id'] == vpid)
    assert vprod['has_variants'] is True
    assert vprod['video_url'] == 'https://streamable.com/e/abc123xyz'
    assert len(vprod['variants']) == 2
    full_var = vprod['variants'][1]

    # Must require variant_id when product has_variants=True
    assert post(alice, '/api/orders', {
        'items': [{'product_id': vpid, 'quantity': 1}],
        'expected_total': 399,
        'request_key': 'variant-missing-id-0001'
    }).status_code == 400

    # Must use selected variant's price (799) and deduct variant stock
    ord_res = post(alice, '/api/orders', {
        'items': [{'product_id': vpid, 'variant_id': full_var['id'], 'quantity': 2}],
        'expected_total': 799 * 2,
        'request_key': 'variant-valid-order-0002'
    })
    assert ord_res.status_code == 201
    assert ord_res.json['order']['total'] == 1598
    assert 'CONTA PRIME VIDEO COMPLETA' in ord_res.json['order']['items'][0]['name']
    vprod_after = next(p for p in alice.get('/api/products').json if p['id'] == vpid)
    assert vprod_after['variants'][1]['stock'] == 4


def test_product_compare_price_video_quantity_stock_edit_and_variants(shop):
    app, admin, alice, bob, *_ = shop
    # 1. Invalid compare_price or untrusted video_url rejected
    base = dict(name='Dragon + Kitsune', description='Conta completa', price=1590, category='Contas Roblox', image='')
    assert post(admin, '/api/products', {**base, 'compare_price': 1590}).status_code == 400
    assert post(admin, '/api/products', {**base, 'video_url': 'https://evil.example.com/embed/123'}).status_code == 400
    assert post(admin, '/api/products', {**base, 'min_quantity': 5, 'max_quantity': 3}).status_code == 400

    # 2. Valid compare_price, YouTube/Streamable/Vimeo video_url, min/max quantity, and stock editing
    created = post(admin, '/api/products', {
        **base,
        'compare_price': 2290,
        'video_url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        'min_quantity': 2,
        'max_quantity': 4,
        'delivery_mode': 'automatic'
    })
    assert created.status_code == 200
    pid = created.json['id']
    prod_row = next(p for p in alice.get('/api/products').json if p['id'] == pid)
    assert prod_row['compare_price'] == 2290
    assert prod_row['video_url'] == 'https://www.youtube-nocookie.com/embed/dQw4w9WgXcQ'
    assert prod_row['min_quantity'] == 2 and prod_row['max_quantity'] == 4

    # Add stock and edit stock unit
    assert post(admin, f'/api/admin/products/{pid}/stock', {'content': 'login-1:pass-1'}).status_code == 201
    assert post(admin, f'/api/admin/products/{pid}/stock', {'content': 'login-2:pass-2'}).status_code == 201
    stock_id = admin.get(f'/api/admin/products/{pid}/delivery').json['stock'][0]['id']
    assert alice.get(f'/api/admin/products/{pid}/stock/{stock_id}').status_code == 403
    unit = admin.get(f'/api/admin/products/{pid}/stock/{stock_id}')
    assert unit.status_code == 200 and unit.json['content'] == 'login-1:pass-1'
    updated_unit = post(admin, f'/api/admin/products/{pid}/stock/{stock_id}', {'content': 'login-1-editado:pass-9'}, 'PUT')
    assert updated_unit.status_code == 200
    assert admin.get(f'/api/admin/products/{pid}/stock/{stock_id}').json['content'] == 'login-1-editado:pass-9'

    # Min/Max quantity enforced on order creation
    assert post(alice, '/api/orders', {
        'items': [{'product_id': pid, 'quantity': 1}],
        'expected_total': 1590,
        'request_key': 'minmax-too-low-0001'
    }).status_code == 400
    assert post(alice, '/api/orders', {
        'items': [{'product_id': pid, 'quantity': 5}],
        'expected_total': 1590 * 5,
        'request_key': 'minmax-too-high-0001'
    }).status_code == 400
    ok_order = post(alice, '/api/orders', {
        'items': [{'product_id': pid, 'quantity': 2}],
        'expected_total': 1590 * 2,
        'request_key': 'minmax-valid-000001'
    })
    assert ok_order.status_code == 201

    # 3. Variant product creation and checkout validation
    var_created = post(admin, '/api/products', {
        'name': 'Amazon Prime Video',
        'description': 'Escolha sua opção',
        'price': 399,
        'compare_price': 3000,
        'video_url': 'https://streamable.com/abc123xyz',
        'category': 'Streamings',
        'image': '',
        'has_variants': True,
        'variants': [
            {'name': 'AMAZON PRIME VIDEO (30 DIAS DE ACESSO)', 'price': 399, 'compare_price': 3000, 'stock': 6},
            {'name': 'CONTA PRIME VIDEO COMPLETA (FULL ACESSO) 30 DIAS', 'price': 799, 'compare_price': 3000, 'stock': 2}
        ]
    })
    assert var_created.status_code == 200
    vpid = var_created.json['id']
    vprod = next(p for p in bob.get('/api/products').json if p['id'] == vpid)
    assert vprod['has_variants'] is True
    assert vprod['video_url'] == 'https://streamable.com/e/abc123xyz'
    assert len(vprod['variants']) == 2
    v1_id = vprod['variants'][0]['id']
    v2_id = vprod['variants'][1]['id']

    # Ordering variant product without variant_id must fail
    assert post(bob, '/api/orders', {
        'items': [{'product_id': vpid, 'quantity': 1}],
        'expected_total': 399,
        'request_key': 'var-missing-id-0001'
    }).status_code == 400

    # Ordering variant 2 with variant 1's price must fail (server-side price enforcement)
    assert post(bob, '/api/orders', {
        'items': [{'product_id': vpid, 'variant_id': v2_id, 'quantity': 1}],
        'expected_total': 399,
        'request_key': 'var-wrong-total-001'
    }).status_code == 409

    # Ordering variant 2 with correct total succeeds and decrements variant stock
    v_order = post(bob, '/api/orders', {
        'items': [{'product_id': vpid, 'variant_id': v2_id, 'quantity': 2}],
        'expected_total': 799 * 2,
        'request_key': 'var-valid-order-001'
    })
    assert v_order.status_code == 201
    assert v_order.json['order']['items'][0]['name'] == 'Amazon Prime Video — CONTA PRIME VIDEO COMPLETA (FULL ACESSO) 30 DIAS'
    vprod_after = next(p for p in bob.get('/api/products').json if p['id'] == vpid)
    assert next(v for v in vprod_after['variants'] if v['id'] == v2_id)['stock'] == 0
    assert next(v for v in vprod_after['variants'] if v['id'] == v1_id)['stock'] == 6


def test_pantera_pix_amount_only_confirmation_and_replay(shop,monkeypatch):
    app,admin,alice,_,_,_=shop
    app.config.update(PAYMENT_PROVIDER='pantera',PANTERA_API_KEY='test-pantera')
    calls=[];state={'status':'PENDING','amount':1990,'id':'pantera-test-123','type':'DEPOSIT','reason':'PIX_PAYMENT'}
    def external(url,payload,headers=None,method=None):
        assert url.startswith('https://panterapay-production.up.railway.app/transactions')
        assert headers=={'Authorization':'test-pantera'}
        calls.append((method,payload))
        if method=='GET':
            assert url.endswith('/pantera-test-123?nocache=1')
            return dict(state)
        assert payload['amount']==1990 and set(payload)<={'amount','webhook'}
        return {'id':state['id'],'amount':1990,'copyPaste':'000201010212test-pantera-pix','status':'pending'}
    monkeypatch.setattr(commerce,'post_json',external)
    pid=product(admin,'manual');o,_=order(alice,pid);oid=o['id']
    start_payment(alice,oid)
    assert post(alice,f'/api/orders/{oid}/payment',{'payer_name':'Cliente Teste','payer_email':'cliente@example.com','payer_email_confirmation':'cliente@example.com','terms_accepted':True}).status_code==200
    assert len(calls)==1
    assert post(alice,f'/api/orders/{oid}/payment/check').json['order']['payment']=='pendente'
    state['status']='PAID';state['amount']=1
    assert post(alice,f'/api/orders/{oid}/payment/check').status_code==503
    state['amount']=1990;state['id']='forged'
    assert post(alice,f'/api/orders/{oid}/payment/check').status_code==503
    state['id']='pantera-test-123'
    assert post(alice,f'/api/orders/{oid}/payment/check').json['order']['payment']=='pago'
    assert post(alice,f'/api/orders/{oid}/payment/check').json['order']['payment']=='pago'
    with app.extensions['db']() as c:
        assert c.execute('SELECT payment_provider FROM orders WHERE id=?',(oid,)).fetchone()[0]=='pantera'
        assert c.execute("SELECT COUNT(*) FROM audit WHERE event='payment_confirmed'").fetchone()[0]==1


def test_private_pix_qr_png(shop):
    import io
    from PIL import Image
    app,admin,alice,bob,_,_=shop
    pid=product(admin,'manual');o,_=order(alice,pid);oid=o['id']
    path=f'/api/orders/{oid}/pix.png'
    assert alice.get(path).status_code==404
    assert bob.get(path).status_code in (403,404)
    start_payment(alice,oid)
    r=alice.get(path)
    assert r.status_code==200 and r.mimetype=='image/png'
    Image.open(io.BytesIO(r.data)).verify()
    assert r.headers['Cache-Control']=='no-store'
    assert app.test_client().get(path).status_code==401
    paid(shop,alice,oid)
    assert alice.get(path).status_code==404


def test_one_active_pix_per_customer_and_fifteen_minute_expiry(shop,monkeypatch):
    import time
    app,admin,alice,bob,_,_=shop
    pid=product(admin,'manual');first,_=order(alice,pid);oid=first['id']
    start_payment(alice,oid)
    current=alice.get('/api/orders/'+oid).json['order']
    now=int(time.time());assert 899<=current['pix_expires_at']-now<=900
    second=post(alice,'/api/orders',{'items':[{'product_id':pid,'quantity':1}],'expected_total':1990,'request_key':'second-checkout-key-0002'}).json['order']
    path='/api/orders/'+second['id']+'/payment'
    body={'payer_name':'Cliente Teste','payer_email':'cliente@example.com','payer_email_confirmation':'cliente@example.com','terms_accepted':True}
    blocked=post(alice,path,body)
    assert blocked.status_code==429 and blocked.json['active_order_id']==oid
    assert int(blocked.headers['Retry-After'])>0
    assert alice.get('/api/orders/'+second['id']).json['order']['payment']=='nao_iniciado'
    start_payment(bob,order(bob,pid)[0]['id'])
    monkeypatch.setattr(commerce.time,'time',lambda:now+901)
    assert alice.get('/api/orders/'+oid).json['order']['payment']=='expirado'
    assert alice.get('/api/orders/'+oid).json['order']['pix_code'] is None
    assert alice.get('/api/orders/'+oid+'/pix.png').status_code==404
    assert post(alice,path,body).status_code==200
    assert post(alice,'/api/orders/'+oid+'/payment',body).json['order']['payment']=='expirado'
    paid(shop,alice,oid)
    assert alice.get('/api/orders/'+oid).json['order']['payment']=='pago'


def test_pantera_requires_matching_email_and_explicit_terms_without_name(shop,monkeypatch):
    app,admin,alice,*_=shop
    app.config.update(PAYMENT_PROVIDER='pantera',PANTERA_API_KEY='test-pantera')
    calls=[]
    def external(url,payload,headers=None,method=None):
        calls.append(payload)
        assert set(payload)<={'amount','webhook'}
        return {'id':'email-only-pix','amount':1990,'copyPaste':'000201010212email-only-pix-code'}
    monkeypatch.setattr(commerce,'post_json',external)
    pid=product(admin,'manual');o,_=order(alice,pid);path=f"/api/orders/{o['id']}/payment"
    body={'payer_email':'cliente@example.com','payer_email_confirmation':'cliente@example.com','terms_accepted':True}
    for payload in ({**body,'terms_accepted':False},{k:v for k,v in body.items() if k!='terms_accepted'},{**body,'payer_email_confirmation':'outro@example.com'},{k:v for k,v in body.items() if k!='payer_email_confirmation'}):
        assert post(alice,path,payload).status_code==400
    assert not calls
    assert post(alice,path,body).status_code==200
    with app.extensions['db']() as c:
        terms=c.execute('SELECT * FROM payment_terms WHERE order_id=?',(o['id'],)).fetchone()
        assert terms['terms_path']=='/terms' and terms['accepted_at']>0
        assert c.execute('SELECT payer_name FROM order_tracking WHERE order_id=?',(o['id'],)).fetchone()[0] is None
