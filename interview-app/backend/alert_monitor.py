import time
import json
import os
from collections import defaultdict

LOG_FILE = os.path.join(os.path.dirname(__file__), "logs", "app.log")

class Monitor:
    def __init__(self):
        self.auth_failures = defaultdict(list)
        self.rate_limits = defaultdict(list)
        
    def process_log_line(self, line):
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            return

        event = record.get("security_event")
        if not event:
            return

        timestamp = record.get("timestamp")
        
        if event == "auth_failure":
            ip = record.get("client", "unknown")
            self.auth_failures[ip].append(time.time())
            self._check_auth_alerts(ip)
            
        elif event == "rate_limit_exceeded":
            ip = record.get("client_ip", "unknown")
            self.rate_limits[ip].append(time.time())
            self._check_brute_force_alerts(ip)
            
        elif event == "unusual_ai_usage":
            print(f"[ALERT] Unusual AI Usage detected for user {record.get('user_id')} - Doubt: {record.get('doubt')}")
            
        elif event == "excessive_upload":
            print(f"[ALERT] Excessive upload detected for user {record.get('user_id')} - Size: {record.get('size')} bytes")
            
        elif event == "privilege_escalation":
            print(f"[ALERT] Privilege escalation attempt detected for user {record.get('user_id')} at path {record.get('path')}")
            
    def _check_auth_alerts(self, ip):
        # Clean old records
        now = time.time()
        self.auth_failures[ip] = [t for t in self.auth_failures[ip] if now - t < 60]
        
        if len(self.auth_failures[ip]) >= 3:
            print(f"[ALERT] Repeated failed logins / authorization failures from IP {ip}")
            self.auth_failures[ip] = [] # Reset after alert
            
    def _check_brute_force_alerts(self, ip):
        now = time.time()
        self.rate_limits[ip] = [t for t in self.rate_limits[ip] if now - t < 60]
        
        if len(self.rate_limits[ip]) >= 5:
            print(f"[ALERT] Brute force attack suspected from IP {ip} (Multiple rate limits exceeded)")
            self.rate_limits[ip] = []

def run_monitor():
    if not os.path.exists(LOG_FILE):
        print(f"Log file {LOG_FILE} does not exist.")
        return
            
    monitor = Monitor()
    print(f"Monitoring logs at {LOG_FILE}...")
    
    with open(LOG_FILE, "r") as f:
        for line in f:
            monitor.process_log_line(line)
            
    print("Log processing complete.")

if __name__ == "__main__":
    run_monitor()
