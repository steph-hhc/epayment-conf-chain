"""Build the 5-slide presentation deck: python docs/build_slides.py

Reads screenshots from docs/screenshots and live difficulty numbers from Node A.
"""
import json
import urllib.request
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

HERE = Path(__file__).parent
SHOTS = HERE / "screenshots"
OUT = HERE / "ConfChain_Presentation.pptx"

NAVY, NAVY2 = "121624", "1D2234"
INDIGO, INDIGO_SOFT = "4F46E5", "EEF0FF"
MINT, MINT_SOFT = "0F9D6B", "E6F6EF"
RED, RED_SOFT = "D64545", "FDECEC"
BG, WHITE, TEXT, MUTED, LINE = "F5F6F9", "FFFFFF", "171B26", "667085", "E4E7EE"
ICE = "C9CEDE"
HEAD, BODY, MONO = "Segoe UI Semibold", "Segoe UI", "Consolas"

rgb = lambda h: RGBColor.from_string(h)


def bg(slide, color):
    f = slide.background.fill
    f.solid()
    f.fore_color.rgb = rgb(color)


def text(slide, x, y, w, h, runs, size=16, color=TEXT, font=BODY, bold=False, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP, spacing=None, name=None):
    """runs: str, or list of paragraphs; each paragraph a str or list of (text, {opts})."""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        tb.name = name
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = anchor
    paras = [runs] if isinstance(runs, str) else runs
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        if spacing:
            p.space_after = Pt(spacing)
        for t, o in ([(para, {})] if isinstance(para, str) else para):
            r = p.add_run()
            r.text = t
            r.font.size = Pt(o.get("size", size))
            r.font.bold = o.get("bold", bold)
            r.font.italic = o.get("italic", False)
            r.font.name = o.get("font", font)
            r.font.color.rgb = rgb(o.get("color", color))
    return tb


def box(slide, x, y, w, h, fill, line=None, radius=0.08, shape=MSO_SHAPE.ROUNDED_RECTANGLE, name=None):
    s = slide.shapes.add_shape(shape, Inches(x), Inches(y), Inches(w), Inches(h))
    if name:
        s.name = name
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = radius
    s.fill.solid()
    s.fill.fore_color.rgb = rgb(fill)
    if line:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(1)
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    return s


def image(slide, path, x, y, w, h, frame=True, name=None):
    """Fit image inside the box (keeps aspect ratio), centered horizontally, top-aligned."""
    iw, ih = Image.open(path).size
    scale = min(w / iw, h / ih)
    dw, dh = iw * scale, ih * scale
    dx = x + (w - dw) / 2
    if frame:
        box(slide, dx - 0.06, y - 0.06, dw + 0.12, dh + 0.12, WHITE, LINE, radius=0.03)
    pic = slide.shapes.add_picture(str(path), Inches(dx), Inches(y), Inches(dw), Inches(dh))
    if name:
        pic.name = name
    return dx, y, dw, dh


def code(slide, x, y, w, h, src, size=12, name=None):
    box(slide, x, y, w, h, NAVY, radius=0.04, name=name)
    lines = []
    for line in src.strip("\n").split("\n"):
        if line.lstrip().startswith("#"):
            lines.append([(line, {"color": "7D849B"})])
        else:
            lines.append([(line or " ", {"color": "E8EAF2"})])
    text(slide, x + 0.25, y + 0.22, w - 0.5, h - 0.44, lines, size=size, font=MONO)


def title(slide, t, sub=None):
    text(slide, 0.6, 0.45, 12.1, 0.7, t, size=32, font=HEAD, color=TEXT, name="Title")
    if sub:
        text(slide, 0.6, 1.15, 12.1, 0.4, sub, size=15, color=MUTED, name="Subtitle")


def pill(slide, x, y, w, label, fill, color):
    box(slide, x, y, w, 0.34, fill, radius=0.5)
    text(slide, x, y, w, 0.34, label, size=11, color=color, bold=True, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)


def arrow(slide, x1, y1, x2, y2, color=MUTED):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = rgb(color)
    c.line.width = Pt(2)
    ln = c.line._get_or_add_ln()
    from pptx.oxml.ns import qn
    tail = ln.makeelement(qn("a:tailEnd"), {"type": "triangle", "w": "med", "len": "med"})
    ln.append(tail)


def live_difficulty():
    try:
        with urllib.request.urlopen("http://127.0.0.1:5001/api/difficulty", timeout=3) as r:
            d = json.load(r)
        rt = d["retargets"]
        hist = [h for h in d["history"] if h["block_time"]]
        last, first = hist[-30:], hist[:8]
        return {"start": rt[0]["old_bits"], "peak": max(r["new_bits"] for r in rt), "end": rt[-1]["new_bits"],
                "n": len(rt), "avg": sum(h["block_time"] for h in last) / len(last), "blocks": len(hist) + 1,
                "first": sum(h["block_time"] for h in first) / len(first)}
    except Exception:
        return None


# =====================================================================================
prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
blank = prs.slide_layouts[6]

# ---------------------------------------------------------------- 1. title
s = prs.slides.add_slide(blank)
bg(s, NAVY)
text(s, 0.7, 0.75, 5.6, 0.35, "DSAI 4202 · E-Payment and Cryptocurrency · Group Project", size=12, color="3CCF95", bold=True)
text(s, 0.7, 1.2, 5.6, 1.0, "ConfChain", size=54, font=HEAD, color=WHITE, name="Title")
text(s, 0.7, 2.25, 5.4, 1.1, "Tamper-proof conference registration and attendance on a peer-to-peer proof-of-work blockchain",
     size=18, color=ICE)
stats = [("3 nodes", "gossip, pending pools, fork choice"), ("4 / 4", "functions and organizer queries"),
         ("ECDSA P-256", "keys never leave the browser"), ("Dynamic PoW", "Bitcoin-style retargeting")]
for i, (big, small) in enumerate(stats):
    cx, cy = 0.7 + (i % 2) * 2.75, 3.75 + (i // 2) * 1.35
    box(s, cx, cy, 2.55, 1.15, NAVY2, radius=0.1)
    text(s, cx + 0.22, cy + 0.17, 2.2, 0.5, big, size=22, font=HEAD, color=WHITE)
    text(s, cx + 0.22, cy + 0.67, 2.2, 0.4, small, size=11.5, color=ICE)
text(s, 0.7, 6.65, 6, 0.35, "Member A  ·  Member B  ·  Member C  ·  Member D", size=13, color=ICE)
image(s, SHOTS / "01_dashboard.png", 6.75, 1.85, 6.0, 5.6, frame=False, name="Dashboard screenshot")
s.notes_slide.notes_text_frame.text = (
    "Speaker: Member A (about 20 s).\n"
    "We built ConfChain, a blockchain for conference check-in. Three nodes run a real peer-to-peer network. "
    "Attendees hold their own keys in a browser wallet, sign attendance certificates, miners verify every signature "
    "before mining, and organizers run four queries. Difficulty adapts automatically, like Bitcoin.")

# ---------------------------------------------------------------- 2. architecture
s = prs.slides.add_slide(blank)
bg(s, BG)
title(s, "From a signed check-in to a confirmed block",
      "Every node keeps its own pending pool and chain copy, and re-verifies everything it receives")
steps = [
    ("Attendee wallet", "Browser · Web Crypto", ["Generate P-256 keys", "Sign records locally"], INDIGO),
    ("Node A / B / C", "Flask REST + gossip", ["Format check", "Pool + gossip to peers"], INDIGO),
    ("Miner", "Proof of Work", ["Verify each signature", "PoW, +50 CONF reward"], MINT),
    ("Blockchain", "Heaviest valid chain", ["Merkle root, hash links", "Re-verified by all nodes"], MINT),
    ("Organizer", "Query API", ["4 attendance queries", "Re-check signatures"], INDIGO),
]
w, gap, y0 = 2.22, 0.27, 1.95
for i, (h1, h2, items, col) in enumerate(steps):
    x = 0.6 + i * (w + gap)
    box(s, x, y0, w, 2.3, WHITE, LINE, radius=0.07)
    box(s, x + 0.2, y0 + 0.22, 0.42, 0.42, col, shape=MSO_SHAPE.OVAL)
    text(s, x + 0.2, y0 + 0.22, 0.42, 0.42, str(i + 1), size=14, bold=True, color=WHITE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, x + 0.2, y0 + 0.75, w - 0.3, 0.35, h1, size=15, font=HEAD)
    text(s, x + 0.2, y0 + 1.07, w - 0.3, 0.3, h2, size=11, color=MUTED)
    text(s, x + 0.2, y0 + 1.45, w - 0.3, 0.8, [[("• " + it, {})] for it in items], size=11.5, spacing=2)
    if i < len(steps) - 1:
        arrow(s, x + w + 0.03, y0 + 1.07, x + w + gap - 0.03, y0 + 1.07)
cards = [
    ("Identity", "attendee_id = SHA-256(public key). REGISTER is self-signed, proving the registrant owns the key. Email must be unique."),
    ("Secure wallet", "Private key stored as AES-256-GCM ciphertext, key from password via PBKDF2 (600k rounds). Unlocked as a non-extractable key."),
    ("Consensus rules", "Exact difficulty target, median-time-past timestamps, coinbase = 50 CONF, no duplicate or replayed records."),
]
for i, (h, body) in enumerate(cards):
    x = 0.6 + i * 4.13
    box(s, x, 4.55, 3.88, 2.3, INDIGO_SOFT if i != 2 else MINT_SOFT, radius=0.07)
    text(s, x + 0.3, 4.8, 3.3, 0.4, h, size=17, font=HEAD, color=INDIGO if i != 2 else MINT)
    text(s, x + 0.3, 5.3, 3.3, 1.5, body, size=13.5, color=TEXT)
s.notes_slide.notes_text_frame.text = (
    "Speaker: Member A (about 30 s).\n"
    "Walk left to right. The wallet signs in the browser, so the private key never reaches a server. The node checks the format, "
    "puts the record in its pending pool and gossips it to the other two nodes. A miner verifies each signature, mines the block "
    "and earns 50 CONF. Every other node re-validates the whole block before accepting it, and forks resolve to the chain with the most work.")

# ---------------------------------------------------------------- 3. signatures & mining
s = prs.slides.add_slide(blank)
bg(s, BG)
title(s, "Only validly signed records reach the chain",
      "The pool accepts any well-formed record; the miner's signature check is the gate")
code(s, 0.6, 1.8, 6.3, 3.75, '''
# chain.py · Blockchain.build_candidate()  (miner)
for entry in pending_pool:
    tx = entry["tx"]
    ok, reason = state.check(tx, verify_signature=True)
    if ok:
        state.apply(tx)
        accepted.append(tx)
    else:
        rejected.append((tx, reason))   # dropped
txs = [make_coinbase(miner, height)] + accepted

# State.check() for an attendance certificate
key = registry[tx["attendee_id"]]["public_key"]
if not verify(key, payload(tx), tx["signature"]):
    return False, "invalid signature"
''', size=12.5)
pill(s, 0.6, 5.8, 1.9, "Forgery", RED_SOFT, RED)
pill(s, 2.6, 5.8, 1.9, "Impersonation", RED_SOFT, RED)
pill(s, 4.6, 5.8, 2.3, "Replay / duplicate", RED_SOFT, RED)
text(s, 0.6, 6.3, 6.3, 0.8, "All three are rejected and covered by automated tests (40 passing), including signatures made by the real browser wallet verified in Python.",
     size=13, color=MUTED)
image(s, SHOTS / "el_forged.png", 7.3, 1.8, 5.45, 5.2, name="Forged certificate rejected")
s.notes_slide.notes_text_frame.text = (
    "Speaker: Member B (about 25 s).\n"
    "The certificate contains attendee ID, session ID and timestamp, signed with ECDSA. Here we signed for S2 and changed it to S5 afterwards. "
    "The pending pool accepts it because it is well formed, but the miner verifies the signature against the registered public key and rejects it, "
    "so it never reaches the chain. Valid records are packed behind the coinbase transaction that pays the miner.")

# ---------------------------------------------------------------- 4. queries
s = prs.slides.add_slide(blank)
bg(s, BG)
title(s, "Four organizer queries, answered from chain state",
      "An index rebuilt by replaying every block, so the chain stays the single source of truth")
qs = [
    ("1", "Sessions attended by a participant", "GET /api/query/attendee/<id>/sessions"),
    ("2", "Participants who attended a session", "GET /api/query/session/<sid>/attendees"),
    ("3", "Registered but did not attend", "GET /api/query/session/<sid>/absentees"),
    ("4", "Registration status of anyone", "GET /api/query/status?q=<id | email | key>"),
]
for i, (n, h, ep) in enumerate(qs):
    y = 1.8 + i * 1.28
    box(s, 0.6, y, 5.6, 1.1, WHITE, LINE, radius=0.08)
    box(s, 0.82, y + 0.28, 0.54, 0.54, INDIGO, shape=MSO_SHAPE.OVAL)
    text(s, 0.82, y + 0.28, 0.54, 0.54, n, size=16, bold=True, color=WHITE, align=PP_ALIGN.CENTER, anchor=MSO_ANCHOR.MIDDLE)
    text(s, 1.6, y + 0.2, 4.5, 0.4, h, size=15, font=HEAD)
    text(s, 1.6, y + 0.6, 4.5, 0.35, ep, size=11.5, font=MONO, color=MUTED)
text(s, 0.6, 6.95, 5.6, 0.4, "Status = CONFIRMED (with confirmations), PENDING, or NOT REGISTERED", size=12, color=MUTED)
image(s, SHOTS / "el_q1.png", 6.65, 1.8, 6.1, 2.6, name="Sessions of attendee result")
image(s, SHOTS / "el_q3.png", 6.65, 4.65, 6.1, 2.4, name="Absentees query result")
s.notes_slide.notes_text_frame.text = (
    "Speaker: Member C (about 20 s).\n"
    "Each node replays the chain into an index of registrations and attendance, so queries are instant. Absentees are all registered "
    "attendees minus confirmed attendance. Status distinguishes confirmed, still pending in the pool, and not registered. "
    "Any result can be re-verified: the UI shows the signed message, public key and signature check.")

# ---------------------------------------------------------------- 5. dynamic difficulty
s = prs.slides.add_slide(blank)
bg(s, BG)
d = live_difficulty()
title(s, "Difficulty adapts to the network's hash power",
      "Retarget every 5 blocks toward 5 s per block (Bitcoin: every 2016 blocks toward 10 minutes)")
code(s, 0.6, 1.8, 5.3, 2.85, '''
# difficulty.py (simplified)
expected = N * BLOCK_INTERVAL
actual = ts[h-1] - ts[h-1-N]
actual = clamp(actual, expected/4, expected*4)
new_target = old_target * actual / expected

# faster than expected -> smaller target -> harder
# slower than expected -> larger target  -> easier
''', size=12.5)
if d:
    callouts = [(f"{d['start']:.0f} → {d['peak']:.1f}", "difficulty bits, first to peak"),
                (str(d["n"]), f"retargets in {d['blocks']} blocks"),
                (f"{d['avg']:.1f} s", f"avg block time, last 30 (start: {d['first']:.1f} s)")]
else:
    callouts = [("16 → 25", "difficulty bits"), ("×4", "max change per retarget"), ("5 s", "target block time")]
for i, (big, small) in enumerate(callouts):
    x = 0.6 + i * 1.8
    box(s, x, 4.9, 1.65, 1.5, WHITE, LINE, radius=0.08)
    text(s, x + 0.15, 5.05, 1.4, 0.6, big, size=19, font=HEAD, color=INDIGO)
    text(s, x + 0.15, 5.65, 1.4, 0.7, small, size=11, color=MUTED)
text(s, 0.6, 6.6, 5.3, 0.6, "Every node recomputes the target; a block declaring any other target is rejected.", size=12.5, color=MUTED)
image(s, SHOTS / "el_difficulty_chart.png", 6.3, 1.8, 6.45, 2.8, name="Difficulty chart")
image(s, SHOTS / "el_retargets.png", 6.3, 4.85, 6.45, 2.2, name="Retarget history")
s.notes_slide.notes_text_frame.text = (
    "Speaker: Member D (about 25 s).\n"
    "Every 5 blocks each node measures how long the last window took. Too fast means the target shrinks and mining gets harder; too slow, easier. "
    "Like Bitcoin we clamp each change to four times and work with the full 256-bit target, so steps can be fractional. "
    "The chart shows three nodes starting at 16 bits: blocks were far too fast, so difficulty climbed until block times hovered around the 5 second target, with the usual random spread. "
    "Then we switch to the live demo.")

prs.save(OUT)
print("saved", OUT)
