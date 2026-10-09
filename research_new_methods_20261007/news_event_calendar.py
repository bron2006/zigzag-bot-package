"""Official BLS archive release dates, headers verified via web 2026-10-09.
No reference-month labels, economic figures or forecast surprises are used.
"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

RELEASES = [
    ("2024-01-05", "empsit", "https://www.bls.gov/news.release/archives/empsit_01052024.htm"),
    ("2024-01-11", "cpi", "https://www.bls.gov/news.release/archives/cpi_01112024.htm"),
    ("2024-02-02", "empsit", "https://www.bls.gov/news.release/archives/empsit_02022024.htm"),
    ("2024-02-13", "cpi", "https://www.bls.gov/news.release/archives/cpi_02132024.htm"),
    ("2024-03-08", "empsit", "https://www.bls.gov/news.release/archives/empsit_03082024.htm"),
    ("2024-03-12", "cpi", "https://www.bls.gov/news.release/archives/cpi_03122024.htm"),
    ("2024-04-05", "empsit", "https://www.bls.gov/news.release/archives/empsit_04052024.htm"),
    ("2024-04-10", "cpi", "https://www.bls.gov/news.release/archives/cpi_04102024.htm"),
    ("2024-05-03", "empsit", "https://www.bls.gov/news.release/archives/empsit_05032024.htm"),
    ("2024-05-15", "cpi", "https://www.bls.gov/news.release/archives/cpi_05152024.htm"),
    ("2024-06-07", "empsit", "https://www.bls.gov/news.release/archives/empsit_06072024.htm"),
    ("2024-06-12", "cpi", "https://www.bls.gov/news.release/archives/cpi_06122024.htm"),
    ("2024-07-05", "empsit", "https://www.bls.gov/news.release/archives/empsit_07052024.htm"),
    ("2024-07-11", "cpi", "https://www.bls.gov/news.release/archives/cpi_07112024.htm"),
    ("2024-08-02", "empsit", "https://www.bls.gov/news.release/archives/empsit_08022024.htm"),
    ("2024-08-14", "cpi", "https://www.bls.gov/news.release/archives/cpi_08142024.htm"),
    ("2024-09-06", "empsit", "https://www.bls.gov/news.release/archives/empsit_09062024.htm"),
    ("2024-09-11", "cpi", "https://www.bls.gov/news.release/archives/cpi_09112024.htm"),
    ("2024-10-04", "empsit", "https://www.bls.gov/news.release/archives/empsit_10042024.htm"),
    ("2024-10-10", "cpi", "https://www.bls.gov/news.release/archives/cpi_10102024.htm"),
    ("2024-11-01", "empsit", "https://www.bls.gov/news.release/archives/empsit_11012024.htm"),
    ("2024-11-13", "cpi", "https://www.bls.gov/news.release/archives/cpi_11132024.htm"),
    ("2024-12-06", "empsit", "https://www.bls.gov/news.release/archives/empsit_12062024.htm"),
    ("2024-12-11", "cpi", "https://www.bls.gov/news.release/archives/cpi_12112024.htm"),
    ("2025-01-10", "empsit", "https://www.bls.gov/news.release/archives/empsit_01102025.htm"),
    ("2025-01-15", "cpi", "https://www.bls.gov/news.release/archives/cpi_01152025.htm"),
    ("2025-02-07", "empsit", "https://www.bls.gov/news.release/archives/empsit_02072025.htm"),
    ("2025-02-12", "cpi", "https://www.bls.gov/news.release/archives/cpi_02122025.htm"),
    ("2025-03-07", "empsit", "https://www.bls.gov/news.release/archives/empsit_03072025.htm"),
    ("2025-03-12", "cpi", "https://www.bls.gov/news.release/archives/cpi_03122025.htm"),
    ("2025-04-04", "empsit", "https://www.bls.gov/news.release/archives/empsit_04042025.htm"),
    ("2025-04-10", "cpi", "https://www.bls.gov/news.release/archives/cpi_04102025.htm"),
    ("2025-05-02", "empsit", "https://www.bls.gov/news.release/archives/empsit_05022025.htm"),
    ("2025-05-13", "cpi", "https://www.bls.gov/news.release/archives/cpi_05132025.htm"),
    ("2025-06-06", "empsit", "https://www.bls.gov/news.release/archives/empsit_06062025.htm"),
    ("2025-06-11", "cpi", "https://www.bls.gov/news.release/archives/cpi_06112025.htm"),
    ("2025-07-03", "empsit", "https://www.bls.gov/news.release/archives/empsit_07032025.htm"),
    ("2025-07-15", "cpi", "https://www.bls.gov/news.release/archives/cpi_07152025.htm"),
    ("2025-08-01", "empsit", "https://www.bls.gov/news.release/archives/empsit_08012025.htm"),
    ("2025-08-12", "cpi", "https://www.bls.gov/news.release/archives/cpi_08122025.htm"),
    ("2025-09-05", "empsit", "https://www.bls.gov/news.release/archives/empsit_09052025.htm"),
    ("2025-09-11", "cpi", "https://www.bls.gov/news.release/archives/cpi_09112025.htm"),
    ("2025-10-24", "cpi", "https://www.bls.gov/news.release/archives/cpi_10242025.htm"),
    ("2025-11-20", "empsit", "https://www.bls.gov/news.release/archives/empsit_11202025.htm"),
    ("2025-12-16", "empsit", "https://www.bls.gov/news.release/archives/empsit_12162025.htm"),
    ("2025-12-18", "cpi", "https://www.bls.gov/news.release/archives/cpi_12182025.htm"),
    ("2026-01-09", "empsit", "https://www.bls.gov/news.release/archives/empsit_01092026.htm"),
    ("2026-01-13", "cpi", "https://www.bls.gov/news.release/archives/cpi_01132026.htm"),
    ("2026-02-11", "empsit", "https://www.bls.gov/news.release/archives/empsit_02112026.htm"),
    ("2026-02-13", "cpi", "https://www.bls.gov/news.release/archives/cpi_02132026.htm"),
    ("2026-03-06", "empsit", "https://www.bls.gov/news.release/archives/empsit_03062026.htm"),
    ("2026-03-11", "cpi", "https://www.bls.gov/news.release/archives/cpi_03112026.htm"),
    ("2026-04-03", "empsit", "https://www.bls.gov/news.release/archives/empsit_04032026.htm"),
    ("2026-04-10", "cpi", "https://www.bls.gov/news.release/archives/cpi_04102026.htm"),
    ("2026-05-08", "empsit", "https://www.bls.gov/news.release/archives/empsit_05082026.htm"),
    ("2026-05-12", "cpi", "https://www.bls.gov/news.release/archives/cpi_05122026.htm"),
    ("2026-06-05", "empsit", "https://www.bls.gov/news.release/archives/empsit_06052026.htm"),
    ("2026-06-10", "cpi", "https://www.bls.gov/news.release/archives/cpi_06102026.htm"),
    ("2026-07-02", "empsit", "https://www.bls.gov/news.release/archives/empsit_07022026.htm"),
    ("2026-07-14", "cpi", "https://www.bls.gov/news.release/archives/cpi_07142026.htm"),
    ("2026-08-07", "empsit", "https://www.bls.gov/news.release/archives/empsit_08072026.htm"),
    ("2026-08-12", "cpi", "https://www.bls.gov/news.release/archives/cpi_08122026.htm"),
    ("2026-09-04", "empsit", "https://www.bls.gov/news.release/archives/empsit_09042026.htm"),
    ("2026-09-11", "cpi", "https://www.bls.gov/news.release/archives/cpi_09112026.htm"),
    ("2026-10-02", "empsit", "https://www.bls.gov/news.release/archives/empsit_10022026.htm"),
]


def events():
    result = []
    for date, kind, url in RELEASES:
        instant = datetime.fromisoformat(date + "T08:30:00").replace(tzinfo=ZoneInfo("America/New_York"))
        result.append({"id": f"{date}_{kind}", "date": date, "kind": kind,
                       "release_ts": int(instant.timestamp()),
                       "release_utc": instant.astimezone(timezone.utc).isoformat(),
                       "source": url, "header_time_verified": True})
    return sorted(result, key=lambda row: row["release_ts"])

