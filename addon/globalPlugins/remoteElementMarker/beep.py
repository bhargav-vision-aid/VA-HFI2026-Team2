# -*- coding: UTF-8 -*-
# Remote Element Marker — audio feedback helpers
# Copyright (C) 2025 Team 2
# Released under GPL 2

"""
Thin wrappers around NVDA's tones.beep() for consistent audio feedback.

Pitch / duration conventions
------------------------------
Success (save / resolve):  1200 Hz, 80 ms  — bright, short, upward feel
Failure (save / resolve):   300 Hz, 120 ms — low, slightly longer, "thud"
Progress tick:              800 Hz, 40 ms  — neutral mid-pitch, brief

All public functions are safe to call from the NVDA main thread.
They swallow every exception so a missing tones module never crashes the add-on.
"""

import wx  # type: ignore
import threading
import time

try:
    import tones  # type: ignore
except Exception:
    tones = None

_FREQ_SUCCESS = 1200
_FREQ_FAILURE = 300
_FREQ_PROGRESS = 440
_FREQ_PROGRESS_START = 320
_FREQ_PROGRESS_STEP = 70
_FREQ_PROGRESS_MAX = 1760

_DUR_SUCCESS = 80
_DUR_FAILURE = 120
_DUR_PROGRESS = 40

_PROGRESS_INTERVAL_MS = 1000


def _beep(freq: int, duration: int) -> None:
    try:
        if tones:
            tones.beep(freq, duration)
    except Exception:
        pass


def beep_success() -> None:
    """High-pitch beep: element saved or resolved successfully."""
    _beep(_FREQ_SUCCESS, _DUR_SUCCESS)


def beep_failure() -> None:
    """Low-pitch beep: save failed or element could not be resolved."""
    _beep(_FREQ_FAILURE, _DUR_FAILURE)


# ------------------------------------------------------------------ #
# Progress beeper                                                     #
# ------------------------------------------------------------------ #


class ProgressBeeper:
    """
    Emits rising progress tones from a worker thread until stopped.

    Usage::

            pb = ProgressBeeper()
            pb.start()
            # ... do async work ...
            pb.stop()
            beep_success()   # or beep_failure()

    Only one instance should be active at a time; call stop() before
    discarding or replacing it.
    """

    def __init__(self) -> None:
        self._thread: "threading.Thread | None" = None
        self._running = False
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._pause_event.set()
        self._cancelled = False
        self._timeout_requested = False
        self._timeout_seconds = 40
        self._next_prompt_second = self._timeout_seconds
        self._elapsed_active_seconds = 0
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._stop_event.clear()
        self._pause_event.set()
        self._cancelled = False
        self._timeout_requested = False
        self._elapsed_active_seconds = 0
        self._next_prompt_second = self._timeout_seconds
        _beep(_FREQ_PROGRESS_START, _DUR_PROGRESS)
        self._thread = threading.Thread(
            target=self._run, name="REMProgressBeeper", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        self._stop_event.set()
        self._pause_event.set()
        t = self._thread
        self._thread = None
        if t is not None and t.is_alive():
            t.join(0.2)

    def checkpoint(self) -> bool:
        while True:
            if self._cancelled:
                return False
            if self._pause_event.is_set():
                return True
            if self._stop_event.wait(0.05):
                return False

    def consume_timeout_request(self) -> bool:
        with self._lock:
            if not self._timeout_requested:
                return False
            self._timeout_requested = False
            return True

    def resume(self) -> None:
        self._pause_event.set()

    def cancel(self) -> None:
        self._cancelled = True
        self._stop_event.set()
        self._pause_event.set()

    def is_cancelled(self) -> bool:
        return self._cancelled

    def _run(self) -> None:
        while not self._stop_event.is_set():
            if not self._pause_event.wait(0.1):
                continue
            if self._stop_event.wait(_PROGRESS_INTERVAL_MS / 1000.0):
                return
            if not self._pause_event.is_set():
                continue
            self._elapsed_active_seconds += 1
            freq = min(
                _FREQ_PROGRESS_START
                + max(0, self._elapsed_active_seconds - 1) * _FREQ_PROGRESS_STEP,
                _FREQ_PROGRESS_MAX,
            )
            _beep(freq, _DUR_PROGRESS)
            if self._elapsed_active_seconds >= self._next_prompt_second:
                with self._lock:
                    self._timeout_requested = True
                self._next_prompt_second += self._timeout_seconds
                self._pause_event.clear()
