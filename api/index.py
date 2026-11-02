"""Vercel Serverless WSGI Entrypoint — routes 100% of traffic through the Flask backend."""
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from server import create_app
    app = create_app()
except Exception as exc:
    err_tb = traceback.format_exc()
    err_msg = str(exc)
    print("FATAL ERROR ON STARTUP:\n" + err_tb, file=sys.stderr)
    from flask import Flask, jsonify
    app = Flask(__name__)
    @app.route('/', defaults={'path': ''})
    @app.route('/<path:path>')
    def catch_all(path):
        return jsonify({
            "error": "Erro na inicialização do servidor (Configuração necessária)",
            "message": err_msg,
            "hint": "Cadastre as variáveis de ambiente na Vercel (DATABASE_KEY, PUBLIC_ORIGIN, etc.) e faça um Redeploy."
        }), 500
