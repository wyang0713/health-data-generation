import subprocess
import sys
import datetime
import os

print(f"ETL triggered at {datetime.datetime.now()}")

try:
    # sys.executable keeps this working outside the container, where "python" may not be on PATH
    subprocess.run([sys.executable, "etl.py"], check=True)
    print("ETL completed successfully")
    etl_failed = False
except subprocess.CalledProcessError as e:
    print("ETL failed:", e)
    etl_failed = True

log_path = os.getenv("LOG_PATH", "logs/etl.log")
with open(log_path, "a") as log:
    log.write(f"{datetime.datetime.now()} - ETL run completed\n")

# propagate failure so Docker/orchestrators see a non-zero exit code
if etl_failed:
    sys.exit(1)
