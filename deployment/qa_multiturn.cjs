const { chromium } = require('/tmp/nurse-pw/node_modules/playwright-core');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://localhost:6006/demo/');
  await page.locator('[data-case="wang_ayi"]').click();
  await page.waitForFunction(() => !document.getElementById('message-input').disabled, null, { timeout: 35000 });
  const questions = [
    '阿姨您好，我是今天负责您的护士。您哪里不舒服？',
    '这种脚麻从什么时候开始？',
    '我听出您有些担心，您最害怕什么？',
    '我理解您的担心，会陪您慢慢说。您希望我先了解什么？',
  ];
  const turns = [];
  for (let index = 0; index < questions.length; index++) {
    await page.locator('#message-input').fill(questions[index]);
    const sentAt = Date.now();
    await page.locator('#message-input').press('Enter');
    await page.locator('.message.patient').nth(index + 1).waitFor({ timeout: 12000 });
    const replyAt = Date.now();
    await page.waitForFunction(() => document.getElementById('speaking-indicator').classList.contains('active'), null, { timeout: 10000 });
    const speakingAt = Date.now();
    await page.waitForFunction(() => !document.getElementById('speaking-indicator').classList.contains('active'), null, { timeout: 18000 });
    const endedAt = Date.now();
    turns.push({
      question: questions[index],
      reply: await page.locator('.message.patient').nth(index + 1).innerText(),
      replyMs: replyAt - sentAt,
      speakingMs: speakingAt - sentAt,
      speakingDurationMs: endedAt - speakingAt,
    });
  }
  const result = { turns, pageErrors: errors };
  fs.writeFileSync('artifacts/数字人四轮复验.json', JSON.stringify(result, null, 2));
  console.log(JSON.stringify(result, null, 2));
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
