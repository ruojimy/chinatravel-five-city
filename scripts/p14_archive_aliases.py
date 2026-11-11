"""Repeat exact historical-name matching with explicit traditional normalization.

No fuzzy matching, no network, no change to the P13 archive/observed clocks.
"""
from pathlib import Path
import sys
from opencc import OpenCC
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'scripts'))
import p13_extract_archive as prior
original=prior.name_aliases
converter=OpenCC('t2s')
def normalized_aliases(value):
    return original(value)|original(converter.convert(value or ''))
if __name__=='__main__':
    prior.OUT=ROOT/'results/p14_targeted_completion'
    prior.OUT.mkdir(exist_ok=True)
    if (prior.OUT/'archive_enrichment.jsonl.gz').exists():raise FileExistsError('Preserve the recorded derivative')
    prior.name_aliases=normalized_aliases
    prior.main()
