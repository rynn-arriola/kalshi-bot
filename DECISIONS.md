# Operator decision ledger

This is the authority record. AI agents may recommend decisions but may not mark
them accepted without an explicit operator instruction.

## Current ranking/admission decision

D-069 accepts the reference audit's selection direction for offline construction.
It does not authorize live selection, price chasing, new risk limits or trading.
D-070 extends it with Poly-style bounded discovery and estimated reward tracking,
and explicitly withdraws the proposed fixed 60-market pool.

### D-178 — Follow Polymarket's current entry strategy (no waits)

- **Status:** ACCEPTED for the paper run, 2026-10-05. Operator: "Follow
  current polymarket entry strategy". Polymarket removed the 20 s wait
  ("it blocked most fills") and the esports 30 s wait ("the 3c book cap covers
  spikes") after D-177; Kalshi drops both. Overwatch paper rule ask <= 98c as
  Polymarket. 3-option soccer ("team wins" YES, 2 goals from 88' or 3+ from
  80') becomes a main rule as on Polymarket (still paper on Kalshi). The
  stale-feed skip, live-book re-check, test band and Kalshi-only paper rules
  stay.

### D-177 — Esports per title, stale-feed skip, 20 s hold (from Polymarket)

- **Status:** ACCEPTED for the paper run, 2026-10-04. Operator: "I changed
  esport rule again on polymarket check it if can be applied on kalshi".
  Source: liquidity-bot BC-2026-10-03-B (~18:45Z and ~19:00Z entries) and
  ENDGAME_RULE_RESEARCH_2026-10-04.md (Kalshi 60-day replay per title, fit on
  the first half, checked on the second).
- **Esports per title** (milestone details 'game'; best of 3/5 from Kalshi's
  total-maps market): CS2 1-0 or 1-1 (Bo3/Bo5), 97c, ask <= 98c (842 trades,
  0.83% lost); Dota 2 Bo3 at 1-1 only, 97c, ask <= 99c (77/0); Valorant Bo3 at
  1-1 only, 95c, ask <= 98c (68/1); League of Legends Bo3 at 1-0 or Bo5 at
  2-1/2-2, 98c, ask <= 99c (low confidence); all with a 3c gap and a 30 s
  hold. Paper only: Rainbow Six (no total-maps market on Kalshi, so it waits
  for one) and Overwatch (forced first-to-3 at 2-1/2-2).
- **Feed guards:** no buy when a game's live data has not changed for 15
  minutes (Kalshi has no per-game update time, so the trader watches the data
  itself; esports excluded, its state changes only between maps); every rule
  waits 20 s of continuous qualification before buying (esports 30 s).

### D-176 — Endgame rules from the Polymarket rule research, plus Kalshi-only data

- **Status:** ACCEPTED for the paper run, 2026-10-04. Operator: "Check what we
  did on polymarket for end game trader and optimize it based on kalshi api or
  what kalshi offers". Source: liquidity-bot
  docs/history/ENDGAME_RULE_RESEARCH_2026-10-04.md and BC-2026-10-03-B (Kalshi
  minute prices x play-by-play / goal timelines; NHL 2023-26; MLB 2025-26).
  Polymarket live so far: 223 won, 6 lost (+$17.83).
- **Bug fixed:** NHL milestones ('hockey_match') fell into the rugby branch, so
  the 2nd period counted as the last (found by that research).
- **Rules now (paper):** soccer 2 goals from 88' or 3+ from 80' (both soccer
  markets; 85' was break-even, 88' +$0.31/trade, 1-goal leads draw 5.7% at
  90+4); hockey 2+ goals in the last 2:00 (NHL: 0.23% lost; 1-goal 8%);
  baseball 9th+ with 3+ runs (329 MLB games: 0 lost; 2 runs 1.7%); basketball
  7+ in the last 2:00 at 97c (0 of 28 lost); football last 3:00 with 9+ only
  while the leader has the ball (Kalshi situation.possession_team_id vs the
  milestone's home/away team ids; unknown = skip) or 17+ in the last 2:00
  (402 games: 0 of 39 lost; the old 4:00 window lost 4 of 72); esports CS2
  only (60 days: CS2 0.83% lost vs LoL 3.7%, Valorant 2.5%), best of 3/5 read
  from Kalshi's total-maps market (unknown = skip), 97c middle, ask <= 98c,
  gap <= 3c, qualifying for 30 s before buying; other esports titles paper
  only ('esports-other'); tennis deciding match tiebreak needs 9+ points and a
  3-point lead.
- **Kalshi-only additions:** every buy re-checks the trigger on the live order
  book it fills from (the event listing lagged: two 'rule' fills at 87c and
  94c); a paper 'soccer-no-trailer' rule buys NO on the trailing team with a
  1-goal lead from 88' (wins on a draw too; Kalshi 1 loss in 286) — Kalshi
  lets us buy NO, Polymarket's research could only paper it; the score
  recorder also keeps football possession and CS2 in-map rounds for the next
  study. `endgame_trader.py status --since <UTC time>` reports one rule set.
- **Not done (next):** a freshness gate (Kalshi last_updated_ts looks like a
  batch time, not per game), CS2 in-map round rules (needs recorded data),
  tennis server/point score.

### D-175 — Endgame Trader on Kalshi (dry run for data); liquidity farmer switched off

- **Status:** ACCEPTED for a dry run (paper trades only), 2026-10-03. Live
  orders are NOT authorized and this build has no order code.
  Operator: "build something i did on polymarket like the endgame trader,
  switch off this current liquidity farmer", "Still on same account and also
  doing all sport", "use polymarket as reference like how they enter trade",
  99c cap kept ("Then its ok"), "lets start testing this", "open as much
  position we can handle to get all data", "Or we doing it just for data? Then
  90-99c", "We can decide anyways what is measure for live".
- **Farmer:** stopped, disarmed and latched 2026-10-03 (no auto-restart).
  D-174 is committed but not deployed. Before re-enabling the farmer on the
  same account, endgame positions (once live) must be settled and recorded
  (D-165 style) or they read as unknown positions.
- **Entry (Polymarket late-favourite parity):** game almost over by sport
  (below); clock sports not tied; two-sided book with spread <= 10c; middle
  price >= 95c (esports 97c) — the market's view, not a model (Polymarket has
  no separate "real value" calculation); ask <= 99c; a win clears the taker
  fee; cheapest qualifying favourite; YES on the favourite's own winner market
  only (never Tie, never NO). Size $30 on the 99c cap = 30 contracts (operator
  10-03: "change the risk to 30 usd and stop loss to 90 usd a day"; Polymarket
  uses $10/$50; paper trades before this change are $10); the full
  size must be on the book at <= 99c (filled at the walked average); one trade
  per event; hold to settlement. 99c nets +$0.09 per 10 after the $0.01 fee
  (break-even 99.1% wins).
- **Soccer (operator, 10-03: "Advances", "I dont want the one with 3
  options", "Lets track that for now add it for paper"):** trades the
  2-option cup 'advances' markets (extra time and penalties count; two-leg ties
  on the aggregate): almost over at 90'+ stoppage or 120'+ of extra time with
  an aggregate lead, never during penalties, and only when the market is due
  to settle within 3 h (not a first leg). The 3-option 90-minute game market
  (Team/Tie/Team; buy "team wins" YES only) is tracked on paper only as
  'soccer-3way'. Both are new to Kalshi (Polymarket had no advance rule), so
  both are marked experimental.
  Operator 10-03 "Ok do that then restart": both soccer rules now copy
  Polymarket's soccer rule (from 80', 2+ goal lead; aggregate for advances).
  All four soccer losses that evening (Racing Louisville, Ospitaletto,
  Floresta 1-0 and Hamilton 2-1, equalised in stoppage time) were 1-goal
  leads; all 31 soccer paper trades so far had 1-goal leads.
- **Per sport (Kalshi live data):** basketball last quarter/2nd half or OT
  <= 2:00 with a 7+ point lead (operator 10-03 "Ok do it", after the 14-day
  replay: late basketball favourites at 95-96c lost ~2-3%, 0 of 113 at 97c+;
  close games are the cause); football Q4/OT <= 4:00 with a 9+ point lead
  (Polymarket 10-03, after Villanova 35-31 lost to a late touchdown); hockey
  P3/OT <= 2:00 (NHL is milestone type 'hockey_match', added 10-03 after it
  was found unwatched; the status line now lists any live sport type without
  a rule; darts has no live score and stays out); baseball 9th inning+ with a
  2+ run lead (Polymarket rule); tennis best-of-3 leader a set up with >= 5
  games and ahead in the current set; table tennis one game away with a 6+
  point lead; esports one map away (97c). Experimental (paper only even when
  live): rugby 2nd half <= 2:00 with an 8+ lead, volleyball one set away with
  >= 20 points and a 5+ lead. Cricket and boxing excluded.
- **Dry-run data:** no open-position cap; one 'rule' trade (95-99c) and one
  'data' trade (middle 90c up to the rule) per event; the $90 daily stop is
  reported as "would stop" only. `scripts/endgame_trader.py status` reports
  win rate and result by band, sport and price cent.
- **Alerts and recovery (operator 10-03: "update me if bot stop or
  started", "Pc wont ever restart so what i want this should recover when bot
  stopped"):** the trader writes a heartbeat every poll; Windows task
  `KalshiEndgameWatch` runs `scripts/endgame_watch.py` every minute: down
  (no poll for 2 min) → ntfy alert and automatic restart (stuck process ended
  by exact command line), at most 5 restarts per hour 3 min apart, then one
  urgent alert and a pause; never while data/endgame/STOP exists; "started"
  alert when back; "running but failing" alert when no poll has read Kalshi
  for 10 min (alert only) and "recovered" when it reads again. Live-game
  lookback 24 h (Polymarket). Every restart, even a quick one, sends a
  "restarted" alert (the trader records its start time; operator: "How come i
  dont get notif on ntfy whenever u restart"). Topic URL in data/endgame/ntfy_url.txt (not
  committed).
- **14-day replay (10-03, 7,697 team markets that reached 90c+):** price
  alone has no edge (95c trigger, any time: 2.95% lost, -$0.03/trade); late in
  the game (last 20% of its time) it does: at the 95c trigger tennis 0.9% lost
  (+$0.55/trade, n=1,549), esports 0.9% (+$0.47), table tennis 0/114, hockey
  0/68, baseball 2.2% (+$0.21), football 1.9% (+$0.20); 3-option soccer 2.9%
  (-$0.05) even late, so it stays paper only. Early buys lose in every sport.
- **Paper test floors and recorder (operator 10-03 "Ok apply it"):** a
  'test' band below the rule, paper only: tennis and table tennis from 92c,
  esports from 95c (14-day replay, late: tennis 92c 1.7% lost +$0.92/trade,
  table tennis 92c +$0.47, esports 95c +$0.47 vs +$0.21 at 97c). The trader
  also records every live game's score/clock (tables games, snapshots) once a
  minute and on each score change, kept 21 days, so lead rules can be tested
  against Kalshi's minute price history. Operator 10-04 "All sports": the
  92c test floor now applies to every sport (esports 95c). Paper so far
  (10-04 16:00 UTC): test band 47/47 +$60.16 (tennis 32/32 +$48.46), rule
  without soccer 159/162 +$8.16, tennis rule 98/100 -$0.04.
- **Next:** after 2-3 days of data the operator picks the live rules per sport
  and price; then live order code (signed IOC buy, uncertain-order block,
  account position cap, farmer-running refusal) is built and tested before any
  live order.

### D-174 — A full project list replaces its slowest project with a 2x faster one

- **Status:** ACCEPTED, implemented and verified offline, 2026-10-03.
  Operator: "Look more into this and lets make a decision" → "Do
  recommendation" (C: this now, NFL pregame pilot later) → "Ok do 1".
- **Evidence (10-03):** the 30-minute scan ranks the big pools (NFL props
  score 30 vs Costco 7.7) but 83% of the top 150 unworked markets are blocked
  by design: 63 `early_close_unreviewed` (gas, "Trump says") and 62
  `milestone_missing` (NFL props: the game milestone lists them only as
  related events). 25 are eligible and score 2–5x our median working market
  (2.68), yet the list was full of slow projects. Live NFL prop share at 50
  contracts: 0.66% of ~$200/day ≈ $1.32/day per market (Costco ≈ $1.50) at
  ~$46 per pair; deep queues (5–9k contracts ahead) make sweeps unlikely.
- **What:** when the list is full, a new contract that would reach $1.50 at
  least 2x faster than the slowest project replaces it (`displaced_by_faster_
  contract`). Protected: projects with $0.50+ earned and D-173 urgent ones.
  Unknown-rate projects count as slowest only after the first 10 minutes of
  planning (rates are learned after a restart); at most one replacement per 10
  minutes. Resting orders are not cancelled; the new contract ranks ahead.
- **Next (B, next week):** NFL props pregame pilot (link props to the game
  milestone's related events; pull before kickoff) and a review rule for
  scheduled-data early closes; live watch-list refresh (existing admission)
  after this is proven.

### D-173 — Ending-soon list, payout matcher, rush projects near $1 before their deadline

- **Status:** ACCEPTED, implemented and verified offline, 2026-10-02.
  Operator: "Cant we track markets that gonna end" → "So how come we did not
  track it" → "Ok do recommendation".
- **Evidence (11:27 UTC):** 73 programs ending within 5 days had ≥ $0.05
  metered; only Costco 95 ($1.19) and 96.5 ($1.11) would pay; Bozeman $0.78
  and Case-Shiller $0.75 end 10-04 04:31 and ranked like any other project.
  Reward programs run 1–2 weeks and end days before their markets. The 10-02
  $1.43 credit is most likely KXGEMINIAPP-26OCT08-T70 (ended 04:11, credit
  10:30; most qualifying time), not provable from the meter (started 09-29).
- **What:** (1) status `lip_meter.ending_soon`: programs ending within 96 h
  with ≥ $0.05, soonest first, `pays` flag. (2) Each unattributed credit is
  matched to the closest estimate among programs that ended in the last 36 h
  with ≥ $0.75 (`lip_meter.payouts`, kept 50; event `reward_credit_matched`);
  an estimate, never accounting. (3) Project order: a project under $1 whose
  program ends within 48 h and can still reach $1 in time ranks first,
  soonest deadline first; others keep closest-to-target order.

### D-172 — Hold at a price; held resting orders do not block a flat stop

- **Status:** ACCEPTED, implemented and verified offline, 2026-10-02.
  Operator: "Lets build number 2 and 3".
- **Cause found:** the 10-02 recovery-only run could not finish because the
  ledger counts every ACKNOWLEDGED (resting) intent as unresolved; the held
  market's own 48¢ reducer alone made "verified flat" impossible (not a
  refresh race). It finished within a minute once that order was cancelled.
- **What:** (1) `verified_flat` asks `unresolved_outside(holds)`: resting
  orders in held markets are excluded; RESERVED/SENDING/UNKNOWN there still
  count. (2) `holds.json` may add `"exit_prices": {ticker: "0.78"}` for held
  tickers; the bot then keeps exactly one reducer for the whole held position
  at that price (replacing any other), never moves it to the middle and never
  crosses; an emergency flatten still overrides. Malformed prices stop launch.
- **Meter:** ended programs are already kept 14 days (`KEEP_DAYS`); the 10-02
  $1.43 credit predates the meter (started 09-29), so it is matched via the
  Kalshi Rewards page instead.

### D-171 — 4-hour cross, never cross a near-empty side, operator hold, no ad spend

- **Status:** ACCEPTED, implemented and verified offline, 2026-10-02.
  Operator: "lets wait 3 hours to force exit" → "actually make it 4 hours" →
  "Go 1-4"; on the swept position: "I'll say leave that open".
- **Evidence:** 01:37:54 UTC one seller swept 865 contracts at 77¢ in
  KXAMUSEMENTADS-26NOV06-T155, filling our 50 bid; the next bid was 8¢
  against asks at 76¢. The patient exit would have crossed at 30 min into
  that 8¢ bid (−$35, inside the $0.80/contract cap). Replay of 40 entry fills
  on Kalshi 1-minute candlesticks (cross at the bid/ask): 15 min −$151.62,
  30 min −$149.01, 1 h −$141.75, 3 h −$144.75, 6 h −$138.75.
- **What:** (1) `EXIT_CROSS_SECONDS` 1800 → 14400 (middle-price reducer from
  15 min unchanged; the event/close deadline still forces). (2) A non-forced
  cross is deferred when the side it would cross into is under half the
  middle of other traders' quotes (one-sided books leave it to the loss cap).
  (3) Operator hold: `data/trader/holds.json` {"tickers": [...]}; the bot
  places, moves and cancels nothing for a held position (its orders stay),
  an explicit emergency flatten still overrides, and held positions/orders/
  exposure do not block a verified-flat stop; a malformed file stops launch.
  (4) Ad-spend series (`ADS$`, Carbon Arc) join the avoided types.
  Also: a selection row without its fee reserve is blocked
  (`entry_fee_reserve_missing`) instead of crashing (01:01 and 01:13 KeyError).
- **Held now:** KXAMUSEMENTADS-26NOV06-T155, long 50 @ 77¢, our sell 50 @ 78¢
  resting; settles on Carbon Arc's October value (~Nov 5–13).

### D-170 — Project markets get priority for fresh market terms; keep 50 contracts

- **Status:** ACCEPTED, implemented and verified offline, 2026-10-01.
  Operator: "Look more into this" → "Ok do recommendation and fix it".
- **Evidence (D-169 diagnostics, 18:10 UTC):** 39 of 50 projects showed
  `selection_evidence_unavailable`; 0 batches were discarded (that theory is
  ruled out). Market terms live ≤ 60 s and refresh through one scheduler
  queue for ~1,024 markets (1,020 pending); projects ranked as discovery (0).
  Live LIP share by size across our 25 resting markets (others hold 250–4,000
  contracts in the scoring window): median 5% at 30, 8% at 50 (+61%), 12% at
  80. An earlier 10-minute meter comparison (+4%) compared 50 with 50 and is
  withdrawn. So 50 contracts stays.
- **What:** `_metadata_priority` ranks project markets 1 (with remembered
  priority candidates), after owned safety (2), before discovery (0). Load:
  ~50 projects × one refresh per ≤ 60 s ≈ 1/s against ~9/s capacity.
- **Watch:** `project_reasons` latest = `selection_evidence_unavailable`
  should fall well below 39; orders should rise toward 50.

### D-169 — Project list back to 50; log why each project idles

- **Status:** ACCEPTED, 2026-10-01. Operator: "Check what is really happening
  then recommend me" → "Do all recommendation they review it then restart".
- **Evidence:** orders averaged 41–44/h at 11–14 UTC (list 50) and 20–22/h
  after the D-167 list cut to 35. Live books: 153 of 158 top markets and all
  35 projects pass the 70% exit check at 50 contracts (size is not the
  cause); fill-risk pulls and short-queue triggers were unchanged. Of 35
  projects at 17:30: 10 had orders, 3 had a known block (two coal markets
  after a losing fill, one at 19¢), 22 had no externally visible reason.
  `selection_sources_changed` rose from 6–19 to 44–90 per proposal.
- **What:** MAX_LIST 35 → 50 (stopgap); status `selection.project_reasons`
  (per project: latest reasons and counts per proposal: added, retained,
  each exclusion, `batch_discarded_sources_changed`, `not_evaluated`) and
  `discarded_batches` / `discarded_additions` / `discarded_samples`
  (a whole batch dropped because one market's source changed). Diagnostics
  only; selection is unchanged. 50 contracts kept.
- **Next:** after about an hour of data, fix the dominant idle reason (if it
  is the whole-batch discard, drop only the stale market).

### D-168 — Keep project progress; committed projects pass the $2 gate

- **Status:** ACCEPTED, implemented and verified offline, 2026-10-01.
- **Decision owner:** Operator: "Do recommendation" (after the 15:59 log check).
- **Evidence:** the D-167 restart treated the 50-project saved list as
  invalid under MAX_LIST 35 and started empty (16 closed records lost; Costco
  97 at $0.40 left out). Then only 15 of 35 projects had orders (30 orders,
  $618): the `priority_revalidation_pending` / initial-ranking gate admits only
  markets projected ≥ $2 while it refreshes, and project markets earn ~4¢/h;
  deferred new claims also stayed on the list without orders.
- **What:** (1) a list above MAX_LIST keeps the best-earning projects and
  closes the rest as `list_limit_trimmed`; only lists above 1,000 count as
  corrupt. (2) At launch, metered programs with $0.25 ≤ earned < $1.50, not
  ended, not avoided, not dropped as hopeless or avoided rejoin the list,
  best first, while it has room. (3) Projects committed before a selection
  pass the $2 gate (it protects ranking completeness; they are already
  chosen); a project claimed in that selection and then deferred is
  unclaimed. All entry, risk and loss checks are unchanged.

### D-167 — 50 contracts per order after the $490 deposit; project list 35

- **Status:** ACCEPTED, 2026-10-01. Operator: "i added 490 how much we
  increase size" → "Contract size max 100 maybe" → "Dont change stop loss" →
  "Which is better increase contract number or increase order number" → "Go
  50 then".
- **What:** approved money set ($1,090 capital, 50 contracts); `config/bot.json`
  capital 1090, entry_contracts 50, managed_market_slots 11 (portfolio
  exposure cap 50 × 21 = $1,050; per-market cap $450). Order cap stays 50;
  the 24-hour stop stays $60 (D-162). Project list (`MAX_LIST`) 50 → 35: at
  50 contracts cash covers about 25 working pairs plus 10 places for blocked
  projects; 50 spread resting time too thin (50 projects, 21 working).
- **Why size, not more orders:** total reward is cash-limited either way;
  bigger orders concentrate it so markets reach the $1 floor sooner (none of
  183 metered markets had reached $1 after two days; best $0.39). Rejected
  100: one typical bad fill (−$23–60) could trip the unchanged $60 stop.
- **Watch:** reward rate per market vs size (in thin books we may already
  hold most of the qualifying size), fill losses per event (typical
  −$12–30 now), stop trips.

### D-166 — Only projects with working orders count toward the project limit

- **Status:** ACCEPTED, implemented and verified offline, 2026-10-01.
- **Decision owner:** Operator: "How come orders is only 34?" → "Ok do all
  recommendation" (option 1 of 3).
- **Evidence:** 10:42 UTC, 8 h after start: 30 projects, only 18 with orders
  (36 of 50 entry orders); 12 blocked projects (entry filters, unverified
  reward reflection) kept the list "full" and 14 new markets were turned away
  (`project_list_full`). About 7 pairs idle ≈ $5/day of reward at ~3¢/h.
- **What:** a new project may join while fewer than 30 projects have working
  orders (`MAX_PROJECTS`, counted from the portfolio's working exposure) and
  the whole list is under 50 (`MAX_LIST`). Blocked projects keep their place
  and first priority when they can rest again. Rejected: raising the list to
  50 only (blocked projects still hold slots); dropping idle projects (loses
  progress toward $1.50).

### D-165 — Record a settled operator trade; no more manual trades on this account

- **Status:** ACCEPTED, implemented and verified offline, 2026-10-01.
- **Decision owner:** Operator: "I did combo today ... Its settled already, ok
  build it, i wont manual".
- **What happened:** while the bot was stopped the operator bought 294.65 YES
  of a combo (KXMVECROSSCATEGORY-S202686A632D740B-B9E601E5DE5) at 25.8¢ (fee
  $3.9485) on exchange shard 1; Kalshi moved $79.98 from shard 0 to fund it;
  it settled NO (revenue 0). Both starts on 10-01 then failed recovery
  (`missing_fills_not_yet_imported`) and stopped flat: the bot cannot explain
  a fill, a transfer, a settlement and $79.98 of missing cash it did not cause.
- **What:** `operator_trades.record` adopts one settled trade in a market the
  bot never traded, once, while stopped, only if fills, settlement and funding
  transfers agree exactly; the cash change per shard is journaled as an
  `operator_trade` cash adjustment (cold cash audit reproduces it). Recovery,
  the settlement proof and the cash-activity check accept only those recorded
  digests; anything new or changed still blocks. Never bot P&L: no lots,
  fills, realized events or loss-limit effect. Applied by
  `data/reconcile_D165_operator_combo.py` (dry run unless `--apply`, backup
  first).
- **Going forward:** the operator will not trade manually on this account; a
  separate Kalshi subaccount is the safe place for any manual trading.

### D-164 — Capital setting $600 (account about $600)

- **Status:** ACCEPTED, 2026-09-30. Operator: "Can we still support 50 orders
  only have 600 usd" → "Ok do recommendation and restart".
- **What:** approved money set ($600 capital, 30 contracts) in
  `config/bot.json`, with `managed_market_slots` 10 so the portfolio exposure
  cap (30 × (10+10) = $600) does not exceed capital. The 50-entry cap and size
  30 are unchanged.
- **Evidence:** 307 entry orders since 09-27 tied up $11.35 each on average
  (p90 $19.80); 50 orders ≈ $567. Free cash and the $600 exposure cap simply
  place fewer orders when cash runs short (no error, no overspend).
- `window_stop_usd` stays in the approved tuple but is unused since D-162.

### D-163 — Patient exit, and entry order: projects, juicy finished, ranking

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-30.
- **Decision owner:** Operator: "Ok lets do patient exit"; "project list
  priority then the one we already completed because its guaranteed we will
  get paid but only if reward is good, then next is based on ranking".
- **Patient exit (replaces D-160's 15-minute cross; the $0.80/contract loss
  cap stays):** after a fill the exit rests at our best price (one-tick
  improvement) for 15 minutes, then at the tick nearest the middle of the book
  (never crossing), and may cross only from 30 minutes (`EXIT_MIDDLE_SECONDS`,
  `EXIT_CROSS_SECONDS`). The event/close deadline still forces the exit.
  Evidence: replaying our 11 fully marked losing fills, crossing at 30 minutes
  lost $31.20 against $42.70 at 15 minutes and $48.90 at 1 minute; right after
  a sweep the thin book is empty and refills.
- **Entry order:** (1) project-list contracts still working toward $1.50,
  closest first; (2) contracts already past $1 whose reward rate is at least
  5¢/hour for our pair (`JUICY_RATE_USD`, about our top 10%): payment is
  guaranteed and every further cent is paid; (3) everything else — new
  projects and other contracts past $1 — in the board's normal reward ranking.
  Contracts past $1 never take a project slot. Every loss check still applies.
- **Watch:** exit cost per losing fill (WATCHLIST B8) and whether juicy
  finished contracts attract fills.

### D-162 — One loss limit: $60 net over the last 24 hours

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-30.
- **Decision owner:** Operator: "I think we should not have time frame stop
  loss and just have a 24 hr stop loss of 60 max ... We dont need to track 6
  hours anymore".
- **What:** new entries stop while the net realized trading result (fills and
  fees, gains offset losses) of the last 24 hours is −$60 or worse
  (`risk.DAILY_LOSS_LIMIT`, `LOSS_LOOKBACK`); they resume by themselves as
  older losses age out. Below the limit the full 50-entry cap applies (no
  step-downs). Exits, pulls and protection never stop.
- **Supersedes:** the six-hour America/New_York windows with the $25 stop and
  $5 step-downs (D-016/D-017/D-138) and their latched trip, which was never
  released (Finding 225). `release_previous` and the cached window totals
  (`realized_incremental`) are removed; the old tables stay unused.
- **Unchanged internally:** the six-hour clock still bounds account-proof
  lifetimes (not a loss rule). Status `loss_window` shows the 24-hour view.

### D-161 — Measure reward per contract in real time before concentrating

- **Status:** ACCEPTED plan, 2026-09-29. Step 1 (meter) implemented and verified
  offline 2026-09-29 (`lip_meter.py`); takes effect at the next approved restart.
- **Step 1 as built:** every 5 s, each contract with our orders resting (entries
  and exits, from the live private order stream) is scored in its live book
  (read-only; quiet books count) with the bot's Kalshi scoring
  (`quoting.program_plans`); each program's rate is integrated per interval
  (rate at the interval's start; gaps over 15 s or unknown views are not
  credited). Saved to `data/trader/lip_meter.json` every 5 min; status
  `runtime.lip_meter`; calibration report section "LIP meter per contract"
  compares Kalshi's payout with the meter after the $1-per-contract floor.
  Cost measured ~19 ms per sample of 50 contracts.
- **Step 3 (phase 3) as built, 2026-09-29 (operator: "Ok build it"):**
  `finish_line.FinishLine`, fed by the meter, orders new entries: contracts we
  have started and not yet past $1 first (fewest resting hours to $1.25 first),
  then new contracts fastest to $1.25, then contracts already past $1 (by rate);
  it blocks new entries (`cannot_reach_payout_minimum`) in contracts that would
  need more than half their remaining earning time to reach $1.25. Ordering and
  eligibility only; all loss checks unchanged; never cancels resting orders.
  Deploy only with the operator's go (the plan said after the meter matches a
  payout).
- **Project list (operator: "Build it", 2026-09-29):** measured after phase 3
  went live, 3.1 h spread over 131 contracts (median 0.27 resting hours each;
  $1 needs 22-36), because every contract with any earnings counted as
  "started". Now new entries go only to a saved list of at most 30 projects
  (`data/trader/projects.json`; 25 pairs plus 5 so a temporarily blocked
  project never leaves an entry slot idle): a contract joins only while the list has
  room and it can reach $1.25 needing at most half its remaining earning
  time (fastest first); it stays until the meter shows $1 (cleared) or $1
  becomes unreachable even resting all remaining time (dropped). Contracts
  already past $1 may use idle entry slots (every further cent is paid);
  other contracts are blocked (`project_list_full`). Stop the waste: resting
  orders in a contract that cannot reach $1 are withdrawn
  (`cannot_reach_payout_minimum`, only with a live reward estimate). Launch
  pins projects into the watched scope. Calibration report: "Projects" and
  "Waste: contracts that ended under $1".
- **Avoided market types (Finding 224, operator "Do recommended", 2026-09-30):**
  app rank, card spend, port TEU, diesel and mortgage contracts are never
  entered or kept as projects (`sweep_prone_market_type`); existing projects of
  those types are dropped on the next review.
- **Results filter on the family memory (2026-09-30):** a family (series)
  that filled us stays blocked for 7 days only if its realized trading result
  in those 7 days lost at least $1 more than the LIP the meter credited it;
  harmless fills stop blocking one hour after the last fill; results unknown
  keep it blocked. Writer read `recent_results`; status `fill_cooldown`
  shows `losing_families`.
- **$1.50 target per market (operator, 2026-09-30):** "we should not target a
  dollar ... this is per individual market not pool ... Maybe 1.50 usd Not 2
  usd". A contract joins the project list only if it can reach $1.50 needing at
  most half its remaining earning time, and stays until the meter shows $1.50 in
  that one market's program (earnings above $1 are paid in full, so the extra
  time is not wasted); it is still dropped only if even $1 becomes
  unreachable. Never summed across an event, series or pool. Evidence: the
  $4.22 credit of 2026-09-30 matched two Alaska diesel contracts (6.60 $2.32,
  6.70 $1.98 resting-based; 98% of the estimate), ~6-7 pair-hours each.
- **Decision owner:** Operator, adopting outside advice from an experienced
  Kalshi LIP trader: "Are we making sure we do it this way".
- **Facts adopted:** Kalshi's $1 payout floor applies **per contract (market
  ticker), not per event**: ten contracts at 10¢ each pay nothing; one contract
  at $1 pays. A script can compute cumulative LIP earned so far to within a few
  percent. Recording L2 (order book) data makes backtesting reward and risk
  possible.
- **Why:** our two estimates are far off (Kalshi paid 3.9× the strict tracker,
  which marks most time "unknown"; the resting-based estimate is untested), and
  we store no books (Finding 221 could test a thin-book rule on only 4 fills).
  09-28: 150 programs, ~$0.80 estimated in total, paid $0.
- **Order of work (do not reorder without the operator):**
  1. **Real-time LIP meter per contract:** replicate Kalshi's snapshot scoring
     (our qualifying size vs everyone's, weighted by distance from the best
     price, within the target size) continuously for every contract we rest
     on; cumulative earned vs $1 per contract; validated against payouts
     (target: within a few percent). Replaces the strict and resting-based
     estimates in the calibration report.
  2. **L2 recording** of watched markets (compact snapshots), sized against the
     disk and storage guard first; used to backtest the meter, fill risk and
     exits.
  3. **Phase 3 ($1 finish line)** built on the meter: fewer contracts, each
     driven past $1 before it ends.
- **Boundary:** measurement first; no trading change until the meter is
  validated against at least one payout.

### D-160 — Exit after 15 minutes like Polymarket: loss limit per contract

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-28; takes
  effect at the next approved restart.
- **Decision owner:** Operator: "at 15 minute i think we should exit flat
  like polymarket" (Finding 222, WATCHLIST B8). Claude had recommended holding
  plus a step-toward-mid reducer; the operator chose the Polymarket rule.
- **What:** after 900 s an ordinary exit crosses (price-capped IOC) unless the
  projected loss including the fee bound is worse than $0.80 per contract
  (`exits.ORDINARY_EXIT_LOSS_PER_CONTRACT`), i.e. the Polymarket reference $8 at
  size 10, $24 at 30, proportionally less for partial positions. Replaces the
  flat $8 that held 30-contract positions after a 27-cent move.
- **Unchanged:** the passive reducer first 15 minutes, 50% depth haircut
  (thin books still defer), cancel-confirm before IOC, three IOC attempts, and
  forced exit at the event/close deadline regardless of loss.
- **Effect at deploy:** any position already older than 15 minutes is closed
  at once if within the limit (KXUALCC short 30 @ 0.30: about −$8.70).

### D-159 — Launch the watch list from the latest saved full-market scan

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-27; takes
  effect at the next approved restart.
- **Decision owner:** Operator: "Ok do option A" (Finding 220, option A).
- **Why:** in live broad mode the 1,024 watched markets are fixed at launch,
  so D-158's scores never reached the live watch list (Finding 220).
- **What:** after each good pass `FullMarketScan` saves every scoring market's
  reward left to `data/trader/market_scan.json` (beside the ledger; temp file
  then replace; a failed save is counted as `save_failures`, the pass still
  counts). At launch, `refresh_candidate_inputs` loads it if written within the
  last 3 hours; `prepare_candidates` then fills 7/8 of the scope with scanned,
  eligible markets, most reward left first (event diversity does not demote
  them; seeds are the top 128), and the last 1/8 keeps the old event-diverse,
  stratified hint order so new or unscanned programs stay watched. A missing,
  stale, future-dated, oversized or corrupt file falls back to the old order.
  The launch result reports `scan_observed_at` and `scan_markets`.
- **Boundary:** chooses what to watch at launch only; every eligibility check
  (milestone binding, early close, market active, imminent milestone) and
  every live entry check is unchanged. The scope is still fixed between
  restarts; periodic rescoping is option B (not built).

### D-158 — Score every rewarded market; watch the best-scoring ones

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-27; not
  deployed (operator: no restart yet).
- **Decision owner:** Operator: "we should change our scanning market process
  because we dont get all based on your findings here".
- **Why:** ~5,100 markets have a live liquidity program; the book feeds hold at
  most 1,024, chosen by a pool-per-contract hint plus a slow rotating tail, so
  a better market could go unseen for a long time.
- **What:** `FullMarketScan` runs every 30 minutes (first run 2 minutes after
  start) on the low-priority read lane: market details 50 per request
  (`/markets?tickers=`), order books 100 per request (authenticated
  `/markets/orderbooks`, repeated `tickers`), ~100 requests per pass. It scores
  every live, unpaid program with the bot's own `RankingBoard` in a worker
  thread (never on the trading loop) and publishes, per market, the estimated
  reward still earnable before its program ends (total left, not $/hour: the
  first full scan showed hour-long sports and 15-minute crypto programs topping
  $/hour with only $0.14–1.60 left, under the bot's $1 entry minimum).
  Discovery ranks fresh scores ahead of the pool hint and gives half the free
  watch slots to the best-scoring markets; owned markets stay first; scores
  older than 45 minutes fall back to the old order. Each pass's top 200 goes
  to research (`candidates`, key `scan@…`).
- **Book conversion:** REST order books return NO bids at NO prices; the scan
  stores each as a YES ask at 1 − p. (Verified that live quotes already match
  1 − best NO bid, so the book-feed path is correct.)
- **Boundary:** chooses what to watch only; every entry still passes all live
  checks (downside cap, family memory, sweep filter, loss limits).

### D-157 — Report money from the ledger; show both reward estimates

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-27
  (report script only; no bot change, no restart).
- **Decision owner:** Operator: "We need to make sure our reporting is correct
  because we base our business changes from data we get".
- **Rules:** the calibration report opens with a business summary whose money
  rows come only from the ledger (realized P&L after fees from
  `realized_events`, fees actually charged, rewards paid from
  `cash_adjustments`, deposits shown as not income, open positions noted),
  with a coverage line. Estimates are listed separately and labelled: the
  strict tracker (a floor) and the resting-based estimate (leans high).
  Reward truth shows both beside what Kalshi paid per payout day and covers
  every upcoming day so the totals reconcile. Fee reservations are never
  treated as costs. If the ledger cannot be read, the report says so instead
  of guessing.

### D-156 — Record ranker inputs now; build the market ranker when data exists

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-27; not
  deployed (operator: no restart yet).
- **Decision owner:** Operator: "Ok do whats best for kalshi, but i believe we
  dont have much data on kalshi?" after reviewing the Polymarket ranker
  (reward × paid/predicted factor, 3 weeks weighted 50/25/25, minus expected
  fill cost; priority list for slot order only).
- **Now:** (1) the calibration report's reward truth groups programs by the ET
  day they end, matches each morning's unlabelled credit to the previous ET
  day, and prints paid ÷ estimated per day plus the three-week weighted factor
  (reads the reward tracker checkpoint; first day 2026-09-26: 3.2 qualifying
  hours, estimate $0.32, paid $1.22, 3.9×); (2) research gains `candidates`
  (top 100 ranked board rows every 15 min: estimated reward, prices, blockers,
  quoted, cooling, swept) and `sweep_counts` (taker orders per tracked market
  and hour from the D-155 poll: count, contracts, largest, ≥30, ≥150).
- **Later (about 2026-10-18, three weeks of payouts):** build the ranker —
  net value per hour = estimated reward × weighted paid/estimated factor −
  expected fill cost (sweep frequency, family history, price, volume) —
  backtest it on the recorded candidates, then run it in shadow before any
  slot-ordering change. Kalshi credits are unlabelled, so the reward factor is
  overall, not per family, unless per-program payouts are supplied.
- **Boundary:** recording and reporting only; no trading change.

### D-155 — Loss filters: downside cap, family memory, big-sweep filter; lag retry

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-27.
- **Decision owner:** Operator: "Do recommendation" (Findings 215–216 review:
  cap 0.80, 7-day family memory, snapshot-lag retry, pulls unchanged, size 30)
  and "Also do the big sweep filter".
- **Downside cap:** `BotConfig.maximum_entry_downside = 0.80` (approved value,
  also in `config/bot.json`): a program row whose bid is above 0.80 or ask below
  0.20 gets `entry_downside_above_cap` and cannot be selected. Costs ~8% of
  estimated reward (Finding 216); would have blocked KXBROSFT (−$18.36).
- **Family memory:** the D-154 cooldown is keyed by series (ticker before the
  first `-`) and lasts 7 days.
- **Big-sweep filter:** a background poll of Kalshi-wide public trades every
  30 s (60-s windows, split down to 5 s when a window is too large, up to 10
  minutes of catch-up); any market with one taker order of ≥150 contracts
  (either side) gets no new entry for 60 minutes. Fails closed until the first
  complete poll and when the last complete poll is over 5 minutes old. The
  list is saved to `data/trader/sweeps.json` so a restart keeps the last hour.
  Status: `maintenance.sweep_filter`.
- **Snapshot-lag retry:** an own-order renewal that failed only on
  `terminal_but_resting` mismatches with our evidence under 10 s old gets the
  same bounded retry as `order_not_visible` (D-153 data: 1.5–2.1 s lag).
- **Unchanged on purpose:** protective pulls (Finding 216's stay-out effect),
  size 30, exits.
- **Boundary:** the filters can only block entries; they never add orders,
  change size, exits or protection. Existing resting orders are not pulled by
  them.

### D-154 — No re-entry for 24 hours in a market that filled us

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-27.
- **Decision owner:** Operator: "Do recommendation" (stop while flat, build a
  24-hour cooldown, restart), after Finding 214.
- **Rule:** a market with any own fill in the last 24 hours gets no new entry
  (selection and dispatch both use `QuoteMaintenance.entry_allowed`). Exits and
  cancels are unaffected.
- **Source of truth:** the ledger's `fills` table via the read-only writer
  command `recent_fills`, refreshed every 15 s, so it survives restarts and
  covers every fill path. Fails closed: no entries at all until the first
  ledger read, or when the last read is over 5 minutes old. Status:
  `maintenance.fill_cooldown` (markets, hours left, blocks, failures).
- **Also:** the same loop records any ledger fill missing from the D-151
  research `fills` table (`role='ledger'`; mark-outs only for fills under 60 s
  old).
- **Boundary:** can only block entries; never adds orders, changes size,
  exits or protection.

### D-153 — Label owned-order audit mismatches before changing renewal

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-27; not
  deployed (goes with the 2026-09-27 pull-decision restart).
- **Decision owner:** Operator: "Ok build it what u think we need", after the
  recommendation to measure before any renewal retry change.
- **Scope:** when an own-order renewal fails on `order_not_visible` or
  `audit_blocked`, `account_refresh_failed` also logs `missing_count` /
  `mismatch_count`, the youngest and oldest age of our own evidence for those
  orders (`*_age_min_ms` / `*_age_max_ms`, from Kalshi `last_update_time`), and
  fixed `mismatch_kinds` labels (`terminal_but_resting`,
  `remaining_venue_higher`/`lower`, `price`/`side`/`client`/`ticker`/
  `exchange_index_differs`). The audit carries these as `details`, excluded
  from equality, and bounded to 32 orders.
- **Question it answers:** are the ~40/h renewal escalations Kalshi's snapshot
  lagging our own changes (young evidence, `terminal_but_resting`), or are we
  missing updates (old evidence)? Only then decide on a settle-and-retry.
- **Boundary:** logging only; renewal, audit and recovery decisions unchanged.

### D-152 — Measure before retuning protective pulls

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-26; not
  deployed.
- **Decision owner:** Operator: "Ok do recommended make sure we are tracking
  all this so we dont forget" (collect a day, compare, then switch).
- **Scope:** (1) the calibration report replays every protective pull against
  Kalshi's recorded trades (trade-backed vs cancel-driven, and "skipped but
  gone" = a trade-evidence rule's misses), from data already collected, with no
  bot change; (2) `health_hourly.entry_blocked_fraction` names which
  `entry_allowed` term was false; (3) research failures are counted by site
  and exception type in status (`failure_sites`, `last_failure`).
- **Not done yet, on purpose:** no trigger change. A live trade feed would be
  a separate public `trade` subscription, never mixed into the proof-critical
  book readers (they reject any other channel), and would need admission and
  restart checks to ignore it. Built only if the report supports it.
- **Boundary:** diagnostics only; no trading, size, selection or protection
  change.

### D-151 — Research dataset for calibration

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-26; not
  deployed.
- **Decision owner:** Operator: “Do all but review it per number you finish then
  do the same to the next number”.
- **Scope:** `data/trader/research.db`, separate from the financial ledger,
  written by one background thread (never blocks or raises; drops are
  counted; 120-day retention). Records: (1) every acknowledged entry pair with
  its placement context and how each entry order ended; (2) each fill with
  queue/anchor context and 1/5/30-minute mark-outs; (3) hourly per-program
  reward estimates and every external cash credit; (4) every protective pull
  with triggers and a 30/60-second market check; (5) public trades for up to
  64 quoted or held markets once a minute (background read, 30-s overlap); (6)
  10-second health samples summarised hourly with counter changes.
  `scripts/calibration_report.py` turns it into the **calibration report**
  (weekly by default, read-only), whose goal is to improve the bot: evidence
  for tuning entry gates, fill protection and reward estimates.
- **Payout timing (operator-supplied community evidence):** liquidity rewards
  arrive around 2–4 AM ET the day after a program's end; the report matches
  credits in that window to programs that ended.
- **Boundary:** no trading, size, selection or protection change; research
  failures are counted and never affect account or order processing.

### D-150 — Shadow-only fill-avoidance screen on every prepared entry

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-26; not
  deployed.
- **Decision owner:** Operator: “Ok lets do all of it” (architecture review #9,
  shadow mode first).
- **Scope:** each prepared entry pair emits `entry_screen_shadow` with the
  program's remaining projected reward, the worst-case loss of one leg filling,
  Kalshi's 24-hour volume and a verdict: `volume` (24-h volume × 7 > 2,000,
  Finding 210), `reward_risk` (remaining reward < 25% of that loss), `both`,
  `pass` or `unknown`. It never blocks, delays or changes an order; a screen
  error is only counted. `Market.volume_24h` is optional, parsed without
  failing and excluded from equality.
- **Next:** after enough live entries and fills, compare verdicts against
  actual fills and reward before any operator decision to enforce a rule.
- **Boundary:** no trading, size, selection or protection change.

### D-149 — Routine telemetry rotates separately from events

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-26; not
  deployed.
- **Decision owner:** Operator: “Ok lets do all of it” (architecture review #4).
- **Scope:** seven routine INFO events (about 95% of log bytes) go to
  `telemetry.jsonl`; everything else stays in `events.jsonl`. Same rotation
  sizes; one run id and sequence. `events.jsonl` retention in production grows
  from ~3 hours to ~6 days at current volume (0.65 MB/h vs 29 MB/h).
- **Boundary:** no event, field or trading change.

### D-148 — A routine renewal overtaken by a private update hands over to own-order renewal

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-26; not
  deployed.
- **Decision owner:** Operator: “Ok do recommendation” (fix the routine-renewal
  fallback together with D-147 before deploying).
- **Scope:** when a routine account renewal fails only because a private account
  event arrived mid-read (same connection, writer epoch and stream epoch;
  history tail fetched empty and complete; snapshot otherwise matched) and the
  last released proof is still a valid own-order chain anchor, the live
  refresh owner runs the D-134 own-order renewal instead of a full recovery.
  Cash, position, tail, omitted-history, writer-only, slow-read and reconnect
  failures still escalate at once. Status reports `routine_own_fallbacks`.
- **Evidence:** Finding 211: 85 routine renewals in 1 h 50 min fell back to full
  recovery on a concurrent source change (~221 s, ~3% of the time).
- **Boundary:** no risk, size, strategy or protection threshold change.

### D-147 — Renew the account proof after a protective-cancel drain

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-26; not
  deployed.
- **Decision owner:** Operator: “Ok finish and restart then do the other issue”
  (the recommended post-drain efficiency fix).
- **Scope:** after protective withdrawals drain, when the entry path is not
  paused (no stop drain, no safety pause) and the last released account proof
  is still a valid own-order chain anchor (nothing economic since), the live
  refresh owner runs the D-134 own-order renewal instead of a full recovery.
  Any fill, position, cash or audit change escalates to the full pass as
  before. Status reports `post_drain_renewals`.
- **Evidence:** Finding 211: 208 of 319 full recoveries in 1 h 50 min followed a
  drain (median 2.3 s each); full recoveries covered ~12% of the time.
- **Boundary:** no risk, size, strategy or protection threshold change.

### D-146 — A send-edge refusal is proven unsent; name audit blockers in logs

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-26; not
  deployed.
- **Decision owner:** Operator: “Fix everything that is an issue, check logs and
  fix it”.
- **Scope:**
  - When the write-budget check at the send edge (quota refresh, 429 pause,
    expiry) or dispatcher stop refuses a command after SENDING but before the
    transport call, the command is aborted as NOT_SENT instead of UNKNOWN. The
    dispatcher applies its existing pre-send quota policy: temporary reasons
    wait and re-evaluate; clock faults and stopped quota stay fatal. This
    supersedes the earlier conservative rule that any send-edge exception is
    UNKNOWN; transport exceptions remain UNKNOWN. The send edge also repeats
    the pre-send quota checks synchronously (refresh in progress, or a refresh
    completed since the permit: `write_quota_replaced`), so both refresh races
    become temporary refusals instead of permit errors.
  - A failed own-order renewal with outcome `audit_blocked` logs the exact
    audit blockers (bounded vocabulary).
- **Evidence:** Finding 211 (10:38 UTC runtime crash and ~11 min without
  trading from one quota-refresh race).
- **Boundary:** no risk, size, strategy or protection change.

### D-145 — Fill protection: continuous queue tracking, new triggers, order groups

- **Status:** ACCEPTED, implemented and verified offline, 2026-09-26; not
  deployed.
- **Decision owner:** Operator approved the design in
  `docs/DESIGN_FILL_PROTECTION.md` (“Approve as designed”), then “Lets just
  improve the cancel logic”, “Ok do it”; group limit 31: “Do recommended”.
- **Scope:**
  - A dedicated queue reader (every 2 s, sooner for unanchored orders such as
    a just-acknowledged entry) anchors every resting entry. Between readings
    the estimate is live size at better prices plus the at-price reading less
    every removal by others at our price since the read (per book delta; joins
    never net it; own-order deltas excluded; refresh snapshots in the same
    proven sequence keep the tally). The anchor never expires by age.
  - Withdraw a pair on time-to-fill (existing), fewer than one entry's
    contracts ahead (new), or no valid anchor for more than 10 s (new). No new
    entry is placed while the reader has not succeeded within 10 s.
  - Every entry joins its shard's Kalshi order group; a shard without a known
    active group places no entries (fail closed); creation retries 30 s, 1, 2,
    5 min. Exits and reducers never join a group. A trigger blocks the shard,
    requests a full recovery, and the group resets only after a full recovery
    since the trigger, every position has a non-blocked exit plan, entries are
    otherwise allowed and 60 s have passed. A new private stream abandons old
    groups and creates fresh ones.
- **Group limit (accepted):** the design said 30 (one entry). Implemented as
  one entry plus one contract (31): this week's 16 fills were all single,
  isolated sweeps, so a limit of 30 would have cancelled every other entry on
  the shard after each of them with no benefit; 31 never triggers on one fill
  and still stops a second fill within Kalshi's 15-second window, including
  while the bot is offline. One constant (`GROUP_LIMIT_EXTRA`).
- **Evidence limit:** all 16 entry fills this week were one-shot sweeps with no
  prior trade in 15 of 16; no cancel logic can prevent those (Finding 210).
- **Boundary:** no size, order-count or market-selection change.

### D-144 — 24/7 resilience: order lease, Kalshi status, supervisor self-heal, auto-start

- **Status:** ACCEPTED, implemented and verified, 2026-09-26; not deployed.
- **Decision owner:** Operator: “it should survive kalshi maintenance and pause
  trading and once its save it should continue trading, i want this to run
  24/7”, then “Ok fix all the pending works”.
- **Scope:**
  - Entry orders expire at most 20 minutes after placement (Kalshi
    `expiration_time`), bounding unmanaged exposure through a power or network
    loss; ordinary refill re-enters. Exits are unchanged.
  - `GET /exchange/status` every 30 s: while Kalshi is not active no new entry
    is placed (Kalshi cancels entries itself via `cancel_order_on_pause`; no
    cancels are sent); on resume a full recovery precedes trading. A failed
    status read changes nothing.
  - Supervisor: an exhausted restart budget (crashes, transient failures,
    failed spawns) becomes a 15-minute cooldown with a fresh budget instead of
    `attention_required`; a supervisor-initiated startup-timeout or stall stop
    that exits cleanly restarts. Recovery-only proof still precedes trading
    after an unexpected death.
  - `supervised_live boot` + a logon scheduled task restart the bot after a
    reboot only if it was running (never after a manual stop or attention).
- **Still requires the operator:** manual stops, shutdown timeouts, integrity
  or unknown failures, unresolved work or failed cleanup, startup refusal.
- **Boundary:** Installing the scheduled task changes a Windows setting and is
  run by the operator. No risk, size or strategy change.

### D-143 — UNKNOWN creates: local refusals are unsent; stale ones resolve by absence

- **Status:** ACCEPTED, implemented and verified, 2026-09-26; not deployed.
- **Decision owner:** Operator chose “Auto after 10 min (Recommended)” after the
  first 30-contract pair was refused by a hard-coded size gate and recorded
  UNKNOWN, blocking recovery.
- **Scope:** (1) Remaining entry-size checks (live session gate, reprice
  completeness) follow the active approved size. (2) A stateless local
  transport gate runs before submission; a refusal aborts the prepared
  commands as NOT_SENT. (3) Recovery resolves an UNKNOWN create at least ten
  minutes old: bound normally if Kalshi's complete live order list (all
  statuses) shows it; recorded REJECTED (`absent`, evidence digest) only when
  that complete list and the archive both lack it and no fill is pending in
  the market. Incomplete listings never prove absence.
- **Supersedes in part:** the “absence proves nothing” rule, for this narrow
  aged, complete-enumeration case only.

### D-142 — 30 contracts, $780 capital, run on the approved config file

- **Status:** ACCEPTED, implemented and verified, 2026-09-26; not deployed.
- **Decision owner:** Operator added $300 (verified cash $786.85) and chose
  “30 contracts” for 50 orders after the collateral/exposure comparison.
- **Scope:** Approved money set (780, 30, 25): portfolio cap 30 × (16+10) =
  $780, market cap $270, $25 six-hour loss stop unchanged. The live bot now
  activates `config/bot.json`; built-in defaults remain the original approved
  reference profile (500, 10, 25) used by offline fixtures. Reference quotes
  and the entry-size check follow the active size.
- **Boundary:** ~81% of cash as collateral at 50 orders; per-sweep loss ~3× the
  10-contract size; loss-ratchet steps reach sooner. Size changes need a new
  approved set.

### D-141 — Deposits, withdrawals and reward credits never stop trading

- **Status:** ACCEPTED, implemented and verified, 2026-09-26; not deployed.
- **Decision owner:** Operator: “Make sure the bot dont crash on reward payments
  deposits and withdrawals”, “the orders should have cancelled”, “survive
  those errors and recover itself once it knows it safe to trade again”.
- **Scope:** Applied post-baseline deposits/withdrawals adjust expected cash by
  their exact record; pending ones widen the bound without double counting;
  surplus cash from an otherwise fully consistent account is journaled as an
  unattributed credit (reward payouts have no API record). Approved baseline
  activity must still match exactly; missing cash, new transfers and every
  other inconsistency still block. Adjustments are journaled and reproduced by
  the cold cash audit. When recovery cannot prove the account, a safety pause
  drains owned entries and recovery retries at 30 s, 1, 2, then every 5 min.
- **Boundary:** Kalshi's account-wide cancel-all is not used automatically (it
  also cancels exits, manual orders and new orders for a minute).
### D-139 — Unattended 2-hour status scheduler with restart and crash-fix authority

- **Status:** ACCEPTED, 2026-09-26.
- **Decision owner:** In the Polymarket liquidity-bot session, the operator
  created a 2-hour Claude status check. The operator's words:
  - "i want you to check bot status and check the logs, and write findings on md file … if bot is not trading or crashed i want you to fix it and restart";
  - "Count down should start on latest chat";
  - "When theres issue like fixing something just fix it so you can run the bot during that status check";
  - then "Can you add the same rules to kalshi".
- **Scope:** A Claude scheduled task, "Kalshi bot status scheduler", runs 2 hours after the operator's latest Kalshi chat or its own last check. It:
  - reads local status and logs;
  - records findings in `C:\Users\rynna\Bots\kalshi bot status 2 hour check.md`.

  If the bot crashed, stopped trading or is stuck, it may do an ordinary restart: `scripts\Stop-LiquidityBot.ps1` drain, then `scripts\Start-LiquidityBot.ps1 -Live`. This is a standing restart authorization for this purpose, under D-112's process scope.

  It may also fix operational problems and code bugs that prevent running. Each code fix must:
  - carry a regression test;
  - pass the affected tests, `Test-Bot.ps1 -Fast` and the complete `Test-Bot.ps1` (`-NativeSupervisor` when supervisor/IPC code changed);
  - be recorded in BUGFIXES/STATUS/NEXT, committed and pushed under D-065 before the restart.
- **Boundary:**
  - Only restore existing behavior. Never change strategy, risk limits or holds, size, market selection, pricing, exits or timing.
  - Never use `-Initialize` or Command 1 (`-Flatten`).
  - Never force-kill or use D-112 exact-child termination.
  - Never edit the ledger, attribute cash or clear accounting, ownership or loss blockers. These stay operator decisions.
  - Never place, cancel or modify orders.
  - Never restart a manual operator stop, a loss hold, or a state whose blocker is financial or ownership-related.
  - Never restart over uncommitted tracked changes, or when the checkout's `production_build_fingerprint()` differs from the last armed `build_fingerprint` for any reason other than its own reviewed fix.
  - At most one restart per 6 hours. Any failed or uncertain gate leaves the bot stopped and notifies the operator.

- **Amendment (2026-09-26, operator):**
  - The operator's words: "the point of this is to fix an issue unattended", and "if you think the fix is critical then you should fix it, but if bot is running and this is not urgent then no need to restart."
  - Critical problems (crashed, stuck, cannot trade): the scheduler fixes, tests, ships and deploys unattended through fixed scripts, with automatic rollback.
  - Clarified by the operator: "what I want you to fix is something that crashes the bot and stopped it from trading, so you fix it back so it doesn't lose resting time."
  - Non-urgent problems while the bot is running and trading are reported with a proposed fix; no unattended change to `src/kalshi_bot`.
  - The operator's words: "other simple fix that dont require bot restart then just fix it with no restart".
  - Accordingly, bugs only in `scripts/*.py` helper/report tools, which the live bot does not load, may be fixed, tested and committed unattended without a restart.
  - Protected strategy/risk/selection/quoting/exit files are never edited unattended.
  - Every D-139 boundary above still applies.

### D-138 — Raise the resting entry-order cap to 50

- **Status:** ACCEPTED, implemented and verified, 2026-09-26; not deployed.
- **Decision owner:** Operator: “Ok add that to fix increase to 50”, after
  the order-count vs contract-size comparison.
- **Scope:** `risk.MAX_RESTING_ENTRIES` = 50 is the single source; config must
  equal it. The six-hour loss ratchet keeps its $5 steps and $25 stop at the
  same fractions of the cap: 50, 41, 33, 25, 16, 0. Discovery/selection
  visibility limits follow the cap.
- **Boundary:** An existing risk window keeps its stored cap (30) until the
  next six-hour window; the ratchet never widens within a window.

### D-137 — Reward scorecard: unknown-time reasons and size what-if

- **Status:** ACCEPTED, implemented and verified, 2026-09-26; not deployed.
- **Decision owner:** Operator: “Ok build it”, for measuring rewards without
  waiting for Kalshi payouts.
- **Scope:** Process-local reward-tracker session status: uncredited time by
  fixed reason, and the same live books scored with own quantities ×2 and ×3.
  Never checkpointed; estimate only; no trading effect.

### D-136 — Startup allowance and own-order renewal fallback reasons

- **Status:** ACCEPTED, implemented and verified, 2026-09-26; not deployed.
- **Decision owner:** Operator: “Ok do recommendation”, accepting the
  post-deployment recommendations to raise the startup allowance and to log and
  retry the not-yet-listed own-order case.
- **Scope:** Finding 207. Supervisor startup timeout 60 → 180 s; the separate
  work-deadline cap stays 60 s. Own-order renewal records a fixed failure reason
  and retries only the not-yet-listed case (≤3), else full recovery.
- **Boundary:** No other supervision, risk or recovery rule changes. Deploy
  with the next operator-authorized restart.

### D-135 — Adaptive re-entry lockout after protective withdrawals

- **Status:** ACCEPTED, implemented and verified, 2026-09-26; not deployed.
- **Decision owner:** Operator: “Cant we fix 3 first? Before restart?”, then
  chose “Adaptive 60s (Recommended)” over fixed 60 s or keeping 5 minutes,
  after Finding 206's trade-history evidence.
- **Scope:** Re-entry lockout after a fill-risk withdrawal starts at 60 s and
  doubles per repeat in the same market within an hour, capped at the former
  300 s; an hour without withdrawals resets it.
- **Boundary:** The withdrawal trigger, cancel budget, dwell, ranking and all
  entry/risk gates are unchanged. No trade-feed dependency.
- **Later operation:** The operator invoked `Command 1` (“Ok command 1”) after
  asking about contract size; D-133–D-135 were deployed together at 10
  contracts (size unchanged). The bot held no position, so nothing was
  closed. STATUS owns deployment evidence.

### D-134 — Implement all recovery-efficiency recommendations

- **Status:** ACCEPTED, 2026-09-26; items 1–5 implemented and verified
  (Findings 204–205); item 6 (deployment) pending operator confirmation.
- **Decision owner:** Operator: “Lets do all recommendations”, after the D-133
  report ranked: (1) accept the bot's own acknowledged orders in routine
  renewal instead of full recovery (relaxes D-113), (2) cheaper order scans,
  (3) concurrent first snapshot/history, (4) stop re-proving history from the
  opening boundary (relaxes the D-035/D-068 receipt provenance rule),
  (5) exit-plan refresh cost, (6) deploy together.
- **Scope:** Items 1 and 4 are explicitly authorized design changes; they
  must still fail closed on any fill, reconnect, stream gap, unexplained
  snapshot difference or uncertainty, and keep fresh cash/settlement proof.
- **Boundary:** Deployment (item 6) is a live restart and is confirmed with
  the operator at that time. No other risk, ranking or limit change.
- **Supersedes in part:** D-113's "source changes require ordinary recovery"
  no longer applies to the bot's own acknowledged, fully settled orders; and
  D-035/D-068 receipt provenance now accepts revisions since the last
  economic event (history floor) instead of only the current revision.

### D-133 — Re-audit an unchanged first snapshot in full recovery

- **Status:** ACCEPTED, implemented and verified, 2026-09-26; not deployed.
- **Decision owner:** Operator: “Lets do it on priority order”, taking pending
  item 1 (time spent in full recovery after accepted orders) first.
- **Scope:** Finding 203. Full recovery re-audits its own first snapshot
  instead of reading the venue a second time when nothing but local history
  and settlement work ran since it; the mandatory tail snapshot must match it.
  Adds per-phase recovery timing to status.
- **Boundary:** No longer freshness window, no D-113 change: accepted orders
  and other source changes still require ordinary full recovery. Relaxing that
  is a separate operator decision. No restart or live action.

### D-132 — Final pre-restart review and live-log check

- **Status:** ACCEPTED, 2026-09-25.
- **Decision owner:** Operator: “do 1 last review of all things we fix the
  address any issue that you encounter then check the running bot logs to see
  if you encounter any issue that is not working then fix it then we can
  restart” (after interrupting a “Command 1” request).
- **Scope:** Review every D-129–D-131 change, repair defects found, analyse
  the running generation-170 logs read-only, repair defects they reveal, verify
  and publish. The restart itself follows the operator's confirmation.
- **Boundary:** No live action, restart or order mutation during this work.
- **Later operation:** After the review, the operator invoked `Command 1`,
  authorizing the supported drain to verified flat, integrity-checked ledger
  backup, fast-forward of the canonical checkout to the published D-129–D-132
  release and normal restart. Generation 170 held no position, so no market
  close was needed; STATUS owns deployment evidence.

### D-131 — Fix remaining issues 2–9 before deployment

- **Status:** ACCEPTED, 2026-09-25.
- **Decision owner:** Operator: “Ok fix all 2-9”, “Ok do 2-6 then”, then
  “Do 2-6 then review it after, then start working on 7-9 then review it”.
  The operator declined a clarifying question on 7–9, so the recommended
  conservative options apply: at most 4 concurrent risk-withdrawal cycles;
  repeat withdrawals are instrumented, not re-tuned, until post-deploy data;
  finish the explicit-only Command 1 cancel/flatten/restart path.
- **Scope:** (2) bounded full-recovery history cost, (3) recovery-fill
  evidence ceiling, (4) entry prepare/abort churn, (5) unbounded episode and
  fee-bound rows, (6) finish the line-by-line review of remaining modules.
- **Boundary:** Each group is reviewed before the next. Moving the history proof
  start forward would change D-035's receipt-provenance rule; that remains an
  operator decision — this work adds measurement, early warning and cost
  reductions within existing rules. No live action, deployment or restart.

### D-130 — Fix remaining engineering queue before deployment

- **Status:** ACCEPTED, 2026-09-25.
- **Decision owner:** Operator: “We will deploy later because i want to fix all
  before we restart,” after the pending-work summary.
- **Scope:** Implement, verify and publish the open engineering items before
  any restart: the recovery/protective-cancel race (Finding 195 P1), refill
  logging omissions and stage attribution, the lost entry retry, reward/
  repricing coverage visibility, busy-shard evaluation starvation, startup
  public 429s/metadata log volume, and the unfinished line-by-line review of
  the remaining modules (fixing defects it finds).
- **Boundary:** D-129 and these fixes deploy together later under a separate
  explicit restart/Command 1. Concurrent risk withdrawals and ranking/threshold
  changes remain undecided operator choices. No live action or restart.

### D-129 — Repair Finding 196 in priority order

- **Status:** ACCEPTED source repair, 2026-09-25.
- **Decision owner:** Operator: “Fix all based on priority,” after Finding 196.
- **Scope:** (P0) Archive exact command evidence of retired, zero-fill,
  terminal entry episodes so ACK/rejected/unknown rows stop exhausting the
  4,096 mutation/intent/order bounds; start archival before the boundary;
  roll the exact-archive table into a hash-committed chain instead of
  stopping at 128. (P1) Measure the fill-risk cancel budget from the latched
  withdrawal decision, not the first warning; keep warning-to-ACK as a
  diagnostic. (P2) Prune terminal, fully reconciled receipts from the
  in-memory account order projection. (P3) Route the single-create
  send-edge lease check through the proven-unsent abort path.
- **Boundary:** Any episode with fills, positions, pending fills, held
  credits, active intents/authorizations, or a nonterminal/unfilled-proof
  order stays hot. No change to risk limits, ranking, thresholds, concurrency
  of withdrawals or retry policy. No live action, deployment or restart is
  authorized by this decision; publish under D-065.

### D-128 — Retain interrupted protective-cancel scheduling

- **Status:** ACCEPTED source repair, 2026-09-25.
- **Decision owner:** Operator: “You need to fix issues you encounter,” during
  the deeper investigation of cancellation delays.
- **Scope:** Repair the reproduced lost cancellation wake and premature
  post-drain recovery; preserve deferred threat reevaluation after dispatch.
  Add bounded retry visibility and synthetic race regressions, review, verify
  and publish under D-065.
- **Boundary:** No live action, deployment or restart. Keep exact ownership,
  single-writer/quota fences, reconciliation, queue expiry and strategy unchanged.
  Missing observations are unknown, not permission to cancel or credit rewards.
- **Later operation:** The operator separately invoked `Command 1`, authorizing
  the established flat drain and restart. STATUS owns deployment/live evidence.

### D-127 — Preserve order-scoped fill-risk observation through report renewal

- **Status:** ACCEPTED source repair, 2026-09-25.
- **Decision owner:** Operator: “Ok add the fix,” after Finding 190's corrected
  diagnosis and recommendation to repair detection before changing ranking.
- **Scope:** Reuse existing queue reads with their original expiry, current
  owned-order evidence and fresh WebSocket books for cancellation-only risk
  observation during account/reward refresh gaps. Add bounded diagnostic
  evidence, reproduce source-change/fill/reconnect races, review, verify and
  publish the isolated release under D-065.
- **Boundary:** No ranking, depth threshold, reward, price, risk-limit or queue
  lifetime changes. Keep the sole writer and terminal/fill reconciliation.
  No deployment, live account action or restart in this source task.
- **Follow-up deployment authority:** After release verification and publication,
  the operator separately instructed “Restart.” Under D-112 this authorized the
  supported exact-owner drain, deployment of `221a85a` and replacement launch;
  it did not expand D-127's strategy, limits or evidence lifetime.

### D-126 — Recovery renewal repair and useful bounded diagnostics

- **Status:** ACCEPTED source-only work, 2026-09-25.
- **Decision owner:** Operator asks for proper logging around problem areas,
  to fix the reported issues, and explicitly says not to restart the bot.
- **Scope:** Repair reproduced full-cap account-renewal churn and temporary
  reward-quota handling; add readable recovery stages/causes, sampled dispatch
  and reward diagnostics, and a bounded periodic health summary. Verify, review,
  commit and push under D-065 from an isolated checkout.
- **Boundary:** No running-package update, bot restart, order/account action,
  new poller, freshness relaxation or strategy/risk change. Unknown reward
  periods and actual payouts remain separate from estimated accrual.
- **Follow-up deployment authority:** After release verification and publication,
  the operator separately invoked `Command 1`. That authorizes only the existing
  supported drain, verified deployment and restart; it does not expand D-126's
  strategy, risk, freshness or reward-accounting scope.

### D-125 — Archive proven-unsent command evidence at the entry boundary

- **Status:** ACCEPTED repair and Command 1 deployment, 2026-09-25.
- **Decision owner:** Operator requested investigation and repair after the bot
  repeatedly stopped below 30 orders, then invoked “Command 1.”
- **Scope:** Preserve exact compressed evidence for creates durably proved
  `NOT_SENT` in retired episodes, reclaim only those hot command rows, verify
  the stopped production ledger through a disposable copy, publish, deploy and
  restart through the supported supervisor.
- **Boundary:** Keep the 4,096 ordinary-entry, 8,192 total-mutation and 4,096
  intent/order limits. Never archive ACK, rejected, unknown, active-episode,
  order, fill, P&L, position, risk or accounting evidence. No strategy, size,
  capital, stop-loss, reward filter or venue API contract changes.

### D-124 — Repair replacement-order proof churn

- **Status:** ACCEPTED, 2026-09-25.
- **Decision owner:** Operator: “Ok lets look into that and fix it,” after the
  read-only audit found replacement candidates but excessive unsent attempts.
- **Scope:** Reproduce avoidable selection-to-send invalidations, repair the
  existing handoff, add discriminating diagnostics and verify active-book refill
  in isolation. Publish reviewed, passing changes under D-065.
- **Boundary:** Preserve fresh proofs, protective cancellations, reward ranking,
  quantity/capital/loss limits and the 30-entry cap. No live source update,
  restart, account modification or new worker is authorized by this assignment.

### D-123 — Repair stopped recovery and restore the existing bot

- **Status:** ACCEPTED repair assignment, 2026-09-25.
- **Decision owner:** Operator: “Check bot it stopped and fix it”, following
  standing directions to repair restart problems and restore operation.
- **Scope:** Diagnose the stopped run, fix confirmed recovery/progress and
  restart-handoff defects, verify in isolation, publish and restore the same bot.
  Count verified cleanup plus its normal-child handoff as one restart attempt;
  retain bounded failure budgets and all manual-stop/integrity restrictions.
- **Boundary:** No strategy, risk, freshness, selection or account-history
  changes. No second bot or broad process termination. Report unexplained
  process death as unknown, not as a diagnosed exception.

### D-122 — Audit live withdrawal and repair quota-refresh dispatch failure

- **Status:** ACCEPTED, 2026-09-24.
- **Decision owner:** Operator requests current-run log verification, especially
  cancellation to avoid fills, and fixes for observed defects. After the crash
  left orders resting, explicitly authorizes: “Yes—cancel all resting orders;
  keep bot stopped.”
- **Scope:** Cancel and independently verify the stopped account, preserve the
  ledger, reproduce the live quota-refresh/unsent-preparation race, and repair
  only confirmed defects with focused and full offline verification.
- **Follow-up:** “Make sure we all deploy all fixes we did earlier” authorizes
  deployment of the cumulative verified release, including D-121 and D-122,
  after publication and release checks. Keep the bot stopped; this is not a
  trading restart or permission to include unfinished/unverified work.
- **Boundary:** No trading restart, no new entries/liquidation,
  no risk or selection changes. Retry only a reevaluation key after durable
  NOT_SENT proof; ambiguous/SENDING commands keep existing recovery behavior.

### D-121 — Repair startup recovery and slow risk-pair refill

- **Status:** ACCEPTED, 2026-09-24.
- **Decision owner:** Operator: “Ok lets look into that then fix it,” following
  the startup timeline and recommendation to address repeated recovery, slow
  refill, startup 429 retries and the cancellation delay feeding fill-risk.
- **Scope:** Reproduce and repair premature recovery around durable mutations,
  unnecessary recovery between the exact latched risk-pair cancellations and
  bursty public discovery. Verify the whole withdrawal/reconcile/refill path.
- **Boundary:** Keep target/reference/scoring policy, loss/capital/quantity caps,
  current entry proofs, terminal/fill reconciliation and a single writer.
  Isolated source changes, review, tests and publication; no new live restart.

### D-120 — Estimate fill risk, withdraw and select another rewarded market

- **Status:** ACCEPTED, 2026-09-24.
- **Decision owner:** Operator requests calculating fill risk, canceling and
  finding new markets, while acknowledging fills cannot always be avoided;
  follow-up explicitly requires considering program target size/reference price.
- **Scope:** Reuse exact queue-position reads and WebSocket books, estimate
  queue depletion against observed cancellation delays, withdraw threatened
  owned entry pairs without the ordinary repricing dwell, then refill through
  existing ranking. Show target/5 reference depth and actual queue protection
  separately. Risk withdrawal can precede the estimated $1 reward threshold.
- **Implementation defaults:** Two-second cancellation floor, measured
  decision-to-ACK p95, one-second margin plus sampling interval/queue age,
  ten-second trend retention and five-minute market cooldown. These are
  engineering estimates, not calibrated probabilities or venue guarantees.
- **Boundary:** One writer, existing fill reconciliation and position exits,
  30 entries/size ten/capital/reward gates unchanged. Unknown evidence never
  fabricates a safe queue. Isolated build, verification and publication; this
  request does not authorize a live restart or deployment.

### D-119 — Investigate and repair the complete refill pipeline

- **Status:** ACCEPTED, 2026-09-24.
- **Decision owner:** Operator requests the broader investigation and fix,
  rather than another isolated patch for the recurring low-order-count issue.
- **Scope:** Trace ranking, shared book processing, account renewal, dispatch
  and recovery together; reproduce confirmed bottlenecks and fix their causes.
  Verify sustained refill under busy 1,024-market synthetic load, real source
  invalidations, renewal, priority/cap behavior and recovery. Add bounded
  diagnostic attribution where current aggregate blockers hide the cause.
- **Boundary:** No strategy, freshness, capital, position or reward-threshold
  changes; no ignored sequence gaps, extra writer or ambiguous-send retries.
  Isolated implementation/review and publication only, no live restart.

### D-118 — Recover unsent quota expiry and remove redundant metadata churn

- **Status:** ACCEPTED, 2026-09-24.
- **Decision owner:** Operator: “Ok fix it,” following the two offline
  reproductions and live refill/shutdown investigation.
- **Scope:** Preserve still-valid metadata during advisory revalidation, retain
  identical source-bound results, and keep dispatch alive after verified-unsent
  temporary quota expiry. Test overlapping refresh/preparation, recovery and
  continued dispatch, not merely absence of an unsafe send.
- **Added scope:** Operator: “Also add to the fix why open position not
  closing.” Trace the actual position/exit evidence and fix confirmed defects;
  this does not authorize forced liquidation or a different exit policy.
- **Boundary:** No widened freshness windows, changed risk/reward policy,
  retry of ambiguous sends, clock/integrity bypass, extra writer or restart.
  Publish verified source separately from the currently running package.
- **Later operation:** Operator “Command 1” explicitly authorizes the supported
  cancel/flatten/restart and deployment of verified D-118 release `350e073`.
  Operational results belong in STATUS; unfinished emergency-command code is
  not included merely because the command was invoked.

### D-117 — Market-local repricing admission

- **Status:** ACCEPTED, 2026-09-24.
- **Decision owner:** Operator: “Ok can we do that then,” accepting isolation
  of a stalled repricing market instead of blocking all shards' new entries.
- **Scope:** Restrict same-program replacement only on the maintenance ticker.
  Other qualified markets may use available slots under ordinary ranking and
  the shared cap; a maintenance cycle does not reserve the account's free slots.
- **Boundary:** Preserve one writer, one maintenance cycle, exact terminal/fill
  reconciliation, fresh dispatch proofs, safety priority and existing risk limits.
  No new shards, parallel writers, price-policy changes or live restart authorized.
  D-098's global new-entry waiting rule is superseded only by this isolation.

### D-116 — Explicit command 1 flatten/restart and restart-friction repair

- **Status:** ACCEPTED, 2026-09-24. Implementation completed under D-131
  (Finding 201); not deployed.
- **Decision owner:** Operator confirmed the manual close and requested restart,
  fixes to wasted restart time, and “command 1” to cancel orders and flatten
  positions instead of waiting for ordinary passive exits.
- **Scope:** Record the actual multi-fill manual close, then restart. Implement
  an explicit emergency cancel/flatten/restart command for this bot's primary
  account scope, using the sole runtime owner and existing reducing IOC path.
  The command accepts execution gains/losses and fees, not guaranteed prices.
- **Boundary:** Ordinary restart/stop does not implicitly liquidate. No other
  account, foreign ownership, risk increase, stale-price execution or concurrent
  writer. Reconcile terminal/fill evidence and verify flat before normal restart.
  Missing liquidity, uncertainty or a bounded timeout must report a concrete
  blocker rather than loop forever or label a process start as success.

### D-115 — Close the remaining position immediately, then restart

- **Status:** ACCEPTED, 2026-09-24.
- **Decision owner:** Operator: “Close this position now, then restart,” accepting
  execution at the available market price and resulting trading gain/loss/fees.
- **Scope:** Exactly the remaining 10 NO contracts in `KXTOKENUSE-26SEP28-T138`;
  reconcile/cancel its passive reducer, close only remaining inventory through
  the existing reduce-only IOC and accounting path, verify flat, then restart.
- **Boundary:** One-time immediate flatten deadline, not a permanent exit-policy
  change. Preserve single ownership, fresh book/account proof and exact remaining
  quantity. No new position, larger size, unrelated cancellation or ledger edit.
- **Follow-up:** Operator: “I can close it.” Automated close is paused to avoid
  competing execution. The exact timed-out generation 141 child was terminated
  under D-112; no one-off close mutation was sent. Await manual-close confirmation
  and fresh reconciliation before restart.

### D-114 — Repair measured cancellation and recovery latency

- **Status:** ACCEPTED, 2026-09-24; verification/deployment state is in STATUS.
- **Decision owner:** Operator: “Why it take so long to cancel? Fix this” and
  “The whole process is really slow it should not be like that.”
- **Scope:** Remove repeated historical-order classification scans, directly
  schedule owned-entry drains, overlap independent final recovery reads, and
  let the stop supervisor consume a fresh flat report before renewing it.
  Finish the already-authorized restart after release verification.
- **Follow-up:** Operator “But why partially cant u fixed it fully” and
  “Continue” directs completion of remaining lifecycle/refill latency repairs.
  Prevent background advisory replacement racing an active entry, while
  preserving live source invalidation and final send checks.
- **Boundary:** Preserve exact cancellation ownership, source freshness,
  accounting/risk checks, single-writer authority and D-112 process scope.
  No broader trading policy, longer proof lease or live ledger migration.

### D-113 — Separate routine freshness from full startup/refill recovery

- **Status:** ACCEPTED, implemented and verified, 2026-09-24; subsequent
  deployment evidence and remaining latency repairs are owned by STATUS.
- **Decision owner:** Operator: “Ok lets do it,” accepting Finding 175's repair.
- **Scope:** Renew account/accounting evidence using a bounded empty-history
  tail after a successful full proof, independently of order occupancy or ranking
  completion. Let advisory market ranking progress during account recovery.
- **Boundary:** No larger freshness windows, invented continuity, changed risk
  or ranking policy. Source/economic changes, nonempty tails and uncertainty
  require ordinary recovery. Advisory observations never authorize dispatch.
  This implementation request does not authorize a live restart.

### D-112 — An explicit restart command covers exact-child timeout recovery

- **Status:** ACCEPTED, 2026-09-24.
- **Decision owner:** The operator directed that future explicit instructions to
  restart this bot require no second termination prompt.
- **Scope:** A `restart` command authorizes the supported stop and start. If the
  supported stop times out, it also authorizes terminating only the exact
  managed child after immediately rechecking PID, generation, production scope,
  and stop-latched/disarmed state.
- **Boundary:** Never kill by process name, terminate unrelated or ambiguously
  identified processes, start a second bot, mutate venue orders ad hoc, edit the
  ledger, or bypass recovery/flat-state checks. If the child exits naturally,
  do not issue the termination.

### D-111 — Repair the false funding hold and restart through exact recovery

- **Status:** ACCEPTED, implemented, published and live on generation 111,
  2026-09-24.
- **Decision owner:** The operator directed the bot to be fixed and restarted,
  then explicitly authorized force termination of only the verified retained
  generation-108 child after the supported stop timed out.
- **Scope:** Accept only null-to-pre-boundary `finalized_ts` enrichment of the
  same approved applied deposit when complete cursor-exhausted funding history
  proves every other field unchanged. Terminate only the exact identified stale
  child, then use normal recovery-only and fresh-child supervisor behavior.
- **Boundary:** No accounting hold is manually deleted. Missing/new/changed cash
  activity, later finalization, incomplete history, risk limits, strategy and
  market-selection policy remain unchanged and fail-closed.
- **Live acceptance:** Recovery-only cleared the false hold and proved flat;
  generation 111 then ranked 1,024/1,024 markets and reached 30 entries across
  15 $2+ priority markets with zero positions and no persistent blocker.

### D-110 — Recover transient outages and rebuild fresh quotes after a crash

- **Status:** ACCEPTED, implemented, published and live on generation 108,
  2026-09-23.
- **Decision owner:** After reviewing Finding 169, the operator directed all
  findings to be fixed and required restart attempts to continue through any
  diagnosed issue until a healthy restart succeeds.
- **Scope:** Persist account/book/lifecycle readers through capped retry rounds;
  retry classified transient account reconciliation after cooldown; report retry
  states truthfully; after unexpected death only, let verified-flat recovery-only
  completion start one fresh normal child that re-ranks and rebuilds through the
  existing dispatcher; roll superseded exact observation archives into a bounded
  cumulative hash commitment before their finite generation fills.
- **Boundary:** ACK alone never resets retries. Invalid data, ambiguity, economic
  or loss holds, uncertain mutations, incomplete cleanup, manual STOP and local
  integrity failures never auto-resume. No stale order is replayed and no risk,
  size, selection, reference-price or reward threshold changes. Exact economic
  rows remain retained; only superseded observation archives become hash-only.
- **Implementation:** [unattended recovery](docs/BUILD_UNATTENDED_RECOVERY.md).
- **Live acceptance:** The supported restart stopped generation 106 flat, then
  generation 108 matched the published production fingerprint, ranked all 1,024
  markets and rebuilt 30 entries across 15 $2+ priority markets with no position,
  retry round, risk/accounting hold or supervisor attention state.

### D-109 — Bound steady full-cap recovery and accounting retention

- **Status:** ACCEPTED, implemented, published and live on generation 106,
  2026-09-23.
- **Decision owner:** Operator directed the measured generation-102 recovery,
  CPU, reward-coverage and accounting-capacity issues to be addressed.
- **Scope:** At an exact full-cap, flat, fully ranked account, refresh the exact
  account snapshot without repeating history/opening-account reconstruction,
  keep full WebSocket ingestion while limiting optional deep evaluation to the
  owned markets, and losslessly archive superseded recovery observations before
  the durable accounting journal reaches its hot limit.
- **Boundary:** Any fill, position, order, cash, account/source revision,
  dispatcher work, vacancy, window change or failed refresh returns to the
  existing full recovery. The optimization grants no trading authority and does
  not change limits, ranking, quote prices, exits, deployment or live orders.
- **Live acceptance:** The authorized restart canceled 30 old entries and proved
  zero orders/positions/exposure before one exact-child forced termination was
  separately authorized for the old build's terminal journal deadlock. Recovery-
  only then archived 8,192 events, cleared the capacity hold through exact
  release and stopped flat. Normal generation 106 ranked 1,024/1,024 markets,
  reached 30 entries/zero positions, and exercised the bounded steady path.

### D-108 — Reconcile the explicit manual close and resume the preserved account

- **Status:** ACCEPTED, implemented, published and deployed, 2026-09-23.
- **Decision owner:** Operator reported the one open position was manually closed,
  directed the required repair, and authorized restart.
- **Scope:** Adopt only the exact audited terminal close fill into the stopped
  ledger, retain its external origin for cold cash validation, reconcile the
  account to flat, then use the normal recovery-only and live startup sequence.
- **Boundary:** This is not general manual-trading support. Ordinary recovery
  still rejects new unbound fills, and no position, limit or strategy changed.

### D-107 — Treat deterministic absent cancel targets as terminal rejection

- **Status:** ACCEPTED, implemented, published and deployed, 2026-09-23.
- **Decision owner:** Operator directed repair of the observed slow/failing
  cancellation path and restart after review.
- **Scope:** A proved deterministic cancel `404` and create `400` now close the
  exact mutation as `REJECTED` instead of crashing recovery and leaving it
  unknown. Ambiguous transport/server failures remain fail-closed.
- **Boundary:** No broader cancel authority, ownership relaxation, force stop,
  market-selection change or risk-limit change is included.

### D-106 — Repair final priority-admission review findings

- **Status:** ACCEPTED, implemented and published; not deployed, 2026-09-23.
- **Decision owner:** Operator: “Fix it,” after the end-to-end review identified
  three concrete D-105 defects.
- **Scope:** Retire remembered priority on fresh definitive ineligibility while
  preserving it for missing/temporarily exhausted proof; continuously refill
  the bounded revalidation window around stalled candidates; and publish
  dispatch-selection evidence only after an ACK or partial venue outcome.
- **Boundary:** No strategy, limits, source concurrency, configuration, runtime,
  deployment, restart, cancel or live-order change is included.

### D-105 — Revalidate remembered $2 candidates before $1 fallback

- **Status:** ACCEPTED, implemented and published; not deployed, 2026-09-23.
- **Decision owner:** Operator: “Ok do it,” after review of the priority-admission
  investigation and recommendation.
- **Scope:** Retain bounded advisory memory of previously current $2 candidates,
  prioritize their metadata refresh in batches up to twice available pair slots,
  and defer $1 fallback until that batch is freshly resolved. Make early $2
  capacity release reachable from the actual runtime loop, continue full
  coverage afterward, and expose bounded selection evidence in status.
- **Boundary:** Advisory memory never authorizes an order. Every pair still needs
  current book, program, metadata, account, risk and dispatch proof. Keep current
  qualifying owners, four book shards, REST concurrency, limits and exit policy
  unchanged. No deployment, restart, cancel or live order action is included.

### D-104 — Prioritize owned metadata and repair clean supervisor shutdown

- **Status:** ACCEPTED, published, deployed and live-observed, 2026-09-23.
- **Decision owner:** Operator directed completion of the four-shard fixes and
  restart after verification, then explicitly accepted repair of the diagnosed
  metadata and shutdown defects.
- **Scope:** Keep current owned/maintenance markets ahead of optional discovery
  in the shared metadata scheduler, use four bounded metadata reads only in
  broad discovery, and permit liveness-only parent pulses during a latched stop
  so verified-flat cleanup can finish. Review, test, publish, then restart with
  the preserved ledger and existing limits.
- **Boundary:** A stop-latched child receives no admission or mutation authority;
  identity/dead-parent checks remain mandatory. Do not change strategy, reward
  thresholds, quantity, capital, loss limits or exit timing.

### D-103 — Repair exits and require priority-safe broad ranking

- **Status:** ACCEPTED implementation; restart not authorized, 2026-09-23.
- **Decision owner:** Operator: “Fix all the work but dont restart yet,” after
  prioritizing the observed exit/recovery incident, repeatable 1,024-market
  source coverage and $2-first admission.
- **Scope:** Use the venue-valid passive-exit payload while retaining exact local
  managed-exit authority; rearm one fresh recovery at a due safety boundary;
  measure two versus four book shards; prepare four shards; and prevent partial
  ranking from admitting $1 fallback before complete coverage or a full current
  $2 slate. Review, test, commit and push.
- **Boundary:** Keep the bot stopped and flat. No account/order mutation,
  deployment, restart, ledger edit, risk/quantity/loss change or incumbent
  reward-chasing replacement. Existing qualifying owners remain retained.

### D-101 — Repair actual-order repricing and final drain reconciliation

- **Status:** ACCEPTED, deployed and live-observed, 2026-09-23.
- **Decision owner:** Operator requested the demonstrated repricing fix and a
  review of retained logs for the next restart, then explicitly clarified:
  "stop the bot and cancel all order."
- **Scope:** Repair reproduced reward-source joins that starve incumbent
  maintenance, verify the two-leg cancellation/replacement path, and repair the
  observed post-drain recovery stall. Review, test, commit and publish.
- **Boundary:** Keep qualifying incumbents, $2-first/$1-fallback entry ranking,
  sizes, risk, exact fill/terminal proof and all freshness limits unchanged.
  The later explicit restart instruction authorized controlled deployment and
  launch. The preserved ledger and unchanged limits were used; no initialization
  or account-wide cancellation was performed during restart.

### D-102 — Safety stop and immediate bounded close after live fill

- **Status:** ACCEPTED operation, completed flat, 2026-09-23.
- **Decision owner:** Operator: “Close position first then lets see where we at
  on the other work.”
- **Scope:** Cancel remaining entries through the supported stop, close only the
  exact 10-contract KXONPOS position through the existing ledger-backed IOC path,
  and verify venue/account flatness before further development.
- **Boundary:** No new entries, ledger reset, account-wide cancel, risk change or
  unrelated process termination. Production remains stopped after verified
  flatness; another restart requires a separate instruction.

### D-100 — Repair live maintenance timing and rejected-reducer churn

- **Status:** ACCEPTED, deployed and live-observed, 2026-09-23.
- **Decision owner:** Operator: “add the fix but do not restart yet,” followed by
  a request to review the change, inspect current live logs and fix unusual
  behavior before restart.
- **Scope:** Preserve verified reference-drift evidence through brief ordinary
  source gaps without counting unknown time; reset on a changed owner/program/
  account generation or a gap over 15 seconds; require a fresh exact lease at
  cancellation send. Wake reward reflection after successful account recovery.
  Treat scalar create HTTP 400 as no-order proof, retain only a bounded error
  code, and durably back off consecutive identical reducers 10/20/40/60 seconds.
  Changed price, quantity or IOC mode may proceed immediately. Suppress empty
  broad-discovery inventory-plan logs while retaining material/final transitions.
  The required log review also authorizes repair of the observed 4,096-receipt
  writer crash: atomically archive the exact old audit rows before retaining a
  fresh hot receipt, never use archived evidence as current account authority,
  and classify overtaken metadata publications/quota deferrals as retry/defer
  states rather than failed market attempts.
- **Boundary:** No risk, quote-size, loss, market-selection or exit-deadline
  change. Unknown writes remain non-retrying. The operator subsequently
  authorized the controlled deployment and restart. The preserved ledger and
  limits were used; no initialization or account-wide cancellation occurred.

### D-099 — Emergency force cancellation, shutdown repair and controlled restart

- **Status:** ACCEPTED operation and implementation, 2026-09-23.
- **Decision owner:** Operator: “Force cancel all order then fix this” and, for
  the combined entry/exit repair, “fix it then restart.”
- **Scope:** Immediately cancel every account order, stop only the verified bot
  processes, repair the slow cancellation and false terminal-timeout mechanisms,
  test/review/publish/deploy, reconfirm a flat account and perform the already
  authorized normal restart.
- **Boundary:** Preserve the ledger, strategy and configured limits. No
  initialization, blind resend, risk expansion or process-wide termination.
  Cancellation speed cannot weaken exact owned-order, mutation, transport,
  identity or recovery proof; restart remains conditional on current flatness
  and normal supervisor admission.

### D-098 — Retain rewarded owners and review the complete order lifecycle

- **Status:** ACCEPTED implementation, 2026-09-23.
- **Decision owner:** Operator accepted incumbent retention, actual-reference
  monitoring, controlled same-market repricing and per-program reward progress,
  then requested the full entry/exit comparison with executable Polymarket code
  and inclusion of relevant fixes in the next restart bundle.
- **Scope:** Keep qualifying markets rather than chasing higher-ranked spares;
  reaching an estimated $1 does not release a market. Reuse the existing tracker,
  source owners, dispatcher and exact terminal/fill reconciliation. New entries
  retain $2-first/$1-fallback and 70% retained-value gates. Inventory handling
  takes priority over reward maintenance. Fix demonstrated lifecycle defects
  without importing Poly's current numeric risk settings or sports-only policy.
- **Boundary:** Build/test/review/publish in an isolated checkout. No live order
  action, deployment or restart is authorized by preparing the next bundle.
  Reward estimates remain advisory, never paid cash or guaranteed payout.

### D-097 — Repair recurring Windows status publication failure

- **Status:** ACCEPTED implementation, 2026-09-23.
- **Decision owner:** Operator: “Fix it.”
- **Scope:** Repair the observed transient Windows atomic-replacement failure,
  add a real contention regression, retain whole-document publication and
  fail-closed permanent-error handling, then verify/review/commit/push.
- **Boundary:** No trading logic, risk/configuration change, ledger reset or live
  restart. A later restart still requires explicit operational authority.

### D-096 — Initial combined-ranking checkpoint

- **Status:** ACCEPTED implementation and subsequent reviewed restart, 2026-09-23.
- **Decision owner:** Operator: “Ok do recommended,” then “Can you also restart
  once you review the fix.”
- **Scope:** Keep both book feeds and missing-field metadata concurrent; delay
  new entries until initial evaluated coverage or a bounded timeout, then rank
  current eligible candidates together with existing $2-first/$1-fallback rules.
  Revalidate prices, sources and limits before each order. Test and review before
  controlled stop/deployment/restart using the existing ledger.
- **Boundary:** No incumbent-upgrade policy, automatic repricing, risk changes,
  second bot or force-kill. Timeout never makes missing/stale evidence eligible.
  Inventory, cancellation and recovery continue independently of the checkpoint.

### D-095 — Controlled live restart after D-094 repair

- **Status:** ACCEPTED operation, 2026-09-23 Eastern.
- **Decision owner:** Operator: “Restart.”
- **Scope:** Start the existing normal production supervisor with the preserved
  ledger, reviewed inputs, strategy, risk limits and capital limits. Observe the
  launch through current process, account, source, admission and order evidence.
- **Boundary:** No initialization, configuration/risk changes, force-kill or
  second process. Existing readiness gates remain authoritative; if they block,
  diagnose rather than bypass them.

### D-094 — Repair host continuity and verify stopped-account recovery

- **Status:** ACCEPTED implementation/verification, 2026-09-23 Eastern.
- **Decision owner:** Operator: “Ok fix that too,” following the remaining
  host-continuity and manual-cancellation reconciliation blockers.
- **Scope:** Independent on-demand Windows supervisor launch, truthful liveness
  inspection, inert process-lifetime tests and GET-only account reconciliation
  evidence. Preserve exact order/fill recovery and all existing restrictions.
- **Boundary:** No live restart or order actions; no persistent service, startup
  task or power changes. Any local evidence import requires stopped-owner leases
  and a consistent backup; never infer canceled orders from absence or reset risk.

### D-093 — Adopt broad reviewed books and shared bulk metadata

- **Status:** ACCEPTED implementation, 2026-09-23 Eastern.
- **Decision owner:** Operator: “Ok lets use that,” following D-092's measured
  recommendation.
- **Scope:** Watch up to the existing 1,024 reviewed candidates on two public
  book shards; share bounded bulk event/market/milestone reads. Preserve current
  validators, complete fee schedules, freshness, generations and quotas. Bound
  ranking-to-entry work independently from public subscription breadth.
- **Boundary:** Supersedes D-091's 128-book rotating scope for normal live
  composition only. Monetary/account capacity, 30 resting entries, reward gates
  and all execution proofs remain unchanged. Test integration and performance;
  no live restart, account calls, order actions or production ledger changes.

### D-092 — Research and measure discovery alternatives before architecture changes

- **Status:** ACCEPTED read-only research/testing, 2026-09-23 Eastern.
- **Decision owner:** Operator: “Ok test it,” followed by research and comparison
  before blindly building an architecture.
- **Scope:** Bounded public-market WebSocket capacity measurements at increasing
  reviewed/rewarded scope, current official API research and comparison of
  broader subscriptions, ticker-assisted discovery and snapshot/metadata options.
- **Boundary:** Diagnostic instruments only. No production configuration, risk,
  order, ledger, restart or architecture change. Existing WS-first policy remains;
  broad REST book polling is not implicitly approved. Present evidence and the
  recommended implementation scope before adopting a production design.

### D-091 — Repair discovery coverage and bounded refill progress

- **Status:** ACCEPTED implementation, 2026-09-22 Eastern.
- **Decision owner:** Operator: “Ok lets do it,” approving the preceding
  market-coverage diagnosis and recommendation.
- **Scope:** Consume exploration progress only for actually subscribed markets,
  retain unadmitted candidates across partial/deferred rotations, and improve
  bounded refill cadence when another pair fits the current risk limit. Add
  composed coverage/selection tests and bounded exclusion diagnostics.
- **Boundary:** Preserve protected ownership, 128 active books, two shards,
  16 additions per rotation, reward/reference/value gates, quota, risk and
  freshness rules. No live restart, venue commands, ledger edits or hosting
  overhaul in this work unit.

### D-090 — Size lifecycle transport for one bounded full-market snapshot

- **Status:** ACCEPTED, DEPLOYED and live-verified, 2026-09-22 Eastern.
- **Decision owner:** Operator: “Also fix this issue before restart,” “Continue
  working,” and “Why it take so long just to cancel the order?” during the
  authorized stop/restart investigation.
- **Scope:** Restore the transport's existing 8,192-event / 16-MiB bounds only
  for the unscoped lifecycle subscription, whose measured initial snapshot was
  about 5,018 rows. Preserve account/scoped-book limits at 256 / 2 MiB.
- **Boundary:** Queueing remains bounded and overflow remains fail-closed. No
  ranking, reward, order, risk or stop-loss rule changes. If one complete live
  snapshot still cannot converge, stop flat and measure high-water before any
  further capacity change.

### D-089 — Correct proven pre-transport cancellation outcomes before restart

- **Status:** ACCEPTED implementation and controlled recovery, 2026-09-22 Eastern.
- **Decision owner:** Operator: “Also fix this issue before restart,” followed by
  “Continue working,” after two cancellations remained blocked by the same
  pre-transport proof-change path.
- **Scope:** When the sole executor has advanced a command to `SENDING` but an
  explicit final proof check fails before transport invocation, atomically record
  `NOT_SENT`/`ABORTED`, release applicable capacity and request fresh recovery.
- **Boundary:** Any exception at or after transport invocation remains UNKNOWN.
  Do not infer safety from a timeout, HTTP error or missing acknowledgement. The
  two historical rows may be corrected only from exact stopped-owner ledger and
  retained diagnostic evidence, with a verified backup. Normal entries still
  require recovery-only verified flatness.

### D-088 — Repair progress-aware graceful drain before restart

- **Status:** ACCEPTED implementation and controlled restart, 2026-09-22 Eastern.
- **Decision owner:** Operator: “Also fix this issue before restart,” after the
  authorized stop exposed recovery exhaustion with resting orders remaining.
- **Scope:** Preserve source revalidation after every safety cancellation, but
  give a new bounded three-failure budget after a source-consistent pass made
  durable forward progress and queued its required fresh reconciliation.
- **Boundary:** Do not weaken ownership/proof checks, batch uncertain cancels,
  retry an UNKNOWN mutation, reset the ledger/risk state or force flatness.
  Resume normal entries only after recovery reaches verified flatness.

### D-087 — Recover the lifecycle stream after bounded retry rounds

- **Status:** ACCEPTED implementation, 2026-09-22 Eastern.
- **Decision owner:** Operator: “Ok check it then fix it,” after the unchanged
  live process reported permanent lifecycle retry exhaustion.
- **Scope:** Keep account/book retry exhaustion unchanged. For the advisory
  lifecycle reader only, revoke source terms after failure, retain three attempts
  per round, then retry on a capped 30/60/120/240/300-second backoff until stop.
  Preserve monotonically increasing stream generations and bounded diagnostics.
- **Boundary:** A retry/ACK never makes stale metadata current, resets no metadata
  retry hold and grants no trading authority. Deployment/restart remains separate.

### D-086 — Repair reward catalog and quiet-book sources

- **Status:** ACCEPTED implementation, 2026-09-22 Eastern.
- **Decision owner:** Operator: “Ok add all the fix,” following the reward API audit.
- **Scope:** Use bounded 1,000-row incentive pages in preparation and runtime;
  refresh quiet subscribed books using documented WebSocket `get_snapshot`,
  with bounded requests, correlation, sequence checks and offline regressions.
- **Boundary:** Preserve reward/risk filters, freshness, retry exhaustion and
  account authority. No new earnings API is invented. No live restart, retry
  reset, order action or wider market capacity is included in this code task.

### D-085 — Reconcile the single pre-transport cancel refusal

- **Status:** ACCEPTED one-time operational correction, 2026-09-22 Eastern.
- **Decision owner:** Operator: “Sure,” approving reclassification of the
  specific cancellation discussed in the preceding session and recovery/restart.
- **Scope:** With the production process stopped and account ownership held,
  preserve a backup and transactional audit of the one cancel attempt recorded
  at 2026-09-22 23:34:25 UTC. Its retained execution diagnostic points to the
  pre-transport `proof_changed_before_submission` branch. Change that attempt
  from UNKNOWN to NOT_SENT and its exact authorization to ABORTED, allowing
  the existing bounded reauthorization path to obtain fresh cancellation proof.
  Reconcile remaining orders through the supervised recovery path, then resume
  the previously authorized normal bot only after verified flat recovery.
- **Boundary:** No general UNKNOWN retry policy, loss/accounting reset, deletion
  of history, size/capital/filter change or manual venue cancellation. Keep
  original rows and evidence in the ignored local audit and ledger audit entry.

### D-084 — Attribute exact personal opening cash and resume initialization

- **Status:** ACCEPTED live-opening correction, 2026-09-22.
- **Decision owner:** Operator previously identified the account as personal,
  said its $500 bank/card funding may be used, explicitly authorized the live
  run, and then instructed “Lets fix it” after the retained funding blocker was
  shown.
- **Scope:** The explicit opening approval may attribute retained, completed,
  pre-boundary personal deposits and completed pre-boundary intra-exchange
  transfers to the exact current flat cash baseline. An interrupted first
  initialization must resume the same immutable checkpoint after a fresh
  matching inspection; it must not delete the ledger, choose a new boundary or
  replay initialization.
- **Boundary:** Pending/returned/failed funding, withdrawals, subaccount
  transfers, post-boundary activity, settlements, changed cash, positions,
  orders and every other economic hold remain blocking. Attribution records
  exact retained event digests and grants no independent order authority.
- **Contract:** [First-live opening recovery](docs/BUILD_FIRST_LIVE_OPENING_RECOVERY.md).

### D-083 — Gate new entries by value retention and projected reward

- **Status:** ACCEPTED implementation, 2026-09-22.
- **Decision owner:** Operator: “Ok lets add those filters,” after reviewing the
  current public rewarded-market measurement.
- **Scope:** A new size-10 two-sided entry must quote both current reference
  prices at full reward weight, retain at least 70% of each side's entry value
  under a full visible-depth immediate exit including the current fee bound, and
  project at least $1 gross reward through the earlier program/entry deadline.
  Candidates projecting at least $2 receive slots before the $1–<$2 fallback;
  the existing ranking remains stable within each tier.
- **Boundary:** These are initial-entry gates, not payout or profit guarantees.
  Existing orders and inventory remain governed by their current management and
  exit rules; this does not add hot repricing, reward-chasing cancellation, a
  fixed market pool, live authority or a bot start.
- **Contract:** [Entry-quality gates](docs/BUILD_ENTRY_QUALITY_GATES.md).

### D-082 — Admit the reviewed scheduled-release timing family

- **Status:** ACCEPTED implementation, 2026-09-22.
- **Decision owner:** Operator: “Ok fix it,” after the executable Polymarket
  comparison and current Kalshi public-data audit found zero eligible candidates.
- **Scope:** Replace the blanket early-close exclusion only for Kalshi's exact
  scheduled-economic-data release condition when the market has an occurrence
  time and exactly one future primary milestone of a reviewed release type.
  Bind the occurrence time into the rules digest and recheck the family and
  timing relation at runtime.
- **Boundary:** Unknown early-close rules, sports, related-only milestones and
  missing/conflicting clocks remain blocked. Existing reward, ranking, capital,
  order, position, loss, fee and launch gates remain unchanged. This decision
  does not authorize a live start or order.
- **Contract:** [Candidate timing adaptation](docs/REVIEW_CANDIDATE_TIMING_POLY.md).

### D-081 — Connect the production runtime to the native supervisor

- **Status:** ACCEPTED implementation scope, 2026-09-22.
- **Decision owner:** Operator: “Ok we need to work on all of this, lets start
  the implementation,” after accepting the ordered supervisor checklist.
- **Scope:** Connect one fixed production child to the existing foreground
  Windows supervisor; route start/stop/status through it; preserve the existing
  financial ledger and runtime gates; use bounded recovery-only child restarts.
- **Recovery rule:** Unexpected child death can restart only with entries paused.
  A recovery child reconciles/cancels/manages existing inventory to verified
  flat, then the supervisor disarms. Resuming entries requires a later explicit
  operator start. Startup/integrity/local-control failure and exhausted retries
  require attention.
- **Boundary:** This decision does not authorize the first live run, install a
  host watchdog or scheduled task, alter power settings, reset a ledger, weaken
  risk limits, or change trading strategy.
- **Contract:** [Production supervisor recovery](docs/DESIGN_PRODUCTION_SUPERVISOR.md).

### D-080 — Prepare the production-supervisor work checklist

- **Status:** ACCEPTED planning/documentation scope, 2026-09-22.
- **Decision owner:** Operator: “Ok create a to do list for this work lets start
  from that,” following the production supervisor and later host-watchdog discussion.
- **Scope:** Maintain one prioritized checklist in [NEXT.md](docs/history/NEXT_ARCHIVE_2026-09-26.md#production-supervisor-connection--ordered-checklist),
  covering production integration, recovery rules, tests, review/publication,
  live acceptance and the separately staged Windows host watchdog. Reuse S1/S2.
- **Boundary:** Creating the checklist does not implement or accept a new restart
  policy, start trading, install a scheduled task, change power settings or modify
  Polymarket. Existing model continuity and single-session rules remain.

### D-079 — Automatically prepare the best current rewarded-market universe

- **Status:** ACCEPTED implementation, 2026-09-22.
- **Decision owner:** Operator: “We need to fix it that we get the best rewarded
  market,” after confirming the existing one-market input defeated ranking.
- **Scope:** Use public active incentives, complete market rules and exactly one
  future official primary milestone to prepare at most 1,024 candidates; seed at
  most 128 WebSocket books and retain the existing actual-book ranking and
  30-resting-order limit. Keep a rewarded head plus stratified discovery tail.
- **Boundary:** Cheap reward density is exploration, not final selection or a
  profit claim. Runtime rules/milestone/lifecycle checks, T-5 deadline, fee,
  capital, position, loss, ownership and dispatch gates remain. No live start or
  order is authorized. Refresh is blocked with an existing ledger unless saved
  shutdown is verified flat. Automatic preparation excludes early-closing
  markets; their natural-language conditions require a separate explicit review.
- **Contract:** [Automatic candidate preparation](docs/BUILD_AUTOMATIC_CANDIDATES.md).

### D-078 — Connect automatic selection to the original launcher

- **Status:** ACCEPTED implementation, 2026-09-22.
- **Decision owner:** Operator: “Ok lets do it,” accepting discovery → market
  checks → ranking → admission, with unsupported candidates skipped visibly.
- **Scope:** Attach the existing admission owner to the actual composition;
  separate the bounded reviewed candidate universe from active subscriptions,
  preserve timing reviews across rotation, resolve fresh fees/rules through the
  existing metadata service, and test the complete handoff with synthetic wires.
- **Boundary:** No inferred event-risk clock, automatic approval of unknown
  rules, sports-only filter, score-chasing cancellations or risk-limit changes.
  Working orders, inventory and uncertain owners remain protected. No live
  start, private-input change, order or deployment is authorized by this build.
  At D-078 publication local inputs contained one review; D-079 subsequently
  supplies bounded exact preparation. D-078 itself never made unknown markets
  eligible.

### D-077 — Finish the existing bot's minimum operating path

- **Status:** ACCEPTED implementation, 2026-09-22.
- **Decision owner:** Operator: use the bot already built, defer unnecessary
  hardening, then “Ok finish whats necessary.”
- **Scope:** Connect the original WebSocket/ranking/accounting/dispatch/inventory
  owners to an explicit Windows foreground launch; retain the approved size,
  capital, exposure, loss windows and exit policy. Keep basic logs and graceful
  shutdown. No new paper-trading stage, replacement bot, model switch or worker.
- **Supersedes:** D-076's separate REST canary and hold-to-settlement workflow.
  Its run entry point is retired. Historical previews remain local evidence.
- **Boundary:** Implementation and synthetic/read-only verification are not a
  completed live launch. Reviewed current market/fee inputs and a fresh opening
  baseline remain necessary. No automatic deployment/restart or risk expansion.
  The coding assistant must not submit trades or invoke the trading launcher;
  an operator-run live command is separate from software verification.
- **Contract:** [Minimal original runtime](docs/RUN_LIQUIDITY_BOT.md).
- **Account evidence:** On 2026-09-22 the operator confirmed this is a personal
  account opened directly with Kalshi, not a broker/FCM account. This supports
  the direct-member fee profile; it does not authorize a launch by itself.

### D-076 — Prioritize a minimal live profitability canary — SUPERSEDED by D-077

- **Status:** ACCEPTED build/prepare scope, 2026-09-22; submission pending.
- **Decision owner:** Operator: focus on resting orders and gathering live data
  today; defer additional production hardening until profitability is known.
- **Decision:** Build a one-market canary using the existing Kalshi selection
  arithmetic: two post-only 10-contract orders, at most six hours, estimated
  reward at least $1, cancel on first observed fill or planned end, and preserve
  actual fill/fee/settlement/reward evidence.
- **Risk boundary:** One entry batch only; maximum net position is 10 contracts,
  no market taking/repricing/rotation and no autonomous runtime activation.
  Preparation is read-only. The exact live submission still requires explicit
  operator confirmation after a fresh preview.

## Accepted decisions

### D-001 — Measure before building

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator
- **Decision:** Do not build the full Kalshi bot yet. Determine whether the
  Polymarket US strategy can work profitably on Kalshi through measurement.
- **Consequence:** Production package, multi-market execution, deployment, and
  scaling work are paused.
- **Revisit when:** The experiment gates in `EXPERIMENT.md` have enough evidence
  to support a build/no-build recommendation.

### D-002 — AI-maintained repository

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator
- **Decision:** Assume the operator will not write the code. AI agents maintain
  the code, tests, research, and handoff documentation.
- **Consequence:** Every material session must leave `STATUS.md`, `NEXT.md`, and
  the evidence trail usable by a fresh AI session.
- **Revisit when:** The operator changes the maintenance model.

### D-003 — Operator retains consequential decisions

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator
- **Decision:** The operator makes strategy, capital, risk, live-action,
  deployment, and scope decisions. AI agents investigate, recommend, implement
  approved work, and report results.
- **Consequence:** No AI may convert a recommendation into authorization.
- **Revisit when:** Only by explicit operator instruction.

### D-004 — No live mutation in the current phase

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator, preserving the existing project constraint
- **Decision:** Current work is read-only measurement and experiment design.
  Live order placement remains outside scope. A later minimal evidence run must
  receive a separate operator decision, and the operator performs the arming
  action unless this decision is explicitly amended.
- **Consequence:** Keep `kalshi_auth.py` read-only and add no order endpoint yet.
- **Revisit when:** Read-only gates justify a minimal live experiment.

### D-005 — Polymarket repository is a read-only reference

- **Status:** ACCEPTED
- **Date:** 2026-08-17
- **Decision owner:** Operator
- **Decision:** Do not modify `D:\polybot\liquidity-bot`; copy concepts only
  after separating venue-independent safety from venue-specific calibration.

### D-006 — Canonical GitHub repository

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator
- **Decision:** Publish and maintain this project at
  `https://github.com/rynn-arriola/kalshi-bot.git`.
- **Consequence:** This remote carries measurement code, tests, and AI handoff
  documentation. Ignored credentials and captured data remain local only.
- **Revisit when:** The operator names a replacement repository.

### D-007 — Isolated server measurement is allowed

- **Status:** ACCEPTED
- **Date:** 2026-08-26
- **Decision owner:** Operator
- **Decision:** Read-only Kalshi measurement may run on the server that hosts
  the Polymarket bot, but it must be installed in a new standalone Kalshi
  project folder and never inside the Polymarket folder.
- **Consequence:** Use a separate top-level directory, environment, process,
  configuration, data, and logs. Do not import from, write inside, restart, or
  make API calls through the Polymarket project. Read-only Kalshi API calls are
  permitted from that isolated project; authenticated writes and all live order
  actions remain prohibited by D-004. The boundaries in
  `docs/SERVER_MEASUREMENT.md` are mandatory.
- **Revisit when:** Measurement resource use interferes with production, or the
  operator selects a separate server.

### D-008 — Include spread scalping in the measurement

- **Status:** ACCEPTED
- **Date:** 2026-08-27
- **Decision owner:** Operator
- **Decision:** Measure whether two-sided spread capture is profitable on the
  current Kalshi data, both alone and combined with liquidity reward. For the
  pure-scalping result, compare feasible quote-spread widths and identify which
  width, if any, has the best bounded net P&L without crediting any reward.
- **Consequence:** Offline/read-only replay may measure pair completion,
  one-sided inventory, fees, exits, and net. Keep pure scalping and reward
  separate before producing a combined result. Spread widths must use the same
  market universe, evaluation windows, size, queue assumptions, and exit rules;
  report gross pair edge and fill rate separately from net. This does not
  authorize live orders or a new strategy implementation.
- **Revisit when:** A fixed-universe replay provides a decision-grade estimate.

### D-009 — Move read-only measurement to the laptop

- **Status:** ACCEPTED
- **Date:** 2026-08-28
- **Decision owner:** Operator
- **Decision:** The former server was destroyed. Restart the approved read-only
  Kalshi measurement on the operator's laptop, which is reachable from this PC.
  The live Polymarket project remains on this PC.
- **Consequence:** Install and run Kalshi only inside the laptop's separate WSL
  path `/home/polybot/kalshi-bot`, with its own environment, process, data, and
  logs. Do not use or modify the laptop's stale Polymarket copy, and do not
  touch the live Polymarket folder or process on this PC. D-004's no-order and
  no-write boundary remains unchanged.
- **Revisit when:** The operator changes the measurement host or ends the
  capture.

### D-010 — `run parity` operator command

- **Status:** ACCEPTED
- **Date:** 2026-08-28
- **Decision owner:** Operator
- **Decision:** When the operator says `run parity`, reconcile the Kalshi
  project across this PC, the laptop, and GitHub so tracked code and AI
  documentation resolve to one identical commit.
- **Consequence:** First inspect and preserve uncommitted work on both machines;
  never overwrite a divergence silently. Push/fetch only after the tracked state
  is verified, then print the PC, laptop, and GitHub commit IDs. Also verify the
  laptop measurement service and live database health, create an
  integrity-checked SQLite online-backup snapshot, and copy the closed snapshot
  plus matching log to this PC. Runtime databases/logs remain gitignored and
  must never be pushed to GitHub.
- **Revisit when:** The operator changes the parity destinations or data-retention
  policy.

### D-011 — Plan a live liquidity-reward test; do not build yet

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, in the current conversation
- **Decision:** Continue the Reference Price liquidity-reward strategy in
  `Bots/kalshi-bot`. Do not run paper testing. Plan the live approach first;
  do not build the bot yet. Capital ceiling is $500 and each order must be
  fewer than 10 contracts. The assistant's $10 loss-stop suggestion has NOT
  been approved. Entry size, market list, exit policy, duration, and maximum
  loss remain planning decisions before a live run.
- **Consequence:** Documentation/research may continue. No trading code,
  deployment, live orders, or transfers are authorized by this planning task.
  This instruction supersedes recommendations to require a forward paper stage.

### D-012 — Official API reference and credential-use permission

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, in the current conversation
- **Decision:** Collect all public Kalshi API endpoint information into a
  Markdown source reference. The operator also authorizes use of their keys
  when needed. Documentation retrieval is public and does not require keys.
- **Consequence:** Preserve dated sources, exact contracts, and visible gaps;
  keep credentials out of all documentation. Credential access is not a new
  trading, capital-transfer, or bot-building decision. D-011 remains in force.

### D-013 — Research liquidity rewards and every documented reward API

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, in the current conversation
- **Decision:** Research what is needed to understand and benefit from Kalshi
  liquidity rewards, including every reward API.
- **Consequence:** Read-only official-source/API research and documentation
  are in scope. D-011 remains unchanged: no bot build, paper run or live order
  authorization. Research recommendations are not accepted risk settings.

### D-014 — Polymarket-style documentation and permanent architecture rules

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, in the current conversation
- **Decision:** Inspect the Polymarket bot's Markdown setup and use that
  organizational pattern for Kalshi. Architecture must primarily use
  WebSocket; when required information is unavailable through WebSocket,
  REST is the fallback. Build for CPU efficiency and scalability. Preserve
  these as standing rules for future sessions.
- **Consequence:** `AI_OPERATOR.md` is the shared entry point; AGENTS/CLAUDE
  route to it. `AI_ENGINEERING.md` records permanent requirements and
  `docs/ARCHITECTURE.md` records the source map and proposed design boundaries.
  Polymarket risk settings, deployment permissions and account-source policy
  are not imported. No CPU benchmark, target capacity or runtime behavior is
  claimed implemented. D-011's planning-only boundary remains unchanged.

### D-015 — AI-operated project; all decisions belong to the operator

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, in the current conversation
- **Decision:** This project will be AI-operated, but the human operator makes
  all project decisions. AI researches, explains options and recommendations,
  and performs the technical work within the operator's approved scope.
- **Consequence:** Undecided strategy, architecture, implementation scope,
  testing, risk, capital and operational choices return to the operator.
  Recommendations and watchlist ideas are not approvals. Routine technical
  steps within an approved task do not require repeated approval, but cannot
  introduce new policy or expand scope. Record accepted choices here.
  D-011 remains in force: planning only; no bot build or live execution.

### D-016 — Multi-WebSocket plan and initial trading parameters

- **Status:** ACCEPTED requirements; detailed architecture remains PROPOSED
- **Date:** 2026-09-19
- **Decision owner:** Operator, current conversation and clarification
- **Decision:** Use multiple WebSocket connections. Start with 10-contract
  entry orders and at most 30 resting entry orders, excluding orders managing
  open positions. This is not a 30-market or filled-position cap. Use the
  Polymarket-style $25 settled trading-loss stop in each fixed six-hour
  America/New_York window: 00-06, 06-12, 12-18 and 18-00.
- **Consequence:** The 10-contract size supersedes D-011's fewer-than-10
  boundary. Its $500 cap, no-paper-testing and planning-only restrictions
  remain. Open inventory limits, exits and precise stop/resumption mechanics
  remain decisions. No gradual entry-cap ratchet or separate daily loss cap
  is inferred. Loss stops can overshoot and do not cap total realized loss.
- **Design direction:** Recommend the best Kalshi-specific architecture using
  Polymarket's implementation and recorded failures as reference, not a full
  copy. Four connections and component choices in
  [the proposal](docs/MULTI_WEBSOCKET_DESIGN.md) need operator approval.
  No implementation, deployment or live execution is authorized.

### D-017 — Loss stop counts opened-and-closed trades only

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, current conversation
- **Decision:** For the D-016 stop, count only settled trading results from
  positions the bot opened and then closed. "Settled" here means realized
  closed-trade P&L, not waiting for the market event to resolve.
- **Consequence:** Include actual trading fees attributable to those closed
  trades. Exclude open/unmatched inventory, unrealized marks, pending or paid
  rewards, transfers and changes in cash caused by collateral/settlement timing.
  Do not recognize open inventory's estimated loss as settled loss.
  Detailed partial-close, fee-allocation and late-fill/window attribution rules
  remain part of the design for approval; no new risk policy is implied.
  Separate open-inventory protection still needs an operator decision.

### D-018 — Follow Polymarket's open-inventory rules

- **Status:** ACCEPTED policy direction and reference inventory limits;
  Kalshi-specific execution mapping must be reviewed before implementation
- **Date:** 2026-09-19
- **Decision owner:** Operator: "Open inventory just follow poly rule"
- **Reference:** Polymarket checkout `54ac71a241d1ad6f02e3445655bb7115247bac02`,
  `DECISIONS.md`, `docs/SAFETY_INVARIANTS.md`,
  `src/liquidity_bot/commissioning.py` and `reconciler.py`.
- **Decision:** Adopt that setup's open-inventory protection: cancel
  risk-building orders in a market after its first fill; manage only the exact
  remaining reducing quantity; do not add inventory while positioned; preserve
  ownership and exposure reservations until positive terminal/flat proof.
  Reducing orders do not consume the 30 resting-entry allowance.
- **Exposure limits:** Carry over the documented size-10 setup's $90
  per-market and $420 portfolio unmatched-loss exposure ceilings. Include
  filled inventory, working risk-building orders and deduplicated ambiguous
  sends; these are not additional allowances on top of inventory. The $500
  capital ceiling and actual buying-power checks also apply. They are exposure
  ceilings, not target allocation, realized-loss stops or permission to scale.
  Polymarket derives these as `9 * size` and `(slots + 10) * size` at
  size 10 / 32 slots. Carrying over its current dollar limits does not select
  32 Kalshi markets or reinterpret 30 resting orders as 30 slots.
- **Exit reference:** Work an exact passive reducer at the active touch,
  without a break-even floor or stepping ahead of one's own valid order.
  After 900 seconds evaluate a cancel-confirm, price-capped IOC. This is not
  guaranteed flatness after 15 minutes: ordinary crossing can defer for
  inadequate depth or projected loss worse than $8 at size 10, retaining the
  passive reducer. Absolute event/maintenance/HARD deadlines override ordinary
  deferral. Polymarket's pre-event boundary is five minutes before kickoff.
- **Kalshi adaptation:** Map the relevant event-risk/close deadline and exact
  quantity/fee/depth contracts before implementation; no automatic sports-only
  clock or Polymarket fractional-residue rule is imported. Unsupported cases
  require an operator decision, not invented behavior. No venue execution
  or profitability validation is claimed.
- **Unchanged:** D-016/D-017's size, 30-entry ceiling and closed-trade-only
  six-hour $25 stop; no paper stage; planning only. This does not authorize
  a build, start, orders, a loss-based entry ratchet or new strategy rules.

### D-019 — Native Windows, not Ubuntu/WSL

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, current conversation
- **Decision:** Use native Windows for this project, not Ubuntu/WSL.
- **Consequence:** Active project is
  `C:/Users/rynna/OneDrive/Documents/Bots/kalshi-bot`. Future environment,
  launch/control, locking, shutdown and recovery design must support Windows.
  Do not mirror further edits into WSL or treat that copy as active authority.
  D-009's WSL requirement and contrary historical runtime guidance are superseded.
  Preserve old WSL files/data; no deletion, migration, service installation,
  scheduled task, runtime change or bot start is authorized by this decision.

### D-020 — Verify inherited behavior in Polymarket code

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator, current conversation
- **Decision:** Do not rely on documents to establish Polymarket behavior.
  Verify the actual code before carrying its rules into Kalshi.
- **Consequence:** Trace configuration into enforcement and inspect edge cases;
  use safe relevant tests, distinguish defaults/selected values from live state,
  and correct summaries that overstate the evidence.
- **Correction to D-018:** The verified code uses `9 * size` per market and
  `(configured market slots + 10) * size` portfolio exposure. $90 is verified
  at size 10; $420 requires 32 configured slots and is not a fixed code limit.
  Kalshi slot count remains pending; do not treat the previous $420 wording as
  separate approval to select 32 markets. Preserve the requested Poly formula.
  All working/unknown-absent orders, including reducers, contribute to the
  reference's conservative dollar exposure; their 30-entry-count exclusion is
  a separate rule. See [code audit](docs/POLYMARKET_INVENTORY_CODE_AUDIT.md).
  104 configuration/reconciler tests passed on Windows. No live state is claimed.

### D-021 — Begin Windows-native implementation; accept percentage entry caps

- **Status:** ACCEPTED
- **Date:** 2026-09-19
- **Decision owner:** Operator: "Ok lets start building it", responding to the
  source-verified percentage-cap table.
- **Decision:** Start implementing the Windows-native liquidity-reward bot.
  Adopt 30/25/20/15/10/0 resting-entry caps at $0/$5/$10/$15/$20/$25
  closed-trade net loss, ratcheting downward during each fixed six-hour window.
  Keep 10-contract entries and exclude position-management orders from entry count.
- **Consequence:** Supersedes D-011's no-build restriction, not its no-paper
  requirement. Offline software/fault/load tests are allowed. Build the proposed
  multi-WebSocket/single-owner design with live execution disabled; no deployment,
  live start, order, cancellation or transfer is authorized. Unresolved managed
  market count and venue-specific risk/exit decisions must remain explicit
  live-readiness blockers rather than assumed defaults.

## Remaining implementation/live decisions

### D-022 — Include market rankings

- **Status:** ACCEPTED scope
- **Date:** 2026-09-20
- **Decision owner:** Operator: "Make sure we do the rankings of the market too"
- **Decision:** Include market rankings in the liquidity-reward bot build.
- **Boundary:** This does not select a live market set, profitability threshold,
  automatic allocation/repricing policy or larger capital/market capacity.
  Informational views distinguish gross reward arithmetic from unknown net
  profit/paid rewards and expose stale/unsafe/missing-input exclusions.

### D-023 — Market capacity follows the approved limits

- **Status:** ACCEPTED direction, 2026-09-20
- **Decision owner:** Operator: "Market capacity is based on our limits"
- **Decision:** Derive active entry breadth from capital, exposure, entry-count
  and eligibility constraints rather than asking for an arbitrary market target.
- **Boundary:** 30 entries can fund at most 15 two-sided or 30 one-sided entry
  markets before other gates. Inventory remains managed outside that count.
  No 30/32-slot setting or $400/$420 portfolio cap was selected. Resolve the old
  slot-dependent exposure formula explicitly; do not raise its cap automatically
  with occupancy or treat $500 capital as a newly selected portfolio-risk cap.
- **Related request:** Check actual Poly code for partial closes, selection,
  exits and restart. The audit below supplies evidence, not blanket adoption.

### D-024 — Adopt source-verified partial-close accounting

- **Status:** ACCEPTED, 2026-09-20
- **Decision owner:** Operator: "Ok do it then", accepting the recommendation
  based on `docs/POLYMARKET_POLICY_CODE_AUDIT.md`.
- **Decision:** Realize each matched partial close immediately using weighted-
  average entry basis. Charge actual fill fees immediately, including opening
  and unmatched portions. Count each fill once in the six-hour window when it
  is first durably recorded; retain venue execution time separately for reports.
  Late fills do not rewrite old risk windows. Preserve ratcheted caps and stops
  across restarts; exclude unrealized marks and rewards from this meter.
- **Boundary:** Supersedes D-017 only for fee timing and resolves partial-close
  and late-fill-window attribution. Existing capital, size and stop thresholds
  are unchanged. No live activation, automatic old-ledger migration, correction/
  reversal/settlement policy or complete historical-recovery approval is implied.
  Refuse incompatible accounting ledgers rather than silently reinterpret them.

### D-025 — Polymarket-style automatic recovery, adapted to Kalshi

- **Status:** ACCEPTED, 2026-09-20
- **Decision owner:** Operator: "Just do something like polymarket", after the
  executable-code explanation of automatic backfill and venue-cost fallback.
- **Decision:** Implement automatic recovery of verifiable bot executions,
  idempotent replay, immutable-identity conflict blocking, and a separately
  attributed venue-cost fallback for managing known inventory when local fill
  basis is incomplete. Ordinary verifiable repairs need no per-fill approval.
- **Adaptation:** WebSocket remains primary; bounded REST supplies missing order,
  history and reconciliation evidence. Preserve D-024 receipt-window accounting,
  per-fill risk ratchets and original duplicate receipts. Venue position cost
  never invents executions, fees, settled P&L or complete history proof.
  Exact account/market/order ownership and fresh position evidence are required
  before exposing fallback exit basis. Preserve its first-seen clock on restart.
- **Boundary:** Copy venue-confirmed correction handling only when Kalshi has a
  verified equivalent contract; absent that, conflicting fills/settlements stay
  blocked, not silently rewritten. No reset of holds, new exposure allowance,
  old-ledger migration or live activation is authorized. Recovery reports alone
  cannot establish complete stream continuity or allow new orders.

### D-026 — Connect recovery to the event engine

- **Status:** ACCEPTED, 2026-09-20
- **Decision owner:** Operator: "Ok do recommendation", accepting recovery
  integration for startup/restarts, disconnects, missed fills and fill-before-order.
- **Decision:** Wire the approved recovery components into the main event engine;
  automatically recover verifiable evidence with bounded resources/retries and
  keep new entries blocked until adequate account proof exists.
- **Boundary:** Native Windows, WebSocket first, existing capital/accounting
  rules unchanged. No live launch, credentials, orders, cancellations, new
  correction/settlement policy or fabricated continuity proof. Tests use injected
  transports and disposable local ledgers, not a paper trading stage.

### D-027 — Connect inventory management and account-wide risk checks

- **Status:** ACCEPTED build scope, 2026-09-20
- **Decision owner:** Operator: "Ok do next", accepting the next inventory-exit
  and account-wide-risk integration milestone.
- **Decision:** Wire approved exact-quantity passive inventory management and
  shared risk/reservation checks into the recovery-connected engine. Verify
  Polymarket's actual enforcement; preserve existing limits and percentage caps.
- **Boundary:** No portfolio-cap selection, forced-exit/deadline mapping, live
  activation or new authority to send/cancel orders. Keep unresolved decisions
  explicit blockers; exercise positive reservation paths only in offline fixtures.

### D-028 — Continue account-state verification

- **Status:** ACCEPTED build scope, 2026-09-20
- **Decision owner:** Operator: "Ok do next", following D-027's handoff.
- **Scope:** Continue account-state verification: coherent local snapshot/order/
  pending-fill checks and recovery provenance, with offline fault/load tests.
- **Boundary:** No claim of complete history from matching net positions or
  exhausted cursors; no invented private-stream barrier, starting basis, cash
  semantics, correction policy, portfolio cap or exit policy. No live activation.

### D-029 — Move Windows project beside Polymarket

- **Status:** ACCEPTED, 2026-09-20
- **Decision owner:** Operator requests transfer under rynna/Bots, then confirms
  the same Bots parent as Polymarket.
- **Decision:** Relocate the Windows project from OneDrive to
  `C:/Users/rynna/Bots/kalshi`, alongside (not inside) `liquidity-bot`.
  Move the supplied Kalshi credential file from the separate OneDrive Kalshi
  folder without displaying or changing its contents. Preserve project data.
- **Boundary:** Update active routing/environment paths and verify locally.
  No Polymarket changes, WSL migration, live trading, bot start or venue writes.
  D-019's Windows requirement remains; its old active path is superseded.
  The previously requested read-only account inspection remains pending.

### D-030 — Separate pre-bot history; verify private streams read-only

- **Status:** ACCEPTED scope and baseline direction, 2026-09-20
- **Decision owner:** Operator: "Ok do it", accepting the next-steps recommendation.
- **Decision:** Keep the 18 previously returned fills separate from this bot's
  trading record, retaining prior history as reconciliation evidence. Verify
  private WebSocket access and reconnect behavior without placing orders;
  continue the execution-disabled build and bring unresolved risk/exit choices
  back before implementing them.
- **Boundary:** This is not approval to discard history, assign every old fill
  to a foreign owner, reset existing risk windows, or choose a launch timestamp.
  A fresh scoped account check and durable ownership/history evidence are still
  required before arming. Any prior fill that proves bot-owned follows D-024/025;
  unknown ownership remains unresolved, never silently ignored. No historical
  ledger migration or automatic import of the 18 fills is authorized.
- **Unchanged:** $500 capital, size 10, 30 resting entry orders, $90 per-market
  exposure and the approved six-hour accounting/caps. No new aggregate exposure
  dollar cap or Kalshi event/IOC deadline was specified. No trading start,
  placement, cancellation, account mutation or paper-trading stage is authorized.

### D-031 — Follow Polymarket's exposure formula and verified local default

- **Status:** ACCEPTED direction, implemented using verified reference default,
  2026-09-20.
- **Decision owner:** Operator: "Just follow poly", responding to the proposed
  fixed $400 portfolio ceiling. That proposal is superseded, not accepted.
- **Source:** Local Poly HEAD `51cf59548b8e339be790e0662b6594ff0af77ddc`;
  `commissioning.py` computes quote size times (configured slots + 10).
  `slot_capacity.py` and both launchers default to 20; no local
  `data/commissioning_slot_capacity` override exists. This is checkout/default
  evidence, not a claim about a running process or another host.
- **Implementation:** Use that 20-slot reference for the exposure formula at
  Kalshi's approved size 10: $300 aggregate conservative exposure. Keep the
  $90 per-market limit, $500 capital ceiling, and 30 resting-entry cap unchanged.
  Inventory, working orders including reducers, and deduplicated uncertain sends
  share that exposure allowance; it never grows with current occupancy.
- **Capacity boundary:** This resolves the exposure calibration, not a new
  target or ceiling of 20 traded Kalshi markets. D-023's entry breadth remains
  limits-driven; the technical 128-market tracking bound is not a dollar budget.
  No automatic synchronization to future Poly configuration changes. Reconfiguring
  the reference capacity requires operator review, not hot changes under orders.
- **Unchanged:** Existing accounting/holds, history, exits and live-readiness
  requirements. No credentials, venue reads/writes, Poly modifications, live start
  or approval of unrelated Poly policies is implied.

### D-032 — Build source-verified inventory exits, execution disabled

- **Status:** ACCEPTED build scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do it", accepting the inventory-exit milestone.
- **Scope:** Exact passive reducers, conditional one-tick improvement, keeping
  an exact reducer at touch, 900-second ordinary exit evaluation, cancel-confirm
  before price-capped IOC, partial fills and reconnect/restart safeguards.
- **Reference adaptation:** Preserve the size-10 $8 ordinary projected-exit-loss
  allowance and 50% stressed displayed depth. Absolute verified event/maintenance/
  HARD deadlines override ordinary loss deferral, not ownership, book freshness,
  cancellation proof or actual tradability. Use actual Kalshi tick bands and
  reduce-only IOC semantics, not Poly payloads or fractional-residue exceptions.
- **Timing boundary:** Implement explicit verified event-risk time minus five
  minutes, bounded by the market's trading close. Do not substitute latest or
  expected expiration for event risk. Unknown event timing/early-close exposure
  stays an explicit producer/readiness gap; no invented universal event clock.
  Closed/inactive markets require attention, not an impossible flatten claim.
- **Authority:** Advisory plans and offline injected-command tests only. Live
  fee/deadline producers, complete account proof and production execution still
  require verification; no orders, cancels, account writes or live start authorized.

### D-033 — Structured diagnostics and error handling

- **Status:** ACCEPTED build scope, 2026-09-20.
- **Decision owner:** Operator requests proper logging for debugging and error handling.
- **Scope:** Bounded structured local logs, secret-safe failure context, correlation,
  rotation, observable retry/fatal states and offline fault/performance tests.
- **Boundary:** Preserve risk/proof gates and existing retry limits. No swallowing
  unexpected errors, blind mutation retries, account calls or live activation.
  Logs are diagnostics, never the durable financial ledger or recovery authority.

### D-034 — Connect verified market inputs to advisory exits

- **Status:** ACCEPTED build scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do it", accepting the next market-input milestone.
- **Scope:** Typed market/tick/fee/milestone readers, stream-first invalidation,
  bounded missing-field REST fallback and source/freshness-bound ExitTerms.
- **Boundary:** No universal event-start inference from expiry/strike dates,
  no assumed membership fee precision, and no automatic approval of market-rule
  interpretations. Unreviewed timing/early-close exposure and unsupported fee
  models remain blocked. No market selection, keys, orders or live activation.

### D-035 — Continue reconciliation and durable history-read evidence

- **Status:** ACCEPTED build scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do next", following D-034's reconciliation handoff.
- **Scope:** Continue account reconciliation, including durable completed history-read
  receipts, explicit interval gaps, restart inspection and bounded offline tests.
- **Boundary:** Receipts describe completed enumerations, not complete venue history
  or a snapshot/stream barrier. Do not choose/install a launch boundary, classify
  unknown old fills as foreign, reset risk, invent correction/settlement semantics,
  change limits or activate trading. Production input scheduling remains queued.

### D-036 — Bounded automatic metadata refresh scheduling

- **Status:** ACCEPTED build scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do next", accepting the D-035 scheduler handoff.
- **Scope:** Lifecycle-driven bootstrap/change/expiry refreshes around D-034,
  bounded shared work, retry limits, shutdown and offline resource/fault checks.
- **Added operator request:** "We have to also work on kalshi rate limits."
  Verify current venue token contracts and improve shared read-budget configuration,
  recovery priority, throttling and diagnostics. Document write/shard requirements;
  this does not enable mutations or tier upgrades.
- **Boundary:** No live launch, account use, market selection, automatic timing
  review or fee-profile approval. Keep existing freshness, risk and authority gates.

### D-037 — Mandatory Astra / 5.6 Sol development handoffs

- **Status:** SUPERSEDED by D-049 on 2026-09-21; retained as workflow history.
- **Decision owner:** Operator, explicitly requiring this flow from now on.
- **Decision:** Astra analyzes the repo/requirements and designs architecture,
  modules, data flow, interfaces, failure handling and implementation phases,
  without implementing. ALWAYS stop after planning so the operator can switch
  to 5.6 Sol. Sol implements Phase 1 against the agreed structure/interfaces,
  adds tests and verifies. Astra handles difficult problems and reviews the
  implementation/current Git diff for architectural violations, races, edge
  cases, security issues and incorrect assumptions. Sol implements the findings
  while preserving the architecture.
- **Consequence:** No automatic design-to-build transition or model switching.
  Canonical phase/handoff procedure: `AI_OPERATOR.md`. General build permission
  and "do next" do not bypass the planning stop. Existing D-036 code is preserved;
  new implementation is paused at this instruction, with review/verification
  handoff recorded in STATUS/NEXT. No deployment/live authority changes.

### D-038 — Design supervised quota freshness and grant expiry

- **Status:** ACCEPTED design scope only, 2026-09-20.
- **Decision owner:** Operator: "Ok do it", responding to the proposed next Astra
  design and required stop before Sol implementation.
- **Scope:** Inspect current code and official contracts; design quota lease
  validation, expiry enforcement, restricted bootstrap/recovery, scheduling,
  ownership, failure handling, phased interfaces and offline acceptance checks.
- **Handoff:** `docs/DESIGN_QUOTA_FRESHNESS.md` is the proposed contract. Stop for
  the operator's switch to 5.6 Sol and approval of Phase 1. Numeric freshness,
  probe and retry settings in that document are recommendations, not separately
  approved production configuration. Phase 2 requires its later handoff.
- **Boundary:** Documentation only this turn; no source/test implementation,
  account use, live activation, tier upgrades, write transport or risk changes.

### D-039 — Implement both quota-freshness phases

- **Status:** ACCEPTED implementation scope, 2026-09-20.
- **Decision owner:** Operator: "Implement both", following the D-038 design.
- **Scope:** Implement both phases in `docs/DESIGN_QUOTA_FRESHNESS.md`, including
  guarded quota leases, automatic scheduling/runtime integration, diagnostics and
  offline correctness/resource checks. This explicitly replaces that plan's
  separate Phase 2 approval gate for this implementation only.
- **Boundary:** Preserve D-037's handoff for Astra review after implementation.
  No automatic model switch, live activation, credentials/account calls, write
  transport, tier upgrade or trading-risk changes. Production probe configuration
  and all other launch proofs remain separately required.

### D-040 — Clarify the quota-review design before Sol fixes

- **Status:** ACCEPTED design scope only, 2026-09-20.
- **Decision owner:** Operator: "Ok do it", responding to the review handoff:
  clarify grant-expiry design, then stop for the switch to Sol fixes.
- **Scope:** Resolve R1's conflicting refresh/acceptance timing and specify
  bounded scheduling, interfaces and regressions; consolidate R2/R3 and the
  timing-test investigation into a clear proposed fixes assignment.
- **Handoff:** `docs/DESIGN_QUOTA_REVIEW_FIXES.md` is the proposed correction.
  Always STOP for the operator's switch and implementation instruction. The
  precise new deferral policy is a design recommendation, not already implemented
  or separately approved production configuration.
- **Boundary:** Documentation and read-only inspection only; no source/test
  fixes, live activation, credentials/account calls, risk changes or new milestone.

### D-041 — Implement the quota review fixes

- **Status:** ACCEPTED implementation scope, 2026-09-20.
- **Decision owner:** Operator: "Implement fixes", after switching to 5.6 Sol.
- **Scope:** Implement D-040's correction for reviewed R1-R3, investigate and
  repair the timing-sensitive test, add regressions and run focused, complete
  and affected resource checks. `docs/BUILD_QUOTA_REVIEW_FIXES.md` records the
  result; independent Astra re-review follows under D-037.
- **Boundary:** No live start, credentials/account calls, write transport,
  new risk settings, Polymarket changes or production probe selection.

### D-042 — Implement the two D-041 re-review follow-ups

- **Status:** ACCEPTED implementation scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do it", after the D-041 Astra review.
- **Scope:** Fix truthful supervisor status after repeated cancellation and
  replace retained rollover exceptions with a small immutable boundary record;
  add regressions and verify. `docs/BUILD_QUOTA_REVIEW_FOLLOWUPS.md` records the
  implementation. Independent Astra re-review follows under D-037.
- **Boundary:** Preserve the D-040 design, physical wire ownership and late-429
  accounting. No live start, credentials/account calls, write transport, risk
  changes, Polymarket changes or production probe selection.

### D-043 — Replace the canonical GitHub repository with this Windows project

- **Status:** ACCEPTED repository publication scope, 2026-09-20.
- **Decision owner:** Operator: "all work here gonna use this previous github,
  delete everything on this repo and replace with what we have on kalshi bot now",
  naming `https://github.com/rynn-arriola/kalshi-bot`.
- **Scope:** Publish the present `C:/Users/rynna/Bots/kalshi` source, tests and
  documentation to the existing GitHub repository, replacing its old tracked
  tree. Connect the active Windows folder to that repository. Keep prior Git
  history recoverable; retire the obsolete remote `main` branch after preserving
  its history in the default `master` branch.
- **Boundary:** Exclude credentials, local data, logs, environments and
  machine-local transfer/deployment state. No live bot start or account action.

### D-044 — Design starting-account and private-stream continuity

- **Status:** ACCEPTED design scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do it" in response to the recommended next
  Astra design milestone.
- **Scope:** Analyze the current Windows Kalshi implementation and official API
  contract, use Polymarket source as a read-only conceptual reference, and
  specify a phased starting-inventory/private-stream continuity design in
  `docs/DESIGN_ACCOUNT_CONTINUITY.md`.
- **Boundary:** Stop after design for the operator's 5.6 Sol switch under D-037.
  This does not authorize implementation, a launch boundary, live account calls,
  credential use, order actions or trading. An undocumented venue handoff is
  not proof of complete fill coverage or starting inventory.

### D-045 — Implement evidence-only continuity Phase 1

- **Status:** ACCEPTED implementation scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do phase 1" and confirmed "I did" when
  asked whether this task had switched to 5.6 Sol.
- **Scope:** Implement and offline-verify Phase 1 of
  `docs/DESIGN_ACCOUNT_CONTINUITY.md` in the native Windows Kalshi project.
  Record local private epochs and baseline candidates, tighten positions
  pagination, and handle unscoped position updates without claiming account
  authority. Hand off to Astra for independent review under D-037.
- **Boundary:** No venue handoff proof, approved opening inventory, Phase 2/3,
  real account calls, credential use, live order action or activation. All
  entry and live-readiness gates remain false.

### D-046 — Implement D-045 independent-review fixes

- **Status:** ACCEPTED fix scope, 2026-09-20.
- **Decision owner:** Operator: "Ok fix it" after receiving the independent
  Astra review and switching back to the implementation model.
- **Scope:** Implement R1-R5 from `docs/REVIEW_D045_ASTRA.md`: private-event
  shutdown ownership, accepted epoch-open cancellation/gap reconciliation,
  coherent quota-boundary status, quota-test callback synchronization and a
  correctly instrumented reconnect resource fixture. Add regressions and rerun
  focused/full/resource/preflight verification.
- **Boundary:** Preserve D-044's evidence-only architecture. No Phase 2/3,
  approved baseline, risk/policy change, real account/credential call, order
  action, deployment or live activation. Return to Astra re-review under D-037.

### D-047 — Fix D-046 re-review shutdown findings

- **Status:** ACCEPTED fix scope, 2026-09-20.
- **Decision owner:** Operator: "Ok do it" after receiving the D-046 Astra
  re-review and switching back to the implementation model.
- **Scope:** Implement both P2 findings from `docs/REVIEW_D046_ASTRA.md`: retain
  reader/marker cleanup through repeated caller cancellation, continue bounded
  queue draining after malformed/staging failures, preserve valid tail fills,
  and surface cleanup failures. Add regressions and rerun focused/full/resource
  and disabled-preflight verification.
- **Boundary:** Preserve the evidence-only architecture and previously cleared
  fixes. No Phase 2/3, baseline, policy/risk change, account/credential call,
  order action, deployment or live activation. Return to Astra re-review.

### D-048 — Fix D-047 connection-finalization finding

- **Status:** ACCEPTED fix scope, 2026-09-21.
- **Decision owner:** Operator: "Fix it", after switching to the implementation
  model following the D-047 Astra review.
- **Scope:** Retain connection finalization when ordinary stop or cancellation
  overlaps a disconnect drain; preserve valid transport-tail fills, finish marker
  close/gap refresh and add the review's real-queue/repeated-cancel regressions.
  `docs/BUILD_ACCOUNT_CONTINUITY_FINALIZER_FIX.md` records implementation and
  verification. Return to Astra review under D-037.
- **Boundary:** Preserve the evidence-only architecture and all prior limits.
  No Phase 2/3, baseline, policy/risk change, account/credential call, order
  action, deployment or live activation.

### D-049 — Mandatory usage-efficient model selection

- **Status:** ACCEPTED permanent rule, 2026-09-21.
- **Decision owner:** Operator, explicitly requiring model selection before every
  substantive task and limiting the repository to GPT-6 Astra and GPT-5.6 Sol.
- **Decision:** GPT-5.6 Sol is the default for approved implementation, focused
  fixes, verification, routine checks/reports/docs, standard operations and Astra
  review fixes. GPT-6 Astra is reserved for material architecture/design,
  strategy/risk/business logic, uncertain difficult incidents, cross-system
  concurrency/recovery/security/account state, architecture/risk-sensitive API
  research and final review of meaningful or high-risk live-money code.
- **Workflow:** Before substantive work, print `Recommended agent: Astra — ...`
  or `Recommended agent: 5.6 Sol — ...`. A model mismatch stops development for
  the operator's switch. Full development remains Astra design -> Sol implement/
  verify -> Astra review -> Sol fixes/verify, with a stop at each handoff. Small,
  low-risk Sol changes need no Astra review; urgent exposure-prevention actions
  never wait for switching. Do not switch repeatedly within a phase; escalate
  Sol only on evidence of material architectural uncertainty or risk.
- **Boundary:** This supersedes D-037 where routing differs. It does not alter
  authority, safety, testing, deployment, restart, capital, risk or live-action
  rules. `AI_OPERATOR.md` is the canonical detailed procedure.

### D-050 — Design a Polymarket-like native Windows supervisor

- **Status:** ACCEPTED requirement/design scope, 2026-09-21; operator approved
  the S1 design and offline policy values through “Implement.”
- **Decision owner:** Operator requests a supervisor that survives errors and
  recovers automatically, before returning to the D-048 review.
- **Scope:** Trace Polymarket's actual supervisor/recovery source and design
  native Windows process supervision, bounded recovery, persistent stops,
  diagnostics and restart safety. See
  [the proposed design](docs/DESIGN_WINDOWS_SUPERVISOR.md).
- **Boundary:** Approval covers the execution-disabled S1 policy/control
  foundation only. It does not approve automatic source-code fixes, live
  auto-resume, services/tasks, deployment, account calls or trading. Preserve
  all existing risk/authority rules. D-048 review remains pending; design
  priority does not waive its integration gate.

### D-051 — Implement native Windows supervisor S1

- **Status:** ACCEPTED implementation scope and implemented, 2026-09-21.
- **Decision owner:** Operator: “Implement,” after the D-050 Astra design stop.
- **Scope:** Add immutable execution-disabled supervisor contracts and pure
  transition policy, a separate transactional bounded SQLite control journal,
  fake event/process tests and offline resource fixtures. Persist stop and
  generation state, reserve attempts before spawn requests, reject stale child
  events, bound restart/backoff and base health on useful progress.
- **Evidence:** See
  [D-051 build evidence](docs/BUILD_WINDOWS_SUPERVISOR_S1.md): 32 focused and
  836 full tests pass, with resource and disabled-preflight checks.
- **Boundary:** No real process launcher, IPC, runtime integration, service/task,
  credential/network/account access, live auto-resume or trading. Independent
  Astra review is mandatory before S2. D-048's separate review also remains an
  S2 gate.

### D-052 — Implement D-051 supervisor review findings

- **Status:** ACCEPTED implementation scope and implemented, 2026-09-21.
- **Decision owner:** Operator: “Implement those,” after the D-051 Astra review.
- **Scope:** Implement R1-R7 from
  [the D-051 review](docs/REVIEW_D051_ASTRA.md): trusted control/event time
  separation, stop/safety generation fencing, strict lifecycle ownership,
  bounded useful-progress and startup deadlines, persistent explicit retry holds,
  truthful process-exit/cleanup recovery evidence and a real persisted-work idle
  benchmark. Add deterministic regressions and rerun required verification.
- **Evidence:** See
  [D-052 build evidence](docs/BUILD_WINDOWS_SUPERVISOR_REVIEW_FIXES.md): 46
  focused and 850 full tests pass, with repeated focused, resource, compilation
  and disabled-preflight checks.
- **Boundary:** Preserve D-051's execution-disabled S1 scope. No process launcher,
  IPC, runtime integration, service/task, credential/network/account access,
  live auto-resume or trading. Independent Astra re-review is mandatory before
  S2; D-048's separate review remains another S2 gate.

### D-053 — Implement D-052 supervisor re-review findings

- **Status:** ACCEPTED implementation scope and implemented, 2026-09-21.
- **Decision owner:** Operator: “Ok implement,” after the D-052 Astra re-review.
- **Scope:** Implement R1-R5 from
  [the D-052 review](docs/REVIEW_D052_ASTRA.md): fence every STOP generation,
  evaluate startup/progress expiry before status refresh, preserve attention
  during failed-spawn release, persist and validate clock continuity across
  store instances/lifetimes, and require complete child identity. Add the
  review's deterministic policy and SQLite regressions.
- **Evidence:** See
  [D-053 build evidence](docs/BUILD_WINDOWS_SUPERVISOR_REVIEW_FOLLOWUPS.md): 59
  focused and 863 full tests pass, with 10/10 repeated focused runs, resource,
  compilation, documentation and disabled-preflight checks.
- **Boundary:** Preserve execution-disabled S1. No process launcher, IPC,
  runtime integration, service/task, configuration, credential/network/account
  access, bot restart, orders or live action. Independent Astra re-review is
  mandatory before S2; D-048 remains a separate S2 gate.

### D-054 — Implement D-053 clock review findings

- **Status:** ACCEPTED implementation scope and implemented, 2026-09-21.
- **Decision owner:** Operator: “Sol implement,” after the D-053 Astra review.
- **Scope:** Implement R1/R2 from
  [the D-053 review](docs/REVIEW_D053_ASTRA.md): durably apply local clock trust
  failures before stale child payload filtering while preserving stale labels,
  and replace exact quantized default boot matching with persisted, tolerance-
  validated wall/monotonic continuity. Add policy and SQLite regressions for
  stale/missing identity, duplicate lifecycle, multiple store handles, reopen,
  active-child ownership, harmless jitter and genuine discontinuities.
- **Evidence:** See
  [D-054 build evidence](docs/BUILD_WINDOWS_SUPERVISOR_CLOCK_FIXES.md): 64
  focused and 868 full tests pass, with 10/10 repeated focused runs, four
  counterfactual parent detections, resource, compilation and preflight checks.
- **Boundary:** Preserve execution-disabled S1. No launcher, IPC, runtime
  integration, service/task, configuration, credential/network/account access,
  bot restart, orders or live action. Independent Astra re-review is mandatory
  before S2; D-048 remains a separate S2 gate.

### D-055 — Design supervisor S2 native lifecycle

- **Status:** ACCEPTED design scope only, 2026-09-21.
- **Decision owner:** Operator: “Astra design s2,” after S1 and D-048 review
  clearance. This does not approve the resulting design's implementation.
- **Scope:** Specify native Windows ownership, process/IPC interfaces, stop and
  crash recovery, bounded resources, offline runtime integration and acceptance.
  See [S2 design](docs/DESIGN_WINDOWS_SUPERVISOR_S2.md).
- **Proposed handoff:** Approve S2A inert-process foundations for Sol first;
  stop for Astra review before a separately assigned S2B offline runtime/fence
  phase. The split and new fixture thresholds await approval.
- **Boundary:** Design/documentation only. No code/configuration change, process
  launch, service/task, laptop suspend/reboot, credentials, venue/account access,
  order action, deployment or live authority. Preserve D-049's design stop.

### D-056 — Implement supervisor S2A inert-process foundations

- **Status:** ACCEPTED and implemented offline, 2026-09-21; Astra review pending.
- **Decision owner:** Operator: “Sol implement,” after the D-055 Astra design.
- **Scope:** Implement only D-055 S2A: protected native role objects, serialized
  control/reservation state, bounded strict local pipe IPC, one fixed inert child,
  retained graceful shutdown, cold orphan release, native fault tests and resource
  evidence. See [build evidence](docs/BUILD_WINDOWS_SUPERVISOR_S2A.md).
- **Boundary:** No S2B runtime adapter or recovery-fence transfer, production start
  command, service/task, bot configuration/runtime change, credentials, network,
  venue/account access, order action, deployment or live authority. Stop for Astra
  review under D-049.

### D-057 — Astra implements the S2A review fixes

- **Status:** ACCEPTED and implemented offline, 2026-09-21; independent review pending.
- **Decision owner:** Operator: “I recommend astra to fix this since sol took so
  long to solve it,” after the D-056 review and correction handoff.
- **Scope:** Astra implements R1-R8 from [the review](docs/REVIEW_D056_ASTRA.md)
  and verifies the inert S2A foundation. This is a task-specific exception to
  D-049's Sol fix phase, not a permanent change to model routing.
- **Boundary:** Preserve the D-055 architecture and all safety gates. No S2B,
  live runtime, configuration, account access, deployment, restart or trading.
  Stop after fixes/verification for independent review; implementation is not
  self-clearance.

### D-058 — Astra commits previous work and performs overall review

- **Status:** ACCEPTED and performed, 2026-09-21.
- **Decision owner:** Operator: “Astra commit then review the one I asked previously.”
- **Scope:** One-task commit exception to D-049, followed by the requested
  overall code review and priority-ordered actions. Previous work committed as
  `8c03aa0`; [review evidence](docs/REVIEW_OVERALL_2026-09-21.md).
- **Boundary:** No permanent routing change, new implementation, source/config
  change, push, runtime action or live authority. Recommendations need a new
  assignment; existing review and readiness gates remain in force.

### D-059 — Plan the first two overall-review priorities

- **Status:** ACCEPTED design assignment, 2026-09-21; plan produced, implementation
  and proposed schema/capacity changes await approval.
- **Decision owner:** Operator: “Ok we are doing it in priority order lets do 1
  and 2 first Astra go ahead and plan it.”
- **Scope:** Astra designs safety-command capacity and the atomic reservation/
  execution handoff in [the plan](docs/DESIGN_COMMAND_CAPACITY_HANDOFF.md), then
  stops for approval and Sol. The earlier overall queue remains the roadmap.
- **Boundary:** Documentation only. No source/config/runtime change, migration,
  history deletion, commit/push, live action or clearance of other readiness gates.

### D-060 — Implement the approved D-059 design

- **Status:** ACCEPTED and implemented offline, 2026-09-21;
  [Astra review](docs/REVIEW_D060_ASTRA.md) requires corrections.
- **Decision owner:** Operator: “Sol implement.”
- **Review assignment:** Operator subsequently: “Astra do it.” Independent
  review only; no new implementation or operational authority inferred.
- **Scope:** Implement both priority fixes exactly through the D-059 interfaces,
  schema-3 disposable ledgers, bounded durable capacity credits, atomic
  preparation/receipt consumption, fault tests and 30/120-market resource
  verification. Evidence: [D-060 build record](docs/BUILD_COMMAND_CAPACITY_HANDOFF.md).
- **Boundary:** No schema-2 migration, archive deletion, risk/config change,
  authenticated transport, account access, deployment, restart or live action.
  Stop after verification for independent Astra review; all other readiness
  gates retain their previous state.

### D-061 — Remove model-switch workflow requirements

- **Status:** ACCEPTED permanent workflow change, 2026-09-21.
- **Decision owner:** Operator: “forget about switching models,” followed by
  “no more changing models even the one from earlier.”
- **Decision:** D-049's required model recommendation, model-mismatch stop and
  manual Astra/Sol phase switching are superseded. Continue authorized work
  with the model already selected; do not recommend or require model changes.
- **Boundary:** This changes only model routing. It does not relax project
  decisions, independent review quality, testing, security, deployment,
  restart, credential, account, capital, risk or live-action controls.

### D-062 — Continue the remaining work in priority order

- **Status:** ACCEPTED offline build assignment, 2026-09-21; in progress.
- **Decision owner:** Operator: “Just do all of it in priority order,” followed
  by “Ok continue working.”
- **Scope:** Finish the remaining authorized development in the
  [overall review](docs/REVIEW_OVERALL_2026-09-21.md). Priority 3 starts with
  [bounded opening-account/cash evidence](docs/DESIGN_OPENING_ACCOUNT_CASH.md),
  current public API verification, offline tests and independent review.
  Continue routine implementation and verification without model-switch gates.
- **Boundary:** No inferred account exclusivity, launch timestamp, inventory
  adoption, settlement/correction policy, loss reset or schema migration.
  Pending choices still require the operator; broad build scope does not grant
  credentials/account calls, live transport activation, trading, deployment,
  restart, commit or push. Existing review and readiness gates remain in force.

### D-063 — Return to single-session development

- **Status:** ACCEPTED workflow change, 2026-09-21.
- **Decision owner:** Operator: “Cant we go back on how we usually build stuff
  like originally,” after discussing delegated workers and usage.
- **Decision:** Continue directly in the primary session. Stop existing workers,
  preserve their partial work, and complete/review/verify it locally. No new
  delegated agents or worker sessions unless explicitly requested again.
  D-061's no-model-switch rule remains.
- **Boundary:** Existing build scope, testing, risk and live-operation rules
  remain unchanged. Worker handoffs are not completion evidence.

### D-064 — Primary account, exclusive bot use, flat opening

- **Status:** ACCEPTED opening-account policy, 2026-09-21; not activated.
- **Decision owner:** Operator: “I wont trade manually on this,” then “Ok” to
  the explicit confirmation: use the primary Kalshi account exclusively for
  this bot, starting only after verifying zero open positions and zero resting
  orders.
- **Decision:** Scope the future bot to primary subaccount 0. No manual trading
  in that account during bot operation. Before arming, require fresh evidence of
  no nonzero positions and no resting orders. Existing history remains separate
  reconciliation evidence under D-030; it is not silently imported or discarded.
- **Boundary:** This records the operator's choice, not current flatness,
  exclusivity proof, a launch timestamp, settled-loss reset, opening basis or
  live authority. Choose the exact accounting boundary during a separately
  approved launch after the required checks. No account/API call, order action,
  migration, deployment or restart is approved by this decision.

### D-065 — Verify, commit and push completed work

- **Status:** ACCEPTED permanent repository workflow, 2026-09-21.
- **Decision owner:** Operator: “When we finish something we should always check
  then commit and push.”
- **Decision:** After each completed work unit, run relevant verification,
  review the exact diff for scope and secrets, commit the verified changes and
  push to the canonical GitHub branch. Verify local/remote commit parity after
  pushing. Do not present unfinished work as complete merely to publish it.
- **Boundary:** This supersedes earlier no-commit/no-push clauses for completed,
  verified repository work only. Preserve unrelated changes, ignored private
  material and remote commits; never force-push or resolve divergence by
  overwriting. If checks or publication fail, report the state and retain work.
  Publication is not bot deployment, account access or live-trading authority.

### D-066 — Pause new entries for unexpected bot-owned settlement

- **Status:** ACCEPTED offline policy, 2026-09-21; not live-integrated.
- **Decision owner:** Operator: “Ok do recommended,” after the recommendation
  to pause new Kalshi entries when a bot-owned open position unexpectedly
  reaches settlement, and reconcile before treating its payout as six-hour
  loss-meter P&L.
- **Decision:** Such a settlement requires a new-entry pause and operator
  reconciliation. Do not synthesize a closing fill, infer basis from venue
  aggregate costs, or automatically add settlement revenue/fees to the D-024
  six-hour matched-fill meter. Preserve the observed position, settlement and
  cash evidence; keep unrelated exit/cancel safety actions available under
  their separate rules. No automatic release merely because the account later
  appears flat or a new six-hour window begins.
- **Boundary:** Existing pre-bot settlements remain historical evidence, not
  proof of a bot-owned event. The precise approved opening boundary, durable
  settlement journal/hold and reconciliation-release protocol are separate
  build gates. This decision does not authorize account calls, schema migration,
  live entry/order actions, deployment or restart.

### D-067 — Finish offline opening-account accounting and enforcement

- **Status:** ACCEPTED build assignment, 2026-09-21.
- **Decision owner:** Operator: “Finish it then,” after the remaining baseline,
  cash/reservations, persistent settlement pause, history/stream and entry-gate
  work was explained.
- **Scope:** Complete the necessary offline design, implementation, integration,
  recovery tests and review under D-064/D-066. Persist accounting evidence and
  restrictions in the single-writer ledger; enforce them in entry reservation
  and prepared-command dispatch. Test new schema only in disposable ledgers.
- **Boundary:** No migration or modification of existing runtime ledgers,
  authenticated account reads, real opening boundary, fabricated venue proof,
  live transport, deployment or trading. Missing venue guarantees remain
  explicit blockers. D-065 governs publication after verification.

### D-068 — Operational reconciliation gate in place of global venue proof

- **Status:** ACCEPTED offline implementation, 2026-09-21.
- **Decision owner:** Operator: “Ok follow poly,” after the actual Polymarket
  reconciliation, freshness gates, buying-power reservations and residual
  silent-staleness limitation were explained from executable code.
- **Context:** The operator requested the required work to finish the release
  path. Investigation found that the reviewed user-data timestamp is explicitly
  approximate; existing source contracts do not establish global REST/stream
  completeness. This explicit choice, not generic build authorization, changes
  the entry-safety criterion.
- **Decision:** Adopt the bot-owned, source-fenced reconciliation and
  conservative two-ceiling cash model in the
  [accounting design](docs/DESIGN_OPENING_ACCOUNT_ACCOUNTING.md). Continue to
  report global venue handoff as unproved. Preserve economic holds and all
  independent risk, operator-settlement, live-activation and restart rules.
- **Tradeoff:** Common REST/stream delay can temporarily hide an event; repeated
  matching observations cannot eliminate that residual risk. The strict-proof
  alternative was not selected; live activation still requires separate approval.
- **Authority:** Offline implementation/tests only, not account requests, a real
  opening boundary, trading or deployment. Do not import Poly's venue fields,
  risk settings or operational permissions. D-066 economic holds remain.

### D-069 — Optimize Kalshi selection using reward qualification and Poly lessons

- **Status:** ACCEPTED offline implementation, 2026-09-21.
- **Decision owner:** Operator: "Ok using all these info make sure we optimize
  our market selection", following the reference-price, competition, loss of
  scoring eligibility and safe quoting discussion.
- **Decision:** Implement the [reference-audit direction](docs/POLYMARKET_RANKING_AUDIT.md):
  eligible feasible size-10 quotes first, estimated gross hourly reward then
  capital efficiency, current reward qualification separate from hypothetical
  new quotes, fresh bounded selection and retained inventory/uncertain owners.
  Do not copy Poly's sports filters, historical reward or fill-loss calibration.
- **Boundary:** Keep D-021's reducer of resting-entry COUNT, not contract size,
  and all existing cash/exposure/exit gates. Show payout uncertainty, not net
  profit or assured payment. Losing scoring is not terminal order evidence.
  No automatic score-chasing repricing, new profitability cutoff, live transport,
  account request, deployment, bot operation or market-set approval.
- **Build contract:** [Selection integration](docs/BUILD_MARKET_SELECTION.md)
  records bounded advisory integration, tests and remaining activation gates.

### D-070 — Poly-style selection and per-program reward tracking, no fixed 60

- **Status:** ACCEPTED offline build, 2026-09-21.
- **Decision owner:** Operator: "follow something like polymarket but optimize
  it to kalshis advantage and add that tracker", then "Forget about the 60
  markets" and "Just do it like poly".
- **Decision:** Drop the proposed fixed 60-market pool. Adapt bounded discovery,
  fresh book-based selection, stable incumbents and flat/clear refill from
  Polymarket's executable code. Add per-program estimated accrual, qualification
  time, unknown gaps and estimated time to the $1 minimum. Preserve Kalshi's
  target/reference rules, actual period duration and separate payout evidence.
- **Boundary:** No automatic import of Poly sports filters, numerical risk,
  fill-loss priors or six-hour reward duration. Size 10, max 30 resting entries,
  existing capital/exposure/exit rules and live-disable remain. No new numerical
  payout buffer, score-displacement threshold or reward-chasing cancellation is
  approved. Track estimates as advisory, never paid cash or entry authority.
- **Implementation:** [Tracker and discovery adaptation](docs/BUILD_REWARD_TRACKER.md).

### D-071 — Connect automatic market admission and rotation

- **Status:** ACCEPTED offline implementation, 2026-09-21.
- **Decision owner:** Operator: "Ok do number 1", referring to automatic market
  admission/rotation in the pending-work list.
- **Scope:** Connect D-070 candidates to bounded book subscriptions and fresh
  D-069 ranking under existing order/capital limits. Never remove inventory,
  working orders or unresolved activity; retain uncertain scope. No fixed pool,
  new category filter, repricing policy, live order transport or bot operation.
- **Implementation contract:** [Admission and rotation](docs/BUILD_MARKET_ADMISSION.md).

### D-072 — Connect selected entry pairs to guarded order transport

- **Status:** ACCEPTED offline implementation, 2026-09-21.
- **Decision owner:** Operator: "Ok do 2", referring to the ordered work item
  after automatic market admission.
- **Scope:** Connect current ranked additions to the existing writer risk gates,
  quota owner and dispatcher. Use one exact two-leg local reservation and one
  documented Kalshi V2 batch create; retain single create/cancel transport for
  inventory exits. Mixed, unidentified or uncertain venue outcomes fail closed,
  request reconciliation and are never retried automatically.
- **Boundary:** This approves construction and synthetic verification only.
  Live activation remains unavailable; no credential/account request, order,
  cancel, deployment, bot start or restart is authorized. The next independent
  strategy/runtime work is production reward reflection/checkpoint lifecycle.
- **Implementation contract:** [Entry dispatch and transport](docs/BUILD_ENTRY_DISPATCH_TRANSPORT.md).

### D-073 — Build production reward reflection/checkpoint lifecycle

- **Status:** ACCEPTED execution-disabled implementation, 2026-09-22.
- **Decision owner:** Operator: "After this can you start working on 3 and 4?"
- **Scope:** Join exact own resting orders, public book levels and queue-position
  evidence for estimate-only reward tracking; own bounded checkpoint load/save
  in runtime lifecycle. Unknown or raced evidence remains UNKNOWN.
- **Boundary:** No paid-reward claim, strategy/risk change, bot start or live
  order authority. [Implementation](docs/BUILD_REWARD_REFLECTION.md).

### D-074 — Continue readiness work after reward reflection

- **Status:** ACCEPTED implementation/read-only verification, 2026-09-22.
- **Decision owner:** Operator requested #4 after #3 and directed remaining work
  in priority order.
- **Scope:** Resolve the existing S2A resource blocker without weakening safety;
  use previously authorized read-only credentials for current limits/costs when
  needed; preserve unresolved fee/timing/account evidence explicitly.
- **Boundary:** No strategy/risk choice, authenticated write, order action,
  service/task, bot start/restart or live launch. S2B and launch remain separate.
- **Implementation contract:** [resource/readiness evidence](docs/BUILD_WINDOWS_SUPERVISOR_RESOURCE_FIXES.md).

### Earlier concentration question — superseded by D-070

- **Status:** Historical discussion; D-070 above is the current build direction.
- **Operator concern:** Rotation may spread earnings below the $1 payout
  minimum; concentrate on the strongest opportunities, referencing Poly's
  moneyline approach. Clarify strict sports moneyline-only versus best eligible
  programs across categories with less rotation before changing selection.
- **Verified rule:** [Kalshi help](https://help.kalshi.com/en/articles/16076644-liquidity-and-volume-incentive-programs-where-to-find-them)
  says a final reward below $1 per individual program is not paid. This is not
  an aggregate event/day/account minimum; estimates can change before payment.
- **Recommendation, not implemented:** Prefer feasible programs with enough
  safe remaining earning time to clear the minimum with a margin; reduce
  unnecessary rotation and track program-specific estimated accrual. Neither
  moneyline classification nor an estimate guarantees payment. Never keep risk
  solely to reach $1 or override existing exit, exposure and stop-loss rules.
- **Boundary:** No new category filter, hard earnings gate, dwell period,
  repricing rule or launch authority accepted/implemented in this build unit.

### Earlier recovery-import question — superseded by D-025

The stricter proposal below was not selected verbatim. D-025 selects a
Polymarket-like automatic recovery flow, including a separate venue-cost fallback.

- **Question:** May missing fills be automatically imported only after proving
  bot ownership and complete starting cost basis, with corrections, unexplained
  inventory and settlement discrepancies blocking new entries for operator review?
- **Recommendation:** Yes, under those evidence gates; never manufacture basis
  from a current balance/position snapshot or treat archive absence as cancellation.
- **Alternative:** Keep every missing-fill import manual/operator-reviewed.
- **Why needed:** D-024 specifies accounting but does not approve the complete
  replay/recovery policy. The async question is unanswered as of this handoff;
  no automatic import or correction/settlement implementation was enabled.
- **Impact:** No new capital allowance. Imported real fills could change current
  receipt-window P&L and tighten caps/stops; they must never loosen a ratchet.
  Unknown/conflicting evidence halts new-entry readiness and retains reservations.
  Existing ledgers/history remain untouched; migration is separately scoped.
- **Work done meanwhile:** Archived order evidence retrieval/binding under D-021
  and existing ownership/terminal-proof rules; not new accounting authority.

### Earlier fixed-slot question — superseded by D-023's capacity direction

The earlier fixed-slot proposal was: 30 slots imply $400 exposure
under the accepted formula, versus $420 for 32. Neither changes the $500 capital
ceiling or 30 resting-entry-order limit. Two-sided quoting consumes two orders
per market. Configuration remains null until dynamic-capacity/exposure integration,
not because the operator must choose one of these fixed-slot suggestions.

### Earlier accounting question — superseded by D-024 above

The following records the earlier, unapproved alternatives for audit only.
The original-execution-window and prorated-fee proposal was NOT selected.

Source correction after the operator requested Poly verification:
`docs/POLYMARKET_POLICY_CODE_AUDIT.md` confirms immediate matched partial-close
P&L, weighted-average basis, immediate actual fees (including unmatched inventory)
and receipt-time loss windows. The earlier execution-time late-fill proposal below
is not a verified Poly copy. Fee timing differs from the Kalshi candidate and
needs explicit approval against D-017; no accounting code changed in this audit.

Requested choice: whether each partial close counts immediately, with proportional
entry/exit fees, and late recovered fills are attributed to their original
execution-time window while preserving already-triggered stops. Alternative:
count only a fully closed position, or leave the contract undecided.

This determines historical replay and loss-window recomputation; current
FIFO/receipt-time fixtures are still candidate accounting, not approval of this
new recommendation. Recovery now stages evidence separately. No answer is
recorded yet. Implementing approved replay must preserve per-fill ratchets,
restart durability and explain tied timestamps/corrections. The $500 capital,
size 10, 30-entry ceiling and $25 window trigger are unchanged. Until resolved,
automatic replay/resumption stays disabled and existing trading data is not
rewritten. This request adds no deployment or live-action authority.

The percentage-budget entry-cap rule is now accepted by D-021. Inventory exits
remain exact-quantity reductions, not percentage liquidation.

Under D-016, size, resting-entry count and the six-hour $25 stop are accepted.
D-018 adopts Polymarket's open-inventory policy; D-020 corrects the evidence:
the old slot-dependent exposure formula needs mapping to D-023's dynamic capacity.
Kalshi-specific deadline/exit mapping, any additional correlated-event limits,
resumption details and final live architecture/performance acceptance remain
unresolved. Implementation is authorized by D-021; live activation is not.
No paper stage is required by the operator.

When a decision becomes necessary, add a short request here containing:

- the exact choice;
- why progress depends on it;
- evidence and uncertainty;
- recommended option and alternatives;
- maximum capital/state impact;
- rollback or stop condition.
