import unittest
from datetime import datetime, timezone, timedelta
from shorttrip.strict_v4_adapter import (diagnose_record, diagnose_candidate,
                                         schedule_content_sha256)


def bind_schedule_scope(activity, *, valid_from='2026-10-01T00:00:00+08:00',
                        valid_until='2026-12-01T00:00:00+08:00', weekdays=None,
                        utc_offset='+08:00'):
    if weekdays is None:
        weekdays = list(activity.get('weekdays') or [activity['start'].weekday()])
    activity['weekdays'] = list(weekdays)
    activity['schedule_scope'] = {
        'source_id': 'synthetic-source', 'evidence_id': 'synthetic-schedule-evidence',
        'valid_from': valid_from, 'valid_until': valid_until,
        'utc_offset': utc_offset, 'weekdays': list(weekdays),
        'activity_start': activity['start'].isoformat(),
        'activity_end': activity['end'].isoformat(),
        'schedule_sha256': schedule_content_sha256(activity),
    }
    return activity


class AdapterTests(unittest.TestCase):
    def test_unknown_record_identity_cannot_be_verifier_approved(self):
        for key in ('id', 'city', 'kind', 'name'):
            record = self.record()
            record[key] = 'unknown'
            result = diagnose_record(record, [], registry={}, now='2026-10-30T00:00:00Z',
                                     uid='test', identity_verifier=lambda *_: True)
            with self.subTest(field=key):
                self.assertFalse(result['identity_independently_verified'])
                self.assertFalse(result['passed_checks'])

    def test_schedule_verifier_cannot_change_original_activity_by_closure(self):
        tz = timezone(timedelta(hours=8))
        activity = bind_schedule_scope({'start': datetime(2026,11,2,12,tzinfo=tz),
            'end': datetime(2026,11,2,13,tzinfo=tz),
            'windows':[{'weekday':0,'open':'09:00','close':'10:00','end_day_offset':0}],
            'schedule_complete':True})
        def mutate(_activity, _scope):
            activity['windows'][0]['close'] = '14:00'
            return True
        result = diagnose_candidate(uid='closure-schedule',city='X',activity=activity,
            route_requirement={'context':{}}, route_evidence={'context':{}},
            required_costs=[None],budget=10,now='2026-10-30T00:00:00Z',
            schedule_verifier=mutate)
        self.assertEqual(result['outcome'], 'pipeline_error')
        self.assertNotIn('opening_hours', [x['field'] for x in result['passed_checks']])

    def test_identity_verifier_cannot_change_original_record_by_closure(self):
        record = self.record()
        def mutate(_copy):
            record['id'] = 'attacker-entity'
            return True
        result = diagnose_record(record, [], registry={}, now='2026-10-30T00:00:00Z',
                                 uid='closure', identity_verifier=mutate)
        self.assertEqual(result['outcome'], 'pipeline_error')
        self.assertFalse(result['identity_independently_verified'])
        self.assertNotEqual(result['entity_id'], 'attacker-entity')
        self.assertFalse(result['passed_checks'])

    def test_metro_legacy_disruption_mapping_cannot_qualify_static_fields(self):
        record = {'id': 'station', 'kind': 'metro_station', 'city': 'X',
                  'name': 'station', 'payload': {'data': {'name': 'station',
                  'line': '1', 'position': [1, 2]}}, 'claims': []}
        requirements = [
            {'native_field': 'name', 'policy_field': 'route_disruption', 'scope': {'city': 'X'}},
            {'native_field': 'line', 'policy_field': 'route_disruption', 'scope': {'city': 'X'}},
            {'native_field': 'position', 'policy_field': 'coordinates', 'scope': {'city': 'X'}},
        ]
        result = diagnose_record(record, requirements, registry={}, now='2026-10-30T00:00:00Z',
                                 uid='metro', identity_verifier=lambda _: True)
        reasons = {gap['reason'] for axis in result['axes'].values() for gap in axis}
        self.assertIn('metro_native_policy_mismatch', reasons)
        self.assertIn('metro_native_policy_unavailable', reasons)
        self.assertIn('missing_evidence', reasons)
        self.assertFalse(result['passed_checks'])

    def test_raw_multisegment_schedule_requires_independent_verifier(self):
        tz=timezone(timedelta(hours=8))
        activity={'start':datetime(2026,11,2,11,30,tzinfo=tz),
                  'end':datetime(2026,11,2,12,30,tzinfo=tz),
                  'windows':None,'raw_schedule_text':'09:00-12:00;13:00-17:00',
                  'weekdays':[0], 'schedule_complete':True}
        bind_schedule_scope(activity)
        kwargs=dict(uid='x',city='X',activity=activity,route_requirement={'context':{}},
                    route_evidence={'context':{}},required_costs=[None],budget=10,now='2026-10-30T00:00:00Z')
        unverified=diagnose_candidate(**kwargs)
        self.assertIn('opening_hours',[x['field'] for x in unverified['unknown_checks']])
        verified=diagnose_candidate(**kwargs,schedule_verifier=lambda copied, scope:
                                    scope['schedule_sha256']==schedule_content_sha256(copied))
        self.assertIn('opening_hours',[x['field'] for x in verified['hard_failures']])
        self.assertFalse(verified['execution_confirmed'])

    def test_schedule_verifier_mutation_is_isolated_and_unknown(self):
        tz=timezone(timedelta(hours=8))
        activity=bind_schedule_scope({
            'start':datetime(2026,11,2,12,tzinfo=tz),
            'end':datetime(2026,11,2,13,tzinfo=tz),
            'windows':[{'weekday':0,'open':'09:00','close':'10:00','end_day_offset':0}],
            'schedule_complete':True})
        original=activity['windows'][0].copy()
        kwargs=dict(uid='mutate',city='X',activity=activity,route_requirement={'context':{}},
                    route_evidence={'context':{}},required_costs=[None],budget=10,
                    now='2026-10-30T00:00:00Z')

        def mutator(copied_activity, copied_scope):
            copied_activity['windows']=[{'weekday':0,'open':'00:00','close':'24:00',
                                         'end_day_offset':0}]
            copied_scope['schedule_sha256']='forged'
            return True

        result=diagnose_candidate(**kwargs,schedule_verifier=mutator)
        self.assertIn('opening_hours',[x['field'] for x in result['unknown_checks']])
        self.assertEqual(activity['windows'][0],original)

    def test_schedule_scope_validity_bounds_and_offset_fail_closed(self):
        tz=timezone(timedelta(hours=8))
        base={'start':datetime(2026,11,2,10,tzinfo=tz),
              'end':datetime(2026,11,2,11,tzinfo=tz),
              'windows':[{'weekday':0,'open':'09:00','close':'17:00','end_day_offset':0}],
              'schedule_complete':True}
        kwargs=dict(uid='scope',city='X',route_requirement={'context':{}},
                    route_evidence={'context':{}},required_costs=[None],budget=10,
                    now='2026-10-30T00:00:00Z')
        verifier_calls=[]
        verifier=lambda *_:verifier_calls.append(True) or True

        future=bind_schedule_scope(dict(base),valid_from='2099-01-01T00:00:00+08:00',
                                   valid_until='2099-12-31T23:59:59+08:00')
        result=diagnose_candidate(**kwargs,activity=future,schedule_verifier=verifier)
        self.assertIn('opening_hours',[x['field'] for x in result['unknown_checks']])
        self.assertEqual(verifier_calls,[])

        wrong_offset=bind_schedule_scope(dict(base),utc_offset='+00:00')
        result=diagnose_candidate(**kwargs,activity=wrong_offset,schedule_verifier=verifier)
        self.assertIn('opening_hours',[x['field'] for x in result['unknown_checks']])
        self.assertEqual(verifier_calls,[])

        # A correctly bound, explicit synthetic scope can reach the verifier.
        valid=bind_schedule_scope(dict(base))
        result=diagnose_candidate(**kwargs,activity=valid,schedule_verifier=verifier)
        self.assertIn('opening_hours',[x['field'] for x in result['passed_checks']])
        self.assertEqual(verifier_calls,[True])
    def test_auditor_is_diagnostic_only_and_errors_are_pipeline(self):
        record=self.record()
        record['claims']=[{'evidence_id':'e','evidence':{},'payload':{'native_field':'price','value':40}}]
        req=[{'native_field':'price','policy_field':'price','scope':{'ticket':'adult'}}]
        result=diagnose_record(record,req,registry={},now='2026-10-30T00:00:00Z',uid='audit',
                               identity_verifier=lambda _:True,
                               evidence_auditor=lambda *args:{'mechanical_checks_pass':True})
        self.assertTrue(result['evidence_audits'][0]['result']['mechanical_checks_pass'])
        self.assertTrue(result['axes']['adapter'])
        self.assertFalse(result['execution_confirmed'])
        def bad(*args): raise RuntimeError('failed')
        result=diagnose_record(record,req,registry={},now='2026-10-30T00:00:00Z',uid='audit',
                               identity_verifier=lambda _:True,evidence_auditor=bad)
        self.assertEqual(result['outcome'],'pipeline_error')
        self.assertEqual(result['axes']['pipeline'][0]['reason'],'independent_evidence_audit_failed')

    def test_identity_verifier_mutation_is_discarded_and_pipeline_blocked(self):
        record=self.record()
        original=record.copy()
        original_payload=record['payload'].copy()

        def mutating_identity(record_copy):
            record_copy['id']='forged-id'
            record_copy['payload']['data']['price']=999
            return True

        result=diagnose_record(record,[{'native_field':'price','policy_field':'price',
            'scope':{'ticket':'adult'}}],registry={},now='2026-10-30T00:00:00Z',uid='identity-mutate',
            identity_verifier=mutating_identity)
        self.assertEqual(record['id'],original['id'])
        self.assertEqual(record['payload'],original_payload)
        self.assertFalse(result['identity_independently_verified'])
        self.assertIn('independent_identity_verifier_mutated_input',
                      [gap['reason'] for gap in result['axes']['pipeline']])
        self.assertIn('identity_unresolved',[gap['reason'] for gap in result['axes']['data']])

    def test_auditor_mutation_is_pipeline_gap_and_cannot_change_evidence_scope(self):
        record=self.record()
        record['claims']=[{'evidence_id':'e','evidence':{},'payload':{
            'native_field':'price','value':40,'context':{'scope':{'ticket':'adult'}}}}]
        requirements=[{'native_field':'price','policy_field':'price',
                       'scope':{'ticket':'adult'}}]
        original_scope=requirements[0]['scope'].copy()

        def mutating_auditor(_record, requirement, claim, evidence):
            requirement['scope']['ticket']='child'
            claim['value']=0
            evidence['eligible']=True
            return {'mechanical_checks_pass':True}

        result=diagnose_record(record,requirements,registry={},now='2026-10-30T00:00:00Z',
            uid='audit-mutate',identity_verifier=lambda _:True,
            evidence_auditor=mutating_auditor)
        self.assertEqual(requirements[0]['scope'],original_scope)
        self.assertEqual(record['claims'][0]['payload']['value'],40)
        self.assertEqual(record['claims'][0]['evidence'],{})
        self.assertIn('independent_evidence_auditor_mutated_input',
                      [gap['reason'] for gap in result['axes']['pipeline']])
        self.assertEqual(result['evidence_audits'],[])
        self.assertNotIn('price',[check['field'] for check in result['passed_checks']])

    def test_cost_verifier_mutation_cannot_certify_stale_total_or_pollute_caller(self):
        costs=[10]
        def mutating_cost_verifier(copied_costs):
            copied_costs[0]=1000
            return True

        result=diagnose_candidate(uid='cost-mutate',city='X',activity={
            'start':datetime(2026,10,26,10),'end':datetime(2026,10,26,11)},
            route_requirement={'context':{}},route_evidence={'context':{}},
            required_costs=costs,budget=15,now='2026-10-30T00:00:00Z',
            cost_verifier=mutating_cost_verifier)
        self.assertEqual(costs,[10])
        self.assertIn('independent_cost_verifier_mutated_input',
                      [gap['reason'] for gap in result['axes']['pipeline']])
        self.assertIn('budget',[check['field'] for check in result['unknown_checks']])
        self.assertNotIn('budget',[check['field'] for check in result['passed_checks']])
    def record(self):
        return {'id':'id','city':'X','kind':'attraction','name':'N',
                'payload':{'data':{'price':40}},'claims':[]}
    def test_missing_context_and_evidence_are_distinct(self):
        result = diagnose_record(self.record(), [{'native_field':'price','policy_field':'price','scope':{}},
            {'native_field':'missing','policy_field':'price','scope':{'ticket':'adult'}},
            {'native_field':'price','policy_field':'price','scope':{'ticket':'adult'}}], registry={}, now='2026-10-30T00:00:00Z', uid='x',
            identity_verifier=lambda _:True)
        self.assertEqual(len(result['axes']['context']),1)
        self.assertEqual(len(result['axes']['data']),2)
        self.assertEqual(len(result['axes']['adapter']),1)
        self.assertFalse(result['execution_confirmed'])
        self.assertEqual({g['reason'] for g in result['repair_queue']},{'missing_value','missing_evidence'})

    def test_candidate_unknowns_do_not_become_proof_or_free_fare(self):
        result=diagnose_candidate(uid='c', city='X', activity={'start':datetime(2026,10,26,12),
            'end':datetime(2026,10,26,13), 'windows':None}, route_requirement={'context':{}},
            route_evidence={'context':{}}, required_costs=[100,None], budget=200,
            now='2026-10-30T00:00:00Z')
        self.assertEqual(result['outcome'],'data_block')
        self.assertFalse(result['proof_verified_by_controller'])
        self.assertFalse(result['execution_confirmed'])
        self.assertEqual(len(result['axes']['data']),3)

    def test_intercity_minutes_in_native_hour_field_is_adapter_error(self):
        record={'id':'train','city':'X','kind':'train','name':'G',
                'payload':{'data':{'Duration':409}},
                'claims':[{'evidence_id':'e','evidence':{},'payload':{'native_field':'Duration',
                  'context':{'scope':{'Duration_unit':'minutes'}}}}]}
        result=diagnose_record(record,[{'native_field':'Duration','policy_field':'intercity_schedule',
            'scope':{'direction':'A>B'}}],registry={},now='2026-10-30T00:00:00Z',uid='unit',
            identity_verifier=lambda _:True)
        self.assertIn('native_duration_unit_conflict',[g['reason'] for g in result['axes']['adapter']])
        self.assertFalse(result['execution_confirmed'])
        missing_scope=diagnose_record(record,[{'native_field':'Duration','policy_field':'intercity_schedule',
            'scope':{}}],registry={},now='2026-10-30T00:00:00Z',uid='unit2')
        self.assertIn('native_duration_unit_conflict',[g['reason'] for g in missing_scope['axes']['adapter']])
        self.assertIn('required_scope_missing',[g['reason'] for g in missing_scope['axes']['context']])

    def test_nested_scope_is_mapped_but_identity_and_source_gates_remain(self):
        record={'id':'r','city':'X','kind':'attraction','name':'N',
                'payload':{'data':{'price':40},'entity_verified':False},
                'claims':[{'evidence_id':'e','evidence':{},'payload':{'native_field':'price',
                    'context':{'scope':{'ticket':'adult'}},'value':40}}]}
        result=diagnose_record(record,[{'native_field':'price','policy_field':'price',
            'scope':{'ticket':'adult'}}],registry={},now='2026-10-30T00:00:00Z',uid='scope',
            identity_verifier=lambda _:True)
        self.assertIn('source_profile_review_pending',[g['reason'] for g in result['axes']['adapter']])
        self.assertEqual(result['axes']['data'],[])
        self.assertEqual(result['repair_queue'],[])

    def test_scope_mismatch_and_unauthorized_source_do_not_promote_claim(self):
        record={'id':'r','city':'X','kind':'attraction','name':'N',
                'payload':{'data':{'price':40},'entity_verified':True},
                'claims':[{'evidence_id':'e','evidence':{'evidence_id':'e'},'payload':{
                    'native_field':'price','field':'price','value':40,'entity_id':'r',
                    'source_id':'s','context':{'scope':{'ticket':'student'}}}}]}
        result=diagnose_record(record,[{'native_field':'price','policy_field':'price',
            'scope':{'ticket':'adult'}}],registry={'s':{'supports':[]}},
            now='2026-10-30T00:00:00Z',uid='scope',identity_verifier=lambda _:True)
        self.assertIn('evidence_ineligible',[g['reason'] for g in result['axes']['data']])
        details=result['axes']['data'][0].get('detail',[])
        reasons=details[0]['reasons']
        self.assertIn('scope_mismatch:ticket',reasons)
        self.assertIn('source_policy_field_not_authorized',reasons)
        self.assertFalse(result['proof_verified_by_controller'])

    def test_claim_value_binding_rejects_bool_and_nested_type_confusables(self):
        from tests.test_strict_v4_evidence import fixture as evidence_fixture
        claim,evidence,profiles=evidence_fixture()
        claim['value']=True
        record={'id':'venue','city':'Xiamen','kind':'attraction','name':'Venue',
            'payload':{'data':{'price':1}},'claims':[{'payload':claim,'evidence':evidence}]}
        result=diagnose_record(record,[{'native_field':'price','policy_field':'price',
            'scope':{'travel_date':'2026-11-02','ticket_type':'ordinary_adult'}}],
            registry=profiles,now='2026-10-30T08:00:00Z',uid='bool-price',
            identity_verifier=lambda _:True,evidence_verifier=lambda *_:True)
        self.assertNotIn('price',[item['field'] for item in result['passed_checks']])
        detail=next(g for g in result['axes']['data'] if g['reason']=='evidence_ineligible')['detail']
        self.assertIn('numeric_price_value_invalid',detail[0]['reasons'])

        claim,evidence,profiles=evidence_fixture()
        claim.update(native_field='experience',field='experience',value={'nested':True})
        claim['context']['native_field']='experience'
        profiles['operator']['supports']=['experience']
        record={'id':'venue','city':'Xiamen','kind':'attraction','name':'Venue',
            'payload':{'data':{'experience':{'nested':1}}},
            'claims':[{'payload':claim,'evidence':evidence}]}
        result=diagnose_record(record,[{'native_field':'experience','policy_field':'experience',
            'scope':{'travel_date':'2026-11-02','ticket_type':'ordinary_adult'}}],
            registry=profiles,now='2026-10-30T08:00:00Z',uid='nested-value',
            identity_verifier=lambda _:True,evidence_verifier=lambda *_:True)
        self.assertNotIn('experience',[item['field'] for item in result['passed_checks']])
        detail=next(g for g in result['axes']['data'] if g['reason']=='evidence_ineligible')['detail']
        self.assertIn('claim_value_mismatch',detail[0]['reasons'])

    def test_price_float_is_rejected_and_exact_decimal_text_can_pass(self):
        from tests.test_strict_v4_evidence import fixture as evidence_fixture

        claim, evidence, profiles = evidence_fixture()
        claim["value"] = 80.0
        record = {'id': 'venue', 'city': 'Xiamen', 'kind': 'attraction', 'name': 'Venue',
                  'payload': {'data': {'price': 80.0}},
                  'claims': [{'payload': claim, 'evidence': evidence}]}
        requirements = [{'native_field': 'price', 'policy_field': 'price',
                         'scope': {'travel_date': '2026-11-02',
                                   'ticket_type': 'ordinary_adult'}}]
        rejected_float = diagnose_record(
            record, requirements, registry=profiles, now='2026-10-30T08:00:00Z',
            uid='float-price', identity_verifier=lambda _: True,
            evidence_verifier=lambda *_: True)
        self.assertNotIn('price', [item['field'] for item in rejected_float['passed_checks']])
        detail = next(g for g in rejected_float['axes']['data']
                      if g['reason'] == 'evidence_ineligible')['detail']
        self.assertIn('numeric_price_value_invalid', detail[0]['reasons'])

        amount = '0.100000000000000005'
        raw = f'普通成人票 {amount} 元，适用日期 2026-11-02'
        claim, evidence, profiles = evidence_fixture()
        claim['value'] = amount
        claim['quote'] = raw
        evidence['raw_text'] = raw
        evidence['raw_sha256'] = __import__('hashlib').sha256(raw.encode()).hexdigest()
        record = {'id': 'venue', 'city': 'Xiamen', 'kind': 'attraction', 'name': 'Venue',
                  'payload': {'data': {'price': amount}},
                  'claims': [{'payload': claim, 'evidence': evidence}]}

        def exact_quote_verifier(claim_copy, evidence_copy, *_):
            return (claim_copy['value'] in claim_copy['quote'] and
                    claim_copy['quote'] == evidence_copy['raw_text'])

        accepted = diagnose_record(
            record, requirements, registry=profiles, now='2026-10-30T08:00:00Z',
            uid='decimal-price', identity_verifier=lambda _: True,
            evidence_verifier=exact_quote_verifier)
        self.assertIn('price', [item['field'] for item in accepted['passed_checks']])

        claim['quote'] = '普通成人票 0.1 元，适用日期 2026-11-02'
        evidence['raw_text'] = claim['quote']
        evidence['raw_sha256'] = __import__('hashlib').sha256(
            claim['quote'].encode()).hexdigest()
        record['payload']['data']['price'] = amount
        rejected_quote = diagnose_record(
            record, requirements, registry=profiles, now='2026-10-30T08:00:00Z',
            uid='rounded-quote', identity_verifier=lambda _: True,
            evidence_verifier=exact_quote_verifier)
        self.assertNotIn('price', [item['field'] for item in rejected_quote['passed_checks']])

    def test_catalog_identity_boolean_cannot_make_missing_gaps_repairable(self):
        record=self.record()
        record['payload']['entity_verified']=True
        record['payload']['data'].pop('price')
        result=diagnose_record(record,[{'native_field':'price','policy_field':'price',
            'scope':{'ticket':'adult'}}],registry={},now='2026-10-30T00:00:00Z',uid='identity')
        self.assertFalse(result['identity_independently_verified'])
        self.assertEqual(result['identity_resolution_workflow']['status'],'required')
        self.assertEqual({g['reason'] for g in result['axes']['data']},
                         {'identity_unresolved','missing_value'})
        self.assertFalse(next(g for g in result['axes']['data'] if g['reason']=='missing_value')['repairable'])
        self.assertEqual(result['repair_queue'],[])

    def test_independent_identity_result_gates_missing_value_and_evidence_jobs(self):
        record=self.record()
        record['payload']['entity_verified']=False
        record['payload']['data'].pop('price')
        record['payload']['data']['hours']='10:00-17:00'
        requirements=[{'native_field':'price','policy_field':'price','scope':{'ticket':'adult'}},
                      {'native_field':'hours','policy_field':'opening_hours','scope':{'date':'2026-11-02'}}]
        out=diagnose_record(record,requirements,registry={},now='2026-10-30T00:00:00Z',uid='verified',
                            identity_verifier=lambda r:r['id']=='id')
        self.assertTrue(out['identity_independently_verified'])
        self.assertEqual({g['reason'] for g in out['repair_queue']},{'missing_value','missing_evidence'})
        rejected=diagnose_record(record,requirements,registry={},now='2026-10-30T00:00:00Z',uid='rejected',
                                 identity_verifier=lambda _:False)
        self.assertEqual(rejected['repair_queue'],[])
        self.assertFalse(rejected['identity_independently_verified'])


if __name__ == '__main__': unittest.main()
