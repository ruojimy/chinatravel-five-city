"""Select the benchmark sandbox with grounded place rules and map replay."""
from g3_sandbox12_repaired import configure as configure_profile, main
from g3_sandbox12_repaired_v17 import PROFILE as V17

PROFILE = V17.with_name('xiamen12_historical_v19_maps')


def configure(*, planner=False):
    return configure_profile(planner=planner, profile=PROFILE)


if __name__ == '__main__':
    main(PROFILE, allow_trial_date=True)
