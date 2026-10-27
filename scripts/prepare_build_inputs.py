"""Restore only the byte-pinned public plan. No app startup, network or database."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from app.packed_plan import restore_plan, APPROVED_SHA256, APPROVED_BYTES


def prepare(output):
    source = ROOT / 'build_inputs/revision6'
    contract = json.loads((source / 'inputs.json').read_text(encoding='utf-8'))
    if (contract['uncompressed_sha256'] != APPROVED_SHA256
            or contract['uncompressed_bytes'] != APPROVED_BYTES):
        raise ValueError('PUBLIC_PLAN_CONTRACT_DIFFERS')
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('NEW_BUILD_INPUT_DIRECTORY_REQUIRED')
    output.mkdir(parents=True)
    storage = {'schema': 'sigra-pinned-gzip-plan-v1', 'file': 'release/plan.json.gz',
               'compressed_sha256': contract['compressed_sha256'],
               'uncompressed_sha256': contract['uncompressed_sha256'],
               'uncompressed_bytes': contract['uncompressed_bytes']}
    restore_plan(source / contract['file'], output / 'plan.json', storage,
                 APPROVED_SHA256, contract['compressed_sha256'])
    decision = source / 'coverage-decision.json'
    if hashlib.sha256(decision.read_bytes()).hexdigest() != contract['decision_sha256']:
        raise ValueError('HISTORICAL_COVERAGE_DECISION_CHANGED')
    shutil.copyfile(decision, output / 'coverage-decision.json')
    return {'SIGRA_REVISION6_BUNDLE': str(output),
            'SIGRA_REVISION6_DECISION': str(output / 'coverage-decision.json'),
            'SIGRA_REVISION6_FIXTURE_MODE': 'pinned-runtime-plan-v1'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--github-env', type=Path)
    args = parser.parse_args()
    values = prepare(args.output)
    if args.github_env:
        with args.github_env.open('a', encoding='utf-8') as stream:
            for name, value in values.items():
                stream.write(f'{name}={value}\n')
    print(json.dumps({'status': 'PUBLIC_BUILD_INPUTS_VERIFIED', 'environment': values}))
