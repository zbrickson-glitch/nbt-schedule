# Stage 1: Build gog CLI for linux/amd64
FROM golang:1.25-bookworm AS gog-builder
RUN git clone --depth 1 --branch v0.9.0 https://github.com/steipete/gogcli.git /src
WORKDIR /src
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
    -ldflags="-s -w -X github.com/steipete/gogcli/internal/cmd.version=0.9.0" \
    -o /gog ./cmd/gog

# Stage 2: Python service
FROM python:3.11-slim-bookworm

# Install gog binary
COPY --from=gog-builder /gog /usr/local/bin/gog
RUN chmod +x /usr/local/bin/gog

# Create app directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY main.py .
COPY schedule_parser.py .
COPY casting_parser.py .
COPY calendar_writer.py .
COPY discord_preview.py .

# gog config directory — on Linux, gog uses $HOME/.config/gogcli/
# The init container sets up credentials and keyring tokens here
ENV HOME=/root
RUN mkdir -p /root/.config/gogcli/keyring

EXPOSE 8002

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8002"]
