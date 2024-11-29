#!/usr/bin/env python3
import os
import sys
import subprocess
import requests
import re
import pytesseract
import ffmpeg
import shutil
from pathlib import Path
from typing import Optional, List, Tuple
import tempfile
import signal
import time
from colorama import init, Fore, Style
from multiprocessing import Pool, cpu_count
from functools import partial
import concurrent.futures

# Initialize colorama for cross-platform colored output
init()

class IPTVChecker:
    VERSION = "2.1 Beta"
    
    def __init__(self):
        self.install_dir = os.path.join(os.path.expanduser("~"), ".iptv-check")
        self.temp_dir = os.path.join(self.install_dir, "temp")
        self.updated_file = os.path.join(self.install_dir, "updated.m3u")
        self.download_time = 1  # Reduced from 2 to 1 second
        self.online_count = 0
        self.max_workers = min(32, cpu_count() * 2)  # Limit max workers
        self.timeout = 10  # Timeout in seconds for stream checks
        self.session = requests.Session()  # Use session for connection pooling
        
        # Create necessary directories
        os.makedirs(self.temp_dir, exist_ok=True)
        
    def print_colored(self, text: str, color: str):
        """Print colored text using colorama."""
        print(f"{color}{text}{Style.RESET_ALL}", flush=True)
        
    def check_dependencies(self):
        """Check if required external programs are installed."""
        dependencies = {
            "ffmpeg": "ffmpeg",
            "tesseract": "tesseract-ocr and its dependencies"
        }
        
        for cmd, name in dependencies.items():
            if cmd == "ffmpeg":
                common_paths = [
                    os.path.join(os.environ.get('ProgramFiles', ''), 'ffmpeg', 'bin', 'ffmpeg.exe'),
                    os.path.join(os.environ.get('ProgramFiles(x86)', ''), 'ffmpeg', 'bin', 'ffmpeg.exe'),
                    os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Microsoft', 'WindowsApps', 'ffmpeg.exe'),
                    'ffmpeg.exe'
                ]
                found = any(os.path.exists(path) for path in common_paths)
                if found:
                    continue

            if not shutil.which(cmd):
                self.print_colored(f"Error: {name} is not installed!", Fore.RED)
                if cmd == "ffmpeg":
                    self.print_colored("To install ffmpeg on Windows:", Fore.YELLOW)
                    self.print_colored("1. Download from https://github.com/BtbN/FFmpeg-Builds/releases", Fore.YELLOW)
                    self.print_colored("2. Extract the zip file", Fore.YELLOW)
                    self.print_colored("3. Add the bin folder to your system PATH", Fore.YELLOW)
                    self.print_colored("Or install using:", Fore.YELLOW)
                    self.print_colored("winget install ffmpeg", Fore.CYAN)
                else:
                    self.print_colored(f"Please install {name} to use this tool.", Fore.YELLOW)
                sys.exit(1)
                
    def check_internet(self):
        """Check if there's an active internet connection."""
        try:
            self.session.get("http://google.com", timeout=5)
            return True
        except requests.RequestException:
            self.print_colored("Not connected to Internet", Fore.RED)
            self.print_colored("(This tool requires Internet Connection)", Fore.GREEN)
            return False
            
    def clean_temp_files(self):
        """Clean temporary files from previous runs."""
        for file in os.listdir(self.temp_dir):
            file_path = os.path.join(self.temp_dir, file)
            try:
                if os.path.isfile(file_path):
                    os.unlink(file_path)
            except Exception as e:
                print(f"Error: {e}")

    def check_stream(self, url: str, worker_id: int) -> bool:
        """Check if a stream is valid by downloading a sample."""
        temp_output = os.path.join(self.temp_dir, f"stream_{worker_id}.mp4")
        try:
            # First do a quick HEAD request to check if the stream is accessible
            try:
                response = self.session.head(url, timeout=5)
                if response.status_code != 200:
                    return False
            except requests.RequestException:
                return False

            # Use ffmpeg to download a sample of the stream
            cmd = [
                "ffmpeg", "-t", str(self.download_time),
                "-i", url,
                "-vsync", "0",
                "-acodec", "copy",
                "-vcodec", "copy",
                "-tls_verify", "0",
                temp_output
            ]
            
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            
            try:
                process.communicate(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                return False
            
            if not os.path.exists(temp_output):
                return False
                
            # Check if file size is too small (likely an error)
            if os.path.getsize(temp_output) < 500:
                return False
                
            return True
            
        except Exception as e:
            return False
        finally:
            if os.path.exists(temp_output):
                try:
                    os.remove(temp_output)
                except:
                    pass

    def process_streams_parallel(self, streams: List[Tuple[str, str]]) -> List[Tuple[str, str, bool]]:
        """Process multiple streams in parallel."""
        results = []
        total = len(streams)
        completed = 0

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            future_to_stream = {
                executor.submit(self.check_stream, stream[1], i): stream 
                for i, stream in enumerate(streams)
            }
            
            for future in concurrent.futures.as_completed(future_to_stream):
                stream = future_to_stream[future]
                completed += 1
                try:
                    is_valid = future.result()
                    if is_valid:
                        self.online_count += 1
                    results.append((stream[0], stream[1], is_valid))
                    self.print_colored(
                        f"Progress: {completed}/{total} streams checked ({self.online_count} online)",
                        Fore.CYAN
                    )
                except Exception as e:
                    results.append((stream[0], stream[1], False))

        return results
                
    def process_m3u(self, input_path: str):
        """Process M3U file and check all streams."""
        if input_path.startswith(('http://', 'https://')):
            try:
                content = self.session.get(input_path).text
            except requests.RequestException as e:
                self.print_colored(f"Error downloading M3U file: {e}", Fore.RED)
                return
        else:
            try:
                with open(input_path, 'r', encoding='utf-8') as f:
                    content = f.read()
            except Exception as e:
                self.print_colored(f"Error reading M3U file: {e}", Fore.RED)
                return
                
        # Parse M3U content
        lines = content.splitlines()
        if not lines or not lines[0].startswith('#EXTM3U'):
            self.print_colored("Invalid M3U file format!", Fore.RED)
            return
            
        # Collect all streams and their info
        streams = []
        extinf = ""
        
        for line in lines:
            line = line.strip()
            if line.startswith('#EXTINF'):
                extinf = line
            elif line.startswith('http'):
                streams.append((extinf, line))
                extinf = ""
                
        # Process streams in parallel
        self.print_colored(f"Found {len(streams)} streams to check", Fore.GREEN)
        results = self.process_streams_parallel(streams)
        
        # Write results to file
        with open(self.updated_file, 'w', encoding='utf-8') as out:
            out.write('#EXTM3U\n')
            for extinf, url, is_valid in results:
                if is_valid:
                    if extinf:
                        out.write(f"{extinf}\n")
                    out.write(f"{url}\n")
                    
        self.print_colored(
            f"\nResults saved to: {self.updated_file}",
            Fore.GREEN
        )
        self.print_colored(
            f"Total streams: {len(streams)}, Online: {self.online_count}",
            Fore.GREEN
        )
                
    def main(self):
        """Main entry point."""
        print(f"IPTV-Check Tool {self.VERSION}")
        print("-------------------------------------")
        print("http://github.com/peterpt")
        print("-------------------------------------")
        
        if len(sys.argv) != 2:
            self.print_colored("Usage: python iptv_check.py <m3u_file>", Fore.YELLOW)
            sys.exit(1)
            
        input_path = sys.argv[1]
        
        print("NOTE")
        print("This tool will download 1 second of each stream to check")
        print("if every link in m3u file is valid, so, it may take a while")
        print("-------------------------------------")
        
        self.check_dependencies()
        if not self.check_internet():
            sys.exit(1)
            
        self.clean_temp_files()
        self.process_m3u(input_path)

if __name__ == "__main__":
    checker = IPTVChecker()
    checker.main()
