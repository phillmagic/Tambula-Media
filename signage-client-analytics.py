#!/usr/bin/env python3
"""
Enhanced signage client with comprehensive device analytics and uptime tracking
Based on your signage-client-FIXED.py with added analytics capabilities
"""

import os, sys, time, logging, json, requests, threading, signal, uuid
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv
import http.server
import socketserver
from urllib.parse import quote

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class DeviceAnalytics:
    """
    Handles device analytics, uptime tracking, and playback logging
    """
    
    def __init__(self, client):
        self.client = client
        self.device_uuid = None
        self.session_start_time = time.time()
        self.last_heartbeat = 0
        self.heartbeat_interval = 60  # Send heartbeat every minute
        self.uptime_log_id = None
        self.running = True
        
        # Analytics tracking
        self.videos_played_today = 0
        self.adverts_played_today = 0
        self.last_video_log_time = 0
        
        # Get device hardware ID
        self.hardware_id = self.get_hardware_id()
        
        logging.info(f"📊 Analytics initialized for device: {self.hardware_id}")
    
    def get_hardware_id(self):
        """Get unique hardware identifier"""
        try:
            # Try to get MAC address
            import subprocess
            try:
                mac = subprocess.check_output(['cat', '/sys/class/net/eth0/address']).decode().strip()
                if mac:
                    return mac
            except:
                pass
            
            try:
                mac = subprocess.check_output(['cat', '/sys/class/net/wlan0/address']).decode().strip()
                if mac:
                    return mac
            except:
                pass
            
            # Fallback to generated UUID
            return str(uuid.uuid4())
            
        except Exception as e:
            logging.warning(f"Could not get hardware ID: {e}")
            return str(uuid.uuid4())
    
    def register_device(self):
        """Register or update device in database"""
        try:
            device_name = os.getenv('DEVICE_NAME', f'Device-{self.hardware_id[:8]}')
            device_type = os.getenv('DEVICE_TYPE', 'client')
            group_id = os.getenv('GROUP_ID')
            
            # Get IP address
            import socket
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                s.connect(("8.8.8.8", 80))
                ip_address = s.getsockname()[0]
                s.close()
            except:
                ip_address = 'unknown'
            
            # Check if device already exists
            url = f"{self.client.supabase_url}/rest/v1/devices"
            params = {'device_id': f'eq.{self.hardware_id}'}
            response = requests.get(url, headers=self.client.headers, params=params, timeout=10)
            
            device_data = {
                'device_name': device_name,
                'device_id': self.hardware_id,
                'device_type': device_type,
                'group_id': group_id,
                'status': 'online',
                'ip_address': ip_address,
                'last_seen': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            if response.status_code == 200 and response.json():
                # Device exists, update it
                existing_device = response.json()[0]
                self.device_uuid = existing_device['id']
                
                # Update device status
                update_response = requests.patch(
                    f"{url}?device_id=eq.{self.hardware_id}",
                    headers=self.client.headers,
                    json=device_data,
                    timeout=10
                )
                
                if update_response.status_code == 204:
                    logging.info(f"✅ Device updated: {device_name} ({self.hardware_id})")
                else:
                    logging.error(f"Failed to update device: {update_response.status_code}")
                    
            else:
                # Device doesn't exist, create it
                device_data['created_at'] = datetime.now().isoformat()
                
                create_response = requests.post(
                    url,
                    headers={**self.client.headers, 'Prefer': 'return=representation'},
                    json=device_data,
                    timeout=10
                )
                
                if create_response.status_code == 201:
                    self.device_uuid = create_response.json()[0]['id']
                    logging.info(f"✅ Device registered: {device_name} ({self.hardware_id})")
                else:
                    logging.error(f"Failed to register device: {create_response.status_code} - {create_response.text}")
                    return False
            
            # Start uptime logging
            self.start_uptime_log()
            return True
            
        except Exception as e:
            logging.error(f"Error registering device: {e}")
            return False
    
    def start_uptime_log(self):
        """Start a new uptime log entry"""
        try:
            if not self.device_uuid:
                return
            
            uptime_data = {
                'device_id': self.device_uuid,
                'online_at': datetime.now().isoformat(),
                'created_at': datetime.now().isoformat()
            }
            
            url = f"{self.client.supabase_url}/rest/v1/device_uptime_logs"
            response = requests.post(
                url,
                headers={**self.client.headers, 'Prefer': 'return=representation'},
                json=uptime_data,
                timeout=10
            )
            
            if response.status_code == 201:
                self.uptime_log_id = response.json()[0]['id']
                logging.info(f"📊 Started uptime logging: {self.uptime_log_id}")
            else:
                logging.error(f"Failed to start uptime log: {response.status_code}")
                
        except Exception as e:
            logging.error(f"Error starting uptime log: {e}")
    
    def update_uptime_log(self):
        """Update current uptime log with duration"""
        try:
            if not self.uptime_log_id:
                return
            
            current_time = datetime.now()
            duration_seconds = int(time.time() - self.session_start_time)
            
            uptime_data = {
                'offline_at': current_time.isoformat(),
                'duration_seconds': duration_seconds
            }
            
            url = f"{self.client.supabase_url}/rest/v1/device_uptime_logs"
            response = requests.patch(
                f"{url}?id=eq.{self.uptime_log_id}",
                headers=self.client.headers,
                json=uptime_data,
                timeout=10
            )
            
            if response.status_code == 204:
                logging.info(f"📊 Updated uptime log: {duration_seconds}s")
            else:
                logging.error(f"Failed to update uptime log: {response.status_code}")
                
        except Exception as e:
            logging.error(f"Error updating uptime log: {e}")
    
    def send_heartbeat(self):
        """Send periodic heartbeat to update device status"""
        try:
            if not self.device_uuid:
                return
            
            # Update device last_seen and total_uptime
            current_uptime = int(time.time() - self.session_start_time)
            
            device_data = {
                'last_seen': datetime.now().isoformat(),
                'total_uptime_seconds': current_uptime,
                'status': 'online',
                'updated_at': datetime.now().isoformat()
            }
            
            url = f"{self.client.supabase_url}/rest/v1/devices"
            response = requests.patch(
                f"{url}?id=eq.{self.device_uuid}",
                headers=self.client.headers,
                json=device_data,
                timeout=10
            )
            
            if response.status_code == 204:
                logging.debug(f"💓 Heartbeat sent: {current_uptime}s uptime")
                self.last_heartbeat = time.time()
            else:
                logging.error(f"Failed to send heartbeat: {response.status_code}")
                
        except Exception as e:
            logging.error(f"Error sending heartbeat: {e}")
    
    def log_video_playback(self, video_filename, is_advert=False, duration_played=None):
        """Log video playback for analytics"""
        try:
            if not self.device_uuid:
                return
            
            # Prevent duplicate logs for the same video within 30 seconds
            current_time = time.time()
            if current_time - self.last_video_log_time < 30:
                return
            
            self.last_video_log_time = current_time
            
            # Find video in database by filename
            video_url = f"{self.client.supabase_url}/rest/v1/videos"
            video_params = {'filename': f'eq.{video_filename}'}
            video_response = requests.get(video_url, headers=self.client.headers, params=video_params, timeout=10)
            
            video_id = None
            if video_response.status_code == 200 and video_response.json():
                video_id = video_response.json()[0]['id']
            
            # Log playback
            playback_data = {
                'device_id': self.device_uuid,
                'video_id': video_id,
                'played_at': datetime.now().isoformat(),
                'duration_played': duration_played,
                'created_at': datetime.now().isoformat()
            }
            
            playback_url = f"{self.client.supabase_url}/rest/v1/video_playback_logs"
            response = requests.post(
                playback_url,
                headers=self.client.headers,
                json=playback_data,
                timeout=10
            )
            
            if response.status_code == 201:
                if is_advert:
                    self.adverts_played_today += 1
                    logging.info(f"📺 Logged advert playback: {video_filename}")
                else:
                    self.videos_played_today += 1
                    logging.info(f"🎬 Logged video playback: {video_filename}")
            else:
                logging.error(f"Failed to log playback: {response.status_code}")
                
        except Exception as e:
            logging.error(f"Error logging video playback: {e}")
    
    def heartbeat_loop(self):
        """Background thread for periodic heartbeats"""
        logging.info("💓 Heartbeat loop started")
        
        while self.running:
            try:
                current_time = time.time()
                
                # Send heartbeat every minute
                if current_time - self.last_heartbeat > self.heartbeat_interval:
                    self.send_heartbeat()
                
                # Update uptime log every 5 minutes
                if int(current_time) % 300 == 0:  # Every 5 minutes
                    self.update_uptime_log()
                
                time.sleep(30)  # Check every 30 seconds
                
            except Exception as e:
                logging.error(f"Error in heartbeat loop: {e}")
                time.sleep(60)  # Wait longer on error
    
    def start(self):
        """Start analytics tracking"""
        if self.register_device():
            # Start heartbeat thread
            heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
            heartbeat_thread.start()
            logging.info("📊 Device analytics started")
            return True
        return False
    
    def stop(self):
        """Stop analytics and finalize logs"""
        logging.info("📊 Stopping device analytics...")
        self.running = False
        
        # Update final uptime log
        self.update_uptime_log()
        
        # Set device status to offline
        try:
            if self.device_uuid:
                device_data = {
                    'status': 'offline',
                    'last_seen': datetime.now().isoformat(),
                    'updated_at': datetime.now().isoformat()
                }
                
                url = f"{self.client.supabase_url}/rest/v1/devices"
                requests.patch(
                    f"{url}?id=eq.{self.device_uuid}",
                    headers=self.client.headers,
                    json=device_data,
                    timeout=5
                )
                logging.info("📊 Device set to offline")
        except Exception as e:
            logging.error(f"Error setting device offline: {e}")


class SyncManager:
    """
    Manages syncing content from Park Server or Supabase
    Runs in background thread, non-blocking
    """
    
    def __init__(self, client):
        self.client = client
        self.running = True
        self.sync_thread = None
        
        # Configuration from .env
        self.park_server_ip = os.getenv('PARK_SERVER_IP')
        self.park_server_port = os.getenv('PARK_SERVER_PORT', '8080')
        self.sync_interval = int(os.getenv('SYNC_INTERVAL', 60))  # 1 minute default
        
        # Sync state
        self.last_sync_time = 0
        self.sync_in_progress = False
        self.last_sync_source = None  # 'park', 'supabase', or 'failed'
        
        # Manifest tracking
        self.local_manifest = self.load_local_manifest()
        
        logging.info(f"🔄 Sync Manager initialized")
        if self.park_server_ip:
            logging.info(f"   Park Server: http://{self.park_server_ip}:{self.park_server_port}")
        else:
            logging.info(f"   Park Server: Not configured (will use Supabase only)")
        logging.info(f"   Sync Interval: {self.sync_interval}s")
    
    def load_local_manifest(self) -> dict:
        """Load local manifest or create new one"""
        manifest_file = Path('./cache/manifest.json')
        
        if manifest_file.exists():
            try:
                with open(manifest_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logging.error(f"Error loading manifest: {e}")
        
        return {
            'generated_at': datetime.now().isoformat(),
            'videos': {},
            'last_sync': 0,
            'source': 'none'
        }
    
    def save_local_manifest(self):
        """Save current manifest to disk"""
        manifest_file = Path('./cache/manifest.json')
        manifest_file.parent.mkdir(exist_ok=True)
        
        try:
            with open(manifest_file, 'w') as f:
                json.dump(self.local_manifest, f, indent=2)
        except Exception as e:
            logging.error(f"Error saving manifest: {e}")
    
    def check_park_server(self) -> bool:
        """Check if park server is reachable"""
        if not self.park_server_ip:
            return False
        
        try:
            url = f"http://{self.park_server_ip}:{self.park_server_port}/status"
            response = requests.get(url, timeout=3)
            if response.status_code == 200:
                logging.info(f"✅ Park server reachable")
                return True
        except Exception as e:
            logging.debug(f"Park server not reachable: {e}")
        
        return False
    
    def sync_from_park_server(self) -> bool:
        """Sync content from park server"""
        try:
            base_url = f"http://{self.park_server_ip}:{self.park_server_port}"
            logging.info(f"🔄 Syncing from Park Server: {base_url}")
            
            # Step 1: Get park server manifest
            response = requests.get(f"{base_url}/api/manifest", timeout=10)
            if response.status_code != 200:
                logging.error(f"Failed to get park manifest: {response.status_code}")
                return False
            
            park_manifest = response.json()
            park_videos = park_manifest.get('videos', {})
            
            # Step 2: Compare with local manifest
            updates_needed = []
            for filename, park_meta in park_videos.items():
                local_meta = self.local_manifest['videos'].get(filename)
                
                if not local_meta:
                    # New file
                    updates_needed.append({
                        'filename': filename,
                        'reason': 'missing',
                        'modified': park_meta['modified']
                    })
                elif park_meta['modified'] > local_meta.get('modified', 0):
                    # Updated file
                    updates_needed.append({
                        'filename': filename,
                        'reason': 'outdated',
                        'modified': park_meta['modified']
                    })
            
            if not updates_needed:
                logging.info(f"✅ All videos up to date ({len(park_videos)} files)")
                return True
            
            logging.info(f"📥 Downloading {len(updates_needed)} video(s)...")
            
            # Step 3: Download new/updated videos
            downloaded = 0
            for update in updates_needed:
                filename = update['filename']
                video_path = self.client.videos_dir / filename
                
                try:
                    url = f"{base_url}/api/videos/{filename}"
                    logging.info(f"   ⬇️  {filename} ({update['reason']})")
                    
                    response = requests.get(url, stream=True, timeout=30)
                    if response.status_code == 200:
                        total_size = int(response.headers.get('content-length', 0))
                        
                        with open(video_path, 'wb') as f:
                            downloaded_bytes = 0
                            for chunk in response.iter_content(chunk_size=8192):
                                if chunk:
                                    f.write(chunk)
                                    downloaded_bytes += len(chunk)
                        
                        # Update manifest
                        self.local_manifest['videos'][filename] = {
                            'filename': filename,
                            'size': video_path.stat().st_size,
                            'modified': update['modified'],
                            'synced_at': time.time()
                        }
                        
                        downloaded += 1
                        logging.info(f"   ✅ {filename} ({downloaded_bytes / 1024 / 1024:.1f} MB)")
                    else:
                        logging.error(f"   ❌ Failed: {filename} (HTTP {response.status_code})")
                        
                except Exception as e:
                    logging.error(f"   ❌ Error downloading {filename}: {e}")
            
            # Step 4: Sync metadata (schedules, playlists, settings)
            self.sync_metadata_from_park(base_url)
            
            # Step 5: Update manifest
            self.local_manifest['last_sync'] = time.time()
            self.local_manifest['source'] = 'park'
            self.local_manifest['generated_at'] = datetime.now().isoformat()
            self.save_local_manifest()
            
            logging.info(f"✅ Park sync complete: {downloaded}/{len(updates_needed)} downloaded")
            return True
            
        except Exception as e:
            logging.error(f"Error syncing from park server: {e}")
            return False
    
    def sync_metadata_from_park(self, base_url: str):
        """Sync schedules, playlists, and settings from park server"""
        try:
            # Schedules
            response = requests.get(f"{base_url}/api/schedules", timeout=10)
            if response.status_code == 200:
                self.client.schedules = response.json()
                logging.info(f"   📅 Synced {len(self.client.schedules)} schedules")
            
            # Playlists
            response = requests.get(f"{base_url}/api/playlists", timeout=10)
            if response.status_code == 200:
                self.client.playlists_data = response.json()
                logging.info(f"   📁 Synced {len(self.client.playlists_data)} playlists")
            
            # Settings
            response = requests.get(f"{base_url}/api/settings", timeout=10)
            if response.status_code == 200:
                self.client.settings = response.json()
                
                # Download logo if exists
                logo_setting = self.client.settings.get('logo', {})
                if logo_setting.get('file_path'):
                    logo_filename = Path(logo_setting['file_path']).name
                    logo_url = f"{base_url}/api/assets/{logo_filename}"
                    logo_dest = self.client.assets_dir / logo_filename
                    
                    try:
                        response = requests.get(logo_url, timeout=10)
                        if response.status_code == 200:
                            with open(logo_dest, 'wb') as f:
                                f.write(response.content)
                            logging.info(f"   🖼️  Synced logo: {logo_filename}")
                    except Exception as e:
                        logging.warning(f"   ⚠️  Logo download failed: {e}")
                
                logging.info(f"   ⚙️  Synced settings")
            
        except Exception as e:
            logging.error(f"Error syncing metadata: {e}")
    
    def sync_from_supabase(self) -> bool:
        """Fallback: Sync directly from Supabase"""
        try:
            logging.info(f"🔄 Syncing from Supabase (fallback)")
            
            # Use existing client methods
            self.client.fetch_schedules()
            self.client.fetch_playlists()
            self.client.fetch_settings()
            
            # The client will download videos as needed during playback
            # For now, just mark as synced from Supabase
            self.local_manifest['last_sync'] = time.time()
            self.local_manifest['source'] = 'supabase'
            self.save_local_manifest()
            
            logging.info(f"✅ Supabase sync complete")
            return True
            
        except Exception as e:
            logging.error(f"Error syncing from Supabase: {e}")
            return False
    
    def perform_sync(self):
        """Perform a sync check and download if needed"""
        if self.sync_in_progress:
            logging.debug("Sync already in progress, skipping")
            return
        
        try:
            self.sync_in_progress = True
            sync_start = time.time()
            
            # Priority 1: Try park server
            if self.park_server_ip and self.check_park_server():
                if self.sync_from_park_server():
                    self.last_sync_source = 'park'
                    self.last_sync_time = time.time()
                    sync_duration = time.time() - sync_start
                    logging.info(f"✅ Sync complete from Park Server ({sync_duration:.1f}s)")
                    return
            
            # Priority 2: Try Supabase
            if self.sync_from_supabase():
                self.last_sync_source = 'supabase'
                self.last_sync_time = time.time()
                sync_duration = time.time() - sync_start
                logging.info(f"✅ Sync complete from Supabase ({sync_duration:.1f}s)")
                return
            
            # Failed
            self.last_sync_source = 'failed'
            logging.warning("⚠️  Sync failed from all sources, using cached content")
            
        except Exception as e:
            logging.error(f"Sync error: {e}")
        finally:
            self.sync_in_progress = False
    
    def background_sync_loop(self):
        """Background thread that checks for updates periodically"""
        logging.info(f"🔄 Background sync started (every {self.sync_interval}s)")
        
        # Initial sync immediately
        time.sleep(5)  # Wait 5 seconds for server to be ready
        self.perform_sync()
        
        while self.running:
            try:
                time.sleep(self.sync_interval)
                
                if not self.running:
                    break
                
                logging.info(f"⏰ Scheduled sync check...")
                self.perform_sync()
                
            except Exception as e:
                logging.error(f"Error in sync loop: {e}")
                time.sleep(60)  # Wait a minute on error
    
    def start(self):
        """Start the background sync thread"""
        self.sync_thread = threading.Thread(target=self.background_sync_loop, daemon=True)
        self.sync_thread.start()
        logging.info("✅ Sync manager started")
    
    def stop(self):
        """Stop the sync thread"""
        self.running = False
        if self.sync_thread:
            self.sync_thread.join(timeout=5)
        logging.info("🛑 Sync manager stopped")


class SignageClient:
    def __init__(self):
        load_dotenv()
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.supabase_anon_key = os.getenv('SUPABASE_ANON_KEY')
        self.group_id = os.getenv('GROUP_ID')
        self.videos_dir = Path('./videos')
        self.assets_dir = Path('./assets')
        self.videos_dir.mkdir(exist_ok=True)
        self.assets_dir.mkdir(exist_ok=True)
        
        self.headers = {
            'apikey': self.supabase_anon_key,
            'Authorization': f'Bearer {self.supabase_anon_key}',
            'Content-Type': 'application/json'
        }
        
        # Data storage
        self.schedules = []
        self.schedule_items = []
        self.playlists_data = {}
        self.advert_playlists = {}
        self.settings = {}
        self.current_playlist = None
        self.current_video_index = 0
        
        # Timing
        self.last_schedule_check = 0
        self.last_settings_check = 0
        self.check_interval = 30  # Check for updates every 30 seconds
        
        # Server
        self.http_server = None
        self.server_port = 8080
        
        # Advert settings
        self.advert_enabled = False
        self.advert_interval = 180
        self.advert_duration = 30
        self.last_advert_time = time.time()
        self.advert_active = False
        
        # Background refresh thread
        self.refresh_thread = None
        self.running = True
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)        
        
        # Initialize analytics and sync manager
        self.analytics = DeviceAnalytics(self)
        self.sync_manager = SyncManager(self)
        
    def signal_handler(self, signum, frame):
        """Handle shutdown signals"""
        logging.info("🛑 Shutting down signage client...")
        self.running = False
        
        # Stop analytics
        if self.analytics:
            self.analytics.stop()
        
        # Stop sync manager
        if self.sync_manager:
            self.sync_manager.stop()
        
        if self.http_server:
            self.http_server.shutdown()
        sys.exit(0)
    
    def download_logo(self, logo_path):
        """Download logo from Supabase storage"""
        try:
            local_logo_path = self.assets_dir / Path(logo_path).name
            
            # Check if already exists and is recent
            if local_logo_path.exists():
                file_age = time.time() - local_logo_path.stat().st_mtime
                if file_age < 300:  # Less than 5 minutes old
                    return str(local_logo_path)
            
            download_url = f"{self.supabase_url}/storage/v1/object/public/videos/{logo_path}"
            
            logging.info(f"📥 Downloading logo: {logo_path}")
            response = requests.get(download_url, timeout=10)
            
            if response.status_code == 200:
                with open(local_logo_path, 'wb') as f:
                    f.write(response.content)
                logging.info(f"✅ Logo downloaded: {local_logo_path.name}")
                return str(local_logo_path)
            else:
                logging.warning(f"Failed to download logo: {response.status_code}")
                return None
                
        except Exception as e:
            logging.error(f"Error downloading logo: {e}")
            return None
    
    def get_settings(self):
        """Get system settings including logo"""
        try:
            url = f"{self.supabase_url}/rest/v1/settings"
            response = requests.get(url, headers=self.headers, timeout=10)
            
            if response.status_code == 200:
                settings_data = response.json()
                self.settings = {}
                
                for setting in settings_data:
                    key = setting['setting_key']
                    value = setting['setting_value']
                    file_path = setting.get('file_path')
                    
                    self.settings[key] = {
                        'value': value,
                        'file_path': file_path
                    }
                    
                    # Download logo if it exists
                    if key == 'logo' and file_path:
                        logo_local_path = self.download_logo(file_path)
                        if logo_local_path:
                            self.settings[key]['local_path'] = logo_local_path
                
                logging.info(f"⚙️ Loaded {len(self.settings)} settings")
                self.save_settings_to_cache() 
                return True
            else:
                logging.warning("No settings found, using defaults")
                return False
                
        except Exception as e:
            logging.error(f"Error getting settings: {e}")
            return False
    
    def save_schedules_and_playlists_to_cache(self):
        """Save schedules and playlists to cache"""
        try:
            cache_dir = Path('./cache')
            cache_dir.mkdir(exist_ok=True)
            
            # Save schedules
            if self.schedules:
                with open(cache_dir / 'schedules.json', 'w') as f:
                    json.dump(self.schedules, f, indent=2)
                logging.debug("💾 Saved schedules to cache")
            
            # Save schedule_items
            if self.schedule_items:
                with open(cache_dir / 'schedule_items.json', 'w') as f:
                    json.dump(self.schedule_items, f, indent=2)
                logging.debug("💾 Saved schedule_items to cache")
            
            # Save playlists
            if self.playlists_data:
                with open(cache_dir / 'playlists.json', 'w') as f:
                    json.dump(self.playlists_data, f, indent=2)
                logging.debug("💾 Saved playlists to cache")
                
        except Exception as e:
            logging.error(f"Error saving schedules/playlists to cache: {e}")
    
    def save_settings_to_cache(self):
        """Save settings to cache"""
        try:
            cache_dir = Path('./cache')
            cache_dir.mkdir(exist_ok=True)
            
            if self.settings:
                with open(cache_dir / 'settings.json', 'w') as f:
                    json.dump(self.settings, f, indent=2)
                logging.debug("💾 Saved settings to cache")
                
        except Exception as e:
            logging.error(f"Error saving settings to cache: {e}")
    
    def load_schedules_and_playlists_from_cache(self):
        """Load schedules and playlists from cache"""
        try:
            cache_dir = Path('./cache')
            
            # Load schedules
            schedules_file = cache_dir / 'schedules.json'
            if schedules_file.exists():
                with open(schedules_file, 'r') as f:
                    self.schedules = json.load(f)
                logging.info(f"📋 Loaded {len(self.schedules)} schedules from cache")
            else:
                return False
            
            # Load schedule_items
            schedule_items_file = cache_dir / 'schedule_items.json'
            if schedule_items_file.exists():
                with open(schedule_items_file, 'r') as f:
                    self.schedule_items = json.load(f)
                logging.info(f"📋 Loaded {len(self.schedule_items)} schedule items from cache")
            else:
                self.schedule_items = []
                logging.warning("⚠️  No schedule_items cache found, will use empty list")
            
            # Load playlists
            playlists_file = cache_dir / 'playlists.json'
            if playlists_file.exists():
                with open(playlists_file, 'r') as f:
                    self.playlists_data = json.load(f)
                logging.info(f"📁 Loaded {len(self.playlists_data)} playlists from cache")
            else:
                return False
            
            return True
            
        except Exception as e:
            logging.error(f"Error loading from cache: {e}")
            return False
    
    def load_settings_from_cache(self):
        """Load settings from cache"""
        try:
            cache_dir = Path('./cache')
            settings_file = cache_dir / 'settings.json'
            
            if settings_file.exists():
                with open(settings_file, 'r') as f:
                    self.settings = json.load(f)
                logging.info(f"⚙️  Loaded settings from cache")
                return True
            else:
                return False
                
        except Exception as e:
            logging.error(f"Error loading settings from cache: {e}")
            return False
        
    def get_schedules_and_playlists(self):
        """Download schedules and playlists from database"""
        try:
            logging.info(f"📅 Getting schedules for group: {self.group_id}")
            
            # Get schedules with advert settings
            url = f"{self.supabase_url}/rest/v1/schedules"
            params = {'group_id': f'eq.{self.group_id}', 'select': '*'}
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            
            if response.status_code != 200:
                logging.error(f"Failed to get schedules: {response.text}")
                return False
                
            self.schedules = response.json()
            logging.info(f"📅 Found {len(self.schedules)} schedules")
            
            # Get schedule_items for active schedules
            active_schedule_ids = [s['id'] for s in self.schedules if s.get('is_active', False)]
            
            if not active_schedule_ids:
                logging.warning("⚠️  No active schedules found")
                self.schedule_items = []
            else:
                url = f"{self.supabase_url}/rest/v1/schedule_items"
                params = {
                    'schedule_id': f'in.({",".join(active_schedule_ids)})',
                    'select': '*',
                    'order': 'start_time'
                }
                response = requests.get(url, headers=self.headers, params=params, timeout=10)
                
                if response.status_code != 200:
                    logging.error(f"Failed to get schedule items: {response.text}")
                    return False
                
                self.schedule_items = response.json()
                logging.info(f"📋 Found {len(self.schedule_items)} schedule items")
            
            # Check for advert/interruption settings in schedules
            advert_settings_found = False
            for schedule in self.schedules:
                if schedule.get('is_active', False):
                    interruption_interval = schedule.get('interruption_interval')
                    advert_playlist_id = schedule.get('advert_playlist_id')
                    
                    if interruption_interval and interruption_interval > 0:
                        self.advert_enabled = True
                        self.advert_interval = interruption_interval
                        self.advert_duration = 30  # Default duration for each advert
                        advert_settings_found = True
                        logging.info(f"📺 Interruption settings loaded: {interruption_interval}s interval, {self.advert_duration}s duration")
                        if advert_playlist_id:
                            logging.info(f"📺 Advert playlist ID: {advert_playlist_id}")
                        break
            
            if not advert_settings_found:
                self.advert_enabled = False
                logging.info("📺 No interruption settings found in schedules")
            
            # Get ALL playlists
            url = f"{self.supabase_url}/rest/v1/playlists"
            params = {'select': '*'}
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            
            if response.status_code != 200:
                logging.error(f"Failed to get playlists: {response.text}")
                return False
            
            all_playlists = response.json()
            
            # Get unique playlist IDs from schedule_items
            scheduled_playlist_ids = list(set([item['playlist_id'] for item in self.schedule_items]))
            logging.info(f"📁 Unique playlists in schedule items: {len(scheduled_playlist_ids)}")
            
            # Process playlists
            self.playlists_data = {}
            self.advert_playlists = {}
            
            for playlist in all_playlists:
                playlist_id = playlist['id']
                playlist_type = playlist.get('playlist_type', 'regular')
                
                # Get videos in playlist
                url = f"{self.supabase_url}/rest/v1/playlist_videos"
                params = {
                    'playlist_id': f'eq.{playlist_id}',
                    'select': 'videos(id,filename,file_path),order_index',
                    'order': 'order_index'
                }
                response = requests.get(url, headers=self.headers, params=params, timeout=10)
                
                if response.status_code == 200:
                    playlist_videos = response.json()
                    videos = []
                    for pv in playlist_videos:
                        if pv.get('videos'):
                            video = pv['videos']
                            videos.append({
                                'filename': video['filename'],
                                'file_path': video['file_path'],
                                'order_index': pv['order_index']
                            })
                    
                    playlist['videos'] = videos
                    
                    if playlist_type == 'advert':
                        self.advert_playlists[playlist_id] = playlist
                        logging.info(f"📺 Found advert playlist: '{playlist['name']}' with {len(videos)} videos")
                    elif playlist_id in scheduled_playlist_ids:
                        self.playlists_data[playlist_id] = playlist
                        logging.info(f"📁 Loaded regular playlist: '{playlist['name']}' with {len(videos)} videos")
            
            # Pre-download videos
            if self.advert_playlists and self.advert_enabled:
                self.preload_advert_videos()
            
            logging.info(f"✅ Loaded {len(self.schedules)} schedules, {len(self.schedule_items)} schedule items, {len(self.playlists_data)} regular playlists, {len(self.advert_playlists)} advert playlists")
            
            # After successful fetch, save to cache
            self.save_to_cache()
            return len(self.schedules) > 0 and len(self.schedule_items) > 0
            
        except Exception as e:
            logging.error(f"Error getting schedules/playlists: {e}")
            return False
    
    def background_refresh(self):
        """Background thread to check for updates"""
        while self.running:
            try:
                current_time = time.time()
                
                # Check for schedule/playlist updates every 30 seconds
                if current_time - self.last_schedule_check > self.check_interval:
                    logging.info("🔄 Checking for schedule/playlist updates...")
                    self.get_schedules_and_playlists()
                    self.last_schedule_check = current_time
                
                # Check for settings updates every 60 seconds
                if current_time - self.last_settings_check > 60:
                    logging.info("🔄 Checking for settings updates...")
                    self.get_settings()
                    self.last_settings_check = current_time
                
                # Sleep for 10 seconds before next check
                time.sleep(10)
                
            except Exception as e:
                logging.error(f"Error in background refresh: {e}")
                time.sleep(30)  # Wait longer on error
    
    def preload_advert_videos(self):
        """Pre-download all advert videos"""
        logging.info("⬇️ Pre-downloading advert videos...")
        
        total_adverts = 0
        for playlist_id, playlist in self.advert_playlists.items():
            for video in playlist.get('videos', []):
                video_path = self.download_video(video)
                if video_path:
                    total_adverts += 1
        
        logging.info(f"✅ Pre-downloaded {total_adverts} advert videos")
    
    def get_current_playlist(self):
        """Get current active playlist based on schedule_items"""
        now = datetime.now()
        current_time = now.strftime('%H:%M:%S')
        current_day = now.strftime('%A').lower()
        
        day_name_to_number = {
            'monday': 1, 'tuesday': 2, 'wednesday': 3, 'thursday': 4,
            'friday': 5, 'saturday': 6, 'sunday': 7
        }
        current_day_number = day_name_to_number.get(current_day, 1)
        
        # Check each schedule to see if it's active today
        for schedule in self.schedules:
            if not schedule.get('is_active', False):
                continue
                
            days_of_week = schedule.get('days_of_week', [])
            if current_day_number not in days_of_week:
                continue
            
            # Schedule is active today, check schedule_items for current time
            schedule_id = schedule['id']
            matching_items = [item for item in self.schedule_items if item['schedule_id'] == schedule_id]
            
            for item in matching_items:
                start_time = item.get('start_time', '00:00:00')
                end_time = item.get('end_time', '23:59:59')
                
                if start_time <= current_time <= end_time:
                    playlist_id = item['playlist_id']
                    if playlist_id in self.playlists_data:
                        return self.playlists_data[playlist_id]
        
        # No matching schedule item found - gap in schedule
        return None
    
    def get_next_playlist(self):
        """Get the next scheduled playlist"""
        now = datetime.now()
        current_time = now.strftime('%H:%M:%S')
        current_day = now.strftime('%A').lower()
        
        day_name_to_number = {
            'monday': 1, 'tuesday': 2, 'wednesday': 3, 'thursday': 4,
            'friday': 5, 'saturday': 6, 'sunday': 7
        }
        current_day_number = day_name_to_number.get(current_day, 1)
        
        # Find next schedule_item after current time
        future_items = []
        
        for schedule in self.schedules:
            if not schedule.get('is_active', False):
                continue
                
            days_of_week = schedule.get('days_of_week', [])
            if current_day_number not in days_of_week:
                continue
            
            # Schedule is active today, find future items
            schedule_id = schedule['id']
            matching_items = [item for item in self.schedule_items if item['schedule_id'] == schedule_id]
            
            for item in matching_items:
                start_time = item.get('start_time', '00:00:00')
                if start_time > current_time:
                    playlist_id = item['playlist_id']
                    if playlist_id in self.playlists_data:
                        future_items.append((start_time, self.playlists_data[playlist_id]))
        
        if future_items:
            future_items.sort(key=lambda x: x[0])
            return future_items[0][1]
        
        # If no future item today, return first item of any active schedule
        for schedule in self.schedules:
            if schedule.get('is_active', False):
                schedule_id = schedule['id']
                matching_items = [item for item in self.schedule_items if item['schedule_id'] == schedule_id]
                if matching_items:
                    # Sort by start_time and get first
                    matching_items.sort(key=lambda x: x.get('start_time', '00:00:00'))
                    playlist_id = matching_items[0]['playlist_id']
                    if playlist_id in self.playlists_data:
                        return self.playlists_data[playlist_id]
        
        return None
    
    def should_play_advert(self):
        """Check if it's time for adverts - autonomous offline timing"""
        if not self.advert_enabled or not self.advert_playlists:
            return False
            
        current_time = time.time()
        time_since_last_advert = current_time - self.last_advert_time
        
        if time_since_last_advert >= self.advert_interval:
            logging.info(f"📺 Time for advert break: {time_since_last_advert:.0f}s since last")
            return True
        
        return False
    
    def download_video(self, video):
        """Download video if not exists"""
        try:
            local_path = self.videos_dir / video['filename']
            if local_path.exists():
                return str(local_path)
            
            file_path = video['file_path']
            if not file_path:
                return None
                
            download_url = f"{self.supabase_url}/storage/v1/object/public/videos/{file_path}"
            
            logging.info(f"⬇️ Downloading: {video['filename']}")
            response = requests.get(download_url, stream=True, timeout=30)
            
            if response.status_code == 200:
                with open(local_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                logging.info(f"✅ Downloaded: {video['filename']}")
                return str(local_path)
            
            return None
                
        except Exception as e:
            logging.error(f"Error downloading {video['filename']}: {e}")
            return None
    
    def get_logo_path(self):
        """Get current logo path"""
        logo_setting = self.settings.get('logo', {})
        local_path = logo_setting.get('local_path')
        
        if local_path and Path(local_path).exists():
            return f"/assets/{Path(local_path).name}"
        
        # Fallback to default
        return "/assets/tambula.png"
    
    def create_html_player(self, playlist, is_advert=False):
        """Create HTML video player with dynamic logo, PAUSE/RESUME support, and analytics tracking"""
        videos = playlist.get('videos', [])
        if not videos:
            return "<html><body><h1>No videos in playlist</h1></body></html>"
            
        # Download all videos first
        video_files = []
        for video in videos:
            video_path = self.download_video(video)
            if video_path:
                rel_path = Path(video_path).name
                video_files.append({
                    'filename': rel_path,
                    'title': video['filename']
                })
        
        if not video_files:
            return "<html><body><h1>No downloadable videos</h1></body></html>"
            
        # Get current and next playlist info
        current_playlist = self.get_current_playlist()
        next_playlist = self.get_next_playlist()
        
        current_name = current_playlist['name'] if current_playlist else 'None'
        next_name = next_playlist['name'] if next_playlist else 'None'
        
        # Get logo path
        logo_path = self.get_logo_path()
        
        # Get advert playlist videos if adverts are enabled
        advert_videos_json = "[]"
        if self.advert_enabled and self.advert_playlists:
            advert_playlist = list(self.advert_playlists.values())[0]
            advert_video_files = []
            for video in advert_playlist.get('videos', []):
                video_path = self.download_video(video)
                if video_path:
                    rel_path = Path(video_path).name
                    advert_video_files.append({
                        'filename': rel_path,
                        'title': video['filename']
                    })
            advert_videos_json = json.dumps(advert_video_files)
        
        # Create HTML content with dynamic logo, PAUSE/RESUME functionality, and analytics
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Tambula Digital Signage - {playlist['name']}</title>
    <meta charset="UTF-8">
    <style>
        body {{
            margin: 0;
            padding: 0;
            background: black;
            overflow: hidden;
            font-family: Arial, sans-serif;
        }}
        video {{
            width: 100vw;
            height: 100vh;
            object-fit: contain;
            background-color: black;
        }}
        .logo {{
            position: absolute;
            top: 20px;
            right: 20px;
            max-width: 200px;
            max-height: 80px;
            z-index: 1000;
            opacity: 0.9;
        }}
        .status {{
            position: absolute;
            top: 20px;
            left: 20px;
            color: white;
            background: rgba(0,0,0,0.8);
            padding: 15px;
            border-radius: 8px;
            font-size: 16px;
            z-index: 1000;
            max-width: 350px;
        }}
        .bottom-info {{
            position: absolute;
            bottom: 20px;
            left: 20px;
            right: 20px;
            color: white;
            background: rgba(0,0,0,0.8);
            padding: 15px;
            border-radius: 8px;
            font-size: 14px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }}
        .time-display {{
            font-size: 18px;
            font-weight: bold;
        }}
        .playlist-info {{
            text-align: left;
        }}
        /* Ad overlay styles */
        .ad-overlay {{
            position: fixed;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            background: black;
            z-index: 2000;
            display: none;
        }}
        .ad-overlay video {{
            width: 100vw;
            height: 100vh;
            object-fit: cover;
        }}
        .ad-indicator {{
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            color: white;
            background: rgba(255, 0, 0, 0.8);
            padding: 20px 40px;
            border-radius: 10px;
            font-size: 24px;
            font-weight: bold;
            z-index: 2001;
            display: none;
        }}
    </style>
</head>
<body>
    <img src="{logo_path}" alt="Logo" class="logo" onerror="this.src='/assets/tambula.png'">
    
    <div class="status" id="status">
        Current: {current_name}<br>
        Next: {next_name}
    </div>
    
    <!-- Main content video -->
    <video id="mainPlayer" autoplay>
        Your browser does not support video playback.
    </video>
    
    <!-- Ad overlay (hidden by default) -->
    <div class="ad-overlay" id="adOverlay">
        <video id="adPlayer" autoplay>
            Your browser does not support video playback.
        </video>
        <div class="ad-indicator" id="adIndicator">ADVERTISEMENT</div>
    </div>
    
    <div class="bottom-info">
        <div class="playlist-info">
            <div>Playlist: {playlist['name']}</div>
            <div>Type: Regular Content</div>
            <div>Videos: <span id="videoCount">{len(video_files)}</span></div>
        </div>
        <div class="time-display" id="currentTime"></div>
    </div>

    <script>
        // Main playlist videos
        const mainVideos = {json.dumps(video_files)};
        const adVideos = {advert_videos_json};
        const advertEnabled = {str(self.advert_enabled).lower()};
        const advertDuration = {self.advert_duration * 1000}; // Convert to milliseconds
        
        let currentMainVideoIndex = 0;
        let currentAdVideoIndex = 0;
        let mainPlayer = document.getElementById('mainPlayer');
        let adPlayer = document.getElementById('adPlayer');
        let adOverlay = document.getElementById('adOverlay');
        let adIndicator = document.getElementById('adIndicator');
        
        let isPlayingAd = false;
        let adStartTime = null;
        let savedMainVideoTime = 0;
        let savedMainVideoIndex = 0;
        
        // Playlist update tracking
        let currentPlaylistVersion = null;
        let currentPlaylistId = null;
        let pendingScheduleChange = false;
        
        // Analytics tracking
        let videoStartTime = null;
        let lastLoggedVideo = null;
        
        // Update time display
        function updateTime() {{
            const now = new Date();
            document.getElementById('currentTime').textContent = now.toLocaleTimeString();
        }}
        setInterval(updateTime, 1000);
        updateTime();
        
        // Auto-enter fullscreen on load
        document.addEventListener('DOMContentLoaded', function() {{
            setTimeout(function() {{
                if (document.documentElement.requestFullscreen) {{
                    document.documentElement.requestFullscreen();
                }} else if (document.documentElement.webkitRequestFullscreen) {{
                    document.documentElement.webkitRequestFullscreen();
                }} else if (document.documentElement.msRequestFullscreen) {{
                    document.documentElement.msRequestFullscreen();
                }}
            }}, 2000);
        }});
        
        // Analytics: Log video playback
        function logVideoPlayback(filename, isAdvert = false, durationPlayed = null) {{
            try {{
                fetch('/log-playback', {{
                    method: 'POST',
                    headers: {{
                        'Content-Type': 'application/json'
                    }},
                    body: JSON.stringify({{
                        filename: filename,
                        is_advert: isAdvert,
                        duration_played: durationPlayed
                    }})
                }});
                console.log('📊 Logged playback:', filename, isAdvert ? '(advert)' : '(video)');
            }} catch (error) {{
                console.error('Failed to log playback:', error);
            }}
        }}
        
        // Load main video
        function loadMainVideo(index) {{
            // Handle queue end - loop back
            if (index >= mainVideos.length) {{
                console.log('📋 Reached end of playlist, looping...');
                index = 0;
            }}
            
            // Validate index
            if (index < 0 || index >= mainVideos.length) {{
                console.error('Invalid video index:', index);
                return;
            }}
            
            currentMainVideoIndex = index;
            const video = mainVideos[index];
            mainPlayer.src = '/videos/' + video.filename;
            console.log('▶️  Playing video', index + 1, 'of', mainVideos.length, ':', video.filename);
            
            // Analytics: Track video start
            videoStartTime = Date.now();
            lastLoggedVideo = video.filename;
            
            // Update UI
            updatePlaybackUI();
        }}
        
        // Update playback UI elements
        function updatePlaybackUI() {{
            const counter = document.getElementById('videoCount');
            if (counter) {{
                counter.textContent = currentMainVideoIndex + 1 + '/' + mainVideos.length;
            }}
        }}
        
        // Load ad video
        function loadAdVideo(index) {{
            if (index >= adVideos.length) {{
                // All ads played, resume main content
                resumeMainContent();
                return;
            }}
            
            const video = adVideos[index];
            adPlayer.src = '/videos/' + video.filename;
            console.log('Loading ad video:', video.filename);
            
            // Analytics: Log advert start
            logVideoPlayback(video.filename, true);
        }}
        
        // Start playing advertisements
        function startAdvertisement() {{
            if (!advertEnabled || adVideos.length === 0 || isPlayingAd) {{
                return;
            }}
            
            console.log('🎬 Starting advertisement break...');
            isPlayingAd = true;
            adStartTime = Date.now();
            
            // Save current main video state
            savedMainVideoTime = mainPlayer.currentTime;
            savedMainVideoIndex = currentMainVideoIndex;
            
            // Analytics: Log main video duration before pause
            if (lastLoggedVideo && videoStartTime) {{
                const durationPlayed = (Date.now() - videoStartTime) / 1000;
                logVideoPlayback(lastLoggedVideo, false, durationPlayed);
            }}
            
            // PAUSE the main video (don't stop it!)
            mainPlayer.pause();
            console.log('⏸️  Main video PAUSED at', savedMainVideoTime.toFixed(2), 'seconds');
            
            // Show ad overlay
            adOverlay.style.display = 'block';
            adIndicator.style.display = 'block';
            
            // Hide ad indicator after 3 seconds
            setTimeout(() => {{
                adIndicator.style.display = 'none';
            }}, 3000);
            
            // Start playing first ad
            currentAdVideoIndex = 0;
            loadAdVideo(0);
        }}
        
        // Resume main content after ads
        function resumeMainContent() {{
            console.log('🎬 Resuming main content...');
            isPlayingAd = false;
            
            // Hide ad overlay
            adOverlay.style.display = 'none';
            adIndicator.style.display = 'none';
            
            // Restore main video to saved position
            mainPlayer.currentTime = savedMainVideoTime;
            
            // Analytics: Reset video start time for resumed content
            videoStartTime = Date.now();
            
            // RESUME playback (continue from where we paused)
            mainPlayer.play();
            console.log('▶️  Main video RESUMED from', savedMainVideoTime.toFixed(2), 'seconds');
        }}
        
        // Check if ad duration limit reached
        function checkAdDuration() {{
            if (isPlayingAd && adStartTime && (Date.now() - adStartTime) >= advertDuration) {{
                console.log('⏱️  Ad duration limit reached');
                resumeMainContent();
                return true;
            }}
            return false;
        }}
        
        // Check for playlist updates
        async function checkForPlaylistUpdates() {{
            try {{
                const response = await fetch('/api/playlist-check');
                const data = await response.json();
                
                if (data.error) {{
                    console.log('No active playlist');
                    return;
                }}
                
                // First time, just store the version and ID
                if (!currentPlaylistVersion) {{
                    currentPlaylistVersion = data.version;
                    currentPlaylistId = data.playlist_id;
                    console.log('📋 Playlist:', data.playlist_name, '| Version:', currentPlaylistVersion);
                    return;
                }}
                
                // Check if playlist changed (different schedule)
                if (data.playlist_id !== currentPlaylistId) {{
                    console.log('🔄 Schedule changed! Will transition after current video finishes...');
                    pendingScheduleChange = true;
                    
                    // Update status display
                    const statusDiv = document.getElementById('status');
                    if (statusDiv) {{
                        statusDiv.innerHTML = `Current: {current_name}<br>Next: ${{data.playlist_name}}<br><span style="color: #ffa500;">⏳ Pending transition...</span>`;
                    }}
                    
                    showNotification('Schedule changed - will switch after current video');
                    return;
                }}
                
                // Check if current playlist was updated
                if (data.version !== currentPlaylistVersion) {{
                    console.log('🔄 Playlist updated! Merging new content...');
                    updatePlaylistQueue(data.videos);
                    currentPlaylistVersion = data.version;
                }}
                
            }} catch (error) {{
                console.error('Failed to check playlist updates:', error);
            }}
        }}
        
        // Smart queue update
        function updatePlaylistQueue(newVideos) {{
            // Convert to comparable format (using filenames)
            const currentFilenames = mainVideos.map(v => v.filename);
            const newFilenames = newVideos.map(v => v.filename);
            
            // Find newly added videos
            const addedVideos = newVideos.filter(v => 
                !currentFilenames.includes(v.filename)
            );
            
            // Find removed videos
            const removedFilenames = currentFilenames.filter(f => 
                !newFilenames.includes(f)
            );
            
            let changesDetected = false;
            
            // Handle additions
            if (addedVideos.length > 0) {{
                console.log('➕ Adding', addedVideos.length, 'new video(s) to queue');
                
                // Append new videos to end of queue
                mainVideos.push(...addedVideos);
                changesDetected = true;
                
                // Show notification
                showNotification(addedVideos.length + ' new video(s) added to playlist');
            }}
            
            // Handle removals
            if (removedFilenames.length > 0) {{
                console.log('➖ Removing', removedFilenames.length, 'video(s) from queue');
                
                // Check if current video was removed
                if (removedFilenames.includes(mainVideos[currentMainVideoIndex]?.filename)) {{
                    console.warn('⚠️  Current video was removed from playlist, will skip after it ends');
                }}
                
                // Remove videos from queue (keep current and past, remove future ones)
                const originalLength = mainVideos.length;
                mainVideos = mainVideos.filter((v, index) => {{
                    // Keep current and already played videos
                    if (index <= currentMainVideoIndex) {{
                        return true;
                    }}
                    // Remove future videos if they're in removed list
                    return !removedFilenames.includes(v.filename);
                }});
                
                if (mainVideos.length !== originalLength) {{
                    changesDetected = true;
                    showNotification(removedFilenames.length + ' video(s) removed from playlist');
                }}
            }}
            
            // Update UI if changes detected
            if (changesDetected) {{
                updatePlaybackUI();
            }}
        }}
        
        // Show user-friendly notification
        function showNotification(message) {{
            // Create notification element if doesn't exist
            let notification = document.getElementById('updateNotification');
            if (!notification) {{
                notification = document.createElement('div');
                notification.id = 'updateNotification';
                notification.style.cssText = `
                    position: fixed;
                    top: 100px;
                    right: 20px;
                    background: rgba(0, 150, 0, 0.9);
                    color: white;
                    padding: 15px 25px;
                    border-radius: 8px;
                    font-size: 16px;
                    z-index: 3000;
                    box-shadow: 0 4px 6px rgba(0,0,0,0.3);
                `;
                document.body.appendChild(notification);
            }}
            
            notification.textContent = '🔄 ' + message;
            notification.style.display = 'block';
            
            // Auto-hide after 5 seconds
            setTimeout(() => {{
                notification.style.display = 'none';
            }}, 5000);
        }}
        
        // Main video ended - move to next video
        mainPlayer.addEventListener('ended', function() {{
            if (!isPlayingAd) {{
                // Analytics: Log completed video
                if (lastLoggedVideo && videoStartTime) {{
                    const durationPlayed = (Date.now() - videoStartTime) / 1000;
                    logVideoPlayback(lastLoggedVideo, false, durationPlayed);
                }}
                
                // Check if schedule changed while video was playing
                if (pendingScheduleChange) {{
                    console.log('✅ Video finished - switching to new schedule now...');
                    location.reload();
                    return;
                }}
                
                currentMainVideoIndex++;
                loadMainVideo(currentMainVideoIndex);
            }}
        }});
        
        // Ad video ended - move to next ad or finish
        adPlayer.addEventListener('ended', function() {{
            if (checkAdDuration()) {{
                return;
            }}
            
            currentAdVideoIndex++;
            loadAdVideo(currentAdVideoIndex);
        }});
        
        // Error handling
        mainPlayer.addEventListener('error', function() {{
            console.error('Main video error, trying next video');
            setTimeout(() => {{
                currentMainVideoIndex++;
                loadMainVideo(currentMainVideoIndex);
            }}, 1000);
        }});
        
        adPlayer.addEventListener('error', function() {{
            console.error('Ad video error, trying next ad');
            setTimeout(() => {{
                if (checkAdDuration()) {{
                    return;
                }}
                currentAdVideoIndex++;
                loadAdVideo(currentAdVideoIndex);
            }}, 1000);
        }});
        
        // Start playing main content
        loadMainVideo(0);
        
        // Check for advert breaks (only if enabled)
        if (advertEnabled && adVideos.length > 0) {{
            setInterval(function() {{
                if (!isPlayingAd) {{
                    fetch('/check-advert')
                        .then(response => response.json())
                        .then(data => {{
                            if (data.should_play_advert) {{
                                startAdvertisement();
                            }}
                        }})
                        .catch(e => console.log('Advert check failed:', e));
                }}
            }}, 30 * 1000); // Check every 30 seconds
        }}
        
        // Check for playlist updates every 30 seconds
        setInterval(checkForPlaylistUpdates, 30 * 1000);
        
        // Initial check after 5 seconds
        setTimeout(checkForPlaylistUpdates, 5000);
        
        // Keyboard controls
        document.addEventListener('keydown', function(e) {{
            if (e.key === 'f' || e.key === 'F') {{
                if (document.documentElement.requestFullscreen) {{
                    document.documentElement.requestFullscreen();
                }}
            }} else if (e.key === 'n' || e.key === 'N') {{
                if (isPlayingAd) {{
                    currentAdVideoIndex++;
                    loadAdVideo(currentAdVideoIndex);
                }} else {{
                    currentMainVideoIndex++;
                    loadMainVideo(currentMainVideoIndex);
                }}
            }} else if (e.key === 'p' || e.key === 'P') {{
                // Previous video
                if (!isPlayingAd) {{
                    currentMainVideoIndex--;
                    if (currentMainVideoIndex < 0) {{
                        currentMainVideoIndex = mainVideos.length - 1;
                    }}
                    loadMainVideo(currentMainVideoIndex);
                }}
            }} else if (e.key === 'a' || e.key === 'A') {{
                // Manual ad trigger for testing
                if (!isPlayingAd) {{
                    startAdvertisement();
                }}
            }}
        }});
    </script>
</body>
</html>
"""
        
        return html_content
    
    def start_web_server(self):
        """Start HTTP server for video playback"""
        
        signage_client_ref = self
        
        class VideoHandler(http.server.SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(signage_client_ref.videos_dir.parent), **kwargs)
            
            def do_GET(self):
                if self.path == '/':
                    playlist = signage_client_ref.get_current_playlist()
                    if playlist:
                        html = signage_client_ref.create_html_player(playlist, False)
                        self.send_response(200)
                        self.send_header('Content-type', 'text/html; charset=utf-8')
                        self.end_headers()
                        self.wfile.write(html.encode('utf-8'))
                        return
                    
                    fallback_html = """
                    <html>
                    <head><title>Tambula Digital Signage</title></head>
                    <body style="background:black;color:white;font-family:Arial;padding:50px;">
                        <h1>No Active Playlist Found</h1>
                        <p>Check schedule configuration in the admin panel.</p>
                        <p>Current time: <span id="time"></span></p>
                        <script>
                            setInterval(() => {
                                document.getElementById('time').textContent = new Date().toLocaleString();
                            }, 1000);
                        </script>
                    </body>
                    </html>
                    """
                    self.send_response(200)
                    self.send_header('Content-type', 'text/html; charset=utf-8')
                    self.end_headers()
                    self.wfile.write(fallback_html.encode('utf-8'))
                    
                elif self.path == '/check-advert':
                    # Check if advert should play - timing controlled by client
                    should_play = signage_client_ref.should_play_advert()
                    if should_play:
                        # Update last advert time for server-side tracking
                        signage_client_ref.last_advert_time = time.time()
                        
                    response_data = {'should_play_advert': should_play}
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(response_data).encode('utf-8'))
                    
                elif self.path == '/api/playlist-check':
                    # Check if playlist has been updated
                    playlist = signage_client_ref.get_current_playlist()
                    
                    if playlist:
                        # Get video list and generate version hash
                        videos = playlist.get('videos', [])
                        video_filenames = [v['filename'] for v in videos]
                        
                        # Generate hash based on video list order
                        import hashlib
                        version_hash = hashlib.md5(
                            json.dumps(video_filenames, sort_keys=True).encode()
                        ).hexdigest()[:8]
                        
                        # Prepare video list with necessary info
                        video_list = []
                        for video in videos:
                            video_list.append({
                                'filename': video['filename'],
                                'title': video.get('filename', 'Unknown')
                            })
                        
                        response_data = {
                            'playlist_id': playlist['id'],
                            'playlist_name': playlist['name'],
                            'version': version_hash,
                            'video_count': len(video_list),
                            'videos': video_list
                        }
                    else:
                        response_data = {'error': 'No active playlist'}
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(response_data).encode('utf-8'))
                    
                elif self.path == '/status':
                    current_time = time.time()
                    time_since_last_advert = current_time - signage_client_ref.last_advert_time
                    
                    status_info = {
                        'schedules': len(signage_client_ref.schedules),
                        'regular_playlists': len(signage_client_ref.playlists_data),
                        'advert_playlists': len(signage_client_ref.advert_playlists),
                        'current_playlist': signage_client_ref.get_current_playlist()['name'] if signage_client_ref.get_current_playlist() else None,
                        'next_playlist': signage_client_ref.get_next_playlist()['name'] if signage_client_ref.get_next_playlist() else None,
                        'advert_enabled': signage_client_ref.advert_enabled,
                        'advert_interval': signage_client_ref.advert_interval,
                        'advert_duration': signage_client_ref.advert_duration,
                        'time_since_last_advert': int(time_since_last_advert),
                        'next_advert_in': max(0, signage_client_ref.advert_interval - int(time_since_last_advert)) if signage_client_ref.advert_enabled else 'Disabled',
                        'settings_count': len(signage_client_ref.settings),
                        'logo_path': signage_client_ref.get_logo_path(),
                        'background_refresh': 'Active',
                        'pause_resume_ads': 'Enabled',
                        'offline_capable': True,
                        'device_analytics': {
                            'device_id': signage_client_ref.analytics.hardware_id if signage_client_ref.analytics else 'Unknown',
                            'uptime_seconds': int(time.time() - signage_client_ref.analytics.session_start_time) if signage_client_ref.analytics else 0,
                            'videos_played_today': signage_client_ref.analytics.videos_played_today if signage_client_ref.analytics else 0,
                            'adverts_played_today': signage_client_ref.analytics.adverts_played_today if signage_client_ref.analytics else 0
                        }
                    }
                    
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps(status_info, indent=2).encode('utf-8'))
                    
                else:
                    super().do_GET()
            
            def do_POST(self):
                if self.path == '/log-playback':
                    # Handle playback logging from frontend
                    try:
                        content_length = int(self.headers['Content-Length'])
                        post_data = self.rfile.read(content_length)
                        data = json.loads(post_data.decode('utf-8'))
                        
                        filename = data.get('filename')
                        is_advert = data.get('is_advert', False)
                        duration_played = data.get('duration_played')
                        
                        if filename and signage_client_ref.analytics:
                            signage_client_ref.analytics.log_video_playback(
                                filename, is_advert, duration_played
                            )
                        
                        self.send_response(200)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({'status': 'logged'}).encode('utf-8'))
                        
                    except Exception as e:
                        logging.error(f"Error logging playback: {e}")
                        self.send_response(500)
                        self.send_header('Content-type', 'application/json')
                        self.end_headers()
                        self.wfile.write(json.dumps({'error': str(e)}).encode('utf-8'))
                else:
                    self.send_response(404)
                    self.end_headers()
        
        try:
            with socketserver.TCPServer(("0.0.0.0", self.server_port), VideoHandler) as httpd:
                self.http_server = httpd
                
                import socket
                try:
                    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    s.connect(("8.8.8.8", 80))
                    local_ip = s.getsockname()[0]
                    s.close()
                except:
                    local_ip = socket.gethostbyname(socket.gethostname())
                
                logging.info("=" * 60)
                logging.info("🎯 TAMBULA DIGITAL SIGNAGE SERVER STARTED")
                logging.info("=" * 60)
                logging.info(f"📡 Server running on port {self.server_port}")
                logging.info(f"🖥️  Local access: http://localhost:{self.server_port}")
                logging.info(f"🌍 Remote access: http://{local_ip}:{self.server_port}")
                logging.info("")
                logging.info("🎬 AVAILABLE ENDPOINTS:")
                logging.info(f"   • Main content: http://{local_ip}:{self.server_port}/")
                logging.info(f"   • Status info:  http://{local_ip}:{self.server_port}/status")
                logging.info(f"   • Playlist API: http://{local_ip}:{self.server_port}/api/playlist-check")
                logging.info("")
                logging.info("⚡ FEATURES:")
                logging.info("   • Dynamic logo from settings")
                logging.info("   • Background auto-refresh every 30s")
                logging.info("   • Smart queue updates (no interruption)")
                logging.info("   • Automatic fullscreen after 2 seconds")
                logging.info(f"   • PAUSE/RESUME on ads: {'Enabled' if self.advert_enabled else 'Disabled'}")
                if self.advert_enabled:
                    logging.info(f"   • Advert interval: {self.advert_interval}s ({self.advert_interval//60}min)")
                    logging.info(f"   • Advert duration: {self.advert_duration}s")
                logging.info("   • Current/Next playlist display")
                logging.info("   • Real-time clock display")
                logging.info("   • Device analytics and uptime tracking")
                logging.info("   • Automatic playback logging")
                logging.info("   • Press 'A' to manually trigger ad break (testing)")
                logging.info("=" * 60)
                
                httpd.serve_forever()
                
        except Exception as e:
            logging.error(f"Failed to start web server: {e}")
    
    def load_from_cache(self):
        """Load schedules and playlists from cache files"""
        try:
            cache_dir = Path('./cache')
            
            # Load schedules
            schedules_file = cache_dir / 'schedules.json'
            if schedules_file.exists():
                with open(schedules_file, 'r') as f:
                    self.schedules = json.load(f)
                logging.info(f"📋 Loaded {len(self.schedules)} schedules from cache")
            else:
                logging.warning("No cached schedules found")
                return False
            
            # Load playlists
            playlists_file = cache_dir / 'playlists.json'
            if playlists_file.exists():
                with open(playlists_file, 'r') as f:
                    self.playlists_data = json.load(f)
                logging.info(f"📁 Loaded {len(self.playlists_data)} playlists from cache")
            else:
                logging.warning("No cached playlists found")
                return False
            
            # Load settings
            settings_file = cache_dir / 'settings.json'
            if settings_file.exists():
                with open(settings_file, 'r') as f:
                    self.settings = json.load(f)
                logging.info(f"⚙️  Loaded settings from cache")
            
            return True
            
        except Exception as e:
            logging.error(f"Error loading from cache: {e}")
            return False


    def save_to_cache(self):
        """Save schedules and playlists to cache files"""
        try:
            cache_dir = Path('./cache')
            cache_dir.mkdir(exist_ok=True)
            
            # Save schedules
            with open(cache_dir / 'schedules.json', 'w') as f:
                json.dump(self.schedules, f, indent=2)
            
            # Save playlists
            with open(cache_dir / 'playlists.json', 'w') as f:
                json.dump(self.playlists_data, f, indent=2)
            
            # Save settings
            with open(cache_dir / 'settings.json', 'w') as f:
                json.dump(self.settings, f, indent=2)
            
            logging.info("💾 Saved data to cache")
            
        except Exception as e:
            logging.error(f"Error saving to cache: {e}")
    
    def fetch_schedules(self):
        """Fetch schedules (used by sync manager)"""
        return self.get_schedules_and_playlists()
    
    def fetch_playlists(self):
        """Fetch playlists (used by sync manager)"""
        # Already handled in get_schedules_and_playlists
        return True
    
    def fetch_settings(self):
        """Fetch settings (used by sync manager)"""
        return self.get_settings()
            
    def run(self):
        """Main client loop"""
        logging.info("🎯 Starting Tambula Digital Signage Client with Analytics")
        
        # Start analytics first
        if not self.analytics.start():
            logging.warning("⚠️  Analytics failed to start, continuing without device tracking")
        
        # Start sync manager
        self.sync_manager.start()
        
        # Try to load initial data (don't exit if fails)
        try:
            self.get_settings()
            if not self.get_schedules_and_playlists():
                logging.warning("⚠️  Failed to load initial data, will retry")
                # Try cache
                self.load_from_cache()
        except Exception as e:
            logging.error(f"Error during initialization: {e}")
            logging.info("Attempting to load from cache...")
            self.load_from_cache()
        
        # Start background refresh thread (will keep trying)
        self.refresh_thread = threading.Thread(target=self.background_refresh, daemon=True)
        self.refresh_thread.start()
        logging.info("🔄 Background refresh thread started")
        
        # ALWAYS start web server (even if offline)
        self.start_web_server()
        
if __name__ == '__main__':
    client = SignageClient()
    client.run()