# IPTV Manager

A comprehensive IPTV management tool with GUI interface for downloading, managing, and playing IPTV streams. This application helps you manage M3U playlists and Electronic Program Guide (EPG) data with an easy-to-use graphical interface.

## Features

- GUI interface for easy IPTV management
- M3U playlist downloading and processing
- EPG (Electronic Program Guide) fetching and optimization
- Playlist combination functionality
- Stream validity checking
- VLC-based stream playback
- Logging system for troubleshooting
- Local M3U file management

## Prerequisites

- Python 3.x
- VLC Media Player installed on your system

## Installation

1. Clone this repository:
```bash
git clone [your-repository-url]
cd iptv
```

2. Install the required dependencies:
```bash
pip install -r requirements.txt
```

## Dependencies

- requests >= 2.31.0 - For HTTP requests
- tqdm >= 4.65.0 - For progress bars
- colorama >= 0.4.6 - For colored terminal output
- m3u8 - For M3U playlist processing
- python-vlc >= 3.0.21203 - For media playback

## Usage

### GUI Interface

Launch the GUI application:
```bash
python iptv_gui.py
```

### Command Line Tools

The repository includes several command-line tools for different purposes:

- `iptv_generator.py` - Generate and manage IPTV playlists
- `epg_fetcher_optimized.py` - Fetch and optimize EPG data
- `m3u_downloader.py` - Download M3U playlists
- `iptv_check.py` - Check stream validity
- `combine_m3u.py` - Combine multiple M3U playlists

## Project Structure

- `iptv_gui.py` - Main GUI application
- `data_manager.py` - Core data management functionality
- `epg_fetcher_optimized.py` - EPG handling
- `m3u_downloader.py` - M3U playlist downloading
- `iptv_check.py` - Stream validation
- `combine_m3u.py` - M3U combination utility
- `logger_config.py` - Logging configuration
- `/data` - Data storage directory
- `/cache` - Cache directory
- `/local_m3u` - Local M3U files directory
- `/logs` - Log files directory

## Logging

The application maintains detailed logs in the `/logs` directory. The logging system is configured in `logger_config.py`.

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

## License

[Your chosen license]

## Disclaimer

This tool is for educational purposes only. Please ensure you have the right to access and use any IPTV streams you connect to with this application.
