# Reverse proxy and HTTPS

audium works on plain HTTP in your LAN (`http://<server>:8091`). Put it behind a reverse proxy with HTTPS when you want to:

- **install it as an app** (PWA, "Zum Startbildschirm hinzufügen"): browsers allow service workers only on HTTPS or `localhost`. On `http://192.168.x.x` audium works normally, it just cannot be installed or start offline;
- reach it from outside your home network;
- copy invite links with one click (the clipboard API also needs HTTPS; the link is shown either way).

What every proxy needs:

1. Forward `X-Forwarded-For` and `X-Forwarded-Proto`, and list the proxy's IP in `AUDIUM_TRUSTED_PROXIES` (or `*` if only the proxy can reach the container). audium then sees the real client IP (login rate limiting) and sets the `Secure` flag on its cookie.
2. Do not buffer `/api/v1/events` (Server-Sent Events) and allow idle connections of at least 30 s. audium sends a keep-alive every 15 s.
3. Pass `Range` headers through (all three below do by default).
4. Under a sub-path: set `AUDIUM_BASE_PATH=/audium` and forward the **full** path; do not strip the prefix.

The examples assume audium runs in the same Docker network as the proxy under the service name `audium` (port 8080 inside the container). If the proxy runs on the host instead, use `127.0.0.1:8091`.

## Caddy

Caddy gets certificates automatically and flushes streamed responses, so this is all:

```caddy
music.example.org {
	reverse_proxy audium:8080
}
```

Sub-path (`AUDIUM_BASE_PATH=/audium`):

```caddy
example.org {
	handle /audium* {
		reverse_proxy audium:8080
	}
}
```

## nginx

```nginx
server {
    listen 443 ssl;
    http2 on;
    server_name music.example.org;
    ssl_certificate     /etc/letsencrypt/live/music.example.org/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/music.example.org/privkey.pem;

    location / {
        proxy_pass http://audium:8080;
        proxy_set_header Host              $host;
        proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 1h;   # long streams and the event stream
    }
}
```

audium sends `X-Accel-Buffering: no` on the event stream, so nginx does not buffer it without further configuration. Sub-path: use `location /audium/ { proxy_pass http://audium:8080; ... }`; note there is **no** trailing slash or path after `proxy_pass`, so nginx keeps the prefix.

## Traefik (Docker labels)

```yaml
services:
  audium:
    image: ghcr.io/<owner>/audium:latest
    environment:
      AUDIUM_TRUSTED_PROXIES: "*"   # only Traefik can reach the container
    labels:
      - traefik.enable=true
      - traefik.http.routers.audium.rule=Host(`music.example.org`)
      - traefik.http.routers.audium.entrypoints=websecure
      - traefik.http.routers.audium.tls.certresolver=letsencrypt
      - traefik.http.services.audium.loadbalancer.server.port=8080
    # no "ports:" needed: Traefik talks to the container directly
```

Traefik streams responses without buffering by default. For a sub-path, use ``rule=Host(`example.org`) && PathPrefix(`/audium`)`` together with `AUDIUM_BASE_PATH=/audium`, and do not add a `stripprefix` middleware.

## Checking it

- `https://music.example.org/api/health` returns `{"status": "ok", ...}`.
- After logging in, the browser's developer tools show the `audium_session` cookie with the `Secure` flag.
- Chrome/Edge show an install icon in the address bar; on iOS use Share → "Zum Home-Bildschirm".
