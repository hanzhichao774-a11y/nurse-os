const { chromium } = require('/tmp/nurse-pw/node_modules/playwright-core');
const fs = require('fs');

const audioPath = process.argv[2] || 'artifacts/source-review/human-reference-8s.wav';
const outputPath = process.argv[3] || 'artifacts/source-review/human-candidate-lipsync.webm';

(async () => {
  const browser = await chromium.launch({
    executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true,
    args: ['--autoplay-policy=no-user-gesture-required'],
  });
  const page = await browser.newPage({ viewport: { width: 1280, height: 720 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://localhost:6006/demo/', { waitUntil: 'domcontentloaded' });

  const sessionId = await page.evaluate(async () => {
    const response = await fetch('/api/demo/session/start', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ case_id: 'wang_ayi' }),
    });
    return (await response.json()).session_id;
  });

  await page.evaluate(async sessionId => {
    document.getElementById('cases-view').hidden = true;
    document.getElementById('training-view').hidden = false;
    await window.PatientPlayer.start({ sessionId, avatarId: 'human_candidate' });
    const video = document.getElementById('patient-video');
    await new Promise(resolve => {
      if (video.videoWidth) return resolve();
      video.addEventListener('playing', resolve, { once: true });
    });
    const recorder = new MediaRecorder(video.srcObject, {
      mimeType: 'video/webm;codecs=vp8,opus', videoBitsPerSecond: 2500000,
    });
    const chunks = [];
    recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
    recorder.start(500);
    window.__candidateQa = { recorder, chunks };
  }, sessionId);

  await page.waitForTimeout(1500);
  const audio = fs.readFileSync(audioPath).toString('base64');
  const upload = await page.evaluate(async ({ sessionId, audio }) => {
    const bytes = Uint8Array.from(atob(audio), char => char.charCodeAt(0));
    const form = new FormData();
    form.append('sessionid', sessionId);
    form.append('file', new Blob([bytes], { type: 'audio/wav' }), 'reference.wav');
    const response = await fetch('/humanaudio', { method: 'POST', body: form });
    return { status: response.status, body: await response.json() };
  }, { sessionId, audio });
  await page.waitForTimeout(11500);

  const media = await page.evaluate(() => new Promise(resolve => {
    const qa = window.__candidateQa;
    qa.recorder.onstop = () => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result.split(',')[1]);
      reader.readAsDataURL(new Blob(qa.chunks, { type: 'video/webm' }));
    };
    qa.recorder.stop();
  }));
  fs.writeFileSync(outputPath, Buffer.from(media, 'base64'));
  const result = await page.evaluate(() => {
    const video = document.getElementById('patient-video');
    const audioTrack = video.srcObject.getAudioTracks()[0];
    const videoTrack = video.srcObject.getVideoTracks()[0];
    return {
      width: video.videoWidth, height: video.videoHeight, muted: video.muted,
      audioTracks: video.srcObject.getAudioTracks().length,
      videoTracks: video.srcObject.getVideoTracks().length,
      audioReadyState: audioTrack?.readyState,
      videoReadyState: videoTrack?.readyState,
    };
  });
  console.log(JSON.stringify({ sessionId, upload, result, errors, outputPath }));
  await page.evaluate(() => window.PatientPlayer.stop());
  await page.waitForTimeout(500);
  await browser.close();
})().catch(error => { console.error(error); process.exit(1); });
