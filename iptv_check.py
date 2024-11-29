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

    def check_stream(self, url: str, worker_id: int) -> bool:
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
            if player.play() == -1:
                return False
                
            # Wait a bit for the stream to start
            time.sleep(0.5)
            
            # Check if media is playing
            start_time = time.time()
            while time.time() - start_time < self.check_time:
                state = player.get_state()
                if state == vlc.State.Error:
                    return False
                elif state == vlc.State.Playing:
                    player.stop()
                    return True
                time.sleep(0.1)
            
            player.stop()
            return False
            
        except Exception as e:
            return False

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
        try:
            if input_path.startswith(('http://', 'https://')):
                try:
                    content = self.session.get(input_path).text
                except requests.RequestException as e:
                    self.print_colored(f"Error downloading M3U file: {e}", Fore.RED)
                    return
            else:
                try:
                    with open(input_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                except Exception as e:
                    self.print_colored(f"Error reading M3U file: {e}", Fore.RED)
                    return
                
            # Parse M3U content
            lines = [line.strip() for line in content.splitlines() if line.strip()]
            if not lines:
                self.print_colored("Empty M3U file!", Fore.RED)
                return
                
            # Some M3U files might not start with #EXTM3U, we'll be more lenient
            # Collect all streams and their info
            streams = []
            extinf = ""
            
            for line in lines:
                if line.startswith('#EXTINF'):
                    extinf = line
                elif line.startswith(('http://', 'https://')):
                    streams.append((extinf, line))
                    extinf = ""
                elif not line.startswith('#'):  # Handle URLs without #EXTINF
                    if line.startswith(('rtmp://', 'rtsp://')):
                        streams.append(("", line))
            
            if not streams:
                self.print_colored("No valid streams found in the file!", Fore.RED)
                return

            # Store current streams for statistics
            self.current_streams = streams
            
            # Use a temporary file for writing results
            temp_file = f"{input_path}.temp"
            
            # Process streams in parallel
            self.print_colored(f"Found {len(streams)} streams to check", Fore.GREEN)
            results = self.process_streams_parallel(streams)
            
            # Count valid streams
            valid_streams = sum(1 for _, _, is_valid in results if is_valid)
            
            if valid_streams == 0:
                self.print_colored(f"No valid streams found, deleting {os.path.basename(input_path)}", Fore.YELLOW)
                try:
                    os.remove(input_path)
                except Exception as e:
                    self.print_colored(f"Error deleting file: {e}", Fore.RED)
                return
            
            # Write results to temporary file
            try:
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
                self.print_colored(f"Error saving file: {e}", Fore.RED)
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

        # Get all M3U files
        m3u_files = []
        for file in os.listdir(directory_path):
            if file.lower().endswith(('.m3u', '.m3u8')):
                m3u_files.append(os.path.join(directory_path, file))

        if not m3u_files:
            self.print_colored("No M3U files found in directory!", Fore.RED)
            return

        total_files = len(m3u_files)
        processed_files = 0
        total_streams = 0
        total_online = 0
        
        self.print_colored(f"\nFound {total_files} M3U files to process", Fore.GREEN)
        
        # Process each file sequentially
        for m3u_file in sorted(m3u_files):
            processed_files += 1
            file_name = os.path.basename(m3u_file)
            
            # Clear line and show progress
            self.print_colored(f"\n[{processed_files}/{total_files}] Processing: {file_name}", Fore.CYAN)
            print("-" * 50)
            
            # Reset counters for this file
            prev_online = self.online_count
            
            # Process the current file
            self.process_m3u(m3u_file)
            
            # Update statistics
            file_online = self.online_count - prev_online
            if hasattr(self, 'current_streams'):
                total_streams += len(self.current_streams)
                total_online += file_online
                
            print("-" * 50)
            
        # Show final statistics
        self.print_colored("\nDirectory processing complete!", Fore.GREEN)
        self.print_colored(f"Total files processed: {processed_files}", Fore.GREEN)
        self.print_colored(f"Total streams checked: {total_streams}", Fore.GREEN)
        self.print_colored(f"Total working streams: {total_online}", Fore.GREEN)

    def main(self):
        """Main entry point."""
        print(f"IPTV-Check Tool {self.VERSION}")
        print("-------------------------------------")
        print("http://github.com/peterpt")
        print("-------------------------------------")
        
        if len(sys.argv) != 2:
            self.print_colored("Usage: python iptv_check.py <m3u_file_or_directory>", Fore.YELLOW)
            sys.exit(1)
            
        input_path = sys.argv[1]
        
        print("NOTE")
        print("This tool will check each stream for 3 seconds to verify")
        print("if every link in m3u file is valid, so, it may take a while")
        print("-------------------------------------")
        
        self.check_dependencies()
        if not self.check_internet():
            sys.exit(1)
            
        self.clean_temp_files()
        
        # Initialize counters
        self.online_count = 0
        self.current_streams = []
        
        # Process directory or single file
        if os.path.isdir(input_path):
            self.process_directory(input_path)
        else:
            self.process_m3u(input_path)
                
if __name__ == "__main__":
    checker = IPTVChecker()
    checker.main()
