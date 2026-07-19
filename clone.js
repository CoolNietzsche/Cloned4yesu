const puppeteer = require('puppeteer');
const fs = require('fs');
const path = require('path');
const { URL } = require('url');

const START_URLS = [
  'https://azuris-nextjs.vercel.app/index-creative-agency',
];
const ALLOWED_HOST = 'azuris-nextjs.vercel.app';
const OUT_DIR = path.resolve('./site');
const MAX_PAGES = 60; // safety cap

const visitedPages = new Set();
const queue = [...START_URLS];
const savedAssets = new Set();

function urlToFilePath(urlStr) {
  const u = new URL(urlStr);
  let p = u.pathname;
  if (p.endsWith('/')) p += 'index.html';
  if (!path.extname(p)) p += '/index.html'; // page routes -> index.html in folder
  // keep query string as part of filename for things like _next/image?url=...
  if (u.search) {
    const safeQuery = Buffer.from(u.search).toString('base64url').slice(0, 40);
    const ext = path.extname(p) || '';
    p = p.replace(ext, '') + '__' + safeQuery + ext;
  }
  return path.join(OUT_DIR, u.host, p);
}

function saveBuffer(urlStr, buffer) {
  try {
    const filePath = urlToFilePath(urlStr);
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, buffer);
  } catch (e) {
    console.error('save fail', urlStr, e.message);
  }
}

(async () => {
  const browser = await puppeteer.launch({
    headless: 'new',
    args: ['--no-sandbox', '--disable-setuid-sandbox'],
  });

  while (queue.length && visitedPages.size < MAX_PAGES) {
    const url = queue.shift();
    if (visitedPages.has(url)) continue;
    visitedPages.add(url);

    console.log('Visiting:', url);
    const page = await browser.newPage();
    await page.setViewport({ width: 1440, height: 900 });

    // Capture every asset response
    page.on('response', async (response) => {
      try {
        const respUrl = response.url();
        const host = new URL(respUrl).host;
        if (host !== ALLOWED_HOST) return; // skip 3rd-party (fonts CDNs etc handled separately below)
        if (savedAssets.has(respUrl)) return;
        const status = response.status();
        if (status >= 300) return;
        const buffer = await response.buffer().catch(() => null);
        if (!buffer) return;
        savedAssets.add(respUrl);
        saveBuffer(respUrl, buffer);
      } catch (e) {
        // ignore individual asset failures
      }
    });

    try {
      await page.goto(url, { waitUntil: 'networkidle0', timeout: 60000 });
      // Let lazy-loaded/animated content settle
      await page.evaluate(async () => {
        window.scrollTo(0, document.body.scrollHeight);
        await new Promise((r) => setTimeout(r, 1500));
        window.scrollTo(0, 0);
      });
      await new Promise((r) => setTimeout(r, 1000));

      // Save fully rendered HTML
      const html = await page.content();
      saveBuffer(url, Buffer.from(html, 'utf-8'));

      // Collect same-host links for crawling
      const links = await page.$$eval('a[href]', (as) => as.map((a) => a.href));
      for (const link of links) {
        try {
          const u = new URL(link);
          if (
            u.host === ALLOWED_HOST &&
            !u.pathname.match(/\.(pdf|zip|jpg|png|webp|mp4)$/i) &&
            !visitedPages.has(link) &&
            !queue.includes(link)
          ) {
            queue.push(link);
          }
        } catch {}
      }
    } catch (e) {
      console.error('Failed to load', url, e.message);
    }

    await page.close();
  }

  await browser.close();
  console.log(`Done. Pages: ${visitedPages.size}, Assets: ${savedAssets.size}`);
  console.log('Output at', OUT_DIR);
})();
