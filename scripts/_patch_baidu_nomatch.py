"""Clean up the 'no confident match' branch: keep the rejected candidates as
structured, auditable evidence instead of the hasattr hack."""
from pathlib import Path

TARGET = Path(__file__).resolve().parents[1] / "src" / "shorttrip" / "dynamic" / "baidu.py"
text = TARGET.read_text(encoding="utf-8")

OLD = '''        if chosen is None:
            return Evidence(
                self.name, url, at, name, "", ok=False,
                error=f"no confident match (best score {attempts[-1]['top'][0]['score'] if attempts and attempts[-1].get('top') else 'n/a'})",
                authority=self.authority,
            )._with_attempts(attempts) if hasattr(Evidence, "_with_attempts") else Evidence(
                self.name, url, at, name, "", ok=False,
                error="no confident match",
                authority=self.authority,
            )
'''

NEW = '''        if chosen is None:
            best = 0.0
            for attempt in attempts:
                for verdict_row in attempt.get("top") or []:
                    best = max(best, float(verdict_row.get("score") or 0.0))
            return Evidence(
                self.name, url, at, name, "", ok=False,
                structured={
                    "requested_name": name,
                    "region": city,
                    "name_match": False,
                    "candidate_score": round(best, 3),
                    "query_attempts": attempts,
                },
                error=f"no confident match (best candidate score {best:.3f} < {self.MIN_SCORE})",
                authority=self.authority,
            )
'''

assert OLD in text
text = text.replace(OLD, NEW, 1)
TARGET.write_text(text, encoding="utf-8")
print("no-match branch cleaned")
