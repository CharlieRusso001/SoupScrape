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

# Try to import Selenium for JavaScript rendering
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.common.exceptions import TimeoutException, WebDriverException
    SELENIUM_AVAILABLE = True
except ImportError:
    SELENIUM_AVAILABLE = False
    print("⚠️  Selenium not available. Install with: pip install selenium")
    print("   JavaScript-rendered images will not be detected.")

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

def create_headless_driver():
    """Create a headless Chrome driver for JavaScript rendering."""
    if not SELENIUM_AVAILABLE:
        return None
    
    try:
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        chrome_options.add_argument("--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")
        
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(30)
        return driver
    except Exception as e:
        print(f"⚠️  Could not create Chrome driver: {e}")
        print("   Make sure Chrome and ChromeDriver are installed.")
        return None


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
    
    # Remove fragment (everything after #)
    url, _ = urldefrag(url)
    
    return url

def is_same_origin(base_netloc, url):
    """Check if URL is from the same domain or related CDN domains."""
    try:
        url_netloc = urlparse(url).netloc
        if url_netloc == base_netloc:
            return True
        
        # Extract base domain (remove www)
        base_domain = base_netloc.replace('www.', '')
        url_domain = url_netloc.replace('www.', '')
        
        # Check if it's the same base domain
        if base_domain == url_domain:
            return True
        
        # Allow common CDN domains that are clearly part of the same website
        cdn_domains = [
            'static.wixstatic.com',
            'siteassets.parastorage.com', 
            'static.parastorage.com',
            'wixstatic.com',
            'parastorage.com',
            'on.demandware.static',  # Tag Heuer's CDN
            'demandware.static',
            'cdn.',  # Any CDN subdomain
            'assets.',  # Any assets subdomain
            'media.',  # Any media subdomain
            'images.',  # Any images subdomain
            'static.',  # Any static subdomain
        ]
        
        # Check if it's a known CDN domain
        for cdn_domain in cdn_domains:
            if cdn_domain in url_netloc:
                return True
        
        # Check if it's a subdomain of the base domain
        if url_domain.endswith('.' + base_domain):
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
        # Debug: Log the URL being attempted
        parsed_url = urlparse(url)
        if not parsed_url.netloc:
            print(f"  [debug] WARNING: URL has no netloc: {url}", flush=True)
            return False, url, "URL has no domain"
        
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
                # Try direct GET request first (some servers don't support HEAD)
                resp = session.get(try_url, timeout=timeout, stream=True, allow_redirects=True)
                if resp.status_code == 200:
                    content_type = resp.headers.get('Content-Type', '').lower()
                    content_length = resp.headers.get('Content-Length', '0')
                    
                    # Check if it's an image
                    if any(ext in content_type for ext in ['image/', 'jpeg', 'png', 'gif', 'webp', 'svg', 'ico', 'bmp', 'tiff']):
                        # Check file size (skip very small files that might be errors)
                        if content_length and int(content_length) < 50:
                            continue
                            
                        filename = generate_safe_filename(try_url, content_type)
                        filepath = os.path.join(output_dir, filename)
                        
                        # Ensure directory exists
                        os.makedirs(os.path.dirname(filepath), exist_ok=True)
                        
                        # Download the content
                        content = resp.content
                        if len(content) < 50:  # Skip very small files
                            continue
                            
                        with open(filepath, 'wb') as f:
                            f.write(content)
                        
                        return True, try_url, f"Downloaded {len(content)} bytes"
                    else:
                        # Check if it's an SVG or other image type that might not have proper content-type
                        parsed_url = urlparse(try_url)
                        path_lower = parsed_url.path.lower()
                        if any(ext in path_lower for ext in ['.svg', '.ico', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tiff']):
                            # It looks like an image file, try to download it anyway
                            filename = generate_safe_filename(try_url, content_type)
                            filepath = os.path.join(output_dir, filename)
                            
                            os.makedirs(os.path.dirname(filepath), exist_ok=True)
                            
                            content = resp.content
                            if len(content) > 50:  # Only save if it has reasonable content
                                with open(filepath, 'wb') as f:
                                    f.write(content)
                                
                                return True, try_url, f"Downloaded {len(content)} bytes (no content-type)"
                elif resp.status_code == 404:
                    continue  # Try next URL variation
                elif resp.status_code in [301, 302, 303, 307, 308]:
                    # Handle redirects
                    redirect_url = resp.headers.get('Location')
                    if redirect_url:
                        # Try the redirect URL
                        redirect_resp = session.get(redirect_url, timeout=timeout, stream=True)
                        if redirect_resp.status_code == 200:
                            content_type = redirect_resp.headers.get('Content-Type', '').lower()
                            if any(ext in content_type for ext in ['image/', 'jpeg', 'png', 'gif', 'webp', 'svg', 'ico', 'bmp', 'tiff']):
                                filename = generate_safe_filename(redirect_url, content_type)
                                filepath = os.path.join(output_dir, filename)
                                
                                os.makedirs(os.path.dirname(filepath), exist_ok=True)
                                
                                content = redirect_resp.content
                                if len(content) > 50:
                                    with open(filepath, 'wb') as f:
                                        f.write(content)
                                    
                                    return True, redirect_url, f"Downloaded {len(content)} bytes (redirected)"
                else:
                    continue
            except requests.exceptions.RequestException as e:
                # Log the specific error for debugging
                if "404" in str(e) or "Not Found" in str(e):
                    continue  # Try next URL variation
                elif "timeout" in str(e).lower():
                    continue  # Try next URL variation
                else:
                    continue  # Try next URL variation
            except Exception:
                continue
        
        return False, url, "All URL variations failed"
        
    except Exception as e:
        return False, url, f"Worker error: {e}"

def discover_and_download_images_with_selenium(driver, start_url, output_dir, max_pages=5, max_workers=5, timeout=20):
    """Discover and download images using Selenium for JavaScript-rendered content."""
    if not driver:
        return set(), 0, 0
    
    print(f"🔍 Using Selenium to discover and download JavaScript-rendered images...", flush=True)
    
    parsed = urlparse(start_url)
    base_netloc = parsed.netloc
    image_urls = set()
    visited = set()
    to_visit = [start_url]
    page_count = 0
    downloaded_count = 0
    failed_count = 0
    
    while to_visit and page_count < max_pages and not shutdown_requested:
        url = to_visit.pop(0)
        url, _ = urldefrag(url)
        
        if url in visited:
            continue
        if not is_same_origin(base_netloc, url):
            continue
        
        page_count += 1
        print(f"[selenium page {page_count}] {url}", flush=True)
        
        try:
            driver.get(url)
            
            # Wait for page to load and images to appear
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )
            
            # Scroll down to trigger lazy loading
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(2)
            
            # Find all img elements
            img_elements = driver.find_elements(By.TAG_NAME, "img")
            for img in img_elements:
                try:
                    src = img.get_attribute("src")
                    if src:
                        # Normalize the URL to make it absolute
                        abs_src = normalize_url(url, src)
                        if abs_src:
                            if is_same_origin(base_netloc, abs_src):
                                image_urls.add(abs_src)
                            else:
                                # Debug: Log rejected URLs
                                parsed_abs = urlparse(abs_src)
                                print(f"  [selenium debug] Rejected URL (domain mismatch): {parsed_abs.netloc}", flush=True)
                    
                    # Also check data-src for lazy loading
                    data_src = img.get_attribute("data-src")
                    if data_src:
                        abs_data_src = normalize_url(url, data_src)
                        if abs_data_src:
                            if is_same_origin(base_netloc, abs_data_src):
                                image_urls.add(abs_data_src)
                            else:
                                # Debug: Log rejected URLs
                                parsed_abs = urlparse(abs_data_src)
                                print(f"  [selenium debug] Rejected data-src (domain mismatch): {parsed_abs.netloc}", flush=True)
                    
                    # Check other common lazy loading attributes
                    for attr in ["data-lazy", "data-original", "data-srcset"]:
                        lazy_src = img.get_attribute(attr)
                        if lazy_src:
                            abs_lazy_src = normalize_url(url, lazy_src)
                            if abs_lazy_src:
                                if is_same_origin(base_netloc, abs_lazy_src):
                                    image_urls.add(abs_lazy_src)
                                else:
                                    # Debug: Log rejected URLs
                                    parsed_abs = urlparse(abs_lazy_src)
                                    print(f"  [selenium debug] Rejected {attr} (domain mismatch): {parsed_abs.netloc}", flush=True)
                        
                except Exception:
                    continue
            
            # Find background images in CSS
            elements_with_bg = driver.find_elements(By.XPATH, "//*[@style]")
            for element in elements_with_bg:
                try:
                    style = element.get_attribute("style")
                    if "background-image" in style:
                        # Extract URL from background-image: url(...)
                        bg_match = re.search(r'background-image:\s*url\(["\']?([^"\']+)["\']?\)', style)
                        if bg_match:
                            bg_url = bg_match.group(1)
                            abs_bg_url = normalize_url(url, bg_url)
                            if abs_bg_url and is_same_origin(base_netloc, abs_bg_url):
                                image_urls.add(abs_bg_url)
                except Exception:
                    continue
            
            # Also check computed styles for background images
            try:
                all_elements = driver.find_elements(By.XPATH, "//*")
                for element in all_elements[:50]:  # Limit to first 50 elements to avoid slowdown
                    try:
                        computed_style = driver.execute_script("return window.getComputedStyle(arguments[0]).backgroundImage;", element)
                        if computed_style and computed_style != "none":
                            # Extract URL from computed background-image
                            bg_match = re.search(r'url\(["\']?([^"\']+)["\']?\)', computed_style)
                            if bg_match:
                                bg_url = bg_match.group(1)
                                abs_bg_url = normalize_url(url, bg_url)
                                if abs_bg_url and is_same_origin(base_netloc, abs_bg_url):
                                    image_urls.add(abs_bg_url)
                    except Exception:
                        continue
            except Exception:
                pass
            
            print(f"  [selenium] Found {len(image_urls)} total unique images so far", flush=True)
            
            # Debug: Show some example URLs found by Selenium
            if len(image_urls) > 0:
                sample_urls = list(image_urls)[:3]  # Show first 3 URLs
                for sample_url in sample_urls:
                    parsed_sample = urlparse(sample_url)
                    print(f"  [selenium debug] Sample URL: {parsed_sample.netloc}{parsed_sample.path[:50]}...")
            
            # Download newly discovered images immediately
            if image_urls:
                print(f"  [selenium downloading] Starting download of {len(image_urls)} images...", flush=True)
                session = requests.Session()
                session.headers.update({
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                    'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                })
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    future_to_url = {
                        executor.submit(download_image_worker, session, img_url, output_dir, timeout): img_url
                        for img_url in image_urls
                    }
                    
                    for future in as_completed(future_to_url):
                        if shutdown_requested:
                            break
                        img_url = future_to_url[future]
                        try:
                            success, final_url, message = future.result()
                            if success:
                                downloaded_count += 1
                                print(f"  ✓ Downloaded: {os.path.basename(final_url)}", flush=True)
                            else:
                                failed_count += 1
                                print(f"  ✗ Failed: {os.path.basename(img_url)} - {message}", flush=True)
                        except Exception as e:
                            failed_count += 1
                            print(f"  ✗ Error: {os.path.basename(img_url)} - {e}", flush=True)
            
            # Find more pages to visit
            links = driver.find_elements(By.TAG_NAME, "a")
            new_pages = 0
            for link in links[:10]:  # Limit to first 10 links
                if new_pages >= 3:  # Limit new pages per page
                    break
                try:
                    href = link.get_attribute("href")
                    if href:
                        abs_url = normalize_url(url, href)
                        if (abs_url and is_same_origin(base_netloc, abs_url) and 
                            abs_url not in visited and abs_url not in to_visit and
                            not any(ext in abs_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico', '.bmp', '.tiff', '.css', '.js', '.pdf', '.zip'])):
                            to_visit.append(abs_url)
                            new_pages += 1
                except Exception:
                    continue
            
            visited.add(url)
            
        except TimeoutException:
            print(f"  [selenium timeout] {url}", flush=True)
            visited.add(url)
        except Exception as e:
            print(f"  [selenium error] {url}: {e}", flush=True)
            visited.add(url)
    
    return image_urls, downloaded_count, failed_count

def discover_and_download_images_fast(session, start_url, output_dir, max_pages=10, delay=0.1, timeout=10, max_workers=5):
    """Fast image discovery with continuous downloading."""
    print(f"Discovering and downloading images from {start_url}...", flush=True)
    
    parsed = urlparse(start_url)
    base_netloc = parsed.netloc
    
    image_urls = set()
    visited = set()
    to_visit = [start_url]
    page_count = 0
    downloaded_count = 0
    failed_count = 0
    
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
                
                # METHOD 2: Fast regex for relative URLs (including those with query parameters)
                relative_pattern = r'["\']([^"\']*\.(?:jpg|jpeg|png|gif|webp|svg|ico|bmp|tiff|jfif|avif)(?:\?[^"\']*)?)["\']'
                relative_urls = re.findall(relative_pattern, html_text, re.IGNORECASE)
                for rel_url in relative_urls:
                    abs_url = normalize_url(url, rel_url)
                    if abs_url and is_same_origin(base_netloc, abs_url):
                        image_urls.add(abs_url)
                
                # METHOD 3: Look for URLs in src attributes that might not have been caught
                src_pattern = r'src=["\']([^"\']+)["\']'
                src_urls = re.findall(src_pattern, html_text, re.IGNORECASE)
                for src_url in src_urls:
                    if any(ext in src_url.lower() for ext in ['.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico', '.bmp', '.tiff', '.jfif', '.avif']):
                        abs_url = normalize_url(url, src_url)
                        if abs_url and is_same_origin(base_netloc, abs_url):
                            image_urls.add(abs_url)
                
                # METHOD 4: Quick BeautifulSoup for src attributes only
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
                
                # Debug: Show some example URLs found
                if len(image_urls) > 0:
                    sample_urls = list(image_urls)[:3]  # Show first 3 URLs
                    for sample_url in sample_urls:
                        parsed_sample = urlparse(sample_url)
                        print(f"  [debug] Sample URL: {parsed_sample.netloc}{parsed_sample.path[:50]}...")
                
                # Download newly discovered images immediately
                # We'll download all images found so far (this is a simple approach)
                if image_urls:
                    print(f"  [downloading] Starting download of {len(image_urls)} images...", flush=True)
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        future_to_url = {
                            executor.submit(download_image_worker, session, img_url, output_dir, timeout): img_url
                            for img_url in image_urls
                        }
                        
                        for future in as_completed(future_to_url):
                            if shutdown_requested:
                                break
                            img_url = future_to_url[future]
                            try:
                                success, final_url, message = future.result()
                                if success:
                                    downloaded_count += 1
                                    print(f"  ✓ Downloaded: {os.path.basename(final_url)}", flush=True)
                                else:
                                    failed_count += 1
                                    print(f"  ✗ Failed: {os.path.basename(img_url)} - {message}", flush=True)
                            except Exception as e:
                                failed_count += 1
                                print(f"  ✗ Error: {os.path.basename(img_url)} - {e}", flush=True)
                
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
        print(f"📊 Downloaded: {downloaded_count}, Failed: {failed_count}", flush=True)
    else:
        print(f"Found {len(image_urls)} unique images across {page_count} pages", flush=True)
        print(f"📊 Downloaded: {downloaded_count}, Failed: {failed_count}", flush=True)
    
    return image_urls, downloaded_count, failed_count

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
    
    # Set up session with proper headers
    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.9',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
    })
    
    # Discover and download images using both methods
    total_downloaded = 0
    total_failed = 0
    
    # Method 1: Fast discovery with requests (for static images)
    print("🔍 Method 1: Fast discovery and download with requests...", flush=True)
    static_images, static_downloaded, static_failed = discover_and_download_images_fast(
        session, start_url, output_dir, max_pages, delay, timeout=10, max_workers=max_workers
    )
    total_downloaded += static_downloaded
    total_failed += static_failed
    print(f"📊 Method 1: Found {len(static_images)} static images, Downloaded: {static_downloaded}, Failed: {static_failed}", flush=True)
    
    # Method 2: Selenium discovery (for JavaScript-rendered images)
    if SELENIUM_AVAILABLE:
        print("🔍 Method 2: Selenium discovery and download for JavaScript images...", flush=True)
        driver = create_headless_driver()
        if driver:
            try:
                js_images, js_downloaded, js_failed = discover_and_download_images_with_selenium(
                    driver, start_url, output_dir, max_pages=3, max_workers=max_workers, timeout=20
                )
                total_downloaded += js_downloaded
                total_failed += js_failed
                print(f"📊 Method 2: Found {len(js_images)} JavaScript-rendered images, Downloaded: {js_downloaded}, Failed: {js_failed}", flush=True)
            finally:
                driver.quit()
        else:
            print("⚠️  Selenium driver not available, skipping JavaScript discovery", flush=True)
    else:
        print("⚠️  Selenium not available, skipping JavaScript discovery", flush=True)
    
    print(f"📊 Total Results: Downloaded: {total_downloaded}, Failed: {total_failed}", flush=True)
    
    if shutdown_requested:
        print("\n🛑 Image extraction stopped by user!", flush=True)
    else:
        print("\nImage extraction complete!", flush=True)
        
        # If no images were found, provide helpful suggestions
        if total_downloaded == 0:
            print("\n💡 No images found. This could be because:")
            print("   • The website doesn't contain images")
            print("   • Images are loaded dynamically with JavaScript")
            print("   • The website requires authentication")
            print("   • The domain doesn't exist or is down")
            print("\n🔧 Try:")
            print("   • Using a different website URL")
            print("   • Checking if the website loads in your browser")
            print("   • Installing Selenium for JavaScript support: pip install selenium")
            print("   • Using the full scraper (scrape.py) instead")

if __name__ == "__main__":
    main()
