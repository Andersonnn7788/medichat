web: gunicorn -k uvicorn.workers.UvicornWorker web_app:app --bind 127.0.0.1:8000 --workers=${WEB_CONCURRENCY:-2} --threads=2 --timeout=120
