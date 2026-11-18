# Presentation and demo plan (8 minutes)

2 min slides, 4 min live demo, 2 min Q&A. Every member speaks in both the talk and the demo.

## Before you walk in (10 minutes before)

1. `python run_network.py --fresh`
2. `python scripts/seed_demo.py` (8 attendees, 18 check-ins, 1 forged record rejected)
3. Open http://127.0.0.1:5001, go to Dynamic Difficulty, click **Auto-mine on all nodes**. Let it run at least 3 minutes so the chart shows the climb and the settle. Stop it before the demo if the laptop fan gets loud; the chart stays.
4. In the browser, import one seeded wallet (Wallet page, Import keystore, `wallets/ATT-...json`, password `demo1234`) as a fallback.
5. Zoom the browser to 110 to 125 percent so the back row can read it.

Backup plan: the full flow is in `docs/screenshots/` (01 to 18). If anything fails live, switch to those and keep talking.

## Slides (2:00)

| Time | Slide | Speaker |
|---|---|---|
| 0:00 to 0:50 | 1 Title, 2 Architecture | Member A |
| 0:50 to 1:15 | 3 Signatures and mining | Member B |
| 1:15 to 1:35 | 4 Queries | Member C |
| 1:35 to 2:00 | 5 Dynamic difficulty | Member D |

Speaker notes in the deck hold the exact lines.

## Live demo (4:00)

| Time | Who | Do | Say |
|---|---|---|---|
| 0:00 | A | Wallet page. Create "Demo Student", any email, password. | "Key pair generated in the browser. The private key is encrypted with my password and never sent to the node." |
| 0:25 | A | Click **Sign & register on chain**. Badge goes Pending, then Registered. | "Signed registration, broadcast to all three nodes, now confirmed in a block." |
| 0:50 | B | Session Check-in. Pick Demo Student, session S5, **Sign & broadcast**. Point at the 4 steps and the certificate JSON. | "Attendee ID, session, timestamp, signed with ECDSA. It is in every node's pending pool... and now mined." |
| 1:30 | B | Tick **Attack demo**, sign for S1, change to S4, submit. | "I changed one field after signing. The pool accepts it, but the miner verifies the signature and rejects it." |
| 2:00 | B | Pending Pool & Mining page. Show miner log line "invalid signature" and the 50 CONF rewards. | "Valid blocks pay the miner 50 CONF through the coinbase." |
| 2:20 | C | Attendance Queries. Q1: type "Alice". Q2: S1. Q3: S1. Q4: Demo Student's email, then a made-up email. | "Sessions per person, attendees per session, registered absentees, and status: confirmed, pending, or not registered." |
| 3:00 | C | In Q1 click **Verify signature**. | "Any organizer can re-verify the original signature against the public key on chain." |
| 3:15 | D | Switch Connected node to Node C. | "Node C has its own copy and reaches the same state independently." |
| 3:25 | D | Dynamic Difficulty page: chart and retarget table. | "Blocks came every fraction of a second at 16 bits, so each retarget raised difficulty, capped at 4x, until block times hovered around the 5 second target." |
| 3:50 | D | Back to Dashboard. | "That covers all four functions, all four queries, and dynamic difficulty. Questions?" |

## Likely questions and short answers

- **Why does the pool accept a forged record?** The spec makes signature checking the miner's job, so we show it there. Every node still re-verifies every signature in every block it receives, and pools are pruned after each block.
- **Where is the private key?** Only in the attendee's browser, as AES-256-GCM ciphertext. Once unlocked it is a non-extractable Web Crypto key, so even page scripts cannot read the bytes.
- **What stops someone checking in as another attendee?** The certificate must verify against the public key registered for that attendee ID, and the ID is the hash of that key. Test `test_impersonation_rejected`.
- **Replays or double check-ins?** One record per (attendee, session), and a confirmed txid cannot be included again.
- **Why ECDSA P-256 and not secp256k1 like Bitcoin?** Browsers support P-256 natively in Web Crypto, which lets keys stay client side. Security level is equivalent (128-bit).
- **How do forks resolve?** Heaviest chain by cumulative work, as in Bitcoin. Records from orphaned blocks go back to the pool.
- **Why can a miner not fake an easier target?** Every node computes the expected target from the chain itself and rejects any other value. Test `test_block_with_wrong_difficulty_rejected`.
- **Why the clamp?** Bitcoin limits each retarget to 4x so a burst of timestamps cannot swing difficulty wildly. We also require timestamps after the median of the last 11 blocks.
- **Limitations?** Emails are public on chain (could store a salted hash), no session time windows, HTTP not HTTPS between nodes, and proof of work is energy-intensive for a conference; a permissioned design could use proof of authority.
