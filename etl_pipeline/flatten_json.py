import pandas as pd
import json
import os
import argparse
import sys


def parse_args():
    parser = argparse.ArgumentParser(
        description='Flatten patient_health_{year}.json to two CSVs'
    )
    parser.add_argument(
        '--year',
        type=int,
        required=True,
        help='The year to process e.g. 2014'
    )
    return parser.parse_args()


def flatten_health(file_year):
    file_path   = os.path.join('json_data', str(file_year))
    json_name   = f'patient_health_{file_year}.json'
    json_path   = os.path.join(file_path, json_name)
    health_path = os.path.join(file_path, f'health_{file_year}.csv')

    with open(json_path, 'r') as f:
        data = json.load(f)

    health_json = pd.json_normalize(
        data=data,
        record_path='health_records',
        meta=['id']
    )
    health_json.to_csv(health_path, index=False)

    print(f'Health rows written  : {len(health_json):,}')


def flatten_patient(file_year):
    file_path    = os.path.join('json_data', str(file_year))
    json_name    = f'patient_health_{file_year}.json'
    json_path    = os.path.join(file_path, json_name)
    patient_path = os.path.join(file_path, f'patient_{file_year}.csv')

    with open(json_path, 'r') as f:
        data = json.load(f)

    patient_columns = [
        'id',
        'birthdate',
        'gender',
        'city',
        'state',
        'height',
        'start_weight',
        'start_systolic',
        'start_diastolic',
        'create_date',
        'updated_date'
    ]

    patient_json = pd.json_normalize(data=data)
    patient_json = patient_json[patient_columns]
    patient_json = patient_json.drop_duplicates(subset=['id'])
    patient_json.to_csv(patient_path, index=False)

    print(f'Patient rows written : {len(patient_json):,}')


if __name__ == '__main__':
    # SSIS passes --year via the Execute Process Task. For local testing,
    # comment these two lines out and hardcode: file_year = 2014
    args = parse_args()
    file_year = args.year

    try:
        flatten_health(file_year)
        flatten_patient(file_year)
        sys.exit(0)
    except Exception as e:
        print(f'ERROR: {e}', file=sys.stderr)
        sys.exit(1)