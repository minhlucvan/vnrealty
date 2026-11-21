// Evaluate a bundled extractor against a stub DOM (no elements, body text only) to catch runtime errors.
// Usage: node tests/js/smoke_bundle.js <bundle.js> <url> <bodyTextFile>
const fs = require('fs');
const [bundlePath, url, bodyFile] = process.argv.slice(2);
const u = new URL(url);
const bodyText = bodyFile ? fs.readFileSync(bodyFile, 'utf8') : '';
global.location = { href: u.href, pathname: u.pathname, hostname: u.hostname, origin: u.origin, hash: u.hash };
global.document = {
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
  body: { innerText: bodyText }, title: 'stub',
};
const out = eval(fs.readFileSync(bundlePath, 'utf8'));
process.stdout.write(JSON.stringify(out));
