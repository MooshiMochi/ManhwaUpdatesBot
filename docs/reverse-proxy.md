# Reverse Proxy Notes

The bot does not expose an HTTP server in normal operation, so it usually does not need nginx or Caddy directly. Reverse proxy configuration belongs in front of the crawler service when the crawler WebSocket is reachable over a public or private HTTPS endpoint.

## Bot configuration

Point the bot at the proxied crawler URLs:

```toml
[crawler]
ws_url = "wss://crawler.example.com/ws"
http_base_url = "https://crawler.example.com"
```

Keep `CRAWLER_API_KEY` in `.env`. The bot sends it during the WebSocket upgrade.

## nginx

```nginx
server {
    listen 443 ssl http2;
    server_name crawler.example.com;

    ssl_certificate /etc/letsencrypt/live/crawler.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/crawler.example.com/privkey.pem;

    location /ws {
        proxy_pass http://127.0.0.1:8000/ws;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

## Caddy

```caddyfile
crawler.example.com {
    reverse_proxy /ws 127.0.0.1:8000 {
        header_up Host {host}
    }

    reverse_proxy 127.0.0.1:8000
}
```

Caddy handles WebSocket upgrades automatically.

## Timeouts

Crawler checks and notification pushes can keep the WebSocket open for a long time. Configure proxy read timeouts in hours, not seconds, and avoid buffering WebSocket traffic.

## TLS and private networks

If the bot and crawler run on the same host, prefer `ws://127.0.0.1:8000/ws` and skip the proxy. Use `wss://` when crossing a network boundary or running the bot in a different container/VM.
