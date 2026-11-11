"""Order-sensitivity fix for the Baidu SN signer.

Finding (falsifiable, from Baidu's own sample URL
`/geocoder/v2/?address=..&output=json&ak=..`): the string that gets MD5'd uses the
parameters in the order they appear in the URL, *not* alphabetically. Sorting the
query before signing therefore produces a different digest than sorting used in
the sample. The client now builds one query string and uses it verbatim for both
the signature and the request, so the two can never diverge.
"""
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "src" / "shorttrip" / "dynamic" / "baidu.py"
text = TARGET.read_text(encoding="utf-8")

OLD_QUERY = '''def canonical_query(params: dict, mode: str = "java") -> str:
    """``a=1&b=2``, keys ascending — byte-for-byte what the request URL carries."""
    items = sorted(((str(k), v) for k, v in params.items() if k != "sn"), key=lambda kv: kv[0])
    return "&".join(f"{key}={_quote_value(value, mode)}" for key, value in items)
'''

NEW_QUERY = '''def canonical_query(params: dict, mode: str = "java", *, sort: bool = False) -> str:
    """``a=1&b=2`` — byte-for-byte what the request URL carries.

    ``sort=False`` (default) preserves insertion order, because Baidu signs the
    parameters *in URL order*. Sorting is available for accounts/clients that
    prefer alphabetical queries, but the very same string must then be sent.
    """
    items = [(str(k), v) for k, v in params.items() if k != "sn"]
    if sort:
        items.sort(key=lambda kv: kv[0])
    return "&".join(f"{key}={_quote_value(value, mode)}" for key, value in items)
'''

OLD_SIGN = '''def sign(
    uri_path: str,
    params: dict,
    sk: str,
    *,
    algorithm: str = "md5_urlenc",
    mode: str = "java",
    with_host: bool = False,
) -> str:
    """Return Baidu's ``sn`` for one request. Default algorithm is the official one."""
    prefix = HOST if with_host else ""
    whole = f"{prefix}{uri_path}?{canonical_query(params, mode)}{sk}"'''

NEW_SIGN = '''def sign(
    uri_path: str,
    params: dict,
    sk: str,
    *,
    algorithm: str = "md5_urlenc",
    mode: str = "java",
    with_host: bool = False,
    sort: bool = False,
) -> str:
    """Return Baidu's ``sn`` for one request. Default algorithm is the official one."""
    prefix = HOST if with_host else ""
    whole = f"{prefix}{uri_path}?{canonical_query(params, mode, sort=sort)}{sk}"'''

OLD_VAR = '''def sign_variants(uri_path: str, params: dict, sk: str) -> dict[str, str]:
    """Every candidate, so a probe failure is diagnosable instead of mysterious."""
    out: dict[str, str] = {}
    for algorithm in SIGN_ALGORITHMS:
        out[algorithm] = sign(uri_path, params, sk, algorithm=algorithm)
    out["legacy_pct"] = sign(uri_path, params, sk, algorithm="md5_raw", mode="pct")
    out["pct_host"] = sign(uri_path, params, sk, algorithm="md5_raw", mode="pct", with_host=True)
    return out
'''

NEW_VAR = '''def sign_variants(uri_path: str, params: dict, sk: str) -> dict[str, str]:
    """Every candidate, so a probe failure is diagnosable instead of mysterious."""
    out: dict[str, str] = {}
    for algorithm in SIGN_ALGORITHMS:
        out[algorithm] = sign(uri_path, params, sk, algorithm=algorithm)
    out["md5_urlenc_sorted"] = sign(uri_path, params, sk, algorithm="md5_urlenc", sort=True)
    out["legacy_pct"] = sign(uri_path, params, sk, algorithm="md5_raw", mode="pct")
    return out
'''

OLD_ST = '''    vector = SN_TEST_VECTOR
    got = sign(vector["uri"], vector["params"], vector["sk"], algorithm="md5_urlenc")'''
NEW_ST = '''    vector = SN_TEST_VECTOR
    got = sign(vector["uri"], vector["params"], vector["sk"], algorithm="md5_urlenc", sort=False)'''

OLD_SELF_RET = '''    return {
        "ok": got == vector["expect"],
        "expected": vector["expect"],
        "got": got,
        "uri": vector["uri"],
        "params": vector["params"],
        "algorithm": "md5_urlenc",
    }'''
NEW_SELF_RET = '''    signed_string = _quote_value(
        f'{vector["uri"]}?{canonical_query(vector["params"], "java")}{vector["sk"]}', "java"
    )
    return {
        "ok": got == vector["expect"],
        "expected": vector["expect"],
        "got": got,
        "algorithm": "md5_urlenc",
        "signed_string": signed_string,
        "note": "参数按 URL 出现顺序参与签名（官方样例即如此），不是字母序",
    }'''

for old, new in ((OLD_QUERY, NEW_QUERY), (OLD_SIGN, NEW_SIGN), (OLD_VAR, NEW_VAR), (OLD_ST, NEW_ST), (OLD_SELF_RET, NEW_SELF_RET)):
    if old not in text:
        raise SystemExit(f"anchor not found:\n{old[:120]}")
    text = text.replace(old, new, 1)

TARGET.write_text(text, encoding="utf-8")
print("order-sensitivity patch applied")
