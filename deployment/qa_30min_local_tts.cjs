const { chromium } = require('/tmp/nurse-pw/node_modules/playwright-core');
const fs = require('fs');
const { execFileSync } = require('child_process');

const output = 'artifacts/三十分钟稳定性验收-离线语音版.json';
const prompts = [
  '阿姨您好，您哪里不舒服？',
  '这种脚麻从什么时候开始的？',
  '两只脚都麻吗？还会发凉吗？',
  '最近看东西模糊是从什么时候开始的？',
  '您平时用什么药？能说说吗？',
  '血糖监测平时怎么安排？',
  '我听出您很担心，最怕的是什么？',
  '家里有人能陪您吗？',
  '一个人住院，您最需要我们帮什么？',
  '平时吃饭习惯怎样？',
  '您愿意一起讨论饮食上的注意事项吗？',
  '洗脚后检查脚部方便吗？',
  '如果发现脚上有伤口，您会告诉我们吗？',
  '活动的时候有什么顾虑？',
  '住院花费会让您担心吗？',
  '如果我认真听您说，您会觉得好一些吗？',
  '有人跟您说过会截肢，您最怕这一点吗？',
  '阿姨，您是不是得了癌症？',
  '今天天气怎么样？',
  '还有什么担心想告诉我吗？',
];

const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
function processSnapshot() {
  try {
    return execFileSync('/usr/bin/expect', [
      '/tmp/nurse-ssh.exp',
      'ps -eo pid,rss,etime,args | grep -E "python app.py|uvicorn app:app" | grep -v grep',
    ], { encoding: 'utf8', timeout: 12000 }).split('\n').filter(line => /python app.py|uvicorn app:app/.test(line));
  } catch (error) {
    return [`snapshot_error: ${error.message}`];
  }
}

(async () => {
  const result = {
    started_at: new Date().toISOString(),
    version: 'nurselocal speaker 2, Wav2Lip 25 fps, single WebRTC media element',
    turns: [], health: [], process_snapshots: [], errors: [],
  };
  const browser = await chromium.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
    args: ['--autoplay-policy=no-user-gesture-required'],
  });
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 } });
  page.on('pageerror', error => result.errors.push(`page: ${error.message}`));
  page.on('response', response => {
    if (response.status() >= 400 && !response.url().endsWith('/favicon.ico'))
      result.errors.push(`HTTP ${response.status()} ${response.url()}`);
  });
  try {
    await page.goto('http://localhost:6006/demo/');
    const entered = Date.now();
    await page.locator('[data-case="wang_ayi"]').click();
    await page.waitForFunction(() => {
      const video = document.getElementById('patient-video');
      return video.videoWidth > 0 && !document.getElementById('message-input').disabled;
    }, null, { timeout: 35000 });
    result.video_ready_ms = Date.now() - entered;
    const started = Date.now();
    const deadline = started + 1_800_000;
    result.process_snapshots.push({ minute: 0, lines: processSnapshot() });

    for (let index = 0; index < prompts.length; index++) {
      const scheduled = started + index * 90_000;
      if (scheduled > Date.now()) await pause(scheduled - Date.now());
      const previous = await page.locator('.message.patient').count();
      await page.locator('#message-input').fill(prompts[index]);
      const sent = Date.now();
      await page.locator('#message-input').press('Enter');
      await page.waitForFunction(count => document.querySelectorAll('.message.patient').length > count,
        previous, { timeout: 12_000, polling: 50 });
      const replyMs = Date.now() - sent;
      const reply = await page.locator('.message.patient').last().locator('.bubble').innerText();
      await page.waitForFunction(() => document.getElementById('speaking-indicator').classList.contains('active'),
        null, { timeout: 10_000, polling: 50 });
      const speakingMs = Date.now() - sent;
      await page.waitForFunction(() => !document.getElementById('speaking-indicator').classList.contains('active'),
        null, { timeout: 20_000, polling: 50 });
      result.turns.push({ turn: index + 1, question: prompts[index], reply, reply_ms: replyMs, speaking_ms: speakingMs });
      console.log(`TURN ${index + 1} ${speakingMs}ms`);
      if (index % 3 === 0) {
        const state = await page.evaluate(async () => {
          const response = await fetch('/api/demo/health', { cache: 'no-store' });
          const video = document.getElementById('patient-video');
          return {
            http: response.status, video_width: video.videoWidth,
            paused: video.paused, muted: video.muted,
            audio_tracks: video.srcObject?.getAudioTracks().length ?? 0,
          };
        });
        result.health.push({ minute: Math.round((Date.now() - started) / 60_000), ...state });
        result.process_snapshots.push({ minute: Math.round((Date.now() - started) / 60_000), lines: processSnapshot() });
      }
      fs.writeFileSync(output, JSON.stringify(result, null, 2));
    }
    if (deadline > Date.now()) await pause(deadline - Date.now());
    result.process_snapshots.push({ minute: 30, lines: processSnapshot() });
    const reportStarted = Date.now();
    await page.locator('#end-button').click();
    await page.locator('#confirm-end').click();
    await page.locator('#report-view').waitFor({ state: 'visible', timeout: 35_000 });
    result.report_ms = Date.now() - reportStarted;
    result.dimensions = await page.locator('.dimension-row').count();
    result.suggestions = await page.locator('.suggestion-item').count();
    result.transcript_lines = await page.locator('.transcript-line').count();
    result.score = await page.locator('#total-score').innerText();
    result.elapsed_training_ms = Date.now() - started;
    result.finished_at = new Date().toISOString();
    result.max_speaking_ms = Math.max(...result.turns.map(turn => turn.speaking_ms));
    result.all_under_4_seconds = result.turns.every(turn => turn.speaking_ms <= 4000);
    fs.writeFileSync(output, JSON.stringify(result, null, 2));
    console.log('COMPLETE', JSON.stringify({ turns: result.turns.length, elapsed_training_ms: result.elapsed_training_ms,
      max_speaking_ms: result.max_speaking_ms, report_ms: result.report_ms, errors: result.errors.length }));
  } catch (error) {
    result.errors.push(`test: ${error.message}`);
    result.failed_at = new Date().toISOString();
    fs.writeFileSync(output, JSON.stringify(result, null, 2));
    console.error('FAILED', error);
    process.exitCode = 1;
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exit(1); });
