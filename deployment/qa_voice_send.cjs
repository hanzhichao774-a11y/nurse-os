const { chromium } = require('/tmp/nurse-pw/node_modules/playwright-core');
const { execFile } = require('child_process');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 }, permissions: ['microphone'] });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://localhost:6006/demo/');
  await page.locator('[data-case="wang_ayi"]').click();
  await page.locator('#training-view').waitFor({ state: 'visible' });
  await page.waitForFunction(() => document.getElementById('patient-video').videoWidth > 0 && !document.getElementById('message-input').disabled, null, { timeout: 35000 });
  const button = page.locator('#mic-button');
  const box = await button.boundingBox();
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await page.waitForFunction(() => document.getElementById('mic-button').classList.contains('recording'), null, { timeout: 5000 });
  await page.waitForTimeout(500);
  await new Promise((resolve, reject) => execFile('/usr/bin/say', ['-v', 'Tingting', '-r', '135', '阿姨您好，您哪里不舒服？'], error => error ? reject(error) : resolve()));
  const interim = await page.locator('#speech-preview').innerText();
  const releasedAt = Date.now();
  await page.mouse.up();
  await page.locator('.message.student').first().waitFor({ timeout: 10000 });
  const sentAt = Date.now();
  const recognized = await page.locator('.message.student .bubble').last().innerText();
  await page.locator('.message.patient').nth(1).waitFor({ timeout: 12000 });
  const replyAt = Date.now();
  await page.waitForFunction(() => document.getElementById('speaking-indicator').classList.contains('active'), null, { timeout: 10000 });
  const speakingAt = Date.now();
  const result = {
    interim,
    recognized,
    reply: await page.locator('.message.patient .bubble').last().innerText(),
    sendMs: sentAt - releasedAt,
    replyMs: replyAt - releasedAt,
    speakingMs: speakingAt - releasedAt,
    pageErrors: errors,
  };
  fs.writeFileSync('artifacts/语音首轮延迟复验.json', JSON.stringify(result, null, 2));
  console.log(result);
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
