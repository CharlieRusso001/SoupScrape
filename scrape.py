#!/usr/bin/env python3
"""
mirror_site.py

Mirror a site (HTML + images + CSS + JS + fonts + videos) into a local directory,
and rewrite links so you can browse it offline.

Usage:
    python mirror_site.py https://example.com output_dir --max-pages 1000 --delay 0.5 --obey-robots

Notes:
 - This is a simple but practical mirror tool. It does NOT execute JavaScript.
 - For JS-heavy sites, consider using Playwright/Selenium to render pages first.
"""

import os
import re
import time
import argparse
import hashlib
import sys
from urllib.parse import urlparse, urljoin, urldefrag
import requests
from bs4 import BeautifulSoup
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from queue import Queue
import mimetypes
import signal

# Set UTF-8 encoding for console output
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except:
        pass

USER_AGENT = "MirrorBot/1.0 (+https://example.com/bot)"

# Global flag for graceful shutdown
shutdown_requested = False

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    global shutdown_requested
    print("\n🛑 Shutdown requested by user (Ctrl+C)")
    print("⏳ Stopping gracefully... Please wait...")
    shutdown_requested = True

# Resource tag attribute mapping to consider for downloading/relinking
RESOURCE_TAGS = [
    ("img", "src"),
    ("img", "srcset"),
    ("script", "src"),
    ("link", "href"),        # CSS (rel=stylesheet) and others
    ("source", "src"),
    ("source", "srcset"),
    ("video", "src"),
    ("audio", "src"),
    ("iframe", "src"),
]

# File extensions that we treat as binary resources; others saved as text
BINARY_EXTS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tiff", ".tif",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp4", ".webm", ".ogg", ".mp3", ".wav", ".avi", ".mov",
    ".pdf", ".zip", ".rar", ".7z", ".tar", ".gz",
)

# Image-specific extensions for better detection
IMAGE_EXTS = (
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp", ".tiff", ".tif", ".avif", ".jfif"
)

# CSS url(...) pattern
CSS_URL_RE = re.compile(r'url\(\s*([\'"]?)(?P<url>[^)\'"]+)\1\s*\)', flags=re.IGNORECASE)


def read_config(config_file="config.txt"):
    """
    Read configuration from a text file.
    Returns a dictionary with configuration values.
    """
    config = {}
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                # Parse key=value pairs
                if '=' in line:
                    key, value = line.split('=', 1)
                    key = key.strip()
                    value = value.strip()
                    
                    # Convert boolean values
                    if value.lower() in ('true', 'yes', '1'):
                        config[key] = True
                    elif value.lower() in ('false', 'no', '0'):
                        config[key] = False
                    # Convert numeric values
                    elif value.isdigit():
                        config[key] = int(value)
                    elif value.replace('.', '').isdigit():
                        config[key] = float(value)
                    else:
                        config[key] = value
    except FileNotFoundError:
        print(f"Configuration file '{config_file}' not found. Using defaults.")
    except Exception as e:
        print(f"Error reading configuration file: {e}")
    
    return config


def ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def url_to_path(base_dir, base_netloc, url):
    """
    Convert a URL to a local filesystem path (under base_dir).
    Keeps directory structure from path, normalizes, appends query hash if needed.
    """
    parsed = urlparse(url)
    assert parsed.netloc, "url_to_path requires absolute url"

    # use netloc as top folder so different hosts don't collide
    netloc_dir = os.path.join(base_dir, parsed.netloc)
    path = parsed.path or '/'
    if path.endswith("/"):
        path = path + "index.html"
    # when path has no extension and looks like a page, ensure .html
    name, ext = os.path.splitext(path)
    if not ext:
        # if path ends with something like /about -> /about/index.html
        path = path + "/index.html"
    # sanitize - remove leading slash
    if path.startswith("/"):
        path = path[1:]
    # include query hash if query exists
    if parsed.query:
        qhash = hashlib.sha1(parsed.query.encode()).hexdigest()[:8]
        # append to filename before extension
        root, ext = os.path.splitext(path)
        path = f"{root}__q{qhash}{ext}"
    full = os.path.join(netloc_dir, path)
    # normalize
    full = os.path.normpath(full)
    return full


def is_same_origin(base_netloc, url):
    try:
        return urlparse(url).netloc == base_netloc
    except Exception:
        return False


def normalize_url(base_url, link):
    if not link:
        return None
    link = link.strip()
    # skip javascript: and mailto:, tel:, data:
    if link.startswith("javascript:") or link.startswith("mailto:") or link.startswith("tel:") or link.startswith("data:"):
        return None
    # build absolute
    abs_u = urljoin(base_url, link)
    abs_u, _ = urldefrag(abs_u)
    return abs_u


def looks_like_resource(url):
    path = urlparse(url).path.lower()
    for ext in BINARY_EXTS:
        if path.endswith(ext):
            return True
    # also treat .css and .js as resources
    if path.endswith(".css") or path.endswith(".js"):
        return True
    return False


def is_image_url(url):
    """Check if URL points to an image based on extension or content type"""
    path = urlparse(url).path.lower()
    for ext in IMAGE_EXTS:
        if path.endswith(ext):
            return True
    return False


def get_content_type_from_url(url):
    """Try to determine content type from URL extension"""
    path = urlparse(url).path
    mime_type, _ = mimetypes.guess_type(path)
    return mime_type


def fetch_url(session, url, stream=False, timeout=20):
    try:
        # Disable automatic redirects to avoid www redirect issues
        resp = session.get(url, stream=stream, timeout=timeout, allow_redirects=False)
        
        # Handle redirects manually
        if resp.status_code in [301, 302, 303, 307, 308]:
            redirect_url = resp.headers.get('Location')
            if redirect_url:
                # Check if redirect is to a different domain
                from urllib.parse import urlparse
                original_domain = urlparse(url).netloc
                redirect_domain = urlparse(redirect_url).netloc
                
                if original_domain != redirect_domain:
                    print(f"  [redirect warning] {url} -> {redirect_url} (different domain)")
                    # Try the redirect URL
                    resp = session.get(redirect_url, stream=stream, timeout=timeout)
                else:
                    # Same domain redirect, follow it
                    resp = session.get(redirect_url, stream=stream, timeout=timeout)
        
        resp.raise_for_status()
        return resp
    except Exception as e:
        print(f"  [fetch error] {url} -> {e}")
        return None


def download_resource_worker(session, url, local_path, timeout=20, delay=0.1, images_dir=None):
    """Worker function for concurrent resource downloads"""
    try:
        time.sleep(delay)  # Small delay to avoid overwhelming server
        resp = fetch_url(session, url, stream=True, timeout=timeout)
        if not resp:
            return False, url, None
        
        # Determine if it's an image or other resource
        content_type = resp.headers.get("Content-Type", "").lower()
        is_image = is_image_url(url) or any(img_type in content_type for img_type in ["image/", "image"])
        
        # If it's an image and we have an images directory, save it there too
        if is_image and images_dir:
            # Create a simple filename for the image
            parsed = urlparse(url)
            filename = os.path.basename(parsed.path)
            if not filename or '.' not in filename:
                # Generate filename from URL hash
                filename = f"image_{hash(url) % 100000}.jpg"
            # Clean filename
            filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
            image_path = os.path.join(images_dir, filename)
            
            if save_binary(resp, image_path):
                print(f"  [downloading image] {url} -> {image_path}", flush=True)
            else:
                print(f"  [failed to save image] {url}", flush=True)
        elif is_image:
            print(f"  [downloading image] {url}", flush=True)
        else:
            print(f"  [downloading resource] {url}", flush=True)
        
        # Save the file to original location
        if save_binary(resp, local_path):
            return True, url, local_path
        else:
            return False, url, None
            
    except Exception as e:
        print(f"  [worker error] {url} -> {e}")
        return False, url, None


def save_binary(resp, filepath):
    ensure_dir(os.path.dirname(filepath))
    try:
        with open(filepath, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                if chunk:
                    f.write(chunk)
        return True
    except Exception as e:
        print(f"  [save error] {filepath} -> {e}")
        return False


def save_text(text, filepath, encoding="utf-8"):
    ensure_dir(os.path.dirname(filepath))
    try:
        with open(filepath, "w", encoding=encoding, errors="replace") as f:
            f.write(text)
        return True
    except Exception as e:
        print(f"  [save error] {filepath} -> {e}")
        return False


def rewrite_html_links(soup, page_url, mapping, base_dir):
    """
    Replace resource URLs in the soup to mapped local paths.
    mapping: dict(original_url -> local_path)
    Returns modified HTML string.
    """
    # Handle tags in RESOURCE_TAGS
    for tag, attr in RESOURCE_TAGS:
        for node in soup.find_all(tag):
            if not node.has_attr(attr):
                continue
            val = node[attr]
            if attr == "srcset":
                # multiple candidates separated by comma
                new_parts = []
                parts = [p.strip() for p in val.split(",") if p.strip()]
                for part in parts:
                    # part like "image.jpg 1x" or "image-800.jpg 800w"
                    comps = part.split()
                    url_part = comps[0]
                    abs_u = normalize_url(page_url, url_part)
                    if abs_u and abs_u in mapping:
                        local_rel = os.path.relpath(mapping[abs_u], os.path.dirname(mapping[page_url]))
                        comps[0] = local_rel.replace(os.path.sep, "/")
                    new_parts.append(" ".join(comps))
                node[attr] = ", ".join(new_parts)
            else:
                abs_u = normalize_url(page_url, val)
                if abs_u and abs_u in mapping:
                    # compute relative path from current page file to resource file
                    src_local = mapping[abs_u]
                    rel = os.path.relpath(src_local, os.path.dirname(mapping[page_url]))
                    node[attr] = rel.replace(os.path.sep, "/")

    # Also rewrite inline styles with url(...) and style tags
    # style attributes
    for node in soup.find_all(style=True):
        original = node["style"]
        node["style"] = rewrite_css_urls(original, page_url, mapping, mapping[page_url])

    # <style> blocks
    for style_tag in soup.find_all("style"):
        if style_tag.string:
            style_tag.string = rewrite_css_urls(style_tag.string, page_url, mapping, mapping[page_url])

    return str(soup)


def rewrite_css_urls(css_text, page_url, mapping, page_localpath):
    """
    Replace url(...) inside CSS text to local relative paths where applicable.
    page_localpath used to compute relative paths from the page to resource.
    """
    def repl(m):
        u = m.group("url").strip().strip('\'"')
        abs_u = normalize_url(page_url, u)
        if abs_u and abs_u in mapping:
            rel = os.path.relpath(mapping[abs_u], os.path.dirname(page_localpath))
            return f'url("{rel.replace(os.path.sep, "/")}")'
        else:
            return m.group(0)
    return CSS_URL_RE.sub(repl, css_text)


def mirror(start_url, outdir, max_pages=1000, delay=0.5, obey_robots=True, same_domain_only=True, user_agent=None, timeout=20, max_workers=5, images_dir=None):
    session = requests.Session()
    if user_agent:
        session.headers.update({"User-Agent": user_agent})
    else:
        session.headers.update({"User-Agent": USER_AGENT})

    parsed = urlparse(start_url)
    base_netloc = parsed.netloc
    base_root = f"{parsed.scheme}://{parsed.netloc}"

    # robots
    rp = urllib.robotparser.RobotFileParser()
    if obey_robots:
        try:
            rp.set_url(urljoin(base_root, "/robots.txt"))
            rp.read()
        except Exception:
            pass

    def allowed_by_robots(url):
        if not obey_robots:
            return True
        try:
            return rp.can_fetch(USER_AGENT, url)
        except Exception:
            return True

    to_visit_pages = [start_url]
    visited_pages = set()
    to_visit_resources = []
    downloaded = {}  # original_url -> local_path

    page_count = 0
    resource_count = 0

    while (to_visit_pages or to_visit_resources) and page_count < max_pages:
        # Prioritize pages first
        if to_visit_pages:
            url = to_visit_pages.pop(0)
            url, _ = urldefrag(url)
            if url in visited_pages:
                continue
            if same_domain_only and not is_same_origin(base_netloc, url):
                visited_pages.add(url)
                continue
            if not allowed_by_robots(url):
                print(f"[robots] skip {url}")
                visited_pages.add(url)
                continue

            print(f"[page] fetching {url}", flush=True)
            resp = fetch_url(session, url, stream=False, timeout=timeout)
            if not resp:
                visited_pages.add(url)
                time.sleep(delay)
                continue

            content_type = resp.headers.get("Content-Type", "")
            body = resp.text
            # compute local path for this page
            local_page_path = url_to_path(outdir, base_netloc, url)
            downloaded[url] = local_page_path

            # parse HTML and discover resources and links
            soup = BeautifulSoup(body, "html.parser")

            # find resource links and enqueue
            for tag, attr in RESOURCE_TAGS:
                for node in soup.find_all(tag):
                    if not node.has_attr(attr):
                        continue
                    raw = node[attr]
                    if not raw:
                        continue
                    if attr == "srcset":
                        # multiple candidates
                        parts = [p.strip() for p in raw.split(",") if p.strip()]
                        for part in parts:
                            comps = part.split()
                            url_part = comps[0]
                            abs_r = normalize_url(url, url_part)
                            if abs_r and abs_r not in downloaded and abs_r not in to_visit_resources and abs_r not in to_visit_pages:
                                # if the srcset candidate looks like a page (rare), enqueue as page, else resource
                                if looks_like_resource(abs_r):
                                    to_visit_resources.append(abs_r)
                                else:
                                    to_visit_pages.append(abs_r)
                    else:
                        abs_r = normalize_url(url, raw)
                        if not abs_r:
                            continue
                        if abs_r in downloaded:
                            continue
                        # if resource (css, img, js), enqueue resource, otherwise maybe it's a page link
                        if looks_like_resource(abs_r):
                            if abs_r not in to_visit_resources:
                                to_visit_resources.append(abs_r)
                        else:
                            # For <a href> and if it's an HTML page, add to pages
                            # But some tags like iframe might be a page too; treat conservatively:
                            if tag in ("a", "iframe"):
                                if abs_r not in to_visit_pages:
                                    to_visit_pages.append(abs_r)
                            else:
                                # unknown tag; treat as resource
                                if abs_r not in to_visit_resources:
                                    to_visit_resources.append(abs_r)

            # Also find anchor links (<a href>) to follow
            for a in soup.find_all("a", href=True):
                abs_a = normalize_url(url, a["href"])
                if not abs_a:
                    continue
                if same_domain_only and not is_same_origin(base_netloc, abs_a):
                    continue
                if abs_a in visited_pages or abs_a in to_visit_pages:
                    continue
                # Heuristic: follow links that look like HTML
                if looks_like_resource(abs_a):
                    # if it looks like resource but it's actually html, it'll be handled later
                    to_visit_resources.append(abs_a)
                else:
                    to_visit_pages.append(abs_a)

            # Save raw HTML for now, but we will rewrite links later after resources downloaded/save mapping
            save_text(body, local_page_path, encoding=resp.encoding or "utf-8")
            print(f"  [saved page] {local_page_path}", flush=True)
            visited_pages.add(url)
            page_count += 1
            time.sleep(delay)
        else:
            # handle resource queue with concurrent downloads
            if to_visit_resources:
                # Process resources in batches for concurrent downloading
                batch_size = min(max_workers * 2, len(to_visit_resources))
                resource_batch = []
                
                for _ in range(batch_size):
                    if to_visit_resources:
                        res_url = to_visit_resources.pop(0)
                        res_url, _ = urldefrag(res_url)
                        if res_url in downloaded:
                            continue
                        if same_domain_only and not is_same_origin(base_netloc, res_url):
                            downloaded[res_url] = None
                            continue
                        if not allowed_by_robots(res_url):
                            print(f"[robots] skip resource {res_url}")
                            downloaded[res_url] = None
                            continue
                        
                        local_path = url_to_path(outdir, base_netloc, res_url)
                        resource_batch.append((res_url, local_path))
                
                if resource_batch:
                    print(f"[batch] downloading {len(resource_batch)} resources concurrently...", flush=True)
                    
                    # Use ThreadPoolExecutor for concurrent downloads
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        # Submit all download tasks
                        future_to_url = {
                            executor.submit(download_resource_worker, session, url, local_path, timeout, delay/2, images_dir): url 
                            for url, local_path in resource_batch
                        }
                        
                        # Process completed downloads
                        for future in as_completed(future_to_url):
                            url = future_to_url[future]
                            try:
                                success, downloaded_url, local_path = future.result()
                                if success:
                                    downloaded[downloaded_url] = local_path
                                    resource_count += 1
                                    
                                    # Special handling for CSS files
                                    if downloaded_url.lower().endswith(".css"):
                                        try:
                                            with open(local_path, "r", encoding="utf-8", errors="replace") as f:
                                                css_text = f.read()
                                            # find referenced urls in CSS and enqueue them
                                            for m in CSS_URL_RE.finditer(css_text):
                                                ref = m.group("url").strip().strip('\'"')
                                                abs_r = normalize_url(downloaded_url, ref)
                                                if abs_r and abs_r not in downloaded and abs_r not in to_visit_resources:
                                                    to_visit_resources.append(abs_r)
                                        except Exception as e:
                                            print(f"  [css processing error] {local_path} -> {e}")
                                    
                                    # Special handling for JS files
                                    elif downloaded_url.lower().endswith(".js"):
                                        try:
                                            with open(local_path, "r", encoding="utf-8", errors="replace") as f:
                                                js_text = f.read()
                                            save_text(js_text, local_path, encoding="utf-8")
                                        except Exception as e:
                                            print(f"  [js processing error] {local_path} -> {e}")
                                            
                                else:
                                    downloaded[downloaded_url] = None
                            except Exception as e:
                                print(f"  [concurrent download error] {url} -> {e}")
                                downloaded[url] = None
                    
                    time.sleep(delay)  # Brief pause between batches

    # SECOND PASS: rewrite HTML pages and CSS files to use local paths
    print("\nRewriting links in saved pages and CSS...", flush=True)
    # Build reverse mapping: only include successes
    mapping = {k: v for k, v in downloaded.items() if v}
    # also include pages mapping (they were saved earlier to downloaded)
    # downloaded contains pages too (url -> local path)
    # Some pages might be in visited_pages but not in downloaded (if saved earlier), ensure they are present
    # (they were added as downloaded[url] earlier)
    # Now rewrite each saved HTML page
    for orig_url, local_path in list(downloaded.items()):
        if not local_path:
            continue
        # act on HTML pages (extension .html) and CSS files
        _, ext = os.path.splitext(local_path)
        ext = ext.lower()
        if ext in (".html", ".htm"):
            try:
                with open(local_path, "r", encoding="utf-8", errors="replace") as f:
                    txt = f.read()
                soup = BeautifulSoup(txt, "html.parser")
                new_html = rewrite_html_links(soup, orig_url, mapping, outdir)
                save_text(new_html, local_path, encoding="utf-8")
                print(f"  [rewrote page] {local_path}")
            except Exception as e:
                print(f"  [rewrite error page] {local_path} -> {e}")
        elif ext == ".css":
            try:
                with open(local_path, "r", encoding="utf-8", errors="replace") as f:
                    css = f.read()
                new_css = rewrite_css_urls(css, orig_url, mapping, local_path)
                save_text(new_css, local_path, encoding="utf-8")
                print(f"  [rewrote css] {local_path}")
            except Exception as e:
                print(f"  [rewrite error css] {local_path} -> {e}")

    print("\nDone.", flush=True)
    print(f"Pages saved: approx {page_count}; resources saved: approx {resource_count}", flush=True)
    print(f"Output directory: {outdir}", flush=True)


def main():
    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    # Display ASCII banner
    print("""
   ▄████████  ▄██████▄  ███    █▄     ▄███████▄    ▄████████  ▄████████    ▄████████    ▄████████    ▄███████▄    ▄████████ 
  ███    ███ ███    ███ ███    ███   ███    ███   ███    ███ ███    ███   ███    ███   ███    ███   ███    ███   ███    ███ 
  ███    █▀  ███    ███ ███    ███   ███    ███   ███    █▀  ███    █▀    ███    ███   ███    ███   ███    ███   ███    █▀  
  ███        ███    ███ ███    ███   ███    ███   ███        ███         ▄███▄▄▄▄██▀   ███    ███   ███    ███  ▄███▄▄▄     
▀███████████ ███    ███ ███    ███ ▀█████████▀  ▀███████████ ███        ▀▀███▀▀▀▀▀   ▀███████████ ▀█████████▀  ▀▀███▀▀▀     
         ███ ███    ███ ███    ███   ███                 ███ ███    █▄  ▀███████████   ███    ███   ███          ███    █▄  
   ▄█    ███ ███    ███ ███    ███   ███           ▄█    ███ ███    ███   ███    ███   ███    ███   ███          ███    ███ 
 ▄████████▀   ▀██████▀  ████████▀   ▄████▀       ▄████████▀  ████████▀    ███    ███   ███    █▀   ▄████▀        ██████████ 
                                                                          ███    ███                                        
""")
    
    # Read configuration from file
    config = read_config("config.txt")
    
    # Set defaults if not in config
    start_url = config.get('start_url')
    max_pages = config.get('max_pages', 1000)
    delay = config.get('delay', 0.5)
    obey_robots = config.get('obey_robots', True)
    same_domain_only = config.get('same_domain_only', True)
    user_agent = config.get('user_agent')
    timeout = config.get('timeout', 20)
    max_workers = config.get('max_workers', 5)
    
    # Check required parameters
    if not start_url:
        print("Error: 'start_url' is required in config.txt")
        return
    
    # Auto-generate output directory based on domain
    from urllib.parse import urlparse
    parsed_url = urlparse(start_url)
    domain = parsed_url.netloc.replace('www.', '')  # Remove www prefix
    output_directory = os.path.join('scraped_site', domain)
    images_directory = os.path.join('scraped_site', f"{domain}-images")
    
    # Test URL accessibility before starting
    print("Testing URL accessibility...", flush=True)
    test_session = requests.Session()
    test_session.headers.update({"User-Agent": user_agent or USER_AGENT})
    
    try:
        test_resp = fetch_url(test_session, start_url, timeout=10)
        if not test_resp:
            print(f"Error: Cannot access {start_url}", flush=True)
            print("Please check:", flush=True)
            print("  1. The URL is correct and accessible", flush=True)
            print("  2. Your internet connection is working", flush=True)
            print("  3. The website is not blocking requests", flush=True)
            return
        
        print(f"✓ URL is accessible: {start_url}", flush=True)
    except Exception as e:
        print(f"Error testing URL: {e}", flush=True)
        print("Continuing anyway...", flush=True)
    finally:
        test_session.close()
    
    print(f"Starting website mirror with configuration:", flush=True)
    print(f"  URL: {start_url}", flush=True)
    print(f"  Output: {output_directory}", flush=True)
    print(f"  Images: {images_directory}", flush=True)
    print(f"  Max pages: {max_pages}", flush=True)
    print(f"  Delay: {delay}s", flush=True)
    print(f"  Obey robots.txt: {obey_robots}", flush=True)
    print(f"  Same domain only: {same_domain_only}", flush=True)
    print(f"  User agent: {user_agent or 'default'}", flush=True)
    print(f"  Timeout: {timeout}s", flush=True)
    print(f"  Max concurrent workers: {max_workers}", flush=True)
    print(flush=True)
    
    ensure_dir(output_directory)
    ensure_dir(images_directory)
    mirror(start_url, output_directory, max_pages=max_pages, delay=delay, 
           obey_robots=obey_robots, same_domain_only=same_domain_only, 
           user_agent=user_agent, timeout=timeout, max_workers=max_workers, 
           images_dir=images_directory)


if __name__ == "__main__":
    main()
