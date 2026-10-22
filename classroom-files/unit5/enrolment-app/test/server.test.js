const test = require('node:test');
const assert = require('node:assert');
const http = require('node:http');
const { handler, VERSION } = require('../server');

function get(server, path) {
  return new Promise((resolve, reject) => {
    const { port } = server.address();
    http.get({ port, path }, (res) => {
      let body = '';
      res.on('data', (chunk) => (body += chunk));
      res.on('end', () => resolve({ status: res.statusCode, body }));
    }).on('error', reject);
  });
}

test('home page shows the release version', async () => {
  const server = http.createServer(handler).listen(0);
  const res = await get(server, '/');
  server.close();
  assert.strictEqual(res.status, 200);
  assert.match(res.body, new RegExp(VERSION));
});

test('health check answers ok', async () => {
  const server = http.createServer(handler).listen(0);
  const res = await get(server, '/health');
  server.close();
  assert.strictEqual(res.status, 200);
  assert.strictEqual(res.body, 'ok');
});
