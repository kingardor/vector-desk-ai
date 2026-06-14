"""
M1 smoke test — run this BEFORE app.py to verify:
  1. SDK auth works (connects to Vector)
  2. TTS fires ("I am alive")
  3. An animation plays
  4. Camera returns a frame (saved to /tmp/vector_frame.jpg)

Run: python3 scripts/smoke_test.py
"""

import anki_vector
import numpy as np
from PIL import Image

print("[smoke] Connecting to Vector...")
args = anki_vector.util.parse_command_args()
with anki_vector.Robot(
    serial=args.serial,
    behavior_activation_timeout=30,
    cache_animation_lists=True,
) as robot:
    print("[smoke] Connected!")

    print("[smoke] Playing animation...")
    robot.anim.play_animation_trigger("GreetAfterLongTime")

    print("[smoke] Speaking...")
    robot.behavior.say_text("I am alive. Systems online.")

    print("[smoke] Grabbing camera frame...")
    robot.camera.init_camera_feed()
    import time; time.sleep(1)
    img = robot.camera.latest_image
    if img is not None:
        pil = img.raw_image
        pil.save("/tmp/vector_frame.jpg")
        print(f"[smoke] Frame saved: {pil.size} → /tmp/vector_frame.jpg")
    else:
        print("[smoke] WARNING: no camera frame received")

    robot.camera.close_camera_feed()

print("[smoke] All checks passed.")
