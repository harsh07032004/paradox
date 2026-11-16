# Video scripts

## Round 1: idea video

The finished muted video is `submission/video/Paradox_idea_video.mp4` (3:30). The spoken lines and their timings are in `submission/video/VOICEOVER.md`. To add a recorded voice, run `python -m submission.video.add_voice <recording>`.

## Round 2: prototype walkthrough (3–4 minutes, screen recording of `python run_demo.py`)

| Time | On screen | Say |
|---|---|---|
| 0:00 | Control room, cycle starting | "Release v3.0 is production as it is today. Paradox starts with no spec." |
| 0:15 | Agent activity: ledger located, 22 endpoints, inventory | "It located the wallet by experiment, learned 22 endpoints and 7 journeys, and found 4 routes nobody documented." |
| 0:35 | Inventory table: zombie v1, shadow partner/rates, retired v2 | "The v1 booking route was last called 104 days ago and still answers: a zombie. Partner rates are used but undocumented: shadow. v2 correctly returns 410." |
| 0:55 | Findings appear | "First verified finding about a second in. Double refund: cancel a cancelled booking and the wallet grows by ₹7,776, every time." |
| 1:15 | Open the double-refund finding | "Minimal proof: book, pay, cancel, cancel. The wallet column shows the money appear. Owner booking-core, fix suggested, curl repro in the ticket." |
| 1:40 | Zombie v1 cross-agency finding | "Delhi's sub-agent reads Goa's booking through the forgotten v1 route, and the leaked passport is our own canary." |
| 2:00 | Needs a human panel | "A sub-agent can read the markup. Is that allowed? It's a policy question, so Paradox asks instead of filing." |
| 2:15 | Deploy v3.1 event | "Now a deploy ships a new feature, amend booking. Paradox sees the bundle diff and tests the new route first." |
| 2:35 | Amend underpayment finding with ₹ | "Seconds after the deploy: the amend call accepts a client total. Same booking, ₹20,000 less." |
| 2:55 | Deploy v3.1.1, findings turn FIXED | "The hotfix ships. Paradox reruns every proof; the fixed tickets close themselves, and the unfixed PII bug stays open." |
| 3:15 | Kill switch, audit | "Kill switch stops traffic before the next request. Every request is in the audit log." |
| 3:30 | Terminal: benchmark + holdout tables | "172 of 172 injected defects, zero false positives, and seven of seven on a platform it was never built for." |
