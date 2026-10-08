/* Tahta Kumanda - telefon arayüzü */
(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const store = {
    get(k, d) { try { const v = localStorage.getItem("tk_" + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("tk_" + k, JSON.stringify(v)); } catch { /* gizli sekme */ } },
    del(k) { try { localStorage.removeItem("tk_" + k); } catch { /* yok */ } },
  };

  // ------------------------------------------------------------- ayarlar
  const settings = {
    sens: store.get("sens", 1.8),
    scrollSpeed: store.get("scrollSpeed", 1.2),
    natural: store.get("natural", true),
    haptic: store.get("haptic", true),
    tapClick: store.get("tapClick", true),
  };
  let pin = store.get("pin", "");

  const isIOS = /iPhone|iPad|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

  // ------------------------------------------------------------- yardımcı
  let toastTimer = 0;
  function toast(text, ms = 2200) {
    const t = $("#toast");
    t.textContent = text; t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, ms);
  }
  function buzz(ms = 8) { if (settings.haptic && navigator.vibrate) { try { navigator.vibrate(ms); } catch { /* yok */ } } }

  async function api(path, body) {
    const opt = { method: body === undefined ? "GET" : "POST", headers: { "X-Pin": pin } };
    if (body !== undefined) { opt.headers["Content-Type"] = "application/json"; opt.body = JSON.stringify(body); }
    const r = await fetch(path, opt);
    let data = {};
    try { data = await r.json(); } catch { /* boş */ }
    if (r.status === 401) { showPin(data.message || "PIN hatalı"); throw new Error("auth"); }
    return data;
  }

  // ------------------------------------------------------------ WebSocket
  let ws = null, wsTimer = 0, backoff = 500, pingTimer = 0, authFailed = false;

  function setStatus(state, text) {
    const dot = $("#dot");
    dot.className = "dot" + (state === "on" ? " on" : state === "off" ? " off" : "");
    $("#statusText").textContent = text;
  }

  function connect() {
    if (!pin && pinRequired !== false) { showPin(); return; }
    clearTimeout(wsTimer);
    if (ws && (ws.readyState === 0 || ws.readyState === 1)) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    setStatus("wait", "Bağlanıyor…");
    ws = new WebSocket(`${proto}://${location.host}/ws?pin=${encodeURIComponent(pin)}`);
    authFailed = false;

    ws.onopen = () => {
      backoff = 500;
      clearInterval(pingTimer);
      pingTimer = setInterval(() => send({ t: "ping" }), 15000);
    };
    ws.onmessage = (ev) => {
      let m; try { m = JSON.parse(ev.data); } catch { return; }
      if (m.t === "hello") {
        setStatus("on", "Tahtaya bağlı");
        const b = $("#banner");
        if (m.input && !m.input.ok) { b.textContent = "Tahtada fare/klavye hazır değil: " + m.input.error; b.hidden = false; }
        else b.hidden = true;
      } else if (m.t === "auth" && !m.ok) {
        authFailed = true;
        showPin(m.reason === "blocked" ? "Çok fazla hatalı deneme, 1 dakika bekleyin" : "PIN hatalı");
      }
    };
    ws.onclose = () => {
      clearInterval(pingTimer);
      if (authFailed) { setStatus("off", "PIN gerekli"); return; }
      setStatus("off", "Bağlantı koptu, yeniden deneniyor…");
      wsTimer = setTimeout(connect, backoff);
      backoff = Math.min(backoff * 2, 5000);
    };
    ws.onerror = () => { /* onclose halleder */ };
  }

  function send(obj) {
    if (ws && ws.readyState === 1) { ws.send(JSON.stringify(obj)); return true; }
    return false;
  }

  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && (!ws || ws.readyState > 1)) { backoff = 300; connect(); }
  });

  // ---------------------------------------------------------------- PIN
  let pinRequired = null;
  function showPin(err) {
    $("#pinOverlay").hidden = false;
    const e = $("#pinErr");
    if (err) { e.textContent = err; e.hidden = false; } else e.hidden = true;
    setTimeout(() => $("#pinInput").focus(), 50);
  }
  $("#pinForm").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const val = $("#pinInput").value.trim();
    try {
      const r = await fetch("/api/auth", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pin: val }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok || !d.ok) { showPin(d.message || "PIN hatalı"); return; }
      pin = val; store.set("pin", pin);
      $("#pinOverlay").hidden = true; $("#pinInput").blur();
      backoff = 300; connect();
    } catch { showPin("Sunucuya ulaşılamadı"); }
  });

  // ============================================================ TRACKPAD
  const pad = $("#pad");
  const strip = $("#scrollStrip");
  const touches = new Map(); // id -> {x, y, t, sx, sy}
  let seq = null;            // geçerli dokunma dizisi
  let lastTapEnd = 0, lastTapX = 0, lastTapY = 0;
  let dragging = false;
  let mx = 0, my = 0, sv = 0, sh = 0, rafPending = false;

  const TAP_MS = 220, TAP_MOVE = 9, DOUBLE_MS = 300;

  function flush() {
    rafPending = false;
    const ix = Math.trunc(mx), iy = Math.trunc(my);
    if (ix || iy) { send({ t: "m", dx: ix, dy: iy }); mx -= ix; my -= iy; }
    const iv = Math.trunc(sv), ih = Math.trunc(sh);
    if (iv || ih) { send({ t: "s", v: iv, h: ih }); sv -= iv; sh -= ih; }
  }
  function schedule() { if (!rafPending) { rafPending = true; requestAnimationFrame(flush); } }

  function accel(dx, dy, dt) {
    const dist = Math.hypot(dx, dy);
    const speed = dist / Math.max(dt, 4);          // px/ms
    const boost = 1 + 1.4 * Math.min(Math.max(speed - 0.15, 0), 2.2);
    return settings.sens * boost;
  }

  function addScroll(dx, dy) {
    const k = settings.scrollSpeed * 5;            // 120 birim = 1 tekerlek çentiği
    const dir = settings.natural ? 1 : -1;
    sv += dy * k * dir;
    sh += -dx * k * dir;
    schedule();
  }

  function padStart(ev) {
    ev.preventDefault();
    pad.classList.add("active", "used");
    const now = performance.now();
    for (const t of ev.changedTouches) {
      touches.set(t.identifier, { x: t.clientX, y: t.clientY, t: now, sx: t.clientX, sy: t.clientY });
    }
    if (!seq) {
      const t0 = ev.changedTouches[0];
      const r = strip.getBoundingClientRect();
      seq = {
        start: now, maxFingers: 0, moved: false,
        stripScroll: t0.clientX >= r.left && t0.clientY >= r.top && t0.clientY <= r.bottom,
      };
      // İki kez dokun + sürükle => sol tuşu basılı tut
      if (settings.tapClick && now - lastTapEnd < DOUBLE_MS &&
          Math.hypot(t0.clientX - lastTapX, t0.clientY - lastTapY) < 60 && !seq.stripScroll) {
        dragging = true; seq.drag = true;
        send({ t: "d", b: "l" }); pad.classList.add("dragging"); buzz(12);
      }
    }
    seq.maxFingers = Math.max(seq.maxFingers, touches.size);
  }

  function padMove(ev) {
    ev.preventDefault();
    if (!seq) return;
    const now = performance.now();
    let sumDx = 0, sumDy = 0, n = 0;
    for (const t of ev.changedTouches) {
      const p = touches.get(t.identifier);
      if (!p) continue;
      const dx = t.clientX - p.x, dy = t.clientY - p.y, dt = now - p.t;
      p.x = t.clientX; p.y = t.clientY; p.t = now;
      if (Math.hypot(t.clientX - p.sx, t.clientY - p.sy) > TAP_MOVE) seq.moved = true;
      sumDx += dx; sumDy += dy; n++;
      p.dt = dt;
    }
    if (!n) return;

    if (seq.stripScroll && seq.maxFingers === 1) {
      addScroll(0, sumDy / n);
    } else if (seq.maxFingers >= 2) {
      // İki parmak: kaydırma (parmak sayısı azalsa bile dizi bitene kadar)
      if (touches.size >= 2) addScroll(sumDx / n, sumDy / n);
    } else {
      const p = touches.values().next().value;
      const g = accel(sumDx, sumDy, p ? p.dt : 16);
      mx += sumDx * g; my += sumDy * g;
      schedule();
    }
  }

  function padEnd(ev) {
    ev.preventDefault();
    for (const t of ev.changedTouches) touches.delete(t.identifier);
    if (touches.size > 0 || !seq) return;

    const now = performance.now();
    const dur = now - seq.start;
    const t0 = ev.changedTouches[0];
    flush();

    if (seq.drag) {
      send({ t: "u", b: "l" });
      dragging = false; pad.classList.remove("dragging");
      lastTapEnd = 0;
    } else if (!seq.moved && dur < TAP_MS + 80 && settings.tapClick && !seq.stripScroll) {
      if (seq.maxFingers === 1) {
        send({ t: "c", b: "l" }); buzz();
        lastTapEnd = now; lastTapX = t0.clientX; lastTapY = t0.clientY;
      } else if (seq.maxFingers === 2) {
        send({ t: "c", b: "r" }); buzz(14); lastTapEnd = 0;
      } else if (seq.maxFingers >= 3) {
        send({ t: "c", b: "m" }); buzz(14); lastTapEnd = 0;
      }
    }
    seq = null;
    pad.classList.remove("active");
  }

  pad.addEventListener("touchstart", padStart, { passive: false });
  pad.addEventListener("touchmove", padMove, { passive: false });
  pad.addEventListener("touchend", padEnd, { passive: false });
  pad.addEventListener("touchcancel", padEnd, { passive: false });
  pad.addEventListener("contextmenu", (e) => e.preventDefault());

  // Masaüstünden deneme için fare desteği
  let mouseDown = false;
  pad.addEventListener("pointerdown", (e) => { if (e.pointerType === "mouse") { mouseDown = true; pad.setPointerCapture(e.pointerId); } });
  pad.addEventListener("pointermove", (e) => {
    if (e.pointerType !== "mouse" || !mouseDown) return;
    mx += e.movementX * settings.sens; my += e.movementY * settings.sens; schedule();
  });
  pad.addEventListener("pointerup", (e) => { if (e.pointerType === "mouse") mouseDown = false; });
  pad.addEventListener("wheel", (e) => { e.preventDefault(); sv += -e.deltaY; sh += e.deltaX; schedule(); }, { passive: false });

  // ------------------------------------------------- fiziksel fare düğmeleri
  function holdButton(el, b) {
    let held = false;
    const down = (e) => { e.preventDefault(); if (held) return; held = true; el.classList.add("pressed"); send({ t: "d", b }); buzz(); };
    const up = (e) => { e.preventDefault(); if (!held) return; held = false; el.classList.remove("pressed"); send({ t: "u", b }); };
    el.addEventListener("touchstart", down, { passive: false });
    el.addEventListener("touchend", up, { passive: false });
    el.addEventListener("touchcancel", up, { passive: false });
    el.addEventListener("mousedown", down);
    el.addEventListener("mouseup", up);
    el.addEventListener("mouseleave", (e) => { if (held) up(e); });
    el.addEventListener("contextmenu", (e) => e.preventDefault());
  }
  holdButton($("#btnL"), "l");
  holdButton($("#btnR"), "r");
  holdButton($("#btnM"), "m");

  // Dokunulduğunda odak kaybettirmeyen buton (klavye açık kalsın)
  function onTap(el, fn) {
    let touched = false;
    el.addEventListener("touchstart", (e) => { e.preventDefault(); touched = true; el.classList.add("pressed"); }, { passive: false });
    el.addEventListener("touchend", (e) => {
      e.preventDefault(); el.classList.remove("pressed");
      if (touched) { touched = false; fn(e); }
    }, { passive: false });
    el.addEventListener("touchcancel", () => { touched = false; el.classList.remove("pressed"); });
    el.addEventListener("click", (e) => { if (!touched) fn(e); });
  }

  function bindKeyButtons(root) {
    root.querySelectorAll("[data-key],[data-combo]").forEach((el) => {
      onTap(el, () => {
        if (el.dataset.key) send({ t: "k", k: el.dataset.key });
        else send({ t: "combo", k: el.dataset.combo.split(",") });
        buzz();
      });
    });
  }

  // ============================================================ KLAVYE
  const kb = $("#kbInput");
  const keybar = $("#keybar");
  const SENT = " ";   // Boş alanda da Geri Sil çalışsın diye bekçi karakter
  let prev = SENT, composing = false, kbOpen = false;

  function resetKb() {
    kb.value = SENT; prev = SENT;
    try { kb.setSelectionRange(SENT.length, SENT.length); } catch { /* yok */ }
  }

  function openKeyboard() {
    resetKb();
    kb.focus({ preventScroll: true });
  }
  function closeKeyboard() { kb.blur(); }

  kb.addEventListener("focus", () => {
    kbOpen = true; keybar.hidden = false; document.body.classList.add("kb-open");
    $("#btnKeyboard").classList.add("on"); resetKb(); updateViewport();
  });
  kb.addEventListener("blur", () => {
    kbOpen = false; keybar.hidden = true; document.body.classList.remove("kb-open");
    $("#btnKeyboard").classList.remove("on"); updateViewport();
  });
  kb.addEventListener("compositionstart", () => { composing = true; });
  kb.addEventListener("compositionend", () => { composing = false; maybeReset(); });

  // Değişikliği farka göre gönder: Android'de otomatik düzeltme/öneri de doğru çalışır
  kb.addEventListener("input", () => {
    const cur = kb.value;
    const n = Math.min(prev.length, cur.length);
    let i = 0;
    while (i < n && prev[i] === cur[i]) i++;
    const del = prev.length - i;
    const ins = cur.slice(i);
    if (del > 0) send({ t: "k", k: "backspace", n: del });
    if (ins) send({ t: "txt", v: ins });
    prev = cur;
    maybeReset();
  });

  function maybeReset() {
    if (composing) return;
    const v = kb.value;
    if (v.length < SENT.length || !v.startsWith(SENT) || v.endsWith("\n") || v.length > 400) resetKb();
  }

  // Harici/Bluetooth klavyeler ve "input" üretmeyen tuşlar
  const KEYDOWN_MAP = {
    ArrowLeft: "left", ArrowRight: "right", ArrowUp: "up", ArrowDown: "down",
    Escape: "esc", Tab: "tab", Home: "home", End: "end", PageUp: "pageup", PageDown: "pagedown", Delete: "delete",
  };
  kb.addEventListener("keydown", (e) => {
    if (e.isComposing || e.keyCode === 229) return;
    const k = KEYDOWN_MAP[e.key];
    if (k) { e.preventDefault(); send({ t: "k", k }); return; }
    if ((e.ctrlKey || e.metaKey) && e.key.length === 1) { e.preventDefault(); send({ t: "combo", k: ["ctrl", e.key.toLowerCase()] }); }
  });

  bindKeyButtons(keybar);
  onTap($("#kbClose"), closeKeyboard);
  $("#btnKeyboard").addEventListener("click", () => { kbOpen ? closeKeyboard() : (closeSheets(), openKeyboard()); });

  // Ekran klavyesi açılınca görünür alanı ayarla (özellikle iOS)
  function updateViewport() {
    const vv = window.visualViewport;
    const h = vv ? vv.height : window.innerHeight;
    const top = vv ? vv.offsetTop : 0;
    const root = document.documentElement.style;
    root.setProperty("--vvh", h + "px");
    $("#app").style.top = top + "px";
    const bottomGap = vv ? Math.max(0, window.innerHeight - (vv.height + vv.offsetTop)) : 0;
    root.setProperty("--kb-bottom", bottomGap + "px");
    root.setProperty("--kb-h", (kbOpen ? keybar.offsetHeight : 0) + "px");
  }
  if (window.visualViewport) {
    visualViewport.addEventListener("resize", updateViewport);
    visualViewport.addEventListener("scroll", updateViewport);
  }
  window.addEventListener("resize", updateViewport);
  updateViewport();

  // ============================================================ PANELLER
  const backdrop = $("#backdrop");
  let openSheetId = null, castPoll = 0;

  function openSheet(id) {
    closeKeyboard();
    if (openSheetId === id) { closeSheets(); return; }
    closeSheets();
    $(id).hidden = false; backdrop.hidden = false; openSheetId = id;
    if (id === "#sheetCast") { refreshCast(); castPoll = setInterval(refreshCast, 3000); }
    if (id === "#sheetSettings") refreshInfo();
    if (id === "#sheetFiles") { refreshFiles(); setBadge(0); }
  }
  function closeSheets() {
    $$(".sheet").forEach((s) => { s.hidden = true; });
    backdrop.hidden = true; openSheetId = null;
    clearInterval(castPoll);
  }
  backdrop.addEventListener("click", closeSheets);
  $$(".sheet-handle").forEach((h) => h.addEventListener("click", closeSheets));

  $("#btnPresent").addEventListener("click", () => openSheet("#sheetPresent"));
  $("#btnCast").addEventListener("click", () => openSheet("#sheetCast"));
  $("#btnFiles").addEventListener("click", () => openSheet("#sheetFiles"));
  $("#btnSettings").addEventListener("click", () => openSheet("#sheetSettings"));
  bindKeyButtons($("#sheetPresent"));

  // ------------------------------------------------------- yansıtma paneli
  function selectTab(name) {
    $$(".tab").forEach((t) => t.classList.toggle("on", t.dataset.tab === name));
    $$(".tab-body").forEach((b) => { b.hidden = b.dataset.body !== name; });
    store.set("castTab", name);
  }
  $$(".tab").forEach((t) => t.addEventListener("click", () => selectTab(t.dataset.tab)));
  selectTab(store.get("castTab", isIOS ? "ios" : "android"));

  function castMsg(text, ok) {
    const m = $("#castMsg");
    m.textContent = text; m.hidden = !text;
    m.className = "msg " + (ok === true ? "ok" : ok === false ? "bad" : "");
  }

  async function refreshCast() {
    try {
      const s = await api("/api/status");
      const a = s.cast.airplay, d = s.cast.android;
      $("#airplayName").textContent = a.name;
      const as = $("#airplayState");
      if (!a.available) { as.textContent = "UxPlay kurulu değil (tahtada: sudo apt install uxplay)"; as.className = "state bad"; }
      else if (a.running) { as.textContent = `● AirPlay alıcısı hazır: "${a.name}"`; as.className = "state ok"; }
      else { as.textContent = "AirPlay alıcısı başlatılıyor…"; as.className = "state"; }

      const ds = $("#androidState");
      if (!d.available) { ds.textContent = "scrcpy/adb kurulu değil (install.sh'i çalıştırın)"; ds.className = "state bad"; }
      else if (d.running) { ds.textContent = `● Yansıtılıyor (${d.serial})`; ds.className = "state ok"; }
      else { ds.textContent = "Hazır — yansıtma kapalı"; ds.className = "state"; }
      $("#pairBox").open = !store.get("paired", false);
    } catch { /* bağlantı yok */ }
  }

  async function busy(btn, fn) {
    btn.disabled = true; const old = btn.textContent; btn.textContent = "Lütfen bekleyin…";
    try { await fn(); } catch (e) { if (e.message !== "auth") castMsg("Sunucuya ulaşılamadı", false); }
    finally { btn.disabled = false; btn.textContent = old; refreshCast(); }
  }

  $("#btnPair").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const r = await api("/api/cast/android/pair", { port: $("#pairPort").value.trim(), code: $("#pairCode").value.trim() });
    castMsg(r.message, r.ok);
    if (r.ok) { store.set("paired", true); $("#pairCode").value = ""; }
  }));
  $("#btnConnect").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    castMsg("Telefona bağlanılıyor…");
    const port = $("#connPort").value.trim();
    const r = await api("/api/cast/android/connect", { port: port || null });
    castMsg(r.message, r.ok);
    if (r.ok) { store.set("paired", true); buzz(20); }
  }));
  $("#btnStopAndroid").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const r = await api("/api/cast/android/stop", {});
    castMsg(r.message, r.ok);
  }));
  $("#btnAirplayRestart").addEventListener("click", (e) => busy(e.currentTarget, async () => {
    const r = await api("/api/cast/airplay/restart", {});
    castMsg(r.message, r.ok);
  }));

  // ------------------------------------------------------- dosya aktarımı
  const fileInput = $("#fileInput");
  const uploadList = $("#uploadList");
  const queue = [];
  let uploading = null, doneCount = 0;

  settings.openAfter = store.get("openAfter", false);
  $("#openAfter").checked = settings.openAfter;
  $("#openAfter").addEventListener("change", (e) => { settings.openAfter = e.target.checked; store.set("openAfter", settings.openAfter); });

  function fmtSize(n) {
    if (n < 1024) return n + " B";
    const u = ["KB", "MB", "GB"]; let i = -1;
    do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
    return (n < 10 ? n.toFixed(1) : Math.round(n)) + " " + u[i];
  }
  function fmtTime(sec) {
    const d = new Date(sec * 1000), now = new Date();
    const hm = d.toLocaleTimeString("tr-TR", { hour: "2-digit", minute: "2-digit" });
    if (d.toDateString() === now.toDateString()) return "Bugün " + hm;
    return d.toLocaleDateString("tr-TR", { day: "numeric", month: "short" }) + " " + hm;
  }
  function kind(name) {
    const ext = (name.split(".").pop() || "").toLowerCase();
    if (["jpg", "jpeg", "png", "gif", "webp", "heic", "heif", "bmp", "svg"].includes(ext)) return ["img", ext];
    if (["mp4", "mov", "mkv", "avi", "webm", "3gp", "mp3", "m4a", "wav", "ogg"].includes(ext)) return ["vid", ext];
    if (["pdf", "doc", "docx", "odt", "ppt", "pptx", "odp", "xls", "xlsx", "ods", "txt"].includes(ext)) return ["doc", ext];
    return ["", ext.slice(0, 4) || "?"];
  }
  function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function setBadge(n) {
    doneCount = n;
    const b = $("#filesBadge");
    b.textContent = n; b.hidden = !n;
  }

  $("#btnPick").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    for (const f of fileInput.files) addUpload(f);
    fileInput.value = "";
    pump();
  });

  function addUpload(file) {
    const li = el("li");
    const top = el("div", "up-top");
    const name = el("span", "up-name", file.name);
    const pct = el("span", "up-pct", fmtSize(file.size));
    const x = el("button", "up-x", "✕");
    x.setAttribute("aria-label", "İptal");
    top.append(name, pct, x);
    const bar = el("div", "bar"); const fill = el("i"); bar.append(fill);
    const msg = el("div", "up-msg", "Sırada");
    li.append(top, bar, msg);
    uploadList.prepend(li);
    const job = { file, li, fill, pct, msg, xhr: null, state: "queued" };
    x.addEventListener("click", () => {
      if (job.state === "queued") { job.state = "cancelled"; li.remove(); }
      else if (job.state === "uploading" && job.xhr) job.xhr.abort();
      else li.remove();
    });
    queue.push(job);
  }

  function finish(job, ok, text) {
    job.state = ok ? "done" : "fail";
    job.li.classList.add(ok ? "done" : "fail");
    job.msg.textContent = text;
    if (ok) { job.fill.style.width = "100%"; job.pct.textContent = fmtSize(job.file.size); }
    uploading = null;
    pump();
  }

  function pump() {
    if (uploading) return;
    const job = queue.shift();
    if (!job) { refreshFiles(); return; }
    if (job.state === "cancelled") { pump(); return; }
    uploading = job;
    job.state = "uploading";
    const xhr = new XMLHttpRequest();
    job.xhr = xhr;
    const q = `name=${encodeURIComponent(job.file.name)}&open=${settings.openAfter ? 1 : 0}`;
    xhr.open("PUT", "/api/files/upload?" + q);
    xhr.setRequestHeader("X-Pin", pin);
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    const t0 = performance.now();
    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable) return;
      const p = e.loaded / e.total;
      job.fill.style.width = (p * 100).toFixed(1) + "%";
      job.pct.textContent = Math.floor(p * 100) + "%";
      const secs = (performance.now() - t0) / 1000;
      if (secs > 0.5) {
        const rate = e.loaded / secs;
        const left = (e.total - e.loaded) / Math.max(rate, 1);
        job.msg.textContent = `${fmtSize(rate)}/sn · ${left < 60 ? Math.ceil(left) + " sn" : Math.ceil(left / 60) + " dk"} kaldı`;
      } else job.msg.textContent = "Gönderiliyor…";
    };
    xhr.onload = () => {
      let d = {};
      try { d = JSON.parse(xhr.responseText); } catch { /* boş */ }
      if (xhr.status === 401) { finish(job, false, "PIN hatalı"); showPin(d.message); return; }
      if (xhr.status === 200 && d.ok) {
        finish(job, true, (settings.openAfter ? "Gönderildi, tahtada açılıyor: " : "Tahtaya gönderildi: ") + d.name);
        buzz(15);
        if (openSheetId !== "#sheetFiles") setBadge(doneCount + 1);
      } else finish(job, false, d.message || "Gönderilemedi");
    };
    xhr.onerror = () => finish(job, false, "Bağlantı koptu");
    xhr.onabort = () => finish(job, false, "İptal edildi");
    xhr.send(job.file);
  }

  window.addEventListener("beforeunload", (e) => {
    if (uploading || queue.length) { e.preventDefault(); e.returnValue = ""; }
  });

  async function refreshFiles() {
    const list = $("#fileList");
    let d;
    try { d = await api("/api/files"); } catch { return; }
    if (!d.ok) { $("#filesInfo").textContent = d.message || ""; return; }
    list.textContent = "";
    if (!d.files.length) list.append(el("li", "empty", "Henüz dosya yok. Tahtadaki klasöre konan dosyalar da burada görünür."));
    for (const f of d.files) list.append(fileRow(f));
    $("#filesInfo").textContent = `Tahtadaki klasör: ${d.dir} · Boş yer: ${fmtSize(d.free)}`;
  }

  function fileRow(f) {
    const li = el("li");
    const [k, ext] = kind(f.name);
    const ico = el("div", "f-ico " + k, ext);
    const main = el("div", "f-main");
    main.append(el("div", "f-name", f.name), el("div", "f-meta", `${fmtSize(f.size)} · ${fmtTime(f.mtime)}`));
    const act = el("div", "f-act");
    const open = el("button", "", "Aç");
    open.title = "Tahtada aç";
    open.addEventListener("click", async () => {
      try { const r = await api("/api/files/open", { name: f.name }); toast(r.ok ? "Tahtada açılıyor" : r.message); } catch { /* yok */ }
    });
    const dl = el("a", "", "İndir");
    dl.href = `/api/files/download/${encodeURIComponent(f.name)}?pin=${encodeURIComponent(pin)}`;
    dl.setAttribute("download", f.name);
    const del = el("button", "del", "Sil");
    let armed = 0;
    del.addEventListener("click", async () => {
      if (!armed) {
        del.classList.add("confirm"); del.textContent = "Emin mi?";
        armed = setTimeout(() => { armed = 0; del.classList.remove("confirm"); del.textContent = "Sil"; }, 3000);
        return;
      }
      clearTimeout(armed);
      try { const r = await api("/api/files/delete", { name: f.name }); if (r.ok) li.remove(); else toast(r.message); } catch { /* yok */ }
    });
    act.append(open, dl, del);
    li.append(ico, main, act);
    return li;
  }

  $("#btnRefreshFiles").addEventListener("click", refreshFiles);
  $("#btnOpenFolder").addEventListener("click", async () => {
    try { const r = await api("/api/files/open", {}); toast(r.ok ? "Klasör tahtada açılıyor" : r.message); } catch { /* yok */ }
  });

  // ---------------------------------------------------------- ayarlar
  function bindSlider(id, key, fmt) {
    const el = $("#" + id), out = $("#" + fmt);
    el.value = settings[key]; out.textContent = Number(settings[key]).toFixed(1) + "×";
    el.addEventListener("input", () => {
      settings[key] = parseFloat(el.value); store.set(key, settings[key]);
      out.textContent = settings[key].toFixed(1) + "×";
    });
  }
  bindSlider("sens", "sens", "sensOut");
  bindSlider("scrollSpeed", "scrollSpeed", "scrollOut");
  ["natural", "haptic", "tapClick"].forEach((k) => {
    const el = $("#" + k); el.checked = settings[k];
    el.addEventListener("change", () => { settings[k] = el.checked; store.set(k, el.checked); });
  });
  $("#btnShowPanel").addEventListener("click", async () => {
    try { await api("/api/panel/show", {}); toast("Panel tahtada gösteriliyor"); closeSheets(); } catch { /* yok */ }
  });
  $("#btnLogout").addEventListener("click", () => {
    store.del("pin"); pin = ""; if (ws) { authFailed = true; ws.close(); } closeSheets(); showPin();
  });

  async function refreshInfo() {
    try {
      const s = await api("/api/status");
      $("#serverInfo").innerHTML =
        `Sunucu: <b>${s.url}</b><br>Telefon IP: ${s.your_ip}<br>Bağlı cihaz: ${s.clients}<br>` +
        `Klavye düzeni: ${s.input.layout.toUpperCase()}` + (s.input.ok ? "" : `<br><span class="err">${s.input.error}</span>`);
    } catch { /* yok */ }
  }

  // ------------------------------------------------------------ başlangıç
  (async () => {
    // PIN kapalı mı? Boş PIN ile dene.
    if (!pin) {
      try {
        const r = await fetch("/api/info");
        pinRequired = (await r.json()).pin_required !== false;
      } catch { pinRequired = true; }
    }
    connect();
  })();
})();
