#!/usr/bin/env python3
"""
Tambula Park Server - Enhanced Content Distribution Server
Syncs content from Supabase and serves to bus clients via LAN
Includes analytics tracking and device management integration
"""

import os
import sys
import time
import json
import logging
import hashlib
import requests
import threading
import socket
import uuid
from pathlib import Path
from urllib.parse import quote
from datetime import datetime
from typing import Dict, List, Optional
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Setup logging
from logging.handlers import RotatingFileHandler as _RFH
_log_fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
_log_handlers: list = [logging.StreamHandler()]
try:
    os.makedirs('logs', exist_ok=True)
    open('logs/park-server.log', 'w').close()  # clear on boot
    _rfh = _RFH('logs/park-server.log', maxBytes=10 * 1024 * 1024, backupCount=3)
    _rfh.setFormatter(_log_fmt)
    _log_handlers.insert(0, _rfh)
except (PermissionError, OSError) as _e:
    print(f"Warning: cannot write log file: {_e} — console only")
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=_log_handlers)

# Load environment variables
load_dotenv()

# Configuration
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_ANON_KEY = os.getenv('SUPABASE_ANON_KEY')
SUPABASE_SERVICE_KEY = os.getenv('SUPABASE_SERVICE_ROLE_KEY')
GROUP_ID = os.getenv('GROUP_ID', 'default')
SERVER_PORT = int(os.getenv('SERVER_PORT', 8080))
SYNC_INTERVAL = int(os.getenv('SYNC_INTERVAL', 600))  # 10 minutes default
SERVER_NAME = os.getenv('SERVER_NAME', f'Park-Server-{socket.gethostname()}')

# Directory structure
BASE_DIR = Path(__file__).parent
VIDEOS_DIR = BASE_DIR / 'videos'
ASSETS_DIR = BASE_DIR / 'assets'
CACHE_DIR = BASE_DIR / 'cache'
LOGS_DIR = BASE_DIR / 'logs'

# Create directories
for directory in [VIDEOS_DIR, ASSETS_DIR, CACHE_DIR, LOGS_DIR]:
    directory.mkdir(exist_ok=True)

# Supabase headers
HEADERS = {
    'apikey': SUPABASE_ANON_KEY,
    'Authorization': f'Bearer {SUPABASE_ANON_KEY}',
    'Content-Type': 'application/json'
}

SERVICE_HEADERS = {
    'apikey': SUPABASE_SERVICE_KEY,
    'Authorization': f'Bearer {SUPABASE_SERVICE_KEY}',
    'Content-Type': 'application/json'
}

# FastAPI app
app = FastAPI(title="Tambula Park Server Enhanced", version="2.0.0")

# Enable CORS for all origins (local network)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
server_state = {
    'server_id': None,
    'last_sync': None,
    'sync_in_progress': False,
    'total_files': 0,
    'total_size': 0,
    'schedules': [],
    'schedule_items': [],
    'playlists': {},
    'settings': {},
    'manifest': {},
    'connected_devices': {},
    'analytics_buffer': []
}


class EnhancedParkServer:
    """Enhanced Park Server with analytics and device tracking"""
    
    def __init__(self):
        self.running = True
        self.sync_thread = None
        self.analytics_thread = None
        self.heartbeat_thread = None
        self.server_id = None
        
    def register_server(self) -> str:
        """Register this server instance in the database"""
        try:
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            
            server_data = {
                'server_name': SERVER_NAME,
                'hostname': hostname,
                'local_ip': local_ip,
                'port': SERVER_PORT,
                'group_id': GROUP_ID,
                'status': 'online',
                'last_heartbeat': datetime.now().isoformat()
            }
            
            # Try to find existing server first - using simple table name
            url = f"{SUPABASE_URL}/rest/v1/park_servers"
            params = {
                'hostname': f'eq.{hostname}',
                'port': f'eq.{SERVER_PORT}',
                'select': 'id'
            }
            
            response = requests.get(url, headers=SERVICE_HEADERS, params=params)
            
            if response.status_code == 200 and response.json():
                # Update existing server
                existing_server = response.json()[0]
                self.server_id = existing_server['id']
                
                url = f"{SUPABASE_URL}/rest/v1/park_servers"
                params = {'id': f'eq.{self.server_id}'}
                
                response = requests.patch(url, headers=SERVICE_HEADERS, params=params, json=server_data)
                logging.info(f"✅ Updated server registration: {self.server_id}")
            else:
                # Create new server
                response = requests.post(url, headers=SERVICE_HEADERS, json=server_data)
                
                if response.status_code == 201:
                    created_server = response.json()[0]
                    self.server_id = created_server['id']
                    logging.info(f"✅ Registered new server: {self.server_id}")
                else:
                    logging.error(f"Failed to register server: {response.text}")
                    self.server_id = str(uuid.uuid4())  # Fallback to local UUID
            
            server_state['server_id'] = self.server_id
            return self.server_id
            
        except Exception as e:
            logging.error(f"Error registering server: {e}")
            self.server_id = str(uuid.uuid4())  # Fallback to local UUID
            server_state['server_id'] = self.server_id
            return self.server_id
    
    def log_analytics(self, client_ip: str, endpoint: str, method: str, status: int, 
                     filename: str = None, file_size_mb: float = None, user_agent: str = None):
        """Log analytics data to buffer for batch processing"""
        analytics_entry = {
            'server_id': self.server_id,
            'client_ip': client_ip,
            'endpoint': endpoint,
            'filename': filename,
            'file_size_mb': file_size_mb,
            'request_method': method,
            'response_status': status,
            'user_agent': user_agent,
            'created_at': datetime.now().isoformat()
        }
        
        server_state['analytics_buffer'].append(analytics_entry)
        
        # Flush buffer if it gets too large
        if len(server_state['analytics_buffer']) >= 50:
            self.flush_analytics()
    
    def flush_analytics(self):
        """Flush analytics buffer to database"""
        if not server_state['analytics_buffer']:
            return
            
        try:
            # Using simple table name
            url = f"{SUPABASE_URL}/rest/v1/server_analytics"
            
            # Send in batches
            batch_size = 20
            buffer = server_state['analytics_buffer'].copy()
            server_state['analytics_buffer'].clear()
            
            for i in range(0, len(buffer), batch_size):
                batch = buffer[i:i + batch_size]
                response = requests.post(url, headers=SERVICE_HEADERS, json=batch)
                
                if response.status_code != 201:
                    logging.warning(f"Failed to flush analytics batch: {response.text}")
                else:
                    logging.info(f"📊 Flushed {len(batch)} analytics entries")
                    
        except Exception as e:
            logging.error(f"Error flushing analytics: {e}")
    
    def update_server_stats(self):
        """Update server statistics in database"""
        try:
            stats_data = {
                'total_files': server_state['total_files'],
                'total_size_mb': round(server_state['total_size'] / 1024 / 1024, 2),
                'total_videos': len(server_state['manifest'].get('videos', {})),
                'total_assets': len(server_state['manifest'].get('assets', {})),
                'last_sync': server_state['last_sync'],
                'sync_in_progress': server_state['sync_in_progress'],
                'last_heartbeat': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }
            
            # Using simple table name
            url = f"{SUPABASE_URL}/rest/v1/park_servers"
            params = {'id': f'eq.{self.server_id}'}
            
            response = requests.patch(url, headers=SERVICE_HEADERS, params=params, json=stats_data)
            
            if response.status_code == 204:
                logging.info("📊 Updated server statistics")
            else:
                logging.warning(f"Failed to update server stats: {response.text}")
                
        except Exception as e:
            logging.error(f"Error updating server stats: {e}")
    
    def heartbeat_loop(self):
        """Background thread for server heartbeat and analytics flushing"""
        logging.info("💓 Server heartbeat started (every 30 seconds)")
        
        while self.running:
            try:
                time.sleep(30)
                
                if not self.running:
                    break
                
                # Update server heartbeat
                self.update_server_stats()
                
                # Flush analytics buffer
                self.flush_analytics()
                
            except Exception as e:
                logging.error(f"Error in heartbeat loop: {e}")
                time.sleep(10)
    
    def track_device_heartbeat(self, device_id: str, client_ip: str, status: str = 'online',
                             current_video: str = None, uptime_seconds: int = 0, sync_info: dict = None, device_name: str = ''):
        """Track device heartbeat and status"""
        # Always update in-memory state — Supabase persistence is best-effort
        server_state['connected_devices'][device_id] = {
            'device_name': device_name,
            'client_ip': client_ip,
            'status': status,
            'current_video': current_video,
            'uptime_seconds': uptime_seconds,
            'sync': sync_info or {},
            'last_seen': datetime.now().isoformat()
        }
        logging.info(f"💓 Heartbeat from {device_id} ({client_ip}) uptime={uptime_seconds}s")

        # Persist to Supabase if configured
        if not SUPABASE_URL or not SUPABASE_SERVICE_KEY:
            return
        try:
            heartbeat_data = {
                'device_id': device_id,
                'server_id': self.server_id,
                'client_ip': client_ip,
                'status': status,
                'current_video': current_video,
                'uptime_seconds': uptime_seconds,
                'last_sync': datetime.now().isoformat()
            }

            url = f"{SUPABASE_URL}/rest/v1/device_heartbeats"
            params = {
                'device_id': f'eq.{device_id}',
                'server_id': f'eq.{self.server_id}',
                'select': 'id'
            }
            response = requests.get(url, headers=SERVICE_HEADERS, params=params, timeout=5)

            if response.status_code == 200 and response.json():
                existing_id = response.json()[0]['id']
                requests.patch(url, headers=SERVICE_HEADERS, params={'id': f'eq.{existing_id}'}, json=heartbeat_data, timeout=5)
            else:
                requests.post(url, headers=SERVICE_HEADERS, json=heartbeat_data, timeout=5)

        except Exception as e:
            logging.warning(f"Supabase heartbeat persistence failed (non-critical): {e}")

    def sync_settings(self) -> bool:
        """Sync settings from Supabase"""
        try:
            logging.info("⚙️  Syncing settings...")
            
            # Using simple table name
            url = f"{SUPABASE_URL}/rest/v1/settings"
            response = requests.get(url, headers=HEADERS, timeout=10)
            
            if response.status_code == 200:
                settings_data = response.json()
                server_state['settings'] = {}
                
                for setting in settings_data:
                    key = setting['setting_key']
                    value = setting['setting_value']
                    file_path = setting.get('file_path')
                    
                    server_state['settings'][key] = {
                        'value': value,
                        'file_path': file_path
                    }
                    
                    # Download logo if exists
                    if key == 'logo' and file_path:
                        logo_url = f"{SUPABASE_URL}/storage/v1/object/public/videos/{quote(file_path)}"
                        logo_dest = ASSETS_DIR / Path(file_path).name
                        self.download_file(logo_url, logo_dest, f"Logo: {Path(file_path).name}")
                        server_state['settings'][key]['local_path'] = str(logo_dest)
                
                # Save to cache
                with open(CACHE_DIR / 'settings.json', 'w') as f:
                    json.dump(server_state['settings'], f, indent=2)
                
                logging.info(f"✅ Synced {len(settings_data)} settings")
                return True
            else:
                logging.warning("No settings found")
                return False
                
        except Exception as e:
            logging.error(f"Error syncing settings: {e}")
            return False

    def get_file_metadata(self, filepath: Path) -> Dict:
        """Get file metadata including timestamp and size"""
        if not filepath.exists():
            return None
            
        stat = filepath.stat()
        return {
            'filename': filepath.name,
            'size': stat.st_size,
            'modified': stat.st_mtime,
            'modified_iso': datetime.fromtimestamp(stat.st_mtime).isoformat()
        }
    
    def download_file(self, url: str, destination: Path, desc: str = None) -> bool:
        """Download file from Supabase with progress"""
        try:
            logging.info(f"⬇️  Downloading: {desc or destination.name}")
            logging.debug(f"   URL: {url}")

            response = requests.get(url, stream=True, timeout=30)

            # If 400 and URL has single /videos/ (missing subfolder), retry with /videos/videos/
            if response.status_code == 400 and '/storage/v1/object/public/videos/' in url \
                    and '/storage/v1/object/public/videos/videos/' not in url:
                alt_url = url.replace(
                    '/storage/v1/object/public/videos/',
                    '/storage/v1/object/public/videos/videos/',
                    1
                )
                logging.warning(f"↩️ Retrying with corrected path: {alt_url[:120]}")
                response = requests.get(alt_url, stream=True, timeout=30)
                if response.status_code == 200:
                    url = alt_url

            if response.status_code != 200:
                logging.error(
                    f"Failed to download {desc}: HTTP {response.status_code} | "
                    f"URL: {url} | Body: {response.text[:300]}"
                )
                return False
            
            # Get file size
            total_size = int(response.headers.get('content-length', 0))
            
            # Download with progress
            downloaded = 0
            with open(destination, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            if progress % 10 < 1:  # Log every 10%
                                logging.info(f"   Progress: {progress:.0f}%")
            
            logging.info(f"✅ Downloaded: {destination.name} ({downloaded / 1024 / 1024:.1f} MB)")
            return True
            
        except Exception as e:
            logging.error(f"Error downloading {desc}: {e}")
            return False
    
    def sync_schedules_and_playlists(self) -> bool:
        """Sync schedules and playlists from Supabase"""
        try:
            logging.info("📅 Syncing schedules and playlists...")
            
            # Get schedules - using simple table name (this is correct)
            url = f"{SUPABASE_URL}/rest/v1/schedules"
            params = {'group_id': f'eq.{GROUP_ID}', 'select': '*'}
            response = requests.get(url, headers=HEADERS, params=params, timeout=10)
            
            if response.status_code != 200:
                logging.error(f"Failed to get schedules: {response.text}")
                return False
            
            server_state['schedules'] = response.json()
            logging.info(f"📅 Found {len(server_state['schedules'])} schedules")
            
            # Get schedule_items for active schedules
            schedule_ids = [s['id'] for s in server_state['schedules'] if s.get('is_active', False)]
            
            if not schedule_ids:
                logging.warning("⚠️  No active schedules found")
                return False
            
            url = f"{SUPABASE_URL}/rest/v1/schedule_items"
            params = {
                'schedule_id': f'in.({",".join(schedule_ids)})',
                'select': '*',
                'order': 'start_time'
            }
            response = requests.get(url, headers=HEADERS, params=params, timeout=10)
            
            if response.status_code != 200:
                logging.error(f"Failed to get schedule items: {response.text}")
                return False
            
            schedule_items = response.json()
            server_state['schedule_items'] = schedule_items
            logging.info(f"📋 Found {len(schedule_items)} schedule items")
            
            # Extract unique playlist IDs from schedule_items
            playlist_ids = list(set([item['playlist_id'] for item in schedule_items]))
            logging.info(f"📁 Unique playlists in schedules: {len(playlist_ids)}")
            
            # Get all playlists - using simple table name (this is correct)
            url = f"{SUPABASE_URL}/rest/v1/playlists"
            params = {'select': '*'}
            response = requests.get(url, headers=HEADERS, params=params, timeout=10)
            
            if response.status_code != 200:
                logging.error(f"Failed to get playlists: {response.text}")
                return False
            
            all_playlists = response.json()
            server_state['playlists'] = {}

            # Step 1: Fetch ALL playlist_videos in paginated batches (avoids N+1 and embedded join)
            all_pv_rows = []
            offset = 0
            PAGE = 1000
            while True:
                pv_resp = requests.get(
                    f"{SUPABASE_URL}/rest/v1/playlist_videos",
                    headers=HEADERS,
                    params={'select': 'playlist_id,video_id,order_index', 'order': 'order_index',
                            'offset': offset, 'limit': PAGE},
                    timeout=15
                )
                if pv_resp.status_code != 200:
                    logging.error(f"Failed to get playlist_videos: {pv_resp.text}")
                    break
                batch = pv_resp.json()
                all_pv_rows.extend(batch)
                if len(batch) < PAGE:
                    break
                offset += PAGE
            logging.info(f"📋 Fetched {len(all_pv_rows)} playlist_video rows")

            # Step 2: Batch fetch video metadata by ID (chunks of 200)
            video_ids = list({row['video_id'] for row in all_pv_rows if row.get('video_id')})
            video_map = {}
            CHUNK = 200
            for i in range(0, len(video_ids), CHUNK):
                chunk = video_ids[i:i + CHUNK]
                v_resp = requests.get(
                    f"{SUPABASE_URL}/rest/v1/videos",
                    headers=HEADERS,
                    params={'id': f'in.({",".join(chunk)})', 'select': 'id,filename,file_path'},
                    timeout=15
                )
                if v_resp.status_code == 200:
                    for v in v_resp.json():
                        video_map[v['id']] = v

            # Step 3: Group playlist_video rows by playlist_id
            pv_by_playlist = {}
            for row in all_pv_rows:
                pid = row['playlist_id']
                vid = video_map.get(row.get('video_id'))
                if vid:
                    pv_by_playlist.setdefault(pid, []).append({
                        'filename': vid['filename'],
                        'file_path': vid['file_path'],
                        'order_index': row.get('order_index') or 0
                    })

            # Attach videos to each playlist
            for playlist in all_playlists:
                playlist_id = playlist['id']
                videos = sorted(pv_by_playlist.get(playlist_id, []),
                                key=lambda x: x['order_index'])
                playlist['videos'] = videos
                server_state['playlists'][playlist_id] = playlist
                logging.info(f"📁 Playlist '{playlist['name']}' ({playlist.get('playlist_type','regular')}): {len(videos)} videos")
            
            # Save to cache
            with open(CACHE_DIR / 'schedules.json', 'w') as f:
                json.dump(server_state['schedules'], f, indent=2)
            
            with open(CACHE_DIR / 'schedule_items.json', 'w') as f:
                json.dump(server_state['schedule_items'], f, indent=2)
            
            with open(CACHE_DIR / 'playlists.json', 'w') as f:
                json.dump(server_state['playlists'], f, indent=2)
            
            logging.info(f"✅ Synced {len(server_state['schedules'])} schedules, {len(schedule_items)} items, {len(server_state['playlists'])} playlists")
            return True
            
        except Exception as e:
            logging.error(f"Error syncing schedules/playlists: {e}")
            return False
    
    def sync_videos(self) -> bool:
        """Sync all video files from Supabase"""
        try:
            logging.info("🎬 Syncing videos...")
            
            # Collect all unique videos from playlists
            videos_to_download = {}
            
            for playlist_id, playlist in server_state['playlists'].items():
                for video in playlist.get('videos', []):
                    filename = video['filename']
                    file_path = video['file_path']
                    
                    if filename not in videos_to_download:
                        videos_to_download[filename] = file_path
            
            logging.info(f"📊 Total unique videos to sync: {len(videos_to_download)}")
            
            # Download missing or outdated videos
            downloaded_count = 0
            skipped_count = 0
            
            for filename, file_path in videos_to_download.items():
                local_path = VIDEOS_DIR / filename
                
                # Check if file exists and is recent
                if local_path.exists():
                    # For now, skip existing files
                    skipped_count += 1
                    logging.info(f"⏭️  Skipping (exists): {filename}")
                    continue
                
                # Normalise file_path before building the URL:
                # 1. If stored as a full URL, use it directly (strip nothing)
                # 2. If stored with a "videos/" bucket-name prefix, strip it (avoids /videos/videos/...)
                # 3. Otherwise use as-is
                if file_path and file_path.startswith('http'):
                    download_url = file_path  # already a full URL
                else:
                    clean_path = file_path or filename
                    # Strip leading bucket-name prefix if present
                    for prefix in ('videos/', '/videos/'):
                        if clean_path.startswith(prefix):
                            clean_path = clean_path[len(prefix):]
                            break
                    download_url = f"{SUPABASE_URL}/storage/v1/object/public/videos/{quote(clean_path)}"

                logging.info(f"   file_path='{file_path}'  →  {download_url}")
                if self.download_file(download_url, local_path, f"Video: {filename}"):
                    downloaded_count += 1
                else:
                    logging.error(f"Failed to download: {filename}")
            
            logging.info(f"✅ Video sync complete: {downloaded_count} downloaded, {skipped_count} skipped")
            return True
            
        except Exception as e:
            logging.error(f"Error syncing videos: {e}")
            return False
    
    def generate_manifest(self) -> Dict:
        """Generate manifest of all files with metadata"""
        manifest = {
            'generated_at': datetime.now().isoformat(),
            'videos': {},
            'assets': {},
            'cache': {},
            'stats': {
                'total_videos': 0,
                'total_assets': 0,
                'total_size_mb': 0
            }
        }
        
        total_size = 0
        
        # Scan videos
        for video_file in VIDEOS_DIR.glob('*'):
            if video_file.is_file():
                metadata = self.get_file_metadata(video_file)
                if metadata:
                    manifest['videos'][video_file.name] = metadata
                    total_size += metadata['size']
        
        manifest['stats']['total_videos'] = len(manifest['videos'])
        
        # Scan assets
        for asset_file in ASSETS_DIR.glob('*'):
            if asset_file.is_file():
                metadata = self.get_file_metadata(asset_file)
                if metadata:
                    manifest['assets'][asset_file.name] = metadata
                    total_size += metadata['size']
        
        manifest['stats']['total_assets'] = len(manifest['assets'])
        
        # Add cached JSON files
        for cache_file in CACHE_DIR.glob('*.json'):
            if cache_file.name != 'manifest.json':
                metadata = self.get_file_metadata(cache_file)
                if metadata:
                    manifest['cache'][cache_file.name] = metadata
        
        manifest['stats']['total_size_mb'] = round(total_size / 1024 / 1024, 2)
        
        # Save manifest
        with open(CACHE_DIR / 'manifest.json', 'w') as f:
            json.dump(manifest, f, indent=2)
        
        server_state['manifest'] = manifest
        server_state['total_files'] = manifest['stats']['total_videos'] + manifest['stats']['total_assets']
        server_state['total_size'] = total_size
        
        return manifest
    
    def full_sync(self) -> bool:
        """Perform full sync from Supabase"""
        if server_state['sync_in_progress']:
            logging.warning("⚠️  Sync already in progress, skipping")
            return False
        
        try:
            server_state['sync_in_progress'] = True
            sync_start = time.time()
            
            logging.info("=" * 60)
            logging.info("🔄 STARTING FULL SYNC FROM SUPABASE")
            logging.info("=" * 60)
            
            # Step 1: Sync settings
            self.sync_settings()
            
            # Step 2: Sync schedules and playlists
            self.sync_schedules_and_playlists()
            
            # Step 3: Sync videos
            self.sync_videos()
            
            # Step 4: Generate manifest
            manifest = self.generate_manifest()
            
            sync_duration = time.time() - sync_start
            server_state['last_sync'] = datetime.now().isoformat()
            
            logging.info("=" * 60)
            logging.info(f"✅ SYNC COMPLETE in {sync_duration:.1f} seconds")
            logging.info(f"📊 Stats:")
            logging.info(f"   • Videos: {manifest['stats']['total_videos']}")
            logging.info(f"   • Assets: {manifest['stats']['total_assets']}")
            logging.info(f"   • Total Size: {manifest['stats']['total_size_mb']} MB")
            logging.info(f"   • Schedules: {len(server_state['schedules'])}")
            logging.info(f"   • Playlists: {len(server_state['playlists'])}")
            logging.info("=" * 60)
            
            return True
            
        except Exception as e:
            logging.error(f"Error during full sync: {e}")
            return False
        finally:
            server_state['sync_in_progress'] = False
    
    def background_sync_loop(self):
        """Background thread for periodic syncing"""
        logging.info(f"🔄 Background sync started (every {SYNC_INTERVAL} seconds)")
        
        # Do initial sync
        self.full_sync()
        
        while self.running:
            try:
                time.sleep(SYNC_INTERVAL)
                
                if not self.running:
                    break
                
                logging.info("⏰ Scheduled sync triggered")
                self.full_sync()
                
            except Exception as e:
                logging.error(f"Error in background sync loop: {e}")
                time.sleep(60)  # Wait a minute before retry
    
    def start(self):
        """Start the enhanced park server"""
        logging.info("🚀 Starting Tambula Park Server Enhanced")
        
        # Register server in database
        self.register_server()
        
        # Start background sync thread
        self.sync_thread = threading.Thread(target=self.background_sync_loop, daemon=True)
        self.sync_thread.start()
        
        # Start heartbeat thread
        self.heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        self.heartbeat_thread.start()
        
        # Start FastAPI server
        hostname = socket.gethostname()
        local_ip = socket.gethostbyname(hostname)
        
        logging.info("=" * 60)
        logging.info("🎯 TAMBULA PARK SERVER ENHANCED STARTED")
        logging.info("=" * 60)
        logging.info(f"📡 Server ID: {self.server_id}")
        logging.info(f"📡 Server running on port {SERVER_PORT}")
        logging.info(f"🖥️  Hostname: {hostname}")
        logging.info(f"🌍 Local IP: {local_ip}")
        logging.info(f"📍 Access: http://{local_ip}:{SERVER_PORT}")
        logging.info("")
        logging.info("🎬 ENDPOINTS:")
        logging.info(f"   • Status:     http://{local_ip}:{SERVER_PORT}/status")
        logging.info(f"   • Analytics:  http://{local_ip}:{SERVER_PORT}/api/analytics")
        logging.info(f"   • Devices:    http://{local_ip}:{SERVER_PORT}/api/devices")
        logging.info(f"   • Manifest:   http://{local_ip}:{SERVER_PORT}/api/manifest")
        logging.info(f"   • Schedules:  http://{local_ip}:{SERVER_PORT}/api/schedules")
        logging.info(f"   • Playlists:  http://{local_ip}:{SERVER_PORT}/api/playlists")
        logging.info(f"   • Settings:   http://{local_ip}:{SERVER_PORT}/api/settings")
        logging.info("")
        logging.info("⚙️  CONFIGURATION:")
        logging.info(f"   • Group ID: {GROUP_ID}")
        logging.info(f"   • Sync Interval: {SYNC_INTERVAL}s ({SYNC_INTERVAL//60}min)")
        logging.info(f"   • Storage: {BASE_DIR}")
        logging.info("=" * 60)
        
        uvicorn.run(app, host="0.0.0.0", port=SERVER_PORT, log_level="info")


# Create global server instance
enhanced_server = EnhancedParkServer()


# ==================== API ENDPOINTS ====================

@app.get("/")
async def root():
    """Root endpoint with server info"""
    return {
        "name": "Tambula Park Server Enhanced",
        "version": "2.0.0",
        "status": "running",
        "server_id": server_state['server_id'],
        "endpoints": [
            "/status",
            "/api/manifest",
            "/api/schedules",
            "/api/playlists",
            "/api/settings",
            "/api/videos",
            "/api/videos/{filename}",
            "/api/assets/{filename}",
            "/api/analytics",
            "/api/devices",
            "/api/devices/heartbeat"
        ]
    }


@app.get("/status")
async def status():
    """Server status and statistics"""
    return {
        "status": "online",
        "server_id": server_state['server_id'],
        "server_name": SERVER_NAME,
        "server_time": datetime.now().isoformat(),
        "last_sync": server_state['last_sync'],
        "sync_in_progress": server_state['sync_in_progress'],
        "sync_interval": SYNC_INTERVAL,
        "connected_devices": len(server_state['connected_devices']),
        "stats": {
            "total_files": server_state['total_files'],
            "total_size_mb": round(server_state['total_size'] / 1024 / 1024, 2),
            "schedules": len(server_state['schedules']),
            "playlists": len(server_state['playlists']),
            "videos": len(server_state['manifest'].get('videos', {})),
            "assets": len(server_state['manifest'].get('assets', {}))
        }
    }


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    """Visual dashboard for monitoring bus sync status"""
    return HTMLResponse(content="""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Tambula Park Server</title>
<style>
  *{margin:0;padding:0;box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;min-height:100vh;padding:24px}
  h1{font-size:1.4rem;font-weight:700;color:#f8fafc}
  h2{font-size:0.85rem;font-weight:600;text-transform:uppercase;letter-spacing:.08em;color:#94a3b8;margin-bottom:12px}
  .header{display:flex;align-items:center;justify-content:space-between;margin-bottom:28px;flex-wrap:gap}
  .header-left{display:flex;align-items:center;gap:12px}
  .dot{width:10px;height:10px;border-radius:50%;background:#22c55e;box-shadow:0 0 8px #22c55e}
  .dot.syncing{background:#f59e0b;box-shadow:0 0 8px #f59e0b;animation:pulse 1s infinite}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
  .refresh-info{font-size:0.75rem;color:#64748b}
  .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px;margin-bottom:28px}
  .card{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:18px}
  .card .val{font-size:1.9rem;font-weight:700;color:#f8fafc;line-height:1}
  .card .lbl{font-size:0.75rem;color:#94a3b8;margin-top:6px}
  .card .sub{font-size:0.7rem;color:#475569;margin-top:4px}
  .section{background:#1e293b;border:1px solid #334155;border-radius:10px;padding:20px;margin-bottom:20px}
  table{width:100%;border-collapse:collapse;font-size:0.82rem}
  th{text-align:left;padding:8px 12px;color:#64748b;font-weight:600;font-size:0.75rem;text-transform:uppercase;border-bottom:1px solid #334155}
  td{padding:10px 12px;border-bottom:1px solid #1e293b;vertical-align:middle}
  tr:last-child td{border-bottom:none}
  tr:hover td{background:#0f172a}
  .badge{display:inline-block;padding:2px 8px;border-radius:9999px;font-size:0.7rem;font-weight:600}
  .badge.online{background:#14532d;color:#4ade80}
  .badge.offline{background:#3b0000;color:#f87171}
  .badge.syncing{background:#431407;color:#fb923c}
  .btn{padding:8px 18px;border-radius:7px;border:none;font-size:0.82rem;font-weight:600;cursor:pointer;transition:opacity .15s}
  .btn-sync{background:#3b82f6;color:#fff}
  .btn-sync:hover{opacity:.85}
  .btn-sync:disabled{background:#334155;color:#64748b;cursor:not-allowed}
  .sync-row{display:flex;align-items:center;justify-content:space-between;margin-bottom:16px}
  .empty{text-align:center;padding:32px;color:#475569;font-size:0.85rem}
  .uptime{font-family:monospace;font-size:0.78rem;color:#94a3b8}
  .video-cell{max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#94a3b8;font-size:0.78rem}
  .ip{font-family:monospace;font-size:0.78rem}
  #syncMsg{font-size:0.78rem;color:#f59e0b;margin-left:12px;display:none}
  .last-sync{font-size:0.75rem;color:#64748b;margin-top:4px}
</style>
</head>
<body>

<div class="header">
  <div class="header-left">
    <div class="dot" id="serverDot"></div>
    <h1 id="serverTitle">Tambula Park Server</h1>
  </div>
  <span class="refresh-info" id="refreshInfo">Loading...</span>
</div>

<!-- Stats row -->
<div class="grid">
  <div class="card"><div class="val" id="statDevices">—</div><div class="lbl">Connected Buses</div></div>
  <div class="card"><div class="val" id="statVideos">—</div><div class="lbl">Videos</div><div class="sub" id="statSize"></div></div>
  <div class="card"><div class="val" id="statPlaylists">—</div><div class="lbl">Playlists</div></div>
  <div class="card"><div class="val" id="statSchedules">—</div><div class="lbl">Schedules</div></div>
</div>

<!-- Sync control + last sync -->
<div class="section">
  <div class="sync-row">
    <div>
      <h2>Sync Status</h2>
      <div class="last-sync" id="lastSync">Last sync: —</div>
      <div class="last-sync" id="nextSync" style="margin-top:2px"></div>
      <div class="last-sync" id="syncFiles" style="margin-top:2px"></div>
    </div>
    <div style="display:flex;align-items:center">
      <span id="syncMsg">Sync triggered...</span>
      <button class="btn btn-sync" id="syncBtn" onclick="triggerSync()">Sync Now</button>
    </div>
  </div>
</div>

<!-- Devices table -->
<div class="section">
  <h2>Connected Buses</h2>
  <div id="devicesBody">
    <div class="empty">Loading devices...</div>
  </div>
</div>

<script>
  function fmt(seconds) {
    if (!seconds) return '—';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return h > 0 ? h + 'h ' + m + 'm' : m + 'm';
  }

  function timeAgo(iso) {
    if (!iso) return '—';
    const diff = Math.floor((Date.now() - new Date(iso)) / 1000);
    if (diff < 60) return diff + 's ago';
    if (diff < 3600) return Math.floor(diff / 60) + 'm ago';
    if (diff < 86400) return Math.floor(diff / 3600) + 'h ago';
    return Math.floor(diff / 86400) + 'd ago';
  }

  async function refresh() {
    try {
      const [statusRes, devicesRes] = await Promise.all([
        fetch('/status'),
        fetch('/api/devices')
      ]);
      const status = await statusRes.json();
      const devicesData = await devicesRes.json();

      // Update dot
      const dot = document.getElementById('serverDot');
      dot.className = 'dot' + (status.sync_in_progress ? ' syncing' : '');
      if (status.server_name) document.getElementById('serverTitle').textContent = status.server_name;

      // Stats
      document.getElementById('statDevices').textContent = status.connected_devices ?? 0;
      document.getElementById('statVideos').textContent = status.stats.videos ?? 0;
      document.getElementById('statSize').textContent = status.stats.total_size_mb + ' MB';
      document.getElementById('statPlaylists').textContent = status.stats.playlists ?? 0;
      document.getElementById('statSchedules').textContent = status.stats.schedules ?? 0;

      // Last sync
      document.getElementById('lastSync').textContent =
        'Last sync: ' + (status.last_sync ? new Date(status.last_sync).toLocaleString() : 'Never');
      if (status.last_sync && status.sync_interval) {
        const nextMs = new Date(status.last_sync).getTime() + status.sync_interval * 1000;
        const diffMin = Math.max(0, Math.round((nextMs - Date.now()) / 60000));
        document.getElementById('nextSync').textContent =
          status.sync_in_progress ? 'Syncing now...' : 'Next sync: ' + (diffMin <= 0 ? 'due now' : 'in ' + diffMin + 'm');
      }
      const s = status.stats;
      document.getElementById('syncFiles').textContent =
        s ? s.videos + ' videos · ' + s.playlists + ' playlists · ' + s.schedules + ' schedules · ' + s.total_size_mb + ' MB' : '';

      // Sync button
      const btn = document.getElementById('syncBtn');
      btn.disabled = status.sync_in_progress;
      btn.textContent = status.sync_in_progress ? 'Syncing...' : 'Sync Now';

      // Devices table
      const devices = devicesData.devices || {};
      const keys = Object.keys(devices);
      const container = document.getElementById('devicesBody');

      if (keys.length === 0) {
        container.innerHTML = '<div class="empty">No buses connected yet. Buses appear here once they send a heartbeat.</div>';
      } else {
        const rows = keys.map(id => {
          const d = devices[id];
          const lastSeen = d.last_seen || d.last_heartbeat;
          const seenAgo = timeAgo(lastSeen);
          const isRecent = lastSeen && (Date.now() - new Date(lastSeen)) < 120000;
          const badgeClass = isRecent ? 'online' : 'offline';
          const badgeText = isRecent ? 'Online' : 'Offline';
          const nowPlaying = d.current_video || '—';
          const sy = d.sync || {};
          let syncCell = '—';
          if (sy.total > 0) {
            if (sy.active) {
              syncCell = '<span style="color:#f59e0b">⬇ Syncing... (' + sy.pending + ' left)</span>';
            } else if (sy.pending > 0) {
              syncCell = '<span style="color:#f59e0b">⚠ ' + sy.pending + ' pending</span>';
            } else {
              syncCell = '<span style="color:#4ade80">✓ Synced (' + sy.local + '/' + sy.total + ')</span>';
            }
          }
          const nameLabel = d.device_name || d.client_ip || '—';
          const ipLabel = d.device_name ? d.client_ip || '' : '';
          return '<tr>' +
            '<td class="ip"><strong>' + nameLabel + '</strong>' + (ipLabel ? '<br><span style="font-weight:400;color:#64748b">' + ipLabel + '</span>' : '') + '</td>' +
            '<td><span class="badge ' + badgeClass + '">' + badgeText + '</span></td>' +
            '<td class="video-cell" title="' + nowPlaying + '">' + nowPlaying + '</td>' +
            '<td class="uptime">' + syncCell + '</td>' +
            '<td class="uptime">' + fmt(d.uptime_seconds) + '</td>' +
            '<td class="uptime">' + seenAgo + '</td>' +
            '</tr>';
        }).join('');

        container.innerHTML = '<table>' +
          '<thead><tr>' +
          '<th>IP Address</th><th>Status</th><th>Now Playing</th><th>Content Sync</th><th>Uptime</th><th>Last Seen</th>' +
          '</tr></thead>' +
          '<tbody>' + rows + '</tbody>' +
          '</table>';
      }

      // Refresh timestamp
      document.getElementById('refreshInfo').textContent =
        'Updated ' + new Date().toLocaleTimeString();

    } catch(e) {
      document.getElementById('refreshInfo').textContent = 'Error loading data';
    }
  }

  async function triggerSync() {
    const btn = document.getElementById('syncBtn');
    const msg = document.getElementById('syncMsg');
    btn.disabled = true;
    msg.style.display = 'inline';
    try {
      await fetch('/api/sync/trigger', { method: 'POST' });
      setTimeout(() => { msg.style.display = 'none'; refresh(); }, 2000);
    } catch(e) {
      msg.textContent = 'Failed to trigger sync';
      setTimeout(() => { msg.style.display = 'none'; btn.disabled = false; }, 3000);
    }
  }

  refresh();
  setInterval(refresh, 30000);
</script>
</body>
</html>""")


@app.get("/api/analytics")
async def get_analytics():
    """Get server analytics summary"""
    return {
        "server_id": server_state['server_id'],
        "connected_devices": server_state['connected_devices'],
        "pending_analytics": len(server_state['analytics_buffer']),
        "last_sync": server_state['last_sync']
    }


@app.get("/api/devices")
async def get_connected_devices():
    """Get list of connected devices"""
    return {
        "server_id": server_state['server_id'],
        "total_devices": len(server_state['connected_devices']),
        "devices": server_state['connected_devices']
    }


@app.post("/api/devices/heartbeat")
async def device_heartbeat(request: Request, heartbeat_data: dict):
    """Receive device heartbeat"""
    client_ip = request.client.host
    
    device_id = heartbeat_data.get('device_id')
    device_name = heartbeat_data.get('device_name', '')
    status = heartbeat_data.get('status', 'online')
    current_video = heartbeat_data.get('current_video')
    uptime_seconds = heartbeat_data.get('uptime_seconds', 0)
    sync_info = {
        'total':   heartbeat_data.get('sync_total', 0),
        'local':   heartbeat_data.get('sync_local', 0),
        'pending': heartbeat_data.get('sync_pending', 0),
        'active':  heartbeat_data.get('sync_active', False),
        'last':    heartbeat_data.get('sync_last')
    }

    if not device_id:
        raise HTTPException(status_code=400, detail="device_id is required")

    # Track device heartbeat
    enhanced_server.track_device_heartbeat(device_id, client_ip, status, current_video, uptime_seconds, sync_info, device_name)
    
    # Log analytics
    enhanced_server.log_analytics(
        client_ip=client_ip,
        endpoint="/api/devices/heartbeat",
        method="POST",
        status=200,
        user_agent=request.headers.get('user-agent')
    )
    
    return {
        "status": "received",
        "server_id": server_state['server_id'],
        "timestamp": datetime.now().isoformat()
    }


@app.get("/api/manifest")
async def get_manifest(request: Request):
    """Get complete file manifest"""
    client_ip = request.client.host
    
    manifest_file = CACHE_DIR / 'manifest.json'
    
    if not manifest_file.exists():
        enhanced_server.log_analytics(client_ip, "/api/manifest", "GET", 404)
        raise HTTPException(status_code=404, detail="Manifest not found")
    
    enhanced_server.log_analytics(client_ip, "/api/manifest", "GET", 200)
    
    with open(manifest_file, 'r') as f:
        return json.load(f)


@app.get("/api/schedules")
async def get_schedules(request: Request):
    """Get all schedules"""
    client_ip = request.client.host
    enhanced_server.log_analytics(client_ip, "/api/schedules", "GET", 200)
    return server_state['schedules']


@app.get("/api/playlists")
async def get_playlists(request: Request):
    """Get all playlists"""
    client_ip = request.client.host
    enhanced_server.log_analytics(client_ip, "/api/playlists", "GET", 200)
    return server_state['playlists']


@app.get("/api/settings")
async def get_settings(request: Request):
    """Get all settings"""
    client_ip = request.client.host
    enhanced_server.log_analytics(client_ip, "/api/settings", "GET", 200)
    return server_state['settings']


@app.get("/api/videos")
async def list_videos(request: Request):
    """List all available videos"""
    client_ip = request.client.host
    
    videos = []
    for video_file in VIDEOS_DIR.glob('*'):
        if video_file.is_file():
            metadata = enhanced_server.get_file_metadata(video_file)
            if metadata:
                videos.append(metadata)
    
    enhanced_server.log_analytics(client_ip, "/api/videos", "GET", 200)
    
    return {
        "total": len(videos),
        "videos": videos
    }


@app.get("/api/videos/{filename}")
async def download_video(filename: str, request: Request):
    """Download a specific video file"""
    video_path = VIDEOS_DIR / filename
    client_ip = request.client.host
    
    if not video_path.exists() or not video_path.is_file():
        enhanced_server.log_analytics(client_ip, f"/api/videos/{filename}", "GET", 404, filename)
        raise HTTPException(status_code=404, detail=f"Video not found: {filename}")
    
    # Log client download
    file_size_mb = video_path.stat().st_size / 1024 / 1024
    logging.info(f"📤 Client {client_ip} downloading: {filename} ({file_size_mb:.1f} MB)")
    
    enhanced_server.log_analytics(
        client_ip=client_ip,
        endpoint=f"/api/videos/{filename}",
        method="GET",
        status=200,
        filename=filename,
        file_size_mb=file_size_mb,
        user_agent=request.headers.get('user-agent')
    )
    
    return FileResponse(
        path=video_path,
        media_type="video/mp4",
        filename=filename
    )


@app.get("/api/assets/{filename}")
async def download_asset(filename: str, request: Request):
    """Download a specific asset file"""
    asset_path = ASSETS_DIR / filename
    client_ip = request.client.host
    
    if not asset_path.exists() or not asset_path.is_file():
        enhanced_server.log_analytics(client_ip, f"/api/assets/{filename}", "GET", 404, filename)
        raise HTTPException(status_code=404, detail=f"Asset not found: {filename}")
    
    file_size_mb = asset_path.stat().st_size / 1024 / 1024
    enhanced_server.log_analytics(
        client_ip=client_ip,
        endpoint=f"/api/assets/{filename}",
        method="GET",
        status=200,
        filename=filename,
        file_size_mb=file_size_mb
    )
    
    return FileResponse(
        path=asset_path,
        filename=filename
    )


@app.post("/api/sync/trigger")
async def trigger_sync(background_tasks: BackgroundTasks, request: Request):
    """Manually trigger a sync (admin only)"""
    client_ip = request.client.host
    
    if server_state['sync_in_progress']:
        enhanced_server.log_analytics(client_ip, "/api/sync/trigger", "POST", 409)
        return {
            "status": "already_syncing",
            "message": "Sync is already in progress"
        }
    
    background_tasks.add_task(enhanced_server.full_sync)
    enhanced_server.log_analytics(client_ip, "/api/sync/trigger", "POST", 200)
    
    return {
        "status": "sync_triggered",
        "message": "Sync has been triggered and will run in background"
    }


@app.post("/api/sync/check")
async def check_sync(client_manifest: Dict, request: Request):
    """
    Client sends its manifest, server responds with what needs updating
    Timestamp-based comparison
    """
    client_ip = request.client.host
    client_videos = client_manifest.get('videos', {})
    server_videos = server_state['manifest'].get('videos', {})
    
    logging.info(f"🔍 Sync check from client {client_ip} ({len(client_videos)} local videos)")
    
    updates_needed = {
        'videos': [],
        'assets': [],
        'schedules_updated': False,
        'playlists_updated': False,
        'settings_updated': False
    }
    
    # Check which videos need updating (timestamp comparison)
    updates_count = 0
    for filename, server_meta in server_videos.items():
        client_meta = client_videos.get(filename)
        
        if not client_meta:
            # Client doesn't have this video
            updates_needed['videos'].append({
                'filename': filename,
                'reason': 'missing',
                'size': server_meta['size'],
                'modified': server_meta['modified_iso']
            })
            updates_count += 1
        elif server_meta['modified'] > client_meta.get('modified', 0):
            # Server version is newer
            updates_needed['videos'].append({
                'filename': filename,
                'reason': 'outdated',
                'size': server_meta['size'],
                'modified': server_meta['modified_iso']
            })
            updates_count += 1
    
    # Check metadata updates (simple version comparison)
    client_last_sync = client_manifest.get('last_sync', 0)
    schedules_file = CACHE_DIR / 'schedules.json'
    playlists_file = CACHE_DIR / 'playlists.json'
    settings_file = CACHE_DIR / 'settings.json'
    
    if schedules_file.exists() and schedules_file.stat().st_mtime > client_last_sync:
        updates_needed['schedules_updated'] = True
    
    if playlists_file.exists() and playlists_file.stat().st_mtime > client_last_sync:
        updates_needed['playlists_updated'] = True
    
    if settings_file.exists() and settings_file.stat().st_mtime > client_last_sync:
        updates_needed['settings_updated'] = True
    
    enhanced_server.log_analytics(client_ip, "/api/sync/check", "POST", 200)
    
    if updates_count > 0:
        logging.info(f"📤 Client {client_ip} needs {updates_count} update(s)")
    else:
        logging.info(f"✅ Client {client_ip} is up to date")
    
    return updates_needed


if __name__ == '__main__':
    enhanced_server.start()