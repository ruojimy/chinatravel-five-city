"""Select the twelve-city sandbox with verified intercity arrival-day scoring."""
from g3_sandbox12_repaired import TIMELINE_PROFILE as PROFILE
from g3_sandbox12_repaired import configure as configure_profile, main


def configure(*, planner=False):
    return configure_profile(planner=planner, profile=PROFILE)


if __name__ == '__main__':
    main(PROFILE)
