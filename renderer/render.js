#!/usr/bin/env node
/**
 * HTML 템플릿을 Puppeteer로 렌더링해 PNG bytes를 stdout으로 출력
 *
 * 사용법:
 *   node renderer/render.js '{"template":"basic_2line","title":"제목","sub":"부제"}'
 *
 * 성공 시: PNG bytes → stdout
 * 실패 시: 에러 메시지 → stderr, exit code 1
 */

const puppeteer = require('puppeteer');
const path = require('path');

const CANVAS_W = 1029;
const CANVAS_H = 258;

async function render(params) {
  const qs = new URLSearchParams(params).toString();
  const htmlFile = path.resolve(__dirname, '..', 'templates', 'render.html');

  // Windows: file:///C:/... / Unix: file:///path/...
  const fileUrl = 'file:///' + htmlFile.replace(/\\/g, '/').replace(/^\//, '') + '?' + qs;

  const browser = await puppeteer.launch({
    headless: 'new',
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-dev-shm-usage',
      '--disable-gpu',
      '--single-process',
      '--font-render-hinting=none',
    ],
  });

  try {
    const page = await browser.newPage();
    await page.setViewport({ width: CANVAS_W, height: CANVAS_H, deviceScaleFactor: 1 });

    await page.goto(fileUrl, { waitUntil: 'networkidle0', timeout: 15000 });

    // 커스텀 폰트 로드 완료 대기
    await page.evaluateHandle('document.fonts.ready');

    // 이미지 로드 완료 대기 (image_url 파라미터가 있을 때)
    if (params.image_url) {
      await page.waitForFunction(() => {
        const imgs = document.querySelectorAll('img');
        return [...imgs].every(img => img.complete);
      }, { timeout: 10000 }).catch(() => {});
    }

    const png = await page.screenshot({
      type: 'png',
      clip: { x: 0, y: 0, width: CANVAS_W, height: CANVAS_H },
    });

    process.stdout.write(png);
  } finally {
    await browser.close();
  }
}

const raw = process.argv[2];
if (!raw) {
  process.stderr.write('Usage: node render.js \'{"template":"...","title":"..."}\'\n');
  process.exit(1);
}

let params;
try {
  params = JSON.parse(raw);
} catch {
  process.stderr.write('Invalid JSON: ' + raw + '\n');
  process.exit(1);
}

render(params).catch(err => {
  process.stderr.write(err.stack || err.message);
  process.exit(1);
});
