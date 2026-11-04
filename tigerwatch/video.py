"""Bounded local video/camera inspection and anonymous session-only box tracking.

Gemini assessments are sampled/paced, not a 30-FPS object detector. Tracking links
approximate boxes by overlap, not faces/biometrics, across this session only.
"""
from __future__ import annotations

import json
import math
import time
from collections import deque
from pathlib import Path

from .errors import ProviderError, SetupError
from .media import normalize
from .services import classify


def overlap(a, b):
    top, left = max(a[0], b[0]), max(a[1], b[1])
    bottom, right = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, bottom - top) * max(0, right - left)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0


class SessionTracker:
    def __init__(self, *, minimum_overlap=0.2, max_missing=2):
        self.minimum_overlap, self.max_missing = minimum_overlap, max_missing
        self.tracks, self.sequence, self.tick = {}, 0, 0

    def update(self, detections):
        self.tick += 1
        used, results = set(), []
        for detection in detections:
            for box in detection["boxes"]:
                candidates = [(overlap(box, value["box"]), ident) for ident, value in self.tracks.items()
                              if ident not in used and value["target"] == detection["id"]
                              and self.tick - value["seen"] <= self.max_missing]
                best, ident = max(candidates, default=(0, None))
                previous = self.tracks.get(ident) if best >= self.minimum_overlap else None
                if previous is None:
                    self.sequence += 1
                    ident = self.sequence
                motion = None
                if previous:
                    old, new = previous["box"], box
                    motion = math.hypot((old[0] + old[2] - new[0] - new[2]) / 2,
                                        (old[1] + old[3] - new[1] - new[3]) / 2)
                self.tracks[ident] = {"target": detection["id"], "box": box, "seen": self.tick}
                used.add(ident)
                results.append({"session_track": ident, "target": detection["id"], "box": box,
                                "confidence": detection["confidence"], "relative_frame_displacement": motion})
        self.tracks = {k: v for k, v in self.tracks.items() if self.tick - v["seen"] <= self.max_missing}
        return results


def run_video(cfg, state, http, source, *, camera=False, interval=2, max_samples=60,
              capture_factory=None, emit=print, clock=time.monotonic, sleep=time.sleep):
    cfg.require_free()
    cfg.require("GEMINI_API_KEY")
    if not cfg.analysis_rights_confirmed:
        raise SetupError("Confirm AI analysis rights before processing local video")
    if not 1 <= interval <= 60 or not 1 <= max_samples <= 300:
        raise SetupError("Video interval must be 1–60 seconds and sample count 1–300")
    try:
        import cv2
    except ImportError:
        raise SetupError("Video needs: python -m pip install -r requirements-video.txt") from None
    if camera:
        if type(source) is not int or not 0 <= source <= 9:
            raise SetupError("Camera index must be 0–9")
        endpoint = source
    else:
        path = Path(source).expanduser().resolve()
        if not path.is_file() or path.stat().st_size > 512 * 1024 * 1024:
            raise SetupError("Video must be a local file no larger than 512 MB; network URLs are not accepted")
        endpoint = str(path)
    capture = (capture_factory or cv2.VideoCapture)(endpoint)
    if not capture.isOpened():
        capture.release()
        raise SetupError("Cannot open this local video or camera")
    tracker, frames = SessionTracker(), deque(maxlen=3)
    attempts = samples = frames_read = 0
    started, last_sample = clock(), -float("inf")
    rate = capture.get(cv2.CAP_PROP_FPS)
    step = max(1, round((rate if math.isfinite(rate) and rate > 0 else 25) * interval))
    try:
        while samples < max_samples and clock() - started < cfg.max_runtime:
            ok, image = capture.read()
            if not ok:
                break
            frames_read += 1
            if (camera and clock() - last_sample < interval) or (not camera and (frames_read - 1) % step):
                continue
            last_sample = clock()
            encoded, data = cv2.imencode(".jpg", image)
            if not encoded:
                continue
            frames.append(normalize(data.tobytes()))
            samples += 1
            if len(frames) < 3:
                continue
            if attempts >= cfg.ai_run:
                emit(json.dumps({"event": "paused", "reason": "ai_run_budget", "attempts": attempts}))
                break
            cooldown = state.kv_get("cooldown/gemini") or 0
            if type(cooldown) in (int, float) and cooldown > state.clock():
                emit(json.dumps({"event": "paused", "reason": "gemini_cooldown"}))
                break
            budget = state.reserve("ai", cfg.ai_day, cfg.ai_interval)
            if not budget["ok"] and budget["reason"] == "pace":
                sleep(min(60, budget["wait"]) + 0.05)
                budget = state.reserve("ai", cfg.ai_day, cfg.ai_interval)
            if not budget["ok"]:
                emit(json.dumps({"event": "paused", "reason": "ai_" + budget["reason"] + "_budget"}))
                break
            attempts += 1
            try:
                answer = classify(http, cfg, frames[-1], frames=list(frames))
            except ProviderError as exc:
                if exc.stop:
                    state.kv_set("cooldown/gemini", state.clock() + max(300, exc.wait))
                emit(json.dumps({"event": "paused", "reason": str(exc)}))
                break
            tracks = tracker.update(answer["accepted"])
            emit(json.dumps({"event": "assessment", "sample": samples, "match": answer["match"],
                             "detections": answer["detections"], "tracks": tracks,
                             "scores_uncalibrated": True, "tracking_scope": "current_session_only"}))
    finally:
        capture.release()
        frames.clear()
    return {"samples": samples, "ai_attempts": attempts, "frames_read": frames_read}
