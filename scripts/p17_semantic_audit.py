"""Audit the actual immutable snapshot's evidence semantics, not its truth rate."""
import collections,hashlib,json,re,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import utcnow,parse_time
from shorttrip.travel_catalog import digest_file

def main():
 pointer=json.loads((ROOT/'results/p15_whole_catalog/current_catalog.json').read_text());file=ROOT/pointer['catalog']
 if digest_file(file)!=pointer['sha256']:raise ValueError('Snapshot bytes changed')
 db=sqlite3.connect(file.resolve().as_uri()+'?mode=ro',uri=True);counts=collections.Counter();errors=[];now=parse_time(utcnow())
 for payload, in db.execute('SELECT payload FROM records'):
  record=json.loads(payload);counts['records']+=1
  for a in record.get('operator_assertions',[]):
   counts['assertions']+=1;field=a['field']
   if a['source_id'].startswith('p17-triptailor:'):
    counts['historical_paper_assertions']+=1
    if any(a[k] is not None for k in ('observed_at','source_updated_at')):errors.append('paper_fact_clock_renewed:'+a['assertion_id'])
    if 'price' in a['native_values']:errors.append('paper_price_projected:'+a['assertion_id'])
    method=a['context']['identity_match_basis']['method']
    if method not in ('exact_name_city_unique_near_coordinate_candidate','literal_source_language_alias_city_unique_near_coordinate_candidate'):errors.append('unapproved_identity_method:'+a['assertion_id'])
   if a['source_id'].startswith('p17-ctrip-card:'):
    counts['scoped_card_references']+=1
    if a['native_values']:errors.append('listing_card_native_projection:'+a['assertion_id'])
    if a['value'].get('display_label')=='免费' and a['value'].get('booking_required') is not None:errors.append('free_implies_reservation_rule:'+a['assertion_id'])
   if field.startswith('room_') and a['policy_id'] not in ('room_configuration','dynamic_price','price'):errors.append('room_field_wrong_policy:'+a['assertion_id'])
   if field=='room_area':
    m=re.search(r'(\d+(?:\.\d+)?)\s*(?:-|–|—|至|to)\s*(\d+(?:\.\d+)?)\s*(?:平方米|sq\.?\s*m|m[²2])',a['quote'],re.I)
    if m:
     counts['preserved_room_area_ranges']+=1
     if a['value']!={'minimum':float(m[1]),'maximum':float(m[2])}:errors.append('room_range_collapsed:'+a['assertion_id'])
   if field=='dietary_category_unverified':
    counts['unverified_dietary_categories']+=1
    if a['native_values']:errors.append('dietary_claim_promoted:'+a['assertion_id'])
   if field.endswith('relevance_conflict'):
    counts['source_relevance_or_city_conflicts']+=1
    if a['policy_id']!='identity' or a['native_values']:errors.append('source_conflict_promoted:'+a['assertion_id'])
    required_flag='untrusted_website_source_requires_review' if field=='source_website_relevance_conflict' else 'source_city_conflicts_with_research_window'
    if required_flag not in record['uncertainty_flags']:errors.append('source_conflict_not_marked_in_record:'+a['assertion_id'])
   if a['context'].get('entity_verified'):counts['verified_by_this_assertion']+=1
  if record.get('exclude_from_static_planning'):counts['excluded_records']+=1
 for payload, in db.execute('SELECT payload FROM room_offers'):
  offer=json.loads(payload);counts['stored_room_offer_rows']+=1
  if parse_time(offer.get('valid_until')) and parse_time(offer['valid_until'])<now:counts['expired_stored_room_offer_rows']+=1
 counts['planning_ready']=db.execute('SELECT count(*) FROM records WHERE planning_ready=1').fetchone()[0]
 counts['foreign_key_errors']=len(db.execute('PRAGMA foreign_key_check').fetchall());integrity=db.execute('PRAGMA integrity_check').fetchone()[0];db.close()
 if counts['records']!=14057 or counts['foreign_key_errors'] or integrity!='ok':errors.append('snapshot_integrity_or_entity_count')
 result={'at':utcnow(),'catalogue_basis':pointer,'counts':dict(counts),'errors':errors,'all_semantic_checks_pass':not errors,
  'real_world_truth_or_full_completion_certified':False,'network_requests':0}
 folder=ROOT/'results/p17_continuous/semantic_audits';folder.mkdir(exist_ok=True);out=folder/(file.parent.name+'.json')
 if out.exists():raise FileExistsError('Immutable semantic audit exists')
 out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
 index=ROOT/'results/p17_continuous/current_semantic_audit.json';tmp=index.with_suffix('.tmp');tmp.write_text(json.dumps({'file':str(out.relative_to(ROOT)),'sha256':digest_file(out),'all_semantic_checks_pass':not errors},indent=2),encoding='utf-8');tmp.replace(index)
 print(json.dumps(result,ensure_ascii=False));
 if errors:raise SystemExit(1)
if __name__=='__main__':main()
