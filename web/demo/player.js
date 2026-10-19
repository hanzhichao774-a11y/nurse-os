/*
 * 沿用 LiveTalking/web/index-whep.html 已验证的 WHEP 协商流程：
 * recvonly 音视频轨道 → 等待 ICE 收集 → POST /avatar/{sessionid}/whep
 * → 读取 X-Session-ID 和 SDP answer。仅将页面元素改为回调接口。
 */
window.PatientPlayer = (() => {
  let pc = null;
  let hls = null;
  let soulxSocket = null;
  let soulxOptions = null;
  let soulxBitmap = null;
  let currentSession = null;
  let currentProvider = 'livetalking';
  let mobileSession = null;
  let readyTimer = null;
  let mediaListeners = [];

  const audioPlayer = {
    ctx: null,
    nextStart: 0,
    sources: new Set(),
    responseId: null,
    leadSec: 1.3,
    needLead: true,
    speakingTimer: null,
    finishedTimer: null,
    runningWaiters: new Set(),
    scheduledResponses: 0,
    scheduledChunks: 0,
    scheduledSeconds: 0,
    endedChunks: 0,
    prepare() {
      const AudioCtx = window.AudioContext || window.webkitAudioContext;
      if (!this.ctx && AudioCtx) this.ctx = new AudioCtx();
      if (this.ctx?.state === 'suspended') this.ctx.resume().catch(() => {});
      return this.ctx;
    },
    begin(event) {
      this.responseId = event.response_id;
      this.leadSec = Math.max(0, Number(event.lead_ms || 0) / 1000);
      this.needLead = true;
      this.scheduledResponses += 1;
    },
    feed(event) {
      const ctx = this.prepare();
      if (!ctx || !event.pcm || event.response_id !== this.responseId) return false;
      const bytes = Uint8Array.from(atob(event.pcm), char => char.charCodeAt(0));
      const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
      const floats = new Float32Array(Math.floor(bytes.byteLength / 2));
      for (let i = 0; i < floats.length; i++) floats[i] = view.getInt16(i * 2, true) / 32768;
      const buffer = ctx.createBuffer(1, floats.length, 16000);
      buffer.copyToChannel(floats, 0);
      const source = ctx.createBufferSource();
      source.buffer = buffer;
      source.connect(ctx.destination);
      const earliest = ctx.currentTime + 0.035 + (this.needLead ? this.leadSec : 0);
      const startsAt = Math.max(earliest, this.nextStart);
      this.needLead = false;
      source.start(startsAt);
      this.nextStart = startsAt + buffer.duration;
      this.scheduledChunks += 1;
      this.scheduledSeconds += buffer.duration;
      this.sources.add(source);
      source.onended = () => { this.sources.delete(source); this.endedChunks += 1; };
      if (!this.speakingTimer) {
        this.speakingTimer = setTimeout(() => {
          this.speakingTimer = null;
          soulxOptions?.onSpeaking?.(true);
        }, Math.max(0, (startsAt - ctx.currentTime) * 1000));
      }
      clearTimeout(this.finishedTimer);
      this.finishedTimer = setTimeout(() => {
        this.finishedTimer = null;
        soulxOptions?.onSpeaking?.(false);
      }, Math.max(0, (this.nextStart - ctx.currentTime) * 1000 + 80));
      return true;
    },
    whenRunning(callback) {
      const ctx = this.prepare();
      if (!ctx) return;
      if (ctx.state === 'running') { callback(); return; }
      const waiter = () => {
        if (ctx.state !== 'running') return;
        ctx.removeEventListener('statechange', waiter);
        this.runningWaiters.delete(waiter);
        callback();
      };
      this.runningWaiters.add(waiter);
      ctx.addEventListener('statechange', waiter);
    },
    flush() {
      for (const source of this.sources) { try { source.stop(); } catch { /* already stopped */ } }
      this.sources.clear();
      if (this.ctx) {
        for (const waiter of this.runningWaiters) this.ctx.removeEventListener('statechange', waiter);
      }
      this.runningWaiters.clear();
      clearTimeout(this.speakingTimer);
      clearTimeout(this.finishedTimer);
      this.speakingTimer = null;
      this.finishedTimer = null;
      this.responseId = null;
      this.needLead = true;
      this.nextStart = this.ctx?.currentTime || 0;
      soulxOptions?.onSpeaking?.(false);
    },
    state() {
      return {
        contextState: this.ctx?.state || 'unavailable',
        activeSources: this.sources.size,
        responseId: this.responseId,
        scheduledResponses: this.scheduledResponses,
        scheduledChunks: this.scheduledChunks,
        scheduledSeconds: Number(this.scheduledSeconds.toFixed(3)),
        endedChunks: this.endedChunks,
      };
    },
  };

  function usePublicMedia() {
    return !['localhost', '127.0.0.1', '::1'].includes(location.hostname);
  }

  function clearReadyTimer() {
    if (readyTimer) clearTimeout(readyTimer);
    readyTimer = null;
  }

  async function startPublic(options, video) {
    mobileSession = options.sessionId;
    const response = await fetch('/api/demo/session/mobile-media', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_id: options.sessionId }),
    });
    const data = await response.json();
    if (!response.ok || !data.url) throw new Error(data.error || '患者画面连接失败，请重新进入实训');
    if (currentSession !== options.sessionId) return;

    let notified = false;
    const onPlaying = () => {
      if (notified || currentSession !== options.sessionId || video.paused || video.videoWidth === 0) return;
      notified = true;
      clearReadyTimer();
      options.onConnected?.();
      options.onSessionCreated?.();
      options.onReady?.();
      options.onAudioBlocked?.();
    };
    video.addEventListener('playing', onPlaying);
    video.addEventListener('resize', onPlaying);
    mediaListeners.push(['playing', onPlaying], ['resize', onPlaying]);
    video.muted = true; // iOS permits muted autoplay; sound is unlocked by a visible tap.
    video.setAttribute('webkit-playsinline', '');
    const onError = () => { if (currentSession === options.sessionId) options.onDisconnected?.(); };
    video.addEventListener('error', onError);
    mediaListeners.push(['error', onError]);
    const attemptPlay = () => video.play().catch(() => {
      const unlock = document.getElementById('audio-unlock');
      unlock.textContent = '点击播放患者画面';
      options.onAudioBlocked?.();
    });

    const appleBrowser = /Apple/.test(navigator.vendor || '') || /iPhone|iPad|iPod/.test(navigator.userAgent);
    if (appleBrowser && video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = data.url;
      attemptPlay();
    } else if (window.Hls?.isSupported()) {
      hls = new Hls({ liveSyncDurationCount: 2, maxLiveSyncPlaybackRate: 1.2 });
      hls.on(Hls.Events.ERROR, (_, error) => {
        if (error.fatal) options.onDisconnected?.();
      });
      hls.on(Hls.Events.MANIFEST_PARSED, attemptPlay);
      hls.loadSource(data.url);
      hls.attachMedia(video);
    } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
      video.src = data.url;
      attemptPlay();
    } else {
      throw new Error('当前浏览器无法播放患者画面，请使用最新版 Safari 或 Chrome');
    }
    readyTimer = setTimeout(() => {
      if (!notified && currentSession === options.sessionId) options.onDisconnected?.();
    }, 25000);
    return options.sessionId;
  }

  function waitForIce(peer) {
    return new Promise((resolve, reject) => {
      if (peer.iceGatheringState === 'complete') return resolve();
      const timer = setTimeout(() => { peer.removeEventListener('icegatheringstatechange', check); reject(new Error('媒体连接准备超时')); }, 7000);
      function check() {
        if (peer.iceGatheringState === 'complete') {
          clearTimeout(timer);
          peer.removeEventListener('icegatheringstatechange', check);
          resolve();
        }
      }
      peer.addEventListener('icegatheringstatechange', check);
    });
  }

  async function startLegacy(options) {
    stop();
    const video = document.getElementById('patient-video');
    currentSession = options.sessionId;
    if (usePublicMedia()) {
      try { return await startPublic(options, video); }
      catch (error) { stop(); throw error; }
    }
    const peer = new RTCPeerConnection({ sdpSemantics: 'unified-plan' });
    pc = peer;

    video.addEventListener('playing', () => options.onReady?.(), { once: true });

    peer.addEventListener('track', event => {
      // One media element owns both tracks so the browser uses their WebRTC
      // timestamps to keep the generated lips and speech on the same clock.
      const stream = event.streams[0];
      if (!stream) return;
      if (video.srcObject !== stream) video.srcObject = stream;
      video.muted = false;
      video.play().catch(() => options.onAudioBlocked?.());
    });
    peer.addEventListener('connectionstatechange', () => {
      if (peer.connectionState === 'connected') options.onConnected?.();
      if (peer.connectionState === 'failed' || peer.connectionState === 'disconnected') options.onDisconnected?.();
    });

    try {
      peer.addTransceiver('video', { direction: 'recvonly' });
      peer.addTransceiver('audio', { direction: 'recvonly' });
      const offer = await peer.createOffer();
      await peer.setLocalDescription(offer);
      await waitForIce(peer);

      const params = new URLSearchParams({ avatar: options.avatarId, sessionid: options.sessionId });
      const response = await fetch('/avatar/' + encodeURIComponent(options.sessionId) + '/whep?' + params.toString(), {
        method: 'POST',
        headers: { 'Content-Type': 'application/sdp' },
        body: peer.localDescription.sdp,
      });
      if (!response.ok) throw new Error('媒体连接失败');
      const returnedSession = response.headers.get('X-Session-ID');
      if (returnedSession && returnedSession !== options.sessionId) throw new Error('媒体会话编号不一致');
      options.onSessionCreated?.();
      const answerSdp = await response.text();
      await peer.setRemoteDescription(new RTCSessionDescription({ type: 'answer', sdp: answerSdp }));
      return options.sessionId;
    } catch (error) {
      stop();
      throw error;
    }
  }

  function drawSoulxFrame(blob, canvas, notifyReady) {
    createImageBitmap(blob).then(bitmap => {
      const context = canvas.getContext('2d');
      context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
      if (soulxBitmap) soulxBitmap.close();
      soulxBitmap = bitmap;
      notifyReady();
    }).catch(() => {});
  }

  async function startSoulx(options) {
    stop();
    currentProvider = 'soulx';
    currentSession = options.sessionId;
    soulxOptions = options;
    const video = document.getElementById('patient-video');
    const canvas = document.getElementById('patient-canvas');
    video.hidden = true;
    canvas.hidden = false;
    audioPlayer.prepare();
    const scheme = location.protocol === 'https:' ? 'wss:' : 'ws:';
    const url = `${scheme}//${location.host}/api/demo/avatar/ws/${encodeURIComponent(options.sessionId)}`;
    let ready = false;
    await new Promise((resolve, reject) => {
      const socket = new WebSocket(url);
      soulxSocket = socket;
      socket.binaryType = 'blob';
      const timer = setTimeout(() => {
        if (!ready) { socket.close(); reject(new Error('SoulX 画面连接超时')); }
      }, 25000);
      const notifyReady = () => {
        if (ready || currentSession !== options.sessionId) return;
        ready = true;
        clearTimeout(timer);
        options.onConnected?.();
        options.onSessionCreated?.();
        options.onReady?.();
        resolve(options.sessionId);
      };
      socket.onmessage = event => {
        if (typeof event.data !== 'string') {
          drawSoulxFrame(event.data, canvas, notifyReady);
          return;
        }
        let message;
        try { message = JSON.parse(event.data); } catch { return; }
        if (message.type === 'audio-start') {
          audioPlayer.begin(message);
          if (audioPlayer.ctx?.state !== 'running') options.onAudioBlocked?.();
        } else if (message.type === 'audio') {
          if (!audioPlayer.feed(message)) options.onAudioBlocked?.();
          if (message.final) {
            audioPlayer.whenRunning(() => {
              if (soulxSocket === socket && socket.readyState === WebSocket.OPEN) {
                socket.send(JSON.stringify({ type: 'audio-ready', response_id: message.response_id }));
              }
            });
          }
        } else if (message.type === 'flush' || message.type === 'flushed') {
          audioPlayer.flush();
        } else if (message.type === 'audio-error') {
          audioPlayer.flush();
          options.onAudioError?.();
        }
      };
      socket.onerror = () => {
        if (!ready) { clearTimeout(timer); reject(new Error('SoulX 画面连接失败')); }
      };
      socket.onclose = () => {
        clearTimeout(timer);
        if (!ready) reject(new Error('SoulX 画面连接失败'));
        else if (currentSession === options.sessionId) options.onDisconnected?.();
      };
    });
    return options.sessionId;
  }

  async function start(options) {
    if (options.provider === 'soulx') {
      try { return await startSoulx(options); }
      catch (error) {
        stop();
        if (!options.allowFallback) throw error;
      }
    }
    return startLegacy(options);
  }

  function prepare() { audioPlayer.prepare(); }

  function enableAudio() {
    const ctx = audioPlayer.prepare();
    return ctx ? ctx.resume() : Promise.reject(new Error('浏览器不支持音频播放'));
  }

  async function interrupt() {
    if (currentProvider === 'soulx' && soulxSocket?.readyState === WebSocket.OPEN) {
      audioPlayer.flush();
      soulxSocket.send(JSON.stringify({ type: 'interrupt' }));
      return true;
    }
    if (!currentSession) return false;
    const response = await fetch('/interrupt_talk', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sessionid: currentSession }),
    });
    const data = await response.json();
    return response.ok && data.code === 0;
  }

  function stop() {
    clearReadyTimer();
    if (hls) { hls.destroy(); hls = null; }
    if (pc) { pc.close(); pc = null; }
    if (soulxSocket) {
      soulxSocket.onclose = null;
      soulxSocket.close();
      soulxSocket = null;
    }
    audioPlayer.flush();
    soulxOptions = null;
    currentProvider = 'livetalking';
    if (mobileSession) {
      fetch('/api/demo/session/mobile-media/stop', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ session_id: mobileSession }), keepalive: true,
      }).catch(() => {});
      mobileSession = null;
    }
    currentSession = null;
    const video = document.getElementById('patient-video');
    if (video) {
      for (const [event, callback] of mediaListeners) video.removeEventListener(event, callback);
      mediaListeners = [];
      video.pause();
      video.srcObject = null;
      video.removeAttribute('src');
      video.load();
      video.hidden = false;
    }
    const canvas = document.getElementById('patient-canvas');
    if (canvas) { canvas.hidden = true; canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height); }
    if (soulxBitmap) { soulxBitmap.close(); soulxBitmap = null; }
  }

  window.addEventListener('pagehide', () => {
    if (!mobileSession) return;
    navigator.sendBeacon(
      '/api/demo/session/mobile-media/stop',
      new Blob([JSON.stringify({ session_id: mobileSession })], { type: 'application/json' }),
    );
  });

  return {
    start, stop, prepare, enableAudio, interrupt,
    getSessionId: () => currentSession,
    getProvider: () => currentProvider,
    getAudioState: () => audioPlayer.state(),
  };
})();
