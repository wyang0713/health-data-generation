'''
Consolidates the patient and health CSVs into year-partitioned JSON files
that model the 1:M patient-to-health relationship. Each patient is the root
object with its year of health records nested in a "health_records" array.

Output: json_data/{year}/patient_health_{year}.json
Health records with no matching patient go to json_data/orphan_report.json.
Adjust the constants below before running.
'''

import os
import json
import pandas as pd
from datetime import date


PATIENT_CSV_PATH = 'patient_data/patients.csv'
HEALTH_DATA_DIR  = 'health_data'
JSON_OUTPUT_DIR  = 'json_data'

# Year range should match what main.py generated. Missing CSVs are skipped.
START_YEAR = 2014
END_YEAR   = 2016

JSON_INDENT       = 2      # None for compact output
JSON_ENSURE_ASCII = False


def serialize_value(value) -> object:
    '''Converts pandas/numpy types to JSON-serialisable Python types.'''
    if isinstance(value, (pd.Timestamp, date)):
        return str(value)
    if hasattr(value, 'item'):
        return value.item()
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def clean_record(record: dict) -> dict:
    return {k: serialize_value(v) for k, v in record.items()}


def load_patients(patient_csv_path: str) -> dict:
    '''Returns {patient_id: patient dict with empty health_records list}.'''
    if not os.path.exists(patient_csv_path):
        raise FileNotFoundError(
            f'Patient CSV not found at: {patient_csv_path}\n'
            f'Run main.py first to generate the source data.'
        )

    df = pd.read_csv(patient_csv_path)

    required = {
        'id', 'birthdate', 'gender', 'city', 'state',
        'height', 'start_weight', 'start_systolic',
        'start_diastolic', 'create_date', 'updated_date'
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(
            f'patients.csv is missing expected columns: {missing}'
        )

    patients = {}
    for _, row in df.iterrows():
        patient = clean_record(row.to_dict())
        patient['health_records'] = []
        patients[str(row['id'])] = patient

    print(f'  Loaded {len(patients):,} patients from {patient_csv_path}')
    return patients


def load_health_year(year: int, health_data_dir: str, patients: dict) -> tuple:
    '''
    Reads the year's monthly health CSVs and appends each record to the
    matching patient's health_records (patient_id is implicit from the parent,
    so it is excluded from the nested record).

    Returns (records_loaded, files_found, orphan_rows).
    '''
    records_loaded = 0
    files_found = 0
    orphan_rows = []

    for month in range(1, 13):
        filename = f'health_data_{year}{month:02d}.csv'
        full_path = os.path.join(health_data_dir, str(year), filename)

        if not os.path.exists(full_path):
            continue

        files_found += 1
        df = pd.read_csv(full_path)

        required = {
            'patient_id', 'heart_rate', 'weight',
            'systolic', 'diastolic', 'record_date'
        }
        missing = required - set(df.columns)
        if missing:
            print(f'    WARNING: Skipping {filename} — '
                  f'missing columns: {missing}')
            continue

        for _, row in df.iterrows():
            pid = str(row['patient_id'])

            health_record = clean_record({
                'heart_rate':  row['heart_rate'],
                'weight':      row['weight'],
                'systolic':    row['systolic'],
                'diastolic':   row['diastolic'],
                'record_date': row['record_date']
            })

            if pid in patients:
                patients[pid]['health_records'].append(health_record)
                records_loaded += 1
            else:
                orphan_row = clean_record(row.to_dict())
                orphan_row['_source_file'] = filename
                orphan_rows.append(orphan_row)

        print(f'    OK  {year}/{month:02d}  {filename}  '
              f'({len(df):,} records)')

    return records_loaded, files_found, orphan_rows


def write_year_json(year: int, patients: dict, output_dir: str) -> str:
    year_dir = os.path.join(output_dir, str(year))
    os.makedirs(year_dir, exist_ok=True)

    output_path = os.path.join(year_dir, f'patient_health_{year}.json')

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(
            list(patients.values()),
            f,
            indent=JSON_INDENT,
            ensure_ascii=JSON_ENSURE_ASCII
        )

    return os.path.abspath(output_path)


def write_orphan_report(orphan_rows: list, output_dir: str) -> None:
    if not orphan_rows:
        return

    os.makedirs(output_dir, exist_ok=True)
    report_path = os.path.join(output_dir, 'orphan_report.json')

    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(orphan_rows, f, indent=2, ensure_ascii=False)

    print(f'\n  WARNING: {len(orphan_rows):,} orphan health records '
          f'(no matching patient_id in patients.csv)')
    print(f'  Orphan report written to: {os.path.abspath(report_path)}')


def generate_json_partitions(
    patient_csv_path: str = PATIENT_CSV_PATH,
    health_data_dir: str = HEALTH_DATA_DIR,
    json_output_dir: str = JSON_OUTPUT_DIR,
    start_year: int = START_YEAR,
    end_year: int = END_YEAR
) -> None:
    print('=' * 62)
    print('JSON partition generator  (1:M  patient -> health_records)')
    print('=' * 62)

    all_orphans = []
    total_records = 0
    total_files = 0
    total_skipped = 0

    for year in range(start_year, end_year + 1):

        print(f'\n-- Year {year} ' + '-' * 46)

        # fresh patient dict per year so health_records don't accumulate
        patients = load_patients(patient_csv_path)

        records_loaded, files_found, orphan_rows = load_health_year(
            year, health_data_dir, patients
        )

        skipped = 12 - files_found
        total_files += files_found
        total_skipped += skipped
        total_records += records_loaded
        all_orphans += orphan_rows

        if files_found == 0:
            print(f'  No health CSV files found for {year} — skipping.')
            continue

        output_path = write_year_json(year, patients, json_output_dir)

        patients_with_records = sum(
            1 for p in patients.values() if p['health_records']
        )

        print(f'\n  Year {year} summary:')
        print(f'    Monthly CSVs found  : {files_found}/12  '
              f'({skipped} not found, skipped)')
        print(f'    Health records      : {records_loaded:,}')
        print(f'    Patients with data  : '
              f'{patients_with_records:,} of {len(patients):,}')
        print(f'    Output file         : {output_path}')

    write_orphan_report(all_orphans, json_output_dir)

    print('\n' + '=' * 62)
    print('Complete.')
    print(f'  Years processed     : {start_year} - {end_year}')
    print(f'  Monthly CSVs loaded : {total_files:,}')
    print(f'  Monthly CSVs skipped: {total_skipped:,}')
    print(f'  Total health records: {total_records:,}')
    print(f'  Orphan records      : {len(all_orphans):,}')
    print(f'  Output folder       : {os.path.abspath(json_output_dir)}')
    print('=' * 62)


if __name__ == '__main__':
    generate_json_partitions()
