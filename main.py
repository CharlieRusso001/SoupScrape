#!/usr/bin/env python3
"""
Main Web Scraper UI
A beautiful HTML interface for configuring and running web scraping scripts.
"""

import os
import sys
import json
import webbrowser
import threading
import subprocess
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import time
import base64
import mimetypes
import signal

# Fix Windows encoding issues
sys.stdout.reconfigure(encoding='utf-8')

# Folder monitoring for live preview
import glob
import hashlib
from pathlib import Path

# Global variables for tracking scraping status
_scraping_active = False
_scraping_folder = None
_last_scan_time = 0
_known_files = set()
_console_output = []
_downloaded_images = []  # List to track all downloaded images
_total_files_downloaded = 0  # Counter for total files downloaded
_server_running = True  # Flag to control server shutdown

class WebScraperHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        """Handle GET requests."""
        if self.path == '/':
            self.serve_main_page()
        elif self.path == '/config':
            self.serve_config()
        elif self.path == '/scraping_status':
            self.serve_scraping_status()
        elif self.path == '/debug_status':
            self.serve_debug_status()
        else:
            self.send_error(404)
    
    def do_POST(self):
        """Handle POST requests."""
        if self.path == '/save_config':
            self.save_config()
        elif self.path == '/run_script':
            self.run_script()
        else:
            self.send_error(404)
    
    def serve_main_page(self):
        """Serve the main HTML page."""
        try:
            with open('scrape.html', 'r', encoding='utf-8') as f:
                html = f.read()
            
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(html.encode())
        except FileNotFoundError:
            self.send_error(404, "HTML file not found")
        except Exception as e:
            self.send_error(500, f"Error reading HTML file: {str(e)}")
    
    def serve_config(self):
        """Serve current configuration as JSON."""
        try:
            config = self.load_config_file()
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(config).encode())
        except Exception as e:
            self.send_error(500, str(e))
    
    def serve_scraping_status(self):
        """Serve current scraping status and progress by monitoring download folder."""
        try:
            status_data = get_scraping_status()
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(status_data).encode())
        except Exception as e:
            self.send_error(500, str(e))
    
    def serve_debug_status(self):
        """Serve debug information about scraping status."""
        try:
            global _scraping_active, _scraping_folder, _known_files
            debug_data = {
                'scraping_active': _scraping_active,
                'scraping_folder': _scraping_folder,
                'folder_exists': os.path.exists(_scraping_folder) if _scraping_folder else False,
                'known_files_count': len(_known_files),
                'known_files': list(_known_files)[:10]  # First 10 files
            }
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(debug_data, indent=2).encode())
        except Exception as e:
            self.send_error(500, str(e))
    
    
    def save_config(self):
        """Save configuration from POST request."""
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            config = json.loads(post_data.decode())
            
            self.write_config_file(config)
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'success': True}).encode())
        except Exception as e:
            self.send_error(500, str(e))
    
    def run_script(self):
        """Run the specified script."""
        global _scraping_active, _scraping_folder, _last_scan_time, _known_files
        try:
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            data = json.loads(post_data.decode())
            script_name = data.get('script')
            
            if script_name not in ['scrape.py', 'imagesonly.py']:
                raise ValueError(f"Invalid script: {script_name}")
            
            # Initialize scraping data
            global _scraping_active, _scraping_folder, _last_scan_time, _known_files, _console_output, _downloaded_images, _total_files_downloaded
            _scraping_active = True
            _console_output = []  # Reset console output
            _downloaded_images = []  # Reset image list
            _total_files_downloaded = 0  # Reset file counter
            # Auto-generate scraping folder based on domain from config
            config = self.load_config_file()
            start_url = config.get('start_url', '')
            if start_url:
                from urllib.parse import urlparse
                parsed_url = urlparse(start_url)
                domain = parsed_url.netloc.replace('www.', '')  # Remove www prefix
                if script_name == 'imagesonly.py':
                    _scraping_folder = os.path.join('scraped_site', f"{domain}-images")
                else:
                    # For scrape.py, monitor the images directory for statistics
                    _scraping_folder = os.path.join('scraped_site', f"{domain}-images")
            else:
                _scraping_folder = 'scraped_site'  # Fallback
            _last_scan_time = time.time()
            _known_files = set()
            
            # Run the script in a separate thread but wait for completion
            def run_script_thread():
                try:
                    # Run the script using subprocess with real-time output capture
                    # Use unbuffered Python output for immediate console updates
                    process = subprocess.Popen(
                        [sys.executable, '-u', script_name],  # -u flag for unbuffered output
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        bufsize=1,
                        universal_newlines=True,
                        encoding='utf-8'
                    )
                    
                    # Capture output in real-time
                    output_lines = []
                    while True:
                        output = process.stdout.readline()
                        if output == '' and process.poll() is not None:
                            break
                        if output:
                            line = output.strip()
                            if line:  # Only add non-empty lines
                                output_lines.append(line)
                                _console_output.append(line)
                                # Keep console output buffer limited to last 1000 lines
                                if len(_console_output) > 1000:
                                    _console_output.pop(0)
                                # Also print to main.py's console
                                print(f"[{script_name}] {line}")
                    
                    # Get any remaining output
                    remaining_output = process.stdout.read()
                    if remaining_output:
                        for line in remaining_output.strip().split('\n'):
                            if line:  # Only add non-empty lines
                                output_lines.append(line)
                                _console_output.append(line)
                                if len(_console_output) > 1000:
                                    _console_output.pop(0)
                                # Also print to main.py's console
                                print(f"[{script_name}] {line}")
                    
                    # Wait for process to complete
                    return_code = process.wait()
                    
                    result = type('Result', (), {
                        'returncode': return_code,
                        'stdout': '\n'.join(output_lines),
                        'stderr': ''
                    })()
                    
                    if result.returncode == 0:
                        response = {
                            'success': True,
                            'output': result.stdout,
                            'script': script_name
                        }
                    else:
                        response = {
                            'success': False,
                            'error': result.stderr or result.stdout,
                            'script': script_name
                        }
                except subprocess.TimeoutExpired:
                    response = {
                        'success': False,
                        'error': 'Script timed out after 5 minutes',
                        'script': script_name
                    }
                except Exception as e:
                    response = {
                        'success': False,
                        'error': str(e),
                        'script': script_name
                    }
                finally:
                    # Mark scraping as inactive
                    _scraping_active = False
                    # Print completion message to main.py console
                    if 'result' in locals() and result.returncode == 0:
                        print("-" * 60)
                        print(f"✅ {script_name} completed successfully!")
                        print(f"📁 Files saved to: {_scraping_folder}")
                    elif 'result' in locals():
                        print("-" * 60)
                        print(f"❌ {script_name} failed with exit code {result.returncode}")
                    else:
                        print("-" * 60)
                        print(f"❌ {script_name} failed with an exception")
                
                # Store result for retrieval
                self.server.script_result = response
            
            # Start script in background
            thread = threading.Thread(target=run_script_thread)
            thread.daemon = True
            thread.start()
            
            # Print to main.py console that script started
            print(f"🚀 Started {script_name} in background thread")
            print(f"📁 Output folder: {_scraping_folder}")
            print("📊 Monitor progress in web interface or here in terminal")
            print("-" * 60)
            
            # Immediately return success - don't wait for completion
            response = {
                'success': True,
                'output': 'Script started. Check the preview panel for real-time updates.',
                'script': script_name
            }
            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())
            
        except Exception as e:
            _scraping_active = False
            self.send_error(500, str(e))
    
    def load_config_file(self):
        """Load configuration from config.txt file."""
        config = {
            'start_url': 'https://www.enchantedwave.com/',
            'max_pages': 1000,
            'delay': 0.5,
            'max_workers': 5,
            'same_domain_only': True
        }
        
        try:
            if os.path.exists('config.txt'):
                with open('config.txt', 'r', encoding='utf-8') as f:
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
        except Exception:
            pass  # Use defaults if file can't be read
        
        return config
    
    def write_config_file(self, config):
        """Write configuration to config.txt file."""
        with open('config.txt', 'w', encoding='utf-8') as f:
            f.write("# Web Scraper Configuration\n")
            f.write("# Edit this file or use the web interface to configure your scraper\n\n")
            f.write(f"start_url={config.get('start_url', 'https://www.enchantedwave.com/')}\n")
            f.write(f"max_pages={config.get('max_pages', 1000)}\n")
            f.write(f"delay={config.get('delay', 0.5)}\n")
            f.write(f"max_workers={config.get('max_workers', 5)}\n")
            f.write(f"same_domain_only={str(config.get('same_domain_only', True)).lower()}\n")
    
    def log_message(self, format, *args):
        """Override to reduce log noise."""
        pass

def signal_handler(signum, frame):
    """Handle Ctrl+C gracefully."""
    global _server_running, _scraping_active
    print("\n🛑 Shutdown requested by user (Ctrl+C)")
    print("⏳ Stopping server gracefully... Please wait...")
    _server_running = False
    _scraping_active = False

def get_scraping_status():
    """Get current scraping status by monitoring the download folder."""
    global _scraping_active, _scraping_folder, _last_scan_time, _known_files, _console_output, _downloaded_images, _total_files_downloaded
    
    if not _scraping_active or not _scraping_folder:
        return {
            'active': False,
            'newItems': [],
            'consoleOutput': ''
        }
    
    # Check if folder exists
    if not os.path.exists(_scraping_folder):
        return {
            'active': _scraping_active,
            'newItems': [],
            'consoleOutput': '\n'.join(_console_output[-50:]) if _console_output else 'Waiting for output...'
        }
    
    # Scan folder for new files
    current_time = time.time()
    new_items = []
    
    # Get all files in the folder recursively
    all_files = []
    try:
        for root, dirs, files in os.walk(_scraping_folder):
            for file in files:
                file_path = os.path.join(root, file)
                all_files.append(file_path)
    except Exception as e:
        print(f"Error walking directory {_scraping_folder}: {e}")
        return {
            'active': _scraping_active,
            'newItems': []
        }
    
    # Check for new files
    for file_path in all_files:
        file_key = os.path.relpath(file_path, _scraping_folder)
        
        if file_key not in _known_files:
            _known_files.add(file_key)
            _total_files_downloaded += 1  # Increment total file counter
            
            # Get file info
            try:
                file_size = os.path.getsize(file_path)
                file_name = os.path.basename(file_path)
                _, ext = os.path.splitext(file_name)
                
                # Determine file type
                if ext.lower() in ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.svg', '.ico', '.tiff', '.tif', '.jfif', '.avif']:
                    file_type = 'image'
                    # Add to downloaded images list
                    _downloaded_images.append({
                        'name': file_name,
                        'size': file_size,
                        'path': file_key,
                        'extension': ext
                    })
                elif ext.lower() in ['.html', '.htm']:
                    file_type = 'page'
                else:
                    file_type = 'file'
                
                # Create preview item
                item = {
                    'type': file_type,
                    'name': file_name,
                    'extension': ext,
                    'size': file_size,
                    'path': file_key
                }
                
                # For images, try to encode as base64 for preview
                if file_type == 'image' and file_size < 5 * 1024 * 1024:  # Only for images < 5MB
                    try:
                        with open(file_path, 'rb') as f:
                            image_data = f.read()
                            item['data'] = base64.b64encode(image_data).decode('utf-8')
                            
                            # Better MIME type detection
                            mime_type = mimetypes.guess_type(file_path)[0]
                            if not mime_type:
                                # Fallback MIME type detection based on extension
                                ext_lower = ext.lower()
                                if ext_lower in ['.jpg', '.jpeg', '.jfif']:
                                    mime_type = 'image/jpeg'
                                elif ext_lower == '.png':
                                    mime_type = 'image/png'
                                elif ext_lower == '.gif':
                                    mime_type = 'image/gif'
                                elif ext_lower == '.svg':
                                    mime_type = 'image/svg+xml'
                                elif ext_lower == '.webp':
                                    mime_type = 'image/webp'
                                elif ext_lower == '.bmp':
                                    mime_type = 'image/bmp'
                                elif ext_lower == '.ico':
                                    mime_type = 'image/x-icon'
                                elif ext_lower in ['.tiff', '.tif']:
                                    mime_type = 'image/tiff'
                                elif ext_lower == '.avif':
                                    mime_type = 'image/avif'
                                else:
                                    mime_type = 'image/jpeg'  # Default fallback
                            
                            item['mimeType'] = mime_type
                            print(f"✅ Generated preview for {file_name} ({file_size} bytes, {mime_type})")
                    except Exception as e:
                        print(f"❌ Error encoding image {file_path}: {e}")
                        pass  # Skip base64 encoding if it fails
                elif file_type == 'image':
                    print(f"⚠️  Image {file_name} too large for preview ({file_size} bytes, limit: 5MB)")
                
                new_items.append(item)
                
            except Exception as e:
                print(f"Error processing file {file_path}: {e}")
    
    # Create enhanced console output with statistics
    enhanced_console_output = []
    
    # Add original console output
    if _console_output:
        enhanced_console_output.extend(_console_output[-50:])
    
    # Add statistics header
    if _total_files_downloaded > 0:
        enhanced_console_output.append("")
        enhanced_console_output.append("=" * 60)
        enhanced_console_output.append("📊 DOWNLOAD STATISTICS")
        enhanced_console_output.append("=" * 60)
        enhanced_console_output.append(f"📁 Total Files Downloaded: {_total_files_downloaded}")
        enhanced_console_output.append(f"🖼️  Images Downloaded: {len(_downloaded_images)}")
        enhanced_console_output.append("")
        
        # Add image list if there are images
        if _downloaded_images:
            enhanced_console_output.append("🖼️  DOWNLOADED IMAGES:")
            enhanced_console_output.append("-" * 40)
            for i, img in enumerate(_downloaded_images[-20:], 1):  # Show last 20 images
                size_kb = img['size'] / 1024
                enhanced_console_output.append(f"{i:2d}. {img['name']} ({size_kb:.1f} KB)")
            
            if len(_downloaded_images) > 20:
                enhanced_console_output.append(f"... and {len(_downloaded_images) - 20} more images")
            
            enhanced_console_output.append("")
    
    # If no console output yet, show waiting message
    if not enhanced_console_output:
        enhanced_console_output.append("Waiting for output...")
    
    return {
        'active': _scraping_active,
        'newItems': new_items,
        'consoleOutput': '\n'.join(enhanced_console_output),
        'statistics': {
            'totalFiles': _total_files_downloaded,
            'totalImages': len(_downloaded_images),
            'images': _downloaded_images[-50:]  # Last 50 images for frontend
        }
    }

def main():
    """Main function to start the web server."""
    # Set up signal handler for Ctrl+C
    signal.signal(signal.SIGINT, signal_handler)
    
    print("Starting Web Scraper Control Panel...")
    print("=" * 50)
    
    # Check if required scripts exist
    required_scripts = ['scrape.py', 'imagesonly.py']
    missing_scripts = [script for script in required_scripts if not os.path.exists(script)]
    
    if missing_scripts:
        print(f"Warning: Missing scripts: {', '.join(missing_scripts)}")
        print("   The web interface will still work, but some buttons may not function.")
        print()
    
    # Start the web server
    port = 8080
    server_address = ('localhost', port)
    httpd = HTTPServer(server_address, WebScraperHandler)
    
    print(f"Web interface starting on http://localhost:{port}")
    print("Open your browser and navigate to the URL above")
    print("Press Ctrl+C to stop the server")
    print()
    
    # Open browser automatically
    try:
        webbrowser.open(f'http://localhost:{port}')
        print("Browser opened automatically!")
    except Exception:
        print("Please manually open your browser and go to the URL above")
    
    print()
    
    try:
        while _server_running:
            httpd.handle_request()
    except KeyboardInterrupt:
        pass
    finally:
        print("\n🛑 Server stopped by user")
        httpd.shutdown()
        print("Goodbye!")

if __name__ == "__main__":
    main()
