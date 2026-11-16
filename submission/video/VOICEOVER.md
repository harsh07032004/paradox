# Idea video: voice-over script (3:31)

Read each line while its scene is on screen, at a calm pace. There is a short pause after every line and the video moves on by itself.
Record with the voice-over studio page, or read along with `Paradox_idea_video.mp4`. `python -m submission.video.build_video` rebuilds the video and these timings.

| Time | Scene | Say |
|---|---|---|
| 0:00 to 0:09 | Title | Hi, we're Team Byte Code, and this is Paradox, our idea for the security track of VoyageHack. |
| 0:09 to 0:28 | The problem | Here's the thing about B2B travel. The bugs that cost real money don't look like bugs. A refund that pays out twice? The server says two hundred, OK. Same with a fare the agent sets themselves, or one agency reading another agency's passports. |
| 0:28 to 0:35 | The idea | Scanners look for bad inputs. We look for outcomes that should be impossible. |
| 0:35 to 0:54 | 1 · Learn | Paradox starts with just what TBO gives us: a staging link, a few test accounts, some recorded traffic and logs. No API docs. From that, it works out the routes, how people actually book, who owns what, and where the money sits. |
| 0:54 to 1:07 | 2 · Mutate | Then it plays with those journeys the way a sneaky user would. Cancel twice. Skip the payment. Set your own fare. Pretend to be another agency. |
| 1:07 to 1:24 | 3 · Check the laws | After each try, it checks twelve simple rules. Your wallet can't end up richer. The same booking can't get cheaper. One agency never sees another's data. If a rule breaks, that's a finding. If not, it stays quiet. |
| 1:24 to 1:42 | Proof | Like this one. Cancel a booking that's already cancelled, and the wallet gains seven thousand seven hundred and seventy-six rupees. Every single time. Paradox ran it three times to be sure, and cut it down to just four requests. |
| 1:42 to 1:54 | Canary data | Every booking it creates carries fake details: a made-up name, email and passport. If those turn up in another agency's account, the leak proves itself. |
| 1:54 to 2:07 | Ticket | Each finding turns into a ticket for the team that owns that code, with what it costs in rupees, the exact steps, and how to fix it. |
| 2:07 to 2:24 | After a deploy | And it keeps watching. When a new release went out, Paradox tested the changed part first. The new amend feature trusted whatever total the client sent. It was flagged as critical about twelve seconds later. |
| 2:24 to 2:32 | Retest | Once the fix shipped, Paradox re-ran its proofs, and the fixed tickets closed on their own. |
| 2:32 to 2:42 | API inventory | Along the way, it maps every endpoint, even an old version one route nobody remembered, which was still leaking passports. |
| 2:42 to 2:55 | Results | Does it work? We planted a hundred and seventy-two random bugs. Paradox found all of them, with zero false alarms. A regular scanner found about thirty percent. |
| 2:55 to 3:10 | Holdout | We also tried it on an airline platform it had never seen. After two small, general fixes, it caught all seven planted bugs, and stayed silent on the clean version. |
| 3:10 to 3:23 | Safety | And it's careful. It stays in scope, only touches its own test bookings, slows down if the server struggles, has a kill switch, and logs every request. |
| 3:23 to 3:31 | Close | That's Paradox. It catches the bug that makes money appear, before someone else does. Thank you. |
