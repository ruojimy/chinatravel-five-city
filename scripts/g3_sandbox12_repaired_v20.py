"""Select the V20 catalog completion and explicitly dated transport observations."""
from g3_sandbox12_repaired import configure as configure_profile, main
from g3_sandbox12_repaired_v19 import PROFILE as V19

PROFILE = V19.with_name('xiamen12_historical_v20_completion')


def configure(*, planner=False):
    return configure_profile(planner=planner, profile=PROFILE)


if __name__ == '__main__':
    main(PROFILE, allow_trial_date=True)
