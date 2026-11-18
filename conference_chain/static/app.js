/* ConfChain dashboard: a single-page app that talks to any node's REST API. */
(() => {
  // ------------------------------------------------------------------ helpers
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const short = (h, n = 10) => (h ? `${h.slice(0, n)}…` : "");
  const time = (ts) => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const dateTime = (ts) => new Date(ts * 1000).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const fmt = (n) => Number(n || 0).toLocaleString();
  const store = {
    get: (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch { return d; } },
    set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* private mode */ } },
  };

  const S = {
    api: store.get("confchain.node", location.origin),
    summary: null,
    nodes: {},          // url -> {name, miner_address}
    sessions: [],
    page: "dashboard",
    lastHeight: null,
  };

  async function api(path, opts = {}, base = S.api) {
    const r = await fetch(base + path, {
      ...opts,
      headers: { "Content-Type": "application/json" },
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    const data = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(data.error || data.reason || `HTTP ${r.status}`);
    return data;
  }

  function toast(msg, kind = "") {
    const el = document.createElement("div");
    el.className = `toast ${kind}`;
    el.innerHTML = msg;
    $("#toasts").appendChild(el);
    setTimeout(() => el.remove(), 4500);
  }

  function modal(html) {
    $("#modal-body").innerHTML = html;
    $("#modal").showModal();
  }

  const minerName = (addr) => {
    const n = Object.values(S.nodes).find((x) => x.miner_address === addr);
    return n ? n.name : short(addr, 12);
  };
  const sessionTitle = (sid) => (S.sessions.find((s) => s.session_id === sid) || {}).title || sid;
  const typeBadge = (t) => `<span class="badge ${t === "REGISTER" ? "b-info" : t === "ATTENDANCE" ? "b-ok" : "b-mute"}">${t}</span>`;

  // ------------------------------------------------------------------ node discovery & chrome
  async function discoverNodes() {
    const urls = new Set([location.origin, S.api]);
    try {
      const s = await api("/api/summary", {}, location.origin);
      s.peers.forEach((p) => urls.add(p.url.replace("127.0.0.1", location.hostname)));
    } catch { /* ignore */ }
    await Promise.all([...urls].map(async (u) => {
      try {
        const s = await api("/api/summary", {}, u);
        S.nodes[u] = { name: s.node, miner_address: s.miner_address, online: true };
      } catch { S.nodes[u] = { ...(S.nodes[u] || { name: u }), online: false }; }
    }));
    const sel = $("#node-select");
    sel.innerHTML = Object.entries(S.nodes).sort((a, b) => a[1].name.localeCompare(b[1].name))
      .map(([u, n]) => `<option value="${esc(u)}" ${u === S.api ? "selected" : ""}>${esc(n.name)} · ${esc(u.replace(/^https?:\/\//, ""))}</option>`).join("");
  }

  $("#node-select").addEventListener("change", (e) => {
    S.api = e.target.value;
    store.set("confchain.node", S.api);
    S.lastHeight = null;
    toast(`Switched to <b>${esc(S.nodes[S.api]?.name)}</b>. Each node keeps its own copy of the chain and pending pool.`);
    render();
  });

  function renderChrome() {
    const s = S.summary;
    if (!s) return;
    $("#conf-name").textContent = s.conference;
    const miningDot = s.mining.active ? `<span class="dot pulse"></span>` : "";
    $("#topbar-stats").innerHTML = `
      <span class="chip"><span class="dot on"></span><b>${esc(s.node)}</b></span>
      <span class="chip">Height <b>${fmt(s.height)}</b></span>
      <span class="chip">Difficulty <b>${s.difficulty_bits.toFixed(2)} bits</b></span>
      <span class="chip">Pending <b>${s.pending}</b></span>
      <span class="chip">${miningDot}${s.mining.active ? `Mining #${s.mining.height}` : s.auto_mine ? "Auto-mine on" : "Miner idle"}</span>`;
    $("#node-foot").innerHTML = `<div style="margin-bottom:6px;color:#aab">Peers</div>` + s.peers.map((p) =>
      `<div class="peer"><span>${esc(S.nodes[p.url.replace("127.0.0.1", location.hostname)]?.name || p.url)}</span>
       <span><span class="dot ${p.online === false ? "off" : "on"}"></span></span></div>`).join("");
  }

  // ------------------------------------------------------------------ router
  const PAGES = {};
  let current = null;

  function render() {
    const page = (location.hash || "#dashboard").slice(1);
    S.page = PAGES[page] ? page : "dashboard";
    $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.page === S.page));
    current = PAGES[S.page];
    $("#page-title").textContent = current.title;
    $("#page").innerHTML = current.html();
    current.mount?.();
    current.update?.();
  }
  window.addEventListener("hashchange", render);

  async function tick() {
    try {
      S.summary = await api("/api/summary");
      renderChrome();
      await current?.update?.();
      S.lastHeight = S.summary.height;
    } catch (e) {
      $("#topbar-stats").innerHTML = `<span class="chip"><span class="dot off"></span><b>Node offline</b> ${esc(S.api)}</span>`;
    }
  }

  // ------------------------------------------------------------------ chain strip / feed widgets
  function chainStrip(blocks) {
    const ordered = [...blocks].reverse();
    return ordered.map((b, i) => `${i ? '<div class="link"></div>' : ""}
      <div class="blk ${S.lastHeight !== null && b.index > S.lastHeight ? "new" : ""}" data-block="${b.index}">
        <div class="n">#${b.index}</div>
        <div class="h">${short(b.hash, 14)}</div>
        <div class="meta">${b.index === 0 ? "Genesis" : `${b.records} record${b.records === 1 ? "" : "s"} · ${b.bits.toFixed(1)} bits`}</div>
        <div class="meta">${b.index === 0 ? "Conference program" : esc(minerName(b.miner))}</div>
      </div>`).join("");
  }

  const LEVEL = { block: "b-info", mined: "b-ok", reject: "b-bad", warn: "b-warn", difficulty: "b-info", reorg: "b-warn", info: "b-mute" };
  function feed(events) {
    if (!events.length) return `<div class="empty">No activity yet</div>`;
    return `<ul class="feed">${events.map((e) => `<li><span class="t">${time(e.time)}</span>
      <span><span class="badge ${LEVEL[e.level] || "b-mute"}">${esc(e.level)}</span> ${esc(e.message)}</span></li>`).join("")}</ul>`;
  }

  function bindBlockClicks(root = document) {
    $$("[data-block]", root).forEach((el) => el.onclick = () => showBlock(+el.dataset.block));
  }

  async function showBlock(idx) {
    const b = await api(`/api/block/${idx}`);
    const rows = b.transactions.map((t) => `<tr><td>${typeBadge(t.type)}</td>
      <td>${t.type === "REGISTER" ? esc(t.name) + " &lt;" + esc(t.email) + "&gt;" : t.type === "ATTENDANCE" ? `${esc(t.attendee_id)} → <b>${esc(t.session_id)}</b>` : t.type === "COINBASE" ? `${t.amount} CONF → ${esc(minerName(t.miner))}` : esc(t.conference || "")}</td>
      <td class="mono">${short(t.txid, 12)}</td></tr>`).join("");
    modal(`<h2 style="margin-top:0">Block #${b.index}</h2>
      <dl class="kv">
        <dt>Hash</dt><dd class="mono">${b.hash}</dd>
        <dt>Previous hash</dt><dd class="mono">${b.previous_hash}</dd>
        <dt>Merkle root</dt><dd class="mono">${b.merkle_root}</dd>
        <dt>Target</dt><dd class="mono">${b.target}</dd>
        <dt>Nonce</dt><dd>${fmt(b.nonce)}</dd>
        <dt>Timestamp</dt><dd>${dateTime(b.timestamp)}</dd>
        <dt>Miner</dt><dd>${esc(minerName(b.miner))} <span class="mono">${esc(b.miner)}</span></dd>
      </dl>
      <h3>Transactions (${b.transactions.length})</h3>
      <div class="table-wrap"><table><tr><th>Type</th><th>Content</th><th>txid</th></tr>${rows}</table></div>`);
  }

  async function showVerify(txid) {
    try {
      const v = await api(`/api/verify/${txid}`);
      modal(`<h2 style="margin-top:0">Signature verification</h2>
        <p class="sub">Re-checked by ${esc(S.summary.node)} with the attendee's registered public key (ECDSA P-256, SHA-256).</p>
        <div class="callout ${v.valid ? "ok" : "bad"}"><b>${v.valid ? "VALID" : "INVALID"}</b> · in block #${v.block} with ${v.confirmations} confirmation(s)</div>
        <h3>Signed message (canonical JSON)</h3><pre class="json">${esc(v.signed_payload)}</pre>
        <dl class="kv"><dt>Public key</dt><dd class="mono">${esc(v.public_key)}</dd><dt>Signature</dt><dd class="mono">${esc(v.signature)}</dd></dl>`);
    } catch (e) { toast(esc(e.message), "bad"); }
  }
  window.showVerify = showVerify;

  // ================================================================== DASHBOARD
  PAGES.dashboard = {
    title: "Dashboard",
    html: () => `
      <div class="stats" id="d-stats"></div>
      <div class="card" style="margin-bottom:16px">
        <div class="card-head"><div><h2>Latest blocks</h2><p class="sub">Each block stores the hash of the one before it. Click a block to inspect it.</p></div>
        <a class="btn ghost sm" href="#explorer">Explorer</a></div>
        <div class="chain-strip" id="d-chain"></div>
      </div>
      <div class="grid g-side">
        <div class="card"><h2>Live activity on this node</h2><p class="sub">Gossip, pending records, mining, rejections, and difficulty retargets.</p><div id="d-feed"></div></div>
        <div class="grid">
          <div class="card"><h2>Sessions</h2><p class="sub">Confirmed attendance per session</p><div id="d-sessions"></div></div>
          <div class="card"><h2>Miner rewards</h2><p class="sub">Coinbase payouts, ${S.summary?.block_reward ?? 50} CONF per block</p><div id="d-rewards"></div></div>
        </div>
      </div>`,
    async update() {
      const s = S.summary; if (!s) return;
      const [blocks, events, sessions] = await Promise.all([api("/api/blocks?limit=8"), api("/api/events?limit=40"), api("/api/sessions")]);
      S.sessions = sessions;
      $("#d-stats").innerHTML = [
        ["Chain height", fmt(s.height), `tip ${short(s.tip_hash, 8)}`],
        ["Difficulty", s.difficulty_bits.toFixed(2), `bits · next ${s.next_difficulty_bits.toFixed(2)}`],
        ["Registered", fmt(s.registered), "attendees on chain"],
        ["Attendance", fmt(s.attendance_records), "signed certificates"],
        ["Pending pool", fmt(s.pending), "awaiting a miner"],
        ["Hash rate", fmt(s.mining.hashrate), "H/s on this node"],
      ].map(([l, v, h]) => `<div class="stat"><div class="label">${l}</div><div class="value">${v}</div><div class="hint">${h}</div></div>`).join("");
      $("#d-chain").innerHTML = chainStrip(blocks);
      bindBlockClicks($("#d-chain"));
      $("#d-feed").innerHTML = feed(events);
      const max = Math.max(1, s.registered);
      $("#d-sessions").innerHTML = sessions.map((x) => `
        <div style="margin-bottom:10px"><div style="display:flex;justify-content:space-between;font-size:13px">
          <span><b>${x.session_id}</b> ${esc(x.title)}</span><span>${x.attended}/${s.registered}</span></div>
          <div class="bar" style="margin-top:4px"><div style="animation:none;margin:0;width:${(x.attended / max) * 100}%;background:var(--ok)"></div></div></div>`).join("");
      const bal = Object.entries(s.balances).sort((a, b) => b[1] - a[1]);
      $("#d-rewards").innerHTML = bal.length ? `<div class="table-wrap"><table><tr><th>Miner</th><th>Balance</th></tr>${bal.map(([a, v]) =>
        `<tr><td>${esc(minerName(a))}<div class="mono" style="color:var(--muted)">${esc(a)}</div></td><td><b>${fmt(v)}</b> CONF</td></tr>`).join("")}</table></div>` : `<div class="empty">No blocks mined yet</div>`;
    },
  };

  // ================================================================== WALLET
  PAGES.wallet = {
    title: "Wallet & Registration",
    html: () => `
      <div class="grid g-side">
        <div class="card">
          <h2>My wallets in this browser</h2>
          <p class="sub">Private keys never leave this browser. They are stored encrypted (AES-256-GCM, key from your password via PBKDF2) and unlocked as non-extractable Web Crypto keys.</p>
          <div class="wallets" id="w-list"></div>
        </div>
        <div class="grid" style="align-content:start">
          <div class="card">
            <h2>Create attendee wallet</h2>
            <p class="sub">Generates an ECDSA P-256 key pair locally.</p>
            <form id="w-create">
              <label class="f">Full name<input name="name" required maxlength="80" placeholder="e.g. Alice Chan"></label>
              <label class="f">Email (unique identifier)<input name="email" type="email" required placeholder="alice@connect.edu"></label>
              <label class="f">Wallet password<input name="pw" type="password" required minlength="6" autocomplete="new-password"></label>
              <button class="btn" type="submit">Generate key pair</button>
            </form>
          </div>
          <div class="card">
            <h2>Import keystore</h2>
            <p class="sub">Load a wallet file exported here or created with the Python CLI wallet.</p>
            <input type="file" id="w-import" accept=".json,application/json">
          </div>
        </div>
      </div>`,
    mount() {
      $("#w-create").onsubmit = async (e) => {
        e.preventDefault();
        const f = new FormData(e.target);
        const btn = e.target.querySelector("button"); btn.disabled = true; btn.textContent = "Generating…";
        try {
          const ks = await Wallet.create(f.get("name"), f.get("email"), f.get("pw"));
          await Wallet.unlock(ks.attendee_id, f.get("pw"));
          toast(`Wallet created for <b>${esc(ks.name)}</b><br><span class="mono">${ks.attendee_id}</span>`, "ok");
          e.target.reset(); this.drawList();
        } catch (err) { toast(esc(err.message), "bad"); }
        btn.disabled = false; btn.textContent = "Generate key pair";
      };
      $("#w-import").onchange = async (e) => {
        try {
          const ks = await Wallet.importKeystore(JSON.parse(await e.target.files[0].text()));
          toast(`Imported wallet for <b>${esc(ks.name)}</b>`, "ok"); this.drawList();
        } catch (err) { toast(esc(err.message), "bad"); }
        e.target.value = "";
      };
      this.drawList();
    },
    async drawList() {
      const ws = Wallet.list();
      const el = $("#w-list");
      if (!ws.length) { el.innerHTML = `<div class="empty">No wallets yet. Create one to get started.</div>`; return; }
      const statuses = await Promise.all(ws.map((w) => api(`/api/query/status?q=${encodeURIComponent(w.attendee_id)}`).catch(() => ({ status: "?" }))));
      el.innerHTML = ws.map((w, i) => {
        const st = statuses[i];
        const badge = st.status === "CONFIRMED" ? `<span class="badge b-ok">Registered · ${st.confirmations} conf.</span>`
          : st.status === "PENDING" ? `<span class="badge b-warn">Registration pending</span>` : `<span class="badge b-mute">Not registered</span>`;
        const unlocked = Wallet.isUnlocked(w.attendee_id);
        return `<div class="wallet" data-id="${w.attendee_id}">
          <div class="top"><span class="name">${esc(w.name)}</span><span>${badge} <span class="badge ${unlocked ? "b-info" : "b-mute"}">${unlocked ? "Unlocked" : "Locked"}</span></span></div>
          <dl class="kv"><dt>Attendee ID</dt><dd class="mono">${w.attendee_id}</dd><dt>Email</dt><dd>${esc(w.email)}</dd>
          <dt>Public key</dt><dd class="mono">${short(w.public_key, 40)}</dd><dt>Private key</dt><dd>Encrypted · ${esc(w.crypto.cipher)} / ${esc(w.crypto.kdf)} (${fmt(w.crypto.iterations)} iter.)</dd></dl>
          <div class="actions">
            ${unlocked ? `<button class="btn ghost sm" data-act="lock">Lock</button>` : `<input type="password" placeholder="Password" style="max-width:160px;margin:0" data-pw><button class="btn ghost sm" data-act="unlock">Unlock</button>`}
            ${st.status === "NOT_REGISTERED" ? `<button class="btn sm" data-act="register">Sign &amp; register on chain</button>` : ""}
            <button class="btn ghost sm" data-act="export">Export keystore</button>
            <button class="btn ghost sm" data-act="remove">Remove</button>
          </div></div>`;
      }).join("");
      $$(".wallet", el).forEach((card) => {
        const id = card.dataset.id;
        $$("[data-act]", card).forEach((b) => b.onclick = async () => {
          const act = b.dataset.act;
          try {
            if (act === "unlock") { await Wallet.unlock(id, $("[data-pw]", card).value); toast("Wallet unlocked", "ok"); }
            if (act === "lock") Wallet.lock(id);
            if (act === "register") {
              if (!Wallet.isUnlocked(id)) throw new Error("Unlock the wallet first");
              const tx = await Wallet.registration(id);
              const r = await api("/api/tx", { method: "POST", body: tx });
              toast(`Registration signed and broadcast to ${r.broadcast_to.length} peer(s)<br><span class="mono">${short(r.txid, 16)}</span>`, "ok");
            }
            if (act === "export") {
              const blob = new Blob([JSON.stringify(Wallet.get(id), null, 2)], { type: "application/json" });
              const a = Object.assign(document.createElement("a"), { href: URL.createObjectURL(blob), download: `${id}.json` });
              a.click(); URL.revokeObjectURL(a.href);
            }
            if (act === "remove" && confirm("Remove this wallet from the browser? Export it first if you need it again.")) Wallet.remove(id);
            this.drawList();
          } catch (err) { toast(esc(err.message), "bad"); }
        });
      });
    },
    async update() { if (S.lastHeight !== null && S.summary.height !== S.lastHeight) this.drawList(); },
  };

  // ================================================================== CHECK-IN
  const checkin = { wallet: null, session: null, last: null };
  PAGES.checkin = {
    title: "Session Check-in",
    html: () => `
      <div class="grid g-side">
        <div class="card">
          <h2>1. Choose attendee and session</h2>
          <p class="sub">The attendance certificate {attendee_id, session_id, timestamp} is signed with the attendee's private key in this browser.</p>
          <div class="row">
            <label class="f">Attendee wallet<select id="c-wallet"></select></label>
            <label class="f" id="c-pw-wrap">Password<input id="c-pw" type="password" placeholder="Unlock to sign"></label>
          </div>
          <div class="sessions" id="c-sessions"></div>
          <label style="display:flex;gap:8px;align-items:center;margin-top:14px;font-size:13px;color:var(--muted)">
            <input type="checkbox" id="c-forge" style="width:auto;margin:0"> Attack demo: after signing, change the session to <select id="c-forge-to" style="width:auto;margin:0;padding:4px"></select>
          </label>
          <div style="margin-top:14px"><button class="btn" id="c-go" disabled>Sign &amp; broadcast certificate</button></div>
        </div>
        <div class="card">
          <h2>2. Track the certificate</h2>
          <p class="sub">Sign → broadcast → pending pool of every node → verified by a miner → in a block.</p>
          <div class="steps" id="c-steps"></div>
          <div id="c-result"><div class="empty">Nothing submitted yet</div></div>
        </div>
      </div>`,
    mount() {
      const ws = Wallet.list();
      $("#c-wallet").innerHTML = ws.length ? ws.map((w) => `<option value="${w.attendee_id}">${esc(w.name)} · ${w.attendee_id}</option>`).join("") : `<option value="">Create a wallet first</option>`;
      if (checkin.wallet && ws.some((w) => w.attendee_id === checkin.wallet)) $("#c-wallet").value = checkin.wallet;
      checkin.wallet = $("#c-wallet").value || null;
      $("#c-wallet").onchange = (e) => { checkin.wallet = e.target.value; this.drawSessions(); };
      $("#c-forge-to").innerHTML = S.sessions.map((s) => `<option>${s.session_id}</option>`).join("");
      $("#c-go").onclick = () => this.submit();
      this.drawSteps(0);
      this.drawSessions();
    },
    async drawSessions() {
      if (!S.sessions.length) S.sessions = await api("/api/sessions");
      if (!$("#c-forge-to").options.length) $("#c-forge-to").innerHTML = S.sessions.map((s) => `<option>${s.session_id}</option>`).join("");
      $("#c-pw-wrap").style.display = checkin.wallet && Wallet.isUnlocked(checkin.wallet) ? "none" : "";
      let attended = new Set();
      if (checkin.wallet) {
        const r = await api(`/api/query/attendee/${checkin.wallet}/sessions`).catch(() => ({ sessions: [] }));
        attended = new Set(r.sessions.map((x) => x.session_id));
      }
      $("#c-sessions").innerHTML = S.sessions.map((s) => `<div class="session ${attended.has(s.session_id) ? "done" : ""} ${checkin.session === s.session_id ? "sel" : ""}" data-sid="${s.session_id}">
        <div class="id">${s.session_id} ${attended.has(s.session_id) ? '<span class="badge b-ok">attended</span>' : ""}</div>
        <div class="title">${esc(s.title)}</div><div class="where">${esc(s.room)} · ${esc(s.starts)}</div></div>`).join("");
      $$(".session", $("#c-sessions")).forEach((el) => el.onclick = () => {
        if (el.classList.contains("done")) return;
        checkin.session = el.dataset.sid; this.drawSessions();
      });
      $("#c-go").disabled = !(checkin.wallet && checkin.session);
    },
    drawSteps(stage, failed = false) {
      const steps = [["Signed", "ECDSA with private key"], ["Broadcast", "sent to node + peers"], ["Pending", "in every node's pool"], ["Confirmed", "miner verified, in block"]];
      $("#c-steps").innerHTML = steps.map(([t, d], i) => `<div class="step ${i < stage ? "done" : i === stage && failed ? "fail" : i === stage ? "active" : ""}"><b>${i + 1}. ${t}</b>${d}</div>`).join("");
    },
    async submit() {
      try {
        if (!Wallet.isUnlocked(checkin.wallet)) await Wallet.unlock(checkin.wallet, $("#c-pw").value);
        let tx = await Wallet.attendance(checkin.wallet, checkin.session);
        const signedFor = tx.session_id;
        const forged = $("#c-forge").checked;
        if (forged) tx = { ...tx, session_id: $("#c-forge-to").value };
        this.drawSteps(1);
        const r = await api("/api/tx", { method: "POST", body: tx });
        checkin.last = { txid: r.txid, tx, forged, signedFor, seenPending: true };
        $("#c-result").innerHTML = `
          ${forged ? `<div class="callout bad">Forged: signed for <b>${signedFor}</b> but submitted as <b>${esc(tx.session_id)}</b>. The pool accepts it; the miner's signature check should reject it.</div>` : ""}
          <h3 style="font-size:13px;margin:14px 0 6px">Attendance certificate</h3><pre class="json">${esc(JSON.stringify(tx, null, 2))}</pre>
          <p class="sub" style="margin-top:8px">txid <span class="mono">${r.txid}</span></p><div id="c-final"></div>`;
        this.drawSteps(3);
        toast(`Certificate broadcast to ${r.broadcast_to.length} peer(s). Waiting for a miner…`, "ok");
        this.drawSessions();
      } catch (e) { toast(esc(e.message), "bad"); this.drawSteps(1, true); }
    },
    async update() {
      const L = checkin.last;
      if (!L || L.done) return;
      const mem = await api("/api/mempool");
      if (mem.pending.some((e) => e.tx.txid === L.txid)) { this.drawSteps(2 + 1); return; }
      try {
        const v = await api(`/api/verify/${L.txid}`);
        L.done = true; this.drawSteps(4);
        $("#c-final").innerHTML = `<div class="callout ok">Confirmed in block <b>#${v.block}</b>. Signature valid against the registered public key.</div>`;
        this.drawSessions();
      } catch {
        const ev = await api("/api/events?limit=80");
        const rej = ev.find((e) => e.txid === L.txid && e.level === "reject");
        if (rej) {
          L.done = true; this.drawSteps(3, true);
          $("#c-final").innerHTML = `<div class="callout bad">Rejected by the miner: <b>${esc(rej.reason)}</b>. It was never written to the chain.</div>`;
        }
      }
    },
  };

  // ================================================================== MINING
  PAGES.mining = {
    title: "Pending Pool & Mining",
    html: () => `
      <div class="grid g-side">
        <div class="card">
          <div class="card-head"><div><h2>Pending transaction pool</h2><p class="sub">Records broadcast to this node, not yet in a block. The miner verifies every signature before packaging.</p></div></div>
          <div id="m-pool"></div>
        </div>
        <div class="grid" style="align-content:start">
          <div class="card">
            <h2>Miner</h2>
            <p class="sub" id="m-addr"></p>
            <div class="row" style="margin-bottom:12px">
              <button class="btn" id="m-one">Mine next block</button>
              <button class="btn ghost" id="m-auto"></button>
            </div>
            <div class="mining-box" id="m-status"></div>
          </div>
          <div class="card"><h2>Miner log</h2><p class="sub">Verification results, rewards, and competing blocks</p><div id="m-log"></div></div>
        </div>
      </div>`,
    mount() {
      $("#m-one").onclick = async () => { await api("/api/mine", { method: "POST" }); toast("Mining started"); };
      $("#m-auto").onclick = async () => { await api("/api/automine", { method: "POST", body: { on: !S.summary.auto_mine } }); };
    },
    async update() {
      const s = S.summary; if (!s) return;
      const [mem, ev] = await Promise.all([api("/api/mempool"), api("/api/events?limit=80")]);
      $("#m-addr").innerHTML = `Reward address <span class="mono">${esc(s.miner_address)}</span> · balance <b>${fmt(s.balances[s.miner_address] || 0)} CONF</b>`;
      $("#m-auto").textContent = s.auto_mine ? "Stop auto-mine" : "Start auto-mine";
      const m = s.mining;
      $("#m-status").innerHTML = m.active
        ? `<div style="display:flex;justify-content:space-between"><b>Mining block #${m.height}</b><span class="badge b-warn">searching nonce</span></div>
           <dl class="kv"><dt>Target</dt><dd>${m.bits?.toFixed(2)} leading zero bits</dd><dt>Records</dt><dd>${m.records} valid${m.rejected ? `, ${m.rejected} rejected` : ""}</dd>
           <dt>Attempts</dt><dd>${fmt(m.hashes)}</dd><dt>Hash rate</dt><dd>${fmt(m.hashrate)} H/s</dd><dt>Elapsed</dt><dd>${m.seconds}s</dd></dl><div class="bar"><div></div></div>`
        : `<div style="display:flex;justify-content:space-between"><b>Idle</b><span class="badge b-mute">${s.auto_mine ? "auto-mine on" : "waiting"}</span></div>
           <dl class="kv"><dt>Next target</dt><dd>${s.next_difficulty_bits.toFixed(2)} bits</dd><dt>Last attempts</dt><dd>${fmt(m.hashes)}</dd><dt>Last hash rate</dt><dd>${fmt(m.hashrate)} H/s</dd></dl>`;
      $("#m-pool").innerHTML = mem.pending.length ? `<div class="table-wrap"><table><tr><th>Type</th><th>Content</th><th>From</th><th>Received</th><th>txid</th></tr>${mem.pending.map((e) => {
        const t = e.tx;
        return `<tr><td>${typeBadge(t.type)}</td><td>${t.type === "REGISTER" ? `${esc(t.name)}<div class="mono" style="color:var(--muted)">${esc(t.attendee_id)}</div>` : `<span class="mono">${esc(t.attendee_id)}</span> → <b>${esc(t.session_id)}</b>`}</td>
          <td>${esc(e.source === "wallet" ? "wallet" : S.nodes[e.source]?.name || e.source)}</td><td>${time(e.received)}</td><td class="mono">${short(t.txid, 10)}</td></tr>`;
      }).join("")}</table></div>` : `<div class="empty">Pending pool is empty</div>`;
      $("#m-log").innerHTML = feed(ev.filter((e) => ["reject", "mined", "block", "warn", "reorg", "difficulty"].includes(e.level)).slice(0, 25));
    },
  };

  // ================================================================== DIFFICULTY
  function difficultyChart(hist, target) {
    const data = hist.filter((h) => h.block_time !== null);
    if (data.length < 2) return `<div class="empty">Mine a few blocks to see the chart</div>`;
    const W = 900, H = 300, L = 46, R = 46, T = 14, B = 30;
    const n = data.length, iw = W - L - R, ih = H - T - B;
    const maxT = Math.max(target * 2.2, ...data.map((d) => d.block_time)) * 1.05;
    const bits = data.map((d) => d.bits);
    const minB = Math.floor(Math.min(...bits) - 1), maxB = Math.ceil(Math.max(...bits) + 1);
    const x = (i) => L + (iw * (i + 0.5)) / n;
    const yT = (v) => T + ih - (ih * v) / maxT;
    const yB = (v) => T + ih - (ih * (v - minB)) / (maxB - minB);
    const bw = Math.max(2, (iw / n) * 0.6);
    const bars = data.map((d, i) => `<rect x="${x(i) - bw / 2}" y="${yT(d.block_time)}" width="${bw}" height="${T + ih - yT(d.block_time)}" rx="2" fill="var(--accent)" opacity=".28"><title>#${d.index}: ${d.block_time}s</title></rect>`).join("");
    const line = data.map((d, i) => `${i ? "L" : "M"}${x(i)},${yB(d.bits)}`).join(" ");
    const gridT = [0, target, target * 2].map((v) => `<text x="${L - 6}" y="${yT(v) + 4}" text-anchor="end">${v}s</text>`).join("");
    const gridB = [minB, (minB + maxB) / 2, maxB].map((v) => `<text x="${W - R + 6}" y="${yB(v) + 4}">${v}</text>`).join("");
    const step = Math.ceil(n / 12);
    const xl = data.map((d, i) => (i % step === 0 ? `<text x="${x(i)}" y="${H - 10}" text-anchor="middle">#${d.index}</text>` : "")).join("");
    return `<div class="chart"><svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Block time and difficulty per block">
      <line class="axis" x1="${L}" y1="${T + ih}" x2="${W - R}" y2="${T + ih}"/>
      ${bars}
      <line x1="${L}" x2="${W - R}" y1="${yT(target)}" y2="${yT(target)}" stroke="var(--ok)" stroke-dasharray="5 4" stroke-width="1.5"/>
      <path d="${line}" fill="none" stroke="var(--accent)" stroke-width="2.5" stroke-linejoin="round"/>
      ${data.map((d, i) => `<circle cx="${x(i)}" cy="${yB(d.bits)}" r="2.6" fill="var(--accent)"><title>#${d.index}: ${d.bits} bits</title></circle>`).join("")}
      ${gridT}${gridB}${xl}
      <text x="${L}" y="${T - 2}" >block time</text><text x="${W - R}" y="${T - 2}" text-anchor="end">difficulty bits</text>
    </svg></div>
    <div class="legend"><span><i style="background:var(--accent)"></i>Difficulty (bits, right axis)</span><span><i style="background:var(--accent);opacity:.3;height:10px"></i>Block time (left axis)</span><span><i style="background:var(--ok)"></i>Target ${target}s</span></div>`;
  }

  PAGES.difficulty = {
    title: "Dynamic Difficulty",
    html: () => `
      <div class="stats" id="df-stats" style="grid-template-columns:repeat(5,minmax(0,1fr))"></div>
      <div class="card" style="margin-bottom:16px">
        <div class="card-head"><div><h2>Difficulty vs. block time</h2><p class="sub" id="df-rule"></p></div>
          <div class="row"><button class="btn" id="df-all-on">Auto-mine on all nodes</button><button class="btn ghost" id="df-all-off">Stop all</button></div></div>
        <div id="df-chart"></div>
      </div>
      <div class="card"><h2>Retarget history</h2><p class="sub">new_target = old_target × actual / expected, clamped to ×4 per step (as in Bitcoin). Every node recomputes this; a block with any other target is rejected.</p><div id="df-table"></div></div>`,
    mount() {
      const all = (on) => Promise.all(Object.keys(S.nodes).map((u) => api("/api/automine", { method: "POST", body: { on } }, u).catch(() => null)))
        .then(() => toast(on ? "Auto-mining on all nodes: watch the difficulty adapt" : "Auto-mining stopped on all nodes"));
      $("#df-all-on").onclick = () => all(true);
      $("#df-all-off").onclick = () => all(false);
    },
    async update() {
      const d = await api("/api/difficulty");
      const s = S.summary;
      const recent = d.history.filter((h) => h.block_time !== null).slice(-d.adjust_interval);
      const avg = recent.length ? recent.reduce((a, h) => a + h.block_time, 0) / recent.length : 0;
      const toNext = d.adjust_interval - ((s.height + 1) % d.adjust_interval || d.adjust_interval);
      $("#df-rule").textContent = `Target ${d.target_block_time}s per block; retarget every ${d.adjust_interval} blocks (Bitcoin: 600s and 2016 blocks).`;
      $("#df-stats").innerHTML = [
        ["Current difficulty", s.difficulty_bits.toFixed(2) + " bits"],
        ["Next block", s.next_difficulty_bits.toFixed(2) + " bits"],
        ["Avg block time (last window)", avg ? avg.toFixed(2) + " s" : "n/a"],
        ["Target block time", d.target_block_time + " s"],
        ["Blocks to next retarget", toNext],
      ].map(([l, v]) => `<div class="stat"><div class="label">${l}</div><div class="value" style="font-size:20px">${v}</div></div>`).join("");
      $("#df-chart").innerHTML = difficultyChart(d.history.slice(-60), d.target_block_time);
      $("#df-table").innerHTML = d.retargets.length ? `<div class="table-wrap"><table><tr><th>At block</th><th>Window</th><th>Actual</th><th>Expected</th><th>Difficulty</th><th></th></tr>${[...d.retargets].reverse().map((r) => `
        <tr><td>#${r.height}</td><td>#${r.window[0]}–#${r.window[1]}</td><td>${r.actual_seconds}s</td><td>${r.expected_seconds}s</td>
        <td>${r.old_bits.toFixed(2)} → <b>${r.new_bits.toFixed(2)}</b> bits</td>
        <td><span class="badge ${r.direction === "up" ? "b-bad" : r.direction === "down" ? "b-ok" : "b-mute"}">${r.direction === "up" ? "harder (blocks too fast)" : r.direction === "down" ? "easier (blocks too slow)" : "unchanged"}</span></td></tr>`).join("")}</table></div>`
        : `<div class="empty">No retarget yet. The first happens at block #${d.adjust_interval * 2}.</div>`;
    },
  };

  // ================================================================== QUERIES
  const Q = { tab: "q1" };
  const sessionSelect = (id) => `<select id="${id}">${S.sessions.map((s) => `<option value="${s.session_id}">${s.session_id} · ${esc(s.title)}</option>`).join("")}</select>`;
  const verifyBtn = (txid) => `<button class="btn ghost sm" onclick="showVerify('${txid}')">Verify signature</button>`;

  PAGES.queries = {
    title: "Attendance Queries",
    html: () => `
      <div class="tabs" id="q-tabs">
        <div class="tab" data-tab="q1">Sessions by attendee</div>
        <div class="tab" data-tab="q2">Attendees by session</div>
        <div class="tab" data-tab="q3">Absentees by session</div>
        <div class="tab" data-tab="q4">Registration status</div>
      </div>
      <div class="card" id="q-card"></div>`,
    async mount() {
      if (!S.sessions.length) S.sessions = await api("/api/sessions");
      $$(".tab").forEach((t) => t.onclick = () => { Q.tab = t.dataset.tab; this.drawTab(); });
      this.drawTab();
    },
    drawTab() {
      $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === Q.tab));
      const c = $("#q-card");
      const forms = {
        q1: `<h2>All sessions attended by a participant</h2><p class="sub">Search by name, email, or attendee ID.</p>
          <div class="row"><div style="position:relative"><label class="f">Participant<input id="q1-in" autocomplete="off" placeholder="Start typing a name…"></label><div class="sugg" id="q1-sugg" hidden></div></div><button class="btn" id="q-run">Run query</button></div>`,
        q2: `<h2>All participants who attended a session</h2><p class="sub">Only certificates confirmed in a block are counted.</p>
          <div class="row"><label class="f">Session${sessionSelect("q2-in")}</label><button class="btn" id="q-run">Run query</button></div>`,
        q3: `<h2>Registered participants who did not attend a session</h2><p class="sub">Registered on chain minus confirmed attendance.</p>
          <div class="row"><label class="f">Session${sessionSelect("q3-in")}</label><button class="btn" id="q-run">Run query</button></div>`,
        q4: `<h2>Registration status of any attendee</h2><p class="sub">By attendee ID, email, or public key. Reports confirmed, pending, or not registered.</p>
          <div class="row"><label class="f">Attendee ID / email / public key<input id="q4-in" placeholder="ATT-… or name@connect.edu"></label><button class="btn" id="q-run">Run query</button></div>`,
      };
      c.innerHTML = forms[Q.tab] + `<div id="q-out" style="margin-top:14px"></div>`;
      $("#q-run").onclick = () => this.run();
      // Block body on purpose: an on* handler that returns false cancels the keystroke.
      $$("input", c).forEach((i) => i.onkeydown = (e) => { if (e.key === "Enter") this.run(); });
      if (Q.tab === "q1") {
        // Plain input plus our own suggestion list (a <datalist> hid typed text in some browsers).
        const input = $("#q1-in"), sugg = $("#q1-sugg");
        Q.pick = null;
        input.oninput = async () => {
          Q.pick = null;
          const typed = input.value.trim();
          if (!typed) { sugg.hidden = true; return; }
          const r = await api(`/api/search?q=${encodeURIComponent(typed)}`).catch(() => []);
          if (input.value.trim() !== typed) return; // a newer keystroke is already in flight
          sugg.innerHTML = r.slice(0, 8).map((p) => `<div class="sugg-item" data-id="${p.attendee_id}" data-name="${esc(p.name)}"><b>${esc(p.name)}</b> <span>${esc(p.email)}</span></div>`).join("");
          sugg.hidden = !r.length;
          $$(".sugg-item", sugg).forEach((it) => it.onclick = () => {
            input.value = it.dataset.name; Q.pick = it.dataset.id; sugg.hidden = true; this.run();
          });
        };
        // Delay hiding so a click on a suggestion lands before the list disappears.
        input.onblur = () => setTimeout(() => { sugg.hidden = true; }, 200);
      }
    },
    async run() {
      const out = $("#q-out");
      try {
        if (Q.tab === "q1") {
          $("#q1-sugg").hidden = true;
          let q = Q.pick || $("#q1-in").value.trim();
          if (!q) { out.innerHTML = `<div class="callout bad">Type a name, email, or attendee ID first.</div>`; return; }
          if (!q.startsWith("ATT-")) { const m = await api(`/api/search?q=${encodeURIComponent(q)}`); if (m[0]) q = m[0].attendee_id; }
          const r = await api(`/api/query/attendee/${encodeURIComponent(q)}/sessions`);
          if (!r.attendee) { out.innerHTML = `<div class="callout bad">No registered attendee matches “${esc(q)}”.</div>`; return; }
          out.innerHTML = `<div class="callout info"><b>${esc(r.attendee.name)}</b> (${esc(r.attendee.email)}) attended <b>${r.sessions.length}</b> of ${S.sessions.length} sessions</div>` +
            (r.sessions.length ? `<div class="table-wrap" style="margin-top:12px"><table><tr><th>Session</th><th>Checked in</th><th>Block</th><th>Confirmations</th><th></th></tr>${r.sessions.map((x) =>
              `<tr><td><b>${x.session_id}</b> ${esc(x.session.title)}</td><td>${dateTime(x.timestamp)}</td><td><a href="#" data-block="${x.block}">#${x.block}</a></td><td>${x.confirmations}</td><td>${verifyBtn(x.txid)}</td></tr>`).join("")}</table></div>` : "");
        }
        if (Q.tab === "q2") {
          const r = await api(`/api/query/session/${$("#q2-in").value}/attendees`);
          out.innerHTML = `<div class="callout info"><b>${r.attendees.length}</b> participant(s) attended <b>${esc(r.session.session_id)}</b> ${esc(r.session.title)}</div>` +
            (r.attendees.length ? `<div class="table-wrap" style="margin-top:12px"><table><tr><th>Name</th><th>Attendee ID</th><th>Checked in</th><th>Block</th><th></th></tr>${r.attendees.map((x) =>
              `<tr><td><b>${esc(x.attendee.name)}</b><div style="color:var(--muted);font-size:12px">${esc(x.attendee.email)}</div></td><td class="mono">${x.attendee_id}</td><td>${dateTime(x.timestamp)}</td><td><a href="#" data-block="${x.block}">#${x.block}</a></td><td>${verifyBtn(x.txid)}</td></tr>`).join("")}</table></div>` : "");
        }
        if (Q.tab === "q3") {
          const r = await api(`/api/query/session/${$("#q3-in").value}/absentees`);
          out.innerHTML = `<div class="callout info"><b>${r.absentees.length}</b> of ${r.registered} registered participant(s) did not attend <b>${esc(r.session.session_id)}</b> ${esc(r.session.title)} (${r.attended} attended)</div>` +
            (r.absentees.length ? `<div class="table-wrap" style="margin-top:12px"><table><tr><th>Name</th><th>Email</th><th>Attendee ID</th><th>Registered in</th></tr>${r.absentees.map((p) =>
              `<tr><td><b>${esc(p.name)}</b></td><td>${esc(p.email)}</td><td class="mono">${p.attendee_id}</td><td><a href="#" data-block="${p.block}">#${p.block}</a></td></tr>`).join("")}</table></div>` : "");
        }
        if (Q.tab === "q4") {
          const r = await api(`/api/query/status?q=${encodeURIComponent($("#q4-in").value)}`);
          const cls = { CONFIRMED: "ok", PENDING: "info", NOT_REGISTERED: "bad" }[r.status];
          out.innerHTML = `<div class="callout ${cls}" style="font-size:15px"><b>${r.status.replace("_", " ")}</b>${r.status === "CONFIRMED" ? ` · ${r.confirmations} confirmation(s)` : r.status === "PENDING" ? " · in the pending pool, not yet mined" : ""}</div>` +
            (r.attendee ? `<dl class="kv" style="margin-top:12px"><dt>Name</dt><dd>${esc(r.attendee.name)}</dd><dt>Email</dt><dd>${esc(r.attendee.email)}</dd><dt>Attendee ID</dt><dd class="mono">${r.attendee.attendee_id}</dd>
              <dt>Public key</dt><dd class="mono">${short(r.attendee.public_key, 48)}</dd>${r.attendee.block !== undefined ? `<dt>Registered in</dt><dd><a href="#" data-block="${r.attendee.block}">block #${r.attendee.block}</a></dd><dt>Sessions attended</dt><dd>${r.sessions_attended}</dd>` : ""}</dl>` : "");
        }
        $$("a[data-block]", out).forEach((a) => a.onclick = (e) => { e.preventDefault(); showBlock(+a.dataset.block); });
      } catch (e) { out.innerHTML = `<div class="callout bad">${esc(e.message)}</div>`; }
    },
  };

  // ================================================================== EXPLORER
  PAGES.explorer = {
    title: "Block Explorer",
    html: () => `<div class="card"><h2>Blocks on ${esc(S.summary?.node || "this node")}</h2><p class="sub">Newest first. Click a row for the header and transactions.</p><div id="e-list"></div></div>`,
    async update() {
      const blocks = await api("/api/blocks?limit=60");
      $("#e-list").innerHTML = `<div class="table-wrap"><table><tr><th>#</th><th>Hash</th><th>Previous</th><th>Time</th><th>Miner</th><th>Records</th><th>Difficulty</th><th>Nonce</th></tr>${blocks.map((b) => `
        <tr data-block="${b.index}" style="cursor:pointer"><td><b>${b.index}</b></td><td class="mono">${short(b.hash, 14)}</td><td class="mono">${short(b.previous_hash, 10)}</td>
        <td>${b.index ? time(b.timestamp) : "genesis"}</td><td>${b.index ? esc(minerName(b.miner)) : "n/a"}</td><td>${b.records}</td><td>${b.bits.toFixed(2)}</td><td>${fmt(b.nonce)}</td></tr>`).join("")}</table></div>`;
      bindBlockClicks($("#e-list"));
    },
  };

  // ------------------------------------------------------------------ boot
  (async () => {
    await discoverNodes();
    if (!S.nodes[S.api]?.online) { S.api = location.origin; store.set("confchain.node", S.api); $("#node-select").value = S.api; }
    try { S.summary = await api("/api/summary"); S.sessions = await api("/api/sessions"); } catch { /* offline */ }
    renderChrome();
    render();
    S.lastHeight = S.summary?.height ?? null;
    setInterval(tick, 1500);
    setInterval(discoverNodes, 15000);
  })();
})();
