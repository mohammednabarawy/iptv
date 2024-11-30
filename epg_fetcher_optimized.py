import requests
import logging
import gzip
import os
import json
import hashlib
from datetime import datetime, timedelta
from io import BytesIO
from bs4 import BeautifulSoup
import fnmatch
import xml.etree.ElementTree as ET
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Any
import aiohttp
import asyncio
import threading
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

class CacheManager:
    def __init__(self, cache_dir=".cache"):
        self.cache_dir = cache_dir
        self.cache_duration = timedelta(hours=12)  # Cache EPG data for 12 hours
        os.makedirs(cache_dir, exist_ok=True)
    
    def _get_cache_path(self, url: str) -> str:
        """Get cache file path for a URL"""
        url_hash = hashlib.md5(url.encode()).hexdigest()
        return os.path.join(self.cache_dir, f"{url_hash}.cache")
    
    def get_cached_data(self, url: str) -> Optional[str]:
        """Get cached data if it exists and is not expired"""
        cache_path = self._get_cache_path(url)
        try:
            if os.path.exists(cache_path):
                with open(cache_path, 'r') as f:
                    cache_data = json.load(f)
                    cached_time = datetime.fromisoformat(cache_data['timestamp'])
                    if datetime.now() - cached_time < self.cache_duration:
                        return cache_data['content']
        except Exception as e:
            logger.warning(f"Error reading cache for {url}: {e}")
        return None
    
    def cache_data(self, url: str, content: str):
        """Cache data for a URL"""
        cache_path = self._get_cache_path(url)
        try:
            cache_data = {
                'timestamp': datetime.now().isoformat(),
                'content': content
            }
            with open(cache_path, 'w') as f:
                json.dump(cache_data, f)
        except Exception as e:
            logger.warning(f"Error caching data for {url}: {e}")

class EPGFetcher:
    EPG_SOURCES = [
        {
            'name': 'epgshare01',
            'guide_url': 'https://epgshare01.online/epgshare01/',
            'is_directory': True,
            'file_patterns': ['*.xml', '*.xml.gz'],
            'priority': 1
        },
        {
            'name': 'iptv-org.epg',
            'guide_url': 'https://iptv-org.github.io/epg/guides/en/default.xml',
            'backup_urls': [
                'https://raw.githubusercontent.com/iptv-org/epg/master/guides/en/default.xml',
                'https://cdn.jsdelivr.net/gh/iptv-org/epg@master/guides/en/default.xml'
            ],
            'is_directory': False,
            'priority': 2
        },
        {
            'name': 'i.mjh.nz',
            'guide_url': 'https://i.mjh.nz/all/epg.xml',
            'backup_urls': [
                'https://i.mjh.nz/PlutoTV/all.xml',
                'https://i.mjh.nz/SamsungTV/all.xml'
            ],
            'is_directory': False,
            'priority': 3
        },
        {
            'name': 'xmltv.net',
            'guide_url': 'http://www.xmltv.net/xml_files/tv_guide.xml',
            'is_directory': False,
            'priority': 4
        },
        {
            'name': 'epg.51zmt',
            'guide_url': 'http://epg.51zmt.top:8000/e.xml',
            'backup_urls': [
                'http://epg.51zmt.top:8000/e.xml.gz',
                'https://epg.112114.xyz/e.xml'
            ],
            'is_directory': False,
            'priority': 5
        }
    ]

    def __init__(self, max_workers=10):
        self.session = self._create_session()
        self.cache_manager = CacheManager()
        self.max_workers = max_workers
        self.epg_data = {}
        self._lock = threading.Lock()
        self.successful_sources = set()  # Track which sources were successful
        self.TIMEOUT = 30  # Timeout for requests

    def _create_session(self):
        """Create an optimized requests session"""
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[408, 429, 500, 502, 503, 504]
        )
        adapter = HTTPAdapter(
            max_retries=retry_strategy,
            pool_connections=100,
            pool_maxsize=100
        )
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate'
        })
        return session

    async def _get_directory_listing_async(self, url: str) -> List[Dict]:
        """Get directory listing asynchronously with size-based sorting"""
        files = []
        try:
            async with self.session.get(url, timeout=self.TIMEOUT) as response:
                if response.status == 200:
                    content = await response.text()
                    soup = BeautifulSoup(content, 'html.parser')
                    
                    for link in soup.find_all('a'):
                        href = link.get('href')
                        if not href or href in ['.', '..', '/']:
                            continue
                            
                        # Check if file matches patterns
                        if not any(fnmatch.fnmatch(href.lower(), pattern.lower()) 
                                 for pattern in self.EPG_SOURCES[0]['file_patterns']):
                            continue
                            
                        file_url = urljoin(url, href)
                        
                        # Get file size asynchronously
                        try:
                            async with self.session.head(file_url, timeout=self.TIMEOUT) as head_response:
                                size = int(head_response.headers.get('content-length', 0))
                                if size > 1024 * 1024:  # Only files larger than 1MB
                                    files.append({
                                        'url': file_url,
                                        'size': size,
                                        'name': href
                                    })
                        except Exception as e:
                            logger.warning(f"Failed to get size for {file_url}: {str(e)}")
                            continue
                    
                    # Sort by size, largest first
                    files.sort(key=lambda x: x['size'], reverse=True)
                    
                    # Log file sizes for debugging
                    for file in files[:10]:
                        size_mb = file['size'] / (1024 * 1024)
                        logger.info(f"Found EPG file: {file['name']} ({size_mb:.2f} MB)")
                        
                    return files
                else:
                    logger.error(f"Failed to get directory listing: {response.status}")
                    return []
        except Exception as e:
            logger.error(f"Error getting directory listing: {str(e)}")
            return []

    async def _fetch_with_timeout(self, url: str) -> Optional[str]:
        """Fetch URL with timeout and better error handling"""
        try:
            # Longer timeout for large files
            timeout = aiohttp.ClientTimeout(
                total=120,        # 2 minutes total
                connect=30,       # 30 seconds to connect
                sock_read=60      # 60 seconds to read each chunk
            )
            
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': '*/*',
                'Accept-Encoding': 'gzip, deflate'
            }
            
            async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                async with session.get(url, allow_redirects=True) as response:
                    if response.status == 200:
                        try:
                            # Read in chunks to handle large files
                            chunks = []
                            async for chunk in response.content.iter_chunked(1024 * 1024):  # 1MB chunks
                                chunks.append(chunk)
                            content = b''.join(chunks)
                            
                            return self.decode_content(content, url)
                        except Exception as e:
                            logger.error(f"Error reading content from {url}: {str(e)}")
                            return None
                    elif response.status == 404:
                        logger.warning(f"Resource not found: {url}")
                        return None
                    else:
                        logger.error(f"Failed to fetch {url}, status: {response.status}")
                        return None
        except asyncio.TimeoutError:
            logger.error(f"Timeout fetching {url}")
            return None
        except aiohttp.ClientError as e:
            logger.error(f"Client error fetching {url}: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error fetching {url}: {str(e)}")
            return None

    def decode_content(self, content: bytes, url: str) -> Optional[str]:
        """Decode content with better error handling"""
        try:
            if url.endswith('.gz'):
                try:
                    with BytesIO(content) as buf:
                        with gzip.GzipFile(fileobj=buf) as gz:
                            content = gz.read()
                except gzip.BadGzipFile:
                    logger.warning(f"Content from {url} not properly gzipped, trying direct decode")
                except Exception as e:
                    logger.error(f"Error decompressing {url}: {str(e)}")
                    return None
            
            # Try different encodings
            encodings = ['utf-8', 'latin1', 'cp1252']
            for encoding in encodings:
                try:
                    return content.decode(encoding)
                except UnicodeDecodeError:
                    continue
            
            # If all encodings fail, use utf-8 with error handling
            return content.decode('utf-8', errors='ignore')
            
        except Exception as e:
            logger.error(f"Error decoding {url}: {str(e)}")
            return None

    async def fetch_epg_async(self) -> List[str]:
        """Fetch EPG data asynchronously with better error handling and source tracking"""
        tasks = []
        xml_contents = []
        
        # Sort sources by priority
        sorted_sources = sorted(self.EPG_SOURCES, key=lambda x: x.get('priority', 999))

        try:
            for source in sorted_sources:
                try:
                    if source.get('is_directory', False):
                        # Handle directory listing
                        files = await self._get_directory_listing_async(source['guide_url'])
                        logger.info(f"Found {len(files)} files in directory {source['name']}")
                        
                        # Sort files by size (assuming larger files have more data)
                        for file in files[:10]:  # Limit to top 10 largest files
                            tasks.append(self._fetch_with_timeout(file['url']))
                    else:
                        # Handle single file with fallbacks
                        urls = [source['guide_url']]
                        if 'backup_urls' in source:
                            urls.extend(source['backup_urls'])
                        
                        # Try each URL until one works
                        for url in urls:
                            result = await self._fetch_with_timeout(url)
                            if result:
                                xml_contents.append(result)
                                self.successful_sources.add(source['name'])
                                logger.info(f"Successfully fetched EPG from {source['name']} using {url}")
                                break
                
                except Exception as e:
                    logger.error(f"Error processing source {source['name']}: {str(e)}")
                    continue

            if tasks:
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for result in results:
                    if isinstance(result, str):
                        xml_contents.append(result)
                    elif isinstance(result, Exception):
                        logger.error(f"Task failed with error: {str(result)}")

            logger.info(f"Successfully fetched {len(xml_contents)} XML files")
            logger.info(f"Successful sources: {', '.join(self.successful_sources)}")
            return xml_contents

        except Exception as e:
            logger.error(f"Error in fetch_epg_async: {str(e)}")
            return xml_contents

    def process_xml_content(self, xml_content: str) -> Dict:
        """Process XML content with optimized parsing"""
        try:
            root = ET.fromstring(xml_content)
            channels = {}
            
            # Use XPath for faster searching
            for channel in root.findall('.//channel'):
                channel_id = channel.get('id', '')
                if channel_id:
                    channels[channel_id.replace(' ', '')] = True
                    
            return channels
        except ET.ParseError as e:
            logger.error(f"XML parsing error: {e}")
            return {}

    def fetch_epg(self) -> Dict[str, Any]:
        """Main method to fetch EPG data with caching and better error handling"""
        try:
            # Try to load from cache first
            cached_data = {}
            for source in self.EPG_SOURCES:
                try:
                    cached = self.cache_manager.get_cached_data(source['guide_url'])
                    if cached:
                        logger.info(f"Using cached data for {source['name']}")
                        cached_data.update(self.process_xml_content(cached))
                except Exception as e:
                    logger.error(f"Error loading cache for {source['name']}: {str(e)}")

            if cached_data:
                logger.info(f"Loaded {len(cached_data)} channels from cache")
                return cached_data

            # Fetch new data asynchronously
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                xml_contents = loop.run_until_complete(self.fetch_epg_async())
            finally:
                loop.close()

            if not xml_contents:
                logger.warning("No EPG data fetched from any source")
                return {}

            # Process XML contents in parallel
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                future_to_content = {
                    executor.submit(self.process_xml_content, content): content
                    for content in xml_contents
                }

                for future in as_completed(future_to_content):
                    content = future_to_content[future]
                    try:
                        result = future.result()
                        with self._lock:
                            self.epg_data.update(result)
                    except Exception as e:
                        logger.error(f"Error processing XML content: {str(e)}")

            # Cache the results
            for source in self.EPG_SOURCES:
                if not source.get('is_directory', False) and xml_contents:
                    try:
                        self.cache_manager.cache_data(source['guide_url'], xml_contents[0])
                    except Exception as e:
                        logger.error(f"Error caching data for {source['name']}: {str(e)}")

            logger.info(f"Processed {len(self.epg_data)} channels in total")
            return self.epg_data

        except Exception as e:
            logger.error(f"Error in fetch_epg: {str(e)}")
            return {}
