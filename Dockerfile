FROM python:3.9-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    aria2 \
    curl \
    ffmpeg \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the bot files
COPY . .

# Create directories
RUN mkdir -p downloads templates static

# Create a basic template for the web interface
RUN echo '<!DOCTYPE html>\
<html lang="en">\
<head>\
    <meta charset="UTF-8">\
    <meta name="viewport" content="width=device-width, initial-scale=1.0">\
    <title>Terabox Downloader Bot</title>\
    <style>\
        body { font-family: Arial, sans-serif; margin: 0; padding: 20px; text-align: center; }\
        .container { max-width: 800px; margin: 0 auto; }\
        .status { padding: 15px; background-color: #f0f0f0; border-radius: 5px; margin: 20px 0; }\
    </style>\
</head>\
<body>\
    <div class="container">\
        <h1>Terabox Downloader Bot</h1>\
        <div class="status">{{status}}</div>\
        <p>Bot Status Panel</p>\
    </div>\
</body>\
</html>' > templates/index.html

# Setup aria2
RUN aria2c --enable-rpc --rpc-listen-all=true --rpc-allow-origin-all --daemon=true \
    --max-concurrent-downloads=10 \
    --max-connection-per-server=16 \
    --split=16 \
    --min-split-size=1M \
    --max-overall-download-limit=0 \
    --max-overall-upload-limit=0 \
    --file-allocation=none

# Script to run aria2 daemon and start the bot
RUN echo '#!/bin/bash\n\
aria2c --enable-rpc --rpc-listen-all=true --rpc-allow-origin-all --daemon=true \
--max-concurrent-downloads=10 \
--max-connection-per-server=16 \
--split=16 \
--min-split-size=1M \
--max-overall-download-limit=0 \
--max-overall-upload-limit=0 \
--file-allocation=none\n\
sleep 2\n\
python terabox.py' > /app/start.sh

# Make the script executable
RUN chmod +x /app/start.sh

# Command to run the bot
CMD ["/app/start.sh"]
