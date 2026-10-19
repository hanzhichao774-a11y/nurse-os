const { chromium } = require('/tmp/nurse-pw/node_modules/playwright-core');
const fs = require('fs');
const crypto = require('crypto');

const output = process.argv[2] || 'artifacts/SoulX实时链路验收.json';
const screenshot = process.argv[3] || 'artifacts/SoulX实时链路验收.png';
const baseUrl = process.env.DEMO_URL || 'http://localhost:6006/demo/';
const prompts = [
  '你现在伤口哪里最疼？',
  '这种疼痛从什么时候开始的？',
  '有没有恶心或者想吐？',
  '你现在有发烧或者发冷吗？',
  '你是不是不敢翻身和下床？',
  '你现在最担心的是什么？',
  '家里有人可以陪你吗？',
  '伤口现在有没有渗血或者异常？',
  '医生有没有告诉你怎么活动？',
  '你再详细说说现在最难受的感觉。',
];

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const quantile = (values, q) => {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * q))];
};
const frameDiffs = frames => frames.slice(1).map((frame, i) => {
  const previous = frames[i];
  return frame.reduce((sum, value, index) => sum + Math.abs(value - previous[index]), 0) / frame.length;
});

async function mouthSample(page) {
  return page.evaluate(() => {
    const source = document.getElementById('patient-canvas');
    const sample = document.createElement('canvas');
    sample.width = 16;
    sample.height = 12;
    const context = sample.getContext('2d', { willReadFrequently: true });
    // Reference mouth is near x=256, y=270 on the 512 square source.
    context.drawImage(source, 176, 224, 160, 120, 0, 0, 16, 12);
    const pixels = context.getImageData(0, 0, 16, 12).data;
    const result = [];
    for (let index = 0; index < pixels.length; index += 4) {
      result.push(Math.round((pixels[index] + pixels[index + 1] + pixels[index + 2]) / 3));
    }
    return result;
  });
}

async function canvasHash(page) {
  const encoded = await page.locator('#patient-canvas').evaluate(canvas => canvas.toDataURL('image/jpeg', 0.45).split(',')[1]);
  return crypto.createHash('sha256').update(Buffer.from(encoded, 'base64')).digest('hex');
}

(async () => {
  const result = {
    started_at: new Date().toISOString(),
    url: baseUrl,
    provider: null,
    canvas: null,
    idle: {},
    turns: [],
    interrupt: {},
    report: {},
    errors: [],
  };
  const browser = await chromium.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
    args: ['--autoplay-policy=no-user-gesture-required'],
  });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  page.on('pageerror', error => result.errors.push(`page: ${error.message}`));
  page.on('response', response => {
    if (response.status() >= 400 && !response.url().endsWith('/favicon.ico')) {
      result.errors.push(`HTTP ${response.status()} ${response.url()}`);
    }
  });
  try {
    await page.goto(baseUrl, { waitUntil: 'networkidle' });
    await page.locator('[data-case="human_candidate"]').click();
    await page.waitForFunction(() => {
      const canvas = document.getElementById('patient-canvas');
      return window.PatientPlayer.getProvider() === 'soulx' && !canvas.hidden &&
        canvas.getContext('2d').getImageData(256, 256, 1, 1).data[3] > 0;
    }, null, { timeout: 120000 });
    result.provider = await page.evaluate(() => PatientPlayer.getProvider());
    result.canvas = await page.locator('#patient-canvas').evaluate(canvas => ({ width: canvas.width, height: canvas.height }));
    await page.screenshot({ path: screenshot, fullPage: true });

    await page.waitForFunction(() => document.getElementById('speaking-indicator').classList.contains('active'), null, { timeout: 30000 });
    await page.waitForFunction(() => !document.getElementById('speaking-indicator').classList.contains('active'), null, { timeout: 30000 });
    await page.waitForFunction(() => !document.getElementById('message-input').disabled, null, { timeout: 10000 });

    const idleMouth = [];
    const idleHashes = [];
    const idleStarted = Date.now();
    for (let index = 0; index < 240; index++) {
      idleMouth.push(await mouthSample(page));
      if (index % 4 === 0) idleHashes.push(await canvasHash(page));
      await pause(250);
    }
    const idleDiff = frameDiffs(idleMouth);
    result.idle = {
      observed_seconds: (Date.now() - idleStarted) / 1000,
      frame_hashes: idleHashes.length,
      unique_hashes: new Set(idleHashes).size,
      exact_repeat_count: idleHashes.length - new Set(idleHashes).size,
      mouth_diff_mean: idleDiff.reduce((a, b) => a + b, 0) / Math.max(1, idleDiff.length),
      mouth_diff_p95: quantile(idleDiff, 0.95),
    };

    for (let index = 0; index < prompts.length; index++) {
      const previous = await page.locator('.message.patient').count();
      const audioBefore = await page.evaluate(() => PatientPlayer.getAudioState());
      await page.locator('#message-input').fill(prompts[index]);
      const sent = Date.now();
      await page.locator('#message-input').press('Enter');
      await page.waitForFunction(count => document.querySelectorAll('.message.patient').length > count,
        previous, { timeout: 15000, polling: 50 });
      const replyMs = Date.now() - sent;
      const reply = await page.locator('.message.patient').last().locator('.bubble').innerText();
      await page.waitForFunction(() => document.getElementById('speaking-indicator').classList.contains('active'),
        null, { timeout: 30000, polling: 50 });
      const speakingMs = Date.now() - sent;
      const mouth = [];
      const sampleUntil = Date.now() + 2000;
      while (Date.now() < sampleUntil && await page.locator('#speaking-indicator').evaluate(el => el.classList.contains('active'))) {
        mouth.push(await mouthSample(page));
        await pause(100);
      }
      if (index === prompts.length - 1) {
        const interruptedAt = Date.now();
        await page.locator('#interrupt-button').click();
        await page.waitForFunction(() => !document.getElementById('speaking-indicator').classList.contains('active'), null, { timeout: 3000 });
        result.interrupt = { turn: index + 1, stopped_ms: Date.now() - interruptedAt };
      } else {
        await page.waitForFunction(() => !document.getElementById('speaking-indicator').classList.contains('active'),
          null, { timeout: 30000, polling: 50 });
      }
      const speakingDiff = frameDiffs(mouth);
      const audioAfter = await page.evaluate(() => PatientPlayer.getAudioState());
      result.turns.push({
        turn: index + 1,
        prompt: prompts[index],
        reply,
        text_reply_ms: replyMs,
        audible_start_ms: speakingMs,
        mouth_diff_mean: speakingDiff.reduce((a, b) => a + b, 0) / Math.max(1, speakingDiff.length),
        mouth_samples: mouth.length,
        audio_context: audioAfter.contextState,
        audio_responses_scheduled: audioAfter.scheduledResponses - audioBefore.scheduledResponses,
        audio_seconds_scheduled: Number((audioAfter.scheduledSeconds - audioBefore.scheduledSeconds).toFixed(3)),
      });
      fs.writeFileSync(output, JSON.stringify(result, null, 2));
    }

    await page.locator('#end-button').click();
    await page.locator('#confirm-end').click();
    await page.locator('#report-view').waitFor({ state: 'visible', timeout: 40000 });
    result.report = {
      score: await page.locator('#total-score').innerText(),
      dimensions: await page.locator('.dimension-row').count(),
      transcript_lines: await page.locator('.transcript-line').count(),
    };
    const speakingMouthMean = result.turns.reduce((sum, turn) => sum + turn.mouth_diff_mean, 0) /
      Math.max(1, result.turns.length);
    result.finished_at = new Date().toISOString();
    result.assertions = {
      soulx_selected: result.provider === 'soulx',
      canvas_512: result.canvas.width === 512 && result.canvas.height === 512,
      idle_60_seconds: result.idle.observed_seconds >= 59,
      idle_no_exact_loop: result.idle.exact_repeat_count === 0,
      ten_turns: result.turns.length === 10,
      family_question_selected_family_reply: result.turns[6]?.reply.includes('家里人在外地') === true,
      all_turns_spoke: result.turns.every(turn => turn.mouth_samples > 0),
      all_audible_under_4_seconds: result.turns.every(turn => turn.audible_start_ms <= 4000),
      speaking_mouth_exceeds_idle: speakingMouthMean >= result.idle.mouth_diff_mean * 1.3,
      audio_scheduled_for_every_turn: result.turns.every(turn =>
        turn.audio_context === 'running' && turn.audio_responses_scheduled === 1 && turn.audio_seconds_scheduled > 0),
      interrupt_under_one_second: result.interrupt.stopped_ms <= 1000,
      report_complete: result.report.dimensions === 5 && result.report.transcript_lines >= 21,
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
