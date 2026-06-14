"""
VectorBot — SDK connection, sensor data, and action dispatch.
Uses AsyncRobot; all public action methods that need to block call .result()
on the returned concurrent.futures.Future.
"""

import time
import numpy as np
from PIL import Image
import anki_vector


class Data:
    """Camera frame access."""

    def __init__(self, robot: anki_vector.AsyncRobot):
        self._robot = robot

    def get_numpy_frame(self) -> np.ndarray | None:
        img = self._robot.camera.latest_image
        if img is None:
            return None
        return np.array(img.raw_image)

    def get_pil_frame(self) -> Image.Image | None:
        img = self._robot.camera.latest_image
        if img is None:
            return None
        return img.raw_image


class Action:
    """All robot outputs: motors, animations, eyes, TTS."""

    def __init__(self, robot: anki_vector.AsyncRobot):
        self._robot    = robot
        self._speaking = False
        self._tts      = None   # set via set_tts() after connect

    def set_tts(self, tts) -> None:
        """Attach a TTSEngine; clears with set_tts(None)."""
        self._tts = tts

    # ── Speech ───────────────────────────────────────────────────────────────

    def say_blocking(self, text: str) -> None:
        """
        Speak text and block until the robot finishes.
        Uses custom TTS → stream_wav_file if a TTSEngine is set;
        falls back to Vector's built-in say_text on any error.
        """
        self._speaking = True
        try:
            if self._tts is not None:
                self._say_custom(text)
            else:
                self._say_builtin(text)
        finally:
            self._speaking = False

    def _say_custom(self, text: str) -> None:
        import os
        wav_path = None
        try:
            wav_path = self._tts.synth(text)
            fut = self._robot.audio.stream_wav_file(wav_path)
            if hasattr(fut, "result"):
                fut.result(timeout=30.0)
        except Exception as e:
            print(f"[Action] Custom TTS failed ({e}), falling back to built-in")
            self._say_builtin(text)
        finally:
            if wav_path:
                try:
                    os.unlink(wav_path)
                except OSError:
                    pass

    def _say_builtin(self, text: str) -> None:
        import re
        # Strip any [token] markers that escaped the segment parser
        clean = re.sub(r'\[[^\]]*\]', '', text).strip()
        if not clean:
            return
        try:
            fut = self._robot.behavior.say_text(clean, duration_scalar=0.85)
            if hasattr(fut, "result"):
                fut.result(timeout=30.0)
        except Exception as e:
            print(f"[Action] say_text error: {e}")

    # Keep a non-blocking alias for any legacy callers
    def say(self, text: str) -> None:
        self.say_blocking(text)

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    # ── Animations / emotions ────────────────────────────────────────────────

    def trigger_blocking(
        self,
        trigger_name: str,
        ignore_body_track: bool = True,
    ) -> None:
        """Play an animation trigger and block until it completes."""
        try:
            fut = self._robot.anim.play_animation_trigger(
                trigger_name,
                ignore_body_track=ignore_body_track,
            )
            if hasattr(fut, "result"):
                fut.result(timeout=10.0)
        except Exception as e:
            print(f"[Action] trigger error {trigger_name!r}: {e}")

    def eye_color(self, hue: float, saturation: float) -> None:
        """Set Vector's eye colour."""
        try:
            result = self._robot.behavior.set_eye_color(hue=hue, saturation=saturation)
            if hasattr(result, "result"):
                result.result(timeout=2.0)
        except Exception:
            pass  # non-critical

    def emote(self, emotion: str) -> None:
        """Legacy compatibility — maps old emotion name to trigger_blocking."""
        from src.expressions import get_trigger, get_eye, VECTOR_DEFAULT_EYE
        hue, sat = get_eye(emotion.lower())
        self.eye_color(hue, sat)
        self.trigger_blocking(get_trigger(emotion.lower()))
        self.eye_color(*VECTOR_DEFAULT_EYE)

    # ── Motors ───────────────────────────────────────────────────────────────

    def drive(self, left_speed: float, right_speed: float) -> None:
        fut = self._robot.motors.set_wheel_motors(left_speed, right_speed)
        if hasattr(fut, "result"):
            try:
                fut.result(timeout=2.0)
            except Exception as e:
                print(f"[Action] drive error: {e}")

    def stop(self) -> None:
        fut = self._robot.motors.set_wheel_motors(0, 0)
        if hasattr(fut, "result"):
            try:
                fut.result(timeout=2.0)
            except Exception as e:
                print(f"[Action] stop error: {e}")

    def head(self, speed: float) -> None:
        fut = self._robot.motors.set_head_motor(speed)
        if hasattr(fut, "result"):
            try:
                fut.result(timeout=2.0)
            except Exception:
                pass

    def lift(self, speed: float) -> None:
        fut = self._robot.motors.set_lift_motor(speed)
        if hasattr(fut, "result"):
            try:
                fut.result(timeout=2.0)
            except Exception:
                pass

    # ── High-level timed actions ──────────────────────────────────────────────

    def drive_timed(self, left: float, right: float, secs: float) -> None:
        self.drive(left, right)
        time.sleep(secs)
        self.stop()

    def head_timed(self, speed: float, secs: float) -> None:
        self.head(speed)
        time.sleep(secs)
        self.head(0)

    def lift_timed(self, speed: float, secs: float) -> None:
        self.lift(speed)
        time.sleep(secs)
        self.lift(0)


class Sensors:
    """Poll cached sensor data from the SDK's internal state (updated via robot_state stream)."""

    def __init__(self, robot: anki_vector.AsyncRobot):
        self._robot = robot

    def get_touch(self) -> dict:
        data = self._robot.touch.last_sensor_reading
        if data:
            return {"touched": bool(data.is_being_touched), "raw": int(data.raw_touch_value)}
        return {"touched": False, "raw": 0}

    def get_status(self) -> dict:
        s = self._robot.status
        return {
            "picked_up":  bool(getattr(s, "is_picked_up",        False)),
            "cliff":      bool(getattr(s, "is_cliff_detected",   False)),
            "held":       bool(getattr(s, "is_being_held",       False)),
            "charging":   bool(getattr(s, "is_charging",         False)),
            "on_charger": bool(getattr(s, "is_on_charger",       False)),
        }

    def get_battery(self) -> dict | None:
        """Blocking poll — call from a background thread, not the asyncio loop."""
        try:
            fut = self._robot.get_battery_state()
            b = fut.result(timeout=5.0) if hasattr(fut, "result") else fut
            if b:
                return {
                    "level":      int(b.battery_level),   # 1=Low 2=Nominal 3=Full
                    "volts":      round(float(b.battery_volts), 2),
                    "charging":   bool(b.is_charging),
                    "on_charger": bool(b.is_on_charger_platform),
                }
        except Exception as e:
            print(f"[Sensors] battery poll failed: {e}")
        return None


class VectorBot:
    """
    Top-level robot handle. Call connect() before use, disconnect() when done.
    Exposes .data (camera) and .action (all outputs).
    """

    def __init__(self):
        self.robot: anki_vector.AsyncRobot | None = None
        self.data: Data | None = None
        self.action: Action | None = None
        self.sensors: Sensors | None = None

    def connect(self) -> None:
        args = anki_vector.util.parse_command_args()
        self.robot = anki_vector.AsyncRobot(
            serial=args.serial,
            behavior_activation_timeout=60,
            cache_animation_lists=True,
        )
        self.robot.connect()
        self.robot.camera.init_camera_feed()
        self.data    = Data(self.robot)
        self.action  = Action(self.robot)
        self.sensors = Sensors(self.robot)

        # Startup greeting
        try:
            fut = self.robot.anim.play_animation_trigger("GreetAfterLongTime")
            if hasattr(fut, "result"):
                fut.result(timeout=8.0)
        except Exception:
            pass

    def trigger_list(self) -> list[str]:
        """Return all animation trigger names the robot has (requires cache_animation_lists=True)."""
        try:
            raw = self.robot.anim.anim_trigger_list
            return list(raw) if raw else []
        except Exception as e:
            print(f"[VectorBot] Could not read anim_trigger_list: {e}")
            return []

    def disconnect(self) -> None:
        if self.robot:
            try:
                self.robot.camera.close_camera_feed()
                self.robot.disconnect()
            except Exception:
                pass
