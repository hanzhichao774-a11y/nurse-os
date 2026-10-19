const { chromium } = require('/tmp/nurse-pw/node_modules/playwright-core');
const fs = require('fs');

const outputPath = 'artifacts/年轻男性病例端到端验收.webm';
const metricsPath = 'artifacts/年轻男性病例端到端验收.json';

(async () => {
  const browser = await chromium.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
    args: ['--autoplay-policy=no-user-gesture-required'],
  });
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await context.newPage();
  const pageErrors = [];
  page.on('pageerror', error => pageErrors.push(error.message));
  await page.goto('http://localhost:6006/demo/', { waitUntil: 'networkidle' });

  const desktopCards = await page.locator('.case-card.available').count();
  if (desktopCards !== 2) throw new Error(`expected 2 available cases, got ${desktopCards}`);
  if (!await page.locator('[data-case="human_candidate"]').isVisible()) throw new Error('young male case is hidden');

  await page.locator('[data-case="human_candidate"]').click();
  await page.waitForFunction(() => !document.getElementById('message-input').disabled, null, { timeout: 90000 });
  await page.waitForFunction(() => {
    const video = document.getElementById('patient-video');
    return video.srcObject instanceof MediaStream && video.videoWidth > 0 &&
      video.srcObject.getAudioTracks().length === 1 && video.srcObject.getVideoTracks().length === 1;
  }, null, { timeout: 60000 });
  const identity = await page.locator('#brief-name').textContent();
  if (!identity.includes('林浩')) throw new Error(`wrong patient identity: ${identity}`);

  await page.evaluate(() => {
    const video = document.getElementById('patient-video');
    const recorder = new MediaRecorder(video.srcObject, {
      mimeType: 'video/webm;codecs=vp8,opus', videoBitsPerSecond: 2500000,
    });
    const chunks = [];
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    recorder.start(500);
    window.__maleQa = { recorder, chunks, recordAt: performance.now() };
    document.getElementById('message-input').addEventListener('keydown', event => {
      if (event.key === 'Enter') window.__maleQa.sendAt = performance.now();
    }, { capture: true, once: true });
  });

  await page.waitForTimeout(1000);
  await page.locator('#message-input').fill('林先生您好，我是护士。请问伤口哪里疼，翻身时会不会加重？');
  await page.locator('#message-input').press('Enter');
  await page.locator('.message.patient').nth(1).waitFor({ timeout: 15000 });
  await page.waitForFunction(() => document.getElementById('speaking-indicator').classList.contains('active'), null, { timeout: 30000 });
  await page.waitForFunction(() => !document.getElementById('speaking-indicator').classList.contains('active'), null, { timeout: 30000 });
  await page.waitForTimeout(1000);

  const recorded = await page.evaluate(() => new Promise(resolve => {
    const qa = window.__maleQa;
    const video = document.getElementById('patient-video');
    qa.recorder.onstop = () => {
      const reader = new FileReader();
      reader.onload = () => resolve({
        media: reader.result.split(',')[1],
        sendOffsetSeconds: (qa.sendAt - qa.recordAt) / 1000,
        videoMuted: video.muted,
        audioTracks: video.srcObject.getAudioTracks().length,
        videoTracks: video.srcObject.getVideoTracks().length,
        width: video.videoWidth,
        height: video.videoHeight,
      });
      reader.readAsDataURL(new Blob(qa.chunks, { type: 'video/webm' }));
    };
    qa.recorder.stop();
  }));
  fs.writeFileSync(outputPath, Buffer.from(recorded.media, 'base64'));
  delete recorded.media;

  await page.locator('#end-button').click();
  await page.locator('#confirm-end').click();
  await page.waitForFunction(() => !document.getElementById('report-view').hidden, null, { timeout: 30000 });
  const reportPatient = await page.locator('#report-patient').textContent();
  const transcriptPatient = await page.locator('.transcript-line.patient strong').first().textContent();
  if (!reportPatient.includes('林浩') || transcriptPatient !== '林先生') {
    throw new Error(`wrong report identity: ${reportPatient} / ${transcriptPatient}`);
  }

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await mobile.goto('http://localhost:6006/demo/', { waitUntil: 'networkidle' });
  const mobileVisible = await mobile.locator('.case-card.available:visible').count();
  if (mobileVisible !== 2) throw new Error(`mobile expected 2 visible cases, got ${mobileVisible}`);

  const metrics = {
    ...recorded,
    desktopAvailableCases: desktopCards,
    mobileVisibleCases: mobileVisible,
    reportPatient,
    transcriptPatient,
    pageErrors,
    outputPath,
  };
  fs.writeFileSync(metricsPath, JSON.stringify(metrics, null, 2));
  console.log(JSON.stringify(metrics, null, 2));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
