const { webkit } = require('/tmp/nurse-pw/node_modules/playwright-core');
const fs = require('fs');
const crypto = require('crypto');

const output = process.argv[2] || 'artifacts/SoulX移动Safari十分钟稳定性.json';
const screenshot = process.argv[3] || 'artifacts/SoulX移动Safari十分钟稳定性.png';
const baseUrl = process.env.DEMO_URL || 'http://localhost:6006/demo/';
const durationMs = Number(process.env.SOAK_MS || 600000);
const prompts = [
  '伤口现在疼得厉害吗？',
  '有没有恶心想吐？',
  '你现在最担心什么？',
  '家里有人可以陪你吗？',
];
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));

async function hashCanvas(page) {
  const encoded = await page.locator('#patient-canvas').evaluate(canvas => canvas.toDataURL('image/jpeg', 0.35).split(',')[1]);
  return crypto.createHash('sha256').update(Buffer.from(encoded, 'base64')).digest('hex');
}

(async () => {
  const result = {
    started_at: new Date().toISOString(),
    engine: 'Playwright WebKit with iPhone Safari viewport',
    target_duration_ms: durationMs,
    url: baseUrl,
    samples: [],
    turns: [],
    errors: [],
  };
  const browser = await webkit.launch({ headless: true });
  const context = await browser.newContext({
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
    await page.goto(baseUrl, { waitUntil: 'networkidle' });
    await page.locator('[data-case="human_candidate"]').tap();
    await page.waitForFunction(() => window.PatientPlayer.getProvider() === 'soulx' &&
      !document.getElementById('patient-canvas').hidden, null, { timeout: 120000 });
    await page.waitForFunction(() => !document.getElementById('message-input').disabled, null, { timeout: 60000 });
    const started = Date.now();
    let nextTurn = Math.min(90000, durationMs / 5);
    let turnIndex = 0;
    while (Date.now() - started < durationMs) {
      const elapsed = Date.now() - started;
      const state = await page.evaluate(() => ({
        provider: PatientPlayer.getProvider(),
        canvasHidden: document.getElementById('patient-canvas').hidden,
        overlayHidden: document.getElementById('video-overlay').hidden,
        connection: document.getElementById('connection-badge').textContent.trim(),
        inputDisabled: document.getElementById('message-input').disabled,
        speaking: document.getElementById('speaking-indicator').classList.contains('active'),
      }));
      result.samples.push({ elapsed_ms: elapsed, hash: await hashCanvas(page), ...state });
      if (turnIndex < prompts.length && elapsed >= nextTurn) {
        const previous = await page.locator('.message.patient').count();
        const audioBefore = await page.evaluate(() => PatientPlayer.getAudioState());
        await page.locator('#message-input').fill(prompts[turnIndex]);
        const sent = Date.now();
        await page.locator('#message-input').press('Enter');
        await page.waitForFunction(count => document.querySelectorAll('.message.patient').length > count,
          previous, { timeout: 20000 });
        await page.waitForFunction(() => document.getElementById('speaking-indicator').classList.contains('active'),
          null, { timeout: 30000 });
        const audibleMs = Date.now() - sent;
        await page.waitForFunction(() => !document.getElementById('speaking-indicator').classList.contains('active'),
          null, { timeout: 30000 });
        const audioAfter = await page.evaluate(() => PatientPlayer.getAudioState());
        result.turns.push({
          turn: turnIndex + 1,
          prompt: prompts[turnIndex],
          audible_start_ms: audibleMs,
          audio_context: audioAfter.contextState,
          audio_responses_scheduled: audioAfter.scheduledResponses - audioBefore.scheduledResponses,
          audio_seconds_scheduled: Number((audioAfter.scheduledSeconds - audioBefore.scheduledSeconds).toFixed(3)),
        });
        turnIndex += 1;
        nextTurn += Math.max(90000, durationMs / 5);
      }
      fs.writeFileSync(output, JSON.stringify(result, null, 2));
      await pause(Math.min(30000, Math.max(0, durationMs - (Date.now() - started))));
    }
    await page.screenshot({ path: screenshot, fullPage: true });
    result.finished_at = new Date().toISOString();
    result.elapsed_ms = Date.now() - started;
    result.assertions = {
      completed_duration: result.elapsed_ms >= durationMs,
      soulx_stayed_selected: result.samples.every(item => item.provider === 'soulx'),
      canvas_stayed_visible: result.samples.every(item => !item.canvasHidden && item.overlayHidden),
      connection_stayed_up: result.samples.every(item => item.connection.includes('画面已连接')),
      frames_kept_changing: new Set(result.samples.map(item => item.hash)).size === result.samples.length,
      scheduled_turns_completed: result.turns.length === prompts.length,
      all_audible_under_4_seconds: result.turns.every(turn => turn.audible_start_ms <= 4000),
      audio_scheduled_for_every_turn: result.turns.every(turn =>
        turn.audio_context === 'running' && turn.audio_responses_scheduled === 1 && turn.audio_seconds_scheduled > 0),
      no_runtime_errors: result.errors.length === 0,
    };
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
