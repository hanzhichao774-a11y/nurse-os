const { webkit } = require('/tmp/nurse-pw/node_modules/playwright-core');
const fs = require('fs');

const output = process.argv[2] || 'artifacts/SoulX公网HTTPS验收.json';
const screenshot = process.argv[3] || 'artifacts/SoulX公网HTTPS验收.png';
const baseUrl = process.env.DEMO_URL || 'https://u1182794-a468-42b2d7f1.westc.seetacloud.com:8443/demo/';
const caseId = process.env.QA_CASE_ID || 'human_candidate';
const prompt = process.env.QA_PROMPT || '你现在最担心什么？';
const expectedReply = process.env.QA_EXPECTED_REPLY || '最怕一活动伤口会裂';

(async () => {
  const result = { started_at: new Date().toISOString(), url: baseUrl, errors: [] };
  const browser = await webkit.launch({ headless: true });
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 390, height: 844 },
    deviceScaleFactor: 3,
    isMobile: true,
    hasTouch: true,
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/19.0 Mobile/15E148 Safari/604.1',
  });
  const page = await context.newPage();
  page.on('pageerror', error => result.errors.push(`page: ${error.message}`));
  page.on('response', response => {
    if (response.status() >= 400 && !response.url().endsWith('/favicon.ico')) {
      result.errors.push(`HTTP ${response.status()} ${response.url()}`);
    }
  });
  try {
    const openedAt = Date.now();
    await page.goto(baseUrl, { waitUntil: 'networkidle', timeout: 60000 });
    await page.locator(`[data-case="${caseId}"]`).tap();
    await page.waitForFunction(() => window.PatientPlayer.getProvider() === 'soulx' &&
      !document.getElementById('patient-canvas').hidden, null, { timeout: 120000 });
    result.canvas_ready_ms = Date.now() - openedAt;
    await page.waitForFunction(() => !document.getElementById('message-input').disabled, null, { timeout: 60000 });
    const audioBefore = await page.evaluate(() => PatientPlayer.getAudioState());
    const previous = await page.locator('.message.patient').count();
    await page.locator('#message-input').fill(prompt);
    const sentAt = Date.now();
    await page.locator('#message-input').press('Enter');
    await page.waitForFunction(count => document.querySelectorAll('.message.patient').length > count,
      previous, { timeout: 15000, polling: 50 });
    result.text_reply_ms = Date.now() - sentAt;
    result.reply = await page.locator('.message.patient').last().locator('.bubble').innerText();
    await page.waitForFunction(() => document.getElementById('speaking-indicator').classList.contains('active'),
      null, { timeout: 10000, polling: 50 });
    result.audible_start_ms = Date.now() - sentAt;
    await page.waitForFunction(() => !document.getElementById('speaking-indicator').classList.contains('active'),
      null, { timeout: 30000 });
    const audioAfter = await page.evaluate(() => PatientPlayer.getAudioState());
    result.audio = {
      context: audioAfter.contextState,
      responses: audioAfter.scheduledResponses - audioBefore.scheduledResponses,
      seconds: Number((audioAfter.scheduledSeconds - audioBefore.scheduledSeconds).toFixed(3)),
    };
    result.provider = await page.evaluate(() => PatientPlayer.getProvider());
    result.connection = await page.locator('#connection-badge').innerText();
    await page.screenshot({ path: screenshot, fullPage: true });
    result.assertions = {
      soulx_selected: result.provider === 'soulx',
      canvas_ready: result.canvas_ready_ms < 120000,
      response_under_4_seconds: result.audible_start_ms <= 4000,
      audio_running: result.audio.context === 'running' && result.audio.responses === 1 && result.audio.seconds > 0,
      correct_case_reply: result.reply.includes(expectedReply),
      connection_up: result.connection.includes('画面已连接'),
      no_runtime_errors: result.errors.length === 0,
    };
    result.finished_at = new Date().toISOString();
    fs.writeFileSync(output, JSON.stringify(result, null, 2));
    console.log(JSON.stringify(result.assertions));
    if (!Object.values(result.assertions).every(Boolean)) process.exitCode = 2;
  } catch (error) {
    result.errors.push(`test: ${error.stack || error.message}`);
    result.failed_at = new Date().toISOString();
    fs.writeFileSync(output, JSON.stringify(result, null, 2));
    console.error(error);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
