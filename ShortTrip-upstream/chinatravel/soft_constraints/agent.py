"""Opt-in extension: original DFS + original validation + 20-plan soft selection."""
import copy
import time

from chinatravel.agent.nesy_agent.llm_driven_rec import LLMDrivenAgent
from .pool import CandidatePool
from .scoring import SoftConfig, score_plan


class CandidateCollectionComplete(Exception):
    pass


class CandidateDeadline(Exception):
    pass


class SoftLLMDrivenAgent(LLMDrivenAgent):
    def __init__(self, *, candidate_limit=20, soft_config=None, wall_limit_seconds=None,
                 on_candidate=None, **kwargs):
        super().__init__(**kwargs)
        self.soft_config = soft_config or SoftConfig()
        self.candidate_limit = candidate_limit
        self.wall_limit_seconds = wall_limit_seconds
        self.on_candidate = on_candidate
        # Original first-solution timeout must not prematurely end collection mode A.
        # This setting applies only to this opt-in subclass.
        self.TIME_CUT = float('inf')
        self._route_cache = {}
        self.pool = CandidatePool(candidate_limit, self._score)

    def _route(self, city, start, end, start_time, mode):
        key = (city, start, end, start_time, mode)
        if key not in self._route_cache:
            self._route_cache[key] = self.env.transportation.goto(city, start, end, start_time, mode)
        return self._route_cache[key]

    def _score(self, plan):
        return score_plan(plan, config=self.soft_config, route_resolver=self._route)

    def _deadline_check(self):
        if self.wall_limit_seconds is not None and time.monotonic() - self.soft_started >= self.wall_limit_seconds:
            raise CandidateDeadline()

    def dfs_poi(self, *args, **kwargs):
        self._deadline_check()
        return super().dfs_poi(*args, **kwargs)

    def constraints_validation(self, query, plan, poi_plan):
        # Both complete-plan validation call sites dispatch through this override.
        valid, result = super().constraints_validation(query, plan, poi_plan)
        if valid:
            if self.pool.add(result):
                self.pool.items[-1]['validation'] = {'original_commonsense': True, 'translated_hard_constraints': True}
                print(f'SOFT_CANDIDATE {len(self.pool.items)}/{self.pool.limit} '
                      f'penalty={self.pool.items[-1]["score"]["total_penalty"]}', flush=True)
                if self.on_candidate:
                    self.on_candidate(self.pool)
            if self.pool.full:
                raise CandidateCollectionComplete()
            # Return the original mutable working plan for ordinary DFS backtracking.
            return False, plan
        return valid, result

    def run(self, query, load_cache=False, oralce_translation=False, preference_search=False):
        if oralce_translation or preference_search:
            raise ValueError('Soft candidate mode does not expose Oracle or replace its objective with legacy preference search')
        self.soft_started = time.monotonic()
        self.pool = CandidatePool(self.candidate_limit, self._score)
        reason, base_result = 'search_exhausted', {}
        try:
            _, base_result = super().run(query, load_cache=load_cache,
                                         oralce_translation=False, preference_search=False)
        except CandidateCollectionComplete:
            reason = 'candidate_limit_reached'
        except CandidateDeadline:
            reason = 'wall_limit_reached'
        winner = self.pool.best()
        self.selection = {'candidate_target': self.candidate_limit, 'candidate_count': len(self.pool.items),
                          'complete': self.pool.full, 'stop_reason': reason,
                          'selected_ordinal': winner['ordinal'] if winner else None,
                          'selected_fingerprint': winner['fingerprint'] if winner else None,
                          'minimum_penalty': winner['score']['total_penalty'] if winner else None,
                          'duplicate_count': self.pool.duplicate_count,
                          'elapsed_seconds': time.monotonic() - self.soft_started,
                          'configuration': self.soft_config.__dict__,
                          'wall_limit_seconds': self.wall_limit_seconds,
                          'prune_counts': getattr(self, 'prune_counts', {}),
                          'prune_examples': getattr(self, 'prune_examples', {})}
        result = copy.deepcopy(winner['plan']) if winner else {}
        # Do not use super.run's least_plan_logic fallback as the selected itinerary.
        for name in ('search_nodes', 'backtrack_count', 'constraints_validation_count',
                     'commonsense_pass_count', 'logical_pass_count', 'all_constraints_pass',
                     'llm_rec_count', 'llm_rec_format_error'):
            result[name] = getattr(self, name, 0)
        result.update(input_token_count=self.backbone_llm.input_token_count,
                      output_token_count=self.backbone_llm.output_token_count,
                      input_token_maxx=self.backbone_llm.input_token_maxx,
                      search_time_sec=time.monotonic() - self.soft_started,
                      llm_inference_time_sec=getattr(self, 'llm_inference_time_count', 0))
        return winner is not None, result
