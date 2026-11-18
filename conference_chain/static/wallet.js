/* Browser wallet: key generation, encrypted keystore, and signing with Web Crypto.
 *
 * The private key is generated in the browser and stored only as an AES-256-GCM
 * ciphertext (key derived from the wallet password with PBKDF2, 600k iterations).
 * Once unlocked it is re-imported as a NON-extractable CryptoKey, so page
 * scripts can ask it to sign but cannot read the key bytes. The node never
 * receives the private key: only signed transactions are sent.
 */
const Wallet = (() => {
  const enc = new TextEncoder();
  const STORE = "confchain.wallets.v1";
  const ITER = 600000;
  const unlocked = new Map(); // attendee_id -> CryptoKey (non-extractable)

  const hex = (buf) => [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
  const b64 = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)));
  const unb64 = (s) => Uint8Array.from(atob(s), (c) => c.charCodeAt(0));
  const sha256hex = async (bytes) => hex(await crypto.subtle.digest("SHA-256", bytes));

  /* Must match Python: json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False) */
  function canonical(v) {
    if (Array.isArray(v)) return "[" + v.map(canonical).join(",") + "]";
    if (v && typeof v === "object")
      return "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ":" + canonical(v[k])).join(",") + "}";
    return JSON.stringify(v);
  }

  async function addressOf(pubHex) {
    const bytes = Uint8Array.from(pubHex.match(/../g).map((h) => parseInt(h, 16)));
    return "ATT-" + (await sha256hex(bytes)).slice(0, 16);
  }

  async function deriveKey(password, salt, iterations) {
    const base = await crypto.subtle.importKey("raw", enc.encode(password), "PBKDF2", false, ["deriveKey"]);
    return crypto.subtle.deriveKey({ name: "PBKDF2", salt, iterations, hash: "SHA-256" }, base,
      { name: "AES-GCM", length: 256 }, false, ["encrypt", "decrypt"]);
  }

  function list() {
    try { return JSON.parse(localStorage.getItem(STORE) || "[]"); } catch { return []; }
  }
  function save(all) {
    try { localStorage.setItem(STORE, JSON.stringify(all)); } catch (e) { console.warn("storage unavailable", e); }
  }
  function get(id) { return list().find((w) => w.attendee_id === id); }

  async function create(name, email, password) {
    const kp = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
    const pub = hex(await crypto.subtle.exportKey("raw", kp.publicKey));
    const pkcs8 = await crypto.subtle.exportKey("pkcs8", kp.privateKey);
    const salt = crypto.getRandomValues(new Uint8Array(16));
    const iv = crypto.getRandomValues(new Uint8Array(12));
    const aes = await deriveKey(password, salt, ITER);
    const ct = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, aes, pkcs8);
    const ks = {
      version: 1, attendee_id: await addressOf(pub), name: name.trim(), email: email.trim().toLowerCase(),
      public_key: pub,
      crypto: { kdf: "PBKDF2-SHA256", iterations: ITER, salt: b64(salt), cipher: "AES-256-GCM", iv: b64(iv), ciphertext: b64(ct) },
    };
    save([...list().filter((w) => w.attendee_id !== ks.attendee_id), ks]);
    return ks;
  }

  async function importKeystore(ks) {
    if (!ks || !ks.public_key || !ks.crypto) throw new Error("not a ConfChain keystore");
    ks.attendee_id = await addressOf(ks.public_key);
    save([...list().filter((w) => w.attendee_id !== ks.attendee_id), ks]);
    return ks;
  }

  function remove(id) { unlocked.delete(id); save(list().filter((w) => w.attendee_id !== id)); }

  async function unlock(id, password) {
    const ks = get(id);
    const c = ks.crypto;
    const aes = await deriveKey(password, unb64(c.salt), c.iterations);
    let pkcs8;
    try { pkcs8 = await crypto.subtle.decrypt({ name: "AES-GCM", iv: unb64(c.iv) }, aes, unb64(c.ciphertext)); }
    catch { throw new Error("Wrong password"); }
    const key = await crypto.subtle.importKey("pkcs8", pkcs8, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
    unlocked.set(id, key);
    return true;
  }
  function lock(id) { unlocked.delete(id); }
  function isUnlocked(id) { return unlocked.has(id); }

  async function signTx(id, tx) {
    const key = unlocked.get(id);
    if (!key) throw new Error("Unlock the wallet first");
    const sig = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, enc.encode(canonical(tx)));
    return { ...tx, signature: hex(sig) }; // Web Crypto returns raw r||s (64 bytes)
  }

  async function txid(tx) {
    const { txid: _, ...rest } = tx;
    return sha256hex(enc.encode(canonical(rest)));
  }

  const now = () => Math.floor(Date.now() / 1000);

  async function registration(id) {
    const w = get(id);
    return signTx(id, { type: "REGISTER", attendee_id: w.attendee_id, name: w.name, email: w.email, public_key: w.public_key, timestamp: now() });
  }
  async function attendance(id, session_id) {
    return signTx(id, { type: "ATTENDANCE", attendee_id: id, session_id, timestamp: now() });
  }

  return { list, get, create, importKeystore, remove, unlock, lock, isUnlocked, registration, attendance, txid, canonical };
})();
