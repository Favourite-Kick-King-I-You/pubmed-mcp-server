web: gunicorn server:app -k uvicorn.workers.UvicornWorker --workers 1 --bind 0.0.0.0:${PORT:-8000}
