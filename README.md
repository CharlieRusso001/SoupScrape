```
   ▄████████  ▄██████▄  ███    █▄     ▄███████▄    ▄████████  ▄████████    ▄████████    ▄████████    ▄███████▄    ▄████████ 
  ███    ███ ███    ███ ███    ███   ███    ███   ███    ███ ███    ███   ███    ███   ███    ███   ███    ███   ███    ███ 
  ███    █▀  ███    ███ ███    ███   ███    ███   ███    █▀  ███    █▀    ███    ███   ███    ███   ███    ███   ███    █▀  
  ███        ███    ███ ███    ███   ███    ███   ███        ███         ▄███▄▄▄▄██▀   ███    ███   ███    ███  ▄███▄▄▄     
▀███████████ ███    ███ ███    ███ ▀█████████▀  ▀███████████ ███        ▀▀███▀▀▀▀▀   ▀███████████ ▀█████████▀  ▀▀███▀▀▀     
         ███ ███    ███ ███    ███   ███                 ███ ███    █▄  ▀███████████   ███    ███   ███          ███    █▄  
   ▄█    ███ ███    ███ ███    ███   ███           ▄█    ███ ███    ███   ███    ███   ███    ███   ███          ███    ███ 
 ▄████████▀   ▀██████▀  ████████▀   ▄████▀       ▄████████▀  ████████▀    ███    ███   ███    █▀   ▄████▀        ██████████ 
                                                                          ███    ███                                        
```



A Python-based web scraping toolkit that provides comprehensive website mirroring and image extraction capabilities using Beautiful Soup and concurrent processing.

## Features

- **Full Website Mirroring**: Complete website download with HTML, CSS, JavaScript, images, and other assets
- **Image-Only Extraction**: Dedicated image scraper for bulk image downloads
- **Web Interface**: HTML-based control panel for configuration and monitoring
- **Real-time Statistics**: Live tracking of download progress and file counts
- **Concurrent Processing**: Multi-threaded downloads for improved performance
- **Domain Validation**: Built-in URL accessibility testing
- **Graceful Shutdown**: Ctrl+C support for clean process termination

## Components

### Scripts

- `main.py`: Web server and control panel interface
- `scrape.py`: Full website mirroring with asset preservation
- `imagesonly.py`: Optimized image extraction tool
- `config.txt`: Configuration file for scraping parameters

### Web Interface

The web interface provides:
- Configuration management
- Script execution controls
- Real-time download monitoring
- Statistics display with file counts and image previews
- Live console output streaming

## Configuration

Edit `config.txt` to set scraping parameters:

```
start_url=https://example.com/
max_pages=1000
delay=0.5
max_workers=20
same_domain_only=true
```

## Usage

### Web Interface
```bash
python main.py
```
Access the interface at `http://localhost:8080`

### Command Line
```bash
python scrape.py      # Full website mirror
python imagesonly.py  # Image extraction only
```

## Output Structure

- `scraped_site/{domain}/`: Complete website mirror with preserved structure
- `scraped_site/{domain}-images/`: Flat directory of extracted images

## Requirements

- Python 3.7+
- requests
- beautifulsoup4
- Standard library modules: os, sys, json, threading, subprocess, http.server, urllib, time, base64, mimetypes, signal

The system uses concurrent processing with ThreadPoolExecutor for efficient downloads. Image previews are generated using base64 encoding with a 5MB size limit. The web interface polls for updates every 250ms during active scraping operations.
