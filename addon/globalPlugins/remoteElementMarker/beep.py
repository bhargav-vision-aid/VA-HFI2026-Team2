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

try:
	import tones  # type: ignore
except Exception:
	tones = None

_FREQ_SUCCESS = 1200
_FREQ_FAILURE = 300
_FREQ_PROGRESS = 800

_DUR_SUCCESS = 80
_DUR_FAILURE = 120
_DUR_PROGRESS = 40

_PROGRESS_INTERVAL_MS = 400


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
	Emits a repeating progress beep (every 400 ms) until stopped.

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
		self._timer: "wx.CallLater | None" = None
		self._running = False

	def start(self) -> None:
		if self._running:
			return
		self._running = True
		self._schedule()

	def stop(self) -> None:
		self._running = False
		t = self._timer
		self._timer = None
		if t is not None:
			try:
				if t.IsRunning():
					t.Stop()
			except Exception:
				pass

	def _schedule(self) -> None:
		if not self._running:
			return
		try:
			self._timer = wx.CallLater(_PROGRESS_INTERVAL_MS, self._tick)
		except Exception:
			self._running = False

	def _tick(self) -> None:
		self._timer = None
		if not self._running:
			return
		_beep(_FREQ_PROGRESS, _DUR_PROGRESS)
		self._schedule()
