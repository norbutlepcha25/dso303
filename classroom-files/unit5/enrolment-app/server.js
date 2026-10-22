// USMS enrolment service: the tiny web app used in the Unit 5 CI/CD demo.
// No dependencies, so `npm ci` is fast and the lockfile stays trivial.
const http = require('node:http');

const VERSION = 'Version 1';

function handler(req, res) {
  if (req.url === '/health') {
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    return res.end('ok');
  }
  if (req.url === '/' || req.url === '/index.html') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    return res.end(`<!doctype html><title>USMS enrolment</title><h1>USMS enrolment</h1><p>${VERSION}</p>`);
  }
  res.writeHead(404, { 'Content-Type': 'text/plain' });
  res.end('not found');
}

if (require.main === module) {
  const port = Number(process.env.PORT) || 8080;
  http.createServer(handler).listen(port, () => console.log(`listening on ${port}`));
}

module.exports = { handler, VERSION };
