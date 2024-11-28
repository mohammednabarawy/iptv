import os
import re
import time
from urllib.parse import unquote, urlparse, parse_qs, urljoin
from colorama import Fore, Style, init
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, ElementClickInterceptedException, StaleElementReferenceException
import requests
from selenium.webdriver.common.action_chains import ActionChains
import json

# Initialize colorama for colored output
init()

# List of file hosting domains that need special handling
FILE_HOSTS = {
    'devuploads.com': {
        'download_buttons': [
            "//button[@id='downloadbtnf' and contains(text(), 'Generate Free Download Link')]",
            "//button[@id='downloadbtn' and contains(text(), 'Link Generated')]",
            "//a[@id='dlbtn' and contains(text(), 'Download Now')]"
        ],
        'wait_time': 5
    },
    'uploadrar.com': {'download_buttons': ["//a[contains(@class, 'download')]"], 'wait_time': 10},
    'krakenfiles.com': {'download_buttons': ["//button[contains(text(), 'Download')]"], 'wait_time': 10},
    'gofile.io': {'download_buttons': ["//a[contains(@class, 'download')]"], 'wait_time': 10},
}

# Add more comprehensive filtering lists
IGNORED_DOMAINS = {
    # Email Providers
    'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'live.com',
    'mail.com', 'aol.com', 'protonmail.com', 'icloud.com', 'zoho.com',
    'yandex.com', 'gmx.com', 'tutanota.com',
    
    # Social Media
    'facebook.com', 'fb.com', 'twitter.com', 'instagram.com', 'tiktok.com',
    'linkedin.com', 'pinterest.com', 'reddit.com', 'tumblr.com', 'x.com',
    
    # Video Platforms
    'youtube.com', 'youtu.be', 'vimeo.com', 'dailymotion.com', 'twitch.tv',
    
    # Messaging
    'telegram.org', 't.me', 'whatsapp.com', 'messenger.com', 'discord.com',
    'skype.com', 'signal.org', 'line.me', 'viber.com',
    
    # Other Social
    'medium.com', 'quora.com', 'snapchat.com', 'threads.net', 'tiktok.com',
    
    # Shopping/Payment
    'amazon.com', 'ebay.com', 'paypal.com', 'stripe.com', 'shopify.com',
    'aliexpress.com', 'walmart.com', 'etsy.com',
    
    # General sharing
    'linktr.ee', 'bio.link', 'linkin.bio', 'about.me', 'carrd.co',
    
    # Ad networks and analytics
    'google.com', 'doubleclick.net', 'googlesyndication.com', 'analytics.google.com',
    'googleadservices.com', 'googletagmanager.com', 'google-analytics.com',
    'facebook.net', 'fbcdn.net', 'adnxs.com', 'outbrain.com', 'taboola.com',
    
    # Common web services
    'cloudflare.com', 'amazonaws.com', 'digitaloceanspaces.com', 'heroku.com',
    'netlify.app', 'vercel.app', 'github.io', 'pages.dev',
    
    # News/Media
    'cnn.com', 'bbc.com', 'nytimes.com', 'reuters.com', 'bloomberg.com',
    
    # Search Engines
    'google.com', 'bing.com', 'yahoo.com', 'duckduckgo.com', 'baidu.com',
}

IGNORED_KEYWORDS = {
    # Common web elements
    'login', 'signin', 'signup', 'register', 'subscribe', 'account',
    'profile', 'settings', 'preferences', 'dashboard', 'admin',
    'cart', 'checkout', 'payment', 'pricing', 'plans', 'premium',
    'terms', 'privacy', 'policy', 'cookies', 'gdpr', 'legal',
    'help', 'support', 'faq', 'contact', 'about', 'careers',
    
    # Social elements
    'share', 'like', 'follow', 'subscribe', 'comment', 'post',
    'feed', 'trending', 'popular', 'viral', 'social',
    
    # Navigation elements
    'menu', 'navigation', 'sitemap', 'search', 'category',
    'archive', 'tag', 'index', 'page', 'home', 'blog',
    
    # Marketing/Ads
    'ad', 'ads', 'advert', 'sponsored', 'promotion', 'offer',
    'deal', 'sale', 'discount', 'coupon', 'promo',
    
    # Media unrelated to M3U
    'photo', 'image', 'video', 'audio', 'podcast', 'gallery',
    'picture', 'album', 'camera', 'music',
    
    # Common file types
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'zip', 'rar', '7z', 'tar', 'gz',
}

RELEVANT_KEYWORDS = {
    # IPTV related
    'iptv', 'm3u', 'playlist', 'channel', 'stream', 'live',
    'download', 'free', 'link', 'tv', 'hd', '4k', 'sports',
    'movies', 'shows', 'series', 'entertainment',
}

def is_relevant_url_path(path):
    """Check if the URL path contains relevant keywords"""
    path_lower = path.lower()
    
    # If path contains any relevant keywords, consider it relevant
    if any(keyword in path_lower for keyword in RELEVANT_KEYWORDS):
        return True
        
    # If path contains too many ignored keywords, skip it
    ignored_count = sum(1 for keyword in IGNORED_KEYWORDS if keyword in path_lower)
    if ignored_count > 2:  # Skip if more than 2 ignored keywords found
        return False
        
    return True

def should_process_url(url):
    """Check if URL should be processed"""
    try:
        # Skip empty or invalid URLs
        if not url or not isinstance(url, str):
            return False
            
        # Skip special protocols
        if url.lower().startswith(('mailto:', 'tel:', 'sms:', 'javascript:', 'data:', 'file:')):
            return False
            
        # Parse the URL
        parsed = urlparse(url)
        
        # Skip if no domain or invalid scheme
        if not parsed.netloc or parsed.scheme not in ('http', 'https'):
            return False
            
        # Skip if looks like an email address
        if '@' in url:
            return False
            
        domain = parsed.netloc.lower()
        
        # Get base domain (e.g., facebook.com from www.facebook.com)
        base_domain = '.'.join(domain.split('.')[-2:])
        
        # Skip if domain is in ignored list
        if any(ignored in domain for ignored in IGNORED_DOMAINS):
            return False
            
        # Check the URL path for relevance
        if not is_relevant_url_path(parsed.path + parsed.query):
            return False
            
        # Skip common file types that won't contain M3U files
        if parsed.path:
            extension = os.path.splitext(parsed.path)[1].lower()
            if extension in ['.jpg', '.jpeg', '.png', '.gif', '.pdf', '.zip', '.rar',
                           '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx']:
                return False
                
        return True
        
    except Exception as e:
        print(f"{Fore.YELLOW}Error processing URL {url}: {str(e)}{Style.RESET_ALL}")
        return False

def setup_driver():
    chrome_options = Options()
    # chrome_options.add_argument('--headless=new')  # Commented out for debugging
    chrome_options.add_argument('--disable-gpu')
    chrome_options.add_argument('--no-sandbox')
    chrome_options.add_argument('--disable-dev-shm-usage')
    chrome_options.add_argument('--window-size=1920,1080')
    chrome_options.add_argument('--disable-notifications')  # Disable notifications
    chrome_options.add_argument('--disable-popup-blocking')  # Allow popups
    chrome_options.add_argument('user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36')
    
    driver = webdriver.Chrome(options=chrome_options)
    driver.set_page_load_timeout(30)
    driver.set_script_timeout(30)
    return driver

def scroll_and_click(driver, element):
    """Scroll to element and click it with multiple attempts"""
    try:
        # Scroll element into middle of viewport for better interaction
        driver.execute_script("""
            var viewPortHeight = Math.max(document.documentElement.clientHeight, window.innerHeight || 0);
            var elementTop = arguments[0].getBoundingClientRect().top;
            window.scrollBy(0, elementTop - (viewPortHeight / 2));
        """, element)
        time.sleep(1)
        
        # Try multiple click methods
        try:
            element.click()
        except:
            try:
                ActionChains(driver).move_to_element(element).click().perform()
            except:
                driver.execute_script("arguments[0].click();", element)
                
        return True
    except Exception as e:
        print(f"{Fore.YELLOW}Error clicking element: {str(e)}{Style.RESET_ALL}")
        return False

def scroll_page(driver, pause=1.0):
    """Scroll the page completely with a smooth motion"""
    try:
        # Get initial scroll height
        last_height = driver.execute_script("return document.body.scrollHeight")
        
        while True:
            # Scroll down in smaller increments for smoother motion
            current_position = driver.execute_script("return window.pageYOffset;")
            viewport_height = driver.execute_script("return window.innerHeight;")
            target_position = min(current_position + viewport_height, last_height)
            
            # Smooth scroll to target position
            driver.execute_script(f"""
                window.scrollTo({{
                    top: {target_position},
                    behavior: 'smooth'
                }});
            """)
            
            # Wait for scroll and dynamic content
            time.sleep(pause)
            
            # Check if we've reached the bottom
            new_height = driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height and current_position + viewport_height >= last_height:
                break
            last_height = new_height
            
        # Scroll back to top smoothly
        driver.execute_script("window.scrollTo({top: 0, behavior: 'smooth'});")
        time.sleep(pause)
        
    except Exception as e:
        print(f"{Fore.YELLOW}Error during scrolling: {str(e)}{Style.RESET_ALL}")

def handle_devuploads(driver):
    """Special handler for devuploads.com download sequence"""
    try:
        # Step 1: Click "Generate Free Download Link"
        print(f"{Fore.CYAN}Looking for Generate Download Link button...{Style.RESET_ALL}")
        wait = WebDriverWait(driver, 10)
        generate_btn = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//button[@id='downloadbtnf']")
        ))
        scroll_and_click(driver, generate_btn)
        
        # Step 2: Wait for the timer and click "Link Generated"
        print(f"{Fore.CYAN}Waiting for timer (5 seconds)...{Style.RESET_ALL}")
        time.sleep(5)  # Wait for the timer
        
        link_generated_btn = wait.until(EC.element_to_be_clickable(
            (By.XPATH, "//button[@id='downloadbtn']")
        ))
        scroll_and_click(driver, link_generated_btn)
        
        # Step 3: Wait for redirect and click final download button
        print(f"{Fore.CYAN}Looking for final Download Now button...{Style.RESET_ALL}")
        # Switch to new tab if opened
        handles = driver.window_handles
        if len(handles) > 1:
            driver.switch_to.window(handles[-1])
        
        # Wait for and click the final download button
        download_btn = wait.until(EC.presence_of_element_located(
            (By.XPATH, "//a[@id='dlbtn']")
        ))
        
        # Get the download URL
        download_url = download_btn.get_attribute('href')
        if not download_url:
            scroll_and_click(driver, download_btn)
            download_url = driver.current_url
            
        return download_url
        
    except Exception as e:
        print(f"{Fore.RED}Error in devuploads sequence: {str(e)}{Style.RESET_ALL}")
        return None

def handle_file_host(driver, url):
    """Handle file hosting websites to get the actual download link"""
    try:
        print(f"\n{Fore.YELLOW}Processing file host: {url}{Style.RESET_ALL}")
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()
        
        # Navigate to the page
        driver.get(url)
        time.sleep(3)  # Initial load wait
        
        # First scroll the page to load all content
        scroll_page(driver)
        
        # Handle any popups or overlays
        try:
            driver.execute_script("""
                // Remove overlay divs
                var overlays = document.querySelectorAll('div[class*="popup"], div[class*="overlay"], div[id*="popup"], div[id*="overlay"], div[class*="adblock"]');
                overlays.forEach(function(overlay) {
                    overlay.remove();
                });
                // Remove modal backdrops
                var backdrops = document.querySelectorAll('div[class*="modal"], div[class*="backdrop"]');
                backdrops.forEach(function(backdrop) {
                    backdrop.remove();
                });
            """)
        except:
            pass
            
        # Special handling for devuploads.com
        if 'devuploads.com' in domain:
            download_url = handle_devuploads(driver)
            if download_url:
                return download_url
                
        # Handle other file hosts...
        host_config = next((config for host, config in FILE_HOSTS.items() if host in domain), None)
        if host_config:
            for selector in host_config['download_buttons']:
                try:
                    wait = WebDriverWait(driver, 10)
                    download_button = wait.until(EC.presence_of_element_located((By.XPATH, selector)))
                    
                    download_url = download_button.get_attribute('href')
                    if not download_url:
                        if scroll_and_click(driver, download_button):
                            time.sleep(host_config['wait_time'])
                            
                            handles = driver.window_handles
                            if len(handles) > 1:
                                driver.switch_to.window(handles[-1])
                                scroll_page(driver)
                            
                            download_url = driver.current_url
                    
                    if download_url and ('.m3u' in download_url.lower() or '.m3u8' in download_url.lower()):
                        print(f"{Fore.GREEN}Found M3U download link: {download_url}{Style.RESET_ALL}")
                        return download_url
                        
                except Exception as e:
                    print(f"{Fore.YELLOW}Error with selector {selector}: {str(e)}{Style.RESET_ALL}")
                    continue
        
        # Try to find M3U links in page source
        page_source = driver.page_source
        m3u_pattern = r'https?://[^\s<>"\']+?\.m3u8?[^\s<>"\']+'
        m3u_links = re.findall(m3u_pattern, page_source, re.IGNORECASE)
        
        if m3u_links:
            print(f"{Fore.GREEN}Found M3U link in page source: {m3u_links[0]}{Style.RESET_ALL}")
            return m3u_links[0]
            
        return None
        
    except Exception as e:
        print(f"{Fore.RED}Error handling file host {url}: {str(e)}{Style.RESET_ALL}")
        return None
    finally:
        # Close any extra tabs, keeping the main one
        if len(driver.window_handles) > 1:
            main_handle = driver.window_handles[0]
            for handle in driver.window_handles[1:]:
                driver.switch_to.window(handle)
                driver.close()
            driver.switch_to.window(main_handle)

def download_m3u_file(url, output_dir, driver=None):
    try:
        # Check if this is a file hosting site
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()
        
        if any(host in domain for host in FILE_HOSTS.keys()):
            if driver:
                download_url = handle_file_host(driver, url)
                if download_url:
                    url = download_url
                else:
                    return False
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': '*/*',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive'
        }
        
        response = requests.get(url, headers=headers, allow_redirects=True, timeout=30)
        response.raise_for_status()
        
        # Check if the content seems to be an M3U file
        content_preview = response.content[:100].decode('utf-8', errors='ignore')
        if not ('#EXTM3U' in content_preview or '.m3u' in url.lower() or '.m3u8' in url.lower()):
            return False
            
        filename = clean_filename(url)
        if not filename or filename in ['.m3u', '.m3u8']:
            filename = f"playlist_{int(time.time())}.m3u"
            
        filepath = os.path.join(output_dir, filename)
        
        with open(filepath, 'wb') as f:
            f.write(response.content)
        print(f"{Fore.GREEN}Successfully downloaded: {filename}{Style.RESET_ALL}")
        return True
    except Exception as e:
        print(f"{Fore.RED}Error downloading {url}: {str(e)}{Style.RESET_ALL}")
        return False

def extract_m3u_links(text):
    """Extract potential M3U links from text content"""
    url_pattern = r'https?://[^\s<>"\']+?\.m3u8?[^\s<>"\']+'
    return re.findall(url_pattern, text, re.IGNORECASE)

def clean_filename(url):
    parsed_url = urlparse(url)
    path = parsed_url.path
    filename = os.path.basename(path)
    filename = unquote(filename)
    filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
    
    if not filename.lower().endswith(('.m3u', '.m3u8')):
        filename += '.m3u'
    
    return filename

def is_potential_m3u_page(url):
    patterns = [
        'iptv', 'playlist', 'm3u', 'stream', 'channel', 'live',
        'download', 'media', 'tv', 'sports', 'movie', 'link'
    ]
    url_lower = url.lower()
    return any(pattern in url_lower for pattern in patterns)

def get_page_links(driver, url):
    """Get all links from a page"""
    try:
        if not safe_get_with_retry(driver, url):
            return []
        
        time.sleep(2)  # Wait for initial load
        
        # Get all text content from the page
        page_text = driver.page_source
        
        # Extract links from text content
        m3u_links = extract_m3u_links(page_text)
        
        # Get regular links
        links = driver.find_elements(By.TAG_NAME, "a")
        hrefs = []
        
        for link in links:
            try:
                href = link.get_attribute('href')
                if href:
                    hrefs.append(href)
            except (StaleElementReferenceException, Exception):
                continue
        
        # Combine and deduplicate links
        all_links = list(set(hrefs + m3u_links))
        return all_links
        
    except Exception as e:
        print(f"{Fore.RED}Error getting links from {url}: {str(e)}{Style.RESET_ALL}")
        return []

def process_page(driver, url, output_dir, processed_urls, depth=0, max_depth=3):
    """Recursively process pages to find M3U files"""
    if depth > max_depth or url in processed_urls:
        return 0
        
    # Skip if URL should not be processed
    if not should_process_url(url):
        return 0
        
    processed_urls.add(url)
    m3u_count = 0
    
    print(f"\n{Fore.CYAN}Processing page (depth {depth}): {url}{Style.RESET_ALL}")
    
    # Get all links from the page
    links = get_page_links(driver, url)
    print(f"Found {len(links)} links on this page")
    
    for href in links:
        if not href or href in processed_urls or not should_process_url(href):
            continue
            
        # Check if it's a direct M3U file
        if href.lower().endswith(('.m3u', '.m3u8')):
            print(f"\nAttempting to download M3U file: {href}")
            if download_m3u_file(href, output_dir, driver):
                m3u_count += 1
        
        # Check hosting platforms that might contain M3U files
        elif any(host in href.lower() for host in [
            'raw.githubusercontent.com', 'github.com', 'pastebin.com',
            'drive.google.com', 'mediafire.com', 'mega.nz', 'dropbox.com',
            'devuploads.com', 'uploadrar.com', 'krakenfiles.com',
            'gofile.io', 'anonfiles.com', 'bayfiles.com'
        ]):
            print(f"\nChecking hosting platform: {href}")
            if download_m3u_file(href, output_dir, driver):
                m3u_count += 1
        
        # If it's a potential page with M3U files, process it recursively
        elif is_potential_m3u_page(href):
            m3u_count += process_page(driver, href, output_dir, processed_urls, depth + 1, max_depth)
    
    return m3u_count

def safe_get_with_retry(driver, url, max_retries=3):
    """Safely navigate to a URL with retries"""
    for attempt in range(max_retries):
        try:
            driver.get(url)
            return True
        except Exception as e:
            if attempt == max_retries - 1:
                print(f"{Fore.RED}Failed to load page after {max_retries} attempts: {url}{Style.RESET_ALL}")
                return False
            print(f"Retry {attempt + 1}/{max_retries} loading page: {url}")
            time.sleep(2)
    return False

def scrape_heylink():
    url = "https://heylink.me/tech_edu_byte/"
    output_dir = "m3u_files"
    
    print(f"{Fore.CYAN}Starting to scrape M3U files from {url}{Style.RESET_ALL}")
    os.makedirs(output_dir, exist_ok=True)
    print(f"Output directory: {os.path.abspath(output_dir)}")
    
    try:
        print("Initializing Chrome WebDriver...")
        driver = setup_driver()
        
        processed_urls = set()
        total_m3u_files = process_page(driver, url, output_dir, processed_urls)
        
        print(f"\n{Fore.GREEN}Total M3U files downloaded: {total_m3u_files}{Style.RESET_ALL}")
        print(f"Files are saved in: {os.path.abspath(output_dir)}")
        
    except Exception as e:
        print(f"{Fore.RED}Error scraping website: {str(e)}{Style.RESET_ALL}")
        print(f"Full error details: {str(e)}")
    
    finally:
        try:
            driver.quit()
        except:
            pass

if __name__ == "__main__":
    scrape_heylink()
