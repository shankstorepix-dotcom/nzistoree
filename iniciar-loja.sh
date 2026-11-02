#!/usr/bin/env bash
cd -- "$(dirname -- "${BASH_SOURCE[0]}")" || exit 1
printf 'NziStore: http://localhost:8000\nPainel: http://localhost:8000/dashboard\nPedidos e chat: http://localhost:8000/pedidos\nCtrl+C para encerrar.\n'
.venv/bin/python commerce_worker.py &
worker_pid=$!
trap 'kill "$worker_pid" 2>/dev/null; wait "$worker_pid" 2>/dev/null' EXIT
trap 'exit 130' INT TERM
.venv/bin/gunicorn --bind 127.0.0.1:8000 --workers 2 --threads 2 --timeout 30 'server:create_app()'
