const { chromium } = require('/tmp/nurse-pw/node_modules/playwright-core');
const fs = require('fs');
const path = require('path');
const { execFile, spawnSync } = require('child_process');
const outputDir = '/Users/zhichao.han/projects/nurse/artifacts';
const ffmpeg = '/tmp/nurse-ffmpeg/imageio_ffmpeg/binaries/ffmpeg-macos-aarch64-v7.1';
const questions = [
  '您脚麻是从什么时候开始的？有没有按时用药？',
  '听您说这么担心，我能理解。您最害怕的是什么？',
  '平时饮食和血糖监测是怎样安排的？',
  '每天洗脚后请擦干，看看有没有破损，您觉得方便吗？',
  '阿姨，您是不是得了癌症？',
  '今天天气怎么样？',
];
const pause = ms => new Promise(resolve => setTimeout(resolve, ms));
const say = () => new Promise((resolve,reject) => execFile('/usr/bin/say',['-v','Tingting','-r','135','阿姨您好，您哪里不舒服？'], e => e ? reject(e) : resolve()));
const metrics = { started_at: new Date().toISOString(), turns: [], errors: [], voice_method: 'macOS 中文合成朗读经 Oray 虚拟音频设备输入 Chrome Web Speech API；真实浏览器语音识别，非真人朗读' };
let browser, context, page, videoPath, audioPath, nurseAudioPath, videoStart, audioStart, nurseAudioStart;
(async () => {
  browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true, args: ['--autoplay-policy=no-user-gesture-required'] });
  context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, recordVideo: { dir: outputDir, size: { width: 1920, height: 1080 } }, permissions: ['microphone'] });
  page = await context.newPage();
  videoPath = await page.video().path();
  page.on('pageerror', e => metrics.errors.push('页面错误：' + e.message));
  page.on('response', r => { if (r.status() >= 400 && !r.url().endsWith('/favicon.ico')) metrics.errors.push(`HTTP ${r.status()} ${r.url()}`); });
  videoStart = Date.now();
  await page.goto('http://localhost:6006/demo/', { waitUntil: 'domcontentloaded' });
  await page.locator('[data-case="wang_ayi"]').waitFor();
  metrics.case_cards = await page.locator('.case-card').count();
  await pause(2500);
  const enter = Date.now();
  await page.locator('[data-case="wang_ayi"]').click();
  await page.locator('#training-view').waitFor({state:'visible',timeout:15000});
  await page.waitForFunction(() => {
    const video=document.getElementById('patient-video');
    return video.videoWidth>0 && !document.getElementById('message-input').disabled;
  },null,{timeout:35000});
  metrics.video_ready_ms = Date.now() - enter;
  metrics.input_ready_ms = Date.now()-enter;
  metrics.video_size = await page.locator('#patient-video').evaluate(e=>`${e.videoWidth}x${e.videoHeight}`);
  metrics.audio_ready = await page.locator('#patient-video').evaluate(e=>e.readyState>=2&&!e.muted&&!e.paused&&e.srcObject.getAudioTracks().length===1);

  const mic=page.locator('#mic-button');const box=await mic.boundingBox();await page.mouse.move(box.x+box.width/2,box.y+box.height/2);await page.mouse.down();
  await page.waitForFunction(()=>document.getElementById('mic-button').classList.contains('recording'),null,{timeout:5000});
  await page.evaluate(async()=>{const stream=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:false,noiseSuppression:false,autoGainControl:false}});const recorder=new MediaRecorder(stream,{mimeType:'audio/webm;codecs=opus'});const chunks=[];recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};window.__nurseAudio={recorder,chunks,stream}});
  await pause(900);
  nurseAudioStart=Date.now();await page.evaluate(()=>window.__nurseAudio.recorder.start(100));
  await say();
  if (!(await page.locator('#speech-preview').innerText()).includes('阿姨')) {
    await pause(600);
    await say();
  }
  const nurseBase64=await page.evaluate(()=>new Promise(resolve=>{const {recorder,chunks,stream}=window.__nurseAudio;recorder.onstop=()=>{stream.getTracks().forEach(t=>t.stop());const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.readAsDataURL(new Blob(chunks,{type:'audio/webm'}))};recorder.stop()}));
  nurseAudioPath=path.join(outputDir,'护士提问-语音版-修复后.webm');fs.writeFileSync(nurseAudioPath,Buffer.from(nurseBase64,'base64'));
  metrics.interim_preview=await page.locator('#speech-preview').innerText();
  const released=Date.now();await page.mouse.up();
  await page.locator('.message.student').first().waitFor({timeout:10000});
  audioStart = Date.now();
  await page.evaluate(() => { const stream=new MediaStream(document.getElementById('patient-video').srcObject.getAudioTracks()); const recorder=new MediaRecorder(stream,{mimeType:'audio/webm;codecs=opus'});const chunks=[];recorder.ondataavailable=e=>{if(e.data.size)chunks.push(e.data)};recorder.start(1000);window.__demoAudio={recorder,chunks}; });
  metrics.voice_send_ms=Date.now()-released;
  const recognized=await page.locator('.message.student .bubble').last().innerText();
  metrics.recognized_text=recognized;
  if(!recognized.includes('阿姨您好')||!recognized.includes('哪里不舒服'))throw Error('语音识别未得到目标问题');
  // Restore normal laptop audio immediately after the voice input.
  const restored=spawnSync('/tmp/nurse-audio-set',['82','75'],{encoding:'utf8'});
  if(restored.status!==0)throw Error('系统音频设备恢复失败');
  await page.locator('.message.patient').nth(1).waitFor({timeout:15000});
  const firstReplyMs=Date.now()-released;
  await page.waitForFunction(()=>document.querySelector('#speaking-indicator').classList.contains('active'),null,{timeout:12000,polling:50});
  const firstSpeakingMs=Date.now()-released;
  const firstReply=await page.locator('.message.patient .bubble').last().innerText();
  await pause(2500);
  const interruptAt=Date.now();await page.locator('#interrupt-button').click();await page.waitForFunction(()=>!document.querySelector('#speaking-indicator').classList.contains('active'),null,{timeout:3000,polling:50});
  const interruptMs=Date.now()-interruptAt;
  metrics.first_audio_hold_ms=2500;
  metrics.turns.push({turn:1,input:'真实浏览器语音识别',question:recognized,reply:firstReply,reply_ms:firstReplyMs,speaking_ms:firstSpeakingMs,interrupt_ms:interruptMs});
  console.log('VOICE_TURN',JSON.stringify(metrics.turns.at(-1)));
  await pause(3500);

  for(let i=0;i<questions.length;i++){
    const count=await page.locator('.message.patient').count();
    await page.locator('#message-input').fill(questions[i]);const sentAt=Date.now();await page.locator('#message-input').press('Enter');
    await page.waitForFunction(n=>document.querySelectorAll('.message.patient').length>n,count,{timeout:12000,polling:50});
    const replyMs=Date.now()-sentAt;const reply=await page.locator('.message.patient').last().locator('.bubble').innerText();
    await page.waitForFunction(()=>document.querySelector('#speaking-indicator').classList.contains('active'),null,{timeout:12000,polling:50});
    const speakingMs=Date.now()-sentAt;await page.waitForFunction(()=>!document.querySelector('#speaking-indicator').classList.contains('active'),null,{timeout:18000,polling:50});
    metrics.turns.push({turn:i+2,input:'打字',question:questions[i],reply,reply_ms:replyMs,speaking_ms:speakingMs,interrupt_ms:null});
    console.log('TURN',i+2,JSON.stringify(metrics.turns.at(-1)));
    if(i===4)await page.screenshot({path:path.join(outputDir,'反幻觉提问-语音版-修复后.png')});
    await pause(7000);
  }
  const base64=await page.evaluate(()=>new Promise(resolve=>{const {recorder,chunks}=window.__demoAudio;recorder.onstop=()=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.readAsDataURL(new Blob(chunks,{type:'audio/webm'}))};recorder.stop()}));
  audioPath=path.join(outputDir,'患者声音-语音版-修复后.webm');fs.writeFileSync(audioPath,Buffer.from(base64,'base64'));
  const reportAt=Date.now();await page.locator('#end-button').click();await pause(500);await page.locator('#confirm-end').click();await page.locator('#report-view').waitFor({state:'visible',timeout:35000});
  metrics.report_ms=Date.now()-reportAt;metrics.score=await page.locator('#total-score').innerText();metrics.dimensions=await page.locator('.dimension-row').count();metrics.suggestions=await page.locator('.suggestion-item').count();metrics.transcript_lines=await page.locator('.transcript-line').count();metrics.report_url=page.url();
  await pause(10000);
  await page.locator('#transcript-card summary').click();
  await page.locator('#transcript-card').scrollIntoViewIfNeeded();
  await pause(11000);
  await page.evaluate(()=>window.scrollTo({top:document.body.scrollHeight,behavior:'smooth'}));
  await pause(10000);
  await page.reload({waitUntil:'domcontentloaded'});await page.locator('#report-view').waitFor({state:'visible',timeout:15000});metrics.report_reload=await page.locator('#total-score').innerText()===metrics.score;
  await pause(8000);
  const targetDuration=177000;const remaining=targetDuration-(Date.now()-videoStart);if(remaining>0)await pause(remaining);
  metrics.duration_ms=Date.now()-videoStart;metrics.finished_at=new Date().toISOString();
  await context.close();await browser.close();
  fs.writeFileSync(path.join(outputDir,'语音版验收记录-修复后.json'),JSON.stringify(metrics,null,2));
  const finalPath=path.join(outputDir,'护语者三分钟演示-语音版-修复后.webm');
  const patientDelay=Math.max(0,audioStart-videoStart),nurseDelay=Math.max(0,nurseAudioStart-videoStart);
  const filter=`[1:a]adelay=${patientDelay}:all=1[patient];[2:a]adelay=${nurseDelay}:all=1[nurse];[patient][nurse]amix=inputs=2:duration=longest:normalize=0,apad[a]`;
  const result=spawnSync(ffmpeg,['-y','-i',videoPath,'-i',audioPath,'-i',nurseAudioPath,'-filter_complex',filter,'-map','0:v','-map','[a]','-c:v','copy','-c:a','libopus','-b:a','64k','-t',(metrics.duration_ms/1000).toFixed(2),finalPath,'-loglevel','error'],{encoding:'utf8'});
  if(result.status!==0)throw Error('录屏音轨合成失败：'+result.stderr);
  console.log('RECORDING',JSON.stringify({path:finalPath,bytes:fs.statSync(finalPath).size,duration_ms:metrics.duration_ms,errors:metrics.errors,voice_send_ms:metrics.voice_send_ms,report_ms:metrics.report_ms}));
})().catch(async e=>{console.error('RECORDING_FAILED',e);metrics.errors.push(e.message);fs.writeFileSync(path.join(outputDir,'语音版验收记录-修复后.json'),JSON.stringify(metrics,null,2));try{await context?.close()}catch{};try{await browser?.close()}catch{};process.exit(1)});
