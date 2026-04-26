'use strict';

const http = require('http');

const startTime = Date.now();
let server = null;

function createHandler() {
    return (req, res) => {
        if (req.method !== 'GET') {
            res.writeHead(405, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ error: 'Method Not Allowed' }));
            return;
        }

        if (req.url === '/health') {
            try {
                const now = new Date();
                const kstOffset = '+09:00';
                const pad = (n, len = 2) => String(n).padStart(len, '0');
                const ts =
                    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
                    `T${pad(now.getHours())}:${pad(now.getMinutes())}:${pad(now.getSeconds())}.` +
                    `${pad(now.getMilliseconds(), 3)}${kstOffset}`;

                const body = JSON.stringify({
                    status: 'UP',
                    ts,
                    uptime_s: Math.floor((Date.now() - startTime) / 1000),
                });

                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(body);
            } catch (e) {
                res.writeHead(500, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'DOWN', error: e.message }));
            }
            return;
        }

        res.writeHead(404, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({ error: 'Not Found' }));
    };
}

function start(port) {
    server = http.createServer(createHandler());
    server.listen(port, '0.0.0.0', () => {
        // 로거가 아직 초기화 안 됐을 수 있으므로 직접 사용하지 않음 — index.js에서 호출 후 로그
    });
    server.on('error', (err) => {
        process.stderr.write(JSON.stringify({ level: 'ERROR', module: 'health', msg: err.message }) + '\n');
    });
    return server;
}

function stop() {
    if (server) {
        server.close();
        server = null;
    }
}

module.exports = { start, stop };
