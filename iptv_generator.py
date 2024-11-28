import os
import requests
import xml.etree.ElementTree as ET
import logging
from typing import Optional, Dict, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from tqdm import tqdm
from colorama import init, Fore, Style

# Initialize colorama
init()


def setup_logging(log_file: Optional[str] = None):
    """Configure logging with optional file output"""
    # Force UTF-8 encoding for console output
    import sys
    if sys.platform == 'win32':
        import codecs
        sys.stdout = codecs.getwriter('utf-8')(sys.stdout.buffer)
        sys.stderr = codecs.getwriter('utf-8')(sys.stderr.buffer)

    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding='utf-8'))

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=handlers
    )
    return logging.getLogger(__name__)


def color_log(logger):
    """Add color to logger output"""
    logging.addLevelName(
        logging.INFO,
        f"{Fore.GREEN}{logging.getLevelName(logging.INFO)}{Style.RESET_ALL}"
    )
    logging.addLevelName(
        logging.WARNING,
        f"{Fore.YELLOW}{logging.getLevelName(logging.WARNING)}"
        f"{Style.RESET_ALL}"
    )
    logging.addLevelName(
        logging.ERROR,
        f"{Fore.RED}{logging.getLevelName(logging.ERROR)}{Style.RESET_ALL}"
    )
    return logger


class PlaylistGenerator:
    PLAYLIST_SOURCES = [
        # Main IPTV-org playlists
        {
            'name': 'iptv-org.main',
            'url': 'https://iptv-org.github.io/iptv/index.m3u'
        },
        {
            'name': 'iptv-org.categories',
            'url': 'https://iptv-org.github.io/iptv/index.category.m3u'
        },
        {
            'name': 'iptv-org.countries',
            'url': 'https://iptv-org.github.io/iptv/index.country.m3u'
        },
        {
            'name': 'iptv-org.languages',
            'url': 'https://iptv-org.github.io/iptv/index.language.m3u'
        },
        # Free-TV playlists
        {
            'name': 'free-tv.main',
            'url': ('https://raw.githubusercontent.com/Free-TV/IPTV/'
                    'master/playlist.m3u8')
        },
        # Regional playlists
        {
            'name': 'western-europe',
            'url': 'https://iptv-org.github.io/iptv/regions/wer.m3u'
        },
        {
            'name': 'south-america',
            'url': 'https://iptv-org.github.io/iptv/regions/southam.m3u'
        },
        {
            'name': 'south-asia',
            'url': 'https://iptv-org.github.io/iptv/regions/sas.m3u'
        },
        {
            'name': 'southeast-asia',
            'url': 'https://iptv-org.github.io/iptv/regions/sea.m3u'
        },
        # Category-specific playlists
        {
            'name': 'movies',
            'url': 'https://iptv-org.github.io/iptv/categories/movies.m3u'
        },
        {
            'name': 'entertainment',
            'url': ('https://iptv-org.github.io/iptv/categories/'
                    'entertainment.m3u')
        },
        {
            'name': 'sports',
            'url': 'https://iptv-org.github.io/iptv/categories/sports.m3u'
        },
        {
            'name': 'news',
            'url': 'https://iptv-org.github.io/iptv/categories/news.m3u'
        },
        {
            'name': 'documentary',
            'url': ('https://iptv-org.github.io/iptv/categories/'
                    'documentary.m3u')
        },
        {
            'name': 'music',
            'url': 'https://iptv-org.github.io/iptv/categories/music.m3u'
        }
    ]

    def __init__(self):
        self.iptv_base_url = "https://iptv-org.github.io/iptv"
        self.logger = color_log(logging.getLogger(__name__))
        self.session = requests.Session()
        self.max_workers = 3
        self._setup_session()
        self.local_playlists = []
        self._scan_local_playlists()

    def _setup_session(self):
        """Configure request session"""
        self.session.headers.update({
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/91.0.4472.124 Safari/537.36')
        })
        self.session.timeout = 60
        self.max_retries = 3

    def _build_playlist_url(self, category: Optional[str],
                            country: Optional[str]) -> str:
        """Build the appropriate playlist URL based on filters"""
        if category:
            return f"{self.iptv_base_url}/categories/{category}.m3u"
        elif country:
            return f"{self.iptv_base_url}/countries/{country}.m3u"
        return f"{self.iptv_base_url}/index.m3u"

    def add_epg_mapping(self, content: str) -> str:
        """Add EPG IDs and enhance channel information for Jellyfin compatibility"""
        lines = content.splitlines()
        modified_lines = []
        channel_count = 0

        # Add M3U header with Jellyfin-specific metadata
        modified_lines.extend([
            '#EXTM3U',
            '#EXTINF:-1 tvg-url="guide.xml" x-tvg-url="guide.xml"',
            '# Jellyfin IPTV Channels'
        ])

        for line in lines:
            if line.startswith('#EXTINF:'):
                channel_count += 1
                attrs = self._parse_extinf(line)

                # Get channel info
                channel_name = attrs.get('name', '').strip()
                tvg_id = self._create_epg_id(channel_name)
                tvg_name = attrs.get('tvg-name', channel_name)
                tvg_logo = attrs.get('tvg-logo', '')
                group = attrs.get('group-title', 'Other')

                # Standardize group names for Jellyfin
                group = self._standardize_group_name(group)

                # Build enhanced EXTINF line with Jellyfin attributes
                new_line = '#EXTINF:-1'
                new_line += f' tvg-id="{tvg_id}"'
                new_line += f' tvg-name="{tvg_name}"'
                # Add channel number
                new_line += f' tvg-chno="{channel_count}"'

                if tvg_logo:
                    new_line += f' tvg-logo="{tvg_logo}"'
                new_line += f' group-title="{group}"'

                # Add additional Jellyfin metadata
                new_line += f' x-tvg-id="{tvg_id}"'
                new_line += ' type="video"'  # Specify content type
                new_line += f' channel-id="{channel_count}"'

                # Add channel name
                new_line += f',{channel_name}'

                modified_lines.append(new_line)
            elif line.startswith('#EXTM3U'):
                continue
            elif line.startswith('http'):
                modified_lines.append(line)

        return '\n'.join(modified_lines)

    def _parse_extinf(self, line: str) -> dict:
        """Parse EXTINF line to extract attributes"""
        attrs = {}
        # Remove #EXTINF:-1 prefix
        content = line.replace('#EXTINF:-1', '').strip()

        # Extract channel name
        if ',' in content:
            attrs_str, attrs['name'] = content.rsplit(',', 1)
        else:
            attrs_str, attrs['name'] = content, ''

        # Parse attributes
        for attr in attrs_str.split():
            if '=' in attr:
                key, value = attr.split('=', 1)
                # Remove quotes
                attrs[key] = value.strip('"\'')

        return attrs

    def _standardize_group_name(self, group: str) -> str:
        """Standardize group names for Jellyfin"""
        # Map of common group variations to standard names
        group_mapping = {
            'news': 'News',
            'sports': 'Sports',
            'sport': 'Sports',
            'movie': 'Movies',
            'movies': 'Movies',
            'film': 'Movies',
            'entertainment': 'Entertainment',
            'series': 'Series',
            'tvshows': 'Series',
            'shows': 'Series',
            'documentary': 'Documentary',
            'documentaries': 'Documentary',
            'kids': 'Kids',
            'children': 'Kids',
            'music': 'Music',
            'lifestyle': 'Lifestyle',
            'general': 'General',
            'undefined': 'Other',
            '': 'Other'
        }

        # Normalize group name
        normalized = group.lower().strip()

        # Return mapped name or title case if no mapping exists
        return group_mapping.get(normalized, group.title())

    def _create_epg_id(self, channel_name: str) -> str:
        """Create a Jellyfin-compatible EPG ID"""
        # Remove special characters except dots and dashes
        epg_id = ''.join(
            c.lower() for c in channel_name
            if c.isalnum() or c in '.-'
        )
        # Replace spaces with dots
        epg_id = epg_id.replace(' ', '.')
        # Ensure unique and valid ID format for Jellyfin
        epg_id = f"IPTV.{epg_id}"
        return epg_id

    def organize_by_groups(self, content: str) -> str:
        """Organize channels by groups for Jellyfin"""
        lines = content.splitlines()
        groups = {}
        current_url = None

        # Group channels
        for line in lines:
            if line.startswith('#EXTINF:'):
                attrs = self._parse_extinf(line)
                # Use standardized group names
                group = attrs.get('group-title', '')
                if group:
                    group = group.title().replace('&', 'and')
                else:
                    group = 'Other'

                if group not in groups:
                    groups[group] = []
                groups[group].append((line, current_url))
            elif line.startswith('#EXTM3U'):
                continue
            elif line.startswith('http'):
                current_url = line

        # Rebuild playlist
        result = ['#EXTM3U', '#EXTINF:-1 tvg-url="guide.xml"']

        # Add groups in a Jellyfin-friendly order
        preferred_groups = [
            'News', 'Sports', 'Entertainment', 'Movies', 'Series',
            'Documentary', 'Kids', 'Music', 'Lifestyle', 'Other'
        ]

        # First add preferred groups in order
        for group in preferred_groups:
            if group in groups:
                result.append(f'\n# {group}')
                for extinf, url in groups[group]:
                    if url:  # Only add valid channels
                        result.extend([extinf, url])
                groups.pop(group)

        # Then add remaining groups
        for group in sorted(groups.keys()):
            result.append(f'\n# {group}')
            for extinf, url in groups[group]:
                if url:  # Only add valid channels
                    result.extend([extinf, url])

        return '\n'.join(result)

    def _scan_local_playlists(self):
        """Scan for local M3U files"""
        self.logger.info("Scanning for local playlists...")

        # Define extensions to look for
        extensions = {'.m3u', '.m3u8'}

        # Get the script's directory and local m3u directory
        script_dir = os.path.dirname(os.path.abspath(__file__))
        local_m3u_dir = os.path.join(script_dir, 'local m3u')

        # Walk through local m3u directory
        if os.path.exists(local_m3u_dir):
            for root, _, files in os.walk(local_m3u_dir):
                for file in files:
                    if os.path.splitext(file)[1].lower() in extensions:
                        playlist_path = os.path.join(root, file)
                        self.local_playlists.append({
                            'name': f'local.{os.path.basename(file)}',
                            'path': playlist_path
                        })
                        self.logger.info(
                            f"Found local playlist: {os.path.basename(file)}")

    def fetch_playlist(self, category: Optional[str] = None,
                       country: Optional[str] = None) -> str:
        """Fetch and combine playlists from all sources"""
        combined_content = []
        successful_sources = []

        # Fetch online playlists
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._fetch_single_playlist, source): source
                for source in self.PLAYLIST_SOURCES
            }

            with tqdm(
                total=len(self.PLAYLIST_SOURCES),
                desc=f"{Fore.CYAN}Fetching online playlists{Style.RESET_ALL}"
            ) as pbar:
                for future in as_completed(futures):
                    source = futures[future]
                    try:
                        content = future.result()
                        if content:
                            successful_sources.append(source['name'])
                            combined_content.append(content)
                        pbar.update(1)
                    except Exception as e:
                        self.logger.warning(
                            f"Error fetching from {source['name']}: {str(e)}")
                        pbar.update(1)

        # Process local playlists
        if self.local_playlists:
            self.logger.info("Processing local playlists...")
            for playlist in self.local_playlists:
                content = self._fetch_local_playlist(playlist)
                if content:
                    successful_sources.append(playlist['name'])
                    combined_content.append(content)

        if successful_sources:
            self.logger.info(
                f"Successfully fetched playlists from: "
                f"{', '.join(successful_sources)}")
            return self._merge_playlists(combined_content)

        raise Exception("All playlist sources failed")

    def _merge_playlists(self, playlists: List[str]) -> str:
        """Merge multiple playlists into a single playlist"""
        combined_content = []

        # Process each playlist
        for playlist in playlists:
            lines = playlist.splitlines()
            # Skip header lines from subsequent playlists
            if combined_content:
                lines = [
                    line for line in lines
                    if not line.startswith('#EXTM3U')
                    and not line.startswith('#EXTINF:-1 tvg-url')
                ]
            combined_content.extend(lines)

        # Enhance and organize the combined content
        enhanced = self.add_epg_mapping('\n'.join(combined_content))
        return self.organize_by_groups(enhanced)

    def _fetch_local_playlist(self, playlist: Dict) -> Optional[str]:
        """Read a local playlist file"""
        try:
            self.logger.info(
                f"Reading local playlist: {playlist['name']}...")

            with open(playlist['path'], 'rb') as f:
                content = f.read()

            # Try different encodings
            for encoding in ['utf-8', 'latin1', 'cp1252']:
                try:
                    return content.decode(encoding)
                except UnicodeDecodeError:
                    continue

            # Fallback to utf-8 with error handling
            return content.decode('utf-8', errors='ignore')

        except Exception as e:
            self.logger.warning(
                f"{Fore.YELLOW}Failed to read {playlist['name']}: {str(e)}"
                f"{Style.RESET_ALL}"
            )
            return None

    def fetch_playlist(self, category: Optional[str] = None,
                       country: Optional[str] = None) -> str:
        """Fetch and combine playlists from all sources"""
        combined_content = []
        successful_sources = []

        # Fetch online playlists
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._fetch_single_playlist, source): source
                for source in self.PLAYLIST_SOURCES
            }

            with tqdm(
                total=len(self.PLAYLIST_SOURCES),
                desc=f"{Fore.CYAN}Fetching online playlists{Style.RESET_ALL}"
            ) as pbar:
                for future in as_completed(futures):
                    source = futures[future]
                    try:
                        content = future.result()
                        if content:
                            successful_sources.append(source['name'])
                            combined_content.append(content)
                        pbar.update(1)
                    except Exception as e:
                        self.logger.warning(
                            f"Error fetching from {source['name']}: {str(e)}")
                        pbar.update(1)

        # Process local playlists
        if self.local_playlists:
            self.logger.info("Processing local playlists...")
            for playlist in self.local_playlists:
                content = self._fetch_local_playlist(playlist)
                if content:
                    successful_sources.append(playlist['name'])
                    combined_content.append(content)

        if successful_sources:
            self.logger.info(
                f"Successfully fetched playlists from: "
                f"{', '.join(successful_sources)}")
            return self._merge_playlists(combined_content)

        raise Exception("All playlist sources failed")

    def _merge_playlists(self, playlists: List[str]) -> str:
        """Merge multiple playlists into a single playlist"""
        combined_content = []

        # Process each playlist
        for playlist in playlists:
            lines = playlist.splitlines()
            # Skip header lines from subsequent playlists
            if combined_content:
                lines = [
                    line for line in lines
                    if not line.startswith('#EXTM3U')
                    and not line.startswith('#EXTINF:-1 tvg-url')
                ]
            combined_content.extend(lines)

        # Enhance and organize the combined content
        enhanced = self.add_epg_mapping('\n'.join(combined_content))
        return self.organize_by_groups(enhanced)

    def _fetch_single_playlist(self, source: Dict) -> Optional[str]:
        """Fetch a single playlist source"""
        try:
            self.logger.info(
                f"Fetching playlist from {source['name']}...")

            response = self.session.get(
                source['url'],
                timeout=60,
                stream=True,
                verify=True
            )
            response.raise_for_status()

            # Read content in binary mode first
            content = b''
            with tqdm(
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
                desc=f"{Fore.CYAN}Downloading playlist{Style.RESET_ALL}"
            ) as pbar:
                for chunk in response.iter_content(chunk_size=16384):
                    if chunk:
                        content += chunk
                        pbar.update(len(chunk))

            # Try different encodings
            try:
                text_content = content.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    text_content = content.decode('latin1')
                except UnicodeDecodeError:
                    text_content = content.decode('utf-8', errors='ignore')

            return text_content

        except Exception as e:
            self.logger.warning(
                f"{Fore.YELLOW}Failed {source['name']}: {str(e)}"
                f"{Style.RESET_ALL}"
            )
            return None


class EPGFetcher:
    EPG_SOURCES = [
        # Primary EPG Sources
        {
            'name': 'iptv-org.epg',
            'guide_url': 'https://iptv-org.github.io/epg/guides/en/default.xml'
        },
        {
            'name': 'i.mjh.nz',
            'guide_url': 'https://i.mjh.nz/all/epg.xml'
        },
        {
            'name': 'xmltv.net',
            'guide_url': 'http://www.xmltv.net/xml_files/tv_guide.xml'
        },
        # Regional EPG Sources
        {
            'name': 'uk.rakuten',
            'guide_url': ('https://raw.githubusercontent.com/dp247/'
                          'Freeview-EPG/master/epg.xml')
        },
        {
            'name': 'epg.streamstv.me',
            'guide_url': 'https://epg.streamstv.me/epg/guide-usa.xml'
        },
        # Community EPG Sources
        {
            'name': 'epg.51zmt.top',
            'guide_url': 'http://epg.51zmt.top:8000/e.xml'
        },
        {
            'name': 'epg.112114.xyz',
            'guide_url': 'http://epg.112114.xyz/pp.xml'
        },
        {
            'name': 'epg.pm',
            'guide_url': 'https://epg.pm/xmltv/epg.xml'
        },
        {
            'name': 'epgshare01.online',
            'guide_url': ('https://epgshare01.online/epgshare01/'
                          'epg_ripper.xml.gz')
        },
        # Backup EPG Sources
        {
            'name': 'github.epg',
            'guide_url': ('https://raw.githubusercontent.com/AqFad2811/'
                          'epg/main/epg.xml')
        },
        {
            'name': 'epg.ottclub',
            'guide_url': 'https://epg.ottclub.ru/epg.xml.gz'
        }
    ]

    def __init__(self, max_workers: int = 3):
        self.logger = color_log(logging.getLogger(__name__))
        self.session = requests.Session()
        self.max_workers = max_workers
        self._setup_session()

    def _setup_session(self):
        """Configure request session"""
        self.session.headers.update({
            'User-Agent': ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
                           'AppleWebKit/537.36 (KHTML, like Gecko) '
                           'Chrome/91.0.4472.124 Safari/537.36'),
            'Accept': ('application/xml,text/xml,application/json,'
                       'text/plain,*/*;q=0.9'),
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate'
        })
        # Increase timeout and retries
        self.session.timeout = 120
        self.max_retries = 5

    def fetch_epg(self) -> Optional[str]:
        """Fetch and combine EPG data from multiple sources"""
        combined_epg = None
        successful_sources = []

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._fetch_single_source, source): source
                for source in self.EPG_SOURCES
            }

            with tqdm(
                total=len(self.EPG_SOURCES),
                desc=f"{Fore.CYAN}Trying EPG sources{Style.RESET_ALL}"
            ) as pbar:
                for future in as_completed(futures):
                    source = futures[future]
                    try:
                        content = future.result()
                        if content:
                            successful_sources.append(source['name'])
                            if combined_epg is None:
                                combined_epg = content
                            else:
                                combined_epg = self._merge_epg_data(
                                    combined_epg, content)
                        pbar.update(1)
                    except Exception as e:
                        self.logger.warning(
                            f"Error fetching from {source['name']}: {str(e)}")
                        pbar.update(1)

        if successful_sources:
            sources_str = ', '.join(successful_sources)
            self.logger.info(
                f"Successfully fetched EPG data from: {sources_str}")
            return combined_epg

        self.logger.error(
            f"{Fore.RED}All EPG sources failed{Style.RESET_ALL}")
        return None

    def _merge_epg_data(self, epg1: str, epg2: str) -> str:
        """Merge two EPG XML files with Jellyfin compatibility"""
        try:
            root1 = ET.fromstring(epg1)
            root2 = ET.fromstring(epg2)

            # Add Jellyfin-specific attributes to root
            root1.set('generator-info-name', 'IPTV EPG Generator')
            root1.set('generator-info-url', 'https://github.com/iptv-org/epg')

            # Combine channels with enhanced metadata
            channel_ids = set()
            for channel in root1.findall('./channel'):
                channel_ids.add(channel.attrib['id'])
                # Add display names in multiple formats
                self._enhance_channel_metadata(channel)

            # Add new channels
            for channel in root2.findall('./channel'):
                if channel.attrib['id'] not in channel_ids:
                    self._enhance_channel_metadata(channel)
                    root1.append(channel)
                    channel_ids.add(channel.attrib['id'])

            # Add new programmes with enhanced metadata
            existing_programs = set()
            for program in root1.findall('./programme'):
                key = (
                    program.attrib['channel'],
                    program.attrib.get('start', ''),
                    program.attrib.get('stop', '')
                )
                existing_programs.add(key)
                # Enhance program metadata
                self._enhance_program_metadata(program)

            for program in root2.findall('./programme'):
                key = (
                    program.attrib['channel'],
                    program.attrib.get('start', ''),
                    program.attrib.get('stop', '')
                )
                if key not in existing_programs:
                    self._enhance_program_metadata(program)
                    root1.append(program)

            return ET.tostring(root1, encoding='unicode',
                               xml_declaration=True)

        except ET.ParseError as e:
            self.logger.error(f"Error merging EPG data: {str(e)}")
            return epg1

    def _enhance_channel_metadata(self, channel: ET.Element):
        """Add Jellyfin-specific channel metadata"""
        # Ensure channel has an icon
        if not channel.find('icon'):
            icon = ET.SubElement(channel, 'icon')
            icon.set('src', '')

        # Add multiple display names for better matching
        display_name = channel.find('display-name')
        if display_name is not None:
            name = display_name.text
            # Add variations of the name
            self._add_display_name(channel, name)
            self._add_display_name(channel, name.lower())
            self._add_display_name(channel, name.replace(' ', ''))

        # Add language if missing
        if not channel.find('language'):
            lang = ET.SubElement(channel, 'language')
            lang.text = 'en'

    def _enhance_program_metadata(self, program: ET.Element):
        """Add Jellyfin-specific program metadata"""
        # Add required elements if missing
        required_elements = ['title', 'desc', 'category']
        for elem in required_elements:
            if not program.find(elem):
                el = ET.SubElement(program, elem)
                el.text = ''

        # Add program rating if missing
        if not program.find('rating'):
            rating = ET.SubElement(program, 'rating')
            rating.set('system', 'MPAA')
            value = ET.SubElement(rating, 'value')
            value.text = 'NR'

    def _add_display_name(self, channel: ET.Element, name: str):
        """Add a display name to channel"""
        display_name = ET.SubElement(channel, 'display-name')
        display_name.text = name

    def validate_epg_xml(self, xml_content: str) -> bool:
        """Validates that the EPG XML content is well-formed"""
        try:
            root = ET.fromstring(xml_content)

            # Get all channel IDs from EPG
            epg_channels = {
                channel.attrib['id']: channel.find('display-name').text
                for channel in root.findall('./channel')
            }

            # Log channel mapping info
            self.logger.info(f"Found {len(epg_channels)} channels in EPG")
            if epg_channels:
                self.logger.info("Sample channel mappings:")
                for channel_id, name in list(epg_channels.items())[:5]:
                    self.logger.info(f"  {channel_id} -> {name}")

            # Check for programs
            programs = root.findall('./programme')
            if programs:
                self.logger.info(f"Found {len(programs)} programs in EPG")
                return True
            else:
                self.logger.error("No programs found in EPG")
                return False

        except ET.ParseError as e:
            self.logger.error(
                f"Invalid EPG XML: Parse error - {str(e)}\n"
                f"Content preview: {xml_content[:200]}...")
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error validating XML: {str(e)}")
            return False

    def _fetch_single_source(self, source: Dict) -> Optional[str]:
        """Fetch EPG from a single source"""
        try:
            self.logger.info(
                f"Attempting {Fore.CYAN}{source['name']}{Style.RESET_ALL}...")

            response = self.session.get(
                source['guide_url'],
                timeout=90,
                stream=True,
                verify=True
            )
            response.raise_for_status()

            # Read content in binary mode first
            content = b''
            with tqdm(
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
                desc=f"{Fore.CYAN}Downloading EPG{Style.RESET_ALL}"
            ) as pbar:
                for chunk in response.iter_content(chunk_size=16384):
                    if chunk:
                        content += chunk
                        pbar.update(len(chunk))

            # Try different encodings
            try:
                text_content = content.decode('utf-8')
            except UnicodeDecodeError:
                try:
                    text_content = content.decode('latin1')
                except UnicodeDecodeError:
                    text_content = content.decode('utf-8', errors='ignore')

            if self.validate_epg_xml(text_content):
                self.logger.info(
                    f"{Fore.GREEN}Successfully fetched EPG from "
                    f"{source['name']}{Style.RESET_ALL}"
                )
                return text_content

            return None

        except Exception as e:
            self.logger.warning(
                f"{Fore.YELLOW}Failed {source['name']}: {str(e)}"
                f"{Style.RESET_ALL}"
            )
            return None


def main():
    logger = color_log(setup_logging('iptv_generator.log'))

    try:
        print(f"\n{Fore.CYAN}=== IPTV Playlist Generator ==={Style.RESET_ALL}")

        # Generate playlist with progress
        logger.info("Starting playlist generation...")
        generator = PlaylistGenerator()
        playlist_content = generator.fetch_playlist()

        # Generate EPG with progress
        logger.info("Starting EPG guide generation...")
        epg_fetcher = EPGFetcher(max_workers=3)
        epg_content = epg_fetcher.fetch_epg()

        if epg_content and epg_fetcher.validate_epg_xml(epg_content):
            # Save files with progress
            playlist_path = 'iptv.m3u'
            epg_path = 'guide.xml'

            for path, content in [
                (playlist_path, playlist_content),
                (epg_path, epg_content)
            ]:
                with tqdm(
                    total=len(content),
                    desc=f"{Fore.CYAN}Saving {path}{Style.RESET_ALL}",
                    unit='B',
                    unit_scale=True
                ) as pbar:
                    with open(path, 'w', encoding='utf-8') as f:
                        f.write(content)
                        pbar.update(len(content))

            print(f"\n{Fore.GREEN}Successfully generated files:")
            print(f"Playlist: {Fore.CYAN}{os.path.abspath(playlist_path)}")
            print(f"EPG Guide: {Fore.CYAN}{os.path.abspath(epg_path)}")
            print(f"{Style.RESET_ALL}")
        else:
            print(f"\n{Fore.RED}Failed to generate valid EPG guide"
                  f"{Style.RESET_ALL}")

    except Exception as e:
        logger.error(f"Error: {str(e)}")
        raise


if __name__ == "__main__":
    main()
