FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/routehash

RUN pip install --no-cache-dir \
    'coincurve==21.0.0' \
    'bip-utils==2.12.2' \
    'websocket-client==1.9.2' \
    'cryptography==50.0.1'

WORKDIR /opt/routehash
COPY runtime/ /opt/routehash/

CMD ["python3", "/opt/routehash/pool_balance_loop.py", "--data", "/data", "--ui", "7156"]
