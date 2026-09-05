FROM python:3.13-slim
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000
# #185: `--forwarded-allow-ips=*` used to mean uvicorn trusted a
# client-supplied X-Forwarded-For from literally any peer, including a
# request that reached it directly (app is bound 127.0.0.1:8000 on the
# droplet host, so this only mattered to someone with host-level shell
# access — but "trust everything" is still the wrong default). The real,
# internet-facing fix is the Caddyfile's new `trusted_proxies` global
# option, which stops an untrusted/spoofed X-Forwarded-For from ever
# reaching this container in the first place (see that file's #185
# comment for the full reasoning). This narrows uvicorn's own trust down
# to the docker-compose network's private address range as defense in
# depth underneath that fix, rather than pinning Caddy's one exact
# container IP — docker-compose's default bridge network assigns that IP
# dynamically and it can change across a network recreation, which a
# hardcoded single address would silently break; every address that
# range doesn't cover is already outside the docker-compose network
# entirely, so this is still a real, meaningful narrowing from "*".
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=172.16.0.0/12"]
