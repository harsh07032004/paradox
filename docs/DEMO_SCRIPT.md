# Video scripts

## Round 1: idea video (about 2 minutes, voice over the 2 content slides)

**0:00 Hook (cover slide).**
"In a B2B travel platform the expensive bugs don't look like bugs. A refund that pays out twice returns HTTP 200. So does a fare the client sets to one rupee, or an agency reading another agency's passports. Scanners look for bad inputs. We built Paradox, which looks for impossible outcomes."

**0:15 The idea (slide 1, the loop).**
"Paradox gets exactly what TBO gives teams: a staging URL, test accounts at two agencies, recorded traffic, gateway logs and deploy events. No API docs. From the front-end bundle and the recordings it learns the routes, the user journeys, which response value feeds which request, who owns each object, and where the money is. It finds the wallet balance by experiment."

**0:40 Invariants (slide 1, left panel).**
"Then it mutates real journeys. It repeats a cancel, skips a payment, grafts a cancel onto a discounted booking, sets the fare in the request, swaps the agency, drops the session. After every run it checks twelve laws that hold for any correct platform. An agency's wallet never ends a sequence richer than it started. The same booking never costs less. Agency A's data never reaches agency B. A finding exists only when a law breaks."

**1:05 What's new (slide 1, right panel).**
"Each object it creates carries canary data, a unique name, email and passport, so a leak is proven by the canary itself. Each money bug is measured in rupees on a shadow ledger. Each proof is replayed three times from fresh objects and delta-debugged down to the few requests that matter."

**1:25 Impact and feasibility (slide 2).**
"It already works. We injected 172 random defects across 22 runs: Paradox found all 172 with zero false positives. A signature-based scanner on the same inputs found 30%, and none of the money or isolation bugs. On an airline platform it had never seen, with a different auth scheme, ids and states, it found all seven planted bugs and reported nothing on the clean build."

**1:45 Safety and close.**
"Safety is enforced in code: a scope allowlist, it only touches objects it created, a rate cap with back-off, a kill switch, and a replayable audit log. Policy questions go to a human. Paradox: catch the bug that makes money appear, before someone else does."

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
