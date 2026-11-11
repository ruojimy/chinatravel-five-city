"""Review-only bridge from a development cohort task to v4 diagnostics.

This adapter diagnoses declared candidate handles and task constraints. It
does not construct trips, fill missing start/room/route context, score a
cohort, or establish a formal freeze. A declared business chain is only
candidate coverage metadata; it does not guarantee plan selection or order.
"""
from .collection_workflow import classify
from .strict_plan_diagnostics import diagnose_plan


def diagnose_development_task(task, *, reader, now, registry=None,
                              identity_verifier=None,
                              field_evidence_verifier=None,
                              evidence_auditor=None,
                              constraint_facts=None,
                              constraint_fact_verifier=None,
                              tag_evidence=None, tag_scope_verifier=None):
    """Validate IDs against a V4Reader and return engineering-only checks.

    ``reader`` must provide ``get(entity_id)``. Only declared candidate IDs,
    kinds, city, and explicit structured constraints are consumed. Field-level
    price requirements are not inferred from a total-budget expression.
    """
    if not isinstance(task, dict):
        return _error('task_not_object', 'pipeline')
    uid = task.get('uid') if isinstance(task.get('uid'), str) else 'unknown'
    split = task.get('split')
    purpose = task.get('purpose')
    if split == 'holdout' or purpose == 'holdout':
        return _error('holdout_rejected_from_exploratory_adapter', 'adapter', uid=uid,
                      level=task.get('level'))
    if split != 'development' or purpose != 'development':
        return _error('non_development_task_rejected', 'adapter', uid=uid,
                      level=task.get('level'))
    if not callable(getattr(reader, 'get', None)):
        return _error('v4_reader_missing', 'pipeline', uid=uid, level=task.get('level'))
    errors = _validate_draft_task(task)
    if errors:
        return _error('draft_task_schema_invalid', 'pipeline', uid=uid,
                      level=task.get('level'), detail={'errors': errors[:8]})

    kinds = task.get('required_kinds')
    selection = task.get('candidate_selection')
    entity_ids = selection.get('required_entity_ids') if isinstance(selection, dict) else None
    selected = task.get('generation', {}).get('selected_entities_by_kind')
    city = task.get('target_city')
    if not isinstance(city, str) or not city.strip():
        return _error('target_city_missing', 'context', uid=uid, level=task['level'])
    if (not isinstance(kinds, list) or not kinds or not isinstance(entity_ids, list) or
            len(kinds) != len(entity_ids) or not isinstance(selected, dict)):
        return _error('candidate_selection_context_incomplete', 'context', uid=uid,
                      level=task['level'])
    chain_error = _business_chain_error(task, kinds, entity_ids, selected)
    if chain_error:
        return _error('business_chain_mapping_mismatch', 'pipeline', uid=uid,
                      level=task['level'], detail={'reason': chain_error})

    gaps, checks, record_requirements, candidate_reports = [], [], [], []
    for index, (kind, entity_id) in enumerate(zip(kinds, entity_ids)):
        if not isinstance(kind, str) or not isinstance(entity_id, str) or not entity_id:
            gaps.append(_gap(uid, 'pipeline', f'candidate_{index}_malformed',
                             'candidate_reference_malformed'))
            continue
        mapping = selected.get(kind)
        if not isinstance(mapping, dict) or mapping.get('id') != entity_id:
            gaps.append(_gap(uid, 'pipeline', f'candidate_{index}_mapping',
                             'candidate_mapping_mismatch', entity_id=entity_id,
                             detail={'kind': kind}))
            candidate_reports.append({'entity_id': entity_id, 'kind': kind,
                                     'state': 'unknown', 'reason': 'candidate_mapping_mismatch'})
            continue
        try:
            record = reader.get(entity_id)
        except KeyError:
            gaps.append(_gap(uid, 'pipeline', f'candidate_{index}_missing',
                             'candidate_id_not_found', entity_id=entity_id,
                             detail={'kind': kind}))
            candidate_reports.append({'entity_id': entity_id, 'kind': kind,
                                     'state': 'unknown', 'reason': 'candidate_id_not_found'})
            continue
        except Exception as exc:
            gaps.append(_gap(uid, 'pipeline', f'candidate_{index}_reader',
                             'v4_reader_failed', entity_id=entity_id,
                             detail={'error_type': type(exc).__name__}))
            candidate_reports.append({'entity_id': entity_id, 'kind': kind,
                                     'state': 'unknown', 'reason': 'v4_reader_failed'})
            continue
        if not isinstance(record, dict) or record.get('id') != entity_id:
            gaps.append(_gap(uid, 'pipeline', f'candidate_{index}_identity',
                             'reader_id_mismatch', entity_id=entity_id))
            candidate_reports.append({'entity_id': entity_id, 'kind': kind,
                                     'state': 'unknown', 'reason': 'reader_id_mismatch'})
            continue
        if (not isinstance(record.get('payload'), dict) or
                not isinstance(record.get('claims'), list) or
                any(not isinstance(claim, dict) or not isinstance(claim.get('payload'), dict)
                    or not isinstance(claim.get('evidence'), dict)
                    for claim in record.get('claims', []))):
            gaps.append(_gap(uid, 'pipeline', f'candidate_{index}_record_shape',
                             'v4_record_shape_malformed', entity_id=entity_id))
            candidate_reports.append({'entity_id': entity_id, 'kind': kind,
                                     'state': 'unknown', 'reason': 'v4_record_shape_malformed'})
            continue
        stored_name = mapping.get('stored_name_unverified')
        record_name = record.get('name')
        if (not isinstance(stored_name, str) or not isinstance(record_name, str) or
                stored_name != record_name):
            gaps.append(_gap(uid, 'context', f'candidate_{index}_stored_name',
                             'stored_name_metadata_mismatch', entity_id=entity_id,
                             detail={'stored_name_unverified': stored_name,
                                     'v4_record_name': record_name,
                                     'comparison_only': True}))
            candidate_reports.append({'entity_id': entity_id, 'kind': kind,
                                     'state': 'unknown', 'reason': 'stored_name_metadata_mismatch'})
            continue
        mismatch = {}
        if record.get('kind') != kind:
            mismatch['actual_kind'] = record.get('kind')
        if record.get('city') != city:
            mismatch['actual_city'] = record.get('city')
        if mismatch:
            gaps.append(_gap(uid, 'context', f'candidate_{index}_scope',
                             'candidate_kind_or_city_mismatch', entity_id=entity_id,
                             detail={'expected_kind': kind, 'expected_city': city, **mismatch}))
            candidate_reports.append({'entity_id': entity_id, 'kind': kind,
                                     'state': 'unknown', 'reason': 'candidate_kind_or_city_mismatch'})
            continue
        # No per-record fields are required by the task with an exact field
        # scope. The record adapter still checks identity independently.
        record_requirements.append((record, []))
        candidate_reports.append({'entity_id': entity_id, 'kind': kind,
                                  'city': city, 'state': 'record_loaded_identity_unverified'})

    base = diagnose_plan(
        uid='cohort-draft:' + uid, city=city, record_requirements=record_requirements,
        registry=registry or {}, now=now, candidate=[],
        field_evidence_verifier=field_evidence_verifier,
        evidence_auditor=evidence_auditor,
        identity_verifier=identity_verifier,
        constraints=task.get('additional_constraints', []),
        constraint_facts=constraint_facts,
        constraint_fact_verifier=constraint_fact_verifier,
        tag_evidence=tag_evidence, tag_scope_verifier=tag_scope_verifier,
        business_chain={'chain':task['generation']['business_chain'], 'events':None},
        level=task['level'])

    # Full plan checks are unavailable: this task has no authoritative
    # selection of start point, room configuration, routes, or itinerary.
    gaps.extend(_axis_gaps(base))
    gaps.append(_gap(uid, 'solver', 'plan_not_constructed',
                     'missing_start_room_route_and_itinerary_context'))
    checks.extend(base.get('hard_failures', []))
    checks.extend(base.get('unknown_checks', []))
    checks.extend(base.get('passed_checks', []))
    result = classify({'uid': 'cohort-draft:' + uid, 'city': city,
                       'level': task['level'], 'gaps': gaps,
                       'hard_checks': checks,
                       'planner': {'supported': False},
                       'plan_present': False,
                       'required_checks_complete': False})
    result.update({'label': 'engineering_only', 'engineering_only': True,
                   'formal_score': None, 'frozen': False,
                   'execution_confirmed': False,
                   'soft_checks': base.get('soft_checks', []),
                   'evidence_audits': base.get('evidence_audits', []),
                   'business_chain_check': base.get('business_chain_check'),
                   'candidate_checks': candidate_reports,
                   'constraint_mapping': {
                       'task_constraint_ids': [c['id'] for c in task['additional_constraints']],
                       'field_requirements_derived': [],
                       'reason': 'no exact per-record field scopes declared',
                   },
                   'business_chain_semantics':
                       'candidate_coverage_only_not_plan_selection_or_order'})
    return result


def _axis_gaps(result):
    return [gap for entries in result.get('axes', {}).values() for gap in entries
            if isinstance(gap, dict) and gap.get('gap_id')]


def _business_chain_error(task, required_kinds, entity_ids, selected):
    chain_kinds = ('attraction', 'restaurant', 'accommodation')
    auxiliary_kinds = {'poi', 'metro_station', 'train', 'flight'}
    generation = task.get('generation')
    if not isinstance(generation, dict):
        return 'generation_mapping_missing'
    chain = generation.get('business_chain')
    auxiliary = generation.get('auxiliary_kind')
    if not isinstance(chain, list) or len(chain) != len(chain_kinds):
        return 'business_chain_must_have_three_ordered_kinds'
    if auxiliary not in auxiliary_kinds:
        return 'auxiliary_kind_invalid'
    if tuple(required_kinds) != chain_kinds + (auxiliary,):
        return 'required_kinds_do_not_match_chain_plus_one_auxiliary'
    if set(selected) != set(required_kinds):
        return 'selected_entity_kind_set_mismatch'
    for index, expected_kind in enumerate(chain_kinds):
        item = chain[index]
        if not isinstance(item, dict) or item.get('kind') != expected_kind:
            return 'business_chain_order_or_kind_mismatch'
        entity_id = item.get('entity_id')
        mapping = selected.get(expected_kind)
        if (not isinstance(entity_id, str) or not entity_id or
                not isinstance(mapping, dict) or mapping.get('id') != entity_id or
                entity_ids[index] != entity_id):
            return 'business_chain_entity_id_mismatch'
    auxiliary_mapping = selected.get(auxiliary)
    if (not isinstance(auxiliary_mapping, dict) or
            not isinstance(auxiliary_mapping.get('id'), str) or
            not auxiliary_mapping['id'] or entity_ids[-1] != auxiliary_mapping['id']):
        return 'auxiliary_entity_id_mismatch'
    return None


def _validate_draft_task(task):
    errors = []
    required = ('uid', 'level', 'task_origin', 'purpose', 'start_city', 'target_city',
                'days', 'people_number', 'start_date', 'additional_constraints',
                'required_kinds', 'evidence_policy_id', 'generation',
                'candidate_selection', 'split')
    for key in required:
        if key not in task:
            errors.append('missing_' + key)
    if errors:
        return errors
    if not isinstance(task['uid'], str) or not task['uid'].strip(): errors.append('uid_invalid')
    if task['level'] not in ('easy', 'medium', 'human'): errors.append('level_invalid')
    if task['purpose'] not in ('development', 'holdout', 'schema_example', 'regression'):
        errors.append('purpose_invalid')
    if task['split'] not in ('development', 'holdout', 'example', 'regression'):
        errors.append('split_invalid')
    if type(task['days']) is not int or task['days'] < 1: errors.append('days_invalid')
    if type(task['people_number']) is not int or task['people_number'] < 1:
        errors.append('people_number_invalid')
    if not isinstance(task['start_city'], str) or not task['start_city'].strip(): errors.append('start_city_invalid')
    if not isinstance(task['target_city'], str) or not task['target_city'].strip(): errors.append('target_city_invalid')
    if task['task_origin'] not in ('researcher_generated', 'human_authored', 'synthetic_human_style'):
        errors.append('task_origin_invalid')
    if task['level'] in ('easy', 'medium') and task['task_origin'] != 'researcher_generated':
        errors.append('task_origin_level_mismatch')
    if task['level'] == 'human' and task['task_origin'] not in ('human_authored', 'synthetic_human_style'):
        errors.append('task_origin_level_mismatch')
    if task.get('mode') not in ('collection_static_reference', 'benchmark_frozen', 'live_delivery'):
        errors.append('mode_invalid')
    if not isinstance(task['evidence_policy_id'], str) or not task['evidence_policy_id'].strip():
        errors.append('evidence_policy_id_invalid')
    try:
        from datetime import date
        date.fromisoformat(task['start_date'])
    except (TypeError, ValueError):
        errors.append('start_date_invalid')
    if not isinstance(task['required_kinds'], list) or not task['required_kinds'] or any(
            not isinstance(x, str) or not x for x in task['required_kinds']):
        errors.append('required_kinds_invalid')
    else:
        allowed_kinds = {'attraction', 'restaurant', 'accommodation', 'poi',
                         'metro_station', 'train', 'flight'}
        if any(kind not in allowed_kinds for kind in task['required_kinds']):
            errors.append('required_kind_unsupported')
        if len(set(task['required_kinds'])) != len(task['required_kinds']):
            errors.append('required_kinds_duplicated')
    constraints = task['additional_constraints']
    if not isinstance(constraints, list):
        errors.append('additional_constraints_invalid')
    else:
        ids = []
        for item in constraints:
            if not isinstance(item, dict):
                errors.append('constraint_not_object')
                continue
            cid, expression = item.get('id'), item.get('expression')
            if not isinstance(cid, str) or not cid: errors.append('constraint_id_invalid')
            else: ids.append(cid)
            if item.get('strength') not in ('hard', 'soft'): errors.append('constraint_strength_invalid')
            if not isinstance(item.get('scope'), dict): errors.append('constraint_scope_invalid')
            if (not isinstance(expression, dict) or not isinstance(expression.get('op'), str)
                    or not isinstance(expression.get('args'), dict)):
                errors.append('constraint_expression_invalid')
            if item.get('compiler_status') not in ('unmapped', 'supported', 'unsupported'):
                errors.append('constraint_compiler_status_invalid')
        if len(set(ids)) != len(ids): errors.append('constraint_ids_duplicated')
        if task['level'] == 'easy' and len(constraints) != 1:
            errors.append('easy_constraint_count_invalid')
        if task['level'] == 'medium':
            variant = task.get('medium_variant')
            minimum = 3 if variant == 'paper_main_3_5' else 2 if variant == 'paper_appendix_2_5' else None
            if minimum is None or not minimum <= len(constraints) <= 5:
                errors.append('medium_constraint_count_or_variant_invalid')
    if task['purpose'] == 'schema_example' and task['split'] != 'example':
        errors.append('schema_example_split_invalid')
    selection = task['candidate_selection']
    if (not isinstance(selection, dict) or not isinstance(selection.get('policy'), str)
            or not isinstance(selection.get('required_entity_ids'), list)
            or any(not isinstance(x, str) or not x for x in selection['required_entity_ids'])):
        errors.append('candidate_selection_invalid')
    elif (not selection['policy'].strip() or
          len(set(selection['required_entity_ids'])) != len(selection['required_entity_ids'])):
        errors.append('candidate_selection_duplicate_or_policy_empty')
    generation = task['generation']
    if not isinstance(generation, dict) or not isinstance(task['evidence_policy_id'], str):
        errors.append('generation_or_evidence_policy_invalid')
    elif (not isinstance(generation.get('budget_sampling'), str) or
          generation.get('feasibility_claim') not in
          ('not_checked', 'witness_verified', 'infeasibility_proof_verified')):
        errors.append('generation_fields_invalid')
    if task['level'] == 'medium' and task.get('medium_variant') not in (
            'paper_main_3_5', 'paper_appendix_2_5'):
        errors.append('medium_variant_invalid')
    if task['task_origin'] == 'human_authored' and not isinstance(task.get('human_source'), dict):
        errors.append('human_source_missing')
    return errors


def _gap(uid, axis, suffix, reason, entity_id=None, detail=None):
    item = {'gap_id': f'cohort-draft:{uid}:{suffix}', 'blocker_class': axis,
            'reason': reason, 'required': True, 'blocking': True,
            'repairable': False}
    if entity_id is not None:
        item['entity_id'] = entity_id
    if detail is not None:
        item['detail'] = detail
    return item


def _error(reason, axis, *, uid='unknown', level='easy', detail=None):
    if level not in ('easy', 'medium', 'human'):
        level = 'easy'
    gap = _gap(uid, axis, reason, reason, detail=detail)
    result = classify({'uid': 'cohort-draft:' + uid, 'city': 'unknown', 'level': level,
                       'gaps': [gap], 'hard_checks': [],
                       'planner': {'supported': False}, 'plan_present': False,
                       'required_checks_complete': False})
    result.update({'label': 'engineering_only', 'engineering_only': True,
                   'formal_score': None, 'frozen': False,
                   'execution_confirmed': False, 'soft_checks': [],
                   'evidence_audits': [], 'candidate_checks': [],
                   'constraint_mapping': {'task_constraint_ids': [],
                       'field_requirements_derived': [], 'reason': reason}})
    return result
