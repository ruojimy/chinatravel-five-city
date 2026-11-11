from __future__ import annotations
import argparse, csv, hashlib, json, pathlib, sys
from collections import Counter, defaultdict
if hasattr(sys.stdout, "reconfigure"): sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = pathlib.Path(__file__).resolve().parents[1]
CT_ROOT = ROOT / "ChinaTravel"
DATA = CT_ROOT / "chinatravel" / "data"
PROTOCOL = ROOT / "results" / "luna_tencity_20261106" / "protocol"
SPLITS = ("easy", "medium", "human")
ORACLE_FIELDS = {"hard_logic", "hard_logic_py", "hard_logic_nl"}
CITIES = ("北京", "上海", "南京", "苏州", "杭州", "深圳", "成都", "武汉", "广州", "重庆")
CHECKER_PATHS = (
    "chinatravel/evaluation/schema_constraint.py",
    "chinatravel/evaluation/commonsense_constraint.py",
    "chinatravel/evaluation/hard_constraint.py",
    "chinatravel/evaluation/output_schema.json",
    "chinatravel/evaluation/utils.py",
    "chinatravel/symbol_verification/commonsense_constraint.py",
    "chinatravel/symbol_verification/hard_constraint.py",
)
def sha(data: bytes) -> str: return hashlib.sha256(data).hexdigest()
def canonical(obj) -> bytes: return json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(",",":")).encode("utf-8")
def checker_hashes(): return {p:sha((CT_ROOT/p).read_bytes()) for p in CHECKER_PATHS}

def load_cohort():
    rows=[]
    for split in SPLITS:
        for path in sorted((DATA/split).glob("*.json")):
            raw=path.read_bytes(); d=json.loads(raw.decode("utf-8"))
            if d.get("uid")!=path.stem: raise ValueError(f"UID/file mismatch: {path}")
            participant={k:v for k,v in d.items() if k not in ORACLE_FIELDS}
            rows.append({"split":split,"uid":d["uid"],"source":path.relative_to(ROOT).as_posix(),
              "source_sha256":sha(raw),"participant_input_sha256":sha(canonical(participant)),
              "start_city":d.get("start_city"),"target_city":d.get("target_city"),"days":d.get("days"),
              "_private_oracle":d.get("hard_logic_py",[]),"_participant":participant})
    return rows

def public_item(r): return {k:v for k,v in r.items() if not k.startswith("_")}
def freeze():
    rows=load_cohort(); split_counts=Counter(r["split"] for r in rows)
    if split_counts!={"easy":300,"medium":150,"human":154}: raise SystemExit(f"Unexpected counts: {dict(split_counts)}")
    for r in rows:
        if r["start_city"] not in CITIES or r["target_city"] not in CITIES: raise SystemExit(f"Out-of-cohort city: {r['uid']}")
    city_counts={s:{axis:dict(sorted(Counter(r[axis+"_city"] for r in rows if r["split"]==s).items())) for axis in ("start","target")} for s in SPLITS}
    day_counts={s:dict(sorted(Counter(r["days"] for r in rows if r["split"]==s).items())) for s in SPLITS}
    manifest={"protocol":"luna_tencity_20261106_v1","created_date":"2026-11-06","source":"local vendored ChinaTravel data directories",
      "cohort_count":len(rows),"split_counts":dict(split_counts),"cities":list(CITIES),"city_counts":city_counts,"day_counts":day_counts,
      "checker_sha256":checker_hashes(),"items":[public_item(r) for r in rows]}
    out=PROTOCOL/"manifest.json"; encoded=json.dumps(manifest,ensure_ascii=False,indent=2).encode("utf-8")+b"\n"
    if out.exists():
        if out.read_bytes()!=encoded: raise SystemExit("Frozen manifest exists and differs; refusing overwrite")
        print(f"Frozen manifest verified unchanged: {out}"); return
    out.parent.mkdir(parents=True,exist_ok=True); out.write_bytes(encoded)
    print(json.dumps({"manifest":str(out),"N":len(rows),"splits":dict(split_counts),"schema_sha256":manifest["checker_sha256"]["chinatravel/evaluation/output_schema.json"],"city_counts":city_counts,"day_counts":day_counts},ensure_ascii=False,indent=2))

def evaluate(response_path: pathlib.Path, out_prefix: pathlib.Path, arm: str):
    sys.path.insert(0,str(CT_ROOT))
    from chinatravel.evaluation.schema_constraint import evaluate_schema_constraints
    import chinatravel.symbol_verification.commonsense_constraint as cc
    from chinatravel.symbol_verification.hard_constraint import evaluate_constraints_py, _set_tool_lang
    manifest=json.loads((PROTOCOL/"manifest.json").read_text(encoding="utf-8"))
    if checker_hashes()!=manifest["checker_sha256"]: raise SystemExit("Official checker/schema hash drift from frozen manifest")
    source=load_cohort(); frozen={r["uid"]:r for r in manifest["items"]}
    if len(source)!=manifest["cohort_count"] or any(r["uid"] not in frozen or r["source_sha256"]!=frozen[r["uid"]]["source_sha256"] for r in source):
        raise SystemExit("Source dataset drift from frozen manifest")
    responses={}; duplicates=[]
    for no,line in enumerate(response_path.read_text(encoding="utf-8-sig").splitlines(),1):
        if not line.strip(): continue
        try: item=json.loads(line)
        except Exception: item={"uid":f"__malformed_line_{no}","arm":arm,"status":"error"}
        uid=item.get("uid")
        if uid not in frozen: continue
        if uid in responses:
            duplicates.append(uid); responses[uid]={"uid":uid,"arm":arm,"status":"malformed"}
        else: responses[uid]=item
    if any(x.get("arm") not in (None,arm) for x in responses.values()): raise SystemExit("Response arm mismatch")
    schema=json.loads((CT_ROOT/"chinatravel/evaluation/output_schema.json").read_text(encoding="utf-8"))
    checks=[cc.Is_activity_grounded,cc.Is_intercity_transport_correct,cc.Is_attractions_correct,cc.Is_hotels_correct,cc.Is_restaurants_correct,cc.Is_transport_correct,cc.Is_time_correct,cc.Is_space_correct]
    rows=[]; status_counts=Counter(); per=defaultdict(Counter); evaluator_errors=Counter(); hard_den=hard_pass_den=0
    for r in source:
        uid=r["uid"]; item=responses.get(uid); status=(item or {}).get("status","missing")
        if status=="ok" and not isinstance((item or {}).get("plan"),dict): status="malformed"
        plan=(item or {}).get("plan") if status=="ok" else None
        schema_ok=common_ok=hard_ok=False; common_groups=0; hard_n=len(r["_private_oracle"]); hard_pass=0
        if plan is not None:
            try: _,_,ids=evaluate_schema_constraints([uid],{uid:plan},schema); schema_ok=uid in ids
            except Exception: evaluator_errors["schema"]+=1
            try:
                q=r["_participant"]; cc._set_tool_lang("zh")
                for fn in checks:
                    table,_=fn(q,plan,verbose=False)
                    vals=[v for c,v in table.iloc[0].items() if c!="data_id"]
                    if vals and all(v==0 for v in vals): common_groups+=1
                common_ok=(common_groups==len(checks))
            except Exception: evaluator_errors["commonsense"]+=1; common_groups=0
            try:
                _set_tool_lang("zh"); result=evaluate_constraints_py(r["_private_oracle"],plan,verbose=False)
                hard_pass=sum(bool(v) for v in result); hard_ok=(hard_n>0 and hard_pass==hard_n)
            except Exception: evaluator_errors["hard_logic"]+=1; hard_pass=0
        status_counts[status]+=1; hard_den+=hard_n; hard_pass_den+=hard_pass
        three=bool(schema_ok and common_ok and hard_ok)
        row={"uid":uid,"split":r["split"],"target_city":r["target_city"],"status":status,"schema_pass":int(schema_ok),"commonsense_pass":int(common_ok),
             "commonsense_function_groups_pass":common_groups,"hard_pass":int(hard_ok),"hard_clause_passes":hard_pass,"hard_clause_count":hard_n,"three_gate_pass":int(three)}
        rows.append(row)
        for key,val in (("N",1),("schema_pass",int(schema_ok)),("commonsense_pass",int(common_ok)),("commonsense_function_groups_pass",common_groups),("hard_pass",int(hard_ok)),("three_gate_pass",int(three)),(f"status_{status}",1)):
            per[("split",r["split"])][key]+=val; per[("target_city",r["target_city"])][key]+=val
    N=len(source); summary={"protocol":manifest["protocol"],"arm":arm,"response_file_sha256":sha(response_path.read_bytes()),"N":N,
      "terminal_status_counts":dict(status_counts),"missing":status_counts["missing"],"duplicate_uids":sorted(set(duplicates)),"evaluator_error_counts":dict(evaluator_errors),
      "metrics":{"schema_query_accuracy_pct":100*sum(x["schema_pass"] for x in rows)/N,
        "commonsense_query_accuracy_pct":100*sum(x["commonsense_pass"] for x in rows)/N,
        "commonsense_function_group_accuracy_pct":100*sum(x["commonsense_function_groups_pass"] for x in rows)/(8*N),"commonsense_function_group_denominator":8*N,
        "hard_logic_query_accuracy_pct":100*sum(x["hard_pass"] for x in rows)/N,"hard_logic_clause_micro_pct":100*hard_pass_den/hard_den if hard_den else None,
        "hard_logic_clause_denominator":hard_den,"three_gate_pass_rate_pct":100*sum(x["three_gate_pass"] for x in rows)/N,
        "fpr_three_gate_pct":100*sum(x["three_gate_pass"] for x in rows)/N},
      "by_split_and_target_city":{f"{k}:{v}":dict(c) for (k,v),c in per.items()}}
    out_prefix.parent.mkdir(parents=True,exist_ok=True); out_prefix.with_suffix(".json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    with out_prefix.with_suffix(".csv").open("w",encoding="utf-8-sig",newline="") as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(json.dumps(summary,ensure_ascii=False,indent=2))

if __name__=="__main__":
    p=argparse.ArgumentParser(); sub=p.add_subparsers(dest="cmd",required=True); sub.add_parser("freeze")
    e=sub.add_parser("evaluate");e.add_argument("--responses",required=True,type=pathlib.Path);e.add_argument("--out",required=True,type=pathlib.Path);e.add_argument("--arm",required=True,choices=("A","B"))
    a=p.parse_args()
    if a.cmd=="freeze": freeze()
    else: evaluate(a.responses,a.out,a.arm)
