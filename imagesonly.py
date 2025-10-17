#!/usr/bin/env python3
"""
Fast Image Extractor - Optimized version that doesn't get stuck
Extracts all images from a website into a single organized folder.
"""

import os
import re
import sys
import time
import requests
import urllib.parse
from urllib.parse import urlparse, urljoin, urldefrag
from bs4 import BeautifulSoup
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import signal

# Fix Windows encoding issues
sys.stdout.reconfigure(encoding='utf-8')

# Global flag for graceful shutdown
shutdown_requested = False

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    global shutdown_requested
    print("\n🛑 Shutdown requested by user (Ctrl+C)")
    print("⏳ Stopping gracefully... Please wait...")
    shutdown_requested = True

# ASCII Banner
BANNER = """
   ▄████████  ▄██████▄  ███    █▄     ▄███████▄    ▄████████  ▄████████    ▄████████    ▄████████    ▄███████▄    ▄████████ 
  ███    ███ ███    ███ ███    ███   ███    ███   ███    ███ ███    ███   ███    ███   ███    ███   ███    ███   ███    ███ 
  ███    █▀  ███    ███ ███    ███   ███    ███   ███    █▀  ███    █▀    ███    ███   ███    ███   ███    ███   ███    █▀  
  ███        ███    ███ ███    ███   ███    ███   ███        ███         ▄███▄▄▄▄██▀   ███    ███   ███    ███  ▄███▄▄▄     
▀███████████ ███    ███ ███    ███ ▀█████████▀  ▀███████████ ███        ▀▀███▀▀▀▀▀   ▀███████████ ▀█████████▀  ▀▀███▀▀▀     
         ███ ███    ███ ███    ███   ███                 ███ ███    █▄  ▀███████████   ███    ███   ███          ███    █▄  
   ▄█    ███ ███    ███ ███    ███   ███           ▄█    ███ ███    ███   ███    ███   ███    ███   ███          ███    ███ 
 ▄████████▀   ▀██████▀  ████████▀   ▄████▀       ▄████████▀  ████████▀    ███    ███   ███    █▀   ▄████▀        ██████████ 
                                                                          ███    ███                                        
"""

# Image extensions
IMAGE_EXTS = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico', '.bmp', '.tiff', '.jfif', '.avif')

def read_config():
    """Read configuration from config.txt."""
    config = {
        'start_url': 'https://www.enchantedwave.com/',
        'max_pages': 1000,
        'delay': 0.5,
        'max_workers': 5,
        'same_domain_only': True
    }
    
    try:
        with open('config.txt', 'r') as f:
            for line in f:
                line = line.strip()
                if '=' in line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    if key == 'start_url':
                        config[key] = value
                    elif key == 'max_pages':
                        config[key] = int(value)
                    elif key == 'delay':
                        config[key] = float(value)
                    elif key == 'max_workers':
                        config[key] = int(value)
                    elif key == 'same_domain_only':
                        config[key] = value.lower() in ('true', '1', 'yes', 'on')
    except FileNotFoundError:
        pass
    
    return config

def ensure_dir(path):
    """Ensure directory exists."""
    os.makedirs(path, exist_ok=True)


def normalize_url(base_url, url):
    """Normalize URL to absolute URL."""
    if not url:
        return None
    
    # Handle data URLs
    if url.startswith('data:'):
        return url
    
    # Handle protocol-relative URLs
    if url.startswith('//'):
        parsed = urlparse(base_url)
        url = f"{parsed.scheme}:{url}"
    
    # Handle relative URLs
    if not url.startswith(('http://', 'https://')):
        url = urljoin(base_url, url)
    
    # Clean up URL encoding issues
    url = url.replace('%20', ' ').replace('%2B', '+').replace('%2F', '/')
    
    return url

def is_same_origin(base_netloc, url):
    """Check if URL is from the same domain or related CDN domains."""
    try:
        url_netloc = urlparse(url).netloc
        if url_netloc == base_netloc:
            return True
        
        # Allow common CDN domains that are clearly part of the same website
        cdn_domains = [
            'static.wixstatic.com',
            'siteassets.parastorage.com', 
            'static.parastorage.com',
            'wixstatic.com',
            'parastorage.com',
            'cdn.',  # Any CDN subdomain
            'assets.',  # Any assets subdomain
            'media.',  # Any media subdomain
            'images.',  # Any images subdomain
        ]
        
        # Check if it's a known CDN domain
        for cdn_domain in cdn_domains:
            if cdn_domain in url_netloc:
                return True
        
        return False
    except Exception:
        return False

def generate_safe_filename(url, content_type=None):
    """Generate a safe filename for the image."""
    parsed = urlparse(url)
    path = parsed.path
    
    # Extract filename from path
    filename = os.path.basename(path)
    if not filename or '.' not in filename:
        # Generate filename from URL
        filename = f"image_{hash(url) % 100000}"
        if content_type:
            if 'jpeg' in content_type or 'jpg' in content_type:
                filename += '.jpg'
            elif 'png' in content_type:
                filename += '.png'
            elif 'gif' in content_type:
                filename += '.gif'
            elif 'webp' in content_type:
                filename += '.webp'
            elif 'svg' in content_type:
                filename += '.svg'
            else:
                filename += '.jpg'  # Default
        else:
            filename += '.jpg'
    
    # Clean filename
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    filename = re.sub(r'_+', '_', filename)  # Replace multiple underscores
    
    return filename

def download_image_worker(session, url, output_dir, timeout=20):
    """Worker function for downloading individual images."""
    try:
        # Try multiple URL variations for encoding issues
        urls_to_try = [url]
        if '%20' in url:
            urls_to_try.extend([
                url.replace('%20', ' '),
                url.replace('%20', '-')
            ])
        if ' ' in url:
            urls_to_try.extend([
                url.replace(' ', '%20'),
                url.replace(' ', '-')
            ])
        
        for try_url in urls_to_try:
            try:
                # First, try HEAD request to check if it's really an image
                head_resp = session.head(try_url, timeout=timeout)
                if head_resp.status_code == 200:
                    content_type = head_resp.headers.get('Content-Type', '').lower()
                    if any(ext in content_type for ext in ['image/', 'jpeg', 'png', 'gif', 'webp', 'svg']):
                        # Now download the full image
                        resp = session.get(try_url, timeout=timeout)
                        if resp.status_code == 200:
                            filename = generate_safe_filename(try_url, content_type)
                            filepath = os.path.join(output_dir, filename)
                            
                            with open(filepath, 'wb') as f:
                                f.write(resp.content)
                            
                            return True, try_url, f"Downloaded {len(resp.content)} bytes"
                        else:
                            continue
                    else:
                        continue
                else:
                    continue
            except Exception:
                continue
        
        return False, url, "All URL variations failed"
        
    except Exception as e:
        return False, url, f"Worker error: {e}"

def discover_images_fast(session, start_url, max_pages=10, delay=0.1, timeout=10):
    """Fast image discovery - optimized to not get stuck."""
    print(f"Discovering images on {start_url}...", flush=True)
    
    parsed = urlparse(start_url)
    base_netloc = parsed.netloc
    
    image_urls = set()
    visited = set()
    to_visit = [start_url]
    page_count = 0
    
    while to_visit and page_count < max_pages and not shutdown_requested:
        url = to_visit.pop(0)
        url, _ = urldefrag(url)
        
        if url in visited:
            continue
        if not is_same_origin(base_netloc, url):
            continue
        
        page_count += 1
        print(f"[page {page_count}] {url}", flush=True)
        
        # Add delay between requests
        if delay > 0:
            time.sleep(delay)
        
        # Check for shutdown after delay
        if shutdown_requested:
            print("🛑 Stopping discovery due to shutdown request")
            break
        
        try:
            # Use timeout to prevent hanging
            resp = session.get(url, timeout=timeout)
            if not resp or resp.status_code != 200:
                visited.add(url)
                continue
        except requests.exceptions.ConnectionError as e:
            if "NameResolutionError" in str(e) or "getaddrinfo failed" in str(e):
                print(f"  [DNS ERROR] Cannot resolve domain '{urlparse(url).netloc}' - Domain may not exist or DNS is down")
                print(f"  [SUGGESTION] Try using a different URL or check your internet connection")
            else:
                print(f"  [CONNECTION ERROR] Failed to connect to {url}: {e}")
            visited.add(url)
            continue
        except requests.exceptions.Timeout as e:
            print(f"  [TIMEOUT] Request to {url} timed out after {timeout}s")
            visited.add(url)
            continue
        except Exception as e:
            print(f"  [error] Failed to fetch {url}: {e}")
            visited.add(url)
            continue
        
        content_type = resp.headers.get("Content-Type", "").lower()
        content_length = len(resp.text)
        print(f"  [debug] Content-Type: {content_type}, Size: {content_length} chars")
        
        if "text/html" in content_type:
            try:
                # FAST IMAGE DETECTION - Only use the most effective methods
                html_text = resp.text
                
                # METHOD 1: Fast regex for absolute URLs (most effective)
                absolute_pattern = r'https?://[^\s<>"\']+\.(?:jpg|jpeg|png|gif|webp|svg|ico|bmp|tiff|jfif|avif)(?:\?[^\s<>"\']*)?'
                absolute_urls = re.findall(absolute_pattern, html_text, re.IGNORECASE)
                for found_url in absolute_urls:
                    if is_same_origin(base_netloc, found_url):
                        image_urls.add(found_url)
                
                # METHOD 2: Fast regex for relative URLs
                relative_pattern = r'["\']([^"\']*\.(?:jpg|jpeg|png|gif|webp|svg|ico|bmp|tiff|jfif|avif))["\']'
                relative_urls = re.findall(relative_pattern, html_text, re.IGNORECASE)
                for rel_url in relative_urls:
                    abs_url = normalize_url(url, rel_url)
                    if abs_url and is_same_origin(base_netloc, abs_url):
                        image_urls.add(abs_url)
                
                # METHOD 3: Quick BeautifulSoup for src attributes only
                soup = BeautifulSoup(html_text, "html.parser")
                for img in soup.find_all("img", src=True):
                    img_url = normalize_url(url, img["src"])
                    if img_url and is_same_origin(base_netloc, img_url):
                        image_urls.add(img_url)
                
                # Add URL variations for encoding issues
                new_variations = []
                for img_url in list(image_urls):
                    if '%20' in img_url:
                        new_variations.append(img_url.replace('%20', ' '))
                        new_variations.append(img_url.replace('%20', '-'))
                    if ' ' in img_url:
                        new_variations.append(img_url.replace(' ', '%20'))
                        new_variations.append(img_url.replace(' ', '-'))
                
                for variation in new_variations:
                    if is_same_origin(base_netloc, variation):
                        image_urls.add(variation)
                
                print(f"  [debug] Found {len(image_urls)} total unique images so far")
                
                # Find more pages to crawl - LIMIT to prevent infinite loops
                new_pages = 0
                for a in soup.find_all("a", href=True):
                    if new_pages >= 5:  # Limit new pages per page to prevent explosion
                        break
                    link_url = normalize_url(url, a["href"])
                    if (link_url and is_same_origin(base_netloc, link_url) and 
                        link_url not in visited and link_url not in to_visit and
                        not any(ext in link_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico', '.bmp', '.tiff', '.css', '.js', '.pdf', '.zip'])):
                        to_visit.append(link_url)
                        new_pages += 1
                
                # If we found a lot of images on the first page, we might not need to crawl more
                if page_count == 1 and len(image_urls) > 50:
                    print(f"  [debug] Found many images on first page, limiting further crawling")
                    # Only keep a few more pages to check
                    to_visit = to_visit[:3]
                        
            except Exception as e:
                print(f"  [parse error] {e}")
        
        visited.add(url)
        
        # Safety check - if we've been running too long, break
        if page_count > 10:  # Limit total pages to prevent infinite loops
            print(f"  [debug] Reached page limit, stopping discovery")
            break
    
    if shutdown_requested:
        print(f"🛑 Discovery stopped by user. Found {len(image_urls)} unique images across {page_count} pages", flush=True)
    else:
        print(f"Found {len(image_urls)} unique images across {page_count} pages", flush=True)
    return image_urls

def download_all_images(image_urls, output_dir, max_workers=5, timeout=20):
    """Download all images concurrently."""
    if not image_urls:
        print("No images found to download", flush=True)
        return
    
    if shutdown_requested:
        print("🛑 Download cancelled due to shutdown request", flush=True)
        return
    
    print(f"Downloading {len(image_urls)} images to {output_dir}...", flush=True)
    ensure_dir(output_dir)
    
    session = requests.Session()
    
    successful_downloads = 0
    failed_downloads = 0
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all download tasks
        future_to_url = {
            executor.submit(download_image_worker, session, url, output_dir, timeout): url
            for url in image_urls
        }
        
        # Process completed downloads
        for future in as_completed(future_to_url):
            # Check for shutdown request
            if shutdown_requested:
                print("🛑 Cancelling remaining downloads...", flush=True)
                break
                
            url = future_to_url[future]
            try:
                success, final_url, message = future.result()
                if success:
                    successful_downloads += 1
                    print(f"  ✓ {os.path.basename(final_url)}", flush=True)
                else:
                    failed_downloads += 1
                    print(f"  ✗ {url} - {message}", flush=True)
            except Exception as e:
                failed_downloads += 1
                print(f"  ✗ {url} - Exception: {e}", flush=True)
    
    if shutdown_requested:
        print(f"\n🛑 Download interrupted by user!", flush=True)
        print(f"Successfully downloaded: {successful_downloads}", flush=True)
        print(f"Failed downloads: {failed_downloads}", flush=True)
    else:
        print(f"\nDownload complete!", flush=True)
        print(f"Successfully downloaded: {successful_downloads}", flush=True)
        print(f"Failed downloads: {failed_downloads}", flush=True)

def main():
    """Main function."""
    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    print(BANNER)
    print("Image Extractor")
    print("=" * 50)
    
    # Read configuration
    config = read_config()
    start_url = config['start_url']
    max_pages = config['max_pages']
    delay = config['delay']
    max_workers = config['max_workers']
    same_domain_only = config['same_domain_only']
    
    # Create output directory
    parsed = urlparse(start_url)
    site_name = parsed.netloc.replace('www.', '')
    output_dir = os.path.join("scraped_site", f"{site_name}-images")
    
    print(f"Website: {start_url}", flush=True)
    print(f"Output: {output_dir}", flush=True)
    print(f"Max pages: {max_pages}", flush=True)
    print(f"Delay: {delay}s", flush=True)
    print(f"Workers: {max_workers}", flush=True)
    print(f"Same domain only: {same_domain_only}", flush=True)
    print(flush=True)
    
    # Set up session - use minimal headers to avoid getting limited content
    session = requests.Session()
    
    # Discover all images
    image_urls = discover_images_fast(session, start_url, max_pages, delay, timeout=10)
    
    # Download all images
    download_all_images(image_urls, output_dir, max_workers, timeout=20)
    
    if shutdown_requested:
        print("\n🛑 Image extraction stopped by user!", flush=True)
    else:
        print("\nImage extraction complete!", flush=True)
        
        # If no images were found, provide helpful suggestions
        if len(image_urls) == 0:
            print("\n💡 No images found. This could be because:")
            print("   • The website doesn't contain images")
            print("   • Images are loaded dynamically with JavaScript")
            print("   • The website requires authentication")
            print("   • The domain doesn't exist or is down")
            print("\n🔧 Try:")
            print("   • Using a different website URL")
            print("   • Checking if the website loads in your browser")
            print("   • Using the full scraper (scrape.py) instead")

if __name__ == "__main__":
    main()
