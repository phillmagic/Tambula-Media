#!/bin/bash

# Digital Signage One-Command Setup
# Usage: curl -sSL https://your-domain.com/setup.sh | bash -s -- [server|client]

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log() { echo -e "${GREEN}[INFO]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Check if running as root
if [[ $EUID -eq 0 ]]; then
   error "Don't run as root"
   exit 1
fi

# Get device type from argument or prompt
DEVICE_TYPE="$1"
if [[ -z "$DEVICE_TYPE" ]]; then
    echo "Select device type:"
    echo "1) Server (downloads and serves videos)"
    echo "2) Client (plays videos from server)"
    read -p "Enter 1 or 2: " choice
    case $choice in
        1) DEVICE_TYPE="server" ;;
        2) DEVICE_TYPE="client" ;;
        *) error "Invalid choice"; exit 1 ;;
    esac
fi

log "Setting up Digital Signage $DEVICE_TYPE..."

# Install dependencies
log "Installing system dependencies..."
sudo apt update -qq
sudo apt install -y python3 python3-pip python3-venv git vlc curl jq

# Create project directory
PROJECT_DIR="$HOME/signage"
log "Creating project at $PROJECT_DIR"
mkdir -p "$PROJECT_DIR"
cd "$PROJECT_DIR"

# Setup Python environment
python3 -m venv venv
source venv/bin/activate
pip install -q --upgrade pip requests python-dotenv

# Get configuration
log "Configuration setup..."
read -p "Supabase URL: " SUPABASE_URL
read -p "Supabase Anon Key: " SUPABASE_ANON_KEY
read -p "Group ID: " GROUP_ID
read -p "Device Name: " DEVICE_NAME

# Generate device ID
DEVICE_ID=$(hostname)
if [[ -f /proc/cpuinfo ]]; then
    SERIAL=$(grep "Serial" /proc/cpuinfo | awk '{print $3}' | head -1)
    [[ -n "$SERIAL" && "$SERIAL" != "0000000000000000" ]] && DEVICE_ID="$SERIAL"
fi

# Get server IP for client
if [[ "$DEVICE_TYPE" == "client" ]]; then
    read -p "Server IP Address: " SERVER_IP
fi

# Create .env file
cat > .env << EOF
SUPABASE_URL=$SUPABASE_URL
SUPABASE_ANON_KEY=$SUPABASE_ANON_KEY
GROUP_ID=$GROUP_ID
DEVICE_NAME=$DEVICE_NAME
DEVICE_ID=$DEVICE_ID
VIDEO_DIR=$PROJECT_DIR/videos
CHECK_INTERVAL=60
EOF

[[ "$DEVICE_TYPE" == "client" ]] && echo "SERVER_IP=$SERVER_IP" >> .env

# Create the appropriate script
if [[ "$DEVICE_TYPE" == "server" ]]; then
    log "Creating server script..."
    
cat > signage.py << 'SERVEREOF'
#!/usr/bin/env python3
import os, sys, time, logging, json, signal, requests, threading, re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Any
from dotenv import load_dotenv
from http.server import HTTPServer, SimpleHTTPRequestHandler
import urllib.parse

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class VideoHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, video_dir=None, **kwargs):
        self.video_dir = video_dir
        super().__init__(*args, **kwargs)
    
    def do_GET(self):
        if self.path == '/api/videos':
            self.serve_video_list()
        elif self.path.startswith('/videos/'):
            self.serve_video_file()
        else:
            self.send_error(404)
    
    def serve_video_list(self):
        videos = []
        if self.video_dir and self.video_dir.exists():
            for ext in ['*.mp4', '*.avi', '*.mov', '*.mkv']:
                for f in self.video_dir.glob(ext):
                    if f.is_file():
                        videos.append({'filename': f.name, 'size': f.stat().st_size})
        
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'videos': videos}).encode())
    
    def serve_video_file(self):
        filename = urllib.parse.unquote(self.path.split('/videos/')[-1])
        video_path = self.video_dir / filename
        
        if not video_path.exists():
            self.send_error(404)
            return
        
        self.send_response(200)
        self.send_header('Content-Type', 'video/mp4')
        self.send_header('Content-Length', str(video_path.stat().st_size))
        self.end_headers()
        
        with open(video_path, 'rb') as f:
            while chunk := f.read(8192):
                self.wfile.write(chunk)

class SignageServer:
    def __init__(self):
        load_dotenv()
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.supabase_anon_key = os.getenv('SUPABASE_ANON_KEY')
        self.group_id = os.getenv('GROUP_ID')
        self.device_name = os.getenv('DEVICE_NAME', 'Server')
        self.device_id = os.getenv('DEVICE_ID', 'server-1')
        self.video_dir = Path(os.getenv('VIDEO_DIR', './videos'))
        self.video_dir.mkdir(exist_ok=True)
        
        self.headers = {
            'apikey': self.supabase_anon_key,
            'Authorization': f'Bearer {self.supabase_anon_key}',
            'Content-Type': 'application/json'
        }
        
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)
        
        logging.info(f"Server initialized: {self.device_name}")
    
    def _shutdown(self, signum, frame):
        logging.info("Shutting down...")
        sys.exit(0)
    
    def sanitize_filename(self, filename):
        sanitized = filename.replace(' ', '_')
        sanitized = re.sub(r'[^\w\-_\.]', '_', sanitized)
        return re.sub(r'_+', '_', sanitized)
    
    def register_device(self):
        try:
            device_data = {
                'device_id': self.device_id,
                'device_name': self.device_name,
                'device_type': 'server',
                'group_id': self.group_id,
                'status': 'online',
                'ip_address': self.get_local_ip(),
                'last_seen': datetime.now(timezone.utc).isoformat()
            }
            
            # Try update first, then create
            url = f"{self.supabase_url}/rest/v1/devices"
            params = {'device_id': f'eq.{self.device_id}'}
            
            response = requests.patch(url, headers=self.headers, params=params, json=device_data, timeout=10)
            if response.status_code not in [200, 204]:
                requests.post(url, headers=self.headers, json=device_data, timeout=10)
            
            return True
        except Exception as e:
            logging.error(f"Device registration failed: {e}")
            return False
    
    def get_local_ip(self):
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except:
            return "127.0.0.1"
    
    def get_scheduled_videos(self):
        try:
            # Get schedules
            url = f"{self.supabase_url}/rest/v1/schedules"
            params = {'group_id': f'eq.{self.group_id}', 'select': 'playlist_id'}
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            
            if response.status_code != 200:
                return []
            
            playlist_ids = [s['playlist_id'] for s in response.json()]
            if not playlist_ids:
                return []
            
            # Get videos from playlists
            videos = []
            for pid in playlist_ids:
                url = f"{self.supabase_url}/rest/v1/playlist_videos"
                params = {'playlist_id': f'eq.{pid}', 'select': 'videos(filename,file_url)'}
                response = requests.get(url, headers=self.headers, params=params, timeout=10)
                
                if response.status_code == 200:
                    for pv in response.json():
                        if pv.get('videos'):
                            videos.append(pv['videos'])
            
            logging.info(f"Found {len(videos)} scheduled videos")
            return videos
        except Exception as e:
            logging.error(f"Error getting videos: {e}")
            return []
    
    def download_video(self, video_info):
        try:
            original = video_info['filename']
            sanitized = self.sanitize_filename(original)
            video_path = self.video_dir / sanitized
            
            if video_path.exists():
                logging.info(f"Video exists: {sanitized}")
                return video_path
            
            logging.info(f"Downloading: {original} -> {sanitized}")
            response = requests.get(video_info['file_url'], stream=True, timeout=30)
            
            if response.status_code == 200:
                with open(video_path, 'wb') as f:
                    for chunk in response.iter_content(8192):
                        f.write(chunk)
                logging.info(f"Downloaded: {sanitized} ({video_path.stat().st_size} bytes)")
                return video_path
            
        except Exception as e:
            logging.error(f"Download failed: {e}")
        return None
    
    def sync_videos(self):
        try:
            videos = self.get_scheduled_videos()
            if not videos:
                return
            
            # Download new videos
            current_files = set()
            for video_info in videos:
                result = self.download_video(video_info)
                if result:
                    current_files.add(result.name)
            
            # Remove old videos
            for video_file in self.video_dir.glob('*'):
                if video_file.is_file() and video_file.name not in current_files:
                    logging.info(f"Removing: {video_file.name}")
                    video_file.unlink()
            
            logging.info("Video sync completed")
        except Exception as e:
            logging.error(f"Sync error: {e}")
    
    def start_http_server(self):
        def handler(*args, **kwargs):
            return VideoHandler(*args, video_dir=self.video_dir, **kwargs)
        
        server = HTTPServer(('0.0.0.0', 8000), handler)
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        
        logging.info(f"HTTP server running at http://{self.get_local_ip()}:8000")
        return server
    
    def run(self):
        logging.info("Starting Digital Signage Server...")
        
        self.register_device()
        self.sync_videos()
        http_server = self.start_http_server()
        
        logging.info("Server ready!")
        
        while True:
            try:
                self.register_device()
                self.sync_videos()
                time.sleep(300)  # 5 minutes
            except KeyboardInterrupt:
                break
            except Exception as e:
                logging.error(f"Main loop error: {e}")
                time.sleep(60)

if __name__ == '__main__':
    SignageServer().run()
SERVEREOF

else
    log "Creating client script..."
    
cat > signage.py << 'CLIENTEOF'
#!/usr/bin/env python3
import os, sys, time, logging, subprocess, json, signal, requests
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Dict, List, Any
from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SignageClient:
    def __init__(self):
        load_dotenv()
        self.supabase_url = os.getenv('SUPABASE_URL')
        self.supabase_anon_key = os.getenv('SUPABASE_ANON_KEY')
        self.group_id = os.getenv('GROUP_ID')
        self.device_name = os.getenv('DEVICE_NAME', 'Client')
        self.device_id = os.getenv('DEVICE_ID', 'client-1')
        self.server_ip = os.getenv('SERVER_IP', '192.168.1.16')
        self.video_dir = Path(os.getenv('VIDEO_DIR', './videos'))
        self.video_dir.mkdir(exist_ok=True)
        
        self.headers = {
            'apikey': self.supabase_anon_key,
            'Authorization': f'Bearer {self.supabase_anon_key}',
            'Content-Type': 'application/json'
        }
        
        self.vlc_process = None
        self.playlist = []
        self.current_index = 0
        
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)
        
        logging.info(f"Client initialized: {self.device_name}")
        logging.info(f"Server: {self.server_ip}:8000")
    
    def _shutdown(self, signum, frame):
        logging.info("Shutting down...")
        self.cleanup()
        sys.exit(0)
    
    def cleanup(self):
        if self.vlc_process:
            try:
                self.vlc_process.terminate()
                self.vlc_process.wait(timeout=5)
            except:
                pass
        subprocess.run(['pkill', '-f', 'vlc'], capture_output=True)
    
    def register_device(self):
        try:
            device_data = {
                'device_id': self.device_id,
                'device_name': self.device_name,
                'device_type': 'client',
                'group_id': self.group_id,
                'status': 'online',
                'ip_address': self.server_ip,
                'last_seen': datetime.now(timezone.utc).isoformat()
            }
            
            url = f"{self.supabase_url}/rest/v1/devices"
            params = {'device_id': f'eq.{self.device_id}'}
            
            response = requests.patch(url, headers=self.headers, params=params, json=device_data, timeout=10)
            if response.status_code not in [200, 204]:
                requests.post(url, headers=self.headers, json=device_data, timeout=10)
            
            return True
        except Exception as e:
            logging.error(f"Device registration failed: {e}")
            return False
    
    def check_server(self):
        try:
            response = requests.get(f"http://{self.server_ip}:8000/api/videos", timeout=5)
            return response.status_code == 200
        except:
            return False
    
    def get_server_videos(self):
        try:
            response = requests.get(f"http://{self.server_ip}:8000/api/videos", timeout=10)
            if response.status_code == 200:
                data = response.json()
                videos = data.get('videos', [])
                logging.info(f"Found {len(videos)} videos on server")
                return videos
        except Exception as e:
            logging.error(f"Error getting video list: {e}")
        return []
    
    def download_video(self, video_info):
        try:
            filename = video_info['filename']
            video_path = self.video_dir / filename
            
            if video_path.exists():
                local_size = video_path.stat().st_size
                server_size = video_info.get('size', 0)
                if local_size == server_size:
                    logging.info(f"Video exists: {filename}")
                    return video_path
            
            url = f"http://{self.server_ip}:8000/videos/{filename}"
            logging.info(f"Downloading: {filename}")
            
            response = requests.get(url, stream=True, timeout=30)
            if response.status_code == 200:
                with open(video_path, 'wb') as f:
                    for chunk in response.iter_content(8192):
                        f.write(chunk)
                logging.info(f"Downloaded: {filename} ({video_path.stat().st_size} bytes)")
                return video_path
            else:
                logging.error(f"Download failed: HTTP {response.status_code}")
        except Exception as e:
            logging.error(f"Download error: {e}")
        return None
    
    def sync_videos(self):
        try:
            if not self.check_server():
                logging.warning("Server not available")
                return
            
            server_videos = self.get_server_videos()
            if not server_videos:
                return
            
            # Download videos
            server_files = set()
            for video_info in server_videos:
                result = self.download_video(video_info)
                if result:
                    server_files.add(result.name)
            
            # Remove old videos
            for video_file in self.video_dir.glob('*'):
                if video_file.is_file() and video_file.name not in server_files:
                    logging.info(f"Removing: {video_file.name}")
                    video_file.unlink()
            
            # Update playlist
            self.playlist = [str(f) for f in self.video_dir.glob('*') if f.is_file()]
            logging.info(f"Playlist updated: {len(self.playlist)} videos")
            
        except Exception as e:
            logging.error(f"Sync error: {e}")
    
    def play_video(self, video_path):
        try:
            if self.vlc_process:
                self.vlc_process.terminate()
                self.vlc_process.wait(timeout=3)
            
            logging.info(f"Playing: {Path(video_path).name}")
            
            cmd = [
                'vlc', video_path,
                '--fullscreen',
                '--no-video-title-show',
                '--quiet',
                '--intf', 'dummy',
                '--sub-filter', 'marq',
                '--marq-marquee', datetime.now().strftime('%H:%M'),
                '--marq-position', '6',  # Bottom right
                '--marq-size', '24'
            ]
            
            self.vlc_process = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            logging.error(f"Play error: {e}")
    
    def play_next(self):
        if not self.playlist:
            logging.info("No videos to play")
            return
        
        video_path = self.playlist[self.current_index]
        self.play_video(video_path)
        self.current_index = (self.current_index + 1) % len(self.playlist)
    
    def run(self):
        logging.info("Starting Digital Signage Client...")
        
        self.register_device()
        self.sync_videos()
        self.play_next()
        
        logging.info("Client ready!")
        
        last_sync = 0
        while True:
            try:
                current_time = int(time.time())
                
                # Register every minute
                if current_time % 60 == 0:
                    self.register_device()
                
                # Sync every 5 minutes
                if current_time - last_sync >= 300:
                    self.sync_videos()
                    last_sync = current_time
                
                # Check if video finished
                if self.vlc_process and self.vlc_process.poll() is not None:
                    logging.info("Video finished, playing next...")
                    self.play_next()
                
                time.sleep(30)
                
            except KeyboardInterrupt:
                break
            except Exception as e:
                logging.error(f"Main loop error: {e}")
                time.sleep(30)

if __name__ == '__main__':
    SignageClient().run()
CLIENTEOF

fi

chmod +x signage.py

# Create systemd service
SERVICE_NAME="signage-$DEVICE_TYPE"
log "Creating systemd service: $SERVICE_NAME"

sudo tee "/etc/systemd/system/$SERVICE_NAME.service" > /dev/null << EOF
[Unit]
Description=Digital Signage $DEVICE_TYPE
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$PROJECT_DIR
Environment=PATH=$PROJECT_DIR/venv/bin
ExecStart=$PROJECT_DIR/venv/bin/python signage.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

# Enable service
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME"

# Create videos directory
mkdir -p videos

log "Setup completed!"
echo ""
echo "🎯 DIGITAL SIGNAGE $DEVICE_TYPE READY"
echo "====================================="
echo "Project: $PROJECT_DIR"
echo "Service: $SERVICE_NAME"
echo ""
echo "Commands:"
echo "  Start:  sudo systemctl start $SERVICE_NAME"
echo "  Stop:   sudo systemctl stop $SERVICE_NAME"
echo "  Status: sudo systemctl status $SERVICE_NAME"
echo "  Logs:   sudo journalctl -u $SERVICE_NAME -f"
echo ""

if [[ "$DEVICE_TYPE" == "server" ]]; then
    echo "🖥️  Server will be available at: http://$(hostname -I | awk '{print $1}'):8000"
    echo "   API: /api/videos"
    echo "   Files: /videos/"
else
    echo "📺 Client will connect to: $SERVER_IP:8000"
    echo "   Videos saved to: $PROJECT_DIR/videos"
fi

echo ""
log "Service enabled for auto-start on boot"
log "Run 'sudo systemctl start $SERVICE_NAME' to start now"