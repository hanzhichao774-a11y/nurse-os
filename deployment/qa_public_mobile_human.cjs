const { webkit } = require('/tmp/nurse-pw/node_modules/playwright-core');
const fs = require('fs');

(async () => {
  const browser = await webkit.launch({ headless: true });
  const context = await browser.newContext({
    viewport: { width: 390, height: 844 },
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1',
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('https://u1182794-a468-42b2d7f1.westc.seetacloud.com:8443/demo/', { waitUntil: 'networkidle' });
  const visibleCases = await page.locator('.case-card.available:visible').count();
  if (visibleCases !== 2) throw new Error(`expected 2 cases, got ${visibleCases}`);
  await page.locator('[data-case="human_candidate"]').click();
  await page.waitForFunction(() => {
    const video = document.getElementById('patient-video');
    return video.videoWidth > 0 && video.readyState >= 2;
  }, null, { timeout: 35000 });
  await page.waitForFunction(() => !document.getElementById('message-input').disabled, null, { timeout: 45000 });
  if (await page.locator('#audio-unlock').isVisible()) await page.locator('#audio-unlock').click();
  await page.waitForTimeout(1000);
  const result = await page.evaluate(() => {
    const video = document.getElementById('patient-video');
    return {
      visibleCases: document.querySelectorAll('.case-card.available').length,
      patient: document.getElementById('brief-name').textContent,
      videoWidth: video.videoWidth,
      videoHeight: video.videoHeight,
      readyState: video.readyState,
      paused: video.paused,
      muted: video.muted,
      mediaUrl: video.currentSrc,
      inputEnabled: !document.getElementById('message-input').disabled,
    };
  });
  result.pageErrors = errors;
  if (!result.mediaUrl.includes('.m3u8') || result.patient.indexOf('林浩') < 0 || !result.inputEnabled || result.paused) {
    throw new Error(`mobile media failed: ${JSON.stringify(result)}`);
  }
  await page.screenshot({ path: 'artifacts/年轻男性病例-公网手机Safari.png', fullPage: true });
  fs.writeFileSync('artifacts/年轻男性病例-公网手机Safari.json', JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
