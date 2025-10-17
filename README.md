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
- **JavaScript Support**: Uses Selenium to capture dynamically loaded content and images
- **Web Interface**: HTML-based control panel for configuration and monitoring
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

### Core Dependencies
- Python 3.7+
- requests
- beautifulsoup4
- lxml

### Optional: JavaScript Support
- selenium (for JavaScript-rendered content)
- Chrome browser
- ChromeDriver

### Installation
```bash
# Install core dependencies
pip install -r requirements.txt

# For JavaScript support (optional)
pip install selenium
# Download ChromeDriver from https://chromedriver.chromium.org/
```

The system uses concurrent processing with ThreadPoolExecutor for efficient downloads. When Selenium is available, it automatically uses it for the first few pages to capture JavaScript-rendered content and images.
