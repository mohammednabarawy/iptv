#!/usr/bin/env python3
import os
import sys
import subprocess
import requests
import re
import vlc
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
    VERSION = "2.2 Beta"
    
    def __init__(self):
        self.install_dir = os.path.dirname(os.path.abspath(__file__))  # Get script directory
        self.temp_dir = os.path.join(self.install_dir, "temp")
        self.check_time = 3  # Time in seconds to check each stream
        self.online_count = 0
        self.max_workers = min(32, cpu_count() * 2)  # Limit max workers
        self.timeout = 10  # Timeout in seconds for stream checks
        self.session = requests.Session()  # Use session for connection pooling
        
        # Create necessary directories
        os.makedirs(self.temp_dir, exist_ok=True)
        
        # Configure VLC to be quiet
        os.environ['VLC_VERBOSE'] = '-1'  # Disable VLC output
        
    def print_colored(self, text: str, color: str):
        """Print colored text using colorama."""
        print(f"{color}{text}{Style.RESET_ALL}", flush=True)
        
    def check_dependencies(self):
        """Check if VLC is installed."""
        try:
            instance = vlc.Instance()
        except:
            self.print_colored("Error: VLC is not installed!", Fore.RED)
            self.print_colored("Please install VLC media player from:", Fore.YELLOW)
            self.print_colored("https://www.videolan.org/vlc/", Fore.CYAN)
            self.print_colored("After installing VLC, install python-vlc using:", Fore.YELLOW)
            self.print_colored("pip install python-vlc", Fore.CYAN)
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

    def check_stream(self, url: str) -> bool:
        """Check if a stream is valid using VLC."""
        try:
            # First do a quick HEAD request to check if the stream is accessible
            try:
                response = self.session.head(url, timeout=5)
                if response.status_code != 200:
                    return False
            except requests.RequestException:
                return False

            # Create a new VLC instance with minimal logging
            instance = vlc.Instance('--quiet')
            player = instance.media_player_new()
            media = instance.media_new(url)
            player.set_media(media)
            
            # Try to play the stream
            result = player.play()
            if result == -1:
                player.release()
                return False
                
            # Wait a bit for the stream to start
            time.sleep(1)
            
            # Check if media is playing
            start_time = time.time()
            while time.time() - start_time < self.check_time:
                state = player.get_state()
                if state == vlc.State.Error:
                    player.release()
                    return False
                elif state == vlc.State.Playing:
                    player.stop()
                    player.release()
                    return True
                time.sleep(0.1)
            
            player.stop()
            player.release()
            return False
            
        except Exception as e:
            print(f"Error checking stream {url}: {str(e)}")
            return False

    def process_streams_parallel(self, streams: List[Tuple[str, str]]):
        """Process multiple streams in parallel."""
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_url = {
                    executor.submit(self.check_stream, url): (url, tvg_id)
                    for i, (url, tvg_id) in enumerate(streams)
                }
                for future in concurrent.futures.as_completed(future_to_url):
                    url, tvg_id = future_to_url[future]
                    try:
                        is_valid = future.result()
                        if is_valid:
                            self.online_count += 1
                    except Exception as e:
                        self.print_colored(f"Error checking {url}: {str(e)}", Fore.RED)
        except Exception as e:
            self.print_colored(f"Error in parallel processing: {str(e)}", Fore.RED)

    def process_m3u(self, input_path: str):
        """Process M3U file and check all streams."""
        if not os.path.exists(input_path):
            self.print_colored(f"File not found: {input_path}", Fore.RED)
            return

        temp_file = os.path.join(self.temp_dir, f"temp_{os.path.basename(input_path)}")
        streams = []
        results = []
        valid_streams = 0
        current_extinf = None

        try:
            with open(input_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue

                    if line.startswith('#EXTINF:'):
                        current_extinf = line
                    elif line.startswith('http'):
                        url = line
                        is_valid = self.check_stream(url)
                        if is_valid:
                            valid_streams += 1
                        results.append((current_extinf, url, is_valid))
                        current_extinf = None

            if valid_streams == 0:
                self.print_colored(f"No valid streams found in {os.path.basename(input_path)}", Fore.YELLOW)
                return

            # Write results to temporary file
            with open(temp_file, 'w', encoding='utf-8') as out:
                out.write('#EXTM3U\n')
                for extinf, url, is_valid in results:
                    if is_valid:
                        if extinf:
                            out.write(f"{extinf}\n")
                        out.write(f"{url}\n")

            # Replace original file with the new one
            os.replace(temp_file, input_path)
            self.print_colored(
                f"Updated {os.path.basename(input_path)} with {valid_streams} working streams",
                Fore.CYAN
            )

        except Exception as e:
            self.print_colored(f"Error processing file: {str(e)}", Fore.RED)
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass

    def process_directory(self, directory_path: str):
        """Process all M3U files in a directory one by one."""
        if not os.path.exists(directory_path):
            self.print_colored(f"Directory not found: {directory_path}", Fore.RED)
            return

        m3u_files = []
        for file in os.listdir(directory_path):
            if file.lower().endswith(('.m3u', '.m3u8')):
                m3u_files.append(os.path.join(directory_path, file))

        if not m3u_files:
            self.print_colored("No M3U files found in directory!", Fore.RED)
            return

        total_files = len(m3u_files)
        for i, m3u_file in enumerate(m3u_files, 1):
            self.print_colored(f"\nProcessing file {i}/{total_files}: {os.path.basename(m3u_file)}", Fore.CYAN)
            self.process_m3u(m3u_file)

    def main(self):
        """Main entry point."""
        self.print_colored(f"IPTV Stream Checker v{self.VERSION}", Fore.CYAN)
        self.print_colored("=" * 50, Fore.CYAN)

        # Check dependencies
        self.check_dependencies()

        # Check internet connection
        if not self.check_internet():
            return

        # Clean temp files
        self.clean_temp_files()

        if len(sys.argv) < 2:
            self.print_colored("Usage:", Fore.YELLOW)
            self.print_colored("  Single file:    iptv_check.py <m3u_file>", Fore.CYAN)
            self.print_colored("  Directory:      iptv_check.py -d <directory>", Fore.CYAN)
            return

        if sys.argv[1] == "-d":
            if len(sys.argv) < 3:
                self.print_colored("Error: Directory path required!", Fore.RED)
                return
            self.process_directory(sys.argv[2])
        else:
            self.process_m3u(sys.argv[1])

if __name__ == "__main__":
    checker = IPTVChecker()
    checker.main()
