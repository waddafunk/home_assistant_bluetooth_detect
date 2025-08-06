import os
from datetime import datetime
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
import threading
import logging
import time

from dotenv import load_dotenv

load_dotenv()

# Health check configuration
HEALTH_PORT = int(os.getenv("HEALTH_PORT", "8080"))
HEALTH_CHECK_ENABLED = os.getenv("HEALTH_CHECK_ENABLED", "true").lower() == "true"
PHONE_MACS = json.loads(os.getenv("PHONE_MACS"))

logger = logging.getLogger(os.getenv("APP_NAME", "Home assistant bluettoth detector"))

health_status = {
    "status": "starting",
    "last_scan": None,
    "last_success": None,
    "devices_found": [],
    "error_count": 0,
    "ha_connected": False,
    "uptime_start": datetime.now(),
}

class HealthCheckHandler(BaseHTTPRequestHandler):
    """Simple HTTP handler for health checks"""
    
    def log_message(self, format, *args):
        """Suppress default HTTP logging"""
        pass
    
    def do_GET(self):
        """Handle GET requests for health check"""
        global health_status
        
        try:
            if self.path == "/health":
                # Determine overall health
                is_healthy = True  # Start with healthy
                
                # Check various health conditions
                if health_status["status"] != "running":
                    is_healthy = False
                elif health_status["last_scan"] is None:
                    is_healthy = False
                elif (datetime.now() - health_status["last_scan"]).seconds > 30:
                    is_healthy = False
                elif health_status["error_count"] >= 10:
                    is_healthy = False
                
                # Calculate uptime
                uptime = datetime.now() - health_status["uptime_start"]
                
                # Build response
                response = {
                    "healthy": is_healthy,
                    "status": health_status["status"],
                    "last_scan": health_status["last_scan"].isoformat() if health_status["last_scan"] else None,
                    "last_success": health_status["last_success"].isoformat() if health_status["last_success"] else None,
                    "seconds_since_last_scan": (datetime.now() - health_status["last_scan"]).seconds if health_status["last_scan"] else None,
                    "devices_found": health_status["devices_found"],
                    "devices_configured": list(PHONE_MACS.keys()) if PHONE_MACS else [],
                    "error_count": health_status["error_count"],
                    "ha_connected": health_status["ha_connected"],
                    "uptime_seconds": int(uptime.total_seconds())
                }
                
                # Convert to JSON string first
                response_json = json.dumps(response, indent=2)
                response_bytes = response_json.encode('utf-8')
                
                # Send response with proper headers
                self.send_response(200 if is_healthy else 503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response_bytes)))
                self.end_headers()
                self.wfile.write(response_bytes)
                self.wfile.flush()
                
            elif self.path == "/":
                # Simple status page
                html = f"""
                <html>
                <head><title>Bluetooth Detection Service</title></head>
                <body>
                    <h1>Bluetooth Detection Service</h1>
                    <p>Status: {health_status.get("status", "unknown")}</p>
                    <p>Last Scan: {health_status.get("last_scan", "never")}</p>
                    <p>Devices Found: {health_status.get("devices_found", [])}</p>
                    <p>HA Connected: {health_status.get("ha_connected", False)}</p>
                    <p>Error Count: {health_status.get("error_count", 0)}</p>
                    <p><a href="/health">JSON Health Check</a></p>
                </body>
                </html>
                """
                html_bytes = html.encode('utf-8')
                
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.end_headers()
                self.wfile.write(html_bytes)
                self.wfile.flush()
                
            else:
                error_msg = b"Not Found"
                self.send_response(404)
                self.send_header("Content-Type", "text/plain")
                self.send_header("Content-Length", str(len(error_msg)))
                self.end_headers()
                self.wfile.write(error_msg)
                self.wfile.flush()
                
        except Exception as e:
            logger.error(f"Error in health check handler: {e}")
            error_response = f"Internal Server Error: {str(e)}"
            error_bytes = error_response.encode('utf-8')
            self.send_response(500)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(error_bytes)))
            self.end_headers()
            self.wfile.write(error_bytes)
            self.wfile.flush()


def start_health_server():
    """Start the health check HTTP server in a separate thread"""
    if not HEALTH_CHECK_ENABLED:
        logger.info("Health check server disabled")
        return
    
    try:
        server = HTTPServer(("0.0.0.0", HEALTH_PORT), HealthCheckHandler)
        logger.info(f"Health check server started on port {HEALTH_PORT}")
        
        # Test the handler is working
        logger.debug(f"Health status initialized: {health_status}")
        
        # Run server in a daemon thread
        server_thread = threading.Thread(target=server.serve_forever)
        server_thread.daemon = True
        server_thread.start()
        
        # Give it a moment to start
        time.sleep(1)
        logger.info(f"Health check available at http://0.0.0.0:{HEALTH_PORT}/health")
        
    except Exception as e:
        logger.error(f"Failed to start health check server: {e}")
        import traceback
        logger.error(traceback.format_exc())
