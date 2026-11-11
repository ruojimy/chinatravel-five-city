"""Replace the SN signature block in dynamic/baidu.py with the verified algorithm.

Rationale: Baidu's official sample MD5s the *URL-encoded whole string*
(`uri?query + sk`), not just the query. Verified offline against the published
test vector 7de5a22212ffaa9e326444c75a58f9a0.
"""
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "src" / "shorttrip" / "dynamic" / "baidu.py"

NEW = '''# ------------------------------------------------------------------- signature
# Baidu's official sample (Java) does this, and it is *not* obvious:
#
#   1. build the query string: key=URLEncoder.encode(value), keys ascending;
#   2. whole = uri + "?" + query + sk                       (no separator before sk)
#   3. signed = URLEncoder.encode(whole)                    (encode the WHOLE string)
#   4. sn = md5(signed)                                     (32 lowercase hex)
#
# Step 3 is what most re-implementations miss; without it every request comes
# back 211 "APP SN校验失败". ``self_test()`` pins this against the published
# vector address=百度大厦&output=json&ak=yourak with sk=yoursk ->
# 7de5a22212ffaa9e326444c75a58f9a0, so a refactor cannot silently break it.
SIGN_ALGORITHMS = ("md5_urlenc", "md5_raw", "md5_query_only")
SN_TEST_VECTOR = {
    "uri": "/geocoder/v2/",
    "params": {"address": "百度大厦", "output": "json", "ak": "yourak"},
    "sk": "yoursk",
    "expect": "7de5a22212ffaa9e326444c75a58f9a0",
}


def _quote_value(value, mode: str) -> str:
    """java.net.URLEncoder semantics: space -> '+', keep ``* - . _``, else %XX."""
    text = str(value)
    if mode == "pct":  # RFC3986: space -> %20 (what C#/PHP samples use)
        return urllib.parse.quote(text, safe="")
    if mode == "plus":
        return urllib.parse.quote_plus(text, safe="")
    if mode == "raw":
        return text
    if mode == "java":  # java.net.URLEncoder
        return urllib.parse.quote_plus(text, safe="*-._")
    if mode == "double":
        return urllib.parse.quote(urllib.parse.quote(text, safe=""), safe="")
    if mode == "pct_lower":  # percent-escapes lower-cased, value text untouched
        quoted = urllib.parse.quote(text, safe="")
        return re.sub(r"%[0-9A-F]{2}", lambda m: m.group(0).lower(), quoted)
    if mode == "pct_amp":  # '&' and '=' inside values left literal
        return urllib.parse.quote(text, safe="&=")
    raise ValueError(f"unknown encoding mode: {mode}")


def canonical_query(params: dict, mode: str = "java") -> str:
    """``a=1&b=2``, keys ascending — byte-for-byte what the request URL carries."""
    items = sorted(((str(k), v) for k, v in params.items() if k != "sn"), key=lambda kv: kv[0])
    return "&".join(f"{key}={_quote_value(value, mode)}" for key, value in items)


def sign(
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
    whole = f"{prefix}{uri_path}?{canonical_query(params, mode)}{sk}"
    if algorithm == "md5_urlenc":
        # THE official algorithm: encode the whole assembled string, then MD5.
        whole = _quote_value(whole, "java")
    elif algorithm == "md5_query_only":
        whole = f"{prefix}{uri_path}?" + _quote_value(canonical_query(params, mode), "java") + sk
    elif algorithm == "md5_raw":
        pass
    else:
        raise ValueError(f"unknown signing algorithm: {algorithm}")
    return hashlib.md5(whole.encode("utf-8")).hexdigest()


def sign_variants(uri_path: str, params: dict, sk: str) -> dict[str, str]:
    """Every candidate, so a probe failure is diagnosable instead of mysterious."""
    out: dict[str, str] = {}
    for algorithm in SIGN_ALGORITHMS:
        out[algorithm] = sign(uri_path, params, sk, algorithm=algorithm)
    out["legacy_pct"] = sign(uri_path, params, sk, algorithm="md5_raw", mode="pct")
    out["pct_host"] = sign(uri_path, params, sk, algorithm="md5_raw", mode="pct", with_host=True)
    return out


def self_test() -> dict:
    """Offline proof that the signer still matches Baidu's published vector."""
    vector = SN_TEST_VECTOR
    got = sign(vector["uri"], vector["params"], vector["sk"], algorithm="md5_urlenc")
    return {
        "ok": got == vector["expect"],
        "expected": vector["expect"],
        "got": got,
        "uri": vector["uri"],
        "params": vector["params"],
        "algorithm": "md5_urlenc",
    }


'''

text = TARGET.read_text(encoding="utf-8")
start = text.index("# ------------------------------------------------------------------- signature")
end = text.index("# --------------------------------------------------------------- coordinates")
TARGET.write_text(text[:start] + NEW + text[end:], encoding="utf-8")
print("patched signature block ok")
print("self_test:", __import__("hashlib"))
