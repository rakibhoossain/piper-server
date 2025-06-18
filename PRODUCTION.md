# Production Deployment Guide for Piper Server

This guide explains how to deploy the Piper Server in a production environment using Gunicorn with Nginx as a reverse proxy.

## Requirements

- Python 3.7+
- Gunicorn
- Nginx (recommended for reverse proxy)
- Systemd (for service management)

## Installation

1. Install production dependencies:

```bash
pip install gunicorn
```

2. Add the schedule package for file cleanup:

```bash
pip install schedule
```

## Running with Gunicorn

Gunicorn is a production-ready WSGI server that can run your Flask application.

```bash
gunicorn -w 4 -b 127.0.0.1:5000 wsgi:app
```

Where:
- `-w 4`: 4 worker processes (adjust based on CPU cores, typically 2-4 workers per core)
- `-b 127.0.0.1:5000`: Binds to localhost port 5000 (only accessible locally)
- `wsgi:app`: Uses the app object from wsgi.py

## Environment Variables

You can configure the server using environment variables:

```bash
# Set base URL for file access (must match your public URL)
export PIPER_BASE_URL="https://tts.example.com"

# Then run with gunicorn
gunicorn -w 4 -b 127.0.0.1:5000 wsgi:app
```

## Command Line Arguments

When using WSGI mode, pass arguments through the command line to the main application:

```bash
# Example with custom args
gunicorn -w 4 -b 127.0.0.1:5000 "wsgi:main()" --preload -- --model en_US-amy-medium --storage-dir /var/lib/piper/audio --base-url https://tts.example.com --behind-proxy
```

## Nginx Configuration

Create a configuration file in `/etc/nginx/sites-available/piper`:

```nginx
server {
    listen 80;
    server_name tts.example.com;  # Replace with your domain

    # Redirect HTTP to HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl;
    server_name tts.example.com;  # Replace with your domain

    ssl_certificate /etc/letsencrypt/live/tts.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/tts.example.com/privkey.pem;

    # Security headers
    add_header X-Content-Type-Options "nosniff";
    add_header X-XSS-Protection "1; mode=block";
    add_header X-Frame-Options "SAMEORIGIN";

    # Proxy settings
    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # For large audio files
        client_max_body_size 20M;
        proxy_connect_timeout 300s;
        proxy_send_timeout 300s;
        proxy_read_timeout 300s;
    }
}
```

Enable the site:
```bash
ln -s /etc/nginx/sites-available/piper /etc/nginx/sites-enabled/
nginx -t && systemctl reload nginx
```

## Systemd Service

Create a systemd service file at `/etc/systemd/system/piper.service`:

```ini
[Unit]
Description=Piper TTS Server
After=network.target

[Service]
User=piper  # Create a dedicated user for security
Group=piper
WorkingDirectory=/path/to/piper_server
Environment="PIPER_BASE_URL=https://tts.example.com"
ExecStart=/path/to/venv/bin/gunicorn -w 4 -b 127.0.0.1:5000 wsgi:app
Restart=on-failure
RestartSec=5s

# Security measures
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ReadWritePaths=/path/to/audio_storage
CapabilityBoundingSet=

[Install]
WantedBy=multi-user.target
```

Start and enable the service:
```bash
systemctl daemon-reload
systemctl start piper
systemctl enable piper
```

## Base URL Configuration

When running behind a proxy, make sure to:

1. Set the `--behind-proxy` flag to properly handle forwarded headers
2. Set `--base-url` (or `PIPER_BASE_URL` env var) to your public URL (e.g., "https://tts.example.com")

This ensures that generated file URLs will use your public domain instead of localhost.

## File Storage

1. Create a dedicated directory with appropriate permissions:
```bash
mkdir -p /var/lib/piper/audio
chown -R piper:piper /var/lib/piper/audio
chmod 750 /var/lib/piper/audio
```

2. Configure the storage directory:
```bash
--storage-dir /var/lib/piper/audio
```

## Monitoring

You can monitor the application logs:
```bash
journalctl -u piper -f
```

## Performance Tuning

For high-traffic environments:
- Increase the number of Gunicorn workers
- Consider using async workers (gevent or eventlet)
- Use Nginx caching for static files
- Adjust file expiry time based on your needs
- Monitor memory usage and adjust as needed
