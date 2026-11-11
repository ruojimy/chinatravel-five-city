"""Archive bounded secondary-source observations from normal web-tool lookups.

No inferred issue dates and no made-up precise retrieval timestamps. The normal
tool call history is the capture provenance; archived_at is this script's time.
"""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'src'))
from shorttrip.freshness import utcnow

def main():
    out=ROOT/'results/p11_freshness_skill'
    journal={'archived_at':utcnow(),'method':'normal search/open/find tools, 2026-10-22 session',
      'precise_retrieval_timestamps_available':False,
      'note':'Do not substitute archive time for page publication or exact retrieval time; page extracts below are short literal observations.',
      'weather_trigger':'Amap reporttime 2026-10-22 16:35:28+08:00 was over 15 minutes old at retrieval 16:55:05+08:00.',
      'attempts':[
       {'source_id':'nmc','url':'https://www.nmc.cn/publish/forecast/AZJ/hangzhou.html','retrieved_at':None,
        'source_time_text':'发布时间：10-22 12:00','source_time_normalized':None,
        'additional_literal_date_fragment':'07/18 周四','authority_role':'official weather page, field-specific',
        'independence_group':'cma-weather-services','status':'not_usable_as_fresh_current_observation',
        'reasons':['forecast_is_not_current_observation','issue_year_and_timezone_not_explicit_in_extract','mixed_date_fragments_need_source_validation']},
       {'source_id':'weather_com_cn','url':'https://www.weather.com.cn/zhejiang/hangzhou/index.shtml','retrieved_at':None,
        'source_time_normalized':None,'independence_group':'cma-weather-services','status':'unverified',
        'reasons':['did_not_obtain_unambiguous_current_issue_time_from_opened_page','same_weather_service_lineage_not_independent_NMC_vote']},
       {'source_id':'beijing_metro_operator','url':'https://www.bjsubway.com/','retrieved_at':None,
        'status':'fetch_timeout','reasons':['homepage_not_obtained','no_applicable_route_or_service_notice_verified']}
      ],
      'weather_sources_attempted_including_amap':3,'weather_current_observation_validated_by_fresh_secondary_source':False,
      'independent_weather_lineages_confirmed':1,'amap_weather_upstream_independence':'unknown',
      'weather_search_stage':'completed_bounded_attempts_unresolved',
      'route_operator_stage':'blocked_by_timeout','user_confirmation_required_for_actual_weather_dependent_decision':True,
      'research_only_no_travel_decision_requested':True,
      'does_not_prove':['actual_current_Hangzhou_weather','no_metro_disruption','independent_multi_source_consensus'],
      'next_action':'For an actual itinerary, retry only when justified within budget using a current applicable bulletin; otherwise show uncertainty and ask an affected choice, or replace candidate.'}
    (out/'secondary_source_checks.json').write_text(json.dumps(journal,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'weather_lookup':journal['weather_search_stage'],'operator':journal['route_operator_stage']},ensure_ascii=False))

if __name__=='__main__':main()
