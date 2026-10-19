const { chromium } = require('/tmp/nurse-pw/node_modules/playwright-core');
const fs = require('fs');
const crypto = require('crypto');

const url = process.env.DEMO_URL || 'https://u1182794-a468-42b2d7f1.westc.seetacloud.com:8443/demo/';
const output = process.argv[2] || 'artifacts/王阿姨SoulX口型验收.json';
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const diffs = frames => frames.slice(1).map((frame, index) =>
  frame.reduce((sum, value, pixel) => sum + Math.abs(value - frames[index][pixel]), 0) / frame.length);
const mean = values => values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length);

async function mouth(page) {
  return page.locator('#patient-canvas').evaluate(source => {
    const sample = document.createElement('canvas');
    sample.width = 18; sample.height = 14;
    const context = sample.getContext('2d', { willReadFrequently: true });
    context.drawImage(source, 300, 260, 200, 170, 0, 0, 18, 14);
    const data = context.getImageData(0, 0, 18, 14).data;
    const values = [];
    for (let i = 0; i < data.length; i += 4) values.push(Math.round((data[i] + data[i + 1] + data[i + 2]) / 3));
    return values;
  });
}

(async () => {
  const result = { url, errors: [] };
  const browser = await chromium.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
    args: ['--autoplay-policy=no-user-gesture-required'],
  });
  const page = await browser.newPage({ viewport: { width: 1200, height: 900 } });
  page.on('pageerror', error => result.errors.push(error.message));
  try {
    await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
    await page.locator('[data-case="wang_ayi"]').click();
    await page.waitForFunction(() => PatientPlayer.getProvider() === 'soulx' && !document.getElementById('patient-canvas').hidden,
      null, { timeout: 120000 });
    await page.waitForFunction(() => !document.getElementById('message-input').disabled, null, { timeout: 60000 });
    await page.waitForFunction(() => !document.getElementById('speaking-indicator').classList.contains('active'), null, { timeout: 30000 });

    const idle = [];
    const hashes = [];
    for (let i = 0; i < 24; i++) {
      idle.push(await mouth(page));
      const encoded = await page.locator('#patient-canvas').evaluate(canvas => canvas.toDataURL('image/jpeg', 0.5).split(',')[1]);
      hashes.push(crypto.createHash('sha256').update(Buffer.from(encoded, 'base64')).digest('hex'));
      await pause(100);
    }

    await page.locator('#message-input').fill('王阿姨，您的脚现在是什么感觉？');
    const sent = Date.now();
    await page.locator('#message-input').press('Enter');
    await page.waitForFunction(() => document.getElementById('speaking-indicator').classList.contains('active'), null,
      { timeout: 10000, polling: 50 });
    result.audible_start_ms = Date.now() - sent;
    const speaking = [];
    for (let i = 0; i < 30; i++) { speaking.push(await mouth(page)); await pause(100); }
    const audio = await page.evaluate(() => PatientPlayer.getAudioState());
    result.idle_mouth_diff = mean(diffs(idle));
    result.speaking_mouth_diff = mean(diffs(speaking));
    result.unique_idle_frames = new Set(hashes).size;
    result.reply = await page.locator('.message.patient').last().locator('.bubble').innerText();
    result.audio = audio;
    result.assertions = {
      provider_soulx: await page.evaluate(() => PatientPlayer.getProvider()) === 'soulx',
      idle_has_motion: result.unique_idle_frames >= 20,
      mouth_motion_increases: result.speaking_mouth_diff >= result.idle_mouth_diff * 1.2,
      audible_under_4_seconds: result.audible_start_ms <= 4000,
      audio_running: audio.contextState === 'running' && audio.scheduledResponses >= 2,
      no_page_errors: result.errors.length === 0,
    };
    fs.writeFileSync(output, JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result.assertions));
    if (!Object.values(result.assertions).every(Boolean)) process.exitCode = 2;
  } catch (error) {
    result.errors.push(error.stack || error.message);
    fs.writeFileSync(output, JSON.stringify(result, null, 2));
    console.error(error);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
