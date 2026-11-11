"""Prepare official data without changing the original agent or evaluator."""
import ast
import csv
import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'reproduction'
SAMPLES = {'easy': 'e20241028160248698752', 'medium': 'e20241028160842228543',
           'human': 'h20241029143447759844'}


def normalize(row):
    result = dict(row)
    for field in ('days', 'people_number'):
        result[field] = int(result[field])
    for field in ('limit_rooms', 'limits_room_type'):
        if result[field] not in ('True', 'False'):
            raise ValueError(f'Invalid boolean field: {field}')
        result[field] = result[field] == 'True'
    codes = ast.literal_eval(result['hard_logic_py'])
    if not isinstance(codes, list) or not all(isinstance(x, str) for x in codes):
        raise ValueError('Expected a list of DSL programs')
    result['hard_logic_py'] = []
    for code in codes:
        # Published Phase 1 CSV stores literal backslash-n inside each program.
        try:
            compile(code, '<official-dsl>', 'exec')
        except SyntaxError:
            code = code.replace('\\n', '\n')
            compile(code, '<official-dsl>', 'exec')
        result['hard_logic_py'].append(code)
    return result


def fetch(url):
    with urllib.request.urlopen(url, timeout=90) as response:
        return response.read()


def save(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    raw = OUT / 'data'
    raw.mkdir(parents=True, exist_ok=True)
    manifest = {'datasets': {}, 'samples': [], 'normalization':
                'Safe literal parsing; numeric/bool conversion; restore escaped DSL newlines only when needed for syntax.'}
    revisions = {}
    for name in ('ChinaTravel', 'ChinaTravel-Sandbox'):
        meta = json.loads(fetch(f'https://huggingface.co/api/datasets/LAMDA-NeSy/{name}'))
        revisions[name] = meta['sha']
        manifest['datasets'][name] = {'revision': meta['sha']}
    sandbox_base = f'https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel-Sandbox/resolve/{revisions["ChinaTravel-Sandbox"]}/'
    release = json.loads(fetch(sandbox_base + 'release_manifest.json'))
    save(raw / 'sandbox_release_manifest.json', release)
    archive_path = 'raw/ChinaTravel_sandbox_zh.zip'
    archive = fetch(sandbox_base + archive_path)
    digest = hashlib.sha256(archive).hexdigest()
    if digest != release['files'][archive_path]['sha256']:
        raise ValueError('Sandbox archive checksum mismatch')
    (raw / 'ChinaTravel_sandbox_zh.zip').write_bytes(archive)
    destination = ROOT / 'chinatravel/environment'
    with zipfile.ZipFile(io.BytesIO(archive)) as z:
        for member in z.infolist():
            target = (destination / member.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError('Unsafe archive path')
        z.extractall(destination)
    manifest['datasets']['ChinaTravel-Sandbox'].update(release=release['release_version'], sha256=digest)
    for split, uid in SAMPLES.items():
        url = f'https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel/resolve/{revisions["ChinaTravel"]}/{split}.csv'
        payload = fetch(url)
        (raw / f'{split}.csv').write_bytes(payload)
        rows = list(csv.DictReader(io.StringIO(payload.decode('utf-8-sig'))))
        assert rows[0]['uid'] == uid, f'Unexpected first sample: {split}'
        record = normalize(rows[0])
        local_split = f'repro_{split}'
        query_path = ROOT / 'chinatravel/data' / local_split / f'{uid}.json'
        save(query_path, record)
        save(raw / f'{split}.json', record)
        split_path = ROOT / 'chinatravel/evaluation/default_splits' / f'{local_split}.txt'
        split_path.parent.mkdir(parents=True, exist_ok=True)
        split_path.write_text(uid + '\n', encoding='utf-8')
        manifest['samples'].append({'split': split, 'local_split': local_split, 'uid': uid,
                                    'csv_sha256': hashlib.sha256(payload).hexdigest(),
                                    'query_path': query_path.relative_to(ROOT).as_posix()})
        print(f'Prepared {split}: {uid}', flush=True)
    save(OUT / 'manifest.json', manifest)
    print(f'Sandbox checksum verified: {digest}', flush=True)


if __name__ == '__main__':
    main()
