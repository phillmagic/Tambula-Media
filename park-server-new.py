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
from datetime import datetime
from typing import Dict, List, Optional
from dotenv import load_dotenv

from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/park-server.log'),
        logging.StreamHandler()
    ]
)

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
                             current_video: str = None, uptime_seconds: int = 0):
        """Track device heartbeat and status"""
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
            
            # Upsert device heartbeat - using simple table name
            url = f"{SUPABASE_URL}/rest/v1/device_heartbeats"
            
            # Check if heartbeat exists
            params = {
                'device_id': f'eq.{device_id}',
                'server_id': f'eq.{self.server_id}',
                'select': 'id'
            }
            
            response = requests.get(url, headers=SERVICE_HEADERS, params=params)
            
            if response.status_code == 200 and response.json():
                # Update existing heartbeat
                existing_id = response.json()[0]['id']
                params = {'id': f'eq.{existing_id}'}
                response = requests.patch(url, headers=SERVICE_HEADERS, params=params, json=heartbeat_data)
            else:
                # Create new heartbeat
                response = requests.post(url, headers=SERVICE_HEADERS, json=heartbeat_data)
            
            if response.status_code in [201, 204]:
                server_state['connected_devices'][device_id] = {
                    'client_ip': client_ip,
                    'status': status,
                    'last_seen': datetime.now().isoformat()
                }
                
        except Exception as e:
            logging.error(f"Error tracking device heartbeat: {e}")

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
                        logo_url = f"{SUPABASE_URL}/storage/v1/object/public/videos/{file_path}"
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
            
            response = requests.get(url, stream=True, timeout=30)
            if response.status_code != 200:
                logging.error(f"Failed to download {desc}: HTTP {response.status_code}")
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
            
            # Get all playlists - using simple table name (this is correct)
            url = f"{SUPABASE_URL}/rest/v1/playlists"
            params = {'select': '*'}
            response = requests.get(url, headers=HEADERS, params=params, timeout=10)
            
            if response.status_code != 200:
                logging.error(f"Failed to get playlists: {response.text}")
                return False
            
            all_playlists = response.json()
            server_state['playlists'] = {}
            
            # Get videos for each playlist
            for playlist in all_playlists:
                playlist_id = playlist['id']
                
                url = f"{SUPABASE_URL}/rest/v1/playlist_videos"
                params = {
                    'playlist_id': f'eq.{playlist_id}',
                    'select': 'videos(id,filename,file_path),order_index',
                    'order': 'order_index'
                }
                response = requests.get(url, headers=HEADERS, params=params, timeout=10)
                
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
                    server_state['playlists'][playlist_id] = playlist
                    
                    logging.info(f"📁 Playlist '{playlist['name']}': {len(videos)} videos")
            
            # Save to cache
            with open(CACHE_DIR / 'schedules.json', 'w') as f:
                json.dump(server_state['schedules'], f, indent=2)
            
            with open(CACHE_DIR / 'playlists.json', 'w') as f:
                json.dump(server_state['playlists'], f, indent=2)
            
            logging.info(f"✅ Synced {len(server_state['schedules'])} schedules, {len(server_state['playlists'])} playlists")
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
                
                # Download video
                download_url = f"{SUPABASE_URL}/storage/v1/object/public/videos/{file_path}"
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
        "server_time": datetime.now().isoformat(),
        "last_sync": server_state['last_sync'],
        "sync_in_progress": server_state['sync_in_progress'],
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
    status = heartbeat_data.get('status', 'online')
    current_video = heartbeat_data.get('current_video')
    uptime_seconds = heartbeat_data.get('uptime_seconds', 0)
    
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id is required")
    
    # Track device heartbeat
    enhanced_server.track_device_heartbeat(device_id, client_ip, status, current_video, uptime_seconds)
    
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