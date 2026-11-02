"""Consent-based daily visitors and optional local GeoIP lookup; no raw IP storage."""
import hashlib,hmac,ipaddress,json,os,re,time
from datetime import datetime
from zoneinfo import ZoneInfo
from urllib.parse import unquote
import maxminddb
from flask import request,jsonify

UFS=set('AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR SC SP SE TO'.split())
def install_insights(app,db,key,data,limit):
    app.config.setdefault('GEOIP_DATABASE_PATH',os.getenv('GEOIP_DATABASE_PATH',''))
    app.config.setdefault('GEOIP_TRUSTED_PROXIES',os.getenv('GEOIP_TRUSTED_PROXIES',''))
    networks=[ipaddress.ip_network(n.strip()) for n in app.config['GEOIP_TRUSTED_PROXIES'].split(',') if n.strip()]
    with db() as c:
        c.execute('CREATE TABLE IF NOT EXISTS daily_visits(day TEXT NOT NULL,visitor TEXT NOT NULL,state TEXT,country TEXT,PRIMARY KEY(day,visitor))')
    def locate():
        address=request.remote_addr
        try:
            peer=ipaddress.ip_address(address)
            if any(peer in network for network in networks):address=request.headers.get('X-Real-IP',address)
            ip=ipaddress.ip_address(address)
            if not ip.is_global or not app.config['GEOIP_DATABASE_PATH']:return None,None
            with maxminddb.open_database(app.config['GEOIP_DATABASE_PATH']) as reader:record=reader.get(str(ip)) or {}
            country=record.get('country',{}).get('iso_code')
            subdivisions=record.get('subdivisions') or [{}]
            state=subdivisions[0].get('iso_code')
            return country if isinstance(country,str) and re.fullmatch('[A-Z]{2}',country) else None,state if country=='BR' and state in UFS else None
        except (ValueError,OSError,maxminddb.InvalidDatabaseError):return None,None
    @app.post('/api/analytics/visit')
    def record_visit():
        body=data()
        try:prefs=json.loads(unquote(request.cookies.get('nzi-cookie-preferences','{}')))
        except ValueError:prefs={}
        if not isinstance(prefs,dict) or prefs.get('version')!=2 or prefs.get('analytics') is not True:return jsonify(recorded=False)
        token=body.get('visitor','')
        if not isinstance(token,str) or not re.fullmatch('[a-f0-9]{32}',token):return jsonify(error='Identificador inválido.'),400
        limit('visit:'+(request.remote_addr or ''),30,60)
        day=datetime.now(ZoneInfo('America/Sao_Paulo')).date().isoformat()
        visitor=hmac.new(key.encode(),(day+':'+token).encode(),hashlib.sha256).hexdigest()
        country,state=locate()
        with db() as c:
            c.execute('INSERT OR IGNORE INTO daily_visits VALUES(?,?,?,?)',(day,visitor,state,country))
            c.execute("DELETE FROM daily_visits WHERE day<date('now','-180 days')")
        return jsonify(recorded=True)
    def summary(c,start,end):
        dates=(start.date().isoformat(),end.date().isoformat())
        rows=[dict(r) for r in c.execute('SELECT day,COUNT(*) AS visits FROM daily_visits WHERE day>=? AND day<? GROUP BY day',dates)]
        states=[dict(r) for r in c.execute('SELECT state,COUNT(*) AS visits FROM daily_visits WHERE day>=? AND day<? AND state IS NOT NULL GROUP BY state ORDER BY visits DESC',dates)]
        total=sum(r['visits'] for r in rows)
        abroad=c.execute("SELECT COUNT(*) FROM daily_visits WHERE day>=? AND day<? AND country IS NOT NULL AND country!='BR'",dates).fetchone()[0]
        return dict(visits=total,visit_series=rows,states=states,geo_unknown=total-sum(r['visits'] for r in states)-abroad,geo_abroad=abroad,geo_ready=bool(app.config['GEOIP_DATABASE_PATH'] and os.path.isfile(app.config['GEOIP_DATABASE_PATH'])))
    app.extensions['insights_summary']=summary
