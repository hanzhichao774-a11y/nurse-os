(() => {
  const API = '/api/demo';
  const $ = id => document.getElementById(id);
  const views = { cases: $('cases-view'), training: $('training-view'), report: $('report-view') };
  const state = { case: null, sessionId: null, avatarProvider: 'livetalking', startedAt: 0, timer: null, speakingPoll: null, speakingEvents: null, lastSpeakingEventAt: 0, warmTimeout: null, busy: false, ready: false, videoReady: false, greeted: false, greetingMessageReceived: false, greetingStarted: false, greetingFinished: false, micHeld: false, turn: 0, recognition: null, speechText: '', sendSpeech: false };
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  const patientLabel = () => state.case?.display_name || '患者';
  const patientAvatar = () => state.case?.name?.slice(0, 1) || '患';

  function escapeHtml(value) {
    return String(value ?? '').replace(/[&<>"']/g, char => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[char]);
  }
  function showView(name) { Object.entries(views).forEach(([key, node]) => { node.hidden = key !== name; }); window.scrollTo(0, 0); }
  function showLoading(title, description) { $('loading-title').textContent = title; $('loading-text').textContent = description; $('loading-layer').hidden = false; }
  function hideLoading() { $('loading-layer').hidden = true; }
  let toastTimer;
  function toast(message) { const el = $('toast'); el.textContent = message; el.hidden = false; clearTimeout(toastTimer); toastTimer = setTimeout(() => el.hidden = true, 4500); }
  async function request(path, options = {}) {
    let response;
    try { response = await fetch(API + path, { ...options, headers: { 'Content-Type': 'application/json', ...(options.headers || {}) } }); }
    catch { throw new Error('网络连接暂时不可用，请稍后再试'); }
    let data;
    try { data = await response.json(); } catch { throw new Error('服务响应异常，请稍后再试'); }
    if (!response.ok) throw new Error(data.error || '操作未完成，请稍后再试');
    return data;
  }
  function post(path, body) { return request(path, { method: 'POST', body: JSON.stringify(body) }); }

  async function loadCases() {
    showView('cases');
    try {
      const { cases } = await request('/cases');
      const caseGrid = $('case-grid');
      const availableCount = cases.filter(item => item.available).length;
      $('case-count').textContent = `共 ${cases.length} 个病例 · 当前开放 ${availableCount} 个`;
      caseGrid.innerHTML = cases.map((item, index) => {
        const tags = item.tags.map(tag => `<span>${escapeHtml(tag)}</span>`).join('');
        if (!item.available) {
          return `<article class="case-card unavailable" aria-disabled="true"><div class="upcoming-image"><span class="upcoming-chip">敬请期待</span><svg viewBox="0 0 80 80" fill="none" aria-hidden="true"><circle cx="40" cy="27" r="13" fill="currentColor" opacity=".55"/><path d="M17 66c0-14 10-23 23-23s23 9 23 23" stroke="currentColor" stroke-width="8" stroke-linecap="round" opacity=".55"/></svg></div><div class="case-body"><div class="case-upper"><div><h3>${escapeHtml(item.display_name)}</h3><small>${escapeHtml(item.name)} · ${item.age} 岁</small></div><div class="difficulty"><strong>${'★'.repeat(item.difficulty)}</strong>进阶难度</div></div><div class="case-tags">${tags}</div><div class="case-action"><span>病例即将开放</span><b>↗</b></div></div></article>`;
        }
        return `<article class="case-card available" data-case="${escapeHtml(item.case_id)}" role="button" tabindex="0" aria-label="开始${escapeHtml(item.display_name)}病例实训"><div class="case-image"><img src="${escapeHtml(item.poster)}" alt="${escapeHtml(item.poster_alt || item.display_name)}"><div class="image-label"><span class="live-dot"></span> 可进入实训 · 实时数字人</div></div><div class="case-body"><div class="case-upper"><div><h3>${escapeHtml(item.display_name)}</h3><small>${escapeHtml(item.name)} · ${item.age} 岁</small></div><div class="difficulty"><strong>${'★'.repeat(item.difficulty)}${'☆'.repeat(5-item.difficulty)}</strong>沟通训练难度</div></div><div class="case-tags">${tags}</div><div class="case-action"><span>进入实训，与${escapeHtml(item.display_name)}对话</span><b>→</b></div></div></article>`;
      }).join('');
      caseGrid.querySelectorAll('[data-case]').forEach(card => {
        const item = cases.find(x => x.case_id === card.dataset.case);
        card.addEventListener('click', () => begin(item));
        card.addEventListener('keydown', event => { if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); begin(item); } });
      });
    } catch (error) {
      $('case-grid').innerHTML = `<div class="case-error">病例加载失败。<button type="button" id="case-retry">重试</button></div>`;
      $('case-retry').addEventListener('click', loadCases);
      toast(error.message);
    }
  }

  async function begin(item) {
    if (!item || state.sessionId) return;
    PatientPlayer.prepare?.();
    showLoading('正在唤醒患者…', `为你准备${item.display_name}的病房与沟通场景`);
    try {
      const { session_id, avatar_provider } = await post('/session/start', { case_id: item.case_id });
      state.case = item;
      state.sessionId = session_id;
      state.avatarProvider = avatar_provider || item.avatar_provider || 'livetalking';
      state.startedAt = Date.now();
      state.turn = 0;
      state.ready = false;
      state.videoReady = false;
      state.greeted = false;
      state.greetingMessageReceived = false;
      state.greetingStarted = false;
      state.greetingFinished = false;
      state.lastSpeakingEventAt = 0;
      $('message-input').disabled = true;
      $('send-button').disabled = true;
      $('mic-button').disabled = true;
      $('turn-count').textContent = '第 0 轮';
      $('training-title').textContent = `与${item.display_name}沟通实训`;
      $('brief-avatar').textContent = item.name.slice(0, 1);
      $('brief-name').textContent = `${item.name} · ${item.age} 岁`;
      $('brief-context').textContent = item.care_context || '住院患者 / 标准化病人';
      $('brief-text').textContent = item.brief;
      $('brief-goals').textContent = item.goals.join(' · ');
      $('video-poster').src = item.poster;
      $('video-poster').alt = item.poster_alt || item.display_name;
      $('message-input').placeholder = `输入你想对${item.display_name}说的话…`;
      $('message-input').setAttribute('aria-label', `对${item.display_name}说的话`);
      $('chat-messages').innerHTML = `<div class="chat-empty" id="chat-empty"><div class="empty-icon"><svg viewBox="0 0 24 24" fill="none" aria-hidden="true"><path d="M4 5.5h16v11H9l-5 3v-14Z" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/><path d="M8 10h8m-8 3h5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/></svg></div><strong>一次真诚的问候，是沟通的开始</strong><p>请向${escapeHtml(item.display_name)}介绍自己，并询问目前的不适与担忧。</p></div>`;
      $('connection-badge').classList.remove('connected');
      $('connection-badge').innerHTML = '<span></span> 正在连接';
      $('video-overlay').hidden = false;
      $('video-overlay').querySelector('.video-orbit').hidden = false;
      $('video-overlay').querySelector('strong').textContent = '正在唤醒患者…';
      $('video-overlay').querySelector('small').textContent = '数字人画面连接中，请稍候';
      $('video-poster').hidden = false;
      $('audio-unlock').hidden = true;
      $('audio-unlock').textContent = '点击开启患者声音';
      $('interrupt-button').disabled = true;
      showView('training');
      hideLoading();
      clearInterval(state.timer);
      state.timer = setInterval(updateTimer, 1000);
      updateTimer();
      if (state.avatarProvider === 'livetalking') state.speakingPoll = setInterval(pollSpeaking, 200);
      state.warmTimeout = setTimeout(() => {
        if (!state.ready && state.videoReady) {
          toast(`${patientLabel()}开场稍慢，可以先开始交流`);
          state.greetingMessageReceived = true;
          activateInput();
        }
      }, 35000);
      await PatientPlayer.start({
        sessionId: session_id,
        avatarId: item.case_id,
        provider: state.avatarProvider,
        onSessionCreated: () => {
          if (state.avatarProvider === 'livetalking') startSpeakingEvents(session_id);
          greetOnce();
        },
        onConnected: () => { $('connection-badge').classList.add('connected'); $('connection-badge').innerHTML = '<span></span> 画面已连接'; },
        onReady: () => readyForTraining(),
        onSpeaking: speaking => applySpeaking(speaking),
        onAudioError: () => { applySpeaking(false); toast('患者声音暂时生成失败，请稍后重试'); },
        onAudioBlocked: () => { $('audio-unlock').hidden = false; },
        onDisconnected: () => {
          state.speakingEvents?.close();
          $('connection-badge').classList.remove('connected');
          $('connection-badge').innerHTML = '<span></span> 连接中断';
          $('video-overlay').hidden = false;
          $('video-overlay').querySelector('.video-orbit').hidden = true;
          $('video-overlay').querySelector('strong').textContent = '患者画面连接中断';
          $('video-overlay').querySelector('small').textContent = '请刷新页面后重新进入实训';
          toast('患者画面连接中断，请刷新页面重试');
        },
      });
    } catch (error) {
      state.speakingEvents?.close();
      clearInterval(state.timer);
      clearInterval(state.speakingPoll);
      clearTimeout(state.warmTimeout);
      PatientPlayer.stop();
      state.sessionId = null;
      hideLoading();
      $('video-overlay').hidden = true;
      $('connection-badge').innerHTML = '<span></span> 连接失败';
      showView('cases');
      toast(error.message === '媒体连接失败' ? '数字人画面连接失败，请重新进入实训' : error.message);
    }
  }

  async function readyForTraining() {
    if (state.videoReady) return;
    state.videoReady = true;
    $('video-overlay').hidden = true;
    $('video-poster').hidden = true;
    $('chat-status').textContent = `${patientLabel()}正在准备开场…`;
    if (state.greetingFinished && state.greetingMessageReceived) activateInput();
  }

  function activateInput() {
    if (state.ready || !state.videoReady || !state.greetingMessageReceived) return;
    state.ready = true;
    clearTimeout(state.warmTimeout);
    $('message-input').disabled = false;
    $('send-button').disabled = false;
    $('mic-button').disabled = !SpeechRecognition;
    $('chat-status').textContent = '可以开始交流';
    $('message-input').focus();
  }

  async function greetOnce() {
    if (state.greeted || !state.sessionId) return;
    state.greeted = true;
    try {
      const greeting = await post('/session/greet', { session_id: state.sessionId });
      addMessage('patient', greeting.reply, greeting.emotion, 0);
      state.greetingMessageReceived = true;
      if (!greeting.avatar_played) { toast('患者声音暂时未播放，文字对话仍可继续'); state.greetingFinished = true; activateInput(); }
      else if (state.greetingFinished) activateInput();
    } catch { toast('开场白暂未播放，可以直接开始沟通'); state.greetingMessageReceived = true; state.greetingFinished = true; activateInput(); }
  }

  function updateTimer() {
    const elapsed = Math.floor((Date.now() - state.startedAt) / 1000);
    $('session-timer').textContent = `${String(Math.floor(elapsed / 60)).padStart(2, '0')}:${String(elapsed % 60).padStart(2, '0')}`;
  }
  function applySpeaking(speaking) {
    if (speaking && !state.greetingFinished) state.greetingStarted = true;
    if (!speaking && state.greetingStarted && !state.greetingFinished) {
      state.greetingFinished = true;
      activateInput();
    }
    $('speaking-indicator').classList.toggle('active', speaking);
    $('speaking-label').textContent = speaking ? `${patientLabel()}说话中…` : state.ready ? '等待对话' : '患者准备中…';
    $('interrupt-button').disabled = !speaking;
  }
  function startSpeakingEvents(sessionId) {
    if (!window.EventSource) return;
    state.speakingEvents?.close();
    const source = new EventSource('/sse?sessionid=' + encodeURIComponent(sessionId));
    state.speakingEvents = source;
    source.onmessage = event => {
      try {
        const status = JSON.parse(event.data).status;
        state.lastSpeakingEventAt = Date.now();
        if (status === 'start') applySpeaking(true);
        if (status === 'end') applySpeaking(false);
        if (status === 'error') { applySpeaking(false); toast('患者声音暂时生成失败，请稍后重试'); }
      } catch { /* /is_speaking 轮询仍会更新状态 */ }
    };
  }
  async function pollSpeaking() {
    if (!state.sessionId) return;
    const requestedAt = Date.now();
    try {
      const response = await fetch('/is_speaking', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ sessionid: state.sessionId }) });
      const data = await response.json();
      if (data.code !== 0) return;
      if (requestedAt < state.lastSpeakingEventAt) return;
      applySpeaking(Boolean(data.data));
    } catch { /* 查询状态失败不会打断实训 */ }
  }
  async function interrupt() {
    if (!state.sessionId) return;
    try {
      if (!await PatientPlayer.interrupt()) throw new Error();
      $('speaking-indicator').classList.remove('active');
      $('speaking-label').textContent = `已打断${patientLabel()}的发言`;
      $('interrupt-button').disabled = true;
      if (!state.greetingFinished) { state.greetingFinished = true; activateInput(); }
      toast('已打断，可以继续提问');
    } catch { toast('打断未成功，请再试一次'); }
  }

  function addMessage(role, text, emotion, turn, pending = false) {
    $('chat-empty')?.remove();
    const el = document.createElement('div');
    el.className = 'message ' + role + (pending ? ' pending' : '');
    const emotionClass = { '平静': 'calm', '抗拒': 'resist', '感激': 'grateful' }[emotion] || '';
    el.innerHTML = `${role === 'patient' ? `<div class="message-avatar">${escapeHtml(patientAvatar())}</div>` : ''}<div class="message-body"><div class="message-head"><span>${role === 'patient' ? escapeHtml(patientLabel()) : '你'} · ${turn === 0 ? '开场' : `第 ${turn} 轮`}</span>${role === 'patient' && emotion ? `<span class="emotion-tag ${emotionClass}">${escapeHtml(emotion)}</span>` : ''}</div><div class="bubble"></div></div>`;
    el.querySelector('.bubble').textContent = text;
    $('chat-messages').appendChild(el);
    $('chat-messages').scrollTop = $('chat-messages').scrollHeight;
    return el;
  }
  async function sendMessage(value) {
    const text = String(value ?? $('message-input').value).trim();
    if (!text || state.busy) return;
    if (!state.ready) { toast('患者画面正在连接，请稍候再说话'); return; }
    state.busy = true;
    $('send-button').disabled = true;
    $('message-input').value = '';
    const turn = state.turn + 1;
    const bubble = addMessage('student', text, null, turn, true);
    $('chat-status').textContent = `${patientLabel()}正在回应…`;
    try {
      const result = await post('/chat', { session_id: state.sessionId, text });
      bubble.classList.remove('pending');
      state.turn = result.turn;
      $('turn-count').textContent = `第 ${state.turn} 轮`;
      addMessage('patient', result.reply, result.emotion, result.turn);
      $('chat-status').textContent = '可以继续交流';
      if (!result.avatar_played) toast('患者声音暂时未播放，文字对话仍可继续');
    } catch (error) {
      bubble.remove();
      $('message-input').value = text;
      $('chat-status').textContent = '发送未完成';
      toast(error.message);
    } finally {
      state.busy = false;
      $('send-button').disabled = false;
      $('message-input').focus();
    }
  }

  function setupSpeech() {
    if (!SpeechRecognition) {
      $('mic-button').disabled = true;
      $('mic-button').title = '当前浏览器不支持语音识别';
      $('input-hint').textContent = '麦克风不可用，请输入文字后按 Enter 发送';
      toast('当前浏览器不支持语音识别，已切换为打字输入');
      return;
    }
    const button = $('mic-button');
    const submitSpeech = () => {
      if (!state.sendSpeech || !state.speechText) return false;
      const recognized = state.speechText;
      state.speechText = '';
      state.sendSpeech = false;
      sendMessage(recognized);
      return true;
    };
    button.addEventListener('pointerdown', event => {
      if (!state.ready || state.busy) { toast('请等待患者画面连接完成'); return; }
      event.preventDefault();
      button.setPointerCapture(event.pointerId);
      state.speechText = '';
      state.sendSpeech = false;
      state.micHeld = true;
      const recognition = new SpeechRecognition();
      state.recognition = recognition;
      recognition.lang = 'zh-CN';
      recognition.continuous = true;
      recognition.interimResults = true;
      recognition.onresult = resultEvent => {
        let finalText = '', interimText = '';
        for (let i = 0; i < resultEvent.results.length; i++) {
          const segment = resultEvent.results[i][0]?.transcript || '';
          if (resultEvent.results[i].isFinal) finalText += segment;
          else interimText += segment;
        }
        const recognized = (finalText + interimText).trim();
        if (recognized) state.speechText = recognized;
        $('speech-preview').hidden = false;
        $('speech-preview').textContent = '识别中：' + state.speechText;
        if (!state.micHeld && finalText.trim()) {
          state.speechText = finalText.trim();
          submitSpeech();
        }
      };
      recognition.onerror = event => {
        if (event.error === 'not-allowed' || event.error === 'audio-capture') {
          button.disabled = true;
          $('input-hint').textContent = '麦克风不可用，请输入文字后按 Enter 发送';
          toast('麦克风不可用，已切换为打字输入');
        } else if (event.error !== 'no-speech' && event.error !== 'aborted') toast('语音识别未完成，请改用打字输入');
      };
      recognition.onend = () => {
        button.classList.remove('recording');
        button.querySelector('span').textContent = '按住说话';
        $('speech-preview').hidden = true;
        if (!state.micHeld) submitSpeech();
        state.recognition = null;
      };
      try { recognition.start(); button.classList.add('recording'); button.querySelector('span').textContent = '松开发送'; }
      catch { toast('语音识别未启动，请改用打字输入'); }
    });
    const release = () => {
      if (!state.micHeld) return;
      state.micHeld = false;
      state.sendSpeech = true;
      if (state.recognition) {
        try { state.recognition.stop(); } catch { /* 识别器可能已自动停止 */ }
      }
      setTimeout(() => {
        if (submitSpeech()) return;
        if (state.sendSpeech) {
          state.sendSpeech = false;
          toast('没有识别到语音，请改用打字输入');
        }
      }, 1200);
    };
    button.addEventListener('pointerup', release);
    button.addEventListener('pointercancel', release);
    button.addEventListener('lostpointercapture', release);
  }

  function showEndModal() { if (state.busy) { toast(`请等${patientLabel()}回答后再结束实训`); return; } $('end-modal').hidden = false; }
  async function finish() {
    $('end-modal').hidden = true;
    if (!state.sessionId) return;
    clearInterval(state.timer);
    clearInterval(state.speakingPoll);
    state.speakingEvents?.close();
    clearTimeout(state.warmTimeout);
    showLoading('AI 教师正在批改…', '正在回看本场对话，生成五维能力报告');
    try {
      const { report } = await post('/session/end', { session_id: state.sessionId });
      PatientPlayer.stop();
      state.ready = false;
      renderReport(report);
      history.pushState({}, '', `/demo/index.html?view=report&session_id=${encodeURIComponent(state.sessionId)}`);
      showView('report');
    } catch (error) {
      toast(error.message);
      state.timer = setInterval(updateTimer, 1000);
      if (state.avatarProvider === 'livetalking') {
        state.speakingPoll = setInterval(pollSpeaking, 200);
        startSpeakingEvents(state.sessionId);
      }
    }
    finally { hideLoading(); }
  }
  function renderReport(report) {
    const reportCase = report.case || state.case || { name: '王秀兰', display_name: '王阿姨', age: 68, report_subtitle: '糖尿病足风险沟通 · 焦虑型' };
    state.case = { ...(state.case || {}), ...reportCase };
    $('report-patient').textContent = `${reportCase.name} · ${reportCase.age} 岁`;
    $('report-subtitle').textContent = reportCase.report_subtitle || '标准化病人沟通实训';
    $('total-score').textContent = report.total_score;
    $('score-comment').textContent = report.total_score >= 85 ? '你已展现出良好的倾听与回应能力，继续保持。' : report.total_score >= 60 ? '你已迈出重要一步，下一次试着更深入地理解患者。' : '沟通能力在练习中成长，建议结合下方反馈再次实训。';
    $('report-time').textContent = new Date(report.created_at).toLocaleString('zh-CN', { hour12: false });
    $('report-turns').textContent = `共 ${report.transcript.filter(item => item.role === 'student').length} 轮沟通`;
    $('dimension-list').innerHTML = report.dimensions.map(item => `<div class="dimension-row"><div class="dimension-name">${escapeHtml(item.name)}</div><div class="score-track"><div class="score-fill" style="width:${Math.max(0, Math.min(100, item.score / item.weight * 100))}%"></div></div><div class="dimension-score">${item.score}<small>/${item.weight}</small></div></div><p class="dimension-comment">${escapeHtml(item.comment)}</p>`).join('');
    $('suggestion-list').innerHTML = report.suggestions.map((item, i) => `<div class="suggestion-item"><span>${String(i + 1).padStart(2, '0')}</span><div>${escapeHtml(item)}</div></div>`).join('');
    $('report-transcript').innerHTML = report.transcript.map(item => `<div class="transcript-line ${item.role}"><span>${item.turn === 0 ? '开场' : `第${item.turn}轮`}</span><strong>${item.role === 'student' ? '学生' : escapeHtml(reportCase.display_name || reportCase.name || '患者')}</strong><p>${escapeHtml(item.text)}</p></div>`).join('');
  }
  async function openReport(sessionId) {
    showLoading('正在打开评分报告', '读取本场沟通记录…');
    try { const { report } = await request('/report/' + encodeURIComponent(sessionId)); renderReport(report); showView('report'); state.sessionId = sessionId; }
    catch (error) { toast(error.message); history.replaceState({}, '', '/demo/index.html'); await loadCases(); }
    finally { hideLoading(); }
  }

  $('brand-home').addEventListener('click', () => { if (!views.training.hidden) { toast('请先结束本场实训'); return; } state.sessionId = null; history.pushState({}, '', '/demo/'); loadCases(); });
  $('message-input').addEventListener('keydown', event => { if (event.key === 'Enter' && !event.isComposing) { event.preventDefault(); sendMessage(); } });
  $('send-button').addEventListener('click', () => sendMessage());
  $('interrupt-button').addEventListener('click', interrupt);
  $('audio-unlock').addEventListener('click', () => {
    const video = $('patient-video');
    video.muted = false;
    Promise.allSettled([video.play(), PatientPlayer.enableAudio?.()])
      .then(() => $('audio-unlock').hidden = true)
      .catch(() => toast('声音仍未开启，请检查浏览器音量'));
  });
  $('end-button').addEventListener('click', showEndModal);
  $('cancel-end').addEventListener('click', () => $('end-modal').hidden = true);
  $('confirm-end').addEventListener('click', finish);
  $('print-button').addEventListener('click', () => { $('transcript-card').open = true; window.print(); });
  $('again-button').addEventListener('click', () => { state.sessionId = null; history.pushState({}, '', '/demo/'); loadCases(); });
  window.addEventListener('popstate', () => { const params = new URLSearchParams(location.search); if (params.get('view') === 'report' && params.get('session_id')) openReport(params.get('session_id')); else if (views.training.hidden) loadCases(); });
  setupSpeech();
  const params = new URLSearchParams(location.search);
  if (params.get('view') === 'report' && params.get('session_id')) openReport(params.get('session_id'));
  else loadCases();
})();
