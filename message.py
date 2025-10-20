"""
Simple metrics library with web UI.
Usage:
    from metrics import metrics
    metrics.increment("feature.step1")
    metrics.start_server(port=8080)
"""

import json
import sqlite3
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler


class MetricsCollector:
    def __init__(self):
        self.db_path = "metrics.db"
        self.lock = threading.Lock()
        self.init_db()
    
    def init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                timestamp INTEGER NOT NULL,
                count INTEGER DEFAULT 1
            )
        """)
        conn.commit()
        conn.close()
    
    def increment(self, name, count=1):
        timestamp = int(time.time())
        self.lock.acquire()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO metrics (name, timestamp, count) VALUES (?, ?, ?)", 
                      (name, timestamp, count))
        conn.commit()
        conn.close()
        self.lock.release()
    
    def get_names(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT name FROM metrics ORDER BY name")
        names = []
        for row in cursor.fetchall():
            names.append(row[0])
        conn.close()
        return names
    
    def get_data(self, name):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        end_time = int(time.time())
        start_time = end_time - 86400
        cursor.execute("SELECT timestamp, count FROM metrics WHERE name = ? AND timestamp >= ?", 
                      (name, start_time))
        rows = cursor.fetchall()
        conn.close()
        
        buckets = {}
        for timestamp, count in rows:
            bucket = (timestamp // 300) * 300
            if bucket in buckets:
                buckets[bucket] = buckets[bucket] + count
            else:
                buckets[bucket] = count
        
        result = []
        current = (start_time // 300) * 300
        while current <= end_time:
            if current in buckets:
                result.append({"timestamp": current, "count": buckets[current]})
            else:
                result.append({"timestamp": current, "count": 0})
            current = current + 300
        
        return result
    
    def start_server(self, port=8080):
        collector = self
        
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                pass
            
            def do_GET(self):
                if self.path == "/":
                    self.send_response(200)
                    self.send_header("Content-type", "text/html")
                    self.end_headers()
                    self.wfile.write(get_html().encode())
                elif self.path == "/api/names":
                    names = collector.get_names()
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(names).encode())
                elif self.path.startswith("/api/data/"):
                    name = self.path.split("/")[-1]
                    data = collector.get_data(name)
                    self.send_response(200)
                    self.send_header("Content-type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(data).encode())
                else:
                    self.send_error(404)
        
        server = HTTPServer(("0.0.0.0", port), Handler)
        print("Metrics running on port " + str(port))
        thread = threading.Thread(target=server.serve_forever)
        thread.daemon = True
        thread.start()
        return server


def get_html():
    return """
<!DOCTYPE html>
<html>
<head>
    <title>Metrics</title>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js"></script>
    <style>
        body { font-family: Arial; background: #f5f5f5; padding: 20px; }
        h1 { color: #333; }
        select, button { padding: 8px; margin: 5px; font-size: 14px; }
        .box { background: white; padding: 20px; margin: 10px 0; border: 1px solid #ddd; }
        .stats { margin: 10px 0; }
        .stat { display: inline-block; margin-right: 20px; padding: 10px; background: #eee; }
        .stat-label { font-size: 12px; color: #666; }
        .stat-value { font-size: 20px; font-weight: bold; }
    </style>
</head>
<body>
    <h1>Metrics Dashboard</h1>
    <div class="box">
        <select id="name">
            <option value="">Select metric...</option>
        </select>
        <button onclick="refresh()">Refresh</button>
    </div>
    
    <div id="stats" class="stats"></div>
    
    <div class="box">
        <canvas id="chart" width="800" height="400"></canvas>
    </div>
    
    <script>
        var chart = null;
        
        function loadNames() {
            fetch('/api/names').then(function(res) {
                return res.json();
            }).then(function(names) {
                var select = document.getElementById('name');
                select.innerHTML = '<option value="">Select metric...</option>';
                for (var i = 0; i < names.length; i++) {
                    var option = document.createElement('option');
                    option.value = names[i];
                    option.textContent = names[i];
                    select.appendChild(option);
                }
                if (names.length > 0) {
                    select.value = names[0];
                    loadData(names[0]);
                }
            });
        }
        
        function loadData(name) {
            if (!name) return;
            
            fetch('/api/data/' + name).then(function(res) {
                return res.json();
            }).then(function(data) {
                var total = 0;
                var recent = 0;
                var peak = 0;
                
                for (var i = 0; i < data.length; i++) {
                    total = total + data[i].count;
                    if (data[i].count > peak) peak = data[i].count;
                    if (i >= data.length - 12) recent = recent + data[i].count;
                }
                
                document.getElementById('stats').innerHTML = 
                    '<div class="stat"><div class="stat-label">Total (24h)</div><div class="stat-value">' + total + '</div></div>' +
                    '<div class="stat"><div class="stat-label">Last Hour</div><div class="stat-value">' + recent + '</div></div>' +
                    '<div class="stat"><div class="stat-label">Peak</div><div class="stat-value">' + peak + '</div></div>';
                
                var labels = [];
                var values = [];
                for (var i = 0; i < data.length; i++) {
                    var d = new Date(data[i].timestamp * 1000);
                    labels.push(d.getHours() + ':' + ('0' + d.getMinutes()).slice(-2));
                    values.push(data[i].count);
                }
                
                var ctx = document.getElementById('chart').getContext('2d');
                if (chart) chart.destroy();
                
                chart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: name,
                            data: values,
                            borderColor: '#4169e1',
                            backgroundColor: 'rgba(65, 105, 225, 0.1)',
                            fill: true
                        }]
                    },
                    options: {
                        responsive: false,
                        scales: {
                            y: { beginAtZero: true }
                        }
                    }
                });
            });
        }
        
        function refresh() {
            var name = document.getElementById('name').value;
            if (name) loadData(name);
        }
        
        document.getElementById('name').addEventListener('change', function(e) {
            loadData(e.target.value);
        });
        
        loadNames();
    </script>
</body>
</html>
    """


metrics = MetricsCollector()


if __name__ == "__main__":
    metrics.start_server(port=8080)
    while True:
        time.sleep(1)