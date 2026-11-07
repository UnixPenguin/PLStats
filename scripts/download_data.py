"""Download the latest OpenPowerlifting CSV into data/.

The zip is ~170 MB (~650 MB unzipped). Older openpowerlifting-*.csv files in
data/ are removed so run_pipeline.py always picks up the newest snapshot.
Source: https://openpowerlifting.gitlab.io/opl-csv/  (public domain)
"""
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

URL = "https://openpowerlifting.gitlab.io/opl-csv/files/openpowerlifting-latest.zip"
DATA = Path(__file__).resolve().parents[1] / "data"


def main():
    DATA.mkdir(exist_ok=True)
    print(f"Downloading {URL} ...", flush=True)
    req = urllib.request.Request(URL, headers={"User-Agent": "PLStats-data-refresh"})
    with tempfile.TemporaryFile() as tmp:
        with urllib.request.urlopen(req) as r:
            shutil.copyfileobj(r, tmp, length=1 << 20)
        tmp.seek(0)
        with zipfile.ZipFile(tmp) as z:
            csvs = [n for n in z.namelist() if n.endswith(".csv")]
            if not csvs:
                sys.exit("No CSV found in the archive.")
            target = DATA / Path(csvs[0]).name
            part = target.with_suffix(".part")
            # zipfile checks the CRC while reading, so a corrupt download raises here; the CSV only
            # replaces the old one once it has been written completely.
            with z.open(csvs[0]) as src, open(part, "wb") as dst:
                shutil.copyfileobj(src, dst, length=1 << 20)
            part.replace(target)
            for old in DATA.glob("openpowerlifting-*.csv"):
                if old != target:
                    old.unlink()
    print(f"Saved {target}")


if __name__ == "__main__":
    main()
