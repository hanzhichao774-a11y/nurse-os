(() => {
  "use strict";

  const API_BASE = "/api/exam";
  const TYPE_LABELS = { single: "单选题", multiple: "多选题", judge: "判断题" };
  const MODE_LABELS = { sequential: "顺序练习", random: "随机练习", exam: "模拟考试", review: "专项复习" };
  const SUBJECT_SHORT = { "高等教育学": "教育学", "高等教育心理学": "心理学", "职业道德与法规": "道德法规" };

  const $ = (id) => document.getElementById(id);
  const els = {};
  let bank = null;
  let questionById = new Map();
  let profile = freshProfile();
  let session = null;
  let currentUser = null;
  let currentPage = "home";
  let setup = { mode: "sequential", subject: "all", type: "all", count: 50 };
  let collectionFilter = "all";
  let timerHandle = null;
  let confirmAction = null;
  let toastHandle = null;
  let syncTimer = null;
  let stateRevision = 0;
  let syncedRevision = 0;
  let syncing = false;

  function freshProfile() {
    return { history: {}, wrong: [], favorites: [], sessionsCompleted: 0, totalAttempts: 0, totalCorrect: 0, totalSeconds: 0, lastResult: null };
  }

  function saveProfile() {
    queueStateSync();
  }

  function saveSession() {
    if (session) {
      session.lastActiveAt = Date.now();
    }
    queueStateSync();
  }

  function queueStateSync() {
    if (!currentUser) return;
    stateRevision += 1;
    clearTimeout(syncTimer);
    syncTimer = setTimeout(syncState, 180);
  }

  async function syncState() {
    if (!currentUser || syncing || syncedRevision >= stateRevision) return;
    syncing = true;
    const targetRevision = stateRevision;
    try {
      const response = await fetch(`${API_BASE}/state`, {
        method: "PUT",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile, session })
      });
      if (response.status === 401) return handleExpiredSession();
      if (!response.ok) throw new Error("学习数据同步失败");
      syncedRevision = targetRevision;
    } catch (error) {
      showToast(error.message || "学习数据同步失败，请检查网络");
    } finally {
      syncing = false;
      if (syncedRevision < stateRevision && currentUser) {
        clearTimeout(syncTimer);
        syncTimer = setTimeout(syncState, 350);
      }
    }
  }

  async function flushState() {
    clearTimeout(syncTimer);
    while (syncing) await new Promise((resolve) => setTimeout(resolve, 25));
    await syncState();
    while (syncing) await new Promise((resolve) => setTimeout(resolve, 25));
  }

  function cacheElements() {
    document.querySelectorAll("[id]").forEach((node) => { els[node.id] = node; });
  }

  async function init() {
    cacheElements();
    bindEvents();
    try {
      const response = await fetch("./data/questions.json", { cache: "no-cache" });
      if (!response.ok) throw new Error(`题库请求失败 (${response.status})`);
      bank = await response.json();
      if (!bank?.questions?.length) throw new Error("题库内容为空");
      questionById = new Map(bank.questions.map((question) => [question.id, question]));
      els.loadingView.classList.add("hidden");
      const authResponse = await fetch(`${API_BASE}/auth/status`, { credentials: "same-origin" });
      const authState = authResponse.ok ? await authResponse.json() : { user: null };
      if (authState.user) {
        currentUser = authState.user;
        await loadUserState();
        enterApplication();
      } else {
        showAuth();
      }
    } catch (error) {
      els.loadingView.innerHTML = `<div class="empty-state"><h2>题库加载失败</h2><p>${escapeHTML(error.message)}</p><button class="button primary" onclick="location.reload()">重新加载</button></div>`;
      els.loadingView.classList.remove("hidden");
    }
  }

  async function loadUserState() {
    const response = await fetch(`${API_BASE}/state`, { credentials: "same-origin" });
    if (!response.ok) throw new Error("无法加载账户学习数据");
    const state = await response.json();
    profile = state.profile && typeof state.profile === "object" ? { ...freshProfile(), ...state.profile } : freshProfile();
    session = state.session && typeof state.session === "object" ? state.session : null;
    stateRevision = 0;
    syncedRevision = 0;
  }

  function enterApplication() {
    sanitizeStoredData();
    els.authView.classList.add("hidden");
    els.headerAction.classList.remove("hidden");
    els.headerUsername.textContent = currentUser.username;
    els.userInitial.textContent = [...currentUser.username][0] || "用";
    els.bottomNav.classList.remove("hidden");
    renderHome();
    showPage("home");
  }

  function showAuth(mode = "login") {
    stopTimer();
    currentUser = null;
    profile = freshProfile();
    session = null;
    stateRevision = 0;
    syncedRevision = 0;
    ["homeView", "questionView", "collectionView", "statsView", "resultView", "loadingView"].forEach((id) => els[id].classList.add("hidden"));
    els.bottomNav.classList.add("hidden");
    els.headerAction.classList.add("hidden");
    els.authView.classList.remove("hidden");
    switchAuthMode(mode);
  }

  function sanitizeStoredData() {
    const valid = (ids) => [...new Set(Array.isArray(ids) ? ids.filter((id) => questionById.has(id)) : [])];
    profile = { ...freshProfile(), ...profile };
    profile.wrong = valid(profile.wrong);
    profile.favorites = valid(profile.favorites);
    profile.history = Object.fromEntries(Object.entries(profile.history || {}).filter(([id]) => questionById.has(id)));
    if (session && (!Array.isArray(session.ids) || !session.ids.length)) session = null;
    if (session) {
      session.ids = valid(session.ids);
      if (!session.ids.length) session = null;
      else session.index = Math.min(Math.max(Number(session.index) || 0, 0), session.ids.length - 1);
    }
    saveProfile();
    saveSession();
  }

  function bindEvents() {
    els.brandButton.addEventListener("click", () => { if (currentUser) leaveFor("home"); });
    els.headerAction.addEventListener("click", openAccount);
    els.loginTab.addEventListener("click", () => switchAuthMode("login"));
    els.registerTab.addEventListener("click", () => switchAuthMode("register"));
    els.loginForm.addEventListener("submit", handleLogin);
    els.registerForm.addEventListener("submit", handleRegister);
    els.closeAccount.addEventListener("click", () => els.accountDialog.close());
    els.accountStats.addEventListener("click", () => { els.accountDialog.close(); showPage("stats"); });
    els.logoutButton.addEventListener("click", handleLogout);
    els.continueCard.addEventListener("click", resumeSession);
    document.querySelectorAll("[data-mode]").forEach((button) => button.addEventListener("click", () => openSetup(button.dataset.mode)));
    document.querySelectorAll("[data-go-home]").forEach((button) => button.addEventListener("click", () => showPage("home")));
    els.bottomNav.addEventListener("click", (event) => {
      const button = event.target.closest("[data-page]");
      if (button) leaveFor(button.dataset.page);
    });
    els.exitSession.addEventListener("click", () => confirmExit("home"));
    els.previousButton.addEventListener("click", previousQuestion);
    els.nextButton.addEventListener("click", nextQuestion);
    els.confirmButton.addEventListener("click", confirmMultipleAnswer);
    els.favoriteButton.addEventListener("click", toggleFavorite);
    els.openPalette.addEventListener("click", openPalette);
    els.mobilePalette.addEventListener("click", openPalette);
    els.closePalette.addEventListener("click", () => els.paletteDialog.close());
    els.submitExamAside.addEventListener("click", requestSubmitExam);
    els.submitExamPalette.addEventListener("click", requestSubmitExam);
    els.startButton.addEventListener("click", startConfiguredSession);
    els.confirmCancel.addEventListener("click", () => els.confirmDialog.close());
    els.confirmAccept.addEventListener("click", () => {
      const action = confirmAction;
      confirmAction = null;
      els.confirmDialog.close();
      action?.();
    });
    els.resultHome.addEventListener("click", () => showPage("home"));
    els.reviewWrong.addEventListener("click", () => {
      const ids = profile.lastResult?.wrongIds || [];
      if (ids.length) startReview(ids, "本次错题复习");
    });
    els.resetData.addEventListener("click", requestResetData);
    window.addEventListener("beforeunload", () => {
      // Do not upload an unchanged, potentially stale snapshot when another
      // device has updated the same account since this page last synchronized.
      if (session && currentUser && stateRevision > syncedRevision) {
        session.accumulatedSeconds = elapsedSeconds();
        session.startedAt = Date.now();
        fetch(`${API_BASE}/state`, {
          method: "PUT",
          credentials: "same-origin",
          keepalive: true,
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ profile, session })
        }).catch(() => {});
      }
    });
  }

  function switchAuthMode(mode) {
    const login = mode === "login";
    els.loginTab.classList.toggle("active", login);
    els.registerTab.classList.toggle("active", !login);
    els.loginTab.setAttribute("aria-selected", String(login));
    els.registerTab.setAttribute("aria-selected", String(!login));
    els.loginForm.classList.toggle("hidden", !login);
    els.registerForm.classList.toggle("hidden", login);
    els.loginError.classList.add("hidden");
    els.registerError.classList.add("hidden");
  }

  async function requestJSON(endpoint, options = {}) {
    const response = await fetch(`${API_BASE}${endpoint}`, {
      credentials: "same-origin",
      ...options,
      headers: { "Content-Type": "application/json", ...(options.headers || {}) }
    });
    let body = {};
    try { body = await response.json(); } catch (_) {}
    if (!response.ok) {
      const error = new Error(body.detail || "请求失败，请稍后再试");
      error.status = response.status;
      throw error;
    }
    return body;
  }

  function setFormBusy(button, busy, normalText) {
    button.disabled = busy;
    button.textContent = busy ? "请稍候…" : normalText;
  }

  async function handleLogin(event) {
    event.preventDefault();
    els.loginError.classList.add("hidden");
    setFormBusy(els.loginButton, true, "登录");
    try {
      const result = await requestJSON("/auth/login", {
        method: "POST",
        body: JSON.stringify({ username: els.loginUsername.value, password: els.loginPassword.value })
      });
      currentUser = result.user;
      await loadUserState();
      els.loginForm.reset();
      enterApplication();
    } catch (error) {
      showFormError(els.loginError, error.message);
    } finally {
      setFormBusy(els.loginButton, false, "登录");
    }
  }

  async function handleRegister(event) {
    event.preventDefault();
    els.registerError.classList.add("hidden");
    if (els.registerPassword.value !== els.registerPasswordConfirm.value) {
      return showFormError(els.registerError, "两次输入的密码不一致");
    }
    setFormBusy(els.registerButton, true, "注册并进入");
    try {
      const result = await requestJSON("/auth/register", {
        method: "POST",
        body: JSON.stringify({
          username: els.registerUsername.value,
          password: els.registerPassword.value,
          invitationCode: els.invitationCode.value
        })
      });
      currentUser = result.user;
      await loadUserState();
      els.registerForm.reset();
      enterApplication();
    } catch (error) {
      showFormError(els.registerError, error.message);
    } finally {
      setFormBusy(els.registerButton, false, "注册并进入");
    }
  }

  function showFormError(element, message) {
    element.textContent = message;
    element.classList.remove("hidden");
  }

  function openAccount() {
    if (!currentUser) return;
    els.accountUsername.textContent = currentUser.username;
    const expiry = new Date(currentUser.expiresAt);
    els.accountExpiry.textContent = `当前 Cookie 有效期至 ${expiry.toLocaleString("zh-CN", { hour12: false })}`;
    els.accountDialog.showModal();
  }

  async function handleLogout() {
    els.logoutButton.disabled = true;
    try {
      await flushState();
      await requestJSON("/auth/logout", { method: "POST", body: "{}" });
      els.accountDialog.close();
      showAuth("login");
    } catch (error) {
      showToast(error.message);
    } finally {
      els.logoutButton.disabled = false;
    }
  }

  function handleExpiredSession() {
    if (!currentUser) return;
    showToast("登录状态已过期，请重新登录");
    if (els.accountDialog.open) els.accountDialog.close();
    showAuth("login");
  }

  function showPage(page) {
    if (!currentUser) return showAuth("login");
    stopTimer();
    currentPage = page;
    ["homeView", "questionView", "collectionView", "statsView", "resultView"].forEach((id) => els[id].classList.add("hidden"));
    const navPage = page === "wrong" || page === "favorite" ? page : page === "stats" ? "stats" : "home";
    document.querySelectorAll("#bottomNav button").forEach((button) => button.classList.toggle("active", button.dataset.page === navPage));
    els.bottomNav.classList.toggle("hidden", page === "question" || page === "result");
    if (page === "home") {
      renderHome();
      els.homeView.classList.remove("hidden");
    } else if (page === "question") {
      els.questionView.classList.remove("hidden");
      renderQuestion();
      if (session.mode === "exam") startTimer();
    } else if (page === "wrong" || page === "favorite") {
      renderCollection(page);
      els.collectionView.classList.remove("hidden");
    } else if (page === "stats") {
      renderStats();
      els.statsView.classList.remove("hidden");
    } else if (page === "result") {
      renderResult();
      els.resultView.classList.remove("hidden");
    }
    window.scrollTo({ top: 0, behavior: "auto" });
    els.main.focus({ preventScroll: true });
  }

  function leaveFor(page) {
    if (currentPage === "question") confirmExit(page);
    else showPage(page);
  }

  function confirmExit(page) {
    openConfirm("退出本次练习？", "当前进度会自动保存，下次可以从首页继续。", "退出", () => {
      if (session) {
        session.accumulatedSeconds = elapsedSeconds();
        session.startedAt = Date.now();
        saveSession();
      }
      showPage(page);
    });
  }

  function renderHome() {
    const attempted = Object.keys(profile.history).length;
    const percent = Math.round((attempted / bank.meta.total) * 100);
    els.progressPercent.textContent = `${percent}%`;
    els.progressRing.style.strokeDashoffset = String(201 - (201 * percent) / 100);
    els.attemptedStat.textContent = attempted;
    els.accuracyStat.textContent = profile.totalAttempts ? `${Math.round((profile.totalCorrect / profile.totalAttempts) * 100)}%` : "—";
    els.wrongStat.textContent = profile.wrong.length;
    els.favoriteStat.textContent = profile.favorites.length;
    els.wrongBadge.textContent = profile.wrong.length > 99 ? "99+" : profile.wrong.length;
    els.wrongBadge.classList.toggle("hidden", !profile.wrong.length);
    els.totalBadge.textContent = `${bank.meta.total} 题`;
    els.heroCopy.textContent = attempted ? `已完成 ${attempted} 道题，今天继续巩固薄弱知识点。` : `完整收录 ${bank.meta.total} 道题，从第一组练习开始。`;

    if (session?.ids?.length) {
      els.continueCard.classList.remove("hidden");
      els.continueTitle.textContent = MODE_LABELS[session.mode] || "继续练习";
      els.continueMeta.textContent = `${session.filterLabel || "全部科目"} · 第 ${session.index + 1} / ${session.ids.length} 题`;
    } else {
      els.continueCard.classList.add("hidden");
    }

    const subjects = Object.entries(bank.meta.subjects);
    els.subjectList.innerHTML = subjects.map(([subject, count], index) => {
      const done = bank.questions.filter((q) => q.subject === subject && profile.history[q.id]).length;
      const progress = Math.round((done / count) * 100);
      return `<button class="subject-card" type="button" data-subject="${escapeHTML(subject)}">
        <span class="subject-index">0${index + 1}</span>
        <span><strong>${escapeHTML(subject)}</strong><small>${count} 题 · 已练 ${done} 题</small></span>
        <span class="subject-progress"><span class="mini-progress"><i style="width:${progress}%"></i></span><em>${progress}%</em><svg class="chevron" viewBox="0 0 24 24"><path d="m9 5 7 7-7 7"/></svg></span>
      </button>`;
    }).join("");
    els.subjectList.querySelectorAll("[data-subject]").forEach((button) => button.addEventListener("click", () => openSetup("sequential", button.dataset.subject)));
  }

  function openSetup(mode, preferredSubject = "all") {
    setup = { mode, subject: preferredSubject, type: "all", count: mode === "exam" ? 100 : 50 };
    els.setupTitle.textContent = MODE_LABELS[mode];
    renderSetupOptions();
    els.setupDialog.showModal();
  }

  function renderSetupOptions() {
    const subjectItems = [["all", "全部科目"], ...Object.keys(bank.meta.subjects).map((subject) => [subject, SUBJECT_SHORT[subject]])];
    const typeItems = [["all", "全部题型"], ["single", "单选题"], ["multiple", "多选题"], ["judge", "判断题"]];
    const counts = setup.mode === "exam" ? [[50, "50 题"], [100, "100 题"], [150, "150 题"]] : [[20, "20 题"], [50, "50 题"], [100, "100 题"], ["all", "全部"]];
    els.subjectOptions.innerHTML = chips(subjectItems, setup.subject);
    els.typeOptions.innerHTML = chips(typeItems, setup.type);
    els.countOptions.innerHTML = chips(counts, setup.count);
    bindChipGroup(els.subjectOptions, "subject");
    bindChipGroup(els.typeOptions, "type");
    bindChipGroup(els.countOptions, "count");
    updateSetupNote();
  }

  function chips(items, selected) {
    return items.map(([value, label]) => `<button type="button" class="${String(value) === String(selected) ? "active" : ""}" data-value="${escapeHTML(String(value))}">${escapeHTML(label)}</button>`).join("");
  }

  function bindChipGroup(container, field) {
    container.querySelectorAll("button").forEach((button) => button.addEventListener("click", () => {
      setup[field] = field === "count" && button.dataset.value !== "all" ? Number(button.dataset.value) : button.dataset.value;
      renderSetupOptions();
    }));
  }

  function matchingQuestions() {
    return bank.questions.filter((question) => (setup.subject === "all" || question.subject === setup.subject) && (setup.type === "all" || question.type === setup.type));
  }

  function updateSetupNote() {
    const available = matchingQuestions().length;
    const wanted = setup.count === "all" ? available : Math.min(setup.count, available);
    els.setupNote.textContent = setup.mode === "exam"
      ? `将从 ${available} 道符合条件的题目中随机抽取 ${wanted} 道，限时 ${examMinutes(wanted)} 分钟，交卷后统一显示答案。`
      : `当前筛选共有 ${available} 道题，本次练习 ${wanted} 道，答题后立即显示结果。`;
    els.startButton.disabled = available === 0;
  }

  function startConfiguredSession() {
    let matches = matchingQuestions();
    if (!matches.length) return;
    const wanted = setup.count === "all" ? matches.length : Math.min(setup.count, matches.length);
    if (setup.mode === "sequential") {
      const firstUnseen = matches.findIndex((question) => !profile.history[question.id]);
      if (firstUnseen > 0) matches = [...matches.slice(firstUnseen), ...matches.slice(0, firstUnseen)];
    } else {
      matches = shuffle(matches);
    }
    const ids = matches.slice(0, wanted).map((question) => question.id);
    createSession(ids, setup.mode, filterLabel(setup.subject, setup.type), setup.mode === "exam" ? examMinutes(wanted) * 60 : 0);
    els.setupDialog.close();
    showPage("question");
  }

  function createSession(ids, mode, label, examDurationSec = 0) {
    session = {
      mode,
      filterLabel: label,
      ids,
      index: 0,
      answers: {},
      outcomes: {},
      graded: {},
      startedAt: Date.now(),
      accumulatedSeconds: 0,
      examDurationSec,
      createdAt: Date.now()
    };
    saveSession();
  }

  function resumeSession() {
    if (!session?.ids?.length) return;
    session.startedAt = Date.now();
    showPage("question");
  }

  function startReview(ids, label) {
    const valid = ids.filter((id) => questionById.has(id));
    if (!valid.length) return showToast("暂无可复习题目");
    createSession(valid, "review", label);
    showPage("question");
  }

  function renderQuestion() {
    if (!session?.ids?.length) return showPage("home");
    const question = currentQuestion();
    const selected = session.answers[question.id] || "";
    const graded = Boolean(session.graded[question.id]);
    const isExam = session.mode === "exam";
    els.sessionTitle.textContent = MODE_LABELS[session.mode] || "练习";
    els.sessionSubtitle.textContent = session.filterLabel || "全部科目";
    els.examTimer.classList.toggle("hidden", !isExam);
    els.submitExamAside.classList.toggle("hidden", !isExam);
    els.sessionProgress.style.width = `${((session.index + 1) / session.ids.length) * 100}%`;
    els.questionType.textContent = TYPE_LABELS[question.type];
    els.questionSubject.textContent = question.subject;
    els.currentNumber.textContent = session.index + 1;
    els.questionTotal.textContent = `/ ${session.ids.length}`;
    els.questionPrompt.textContent = question.prompt;
    els.answerHint.textContent = question.type === "multiple" ? "本题有多个正确答案，请选择所有符合项" : question.type === "judge" ? "请判断下列说法是否正确" : "请选择一个答案";
    els.favoriteButton.classList.toggle("active", profile.favorites.includes(question.id));
    els.favoriteButton.setAttribute("aria-label", profile.favorites.includes(question.id) ? "取消收藏" : "收藏本题");

    els.optionList.innerHTML = question.options.map((option) => {
      const picked = selected.includes(option.key);
      const correct = graded && question.answer.includes(option.key);
      const wrong = graded && picked && !question.answer.includes(option.key);
      const classes = ["option", picked ? "selected" : "", correct ? "correct" : "", wrong ? "wrong" : ""].filter(Boolean).join(" ");
      return `<button class="${classes}" type="button" data-key="${option.key}" ${graded && !isExam ? "disabled" : ""}>
        <span class="option-key">${option.key === "T" ? "✓" : option.key === "F" ? "×" : option.key}</span>
        <span class="option-text">${escapeHTML(option.text)}</span>
        <svg class="option-check" viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></svg>
      </button>`;
    }).join("");
    els.optionList.querySelectorAll("[data-key]").forEach((button) => button.addEventListener("click", () => chooseOption(button.dataset.key)));

    const practiceMultiplePending = !isExam && question.type === "multiple" && !graded;
    els.confirmButton.classList.toggle("hidden", !practiceMultiplePending);
    els.confirmButton.disabled = !selected;
    els.nextButton.classList.toggle("hidden", practiceMultiplePending);
    els.previousButton.disabled = session.index === 0;
    els.nextButton.innerHTML = session.index === session.ids.length - 1
      ? `${isExam ? "交卷" : "完成练习"}<svg viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></svg>`
      : `${!graded && !isExam ? "跳过" : "下一题"}<svg viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></svg>`;
    renderFeedback(question, selected, graded, isExam);
    renderSessionStats();
  }

  function renderFeedback(question, selected, graded, isExam) {
    if (!graded || isExam) {
      els.feedbackCard.classList.add("hidden");
      return;
    }
    const correct = session.outcomes[question.id];
    els.feedbackCard.classList.remove("hidden");
    els.feedbackCard.classList.toggle("incorrect", !correct);
    els.feedbackIcon.textContent = correct ? "✓" : "×";
    els.feedbackTitle.textContent = correct ? "回答正确" : "回答错误";
    els.correctAnswer.textContent = displayAnswer(question, question.answer);
    els.yourAnswer.textContent = selected ? displayAnswer(question, selected) : "未作答";
  }

  function displayAnswer(question, answer) {
    if (!answer) return "未作答";
    return [...answer].map((key) => {
      const option = question.options.find((item) => item.key === key);
      return option ? `${key === "T" || key === "F" ? "" : key + ". "}${option.text}` : key;
    }).join("；");
  }

  function chooseOption(key) {
    const question = currentQuestion();
    if (session.graded[question.id] && session.mode !== "exam") return;
    let answer = session.answers[question.id] || "";
    if (question.type === "multiple") {
      answer = answer.includes(key) ? answer.replace(key, "") : [...answer, key].sort().join("");
      session.answers[question.id] = answer;
      saveSession();
      renderQuestion();
      return;
    }
    session.answers[question.id] = key;
    if (session.mode !== "exam") gradeQuestion(question, key);
    saveSession();
    renderQuestion();
  }

  function confirmMultipleAnswer() {
    const question = currentQuestion();
    const answer = session.answers[question.id] || "";
    if (!answer) return;
    gradeQuestion(question, answer);
    saveSession();
    renderQuestion();
  }

  function gradeQuestion(question, answer) {
    if (session.graded[question.id]) return;
    const correct = answer === question.answer;
    session.graded[question.id] = true;
    session.outcomes[question.id] = correct;
    recordOutcome(question.id, answer, correct);
  }

  function recordOutcome(id, answer, correct) {
    const item = profile.history[id] || { attempts: 0, correct: 0 };
    item.attempts += 1;
    item.correct += correct ? 1 : 0;
    item.lastCorrect = correct;
    item.lastAnswer = answer;
    item.lastAt = Date.now();
    profile.history[id] = item;
    profile.totalAttempts += 1;
    profile.totalCorrect += correct ? 1 : 0;
    if (correct) profile.wrong = profile.wrong.filter((wrongId) => wrongId !== id);
    else if (!profile.wrong.includes(id)) profile.wrong.push(id);
    saveProfile();
  }

  function renderSessionStats() {
    const answered = session.ids.filter((id) => session.answers[id]).length;
    const correct = Object.values(session.outcomes).filter(Boolean).length;
    els.answeredCount.textContent = answered;
    els.correctCount.textContent = session.mode === "exam" ? "—" : correct;
    els.remainingCount.textContent = session.ids.length - answered;
  }

  function previousQuestion() {
    if (session.index > 0) {
      session.index -= 1;
      saveSession();
      renderQuestion();
      window.scrollTo({ top: 0, behavior: "smooth" });
    }
  }

  function nextQuestion() {
    if (session.index === session.ids.length - 1) {
      if (session.mode === "exam") requestSubmitExam();
      else finishPractice();
      return;
    }
    session.index += 1;
    saveSession();
    renderQuestion();
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  function finishPractice() {
    const unanswered = session.ids.filter((id) => !session.graded[id]).length;
    const finish = () => finishSession(false);
    if (unanswered) openConfirm("结束本次练习？", `还有 ${unanswered} 道题未完成，结束后将按未作答处理。`, "结束练习", finish);
    else finish();
  }

  function requestSubmitExam() {
    if (!session || session.mode !== "exam") return;
    const unanswered = session.ids.filter((id) => !session.answers[id]).length;
    openConfirm("确认交卷？", unanswered ? `还有 ${unanswered} 道题未作答，交卷后不能修改答案。` : "题目已全部作答，交卷后将立即生成成绩。", "确认交卷", () => finishSession(true));
  }

  function finishSession(isExam) {
    const finishing = session;
    if (isExam) {
      finishing.ids.forEach((id) => {
        const question = questionById.get(id);
        const answer = finishing.answers[id] || "";
        if (!finishing.graded[id]) gradeQuestion(question, answer);
      });
    }
    const correct = finishing.ids.filter((id) => finishing.outcomes[id]).length;
    const wrongIds = finishing.ids.filter((id) => !finishing.outcomes[id]);
    const duration = elapsedSeconds();
    const result = {
      mode: finishing.mode,
      total: finishing.ids.length,
      correct,
      wrongIds,
      duration,
      completedAt: Date.now(),
      filterLabel: finishing.filterLabel
    };
    profile.lastResult = result;
    profile.sessionsCompleted += 1;
    profile.totalSeconds += duration;
    saveProfile();
    session = null;
    saveSession();
    stopTimer();
    if (els.paletteDialog.open) els.paletteDialog.close();
    showPage("result");
  }

  function renderResult() {
    const result = profile.lastResult;
    if (!result) return showPage("home");
    const score = result.total ? Math.round((result.correct / result.total) * 100) : 0;
    els.resultScore.textContent = `${score}%`;
    els.resultCorrect.textContent = result.correct;
    els.resultWrong.textContent = result.total - result.correct;
    els.resultDuration.textContent = formatDuration(result.duration);
    els.resultHeadline.textContent = score >= 90 ? "掌握得很扎实" : score >= 70 ? "完成得不错" : score >= 60 ? "继续巩固一下" : "再复习一轮吧";
    els.resultSummary.textContent = `${MODE_LABELS[result.mode] || "练习"} · ${result.filterLabel || "全部科目"} · 共 ${result.total} 题`;
    els.reviewWrong.disabled = !result.wrongIds.length;
  }

  function openPalette() {
    renderPalette();
    els.paletteDialog.showModal();
  }

  function renderPalette() {
    els.paletteGrid.innerHTML = session.ids.map((id, index) => {
      const classes = [session.answers[id] ? "answered" : "", index === session.index ? "current" : ""].filter(Boolean).join(" ");
      return `<button type="button" class="${classes}" data-index="${index}" aria-label="第 ${index + 1} 题">${index + 1}</button>`;
    }).join("");
    els.paletteGrid.querySelectorAll("[data-index]").forEach((button) => button.addEventListener("click", () => {
      session.index = Number(button.dataset.index);
      saveSession();
      els.paletteDialog.close();
      renderQuestion();
    }));
    els.submitExamPalette.classList.toggle("hidden", session.mode !== "exam");
  }

  function toggleFavorite() {
    const id = currentQuestion().id;
    if (profile.favorites.includes(id)) {
      profile.favorites = profile.favorites.filter((favoriteId) => favoriteId !== id);
      showToast("已取消收藏");
    } else {
      profile.favorites.push(id);
      showToast("已加入收藏");
    }
    saveProfile();
    renderQuestion();
  }

  function renderCollection(kind) {
    const isWrong = kind === "wrong";
    const sourceIds = isWrong ? profile.wrong : profile.favorites;
    els.collectionEyebrow.textContent = isWrong ? "复习巩固" : "重点关注";
    els.collectionTitle.textContent = isWrong ? "错题本" : "我的收藏";
    els.collectionDescription.textContent = isWrong ? "答对后会自动移出，反复练到真正掌握。" : "集中整理需要重点记忆的题目。";
    const subjects = ["all", ...Object.keys(bank.meta.subjects)];
    if (!subjects.includes(collectionFilter)) collectionFilter = "all";
    els.collectionFilters.innerHTML = subjects.map((subject) => `<button type="button" class="${collectionFilter === subject ? "active" : ""}" data-filter="${escapeHTML(subject)}">${subject === "all" ? "全部" : SUBJECT_SHORT[subject]}</button>`).join("");
    els.collectionFilters.querySelectorAll("[data-filter]").forEach((button) => button.addEventListener("click", () => {
      collectionFilter = button.dataset.filter;
      renderCollection(kind);
    }));
    const questions = sourceIds.map((id) => questionById.get(id)).filter(Boolean).filter((question) => collectionFilter === "all" || question.subject === collectionFilter);
    els.collectionCount.textContent = questions.length;
    els.collectionEmpty.classList.toggle("hidden", questions.length > 0);
    els.collectionList.classList.toggle("hidden", questions.length === 0);
    els.collectionList.innerHTML = questions.map((question) => `<article class="collection-item">
      <div><div class="collection-meta"><span>${escapeHTML(question.subject)}</span><span>·</span><span>${TYPE_LABELS[question.type]}</span></div><h3>${escapeHTML(question.prompt)}</h3><div class="collection-answer">答案：${escapeHTML(displayAnswer(question, question.answer))}</div></div>
      <button class="button secondary" type="button" data-review="${question.id}">练习此题</button>
    </article>`).join("");
    els.collectionList.querySelectorAll("[data-review]").forEach((button) => button.addEventListener("click", () => {
      const startId = button.dataset.review;
      const ids = [startId, ...questions.map((q) => q.id).filter((id) => id !== startId)];
      startReview(ids, isWrong ? "错题复习" : "收藏复习");
    }));
  }

  function renderStats() {
    const attempted = Object.keys(profile.history).length;
    const accuracy = profile.totalAttempts ? Math.round((profile.totalCorrect / profile.totalAttempts) * 100) : 0;
    els.statsOverview.innerHTML = [
      [attempted, "累计练题"],
      [profile.totalAttempts ? `${accuracy}%` : "—", "累计正确率"],
      [profile.sessionsCompleted, "完成练习"],
      [formatDuration(profile.totalSeconds), "累计用时"]
    ].map(([value, label]) => `<div class="report-metric"><strong>${value}</strong><span>${label}</span></div>`).join("");
    els.subjectProgress.innerHTML = Object.entries(bank.meta.subjects).map(([subject, total]) => {
      const ids = bank.questions.filter((question) => question.subject === subject).map((question) => question.id);
      const done = ids.filter((id) => profile.history[id]).length;
      const correctLast = ids.filter((id) => profile.history[id]?.lastCorrect).length;
      const percent = Math.round((done / total) * 100);
      return `<div class="progress-item"><div class="progress-item-head"><strong>${escapeHTML(subject)}</strong><span>已练 ${done}/${total} · 当前掌握 ${correctLast}</span></div><div class="progress-bar"><i style="width:${percent}%"></i></div></div>`;
    }).join("");
  }

  function requestResetData() {
    openConfirm("清空学习数据？", "当前账户的练习记录、错题和收藏都会从服务器中删除，此操作无法撤销。", "确认清空", () => {
      profile = freshProfile();
      session = null;
      saveProfile();
      saveSession();
      renderStats();
      showToast("学习数据已清空");
    });
  }

  function openConfirm(title, message, actionLabel, action) {
    confirmAction = action;
    els.confirmTitle.textContent = title;
    els.confirmMessage.textContent = message;
    els.confirmAccept.textContent = actionLabel;
    els.confirmDialog.showModal();
  }

  function currentQuestion() {
    return questionById.get(session.ids[session.index]);
  }

  function elapsedSeconds() {
    if (!session) return 0;
    return Math.max(0, Math.round((session.accumulatedSeconds || 0) + (Date.now() - session.startedAt) / 1000));
  }

  function startTimer() {
    stopTimer();
    updateTimer();
    timerHandle = setInterval(updateTimer, 1000);
  }

  function stopTimer() {
    if (timerHandle) clearInterval(timerHandle);
    timerHandle = null;
  }

  function updateTimer() {
    if (!session || session.mode !== "exam") return stopTimer();
    const remaining = Math.max(0, session.examDurationSec - elapsedSeconds());
    els.examTimer.querySelector("span").textContent = formatClock(remaining);
    if (remaining <= 0) {
      stopTimer();
      showToast("考试时间已到，系统已自动交卷");
      finishSession(true);
    }
  }

  function examMinutes(count) {
    return Math.max(30, Math.round(count * 0.9));
  }

  function filterLabel(subject, type) {
    const subjectLabel = subject === "all" ? "全部科目" : subject;
    return type === "all" ? subjectLabel : `${subjectLabel} · ${TYPE_LABELS[type]}`;
  }

  function shuffle(items) {
    const result = [...items];
    for (let index = result.length - 1; index > 0; index -= 1) {
      const swap = Math.floor(Math.random() * (index + 1));
      [result[index], result[swap]] = [result[swap], result[index]];
    }
    return result;
  }

  function formatClock(seconds) {
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${String(mins).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }

  function formatDuration(seconds) {
    const value = Math.max(0, Math.round(seconds || 0));
    if (value < 3600) return formatClock(value);
    const hours = Math.floor(value / 3600);
    const mins = Math.floor((value % 3600) / 60);
    return `${hours}时${mins}分`;
  }

  function showToast(message) {
    clearTimeout(toastHandle);
    els.toast.textContent = message;
    els.toast.classList.add("show");
    toastHandle = setTimeout(() => els.toast.classList.remove("show"), 1800);
  }

  function escapeHTML(value) {
    return String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
  }

  init();
})();
