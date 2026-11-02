"""Run alongside Gunicorn to reconcile payments and retry Discord / UTMify notifications."""
import logging
import signal
import time
from server import create_app

app = create_app()
running = True

def stop(*_):
    global running
    running = False

signal.signal(signal.SIGTERM, stop)
signal.signal(signal.SIGINT, stop)
if __name__ == '__main__':
    while running:
        try:
            with app.app_context():
                app.extensions['commerce']['process_jobs']()
        except Exception:
            logging.error('Fila temporariamente indisponível; nova tentativa em 5 segundos.')
        for _ in range(5):
            if not running:
                break
            time.sleep(1)
