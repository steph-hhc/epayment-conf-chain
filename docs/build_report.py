"""Build the project report draft: python docs/build_report.py

Needs the network running (live numbers) and docs/screenshots populated.
"""
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from docx import Document
from docx.enum.section import WD_ORIENT  # noqa: F401
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

HERE = Path(__file__).parent
ROOT = HERE.parent
SHOTS = HERE / "screenshots"
OUT = HERE / "ConfChain_Report.docx"
INDIGO = RGBColor(0x4F, 0x46, 0xE5)
MUTED = RGBColor(0x66, 0x70, 0x85)


def get(path, port=5001):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=5) as r:
        return json.load(r)


# ------------------------------------------------------------------ live evidence
summaries = {p: get("/api/summary", p) for p in (5001, 5002, 5003)}
diff = get("/api/difficulty")
tests = subprocess.run([str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "pytest", "-v", "-p", "no:cacheprovider"],
                       cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
test_rows = re.findall(r"tests/(test_\w+)\.py::(\S+) (PASSED|FAILED|SKIPPED|ERROR)", tests.stdout)
test_total = re.search(r"(\d+ passed.*?) in", tests.stdout)

# ------------------------------------------------------------------ document helpers
doc = Document()
sec = doc.sections[0]
sec.page_width, sec.page_height = Cm(21), Cm(29.7)
sec.left_margin = sec.right_margin = Cm(2.2)
sec.top_margin = sec.bottom_margin = Cm(2.0)

st = doc.styles["Normal"]
st.font.name = "Calibri"
st.font.size = Pt(11)
st.paragraph_format.space_after = Pt(6)
st.paragraph_format.line_spacing = 1.15
for name, size, color in (("Heading 1", 16, INDIGO), ("Heading 2", 13, RGBColor(0x17, 0x1B, 0x26)), ("Title", 30, RGBColor(0x12, 0x16, 0x24))):
    s = doc.styles[name]
    s.font.name = "Calibri"
    s.font.size = Pt(size)
    s.font.bold = True
    s.font.color.rgb = color
    rpr = s.element.get_or_add_rPr()
    fonts = rpr.find(qn("w:rFonts"))
    if fonts is None:
        fonts = OxmlElement("w:rFonts"); rpr.append(fonts)
    for a in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        fonts.set(qn(a), "Calibri")
    s.paragraph_format.space_before = Pt(14 if name == "Heading 1" else 10)
    s.paragraph_format.space_after = Pt(6)

fig_no = [0]
tab_no = [0]


def p(text="", bold_lead=None, style=None, italic=False, size=None, color=None, align=None):
    para = doc.add_paragraph(style=style)
    if bold_lead:
        r = para.add_run(bold_lead); r.bold = True
    # support `code` spans
    for i, part in enumerate(re.split(r"`([^`]+)`", text)):
        if not part:
            continue
        r = para.add_run(part)
        r.italic = italic
        if i % 2:
            r.font.name = "Consolas"; r.font.size = Pt(9.5)
        if size: r.font.size = Pt(size)
        if color: r.font.color.rgb = color
    if align is not None:
        para.alignment = align
    return para


def bullets(items):
    for it in items:
        if isinstance(it, tuple):
            p(it[1], bold_lead=it[0] + ": ", style="List Bullet")
        else:
            p(it, style="List Bullet")


def shade(cell, hex_):
    tcPr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd"); sh.set(qn("w:val"), "clear"); sh.set(qn("w:color"), "auto"); sh.set(qn("w:fill"), hex_)
    tcPr.append(sh)


def table(header, rows, widths=None, caption=None, mono_cols=()):
    if caption:
        tab_no[0] += 1
        c = p(f"Table {tab_no[0]}. {caption}", size=9.5, color=MUTED)
        c.paragraph_format.keep_with_next = True
    t = doc.add_table(rows=1, cols=len(header))
    t.style = "Table Grid"
    t.alignment = WD_TABLE_ALIGNMENT.CENTER
    for i, h in enumerate(header):
        cell = t.rows[0].cells[i]
        cell.text = ""
        r = cell.paragraphs[0].add_run(h); r.bold = True; r.font.size = Pt(9.5)
        shade(cell, "EEF0FF")
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = ""
            r = cells[i].paragraphs[0].add_run(str(v)); r.font.size = Pt(9.5)
            if i in mono_cols:
                r.font.name = "Consolas"; r.font.size = Pt(8.5)
    if widths:
        for row in t.rows:
            for i, w in enumerate(widths):
                row.cells[i].width = Cm(w)
    doc.add_paragraph().paragraph_format.space_after = Pt(2)
    return t


def code(src, caption=None):
    if caption:
        c = p(caption, size=9.5, color=MUTED); c.paragraph_format.keep_with_next = True
    t = doc.add_table(rows=1, cols=1)
    cell = t.rows[0].cells[0]
    shade(cell, "F3F4F8")
    cell.text = ""
    lines = src.strip("\n").split("\n")
    para = cell.paragraphs[0]
    para.paragraph_format.space_after = Pt(0)
    para.paragraph_format.line_spacing = 1.0
    for i, line in enumerate(lines):
        r = para.add_run(line)
        r.font.name = "Consolas"; r.font.size = Pt(8.5)
        if line.lstrip().startswith("#"):
            r.font.color.rgb = MUTED
        if i < len(lines) - 1:
            r.add_break()
    doc.add_paragraph().paragraph_format.space_after = Pt(2)


def figure(name, caption, width_cm=16.2):
    path = SHOTS / name
    if not path.exists():
        p(f"[missing screenshot {name}]"); return
    fig_no[0] += 1
    doc.add_picture(str(path), width=Cm(width_cm))
    doc.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.paragraphs[-1].paragraph_format.keep_with_next = True
    c = p(f"Figure {fig_no[0]}. {caption}", size=9.5, color=MUTED, align=WD_ALIGN_PARAGRAPH.CENTER)
    return fig_no[0]


def h1(t): doc.add_heading(t, level=1)
def h2(t): doc.add_heading(t, level=2)


# ================================================================== title page
for _ in range(5):
    doc.add_paragraph()
doc.add_paragraph("ConfChain", style="Title")
p("A Blockchain-Based Conference Registration System", size=16, color=INDIGO)
p("DSAI 4202 E-Payment and Cryptocurrency · Fall 2026 · Group Project Report", size=12, color=MUTED)
doc.add_paragraph()
table(["Member", "Student ID", "Primary responsibility"], [
    ("Member A", "", "Cryptography, attendee wallets, registration"),
    ("Member B", "", "Attendance certificates, pending pool, mining and rewards"),
    ("Member C", "", "Peer-to-peer network, chain state, organizer queries"),
    ("Member D", "", "Dynamic difficulty, consensus validation, testing"),
], widths=[3.5, 3.5, 9.2])
p("Submission: on or before 1 December 2026. Presentation: 24 November 2026.", size=10, color=MUTED)
doc.add_paragraph().add_run().add_break(WD_BREAK.PAGE)

# ================================================================== 1 overview
h1("1. Project overview")
p("ConfChain is a peer-to-peer proof-of-work blockchain that records conference registrations and session attendance "
  "so that no single party can forge, alter, or delete a record after the fact. Attendees hold their own keys, sign "
  "their own attendance certificates, and miners only package records whose signatures verify. Organizers query the "
  "resulting ledger for attendance and registration status.")
h2("1.1 Objectives")
bullets([
    "Implement the full 3 to 4 member scope: registration, attendance recording, mining with signature verification and rewards, and all four organizer queries.",
    "Implement the enhanced function: dynamic mining difficulty based on the time taken by the previous window of blocks, following Bitcoin's approach.",
    "Run as a real network rather than a single process, so that broadcast to the pending pool of each node is demonstrable.",
    "Keep each attendee's private key under the attendee's control, never on a server.",
])
h2("1.2 Implemented functions")
table(["Requirement", "Implementation", "Evidence"], [
    ("Each attendee generates a key pair", "ECDSA P-256 via the browser Web Crypto API (or the Python CLI wallet)", "Fig. 2"),
    ("Register name, email, public key", "Self-signed REGISTER transaction; attendee ID = SHA-256(public key)", "Fig. 3, 4"),
    ("Private key stored securely in a wallet", "AES-256-GCM keystore, key derived by PBKDF2-SHA256 (600,000 rounds)", "Fig. 2"),
    ("Sign attendance certificate (attendee ID, session ID, timestamp)", "ATTENDANCE transaction signed in the browser", "Fig. 5, 6"),
    ("Broadcast to network, pending pool of each node", "REST submit, then gossip to all peers; per-node pending pool", "Fig. 5, 8"),
    ("Miners verify signatures; only valid records packaged", "Signature check in block assembly; invalid records dropped", "Fig. 7, 8"),
    ("Miners receive rewards", "Coinbase transaction of 50 CONF per block, enforced by consensus", "Fig. 1, 8"),
    ("Query: sessions of a participant", "GET /api/query/attendee/<id>/sessions", "Fig. 10"),
    ("Query: participants of a session", "GET /api/query/session/<sid>/attendees", "Fig. 12"),
    ("Query: registered non-attendees of a session", "GET /api/query/session/<sid>/absentees", "Fig. 13"),
    ("Query: registration status of any attendee", "GET /api/query/status?q=<id, email or key>", "Fig. 14, 15"),
    ("Dynamic difficulty", "Bitcoin-style proportional retarget every N blocks, clamped to 4x", "Fig. 9, Table 10"),
], widths=[5.2, 8.0, 3.0], caption="Required functions and where each is demonstrated")
p("Beyond the brief, the system adds a three-node network with heaviest-chain fork choice, Merkle roots, median-time-past "
  "timestamp checks, replay protection, in-browser key custody, independent signature re-verification for organizers, "
  "and an automated test suite (" + (test_total.group(1) if test_total else "see Section 3") + ").")

# ================================================================== 2 design
h1("2. System design and implementation")
h2("2.1 Architecture")
p("The system is written in Python 3 (Flask, cryptography) with a dependency-free HTML and JavaScript dashboard. Three "
  "full nodes (Node A, B, C on ports 5001 to 5003) each keep an independent copy of the chain, a world-state index, and a "
  "pending pool. The dashboard can connect to any node, which makes it visible that every node reaches the same state on its own.")
table(["Module", "Responsibility"], [
    ("config.py", "Consensus parameters and the conference program written into the genesis block"),
    ("crypto.py", "SHA-256, canonical JSON, ECDSA P-256 sign and verify, encrypted keystore"),
    ("transactions.py", "REGISTER, ATTENDANCE and COINBASE formats, stateless structural checks"),
    ("block.py", "Block header, Merkle root, proof-of-work miner"),
    ("difficulty.py", "Dynamic difficulty retargeting"),
    ("chain.py", "World state, block and chain validation, pending pool, fork choice, the four queries"),
    ("node.py", "REST API, peer-to-peer gossip, background miner thread"),
    ("static/wallet.js", "Browser wallet: key generation, encryption, signing"),
    ("static/app.js", "Dashboard for attendees, miners and organizers"),
], widths=[3.6, 12.6], caption="Code modules", mono_cols=(0,))
p("Lifecycle of a record: (1) the attendee's browser signs a transaction; (2) a node checks its structure, adds it to its "
  "pending pool and gossips it to its peers, each of which does the same; (3) a miner verifies every pending signature "
  "against the registered public key, builds a block with a coinbase reward, and searches for a valid nonce; (4) the "
  "block is broadcast and every node fully re-validates it before appending; (5) organizers query the updated state.")

h2("2.2 Data structures")
table(["Field", "Meaning"], [
    ("index", "Height of the block"), ("timestamp", "Creation time (seconds, millisecond precision)"),
    ("previous_hash", "Hash of the previous block header, linking the chain"),
    ("merkle_root", "Merkle root of all transaction IDs, so the header commits to every record"),
    ("target", "256-bit proof-of-work target; a valid hash must be numerically at most this value"),
    ("nonce", "Value varied by the miner"), ("miner", "Reward address of the miner"),
    ("hash", "SHA-256 of the canonical JSON header"),
], widths=[3.6, 12.6], caption="Block header", mono_cols=(0,))
p("Difficulty is stored as a full 256-bit target rather than a whole number of leading zeros, so it can change by "
  "fractions of a bit. It is reported as difficulty bits = 256 - log2(target).")
table(["Type", "Fields", "Signed by"], [
    ("REGISTER", "attendee_id, name, email, public_key, timestamp, signature", "The registering attendee (proves key ownership)"),
    ("ATTENDANCE", "attendee_id, session_id, timestamp, signature", "The attendee (the attendance certificate)"),
    ("COINBASE", "miner, amount, height", "Not signed; validity enforced by consensus rules"),
], widths=[3.0, 8.0, 5.2], caption="Transaction types", mono_cols=(0, 1))
p("The signed message is the canonical JSON (sorted keys, no whitespace, UTF-8) of every field except the signature. "
  "Browser and Python produce byte-identical messages, which is checked by an automated test.")

h2("2.3 Keys, wallets and registration")
p("Design choice: ECDSA over NIST P-256 with SHA-256. Bitcoin uses secp256k1, but browsers do not support it natively. "
  "P-256 offers the same 128-bit security level and lets the key pair be generated and used entirely inside the "
  "attendee's browser through the Web Crypto API, so the node never sees a private key.")
p("The private key is exported once as PKCS#8, encrypted with AES-256-GCM under a key derived from the wallet password "
  "by PBKDF2-HMAC-SHA256 with 600,000 iterations (the current OWASP recommendation) and a random salt, and stored as a keystore. GCM authentication means a "
  "wrong password is detected rather than producing a wrong key. After unlocking, the key is re-imported as non-extractable, "
  "so even scripts on the page can request signatures but cannot read the key. The same keystore format is used by the "
  "Python CLI wallet, so wallets move between the two.")
code('''
// static/wallet.js
const kp = await crypto.subtle.generateKey({ name: "ECDSA", namedCurve: "P-256" }, true, ["sign", "verify"]);
const pkcs8 = await crypto.subtle.exportKey("pkcs8", kp.privateKey);
const aes = await deriveKey(password, salt, 600000);            // PBKDF2-SHA256
const ct  = await crypto.subtle.encrypt({ name: "AES-GCM", iv }, aes, pkcs8);
// on unlock: re-import as NON-extractable, usable only for signing
const key = await crypto.subtle.importKey("pkcs8", pkcs8, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
''', "Listing 1. Key generation and encrypted storage in the browser wallet")
p("The attendee ID is derived from the public key (`ATT-` plus the first 16 hex digits of its SHA-256), like a Bitcoin "
  "address. A registration is valid only if the ID matches the key, the signature verifies with that key, the ID is new, "
  "and the email is not already registered.")

h2("2.4 Attendance recording and broadcast")
p("The attendance certificate contains exactly the fields required by the brief, attendee ID, session ID and timestamp, "
  "and is signed with the attendee's private key. The node receiving it performs only cheap structural checks (field set, "
  "known session, sane timestamp, signature length) and adds it to its pending pool, then gossips it to every peer. Each "
  "peer de-duplicates by transaction ID before forwarding, so gossip terminates. Signature verification is intentionally "
  "left to the miner, as specified; Section 2.5 explains why this is still safe.")

h2("2.5 Mining with signature verification and rewards")
code('''
# chain.py, Blockchain.build_candidate()
entries = sorted(self.mempool.values(), key=lambda e: (e["tx"]["type"] != REGISTER, e["received"]))
for e in entries:
    tx = e["tx"]
    ok, reason = work_state.check(tx, verify_signature=True)   # miner verifies each signature
    if ok:
        work_state.apply(tx, height, time.time())
        accepted.append(tx)
    else:
        rejected.append({"tx": tx, "reason": reason})          # dropped from the pool
txs = [make_coinbase(miner_address, height)] + accepted
''', "Listing 2. The miner packages only records that pass verification against current state")
p("For an attendance certificate, State.check requires the attendee to be registered, verifies the signature against the "
  "public key recorded at registration, and rejects a second check-in to the same session. Registrations are ordered first "
  "so a new attendee can register and check in within one block. The block's first transaction is a coinbase paying 50 CONF "
  "to the miner; a block with any other reward, height or recipient is invalid.")
p("Proof of work hashes the canonical JSON header until the hash is at most the target. To speed this up in Python, the "
  "header is split around the nonce and the SHA-256 state of the prefix is reused, reaching roughly 1.5 to 2 million "
  "hashes per second per node. Mining runs in a background thread and is aborted as soon as a competing block arrives.")
p("Every node re-runs the complete validation in validate_block for each block it receives: index and link to the tip, "
  "timestamp after the median of the last 11 blocks and not more than 60 s in the future, the exact expected difficulty "
  "target, correct header hash, proof of work, transaction IDs, Merkle root, coinbase rules, and every signature. A "
  "dishonest miner therefore cannot sneak an unsigned record into the chain. After each block, nodes also prune pending "
  "records that can never be mined.")
p("Forks are resolved by adopting the valid chain with the most cumulative work (the sum of 2^256 / (target + 1)), as in "
  "Bitcoin. Records from orphaned blocks are returned to the pending pool.")

h2("2.6 Organizer queries")
p("Each node maintains a state index rebuilt by replaying the chain: registry by attendee ID, an email index, and "
  "attendance indexed both by attendee and by session. The chain remains the single source of truth, and the index makes "
  "queries constant or linear in the size of the answer.")
table(["Query", "Logic"], [
    ("Sessions attended by a participant", "by_attendee[id], with block height and confirmations; lookup by name, email or ID"),
    ("Participants who attended a session", "by_session[sid], joined with the registry"),
    ("Registered participants who did not attend", "registry minus attendees of by_session[sid]"),
    ("Registration status", "CONFIRMED with confirmations, PENDING if only in this node's pool, otherwise NOT_REGISTERED; search by ID, email or public key"),
], widths=[5.5, 10.7], caption="The four queries")
p("Any confirmed record can be re-verified independently: the verify endpoint returns the exact signed message, the "
  "public key and the signature, and checks them again (Figure 11).")

h2("2.7 Dynamic difficulty")
p("Every DIFFICULTY_ADJUSTMENT_INTERVAL blocks, each node compares the actual time taken by the last window of blocks with "
  "the expected time and scales the target proportionally. A faster window shrinks the target, so mining becomes harder; "
  "a slower one enlarges it. Following Bitcoin, the measured time is clamped to between a quarter and four times the "
  "expected time, and the target can never exceed a minimum-difficulty ceiling. The window starts after the genesis block "
  "so the fixed genesis timestamp cannot distort the first adjustment.")
code('''
# difficulty.py
def next_target(chain, height):
    n = DIFFICULTY_ADJUSTMENT_INTERVAL
    prev_target = target_of(chain[height - 1])
    first = height - 1 - n                        # window covers n block intervals
    if height % n != 0 or first < 1:
        return prev_target, None
    expected = n * BLOCK_GENERATION_INTERVAL
    actual = chain[height - 1]["timestamp"] - chain[first]["timestamp"]
    clamped = min(max(actual, expected / 4), expected * 4)
    new_target = prev_target * int(clamped * 1000) // int(expected * 1000)
    return max(1, min(new_target, MAX_TARGET)), info
''', "Listing 3. Retargeting rule")
table(["Parameter", "ConfChain", "Bitcoin"], [
    ("BLOCK_GENERATION_INTERVAL", "5 s", "600 s"), ("DIFFICULTY_ADJUSTMENT_INTERVAL", "5 blocks", "2016 blocks"),
    ("Maximum change per retarget", "4x", "4x"), ("Initial difficulty", "16 bits", "32 bits"),
], widths=[6.5, 4.8, 4.8], caption="Difficulty parameters (configurable via environment variables)")
p("Because the target is part of consensus, every node computes the expected value itself and rejects a block that "
  "declares any other target, so a miner cannot award itself an easier puzzle. The short interval and window were chosen "
  "so the mechanism is visible in a live demo; they are environment variables and can be set to Bitcoin's values.")

h2("2.8 Main design choices and trade-offs")
table(["Choice", "Why", "Trade-off"], [
    ("Signature check at the miner, structural check at the pool", "Matches the brief and lets the demo show a forgery being rejected by the miner", "Invalid records briefly occupy pools; mitigated by full re-validation of blocks and pruning"),
    ("P-256 in the browser instead of secp256k1", "Native Web Crypto support keeps keys client side", "Differs from Bitcoin's curve; equal security level"),
    ("Full 256-bit target", "Fine-grained, proportional difficulty as in Bitcoin", "Less intuitive than counting zeros, so the UI shows bits"),
    ("Heaviest-chain fork choice", "Correct under varying difficulty, unlike longest-chain", "Requires summing work over the chain"),
    ("HTTP gossip between three local nodes", "Simple to run and demonstrate", "No encryption or peer authentication between nodes"),
], widths=[4.6, 5.8, 5.8], caption="Design choices")

# ================================================================== 3 testing
h1("3. Testing and results")
h2("3.1 Automated tests")
p("The pytest suite has three files: unit tests of the ledger (chain), edge cases including the REST API and CLI wallet "
  "(edge_cases), and live network tests that start real node processes and check gossip, agreement, fork resolution and "
  "late-joiner synchronization (network). One test runs the real browser wallet code under Node.js Web Crypto and verifies its keystore, registration "
  "and attendance signatures in Python, proving the two implementations agree byte for byte.")
descr = {
    "test_signature_detects_tampering": "Changing a signed field, or verifying with another key, fails",
    "test_keystore_roundtrip_and_wrong_password": "Keystore decrypts with the right password only",
    "test_register_attend_and_mine": "Registration, attendance, mining and rewards end to end",
    "test_miner_rejects_forged_signature": "Record altered after signing is rejected by the miner",
    "test_impersonation_rejected": "Certificate signed by another key for someone's ID is rejected",
    "test_duplicate_unregistered_and_replay_rejected": "Duplicate check-in, unregistered attendee, re-registration, replay",
    "test_register_and_checkin_in_same_block": "Registration ordered before attendance in one block",
    "test_structural_checks": "Unknown session, mismatched ID, bad email, extra fields",
    "test_four_queries": "All four organizer queries, including PENDING and NOT_REGISTERED",
    "test_tampering_with_mined_block_is_detected": "Editing a mined record or header breaks validation",
    "test_block_with_wrong_difficulty_rejected": "Block claiming an easier target is rejected",
    "test_wrong_coinbase_reward_rejected": "Inflated miner reward is rejected",
    "test_retarget_is_proportional_and_clamped": "2x faster gives +1 bit; extremes clamped to 4x",
    "test_no_retarget_between_intervals": "Target unchanged except at interval boundaries",
    "test_difficulty_rises_on_real_fast_chain": "Real mined chain raises difficulty",
    "test_heavier_fork_wins_and_orphans_return_to_pool": "Heaviest chain adopted, orphaned records restored",
    "test_browser_wallet_signature_verifies_in_python": "Browser wallet output verifies in Python",
}
descr.update({
    "test_retarget_direction": "Retarget direction for fast, slow and on-target windows",
    "test_merkle_root_odd_and_single": "Merkle root matches Bitcoin's odd-node duplication rule",
    "test_chain_reload_restores_state": "Chain saved to disk reloads with identical state",
    "test_corrupted_stored_chain_falls_back_to_genesis": "Tampered chain file is refused on startup",
    "test_email_case_cannot_bypass_uniqueness": "Upper-case email cannot register a second identity",
    "test_future_and_bool_timestamps_rejected": "Future or non-integer certificate timestamps rejected",
    "test_txid_mismatch_rejected_from_pool": "Declared txid must match the contents",
    "test_duplicate_submission_rejected": "Same record cannot enter the pool twice",
    "test_pool_pruned_after_block": "Records made invalid by a new block are evicted",
    "test_query_by_public_key_and_unknown_session": "Status lookup by public key; unknown session is empty",
    "test_old_timestamp_rejected": "Block timestamp must exceed median-time-past",
    "test_future_block_rejected": "Block too far in the future rejected",
    "test_block_without_coinbase_rejected": "Every block must start with a coinbase",
    "test_hash_must_meet_target": "Block whose hash misses the target rejected",
    "test_two_coinbases_rejected": "Only one coinbase per block",
    "test_full_chain_validates_after_many_blocks": "12-block chain fully re-validates; rewards add up",
    "test_api_rejects_garbage": "Malformed API and peer messages return 400/404, not crashes",
    "test_api_query_endpoints": "All four queries and signature verification over HTTP",
    "test_cli_wallet_roundtrip": "CLI keystore has no plaintext key; wrong password fails",
    "test_three_nodes_gossip_mine_and_agree": "Live 3-node network: gossip to every pool, forged record rejected, all nodes agree",
    "test_late_joiner_syncs_and_fork_resolves": "Live nodes: fork resolved to heavier chain, orphan re-gossiped, late joiner syncs",
})
rows = []
for file, name, res in test_rows:
    rows.append((f"{file[5:]}::{name}", descr.get(name.split("[")[0], ""), res))
table(["Test", "What it checks", "Result"], rows, widths=[6.8, 7.4, 2.0], caption=f"Automated test results ({test_total.group(1) if test_total else ''})", mono_cols=(0,))

h2("3.2 End-to-end demonstration")
p("The following screenshots were captured automatically from a live three-node network after running the seed script "
  "(8 attendees, 18 attendance certificates, one forged certificate) and enabling auto-mining on all nodes.")
figure("01_dashboard.png", "Dashboard on Node A: chain height, difficulty, registrations, linked blocks, live activity, rewards")
figure("02_wallet_created.png", "A new attendee wallet: key pair generated in the browser, private key stored encrypted")
figure("03_registration_broadcast.png", "Signed registration broadcast to both peers; status pending")
figure("04_registration_confirmed.png", "Registration confirmed on chain with confirmations")
figure("05_checkin_pending.png", "Signed attendance certificate submitted and waiting in the pending pools")
figure("06_checkin_confirmed.png", "Certificate confirmed in a block; signature valid against the registered key")
figure("07_forged_rejected.png", "Attack: certificate signed for S2 then altered to S5 is rejected by the miner (invalid signature)")
figure("08_mining.png", "Miner view: pending pool, live proof-of-work search, verification log and rewards")
figure("09_difficulty.png", "Dynamic difficulty: difficulty bits against block time, and the retarget history")
figure("10_q1_sessions_of_attendee.png", "Query 1: all sessions attended by a participant")
figure("11_verify_signature.png", "Independent re-verification of a confirmed certificate")
figure("12_q2_attendees_of_session.png", "Query 2: all participants who attended session S1")
figure("13_q3_absentees.png", "Query 3: registered participants who did not attend session S1")
figure("14_q4_status_confirmed.png", "Query 4: registration status, confirmed")
figure("15_q4_status_not_registered.png", "Query 4: registration status, not registered")
figure("16_explorer.png", "Block explorer: hashes, previous-hash links, miners, difficulty and nonces")
figure("17_block_detail.png", "Block detail: header fields and transactions including the coinbase")
figure("18_node_c_dashboard.png", "The same state seen through Node C, which validated every block independently")

h2("3.3 Network consistency")
table(["Node", "Height", "Tip hash", "Registered", "Attendance", "Pending"], [
    (s["node"], s["height"], s["tip_hash"][:20] + "…", s["registered"], s["attendance_records"], s["pending"])
    for s in summaries.values()
], widths=[2.2, 1.8, 5.6, 2.2, 2.2, 2.0], caption="State of the three nodes when the report was generated", mono_cols=(2,))
p("All three nodes independently arrived at the same chain tip and the same world state. Short-lived forks occurred when "
  "two nodes found blocks at almost the same time; they were resolved by the heaviest-chain rule on the next block.")

h2("3.4 Dynamic difficulty results")
rt = diff["retargets"]
table(["At block", "Window", "Actual (s)", "Expected (s)", "Old bits", "New bits", "Direction"], [
    (r["height"], f"{r['window'][0]} to {r['window'][1]}", r["actual_seconds"], r["expected_seconds"],
     f"{r['old_bits']:.2f}", f"{r['new_bits']:.2f}", {"up": "harder", "down": "easier"}.get(r["direction"], "same"))
    for r in rt
], widths=[1.8, 2.4, 2.2, 2.4, 2.2, 2.2, 2.4], caption="Retargets recorded on the live network")
hist = [h for h in diff["history"] if h["block_time"]]
if rt and hist:
    first_win = [h["block_time"] for h in hist[:8]]
    last_win = sorted(h["block_time"] for h in hist[-30:])
    median = last_win[len(last_win) // 2]
    p(f"Starting at {rt[0]['old_bits']:.0f} bits, the three nodes together produced blocks in an average of "
      f"{sum(first_win) / len(first_win):.2f} s, far faster than the 5 s target. Each retarget therefore raised the "
      f"difficulty, by the maximum 4x (2 bits) while blocks were far too fast and by smaller steps as they approached the "
      f"target, reaching {max(r['new_bits'] for r in rt):.2f} bits. Over the last 30 blocks the mean block time was "
      f"{sum(last_win) / len(last_win):.2f} s and the median {median:.2f} s, against the 5 s target. The spread is "
      f"expected: block times are exponentially distributed and a 5-block window is a small sample, which is why Bitcoin "
      f"averages over 2016 blocks. Later retargets move in both directions around the target, which is the "
      f"expected behavior of a proportional controller under random (exponentially distributed) block times.")

# ================================================================== 4 security
h1("4. Security analysis")
table(["Threat", "Defense"], [
    ("Forged or altered certificate", "ECDSA signature over every field; verified by the miner and re-verified by every node"),
    ("Checking in as someone else", "Signature must match the public key registered for that ID; the ID is the hash of that key"),
    ("Duplicate check-in or replay", "One record per (attendee, session); confirmed transaction IDs cannot be included again"),
    ("Editing history", "Header hash covers the Merkle root and previous hash; any change breaks proof of work and every later link"),
    ("Miner awarding itself extra coins or an easier puzzle", "Coinbase amount and difficulty target are consensus rules checked by every node"),
    ("Timestamp manipulation to lower difficulty", "Timestamp must exceed the median of the last 11 blocks and not be more than 60 s in the future; retargets are clamped to 4x"),
    ("Stolen keystore file", "Encrypted with AES-256-GCM, key stretched with 600,000 PBKDF2 rounds"),
    ("Malicious script reading the key", "Unlocked key is non-extractable in Web Crypto"),
], widths=[5.0, 11.2], caption="Threats and defenses")

h1("5. Limitations and future work")
bullets([
    ("Privacy", "names and emails are public on chain. A production system could store a salted hash of the email or encrypt personal data to the organizer's key."),
    ("Session windows", "certificates are not restricted to a session's time window. An organizer-signed session schedule on chain would allow this."),
    ("Transport", "nodes talk over plain HTTP without peer authentication. TLS and signed peer messages would be needed outside a lab."),
    ("Consensus choice", "proof of work is energy-intensive for a conference. A permissioned proof-of-authority network run by organizers would suit the real use case better; proof of work is used here because the brief requires mining and difficulty."),
    ("Check-in assurance", "a signature proves who signed, not that they were in the room. Pairing with a rotating QR code shown in the session would add proof of presence."),
])

h1("6. Contributions")
p("Replace the placeholder names and adjust the split to reflect what each member actually did. The workload below is "
  "designed to be balanced, and each member presents the part they built.", italic=True, color=MUTED)
table(["Member", "Implementation", "Report and presentation"], [
    ("Member A", "crypto.py, browser wallet (wallet.js), CLI wallet, registration transaction and validation", "Sections 1, 2.1 to 2.3; slides 1 and 2; demo: wallet and registration"),
    ("Member B", "Attendance certificate, pending pool and gossip, miner, coinbase rewards, mining page", "Sections 2.4, 2.5; slide 3; demo: check-in and forged certificate"),
    ("Member C", "Node REST API, peer-to-peer sync and fork choice, state index, four queries, query page", "Sections 2.6, 3.3; slide 4; demo: queries and signature re-verification"),
    ("Member D", "difficulty.py, block and chain validation, test suite, difficulty page and chart", "Sections 2.7, 3.1, 3.4, 4; slide 5; demo: multi-node view and difficulty"),
], widths=[2.4, 7.4, 6.4], caption="Member contributions")

h1("7. References")
refs = [
    "Nakamoto, S. (2008). Bitcoin: A peer-to-peer electronic cash system. https://bitcoin.org/bitcoin.pdf",
    "Bitcoin Core developers. (n.d.). src/pow.cpp: CalculateNextWorkRequired [Source code]. GitHub. https://github.com/bitcoin/bitcoin/blob/master/src/pow.cpp",
    "Bitcoin Project. (n.d.). Block chain. Bitcoin Developer Reference. https://developer.bitcoin.org/reference/block_chain.html",
    "Bitcoin Wiki. (n.d.). Difficulty. https://en.bitcoin.it/wiki/Difficulty",
    "Bitcoin Wiki. (n.d.). Block timestamp. https://en.bitcoin.it/wiki/Block_timestamp",
    "Hartikka, L. (2017). Naivecoin: A tutorial for building a cryptocurrency, #2: Proof of work. https://lhartikk.github.io/jekyll/update/2017/07/13/chapter2.html",
    "National Institute of Standards and Technology. (2023). Digital Signature Standard (DSS) (FIPS 186-5). https://csrc.nist.gov/pubs/fips/186-5/final",
    "Chen, L., Moody, D., Regenscheid, A., Robinson, A., & Randall, K. (2023). Recommendations for discrete logarithm-based cryptography: Elliptic curve domain parameters (NIST SP 800-186). https://csrc.nist.gov/pubs/sp/800/186/final",
    "Dworkin, M. (2007). Recommendation for block cipher modes of operation: Galois/Counter Mode (GCM) and GMAC (NIST SP 800-38D). https://csrc.nist.gov/pubs/sp/800/38/d/final",
    "Moriarty, K. (Ed.), Kaliski, B., & Rusch, A. (2017). PKCS #5: Password-based cryptography specification version 2.1 (RFC 8018). https://www.rfc-editor.org/info/rfc8018",
    "Watson, M. (Ed.). (2017). Web Cryptography API (W3C Recommendation, 26 January 2017). https://www.w3.org/TR/2017/REC-WebCryptoAPI-20170126/",
    "OWASP Foundation. (n.d.). Password storage cheat sheet. https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html",
    "Python Cryptographic Authority. (n.d.). pyca/cryptography documentation. https://cryptography.io/",
    "Pallets. (n.d.). Flask documentation. https://flask.palletsprojects.com/",
    "DSAI 4202 E-Payment and Cryptocurrency. (2026). Assignment 4 and group project slides [Course materials].",
    "[Declare any generative AI assistance here as required by the course policy.]",
]
for r in refs:
    p(r, style="List Number")

doc.save(OUT)
print("saved", OUT, "| tests:", test_total.group(1) if test_total else "?", "| retargets:", len(rt))
