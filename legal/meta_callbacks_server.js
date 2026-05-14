'use strict';

const http = require('http');
const fs = require('fs');
const path = require('path');
const crypto = require('crypto');

const HOST = process.env.META_CALLBACK_HOST || '127.0.0.1';
const PORT = Number(process.env.META_CALLBACK_PORT || 8789);
const BASE_URL = process.env.META_CALLBACK_BASE_URL || `http://localhost:${PORT}`;
const PRIVACY_FILE = path.join(__dirname, 'privacy.html');

function readBody(req) {
  return new Promise((resolve, reject) => {
    let body = '';
    req.on('data', (chunk) => {
      body += chunk;
      if (body.length > 1024 * 1024) {
        req.destroy();
        reject(new Error('request body too large'));
      }
    });
    req.on('end', () => resolve(body));
    req.on('error', reject);
  });
}

function send(res, status, headers, body) {
  res.writeHead(status, headers);
  res.end(body);
}

function sendJson(res, status, payload) {
  send(res, status, { 'Content-Type': 'application/json; charset=utf-8' }, JSON.stringify(payload));
}

function sendHtml(res, status, html) {
  send(res, status, { 'Content-Type': 'text/html; charset=utf-8' }, html);
}

function parseUrl(req) {
  return new URL(req.url, BASE_URL);
}

function parseForm(body) {
  return Object.fromEntries(new URLSearchParams(body));
}

function codePage(code, error, state) {
  const safeCode = String(code || '');
  const safeError = String(error || '');
  const safeState = String(state || '');
  return `<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Threads OAuth Callback</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 40px; line-height: 1.6; color: #111827; }
    code, input { font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
    input { width: 100%; box-sizing: border-box; padding: 12px; border: 1px solid #cbd5e1; border-radius: 6px; }
    button { margin-top: 12px; padding: 10px 14px; border: 0; border-radius: 6px; background: #155eef; color: white; cursor: pointer; }
    .box { max-width: 780px; }
    .error { color: #b42318; }
  </style>
</head>
<body>
  <main class="box">
    <h1>Threads OAuth Callback</h1>
    ${safeError ? `<p class="error">OAuth error: <code>${safeError}</code></p>` : ''}
    <p>아래 code 값을 복사해서 <code>threads_auth.js</code> 프롬프트에 붙여넣으세요.</p>
    <input id="code" readonly value="${safeCode}">
    <button onclick="navigator.clipboard.writeText(document.getElementById('code').value)">code 복사</button>
    ${safeState ? `<p>state: <code>${safeState}</code></p>` : ''}
  </main>
</body>
</html>`;
}

function handleGet(req, res, url) {
  if (url.pathname === '/' || url.pathname === '/health') {
    return sendJson(res, 200, { status: 'ok', service: 'stockmate-meta-callbacks' });
  }

  if (url.pathname === '/privacy' || url.pathname === '/privacy.html') {
    if (!fs.existsSync(PRIVACY_FILE)) {
      return sendHtml(res, 404, 'privacy.html not found');
    }
    return send(res, 200, { 'Content-Type': 'text/html; charset=utf-8' }, fs.readFileSync(PRIVACY_FILE));
  }

  if (url.pathname === '/auth/threads') {
    return sendHtml(
      res,
      200,
      codePage(url.searchParams.get('code'), url.searchParams.get('error'), url.searchParams.get('state'))
    );
  }

  if (url.pathname.startsWith('/data-deletion/status/')) {
    return sendJson(res, 200, {
      status: 'received',
      confirmation_code: url.pathname.split('/').pop(),
      message: 'StockMate AI received the data deletion request.',
    });
  }

  return sendJson(res, 404, { error: 'not_found' });
}

async function handlePost(req, res, url) {
  const body = await readBody(req);
  const form = req.headers['content-type']?.includes('application/x-www-form-urlencoded')
    ? parseForm(body)
    : {};

  if (url.pathname === '/callbacks/deauthorize') {
    console.log('[meta deauthorize]', {
      at: new Date().toISOString(),
      signed_request: form.signed_request ? '[present]' : '[missing]',
    });
    return sendJson(res, 200, { status: 'ok' });
  }

  if (url.pathname === '/callbacks/data-deletion') {
    const confirmationCode = crypto.randomUUID();
    console.log('[meta data deletion]', {
      at: new Date().toISOString(),
      confirmation_code: confirmationCode,
      signed_request: form.signed_request ? '[present]' : '[missing]',
    });
    return sendJson(res, 200, {
      url: `${BASE_URL}/data-deletion/status/${confirmationCode}`,
      confirmation_code: confirmationCode,
    });
  }

  return sendJson(res, 404, { error: 'not_found' });
}

const server = http.createServer(async (req, res) => {
  try {
    const url = parseUrl(req);
    if (req.method === 'GET') return handleGet(req, res, url);
    if (req.method === 'POST') return handlePost(req, res, url);
    return sendJson(res, 405, { error: 'method_not_allowed' });
  } catch (err) {
    console.error('[meta callbacks error]', err);
    return sendJson(res, 500, { error: 'internal_error', message: err.message });
  }
});

server.listen(PORT, HOST, () => {
  console.log(`Meta callback server listening on ${BASE_URL}`);
  console.log(`Privacy URL:             ${BASE_URL}/privacy.html`);
  console.log(`OAuth redirect URL:      ${BASE_URL}/auth/threads`);
  console.log(`Deauthorize callback:    ${BASE_URL}/callbacks/deauthorize`);
  console.log(`Data deletion callback:  ${BASE_URL}/callbacks/data-deletion`);
});
