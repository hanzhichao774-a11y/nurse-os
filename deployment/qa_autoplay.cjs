const { chromium } = require('/tmp/nurse-pw/node_modules/playwright-core');

(async () => {
  const browser = await chromium.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  await page.goto('http://localhost:6006/demo/');
  await page.locator('[data-case="wang_ayi"]').click();
  await page.waitForTimeout(11000);
  const result = await page.evaluate(() => {
    const video = document.getElementById('patient-video');
    return {
      paused: video.paused,
      muted: video.muted,
      tracks: video.srcObject?.getTracks().map(track => track.kind),
      unlockVisible: !document.getElementById('audio-unlock').hidden,
      inputEnabled: !document.getElementById('message-input').disabled,
      overlayVisible: !document.getElementById('video-overlay').hidden,
    };
  });
  console.log(result);
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
