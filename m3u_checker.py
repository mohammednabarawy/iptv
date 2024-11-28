import os
import sys
import requests
from urllib.parse import urlparse
import concurrent.futures
import time
from tqdm import tqdm

def is_url_valid(url, timeout=5):
    """Check if a URL is accessible."""
    try:
        # Only get the headers to save bandwidth
        response = requests.head(url, timeout=timeout, allow_redirects=True)
        return response.status_code < 400
    except:
        return False

def check_urls_parallel(urls, max_workers=10):
    """Check multiple URLs in parallel."""
    results = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_url = {executor.submit(is_url_valid, url): url for url in urls}
        
        # Use tqdm for a progress bar
        with tqdm(total=len(urls), desc="Checking links") as pbar:
            for future in concurrent.futures.as_completed(future_to_url):
                url = future_to_url[future]
                try:
                    results[url] = future.result()
                except Exception as e:
                    results[url] = False
                pbar.update(1)
    
    return results

def process_m3u_file(input_file):
    """Process M3U file and return valid entries."""
    if not os.path.exists(input_file):
        print(f"Error: File {input_file} not found!")
        return [], 0, 0

    valid_entries = []
    urls_to_check = []
    url_to_metadata = {}
    total_links = 0

    print(f"Reading file: {input_file}")
    
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except UnicodeDecodeError:
        # Try with a different encoding if UTF-8 fails
        with open(input_file, 'r', encoding='latin-1') as f:
            lines = f.readlines()

    if not lines or not lines[0].strip() == '#EXTM3U':
        print("Error: Not a valid M3U file!")
        return [], 0, 0

    valid_entries.append('#EXTM3U\n')
    
    # First pass: collect all URLs and their metadata
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        
        if not line:
            i += 1
            continue
            
        if line.startswith('#EXTINF:'):
            if i + 1 < len(lines):
                url = lines[i + 1].strip()
                if url and not url.startswith('#'):
                    urls_to_check.append(url)
                    url_to_metadata[url] = line
                    total_links += 1
                i += 2
            else:
                i += 1
        else:
            if line.startswith('#'):
                valid_entries.append(line + '\n')
            i += 1

    # Check all URLs in parallel
    print(f"\nFound {total_links} links to check...")
    results = check_urls_parallel(urls_to_check)
    
    # Second pass: build the output file with working links
    valid_links = 0
    for url, is_valid in results.items():
        if is_valid:
            valid_entries.append(url_to_metadata[url] + '\n')
            valid_entries.append(url + '\n')
            valid_links += 1

    return valid_entries, total_links, valid_links

def save_valid_entries(valid_entries, input_file):
    """Save valid entries to a new file."""
    output_file = input_file.rsplit('.', 1)[0] + '_cleaned.' + input_file.rsplit('.', 1)[1]
    with open(output_file, 'w', encoding='utf-8') as f:
        f.writelines(valid_entries)
    return output_file

def main():
    if len(sys.argv) != 2:
        print("Usage: python m3u_checker.py <input_m3u_file>")
        sys.exit(1)

    input_file = sys.argv[1]
    print(f"Starting M3U file check for: {input_file}")
    
    start_time = time.time()
    valid_entries, total_links, valid_links = process_m3u_file(input_file)
    
    if valid_entries:
        output_file = save_valid_entries(valid_entries, input_file)
        print(f"\nResults:")
        print(f"Total links checked: {total_links}")
        print(f"Valid links found: {valid_links}")
        print(f"Dead links removed: {total_links - valid_links}")
        print(f"Cleaned file saved as: {output_file}")
        print(f"\nTime taken: {time.time() - start_time:.2f} seconds")
    else:
        print("\nNo valid entries found or file processing failed.")
        sys.exit(1)

if __name__ == "__main__":
    main()
