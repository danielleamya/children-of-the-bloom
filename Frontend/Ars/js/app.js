/**
 * CHILD/REN of the BLOOM — kiosk experience controller.
 *
 * Scenes: landing → sacred → (prayer ↔ chat)×8 → endingPrayer → credits.
 * Prayer timing comes from loop.audioCues; line wrapping is shared with
 * cue-review via prayer-lines.js. Staff shortcuts and fullscreen lock live here.
 */
const COPY = {
  disclaimer:
    "You are about to speak with a generative AI chatbot. Your messages and responses may be stored on a local server for this installation. Do not share personal, sensitive, or confidential information.",
};

const CREDITS = {
  // Order and sizing: first entry is the lead credit (larger + extra spacing).
  people: [
    { name: "LaJuné McMillian", role: "Artist" },
    { name: "Danielle McPhatter", role: "Lead Technologist" },
    { name: "Veronica Garza", role: "Project Manager" },
    { name: "Carey Dueweke", role: "UI Art Direction" },
    { name: "Josie Williams", role: "AI Development" },
    { name: "Paz Zait-Givon", role: "Hydroponics Development" },
  ],
};

const SECTION_BASE_MS = 3000;
const SECTION_CHAR_MS = 18;
const SECTION_MAX_MS = 9000;
const POEM_TRANSITION_MS = 900;
const MAX_NEIGHBOR_LINES = 5;
const CHAT_IDLE_MS = 10 * 60 * 1000;
const DEFAULT_TURNS_PER_LOOP = 5;
const VIDEO_BASE = "assets/videos/";
/** Staff password required to leave kiosk fullscreen. */
const KIOSK_EXIT_PASSWORD = "children123";
/** Auto-dismiss the unlock panel if nothing is submitted. */
const KIOSK_LOCK_IDLE_MS = 60 * 1000;

const state = {
  scene: "landing",
  messages: [],
  placeholder: "Type your message here...",
  readingLines: [],
  poemLineIndex: 0,
  poemComplete: false,
  poemTransitioning: false,
  sessionId: null,
  chatBusy: false,
  chatReadyToContinue: false,
  animateLeadingQuestion: false,
  animateContinueButton: false,
  endingPrayerText: "",
  loopIndex: 0,
  turnCount: 0,
  turnsPerLoop: DEFAULT_TURNS_PER_LOOP,
  loops: [],
  loopsMeta: { wrapFraction: 0.48 },
  closing: null,
  contentReady: false,
  audioCueStarts: null,
  audioCompleteAt: null,
  prayerAwaitingSpeech: false,
  prayerAutoContinuing: false,
};

let poemTimer = null;
let poemTransitionTimeout = null;
let chatIdleTimer = null;
let prayerAudioSyncBound = false;
let prayerEndWatchTimer = null;

const ui = document.getElementById("ui");
const kiosk = document.getElementById("kiosk");
const loopVideo = document.getElementById("loop-video");
const kioskLock = document.getElementById("kiosk-lock");
const kioskLockForm = document.getElementById("kiosk-lock-form");
const kioskLockPassword = document.getElementById("kiosk-lock-password");
const kioskLockError = document.getElementById("kiosk-lock-error");
const kioskLockReturn = document.getElementById("kiosk-lock-return");

let kioskFullscreenArmed = false;
let kioskFullscreenExitAllowed = false;
let kioskLockIdleTimer = null;
let kioskSilentRestoreBound = false;

// --- Fullscreen staff gate -------------------------------------------------
// Browsers always allow Escape to exit fullscreen. When armed, we immediately
// cover the UI with #kiosk-lock until the password succeeds, idle times out,
// or staff chooses "Return to kiosk".

function isDocumentFullscreen() {
  return Boolean(
    document.fullscreenElement ||
      document.webkitFullscreenElement ||
      document.msFullscreenElement
  );
}

async function requestKioskFullscreen() {
  const root = document.documentElement;
  if (isDocumentFullscreen()) return true;
  try {
    if (root.requestFullscreen) {
      await root.requestFullscreen({ navigationUI: "hide" });
    } else if (root.webkitRequestFullscreen) {
      root.webkitRequestFullscreen();
    } else if (root.msRequestFullscreen) {
      root.msRequestFullscreen();
    } else {
      return false;
    }
    return true;
  } catch (_) {
    return false;
  }
}

async function exitKioskFullscreen() {
  if (!isDocumentFullscreen()) return;
  try {
    if (document.exitFullscreen) await document.exitFullscreen();
    else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
    else if (document.msExitFullscreen) document.msExitFullscreen();
  } catch (_) {
    /* ignore */
  }
}

function clearKioskLockIdleTimer() {
  if (kioskLockIdleTimer) {
    clearTimeout(kioskLockIdleTimer);
    kioskLockIdleTimer = null;
  }
}

function scheduleKioskLockIdleTimer() {
  clearKioskLockIdleTimer();
  kioskLockIdleTimer = setTimeout(() => {
    dismissKioskLockToKiosk();
  }, KIOSK_LOCK_IDLE_MS);
}

function armSilentFullscreenRestore() {
  if (kioskSilentRestoreBound) return;
  kioskSilentRestoreBound = true;
  const restore = () => {
    kioskSilentRestoreBound = false;
    if (!kioskFullscreenArmed || kioskFullscreenExitAllowed) return;
    if (isDocumentFullscreen()) return;
    requestKioskFullscreen();
  };
  window.addEventListener("pointerdown", restore, { once: true, capture: true });
  window.addEventListener("keydown", restore, { once: true, capture: true });
}

function showKioskLock() {
  if (!kioskLock) return;
  kioskLock.hidden = false;
  if (kioskLockError) kioskLockError.hidden = true;
  if (kioskLockPassword) {
    kioskLockPassword.value = "";
    requestAnimationFrame(() => kioskLockPassword.focus());
  }
  scheduleKioskLockIdleTimer();
}

function hideKioskLock() {
  clearKioskLockIdleTimer();
  if (!kioskLock) return;
  kioskLock.hidden = true;
  if (kioskLockError) kioskLockError.hidden = true;
  if (kioskLockPassword) kioskLockPassword.value = "";
}

async function dismissKioskLockToKiosk() {
  clearKioskLockIdleTimer();
  hideKioskLock();
  kioskFullscreenExitAllowed = false;
  kioskFullscreenArmed = true;
  const ok = await requestKioskFullscreen();
  if (!ok && !isDocumentFullscreen()) {
    armSilentFullscreenRestore();
  }
}

async function armKioskFullscreen() {
  kioskFullscreenExitAllowed = false;
  kioskFullscreenArmed = true;
  hideKioskLock();
  const ok = await requestKioskFullscreen();
  if (!ok && !isDocumentFullscreen()) {
    armSilentFullscreenRestore();
  }
}

function unlockKioskFullscreen() {
  kioskFullscreenExitAllowed = true;
  kioskFullscreenArmed = false;
  hideKioskLock();
}

function onKioskFullscreenChange() {
  if (!kioskFullscreenArmed) return;
  if (isDocumentFullscreen()) {
    hideKioskLock();
    return;
  }
  if (kioskFullscreenExitAllowed) {
    kioskFullscreenArmed = false;
    hideKioskLock();
    return;
  }
  // Browsers always allow Escape to leave fullscreen. Re-cover the UI with
  // the staff gate; returning requires a click (user gesture) to re-enter.
  showKioskLock();
}

function loopWantsAudioSync(loop = currentLoop()) {
  if (!loop) return false;
  if (loop.audioSync === true) return true;
  return Boolean(loop.video && /withsound/i.test(loop.video));
}

function prayerUsesAudioSync() {
  return state.scene === "prayer" && loopWantsAudioSync();
}

function currentLoop() {
  return state.loops[state.loopIndex] || null;
}

function isLastLoop() {
  return state.loops.length > 0 && state.loopIndex >= state.loops.length - 1;
}

function turnsForCurrentLoop() {
  return isLastLoop() ? 1 : state.turnsPerLoop;
}

function isReadingScene(scene = state.scene) {
  // "closing" (The Portal) remains supported in code but is not linked in the live flow.
  return scene === "prayer" || scene === "endingPrayer" || scene === "closing";
}

function readingSourceText() {
  if (state.scene === "endingPrayer") return state.endingPrayerText;
  if (state.scene === "closing") {
    return (state.closing && state.closing.prayer) || "";
  }
  const loop = currentLoop();
  return (loop && loop.prayer) || "";
}

function readingHeader() {
  if (state.scene === "endingPrayer") return "Your prayer";
  if (state.scene === "closing") return "The Portal";
  return "A child's prayer";
}

function readingContinueAction() {
  if (state.scene === "endingPrayer") return "continue-ending-prayer";
  if (state.scene === "closing") return "continue-closing";
  return "continue-prayer";
}

function readingContinueLabel() {
  return "Continue";
}

function renderCreditsScreen() {
  const people = CREDITS.people
    .map((person, index) => {
      const lead = index === 0 ? " credits-person--lead" : "";
      return `
        <li class="credits-person${lead}">
          <span class="credits-name">${escapeHtml(person.name)}</span>
          <span class="credits-role">${escapeHtml(person.role)}</span>
        </li>`;
    })
    .join("");

  return frame(
    0.15,
    `
      <div class="screen-frame" aria-hidden="true"></div>
      <p class="screen-header screen-header--poem">Credits</p>
      <div class="screen-body">
        <div class="credits-stage credits-stage--enter">
          <ul class="credits-people">${people}</ul>
          <div class="credits-logos" aria-label="Partner logos">
            <div class="credits-logo-row credits-logo-row--solo">
              <img
                class="credits-logo credits-logo--irl"
                src="assets/logos/irl-logo.png"
                alt="EY intelligent realities lab"
              />
            </div>
            <div class="credits-logo-row credits-logo-row--pair">
              <img
                class="credits-logo credits-logo--partner"
                src="assets/logos/new-inc-white.png"
                alt="NEW INC"
              />
              <img
                class="credits-logo credits-logo--partner"
                src="assets/logos/new-museum-white.png"
                alt="New Museum"
              />
            </div>
          </div>
        </div>
      </div>
      <div class="poem-footer">
        <button class="btn btn--medium poem-continue" data-action="reload">Begin again</button>
      </div>`,
    { poem: true, credits: true }
  );
}

function readingShowSideActions() {
  return state.scene === "prayer";
}

function videoSrcFor(filename) {
  if (!filename) return "";
  return `${VIDEO_BASE}${filename}`;
}

function clearLoopVideoLayout() {
  if (!loopVideo) return;
  loopVideo.style.top = "";
  loopVideo.style.left = "";
  loopVideo.style.width = "";
  loopVideo.style.height = "";
  loopVideo.style.right = "";
  loopVideo.style.bottom = "";
  loopVideo.style.position = "";
  loopVideo.style.inset = "";
}

function mountLoopVideoHost(mode) {
  if (!loopVideo || !kiosk) return;

  if (mode === "panel") {
    const frame = document.querySelector(".chat-video-frame");
    if (frame && loopVideo.parentElement !== frame) {
      frame.appendChild(loopVideo);
    }
    clearLoopVideoLayout();
    return;
  }

  // Full-bleed / idle: keep video as a direct kiosk layer under the UI.
  if (loopVideo.parentElement !== kiosk) {
    kiosk.insertBefore(loopVideo, kiosk.firstChild);
  }
  clearLoopVideoLayout();
}

function setLoopVideo(filename, { active = true, mode = "full", restart = false } = {}) {
  if (!loopVideo) return;

  if (!filename || !active) {
    detachPrayerAudioSync();
    loopVideo.pause();
    loopVideo.removeAttribute("src");
    loopVideo.load();
    loopVideo.classList.remove("is-active");
    if (kiosk) {
      kiosk.classList.remove("has-loop-video", "has-chat-video");
    }
    mountLoopVideoHost("full");
    app.clearForVideo = false;
    return;
  }

  const nextSrc = videoSrcFor(filename);
  const currentSrc = loopVideo.getAttribute("src") || "";
  const absoluteNext = new URL(nextSrc, window.location.href).href;
  const srcChanged =
    currentSrc !== nextSrc && loopVideo.src !== absoluteNext;

  if (srcChanged) {
    loopVideo.src = nextSrc;
    loopVideo.load();
  }

  // Spoken prayer: play once with audio. Chat (and silent loops): muted + loop.
  const playWithSound = mode === "full" && loopWantsAudioSync();
  loopVideo.muted = !playWithSound;
  loopVideo.loop = !playWithSound;
  if (playWithSound) {
    loopVideo.removeAttribute("loop");
  } else {
    loopVideo.setAttribute("loop", "");
  }

  if ((restart || srcChanged) && playWithSound) {
    const seekStart = () => {
      try {
        loopVideo.currentTime = 0;
      } catch (_) {
        /* seek may fail before metadata */
      }
    };
    seekStart();
    if (!Number.isFinite(loopVideo.duration) || loopVideo.readyState < 1) {
      loopVideo.addEventListener("loadedmetadata", seekStart, { once: true });
    }
  }

  const play = loopVideo.play();
  if (play && typeof play.catch === "function") {
    play.catch(() => {
      // Autoplay-with-sound can fail; keep visuals going muted.
      if (playWithSound) {
        loopVideo.muted = true;
        const retry = loopVideo.play();
        if (retry && typeof retry.catch === "function") retry.catch(() => {});
      }
    });
  }

  loopVideo.classList.add("is-active");

  if (mode === "panel") {
    if (kiosk) {
      kiosk.classList.remove("has-loop-video");
      kiosk.classList.add("has-chat-video");
    }
    app.clearForVideo = false;
  } else {
    if (kiosk) {
      kiosk.classList.remove("has-chat-video");
      kiosk.classList.add("has-loop-video");
    }
    mountLoopVideoHost("full");
    app.clearForVideo = true;
  }
}

function syncChatVideoLayout() {
  if (!loopVideo || !kiosk || state.scene !== "chat") return;
  if (!kiosk.classList.contains("has-chat-video")) return;

  mountLoopVideoHost("panel");

  const frame = document.querySelector(".chat-video-frame");
  if (frame) {
    const applyAspect = () => {
      const w = loopVideo.videoWidth;
      const h = loopVideo.videoHeight;
      if (w > 0 && h > 0) {
        frame.style.aspectRatio = `${w} / ${h}`;
      }
    };
    applyAspect();
    if (!loopVideo.videoWidth) {
      loopVideo.addEventListener("loadedmetadata", applyAspect, { once: true });
    }
  }

  // Keep playback alive after DOM moves.
  if (loopVideo.paused) {
    const play = loopVideo.play();
    if (play && typeof play.catch === "function") play.catch(() => {});
  }
}

function syncVideoForScene(scene) {
  const loop = currentLoop();
  if (scene === "prayer" && loop && loop.video) {
    setLoopVideo(loop.video, { active: true, mode: "full", restart: true });
    return;
  }
  if (scene === "chat" && loop && loop.video) {
    // Mute spoken prayer audio as soon as chat opens; keep picture looping quietly.
    setLoopVideo(loop.video, { active: true, mode: "panel" });
    return;
  }
  if (scene === "closing" && state.closing && state.closing.video) {
    setLoopVideo(state.closing.video, { active: true, mode: "full" });
    return;
  }
  setLoopVideo(null, { active: false });
}

const screens = {
  landing: () =>
    frame(
      0,
      `
      <div class="screen-body">
        <img
          class="brand-mark"
          src="assets/Title_Heading.png"
          alt="CHILD/REN of the BLOOM"
        />
      </div>
      <div class="actions">
        <button class="btn btn--large" data-action="begin">Click to begin</button>
      </div>`,
      { landing: true }
    ),

  sacred: () =>
    frame(
      0,
      `
      <p class="screen-header screen-header--a">Sacred Place</p>
      <div class="screen-body"><p class="disclaimer">${COPY.disclaimer}</p></div>
      <div class="actions">
        <button class="btn btn--medium" data-action="agree">I agree</button>
      </div>`
    ),

  prayer: () => renderReadingScreen(),
  endingPrayer: () => renderReadingScreen(),
  closing: () => renderReadingScreen(),
  credits: () => renderCreditsScreen(),

  chat: () => {
    app.bgDim = 0.15;
    const messages = state.messages
      .map((msg, index) => {
        const arrive =
          state.animateLeadingQuestion && index === 0 && msg.from === "bot"
            ? " msg--arrive"
            : "";
        return `<div class="msg ${msg.from}${arrive}">${escapeHtml(msg.text)}</div>`;
      })
      .join("");
    const busy =
      state.chatBusy && !state.chatReadyToContinue
        ? `<div class="msg bot msg--busy" aria-live="polite">
             <span class="busy-label">Child is listening</span>
             <span class="busy-aura" aria-hidden="true">
               <span class="busy-blob busy-blob--1"></span>
               <span class="busy-blob busy-blob--2"></span>
               <span class="busy-blob busy-blob--3"></span>
               <span class="busy-blob busy-blob--4"></span>
             </span>
           </div>`
        : "";
    const composer = state.chatReadyToContinue
      ? `<div class="chat-continue${
          state.animateContinueButton ? " chat-continue--arrive" : ""
        }">
           <button class="btn btn--medium" data-action="continue-after-chat">Continue</button>
         </div>`
      : `<form class="composer" data-action="send">
           <input
             name="message"
             autocomplete="off"
             placeholder="${state.placeholder}"
             ${state.chatBusy ? "disabled" : ""}
           />
           <button class="send" type="submit" aria-label="Send" ${
             state.chatBusy ? "disabled" : ""
           }>Send</button>
         </form>`;

    return `
      <section class="screen chat${state.animateLeadingQuestion ? " chat--entering" : ""}">
        <div class="chat-stage">
          <div class="chat-video-frame" aria-hidden="true"></div>
          <div class="chat-panel">
            <p class="chat-heading">Child</p>
            <div class="messages" id="messages">${messages}${busy}</div>
            ${composer}
          </div>
        </div>
      </section>`;
  },
};

function renderReadingScreen() {
  const sideActions = readingShowSideActions()
    ? `
        <button class="btn btn--restart" data-action="restart-prayer">Restart</button>
        <button class="btn btn--skip" data-action="skip-prayer">Skip</button>`
    : "";

  return frame(
    0.15,
    `
      <div class="screen-frame" aria-hidden="true"></div>
      <p class="screen-header screen-header--poem">${escapeHtml(readingHeader())}</p>
      <div class="screen-body">
        ${renderPoemCarousel()}
      </div>
      <div class="poem-footer">
        ${sideActions}
        <button
          class="btn btn--medium poem-continue ${state.poemComplete ? "" : "actions--hidden"}"
          data-action="${readingContinueAction()}"
        >${escapeHtml(readingContinueLabel())}</button>
      </div>`,
    {
      poem: true,
      prayer: true,
      closing: state.scene === "closing",
    }
  );
}

/**
 * Prayer line metrics / wrapping / cue expansion live in prayer-lines.js
 * so the cue editor preview matches the kiosk exactly.
 * Authored audioCue = one line; only width-wrap may create extra visual rows.
 */
function prayerViewport() {
  const loop = currentLoop();
  const wrapFraction = Number(
    (loop && loop.wrapFraction) ||
      (state.loopsMeta && state.loopsMeta.wrapFraction) ||
      0.48
  );
  return {
    width: (kiosk && kiosk.clientWidth) || window.innerWidth,
    height: (kiosk && kiosk.clientHeight) || window.innerHeight,
    wrapFraction,
    wrapMode: (loop && loop.wrapMode) || "width",
  };
}

function getPrayerLineMetrics() {
  return PrayerLines.getPrayerLineMetrics(prayerViewport());
}

function wrapLineToWidth(line, maxWidth, font) {
  return PrayerLines.wrapLineToWidth(line, maxWidth, font);
}

function splitOnSentencePunctuation(block) {
  return PrayerLines.splitOnSentencePunctuation(block);
}

function splitOnPeriods(block) {
  return splitOnSentencePunctuation(block);
}

function coalesceAudioCues(cues) {
  return PrayerLines.coalesceAudioCues(cues);
}

function splitPrayerSections(text) {
  return PrayerLines.splitPrayerSections(text, prayerViewport());
}

function sectionDwellMs(text) {
  const length = String(text || "").length;
  return Math.min(SECTION_MAX_MS, SECTION_BASE_MS + length * SECTION_CHAR_MS);
}

function poemLineHTML(text, className, slot) {
  return `<p class="poem-line poem-line--section ${className}" data-slot="${slot}"><span class="poem-line-text">${escapeHtml(
    text
  )}</span></p>`;
}

function buildPoemStackHTML(activeIndex) {
  if (state.prayerAwaitingSpeech) return "";

  const lines = state.readingLines;
  const showFuture = state.poemComplete;
  let html = "";

  const pastStart = Math.max(0, activeIndex - MAX_NEIGHBOR_LINES);
  for (let i = pastStart; i < activeIndex; i += 1) {
    const slot = activeIndex - i;
    html += poemLineHTML(lines[i], "poem-line--past", slot);
  }

  html += poemLineHTML(lines[activeIndex] || "", "poem-line--current", 0);

  if (showFuture) {
    const futureEnd = Math.min(lines.length - 1, activeIndex + MAX_NEIGHBOR_LINES);
    for (let i = activeIndex + 1; i <= futureEnd; i += 1) {
      const slot = activeIndex - i;
      html += poemLineHTML(lines[i], "poem-line--future", slot);
    }
  }

  return html;
}

function renderPoemCarousel() {
  return `
    <div class="poem-carousel" id="poem">
      <div class="poem-stack">${buildPoemStackHTML(state.poemLineIndex)}</div>
    </div>`;
}

function showPoemActions() {
  const continueBtn = document.querySelector(".poem-continue");
  if (continueBtn) continueBtn.classList.remove("actions--hidden");
}

function clearPoemTransition() {
  if (poemTransitionTimeout) {
    clearTimeout(poemTransitionTimeout);
    poemTransitionTimeout = null;
  }
  state.poemTransitioning = false;
}

function detachPrayerAudioSync() {
  if (loopVideo && prayerAudioSyncBound) {
    loopVideo.removeEventListener("timeupdate", onPrayerAudioTimeUpdate);
    loopVideo.removeEventListener("ended", onPrayerAudioEnded);
  }
  prayerAudioSyncBound = false;
  clearPrayerEndWatch();
}

function stopPrayerAudioLineSync() {
  if (!loopVideo) return;
  loopVideo.removeEventListener("timeupdate", onPrayerAudioTimeUpdate);
}

function clearPrayerEndWatch() {
  if (prayerEndWatchTimer) {
    clearTimeout(prayerEndWatchTimer);
    prayerEndWatchTimer = null;
  }
}

function attachPrayerAudioSync() {
  if (!loopVideo) return;
  if (!prayerAudioSyncBound) {
    loopVideo.addEventListener("timeupdate", onPrayerAudioTimeUpdate);
    loopVideo.addEventListener("ended", onPrayerAudioEnded);
    prayerAudioSyncBound = true;
  }
  // Always (re)arm the end watcher — line completion used to drop `ended`.
  schedulePrayerAutoContinueWatch();
}

function revealPrayerSpeech() {
  if (!state.prayerAwaitingSpeech) return;
  state.prayerAwaitingSpeech = false;
  const stack = document.querySelector("#poem .poem-stack");
  if (stack) stack.innerHTML = buildPoemStackHTML(state.poemLineIndex);
}

function autoContinuePrayerToChat() {
  if (state.scene !== "prayer") return;
  if (!loopWantsAudioSync()) return;
  if (state.prayerAutoContinuing) return;
  state.prayerAutoContinuing = true;
  clearPrayerEndWatch();
  if (!state.poemComplete) finishPrayerFromAudio();
  startLoopChat();
}

/**
 * Watch for true end-of-clip (including freeze on final frame).
 * Does not depend on the `ended` event alone — some browsers stall there.
 */
function schedulePrayerAutoContinueWatch() {
  if (!loopVideo || !prayerUsesAudioSync()) return;
  clearPrayerEndWatch();

  const tick = () => {
    prayerEndWatchTimer = null;
    if (state.scene !== "prayer" || state.prayerAutoContinuing) return;
    if (!loopWantsAudioSync()) return;

    const duration = loopVideo.duration;
    const t = loopVideo.currentTime;
    const nearEnd =
      loopVideo.ended ||
      (Number.isFinite(duration) &&
        duration > 0 &&
        t >= Math.max(0, duration - 0.2));

    if (nearEnd) {
      autoContinuePrayerToChat();
      return;
    }

    prayerEndWatchTimer = setTimeout(tick, 175);
  };

  prayerEndWatchTimer = setTimeout(tick, 175);
}

function finishPrayerFromAudio() {
  if (!isReadingScene()) return;
  if (poemTimer) {
    clearTimeout(poemTimer);
    poemTimer = null;
  }
  // Stop line sync only — keep end-of-video auto-continue armed.
  stopPrayerAudioLineSync();
  clearPoemTransition();
  state.prayerAwaitingSpeech = false;
  schedulePrayerAutoContinueWatch();
  if (state.poemComplete) return;
  state.poemComplete = true;
  state.poemLineIndex = Math.max(0, state.readingLines.length - 1);
  const stack = document.querySelector("#poem .poem-stack");
  if (stack) stack.innerHTML = buildPoemStackHTML(state.poemLineIndex);
  showPoemActions();
}

function onPrayerAudioEnded() {
  autoContinuePrayerToChat();
}

/**
 * Drive first-read line advances from spoken video timestamps.
 * Prefer per-line audioCues (expanded into readingStarts) when present.
 * Skip non-monotonic starts so a bad 0.0 wordTiming cannot lock the carousel
 * mid-prayer.
 */
function onPrayerAudioTimeUpdate() {
  if (!prayerUsesAudioSync() || state.poemComplete || state.poemTransitioning) {
    return;
  }
  if (!loopVideo) return;

  const n = state.readingLines.length;
  if (n <= 1) {
    finishPrayerFromAudio();
    return;
  }

  const t = loopVideo.currentTime;
  const firstStart =
    state.audioCueStarts && state.audioCueStarts.length
      ? Number(state.audioCueStarts[0]) || 0
      : 0;

  // Hold blank overlay through opening silence until speech begins.
  if (state.prayerAwaitingSpeech) {
    if (t + 0.05 < firstStart) return;
    revealPrayerSpeech();
  }

  let targetIndex;

  if (state.audioCueStarts && state.audioCueStarts.length === n) {
    targetIndex = 0;
    let lastAccepted = -Infinity;
    for (let i = 0; i < state.audioCueStarts.length; i += 1) {
      const s = Number(state.audioCueStarts[i]);
      if (!Number.isFinite(s)) continue;
      // Skip non-monotonic times (bad 0.0 wordTiming locks on later wraps).
      if (s + 0.05 < lastAccepted) continue;
      if (t + 0.08 >= s) {
        targetIndex = i;
        lastAccepted = s;
      }
    }
    const lastStart = state.audioCueStarts[n - 1];
    const completeAt =
      Number.isFinite(state.audioCompleteAt) && state.audioCompleteAt > lastStart
        ? state.audioCompleteAt
        : lastStart + 1.6;
    if (t >= completeAt) {
      finishPrayerFromAudio();
      return;
    }
  } else {
    const duration = loopVideo.duration;
    if (!Number.isFinite(duration) || duration <= 0) return;
    const progress = Math.min(1, Math.max(0, t / duration));
    targetIndex = Math.min(n - 1, Math.floor(progress * n));
  }

  if (targetIndex > state.poemLineIndex + 1) {
    clearPoemTransition();
    state.poemLineIndex = targetIndex;
    const stack = document.querySelector("#poem .poem-stack");
    if (stack) stack.innerHTML = buildPoemStackHTML(targetIndex);
    return;
  }

  if (targetIndex > state.poemLineIndex) {
    advancePoemLine();
  }
}

function scheduleNextSection() {
  if (poemTimer) {
    clearTimeout(poemTimer);
    poemTimer = null;
  }
  if (!isReadingScene() || state.poemComplete) return;

  if (prayerUsesAudioSync()) {
    attachPrayerAudioSync();
    return;
  }

  detachPrayerAudioSync();
  const current = state.readingLines[state.poemLineIndex] || "";
  poemTimer = setTimeout(() => {
    if (!isReadingScene() || state.poemTransitioning) return;
    advancePoemLine();
  }, sectionDwellMs(current));
}

function createPoemLineElement(text, className, slot) {
  const el = document.createElement("p");
  el.className = `poem-line poem-line--section ${className}`;
  el.dataset.slot = String(slot);
  const span = document.createElement("span");
  span.className = "poem-line-text";
  span.textContent = text;
  el.appendChild(span);
  return el;
}

function syncPoemLineClasses(el, slot) {
  el.classList.remove(
    "poem-line--current",
    "poem-line--past",
    "poem-line--future",
    "poem-line--incoming",
    "poem-line--enter",
    "poem-line--evict"
  );
  if (slot === 0) el.classList.add("poem-line--current");
  else if (slot > 0) el.classList.add("poem-line--past");
  else el.classList.add("poem-line--future");
}

/**
 * Move the carousel by one line. direction: +1 next, -1 previous.
 * Keeps active line centered. Future lines only appear after first readthrough.
 */
function movePrayerBy(direction) {
  if (state.poemTransitioning || !isReadingScene()) return false;

  const lines = state.readingLines;
  if (!lines.length) return false;

  const nextIndex = state.poemLineIndex + direction;
  if (nextIndex < 0) return false;

  if (nextIndex >= lines.length) {
    if (prayerUsesAudioSync()) {
      finishPrayerFromAudio();
    } else {
      state.poemComplete = true;
      clearPoemTimer();
      showPoemActions();
    }
    const stack = document.querySelector("#poem .poem-stack");
    if (stack) stack.innerHTML = buildPoemStackHTML(state.poemLineIndex);
    return false;
  }

  const poemEl = document.getElementById("poem");
  const stack = poemEl && poemEl.querySelector(".poem-stack");
  if (!stack) return false;

  state.poemTransitioning = true;
  const showFuture = state.poemComplete;

  // First readthrough: bring the next line in from below (hidden), then center it.
  if (!showFuture && direction > 0) {
    const outgoing = stack.querySelector(".poem-line--current");
    if (!outgoing) {
      clearPoemTransition();
      return false;
    }

    if (state.poemLineIndex >= MAX_NEIGHBOR_LINES) {
      const oldest = stack.querySelector(
        `.poem-line--past[data-slot="${MAX_NEIGHBOR_LINES}"]`
      );
      if (oldest) oldest.classList.add("poem-line--evict");
    }

    stack.querySelectorAll(".poem-line--past:not(.poem-line--evict)").forEach((el) => {
      const slot = Number(el.dataset.slot);
      if (slot < MAX_NEIGHBOR_LINES) el.dataset.slot = String(slot + 1);
    });

    outgoing.classList.remove("poem-line--current");
    outgoing.classList.add("poem-line--past");
    outgoing.dataset.slot = "1";

    const incoming = createPoemLineElement(
      lines[nextIndex],
      "poem-line--incoming",
      -1
    );
    incoming.style.opacity = "0";
    stack.appendChild(incoming);

    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        incoming.dataset.slot = "0";
        incoming.style.opacity = "";
        incoming.classList.add("poem-line--current", "poem-line--enter");
      });
    });

    poemTransitionTimeout = setTimeout(() => {
      state.poemLineIndex = nextIndex;
      if (nextIndex >= lines.length - 1) {
        if (prayerUsesAudioSync()) {
          finishPrayerFromAudio();
        } else {
          state.poemComplete = true;
          clearPoemTimer();
          showPoemActions();
        }
      }
      stack.innerHTML = buildPoemStackHTML(nextIndex);
      clearPoemTransition();
      if (!state.poemComplete) scheduleNextSection();
    }, POEM_TRANSITION_MS);

    return true;
  }

  // Browse mode (after first read): full carousel with neighbors above and below.
  stack.querySelectorAll(".poem-line").forEach((el) => {
    const slot = Number(el.dataset.slot);
    const newSlot = slot + direction;
    el.dataset.slot = String(newSlot);
    syncPoemLineClasses(el, newSlot);
  });

  if (direction > 0) {
    const incomingIndex = nextIndex + MAX_NEIGHBOR_LINES;
    if (incomingIndex < lines.length) {
      stack.appendChild(
        createPoemLineElement(
          lines[incomingIndex],
          "poem-line--future",
          -MAX_NEIGHBOR_LINES
        )
      );
    }
    const evict = stack.querySelector(
      `.poem-line[data-slot="${MAX_NEIGHBOR_LINES + 1}"]`
    );
    if (evict) evict.classList.add("poem-line--evict");
  } else {
    const incomingIndex = nextIndex - MAX_NEIGHBOR_LINES;
    if (incomingIndex >= 0) {
      stack.appendChild(
        createPoemLineElement(
          lines[incomingIndex],
          "poem-line--past",
          MAX_NEIGHBOR_LINES
        )
      );
    }
    const evict = stack.querySelector(
      `.poem-line[data-slot="${-(MAX_NEIGHBOR_LINES + 1)}"]`
    );
    if (evict) evict.classList.add("poem-line--evict");
  }

  poemTransitionTimeout = setTimeout(() => {
    state.poemLineIndex = nextIndex;
    stack.innerHTML = buildPoemStackHTML(nextIndex);
    clearPoemTransition();
  }, POEM_TRANSITION_MS);

  return true;
}

function advancePoemLine() {
  movePrayerBy(1);
}

function frame(dim, inner, options = {}) {
  app.bgDim = dim;
  const modifiers = [
    options.poem ? "screen--poem" : "",
    options.landing ? "screen--landing" : "",
    options.prayer ? "screen--prayer" : "",
    options.closing ? "screen--closing" : "",
    options.credits ? "screen--credits" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return `<section class="screen${modifiers ? ` ${modifiers}` : ""}">${inner}</section>`;
}

function clearPoemTimer() {
  if (poemTimer) {
    clearTimeout(poemTimer);
    poemTimer = null;
  }
  detachPrayerAudioSync();
  clearPoemTransition();
}

function expandCuesToReadingLines(cues) {
  return PrayerLines.expandCuesToReadingLines(cues, prayerViewport());
}

function preparePrayerReading() {
  // Expand authored audioCues into the visual lines + start times the carousel uses.
  state.audioCueStarts = null;
  state.audioCompleteAt = null;
  state.prayerAwaitingSpeech = false;
  state.prayerAutoContinuing = false;

  const loop = currentLoop();
  const cues =
    state.scene === "prayer" &&
    loop &&
    Array.isArray(loop.audioCues) &&
    loop.audioCues.length
      ? loop.audioCues
      : null;

  if (cues) {
    const expanded = expandCuesToReadingLines(cues);
    state.readingLines = expanded.lines;
    state.audioCueStarts = expanded.starts;
    const last = cues[cues.length - 1];
    state.audioCompleteAt = Number(last && last.end) || Number(last && last.start) + 2;
    const firstStart = Number(expanded.starts[0]) || 0;
    // Hide overlay until the spoken take actually begins.
    state.prayerAwaitingSpeech = firstStart > 0.15;
  } else {
    state.readingLines = splitPrayerSections(readingSourceText());
  }

  if (!state.readingLines.length) {
    state.readingLines = ["…"];
  }
  state.poemLineIndex = 0;
  state.poemComplete = state.readingLines.length <= 1;
  state.poemTransitioning = false;
}

function startPrayerReading() {
  clearPoemTimer();
  if (state.poemComplete) {
    showPoemActions();
    return;
  }
  scheduleNextSection();
}

function restartPrayerReading() {
  if (state.scene !== "prayer") return;
  clearPoemTimer();
  prayerWheelAccum = 0;
  preparePrayerReading();
  const loop = currentLoop();
  if (loop && loop.video) {
    setLoopVideo(loop.video, { active: true, mode: "full", restart: true });
  }
  render();
  startPrayerReading();
}

let prayerWheelAccum = 0;
const PRAYER_WHEEL_STEP = 28;

function jumpToPrayerLine(index) {
  if (!isReadingScene()) return;

  const lines = state.readingLines;
  if (!lines.length) return;

  const next = Math.max(0, Math.min(lines.length - 1, index));
  if (next === state.poemLineIndex) return;

  clearPoemTransition();
  state.poemLineIndex = next;
  const stack = document.querySelector("#poem .poem-stack");
  if (stack) stack.innerHTML = buildPoemStackHTML(next);
  showPoemActions();
}

function onPrayerWheel(event) {
  if (!isReadingScene() || !state.poemComplete) return;
  if (!state.readingLines.length) return;

  event.preventDefault();

  prayerWheelAccum += event.deltaY;
  if (Math.abs(prayerWheelAccum) < PRAYER_WHEEL_STEP) return;

  const direction = Math.sign(prayerWheelAccum);
  const steps = Math.min(
    3,
    Math.floor(Math.abs(prayerWheelAccum) / PRAYER_WHEEL_STEP)
  );
  prayerWheelAccum -= direction * steps * PRAYER_WHEEL_STEP;

  jumpToPrayerLine(state.poemLineIndex + direction * steps);
}

function go(scene) {
  if (isReadingScene(state.scene) && !isReadingScene(scene)) clearPoemTimer();
  if (state.scene === "chat" && scene !== "chat") clearChatIdleTimer();
  state.scene = scene;
  if (isReadingScene(scene)) preparePrayerReading();
  syncVideoForScene(scene);
  render();
  if (isReadingScene(scene)) startPrayerReading();
  if (scene === "chat") bumpChatIdleTimer();
}

function focusChatInput() {
  if (state.scene !== "chat" || state.chatBusy || state.chatReadyToContinue) return;
  const input = document.querySelector('.composer input[name="message"]');
  if (input instanceof HTMLInputElement) {
    input.focus({ preventScroll: true });
  }
}

function render() {
  // Keep the persistent video node alive across UI re-renders.
  if (loopVideo && ui.contains(loopVideo)) {
    kiosk.insertBefore(loopVideo, kiosk.firstChild);
  }

  ui.innerHTML = screens[state.scene]();
  const log = document.getElementById("messages");
  if (log) log.scrollTop = log.scrollHeight;
  if (state.scene === "chat") {
    requestAnimationFrame(() => {
      syncChatVideoLayout();
      focusChatInput();
    });
  }
  if (state.animateLeadingQuestion && state.scene === "chat") {
    // Allow one painted frame with arrive classes, then clear so later renders don't replay.
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        state.animateLeadingQuestion = false;
      });
    });
  }
  if (state.animateContinueButton && state.scene === "chat") {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        state.animateContinueButton = false;
      });
    });
  }
  persist();
}

async function ensureSession() {
  if (state.sessionId) return state.sessionId;
  const data = await Api.createSession();
  state.sessionId = data.session_id;
  return state.sessionId;
}

function beginExperienceLoops() {
  state.loopIndex = 0;
  state.turnCount = 0;
  go("prayer");
}

async function startLoopChat() {
  const loop = currentLoop();
  if (!loop) {
    go("credits");
    return;
  }

  state.turnCount = 0;
  state.chatBusy = false;
  state.chatReadyToContinue = false;
  state.animateLeadingQuestion = true;
  state.animateContinueButton = false;
  state.placeholder = isLastLoop()
    ? "Offer your prayer..."
    : "Type your message here...";
  state.messages = [
    {
      from: "bot",
      text: loop.leadingQuestion || "What stays with you from this prayer?",
    },
  ];

  try {
    if (state.sessionId) await Api.resetSession(state.sessionId);
    state.sessionId = null;
    await ensureSession();
  } catch (err) {
    console.warn("Chat session unavailable:", err);
    state.messages.push({
      from: "bot",
      text: "I cannot reach the local spirit yet. Is the Ars server running?",
    });
  }

  go("chat");
}

function jumpToLoopSection(index, { chat = false } = {}) {
  // Staff testing helper (Ctrl+Shift+#). Resets turn state for that loop only.
  if (!state.loops.length) return;
  const next = Math.max(0, Math.min(state.loops.length - 1, index));
  clearPoemTimer();
  clearChatIdleTimer();
  state.loopIndex = next;
  state.turnCount = 0;
  state.chatBusy = false;
  state.chatReadyToContinue = false;
  state.animateLeadingQuestion = false;
  state.animateContinueButton = false;
  state.endingPrayerText = "";
  if (chat) {
    startLoopChat();
    return;
  }
  go("prayer");
}

function advanceAfterTurns() {
  // Last loop: visitor's offering becomes endingPrayer, then credits (no Portal).
  if (isLastLoop()) {
    go("endingPrayer");
    return;
  }

  const nextIndex = state.loopIndex + 1;
  if (nextIndex < state.loops.length) {
    state.loopIndex = nextIndex;
    state.turnCount = 0;
    go("prayer");
    return;
  }
  go("credits");
}

async function handleSend(text) {
  if (!text || state.scene !== "chat" || state.chatBusy || state.chatReadyToContinue)
    return;

  bumpChatIdleTimer();
  state.messages.push({ from: "user", text });
  state.turnCount += 1;
  state.chatBusy = true;
  render();

  const turnLimit = turnsForCurrentLoop();
  const lastLoopPrayer = isLastLoop();

  if (lastLoopPrayer) {
    state.endingPrayerText = text;
  }

  try {
    // Final loop is a single prayer offering — no chatbot reply needed.
    if (!lastLoopPrayer) {
      const sessionId = await ensureSession();
      const data = await Api.chat(sessionId, text);
      state.messages.push({ from: "bot", text: data.reply });
    }
  } catch (err) {
    state.messages.push({
      from: "bot",
      text: err.reply || "The connection faded. Please try again.",
    });
  } finally {
    const loopComplete = state.turnCount >= turnLimit;
    state.chatReadyToContinue = loopComplete;
    state.animateContinueButton = loopComplete;
    state.chatBusy = loopComplete;
    render();
  }
}

function persist() {
  localStorage.setItem(
    "ars-bloom",
    JSON.stringify({
      scene: state.scene,
      loopIndex: state.loopIndex,
      turnCount: state.turnCount,
      messages: state.messages,
      savedAt: new Date().toISOString(),
    })
  );
}

function clearChatIdleTimer() {
  if (chatIdleTimer) {
    clearTimeout(chatIdleTimer);
    chatIdleTimer = null;
  }
}

function bumpChatIdleTimer() {
  clearChatIdleTimer();
  if (state.scene !== "chat") return;
  chatIdleTimer = setTimeout(() => {
    if (state.scene === "chat") reset();
  }, CHAT_IDLE_MS);
}

function reset() {
  clearPoemTimer();
  clearChatIdleTimer();
  if (state.sessionId) {
    Api.resetSession(state.sessionId).catch(() => {});
  }
  state.scene = "landing";
  state.messages = [];
  state.placeholder = "Type your message here...";
  state.readingLines = [];
  state.poemLineIndex = 0;
  state.poemComplete = false;
  state.poemTransitioning = false;
  state.sessionId = null;
  state.chatBusy = false;
  state.chatReadyToContinue = false;
  state.animateLeadingQuestion = false;
  state.animateContinueButton = false;
  state.endingPrayerText = "";
  state.loopIndex = 0;
  state.turnCount = 0;
  go("landing");
}

function escapeHtml(value) {
  return String(value || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

ui.addEventListener("click", (event) => {
  const btn = event.target.closest("[data-action]");
  if (!btn || btn.tagName === "FORM") return;

  const action = btn.dataset.action;
  if (action === "begin") {
    armKioskFullscreen();
    go("sacred");
  } else if (action === "agree") beginExperienceLoops();
  else if (action === "restart-prayer") restartPrayerReading();
  else if (action === "continue-prayer" || action === "skip-prayer") startLoopChat();
  else if (action === "continue-after-chat") advanceAfterTurns();
  else if (action === "continue-ending-prayer") go("credits");
  else if (action === "continue-closing") go("credits");
  else if (action === "reload") reset();
});

if (kioskLockForm) {
  kioskLockForm.addEventListener("submit", (event) => {
    event.preventDefault();
    const typed = String((kioskLockPassword && kioskLockPassword.value) || "");
    if (typed === KIOSK_EXIT_PASSWORD) {
      unlockKioskFullscreen();
      exitKioskFullscreen();
      return;
    }
    // Wrong password: close the panel and return to kiosk mode.
    dismissKioskLockToKiosk();
  });
}

if (kioskLockReturn) {
  kioskLockReturn.addEventListener("click", () => {
    armKioskFullscreen();
  });
}

document.addEventListener("fullscreenchange", onKioskFullscreenChange);
document.addEventListener("webkitfullscreenchange", onKioskFullscreenChange);
document.addEventListener("MSFullscreenChange", onKioskFullscreenChange);

window.addEventListener("keydown", (event) => {
  if (!kioskLock || kioskLock.hidden) return;
  if (event.key === "Escape") {
    event.preventDefault();
    event.stopPropagation();
  }
}, true);

// Staff shortcuts:
//   Ctrl+Shift+1..8  → that video's prayer
//   Ctrl+Shift+Alt+1..8 → that video's chat
//   Ctrl+Shift+C → credits
//   Ctrl+Shift+E → ending "Your prayer" (needs a sample offering)
window.addEventListener("keydown", (event) => {
  if (!(event.ctrlKey && event.shiftKey)) return;
  if (kioskLock && !kioskLock.hidden) return;
  const tag = (event.target && event.target.tagName) || "";
  if (tag === "INPUT" || tag === "TEXTAREA") return;

  const key = String(event.key || "");
  const lower = key.toLowerCase();

  if (lower === "c") {
    event.preventDefault();
    go("credits");
    return;
  }

  if (lower === "e") {
    event.preventDefault();
    if (!state.endingPrayerText) {
      state.endingPrayerText =
        "May we step into a world that truly loves all people.";
    }
    go("endingPrayer");
    return;
  }

  const codeMatch = /^Digit([1-9])$/.exec(event.code || "");
  const digit =
    (codeMatch ? Number(codeMatch[1]) : null) ||
    {
      1: 1,
      2: 2,
      3: 3,
      4: 4,
      5: 5,
      6: 6,
      7: 7,
      8: 8,
      9: 9,
      "!": 1,
      "@": 2,
      "#": 3,
      $: 4,
      "%": 5,
      "^": 6,
      "&": 7,
      "*": 8,
      "(": 9,
    }[key] ||
    null;
  if (!digit || digit > state.loops.length) return;
  event.preventDefault();
  jumpToLoopSection(digit - 1, { chat: event.altKey });
});

ui.addEventListener(
  "wheel",
  onPrayerWheel,
  { passive: false }
);

window.addEventListener("resize", () => {
  if (state.scene === "chat") syncChatVideoLayout();
});

ui.addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) return;
  const input = form.elements.namedItem("message");
  const text = String(input && input.value ? input.value : "").trim();
  form.reset();
  handleSend(text);
});

async function bootstrap() {
  try {
    const data = await Api.loadLoops();
    state.loops = Array.isArray(data.loops) ? data.loops : [];
    state.closing = data.closing || null;
    state.turnsPerLoop = Number(data.turnsPerLoop) || DEFAULT_TURNS_PER_LOOP;
    state.loopsMeta = {
      wrapFraction: Number(data.wrapFraction) || 0.48,
    };
    state.contentReady = state.loops.length > 0;
  } catch (err) {
    console.error("Failed to load loop content:", err);
    state.loops = [];
    state.closing = null;
    state.contentReady = false;
  }

  go("landing");
}

bootstrap();
