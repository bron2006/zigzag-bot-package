# Separate index clock-effect test, frozen before USTEC outcomes

Original Fed research is S&P500 futures, not USTEC; this is our CFD adaptation.
The authors' July2026 update says the 02-03ET drift faded after2021. Thus weak
prior support, not a promised edge. Test own broker series rather than present
old academic returns as available profits.
https://libertystreeteconomics.newyorkfed.org/2026/07/the-disappearing-overnight-drift/

Only USTEC, existing hash-verified M5 Jan2024..Oct7 2026. Fixed entry02:00
America/New_York, LONG, protective stop2*prior14M5 simpleTR below entryOpen.
15 immediately preceding contiguous bars mandatory for TR and previous close.
12 contiguous bars02:00..02:55; end exit last Close03:00 if stop not reached.
Adverse gaps actualOpen, stop checked on entry bar. No TP or moving stop.
All path coverage required even if an early stop would have been observed;
missing window counted unknown, no interpolation, >=95% coverage gate.
Weekdays excluding existing published cash holidays/early closures, explicitly
an adaptation not the Fed's exact day/sample selection. NY time fixed, not a
claim of correctly following London DST differences. No parameter sweep.

Report each year gross/2pointRT/5pointRT, no leverage or dollar account claim.
Costs conditional not measured historical quotes; same-day trade entirely after
ordinary overnight rollover, no assumed overnight swap, actual terms unverified.
03-04ET LONG and02-03ET SHORT controls with independent causal stop distances,
not promoted as discoveries. Record unstopped gross separately as diagnostic.
2026 test is retrospective already-used history, NOT independent confirmation.
Gate main mean stresspoints>0 ALLyears, >=100known2026, coverage>=95%eachyear,
2026 mean stress lower64-cell-adjusted95%10calendar-day blockbootstrap>0.
Passing would require prospective and actual bid/ask validation; no deployment.
