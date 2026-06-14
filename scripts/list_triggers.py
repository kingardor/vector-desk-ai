"""
Dump all animation trigger names available on the connected Vector robot.

Run:
    source vector/bin/activate
    python3 scripts/list_triggers.py

Prints the full sorted list so you can pick triggers for expressions.py.
"""

import anki_vector

print("[list_triggers] Connecting to Vector...")
args = anki_vector.util.parse_command_args()
with anki_vector.Robot(
    serial=args.serial,
    behavior_activation_timeout=30,
    cache_animation_lists=True,
) as robot:
    raw = robot.anim.anim_trigger_list
    triggers = sorted(raw)
    print(f"\nFound {len(triggers)} animation triggers on this robot:\n")
    for i, t in enumerate(triggers, 1):
        print(f"  {i:3}. {t}")
    print(f"\nTotal: {len(triggers)}")
    print("\nCopy any of these into the TRIGGERS dict in src/expressions.py")
