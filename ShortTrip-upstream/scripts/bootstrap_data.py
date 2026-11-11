"""Fetch pinned official sandbox/input data; never calls a language model."""
import argparse
import hashlib
import json
from pathlib import Path
import urllib.request
import zipfile

ROOT=Path(__file__).resolve().parents[1]

def download(url,path):
    path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.part')
    with urllib.request.urlopen(url,timeout=120) as response,temporary.open('wb') as file:
        while block:=response.read(1024*1024):file.write(block)
    temporary.replace(path)

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--lang',choices=['zh','en','both'],default='zh')
    args=parser.parse_args()
    sources=json.loads((ROOT/'data_sources.json').read_text(encoding='utf-8'))
    cache=ROOT/'artifacts/downloads'
    revision=sources['ChinaTravel-Sandbox']['revision']
    base=f'https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel-Sandbox/resolve/{revision}/'
    release_path=cache/'release_manifest.json'
    download(base+'release_manifest.json',release_path)
    release=json.loads(release_path.read_text(encoding='utf-8'))
    destination=ROOT/'chinatravel/environment'
    for lang in (['zh','en'] if args.lang=='both' else [args.lang]):
        remote=f'raw/ChinaTravel_sandbox_{lang}.zip'
        archive=cache/Path(remote).name
        expected=release['files'][remote]['sha256']
        if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:
            download(base+remote,archive)
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:
            raise ValueError('Sandbox checksum mismatch: '+lang)
        with zipfile.ZipFile(archive) as zipped:
            for member in zipped.infolist():
                path=(destination/member.filename).resolve()
                if not path.is_relative_to(destination.resolve()):raise ValueError('Unsafe archive path')
            zipped.extractall(destination)
        print('Prepared verified sandbox: '+lang)
    queries_revision=sources['ChinaTravel']['revision']
    for split in ('easy','medium','human'):
        download(f'https://huggingface.co/datasets/LAMDA-NeSy/ChinaTravel/resolve/{queries_revision}/{split}.csv',ROOT/'reproduction/data'/f'{split}.csv')
    print('Official data ready. No model calls were made.')

if __name__=='__main__':main()
