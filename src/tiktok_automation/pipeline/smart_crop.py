from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from tiktok_automation.config import Settings
from tiktok_automation.utils import run_command


@dataclass
class FocusSample:
    time_seconds: float
    center_x: float
    source: str


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _load_face_detector():
    import cv2

    detector = cv2.CascadeClassifier(cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
    if detector.empty():
        raise RuntimeError("Nao foi possivel carregar o detector facial do OpenCV.")
    return detector


def _detect_faces(frame, detector) -> list[tuple[float, float]]:
    import cv2

    source_height, source_width = frame.shape[:2]
    resize_scale = 1.0
    working = frame
    if source_width > 960:
        resize_scale = 960 / source_width
        working = cv2.resize(frame, (int(source_width * resize_scale), int(source_height * resize_scale)))

    gray = cv2.cvtColor(working, cv2.COLOR_BGR2GRAY)
    faces = detector.detectMultiScale(
        gray,
        scaleFactor=1.12,
        minNeighbors=5,
        minSize=(56, 56),
    )

    detections: list[tuple[float, float]] = []
    for x, y, width, height in faces:
        center_x = (x + width / 2.0) / resize_scale
        area = (width * height) / (resize_scale * resize_scale)
        detections.append((center_x, area))
    return detections


def _motion_focus(previous_gray, current_gray) -> float | None:
    import cv2
    import numpy as np

    diff = cv2.absdiff(previous_gray, current_gray)
    diff = cv2.GaussianBlur(diff, (5, 5), 0)
    _, threshold = cv2.threshold(diff, 18, 255, cv2.THRESH_BINARY)
    points = np.column_stack(np.where(threshold > 0))
    if len(points) < 1200:
        return None
    return float(points[:, 1].mean())


def _sample_focus_track(
    source_video_path: str,
    sample_fps: float = 4.0,
) -> tuple[list[FocusSample], float, int, int]:
    import cv2

    detector = _load_face_detector()
    capture = cv2.VideoCapture(str(source_video_path))
    if not capture.isOpened():
        raise RuntimeError("Nao foi possivel abrir o video para smart crop.")

    fps = capture.get(cv2.CAP_PROP_FPS) or 29.97
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    if width <= 0 or height <= 0:
        capture.release()
        raise RuntimeError("Nao foi possivel ler as dimensoes do video para smart crop.")

    samples: list[FocusSample] = []
    previous_gray = None
    previous_center_x: float | None = None
    duration_seconds = (capture.get(cv2.CAP_PROP_FRAME_COUNT) or 0) / fps
    sample_count = max(1, int(duration_seconds * sample_fps) + 1)

    try:
        for index in range(sample_count):
            elapsed = min(duration_seconds, index / sample_fps)
            capture.set(cv2.CAP_PROP_POS_MSEC, elapsed * 1000)
            ok, frame = capture.read()
            if not ok:
                break

            faces = _detect_faces(frame, detector)
            if faces:
                anchor = previous_center_x if previous_center_x is not None else width / 2.0
                chosen_center_x, _ = max(
                    faces,
                    key=lambda item: item[1] - abs(item[0] - anchor) * 1.35,
                )
                previous_center_x = chosen_center_x
                source = "face"
            else:
                working_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                motion_center = _motion_focus(previous_gray, working_gray) if previous_gray is not None else None
                previous_gray = working_gray
                if motion_center is not None:
                    previous_center_x = motion_center
                    source = "motion"
                elif previous_center_x is not None:
                    source = "hold"
                else:
                    previous_center_x = width / 2.0
                    source = "center"

            samples.append(
                FocusSample(
                    time_seconds=elapsed,
                    center_x=previous_center_x,
                    source=source,
                )
            )
    finally:
        capture.release()

    return samples, fps, width, height


def _smoothed_crop_positions(
    samples: list[FocusSample],
    frame_count: int,
    fps: float,
    crop_width: int,
    source_width: int,
) -> list[int]:
    if not samples:
        center = max(0, (source_width - crop_width) // 2)
        return [center for _ in range(frame_count)]

    smoothed: list[tuple[float, float]] = []
    previous_x: float | None = None
    previous_time: float | None = None

    for sample in samples:
        raw_x = _clamp(sample.center_x - crop_width / 2.0, 0.0, max(0.0, source_width - crop_width))
        if previous_x is None or previous_time is None:
            current_x = raw_x
        else:
            delta_t = max(0.001, sample.time_seconds - previous_time)
            max_step = crop_width * 0.55 * delta_t
            limited_x = previous_x + _clamp(raw_x - previous_x, -max_step, max_step)
            current_x = previous_x * 0.72 + limited_x * 0.28
        smoothed.append((sample.time_seconds, current_x))
        previous_x = current_x
        previous_time = sample.time_seconds

    positions: list[int] = []
    sample_index = 0
    for frame_index in range(frame_count):
        current_time = frame_index / fps
        while sample_index + 1 < len(smoothed) and smoothed[sample_index + 1][0] <= current_time:
            sample_index += 1

        if sample_index + 1 < len(smoothed):
            left_time, left_x = smoothed[sample_index]
            right_time, right_x = smoothed[sample_index + 1]
            span = max(0.001, right_time - left_time)
            weight = _clamp((current_time - left_time) / span, 0.0, 1.0)
            current_x = left_x + (right_x - left_x) * weight
        else:
            current_x = smoothed[sample_index][1]

        positions.append(int(round(_clamp(current_x, 0.0, max(0.0, source_width - crop_width)))))

    return positions


def _extract_audio_segment(
    working_clip_path: Path,
    output_audio_path: Path,
    settings: Settings,
) -> None:
    run_command(
        [
            settings.ffmpeg_binary,
            "-y",
            "-i",
            str(working_clip_path),
            "-vn",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            str(output_audio_path),
        ]
    )


def _create_working_clip(
    source_video_path: str,
    working_clip_path: Path,
    start_seconds: float,
    duration_seconds: float,
    settings: Settings,
) -> None:
    run_command(
        [
            settings.ffmpeg_binary,
            "-y",
            "-ss",
            f"{start_seconds:.3f}",
            "-i",
            source_video_path,
            "-t",
            f"{duration_seconds:.3f}",
            "-c:v",
            "mpeg4",
            "-q:v",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            str(working_clip_path),
        ]
    )


def render_smart_cropped_segment(
    source_video_path: str,
    output_video_path: Path,
    start_seconds: float,
    duration_seconds: float,
    settings: Settings,
) -> bool:
    import cv2

    working_clip = output_video_path.with_suffix(".smartcrop.source.mp4")
    _create_working_clip(
        source_video_path=source_video_path,
        working_clip_path=working_clip,
        start_seconds=start_seconds,
        duration_seconds=duration_seconds,
        settings=settings,
    )

    samples, fps, source_width, source_height = _sample_focus_track(
        source_video_path=str(working_clip),
    )

    if source_width <= 0 or source_height <= 0:
        working_clip.unlink(missing_ok=True)
        return False

    if source_width / source_height < (9 / 16):
        working_clip.unlink(missing_ok=True)
        return False

    crop_width = min(source_width, int(round(source_height * 9 / 16)))
    frame_count = max(1, int(round(duration_seconds * fps)))
    crop_positions = _smoothed_crop_positions(
        samples=samples,
        frame_count=frame_count,
        fps=fps,
        crop_width=crop_width,
        source_width=source_width,
    )

    capture = cv2.VideoCapture(str(working_clip))
    if not capture.isOpened():
        working_clip.unlink(missing_ok=True)
        return False

    temp_video = output_video_path.with_suffix(".smartcrop.video.mp4")
    temp_audio = output_video_path.with_suffix(".smartcrop.audio.m4a")
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(temp_video), fourcc, fps, (1080, 1920))
    if not writer.isOpened():
        capture.release()
        working_clip.unlink(missing_ok=True)
        return False

    capture.set(cv2.CAP_PROP_POS_FRAMES, 0)

    try:
        written_frames = 0
        for frame_index in range(frame_count):
            ok, frame = capture.read()
            if not ok:
                break
            x = crop_positions[min(frame_index, len(crop_positions) - 1)]
            cropped = frame[:, x : x + crop_width]
            resized = cv2.resize(cropped, (1080, 1920), interpolation=cv2.INTER_AREA)
            writer.write(resized)
            written_frames += 1
    finally:
        writer.release()
        capture.release()

    if written_frames == 0:
        temp_video.unlink(missing_ok=True)
        working_clip.unlink(missing_ok=True)
        return False

    _extract_audio_segment(
        working_clip_path=working_clip,
        output_audio_path=temp_audio,
        settings=settings,
    )

    run_command(
        [
            settings.ffmpeg_binary,
            "-y",
            "-i",
            str(temp_video),
            "-i",
            str(temp_audio),
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-map",
            "0:v:0",
            "-map",
            "1:a:0",
            "-shortest",
            "-movflags",
            "+faststart",
            str(output_video_path),
        ]
    )

    temp_video.unlink(missing_ok=True)
    temp_audio.unlink(missing_ok=True)
    working_clip.unlink(missing_ok=True)
    return True
