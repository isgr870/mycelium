const http = require('http');
const fs = require('fs');
const path = require('path');

const PORT = 8910;

const server = http.createServer((req, res) => {
    // Companion Daemon Telemetry API endpoint
    if (req.url === '/api/telemetry') {
        res.writeHead(200, { 'Content-Type': 'application/json', 'Access-Control-Allow-Origin': '*' });
        res.end(JSON.stringify({
            daemon: 'OmniMesh-Native-Daemon',
            version: '12.0.0',
            uptime: process.uptime(),
            memoryUsage: process.memoryUsage(),
            status: 'OPERATIONAL'
        }));
        return;
    }

    let filePath = path.join(__dirname, 'public', req.url === '/' ? 'index.html' : req.url);
    let extname = String(path.extname(filePath)).toLowerCase();
    let mimeTypes = {
        '.html': 'text/html',
        '.js': 'text/javascript',
        '.css': 'text/css',
        '.json': 'application/json'
    };
    let contentType = mimeTypes[extname] || 'application/octet-stream';

    fs.readFile(filePath, (error, content) => {
        if (error) {
            if(error.code == 'ENOENT') {
                res.writeHead(404, { 'Content-Type': 'text/plain' });
                res.end('404 Not Found');
            } else {
                res.writeHead(500);
                res.end('Server Error: '+error.code);
            }
        } else {
            res.writeHead(200, { 'Content-Type': contentType });
            res.end(content, 'utf-8');
        }
    });
});

server.listen(PORT, '0.0.0.0', () => {
    console.log(`[+] Omni-Mesh v12 Server running at http://localhost:${PORT}`);
});
