// Run with the local Playwright installation used for the deployment checks.
const { chromium } = require('/tmp/nurse-pw/node_modules/playwright-core');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
    args: ['--autoplay-policy=no-user-gesture-required'],
  });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://localhost:6006/demo/');
  await page.locator('[data-case="wang_ayi"]').click();
  await page.waitForFunction(() => !document.getElementById('message-input').disabled, null, { timeout: 35000 });
  await page.waitForFunction(() => {
    const video = document.getElementById('patient-video');
    return video.srcObject instanceof MediaStream && video.videoWidth > 0;
  }, null, { timeout: 35000 });
  await page.evaluate(() => {
    const video = document.getElementById('patient-video');
    const recorder = new MediaRecorder(video.srcObject, { mimeType: 'video/webm;codecs=vp8,opus', videoBitsPerSecond: 2500000 });
    const chunks = [];
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    recorder.start(500);
    window.__qa = { recorder, chunks, recordAt: performance.now() };
    document.getElementById('message-input').addEventListener('keydown', event => {
      if (event.key === 'Enter') window.__qa.sendAt = performance.now();
    }, { capture: true, once: true });
  });
  await page.waitForTimeout(2000);
  await page.locator('#message-input').fill('阿姨您好，我是今天负责您的护士。您哪里不舒服？');
  await page.locator('#message-input').press('Enter');
  await page.locator('.message.patient').nth(1).waitFor({ timeout: 12000 });
  await page.waitForTimeout(14500);
  const result = await page.evaluate(() => new Promise(resolve => {
    const video = document.getElementById('patient-video');
    const qa = window.__qa;
    qa.recorder.onstop = () => {
      const reader = new FileReader();
      reader.onload = () => resolve({
        media: reader.result.split(',')[1],
        sendOffsetSeconds: (qa.sendAt - qa.recordAt) / 1000,
        videoMuted: video.muted,
        videoPaused: video.paused,
        audioTracks: video.srcObject.getAudioTracks().length,
        videoTracks: video.srcObject.getVideoTracks().length,
        unlockVisible: !document.getElementById('audio-unlock').hidden,
      });
      reader.readAsDataURL(new Blob(qa.chunks, { type: 'video/webm' }));
    };
    qa.recorder.stop();
  }));
  fs.writeFileSync('artifacts/数字人同步修复复验.webm', Buffer.from(result.media, 'base64'));
  delete result.media;
  result.pageErrors = errors;
  fs.writeFileSync('artifacts/数字人同步修复复验.json', JSON.stringify(result, null, 2));
  console.log(result);
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
