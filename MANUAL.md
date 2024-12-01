# IPTV Manager - User Manual

## Table of Contents
1. [Getting Started](#getting-started)
2. [Main Interface](#main-interface)
3. [Channel Management](#channel-management)
4. [EPG (Electronic Program Guide)](#epg-electronic-program-guide)
5. [Filtering and Searching](#filtering-and-searching)
6. [Channel Validation](#channel-validation)
7. [Generating Playlists](#generating-playlists)
8. [Troubleshooting](#troubleshooting)

## Getting Started

### Installation
1. Ensure you have Python 3.x and VLC Media Player installed on your system
2. Install the required dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Launch the application:
   ```bash
   python iptv_gui.py
   ```

## Main Interface

The application window is divided into several key areas:

### Top Section
- **Load Channels**: Button to load channels from M3U sources
- **Check Selected**: Validates selected channels' availability
- **Generate**: Creates output files for selected channels

### Middle Section
- **Channel Table**: Displays all loaded channels with their properties
- **Progress Bar**: Shows progress during operations
- **Log Window**: Displays operation logs and status messages

### Filter Panel
- **Search Box**: Filter channels by name
- **Category Dropdown**: Filter by channel category
- **Country Filter**: Filter channels by country
- **Official Only**: Toggle to show only official channels

## Channel Management

### Loading Channels
1. Click the "Load Channels" button
2. Choose from available options:
   - Load from local M3U file
   - Load from URL
   - Load from multiple sources

### Channel Selection
- Use checkboxes to select individual channels
- "Select All" button to select all visible channels
- "Deselect All" button to clear selection

### Channel Information
The channel table shows:
- Channel Name
- Group/Category
- TVG ID (EPG identifier)
- Logo URL
- Working Status (after checking)
- EPG Status

## EPG (Electronic Program Guide)

### Loading EPG Data
- EPG data is automatically loaded when available
- Supports XMLTV format
- Links channels with program guide information

### EPG Integration
- Channels with available EPG data are marked
- Program information is included in generated playlists

## Filtering and Searching

### Search Options
- **Text Search**: Enter text in the search box to filter channel names
- **Category Filter**: Select a specific category from the dropdown
- **Country Filter**: Enter country name to filter channels
- **Official Filter**: Toggle to show only official channels

### Filter Combinations
- All filters can be used simultaneously
- Results update in real-time as filters are modified

## Channel Validation

### Checking Channel Status
1. Select channels to check
2. Click "Check Selected" button
3. Wait for the validation process to complete
4. Results will be displayed in the channel table:
   - ✓ Working channels
   - ✗ Non-working channels
   - ? Unchecked channels

### Validation Features
- Concurrent checking for faster results
- Progress tracking in real-time
- Ability to stop the checking process

## Generating Playlists

### Creating Output Files
1. Select desired channels
2. Click "Generate" button
3. Choose output location
4. Select output options:
   - M3U playlist
   - EPG data (if available)

### Output Options
- Filtered playlist based on selection
- EPG data for selected channels
- Custom naming options

## Troubleshooting

### Common Issues

1. **Channel Loading Fails**
   - Check internet connection
   - Verify M3U source URL
   - Ensure proper file format

2. **EPG Data Not Loading**
   - Verify XML format
   - Check file size and compression
   - Ensure TVG IDs match

3. **Channel Validation Issues**
   - Check network connectivity
   - Verify VLC installation
   - Allow sufficient time for checking

### Logs
- Check the log window for detailed information
- Log files are saved in the `/logs` directory
- Include logs when reporting issues

### Error Messages
Common error messages and solutions:
- "Failed to load M3U": Check file format and accessibility
- "EPG parsing error": Verify XML format
- "Channel check timeout": Network or server issue

## Tips and Best Practices

1. **Performance**
   - Select smaller channel groups for faster checking
   - Use filters to manage large channel lists
   - Regular cache clearing for optimal performance

2. **Organization**
   - Use meaningful categories
   - Maintain consistent naming
   - Regular playlist cleanup

3. **Updates**
   - Check for application updates
   - Update channel sources regularly
   - Verify EPG data periodically

## Keyboard Shortcuts

- `Ctrl+F`: Focus search box
- `Ctrl+A`: Select all channels
- `Ctrl+D`: Deselect all channels
- `Ctrl+G`: Generate playlist
- `Ctrl+R`: Reload channels

## Support

For additional support:
1. Check the README.md file
2. Review the logs in `/logs` directory
3. Report issues with detailed information
4. Include error messages and logs when seeking help
