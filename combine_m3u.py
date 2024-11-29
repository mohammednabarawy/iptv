import os
import glob
from urllib.parse import unquote

def parse_m3u(file_path):
    channels = []
    current_channel = None
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            lines = f.readlines()
            
        if not lines or not lines[0].strip().startswith('#EXTM3U'):
            return channels
            
        for line in lines:
            line = line.strip()
            if not line:
                continue
                
            if line.startswith('#EXTINF:'):
                current_channel = {'info': line}
            elif line.startswith('http://') or line.startswith('https://') or line.startswith('rtmp://'):
                if current_channel:
                    current_channel['url'] = line
                    channels.append(current_channel)
                    current_channel = None
                    
        return channels
    except Exception as e:
        print(f"Error processing file {file_path}: {str(e)}")
        return []

def main():
    # Directory containing M3U files
    m3u_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'local m3u')
    
    # Get all M3U files
    m3u_files = glob.glob(os.path.join(m3u_dir, '*.m3u'))
    
    all_channels = []
    unique_urls = set()
    
    print(f"Found {len(m3u_files)} M3U files")
    
    # Process each M3U file
    for m3u_file in m3u_files:
        print(f"Processing: {os.path.basename(m3u_file)}")
        channels = parse_m3u(m3u_file)
        
        # Add only unique channels
        for channel in channels:
            if channel['url'] not in unique_urls:
                all_channels.append(channel)
                unique_urls.add(channel['url'])
    
    print(f"\nTotal unique channels found: {len(all_channels)}")
    
    # Create output file
    output_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'combined_channels.m3u')
    
    with open(output_file, 'w', encoding='utf-8') as f:
        # Write M3U header
        f.write('#EXTM3U\n')
        
        # Write channels
        for channel in all_channels:
            f.write(f"{channel['info']}\n")
            f.write(f"{channel['url']}\n")
    
    print(f"\nCombined M3U file created: {output_file}")

if __name__ == "__main__":
    main()
