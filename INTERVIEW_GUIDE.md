# Interview guide - aml-transaction-monitoring

## What it does, in three sentences

It generates a year of realistic bank transactions (518,492 rows, 2,000 customers) and deliberately plants six
money-laundering patterns on 190 customers, so there is a known answer key. Eight monitoring rules written in SQL run
over that data in DuckDB, produce alerts, and the alerts are scored and ranked for an analyst queue. Because the answer key
exists, the project measures exactly how many alerts each rule gets right, tunes the thresholds so the monthly alert volume
fits a team of analysts, and writes a SAR-style summary for the top cases.

## Why each key decision was made (plain language)

- **Synthetic data with labels.** No public dataset has real SAR outcomes, and without labels you can't say what a
  "false positive" is. Writing the generator myself means every alert is gradable. The cost is that my rules were written
  knowing the patterns, so recall looks better than it would in real life - I say that up front.
- **Rules in SQL files, not Python functions.** In a bank the rules live in a monitoring system that compliance people
  read and auditors ask about. A SQL file with `{threshold}` placeholders is readable by them and testable by me.
  DuckDB runs it on a laptop in seconds.
- **Tuning against a budget.** The team can work about 40 alerts a month. The tuner starts each rule loose (max recall),
  then repeatedly tightens whichever rule's marginal alerts contain the fewest real hits, until the budget fits. A rule that
  never reaches 15 % precision is switched off and flagged for redesign instead of being tuned into uselessness.
- **Precision floor AND recall floor.** Without a recall floor the tuner could silently switch off coverage of a whole
  typology to save volume; without a precision floor it would keep a rule that only generates work.
- **Scoring with a multi-rule bonus.** One customer hitting structuring *and* cash-intensity in the same month is a
  stronger case than two customers hitting one rule each. That is how analysts actually triage.
- **Template SAR narratives, not an LLM.** A SAR is a regulatory document; the template guarantees every required fact
  (who, what, when, how much, why suspicious) appears and nothing is invented.

## What I'd do differently

- Add counterparty-network rules (funnel accounts, mule rings); today every rule is single-customer.
- Replace the generated risk ratings with a KYC-style risk model so the scoring bonus means something.
- Add an alert-outcome feedback table so the tuner uses analyst dispositions instead of injected labels - that is
  what a real program tunes on.
- Make typologies mutate over time in the generator to test how quickly rules go stale.

## Five questions an interviewer would ask, with honest answers

**1. Your tuned precision is 83%. Real programs run at 5-10 %. Why the gap?**
Because the answer key and the rules were written by the same person: injected structuring *is* three deposits under
$10k in a week, which is exactly what R1 looks for. The number that transfers to real life is the false-positive rate on the
*clean* population - for example R8 (velocity spike) alerted on 251 customers of which only 15 were planted cases,
an 85% false-positive rate, which is why the tuner disabled it.

**2. What does the tuner actually optimise?**
Hits per alert at the margin. It asks, for each rule, "if I tighten you one notch, how many alerts disappear and how many
of those were real?" and tightens the rule with the worst ratio first. It stops when total alerts fit the budget
(58/month baseline -> 39/month tuned) and never drops a rule below 60 % recall of its typology unless nothing else can give.

**3. Why DuckDB rather than pandas or a real database?**
Rules are set logic over a big table - joins, windows, group-bys - which is what SQL is for. DuckDB runs that SQL
in-process on parquet files with no server, so the whole thing runs from a clone in 20 seconds; the same SQL would move to
Snowflake or Postgres with minor syntax changes.

**4. How would you validate this against real data?**
Back-test the rules on historical transactions where SAR decisions are known, measure precision by rule against
analyst dispositions, and compare the alert volume to the team's capacity. Then run the tuner on *that* feedback. The
mechanics in this repo don't change; only the labels do.

**5. What is structuring and why $10,000?**
US banks must file a Currency Transaction Report for cash transactions over $10,000. Breaking a $30,000 deposit into
four deposits of $7,500 to avoid that report is structuring, a federal crime even if the money is clean. R1 looks for
several deposits just under the threshold in a short window, often across branches.

## Numbers to have in your head (from `results/metrics.json`)

518,492 transactions · 2,000 customers · 12 months · 972 injected rows on 190 customers · 8 rules · baseline 693 alerts
(57.8/mo) at 53% precision, 175/190 suspicious customers reached · tuned 470 alerts (39.2/mo) at 83% precision,
190/190 reached · R8 disabled (85% FP) · priority mix high 293, medium 133, low 44 · runs in ~18 s.
