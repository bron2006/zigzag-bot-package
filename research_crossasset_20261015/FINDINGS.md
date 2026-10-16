# Completed different-mechanism screening, 2026-10-15

Four mechanisms / five main asset-arms; ALL gates failed. No candidate deployed.
2317 closed main observations plus one pending pair observation; controls are
additional diagnostics, not counted as new strategies or proof of independence.
No threshold changes after each separately frozen protocol. All history reused,
retrospective, not a prospective independent holdout. No claims all variants of
these mechanisms are unprofitable. No claimed funded cash, deposits or fills.

## Ratio BTC/ETH reversion
316closed,1pending. Conditional30bp RT plus weighted20%annual long financing:
mean bp per gross initial notional 2024 -39.762(n123),2025 -46.148(n106),
2026H1 -28.731(n58),2026H2 -38.063(n29). Gross2026H1 positive4.009bp but
costs exceed this. Prices are Binance spot proxies, not executable CFD pairs;
no actual spot shorts, beta neutrality, stop/margin or liquidation simulation.

## BTC leader / ETH lag
73closed. Stressmean bp2024 +7.284(n43),2025 -60.573(n22),2026H1 -56.156(n5),
2026H2 +54.044(n3). Do not call every phase negative: last phase positive but
three events cannot support a strategy. No stable predictive advantage shown.

## USTEC fixed02-03NY with protective stop
688closed main, all scheduled window coverage100%, no unknowns. Conditional
5pointRT mean2024 -5.524(n249),2025 -2.622(n247),2026 +.410(n192).
2026 adjusted95%CI[-9.379,+11.288]points, not established positive expectation.
2026 base2pointmean+3.410, gross+5.410. Do not call all years/scenariosnegative.
No wideningstop/hoursearch after results. Original Fed effect was S&Pfutures,
not USTEC; authors' July2026 update says original02-03effect faded after2021:
https://libertystreeteconomics.newyorkfed.org/2026/07/the-disappearing-overnight-drift/
Hence neither old paper nor a selected2026 mean justifies live deployment.

## Executed taker flow
BTC743closed,ETH497closed; no unknown/pending. Prior-volume shock and completed
aggressor-side imbalance, onebar full delay and1hour outcome. Stressmeanbp
BTCearly -29.558(n483),late -34.848(n260);ETHearly -28.144(n303),late -32.747(n194).
Grossearly tiny+.542/+1.956bp, latemeansnegative -4.737/-2.634bp. Not historical
orderbook/footprint or millisecond tests; rejects THIS delayed aggregate rule.
Costs hypothetical20/30bp RT, longfinancing20%annual sensitivity, not measured
historicalfees or a guarantee these are the actual venue break-even levels.

## Verification and decision
15new synthetic testsPASS: ratio causality/futurepoison/delay/cooldown/weights,
financing/pending/alignment/bootstrap, Nasdaq entrybarstop/adversegap/missing,
flow direction/priorvolume/futurepoison/timing/costs. Full isolated703testsPASS.
First ratio fixture had zero prior variance because both synthetic assets were
identical; fixed fixture to contain spread variation, not the rule. Early index
smoke check was weak; replaced with exact protective-stop/gap unit assertions.
Independent Decimal price-return recomputation389crossassetobservations matched,
maxabsoluteerror1.67e-16. This validates arithmetic, not market execution.

Research code only. Production code, flags, workers, Telegram, saved cash/history,
DB and credentials untouched. No live health claim from this turn; not inspected.
No deployment, GitHubpush, real orders or attachments/changed-file lists to owner.
Do not turn failed opposite/hour controls into post-hoc discovered strategies.
Further search should be a new separately frozen event/market hypothesis, not
threshold optimization of these outcomes or an assurance a profitable bot exists.
