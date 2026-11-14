"""Freeze and run the existing E protocol against the current integrated system."""
import argparse
import base64
import csv
import hashlib
import importlib.metadata
import json
import os
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1]
ROOT = SOURCE.parent
OUT = ROOT / '实验结果' / 'formal60_2026-11-15'

def now():
    return datetime.now(timezone.utc).isoformat()

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def append(path, value):
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False) + '\n')

def write_csv(path, rows):
    with path.open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

def prepare():
    if OUT.resolve().is_relative_to(SOURCE.resolve()):
        raise ValueError('Choose an output directory outside the source tree for a frozen run.')
    if OUT.exists():
        raise FileExistsError('Experiment directory already exists; do not overwrite frozen evidence.')
    OUT.mkdir(parents=True)
    snapshot = OUT / 'source_snapshot'
    shutil.copytree(SOURCE, snapshot, ignore=shutil.ignore_patterns(
        '.env', 'secrets.toml', '.venv', '.git', '.pytest_cache', '__pycache__', 'runs', 'results', '*.pyc'))
    shutil.copy2(__file__, OUT / 'run_formal60.py')
    save(OUT / 'acceptance_criteria.json', {'declared_before_run': True, 'threshold': 0.9, 'request_success_denominator': 60, 'photo_item_accuracy_denominator': 48, 'primary_gate': 'Report usable recognition and clear-supported photo-only item accuracy separately; no failures removed.', 'extra_user_information': 'Report assisted results separately from photo-only metrics.'})
    shutil.copy2(SOURCE / 'evaluation/SCORING_RUBRIC.md', OUT / 'SCORING_RUBRIC.md')
    files = [{'path': p.relative_to(snapshot).as_posix(), 'sha256': sha(p), 'bytes': p.stat().st_size}
             for p in sorted(snapshot.rglob('*')) if p.is_file()]
    write_csv(OUT / 'snapshot_manifest.csv', files)
    identity = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
    save(OUT / 'snapshot_metadata.json', {
        'created_at_utc': now(), 'source_directory': str(SOURCE),
        'snapshot_revision': 'sha256:' + identity, 'file_count': len(files),
        'snapshot_contains_api_key': False,
        'reference_acceptance': 'Use E images and reference answers as accepted by the user in this conversation. Original a_review fields are preserved; this is not a new A signature.',
    })
    print(json.dumps({'output': str(OUT), 'files': len(files), 'revision': identity}), flush=True)

def initialize():
    snapshot = OUT / 'source_snapshot'
    sys.path[:0] = [str(snapshot), str(snapshot / 'recognition/src')]
    os.environ['RECO_ENV_FILE'] = str(SOURCE / '.env')
    os.environ['RECO_LOG'] = str(OUT / 'recognition_calls.jsonl')
    os.environ['RECO_CATALOGUE'] = str(snapshot / 'data/supported_items.csv')
    from integration import live_recognizer
    from evaluation import evaluate_systems as protocol
    import evaluation_adapter
    rec = live_recognizer()
    if rec.cfg.provider in ('mock', 'fixture'):
        raise ValueError('A real provider is required.')
    cases = protocol.manifest()
    protocol.validate(cases)
    photos, problems = protocol.check_photos(cases)
    accepted_metadata = [problem for problem in problems if problem.endswith(': needs A approval')]
    other_problems = [problem for problem in problems if problem not in accepted_metadata]
    preflight = {'cases': len(cases), 'ready_photos': len(photos), 'blocking_problems': other_problems,
                 'legacy_review_metadata': accepted_metadata,
                 'review_handling': 'User accepted E references; preserve the original pending fields and record that acceptance separately.'}
    save(OUT / 'preflight.json', preflight)
    if other_problems or len(photos) != 60:
        raise ValueError('Dataset preflight failed; see preflight.json.')
    safe_config = {key: value for key, value in vars(rec.cfg).items() if key != 'api_key'}
    safe_config['api_key_present'] = bool(rec.cfg.api_key)
    save(OUT / 'model_config.json', safe_config)
    write_csv(OUT / 'dataset_manifest.csv', [
        {'case_id': case['case_id'], 'case_type': case['case_type'], 'image_path': case['image_path'],
         'image_sha256': photos[case['case_id']]['sha256'],
         'expected_initial_action': case['expected_initial_action'], 'expected_final_action': case['expected_final_action'],
         'expected_final_item_id': case['expected_final_item_id']}
        for case in cases])
    return rec, protocol, evaluation_adapter, cases, photos

def run():
    rec, protocol, adapter, cases, photos = initialize()
    if (OUT / 'run.jsonl').exists():
        raise FileExistsError('Raw run already exists; evidence is never overwritten.')
    snapshot_meta = json.loads((OUT / 'snapshot_metadata.json').read_text(encoding='utf-8'))
    context = {}
    original_send = rec.client._send
    secret = rec.cfg.api_key
    consecutive_transport_errors = 0

    def redact(value):
        if isinstance(value, str):
            return value.replace(secret, '[REDACTED]') if secret else value
        if isinstance(value, list):
            return [redact(x) for x in value]
        if isinstance(value, dict):
            return {k: redact(v) for k, v in value.items() if k.lower() not in ('authorization', 'api_key')}
        return value

    def safe_payload(payload):
        result = json.loads(json.dumps(payload))
        for message in result.get('messages', []):
            if not isinstance(message.get('content'), list):
                continue
            for part in message['content']:
                if part.get('type') == 'image_url':
                    url = part['image_url']['url']
                    if url.startswith('data:'):
                        prefix, encoded = url.split(',', 1)
                        raw = base64.b64decode(encoded)
                        part['image_url'] = {'media_type': prefix.split(';')[0][5:], 'bytes': len(raw),
                                             'sha256': hashlib.sha256(raw).hexdigest()}
        return redact(result)

    def audited_send(payload):
        nonlocal consecutive_transport_errors
        started = time.monotonic()
        entry = {'started_at_utc': now(), **context, 'request': safe_payload(payload)}
        try:
            status, headers, body = original_send(payload)
            try:
                response = json.loads(body)
            except ValueError:
                response = body
            entry.update(http_status=status, response=redact(response))
            if status in (401, 402, 403, 404):
                entry['fatal_configuration_error'] = True
            consecutive_transport_errors = 0
            return status, headers, body
        except Exception as error:
            consecutive_transport_errors += 1
            entry.update(error_type=type(error).__name__, error_code=getattr(error, 'code', ''), error=redact(str(error)))
            raise
        finally:
            entry.update(finished_at_utc=now(), elapsed_ms=round((time.monotonic()-started)*1000, 2))
            append(OUT / 'provider_responses.jsonl', entry)
            if entry.get('fatal_configuration_error') or consecutive_transport_errors >= 4:
                raise SystemExit('Provider configuration/network failed repeatedly. Raw evidence has been preserved.')

    rec.client._send = audited_send
    adapter._recognizer = lambda: rec
    original_predict = adapter.predict

    def predict(*, mode, image_path, history):
        context.update(case_id=Path(image_path).stem, mode=mode,
                       phase='followup' if history else 'initial', history_length=len(history))
        result = original_predict(mode=mode, image_path=image_path, history=history)
        if mode == 'improved' and not history and adapter._previous:
            append(OUT / 'recognition_records.jsonl', {
                'case_id': context['case_id'], 'record': adapter._previous[1].model_dump()})
        return result

    import types
    audited = types.ModuleType('formal_audited_adapter')
    audited.predict = predict
    sys.modules[audited.__name__] = audited
    revision = snapshot_meta['snapshot_revision']
    args = argparse.Namespace(adapter='formal_audited_adapter:predict', out=OUT, model=rec.cfg.model,
                              baseline_revision=revision + ':direct', improved_revision=revision + ':integrated', seed=521)
    package_names = ('streamlit', 'Pillow', 'pydantic', 'requests', 'numpy', 'pandas')
    save(OUT / 'experiment_metadata.json', {
        'started_at_utc': now(), 'python': sys.version, 'snapshot_revision': revision,
        'model': rec.cfg.model, 'provider': rec.cfg.provider, 'seed': args.seed,
        'packages': {name: importlib.metadata.version(name) for name in package_names},
        'arms': list(protocol.ARMS), 'case_order': 'seeded shuffle; baseline/improved order also shuffled',
        'interactive_protocol': 'Primary ordered E answers, at most two rounds. Separate by-key replay can reorder existing answers only; it never invents missing answers.',
        'reference_acceptance': snapshot_meta['reference_acceptance'],
        'raw_provider_responses': 'provider_responses.jsonl; request images represented by content hashes, not base64',
    })
    print(json.dumps({'start': now(), 'model': rec.cfg.model, 'cases': len(cases), 'expected_initial_model_calls': 120}), flush=True)
    protocol.run(args, cases, photos)
    protocol.grade_sheet(OUT, cases)
    shutil.copy2(OUT / 'per_case.csv', OUT / 'per_case_unreviewed.csv')
    metadata = json.loads((OUT / 'experiment_metadata.json').read_text(encoding='utf-8'))
    metadata['finished_at_utc'] = now()
    metadata['status'] = 'predictions_complete_scoring_pending'
    save(OUT / 'experiment_metadata.json', metadata)
    print(json.dumps({'completed': 60, 'case_arm_records': 180, 'output': str(OUT)}), flush=True)

if __name__ == '__main__':
    command = argparse.ArgumentParser()
    command.add_argument('action', choices=('prepare', 'preflight', 'run'))
    command.add_argument('--out', type=Path)
    args = command.parse_args()
    if args.out:
        OUT = args.out.resolve()
    if args.action == 'prepare':
        prepare()
    elif args.action == 'preflight':
        rec, _, _, cases, photos = initialize()
        print(json.dumps({'model': rec.cfg.model, 'endpoint': rec.cfg.base_url, 'key_present': bool(rec.cfg.api_key),
                          'cases': len(cases), 'photos': len(photos), 'timeout': rec.cfg.timeout_s, 'max_retries': rec.cfg.max_retries}), flush=True)
    else:
        run()
