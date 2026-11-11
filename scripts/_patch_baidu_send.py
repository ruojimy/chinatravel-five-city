"""Make the request URL and the signed string structurally identical.

`sign_query(uri, query, sk)` takes the *already-built* query string, so the client
cannot sign one spelling and send another (the failure mode that produced 211).
"""
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "src" / "shorttrip" / "dynamic" / "baidu.py"
text = TARGET.read_text(encoding="utf-8")

OLD_SIGN_HEAD = '''def sign(
    uri_path: str,
    params: dict,
    sk: str,
    *,
    algorithm: str = "md5_urlenc",
    mode: str = "java",
    with_host: bool = False,
    sort: bool = False,
) -> str:'''
NEW_SIGN_HEAD = '''def sign_query(uri_path: str, query: str, sk: str) -> str:
    """Sign an *already assembled* query string — the only safe way to do this.

    The caller builds `query` once and reuses it verbatim in the URL, so the
    digest can never describe a different string than the one Baidu receives.
    """
    return hashlib.md5(_quote_value(f"{uri_path}?{query}{sk}", "java").encode("utf-8")).hexdigest()


def sign(
    uri_path: str,
    params: dict,
    sk: str,
    *,
    algorithm: str = "md5_urlenc",
    mode: str = "java",
    with_host: bool = False,
    sort: bool = False,
) -> str:'''

OLD_SEND = '''    def _send(self, path: str, params: dict, style: str) -> tuple[dict, float]:
        """One signed GET. ``style == 'no_sn'`` deliberately sends AK only."""
        started = time.time()
        if style == "no_sn":
            url = f"{HOST}{path}?{canonical_query(params, 'pct')}"
        else:
            mode = "pct" if style == "pct_host" else style
            qs = canonical_query(params, mode)
            sn = sign(path, params, self.credentials.sk or "", mode=mode, with_host=(style == "pct_host"))
            url = f"{HOST}{path}?{qs}&sn={sn}"'''

NEW_SEND = '''    def _send(self, path: str, params: dict, style: str) -> tuple[dict, float]:
        """One GET. ``style == 'no_sn'`` deliberately sends AK only (diagnostic)."""
        started = time.time()
        sort = style.endswith("_sorted")
        qs = canonical_query(params, "java", sort=sort)
        if style == "no_sn":
            url = f"{HOST}{path}?{qs}"
        elif style.startswith("md5_query_only"):
            sn = sign(path, params, self.credentials.sk or "", algorithm="md5_query_only", sort=sort)
            url = f"{HOST}{path}?{qs}&sn={sn}"
        elif style in ("md5_urlenc", "md5_urlenc_sorted"):
            sn = sign_query(path, qs, self.credentials.sk or "")
            url = f"{HOST}{path}?{qs}&sn={sn}"
        elif style == "md5_raw":
            sn = sign(path, params, self.credentials.sk or "", algorithm="md5_raw", sort=sort)
            url = f"{HOST}{path}?{qs}&sn={sn}"
        else:
            raise ValueError(f"unknown signature style: {style}")'''

OLD_ORDER = '''        base = self._base_params(probe_params or {"q": "广州塔", "region": "广州", "page_size": 1})
        order = ["no_sn"] + list(QUERY_MODES) + ["pct_host"]'''
NEW_ORDER = '''        base = self._base_params(probe_params or {"q": "广州塔", "region": "广州", "page_size": 1})
        order = ["md5_urlenc", "no_sn", "md5_raw", "md5_query_only", "md5_urlenc_sorted"]'''

OLD_ATTEMPTS = '''        style = self._signature_style or (os.environ.get("BAIDU_SIGN_STYLE") or "pct")
        attempts = [style] + [s for s in (["no_sn"] + list(QUERY_MODES) + ["pct_host"]) if s != style]'''
NEW_ATTEMPTS = '''        style = self._signature_style or os.environ.get("BAIDU_SIGN_STYLE") or "md5_urlenc"
        attempts = [style] + [
            s for s in ("md5_urlenc", "no_sn", "md5_raw", "md5_query_only", "md5_urlenc_sorted") if s != style
        ]'''

for old, new in (
    (OLD_SIGN_HEAD, NEW_SIGN_HEAD),
    (OLD_SEND, NEW_SEND),
    (OLD_ORDER, NEW_ORDER),
    (OLD_ATTEMPTS, NEW_ATTEMPTS),
):
    if old not in text:
        raise SystemExit(f"anchor not found:\n{old[:160]}")
    text = text.replace(old, new, 1)

TARGET.write_text(text, encoding="utf-8")
print("url/signature unification patch applied")
