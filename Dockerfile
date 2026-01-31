FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
WORKDIR /app

RUN apt-get update && apt-get install -y \
    postgresql-client \
    build-essential \
    libpq-dev \
    ffmpeg \
    wget \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install numpy && \
    pip install git+https://github.com/itu-p1203/itu-p1203.git && \
    pip install git+https://github.com/Telecommunication-Telemedia-Assessment/itu-p1203-codecextension.git

RUN ARCH=$(uname -m) && \
    if [ "$ARCH" = "x86_64" ]; then \
        wget https://github.com/shaka-project/shaka-packager/releases/download/v3.2.0/packager-linux-x64 -O /usr/local/bin/packager; \
    elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then \
        wget https://github.com/shaka-project/shaka-packager/releases/download/v3.2.0/packager-linux-arm64 -O /usr/local/bin/packager; \
    else \
        echo "Unsupported architecture: $ARCH" && exit 1; \
    fi && \
    chmod +x /usr/local/bin/packager

COPY requirements.txt /app/
RUN pip install --upgrade pip && pip install -r requirements.txt
COPY . /app/