import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))
from strict_cohort_draft import (CITIES, KINDS, CHAIN_KINDS, AUX_KINDS, INCLUDED_COSTS,
    BUDGET_CNY_TOTAL, PEOPLE, EXTRAS, TAG_ITEM_KIND, KIND_LABELS, generate)
from shorttrip.collection_task_schema import validate_cohort
from shorttrip.strict_tag_constraints import evaluate_tag_constraint


class StrictCohortDraftTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "catalog.sqlite3"
        con = sqlite3.connect(self.db)
        con.execute("CREATE TABLE records(id TEXT, city TEXT, kind TEXT, name TEXT)")
        rows = []
        for city in CITIES:
            for kind in KINDS:
                for n in range(6):
                    rows.append((f"{city}:{kind}:{n}", city, kind, f"label-{n}"))
        con.executemany("INSERT INTO records VALUES(?,?,?,?)", rows)
        con.commit()
        con.close()

    def tearDown(self):
        self.temp.cleanup()

    def test_draft_shape_counts_and_schema(self):
        data = generate(self.db)
        self.assertEqual(data["task_count"], 90)
        self.assertEqual(len(data["tasks"]), 90)
        self.assertEqual(data["artifact_status"], "DRAFT_ONLY_NOT_FORMALLY_FROZEN")
        self.assertEqual(data["supersedes_artifact"], "cohort_draft_v5.json")
        self.assertFalse(data["executable"])
        self.assertFalse(data["formal_freeze"])
        self.assertEqual(len({t["uid"] for t in data["tasks"]}), 90)
        self.assertTrue(validate_cohort(data["tasks"])["schema_ok"])
        self.assertEqual(sum(t["split"] == "development" for t in data["tasks"]), 60)
        self.assertEqual(sum(t["split"] == "holdout" for t in data["tasks"]), 30)

    def test_each_city_split_covers_all_kinds_and_ids_are_split_disjoint(self):
        data = generate(self.db)
        for city_info in data["split_design"]["kind_coverage_by_city"]:
            self.assertTrue(city_info["candidate_ids_disjoint_across_splits"])
            self.assertTrue(city_info["kind_coverage_by_split"])
            for split in ("development", "holdout"):
                counts = city_info["kind_coverage_by_split"][split]
                self.assertEqual(set(counts), set(KINDS))
                self.assertTrue(all(counts[k] > 0 for k in KINDS))
        for city in CITIES:
            for level in ("easy", "medium", "human"):
                cell = [t for t in data["tasks"] if t["start_city"] == city and t["level"] == level]
                self.assertEqual(sum(t["split"] == "development" for t in cell), 4)
                self.assertEqual(sum(t["split"] == "holdout" for t in cell), 2)

    def test_candidate_diversity_and_reuse_are_balanced_per_split(self):
        data = generate(self.db)
        for city in CITIES:
            for kind in KINDS:
                for split, expected_unique, expected_uses in (
                    ("development", 4 if kind in CHAIN_KINDS else None, 3 if kind in CHAIN_KINDS else 1),
                    ("holdout", 2 if kind in CHAIN_KINDS else None, 3 if kind in CHAIN_KINDS else 1),
                ):
                    tasks = [t for t in data["tasks"] if t["start_city"] == city and t["split"] == split
                             and kind in t["required_kinds"]]
                    ids = [t["generation"]["selected_entities_by_kind"][kind]["id"] for t in tasks]
                    if kind in CHAIN_KINDS:
                        self.assertEqual(len(set(ids)), expected_unique)
                        self.assertEqual(sorted(ids.count(i) for i in set(ids)), [expected_uses] * expected_unique)
                    else:
                        self.assertEqual(len(ids), len(set(ids)))
            city_info = next(x for x in data["split_design"]["kind_coverage_by_city"] if x["city"] == city)
            self.assertEqual(sum(city_info["unique_candidate_counts_by_split_and_kind"]["development"].values()), 24)
            self.assertEqual(sum(city_info["unique_candidate_counts_by_split_and_kind"]["holdout"].values()), 12)

    def test_core_pool_capacity_fails_closed(self):
        con = sqlite3.connect(self.db)
        con.execute("DELETE FROM records WHERE city=? AND kind=? AND id=(SELECT id FROM records WHERE city=? AND kind=? LIMIT 1)",
                    (CITIES[0], CHAIN_KINDS[0], CITIES[0], CHAIN_KINDS[0]))
        con.commit()
        con.close()
        with self.assertRaisesRegex(ValueError, "insufficient disjoint candidates"):
            generate(self.db)

    def test_business_chain_and_auxiliary_kind_are_in_language_and_structure(self):
        data = generate(self.db)
        for task in data["tasks"]:
            chain = task["generation"]["business_chain"]
            self.assertEqual([x["kind"] for x in chain], CHAIN_KINDS)
            required = task["required_kinds"]
            self.assertEqual(required[:3], CHAIN_KINDS)
            self.assertEqual(len(required), 4)
            self.assertEqual(required[3], task["generation"]["auxiliary_kind"])
            self.assertEqual(task["candidate_selection"]["required_entity_ids"],
                             [task["generation"]["selected_entities_by_kind"][k]["id"] for k in required])
            for kind in required:
                self.assertIn(task["generation"]["selected_entities_by_kind"][kind]["id"], task["nature_language"])

    def test_constraint_levels_budget_scope_and_language_agree(self):
        data = generate(self.db)
        for task in data["tasks"]:
            constraints = task["additional_constraints"]
            self.assertEqual(len(constraints), 1 if task["level"] == "easy" else 4)
            self.assertEqual(task["generation"]["logical_constraint_count"], len(constraints))
            budget = constraints[0]
            self.assertEqual(budget["strength"], "hard")
            self.assertEqual(budget["expression"]["op"], "total_cost_at_most")
            self.assertEqual(budget["expression"]["args"],
                {"CNY": BUDGET_CNY_TOTAL, "people": PEOPLE, "includes": INCLUDED_COSTS})
            for phrase in task["generation"]["constraint_phrases_for_audit"]:
                self.assertIn(phrase, task["nature_language"])
            for extra in constraints[1:]:
                expression, strength, quantifier, variants = EXTRAS[extra["id"]]
                self.assertEqual((extra["expression"], extra["strength"]), (expression, strength))
                expected_kind = TAG_ITEM_KIND[extra["id"]]
                self.assertEqual(extra["scope"], {"domain": "trip", "quantifier": quantifier,
                                                  "item_kind": expected_kind})
                self.assertTrue(any(phrase in task["nature_language"]
                                    for phrase in variants))
                phrase = next(p for p in variants if p in task["nature_language"])
                self.assertIn(KIND_LABELS[expected_kind], phrase)
                if quantifier == "any":
                    self.assertTrue("至少" in phrase)
                else:
                    self.assertTrue(any(word in phrase for word in ("所有", "每一项", "任何")))
                if extra["id"] == "rain_indoor":
                    self.assertTrue(any(word in phrase for word in ("下雨", "雨")))
                self.assertEqual(extra["compiler_status"], "unmapped")
        medium = [t for t in data["tasks"] if t["level"] == "medium"]
        self.assertTrue(all(3 <= len(t["additional_constraints"]) <= 5 for t in medium))
        human = [t for t in data["tasks"] if t["level"] == "human"]
        self.assertTrue(all({"rain_indoor", "exclude_night"}.issubset(
            {c["id"] for c in t["additional_constraints"]}) for t in human))
        self.assertTrue(all(t["task_origin"] == "synthetic_human_style" for t in human))
        self.assertGreater(len({t["nature_language"] for t in data["tasks"]}), 10)

    def test_generated_tag_expressions_match_strict_tag_evaluator_semantics(self):
        data = generate(self.db)
        for task in data["tasks"]:
            for constraint in task["additional_constraints"][1:]:
                op = constraint["expression"]["op"]
                if op == "conditional_prefer_tag":
                    key, value = next(iter(constraint["expression"]["args"]["if"].items()))
                    condition_facts = [{"key": key, "value": value, "scope": {"domain": "trip"}}]
                    pref_key, pref_value = next(iter(constraint["expression"]["args"]["prefer"].items()))
                    tag = f"{pref_key}:{pref_value}"
                else:
                    condition_facts = []
                    tag = constraint["expression"]["args"]["tag"]
                item_kind = constraint["scope"]["item_kind"]
                fact_scope = {"domain": "trip", "item_kind": item_kind}
                facts = [{"item_id": item, "item_kind": item_kind, "tag": tag,
                          "present": op != "exclude_tag", "scope": fact_scope}
                         for item in ("item-1", "item-2")]
                trusted = facts + condition_facts
                out = evaluate_tag_constraint(constraint, scope_items=["item-1", "item-2"],
                    tag_facts=facts, condition_facts=condition_facts,
                    fact_verifier=lambda _c, f: f in trusted,
                    scope_verifier=lambda c, items: (items == ["item-1", "item-2"]
                        and c["scope"]["item_kind"] == item_kind))
                self.assertNotEqual(out["state"], "unknown", (task["uid"], constraint, out))
                self.assertEqual(out["state"], "pass" if op == "exclude_tag" else "satisfied")

    def test_price_independence_and_transport_direction_stays_unknown(self):
        first = generate(self.db)
        con = sqlite3.connect(self.db)
        con.execute("ALTER TABLE records ADD COLUMN price INTEGER DEFAULT -999999")
        con.commit()
        con.close()
        second = generate(self.db)
        self.assertEqual(first["tasks"], second["tasks"])
        self.assertEqual(first["fixed_budget"]["amount"], BUDGET_CNY_TOTAL)
        for task in second["tasks"]:
            if {"train", "flight"} & set(task["required_kinds"]):
                self.assertIn("没有提供出发地和目的地", task["nature_language"])
                self.assertIn("不预设方向、线路", task["nature_language"])
            self.assertEqual(task["generation"]["feasibility_claim"], "not_checked")


if __name__ == "__main__":
    unittest.main(verbosity=2)
