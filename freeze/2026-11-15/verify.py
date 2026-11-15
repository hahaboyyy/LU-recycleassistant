"""Verify the frozen base files and optionally the non-secret live settings."""
import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[1]
args=argparse.ArgumentParser()
args.add_argument('--check-config',action='store_true')
options=args.parse_args()
rows=list(csv.DictReader((HERE/'files.sha256.csv').open(encoding='utf-8')))
errors=[]
for row in rows:
    path=(ROOT/row['path']).resolve()
    if not path.is_relative_to(ROOT) or not path.is_file():
        errors.append(row['path']);continue
    data=path.read_bytes()
    if row['representation']=='utf8_lf_without_bom':
        data=data.decode('utf-8-sig').replace('\r\n','\n').replace('\r','\n').encode('utf-8')
    digest=hashlib.sha256(data).hexdigest()
    if digest!=row['sha256']:errors.append(row['path'])
config_errors=[]
if options.check_config:
    sys.path[:0]=[str(ROOT),str(ROOT/'recognition/src')]
    os.environ.setdefault('RECO_ENV_FILE',str(ROOT/'.env'))
    from reco.config import load_config
    config=load_config()
    actual={key:getattr(config,key) for key in json.loads((HERE/'runtime_config.json').read_text(encoding='utf-8'))['recognition']}
    actual['timeout_s']=min(30.0,max(1.0,actual['timeout_s']))
    actual['max_retries']=min(1,max(0,actual['max_retries']))
    expected=json.loads((HERE/'runtime_config.json').read_text(encoding='utf-8'))
    config_errors=[key for key,value in expected['recognition'].items() if actual[key]!=value]
    backend=os.environ.get('RECYCLE_D_BACKEND','').strip()
    if backend!=expected['application']['backend']:config_errors.append('RECYCLE_D_BACKEND')
    try:timeout=float(os.environ.get('RECYCLE_D_TIMEOUT','35' if backend else '8'))
    except ValueError:timeout=None
    if timeout!=expected['application']['timeout_s']:config_errors.append('RECYCLE_D_TIMEOUT')
print(json.dumps({'files_checked':len(rows),'file_mismatches':errors,
                  'configuration_checked':options.check_config,'configuration_mismatches':config_errors,
                  'passed':not errors and not config_errors}))
raise SystemExit(1 if errors or config_errors else 0)
