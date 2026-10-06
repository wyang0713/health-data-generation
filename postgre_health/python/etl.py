from dotenv import load_dotenv
import os
from sqlalchemy import create_engine
from urllib.parse import quote_plus
import pandas as pd
import psycopg2
from datetime import datetime

EXPECTED_COLUMNS = [
    "patient_id", "heart_rate", "weight", "systolic", "diastolic", "record_date"
]

def connect_to_sqlalchemy():
    user = os.getenv("POSTGRES_USER")
    raw_password = os.getenv("POSTGRES_PASSWORD")
    password = quote_plus(raw_password) if raw_password else ""
    host = os.getenv("POSTGRES_HOST", "postgres")
    port = "5432"
    db = os.getenv("POSTGRES_DB")
    # pin psycopg2 driver; SQLAlchemy 2.1 defaults bare postgresql:// to psycopg v3
    engine = create_engine(f"postgresql+psycopg2://{user}:{password}@{host}:{port}/{db}")
    return engine

def connect_to_psycopg2():
    return psycopg2.connect(
        dbname=os.getenv("POSTGRES_DB"),
        user=os.getenv("POSTGRES_USER"),
        password=os.getenv("POSTGRES_PASSWORD"),
        host=os.getenv("POSTGRES_HOST", "postgres"),
        port="5432"
    )

def create_health_stats_table(conn):
    with conn.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS health_stats (
            patient_id CHAR(8) NOT NULL,
            heart_rate INTEGER,
            weight REAL,
            systolic INTEGER,
            diastolic INTEGER,
            record_date DATE,
            ingested_at TIMESTAMP,
            source_file TEXT
        );
        """)
        # quarantine columns stay TEXT so malformed values can be stored as-is
        cur.execute("""
        CREATE TABLE IF NOT EXISTS health_stats_staging_errors (
            patient_id TEXT,
            heart_rate TEXT,
            weight TEXT,
            systolic TEXT,
            diastolic TEXT,
            record_date TEXT,
            ingested_at TIMESTAMP,
            source_file TEXT,
            error TEXT
        );
        """)
    conn.commit()

def validate_row(row):
    try:
        str(row["patient_id"])
        int(row["systolic"])
        int(row["diastolic"])
        int(row["heart_rate"])
        float(row["weight"])
        pd.to_datetime(row["record_date"])
        return True, None
    except Exception as e:
        return False, str(e)

def preprocess_csv(path, source_file, engine):
    df = pd.read_csv(path)
    missing = [col for col in EXPECTED_COLUMNS if col not in df.columns]
    if missing:
        raise ValueError(f"Missing columns: {missing}")

    valid_rows = []
    error_rows = []

    for _, row in df.iterrows():
        is_valid, error_msg = validate_row(row)
        if is_valid:
            # cast back to int: one bad value upcasts the whole column to float,
            # and COPY rejects "146.0" into an INTEGER column
            row["heart_rate"] = int(float(row["heart_rate"]))
            row["systolic"] = int(float(row["systolic"]))
            row["diastolic"] = int(float(row["diastolic"]))
            row["weight"] = float(row["weight"])
            row["ingested_at"] = datetime.now()
            row["source_file"] = source_file
            valid_rows.append(row)
        else:
            error_row = {
                k: (None if pd.isna(v) else str(v))
                for k, v in row.to_dict().items()
            }
            error_row.update({
                "ingested_at": datetime.now(),
                "source_file": source_file,
                "error": error_msg
            })
            error_rows.append(error_row)

    valid_df = pd.DataFrame(valid_rows)
    temp_path = path.replace(".csv", "_temp.csv")
    valid_df.to_csv(temp_path, index=False)

    # a failed quarantine insert should not abort the file's valid rows
    if error_rows:
        error_df = pd.DataFrame(error_rows)
        try:
            error_df.to_sql("health_stats_staging_errors", engine, if_exists="append", index=False)
            print(f"{len(error_rows)} rows quarantined from {source_file}")
        except Exception as e:
            print(f"Could not quarantine {len(error_rows)} rows from {source_file}: {e}")

    return temp_path

def copy_csv_to_postgres(csv_path, table_name, conn):
    try:
        with open(csv_path, 'r', encoding='utf-8') as f:
            with conn.cursor() as cur:
                cur.copy_expert(f"COPY {table_name} FROM STDIN WITH CSV HEADER", f)
        conn.commit()
    except Exception as e:
        print(f"COPY failed for {csv_path}: {e}")
        conn.rollback()

def get_year_folders(base_path: str) -> list:
    return sorted([
        folder for folder in os.listdir(base_path)
        if os.path.isdir(os.path.join(base_path, folder)) and folder.isdigit()
    ])

def run_etl():
    load_dotenv()
    engine = connect_to_sqlalchemy()
    conn = connect_to_psycopg2()

    patient_path = "data/patients.csv"
    if not os.path.exists(patient_path):
        raise FileNotFoundError("patients.csv does not exist")

    df_patients = pd.read_csv(patient_path)
    df_patients.to_sql("patients", engine, if_exists="replace", index=False)
    print("Patient data loaded")

    create_health_stats_table(conn)

    # the Docker volume persists between runs; skip files already ingested
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT source_file FROM health_stats")
        already_loaded = {r[0] for r in cur.fetchall()}

    health_base = "health_data"
    years = get_year_folders(health_base)
    missing_files = []

    for year in years:
        year_path = os.path.join(health_base, year)
        expected_files = [f"health_data_{year}{str(month).zfill(2)}.csv" for month in range(1, 13)]

        for file_name in expected_files:
            if file_name in already_loaded:
                print(f"Skipping {file_name} (already loaded)")
                continue
            full_path = os.path.join(year_path, file_name)
            if os.path.exists(full_path):
                try:
                    temp_path = preprocess_csv(full_path, file_name, engine)
                    copy_csv_to_postgres(temp_path, "health_stats", conn)
                    os.remove(temp_path)
                    print(f"Loaded {file_name}")
                except Exception as e:
                    print(f"Error processing {file_name}: {e}")
            else:
                missing_files.append(full_path)

    if missing_files:
        print("Missing health data files:")
        for path in missing_files:
            print(f"  - {path}")

    with conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM health_stats")
        print(f"Total rows in health_stats: {cur.fetchone()[0]}")

    conn.close()
    print("ETL completed")

if __name__ == "__main__":
    run_etl()
