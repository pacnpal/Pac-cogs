"""Video analysis functionality for FFmpeg"""

import os
import subprocess
import logging
import ffmpeg
from pathlib import Path
from typing import Dict, Any
from contextlib import contextmanager
import tempfile
import shutil

logger = logging.getLogger("VideoArchiver")

@contextmanager
def temp_path_context():
    """Context manager for temporary path creation and cleanup"""
    temp_dir = tempfile.mkdtemp(prefix="ffmpeg_")
    try:
        os.chmod(temp_dir, 0o777)
        yield temp_dir
    finally:
        try:
            shutil.rmtree(temp_dir, ignore_errors=True)
        except Exception as e:
            logger.error(f"Error cleaning up temp directory {temp_dir}: {e}")

class VideoAnalyzer:
    def __init__(self, ffmpeg_path: Path):
        self.ffmpeg_path = ffmpeg_path

    def analyze_video(self, input_path: str) -> Dict[str, Any]:
        """Analyze video content for optimal encoding settings"""
        try:
            probe = ffmpeg.probe(input_path)
            video_info = next(s for s in probe["streams"] if s["codec_type"] == "video")

            # Get video properties
            width = int(video_info.get("width", 0))
            height = int(video_info.get("height", 0))
            fps = eval(video_info.get("r_frame_rate", "30/1"))
            duration = float(probe["format"].get("duration", 0))
            bitrate = float(probe["format"].get("bit_rate", 0))

            # Advanced analysis
            has_high_motion = self._detect_high_motion(video_info)
            has_dark_scenes = self._analyze_dark_scenes(input_path)

            # Get audio properties
            audio_info = next(
                (s for s in probe["streams"] if s["codec_type"] == "audio"),
                None
            )
            audio_props = self._get_audio_properties(audio_info)

            return {
                "width": width,
                "height": height,
                "fps": fps,
                "duration": duration,
                "bitrate": bitrate,
                "has_high_motion": has_high_motion,
                "has_dark_scenes": has_dark_scenes,
                "has_complex_scenes": False,  # Reserved for future use
                **audio_props
            }

        except Exception as e:
            logger.error(f"Error analyzing video: {str(e)}")
            return {}

    def _detect_high_motion(self, video_info: Dict) -> bool:
        """Detect high motion content based on frame rate analysis"""
        try:
            if video_info.get("avg_frame_rate"):
                avg_fps = eval(video_info["avg_frame_rate"])
                fps = eval(video_info.get("r_frame_rate", "30/1"))
                return abs(avg_fps - fps) > 5  # Significant frame rate variation
        except Exception as e:
            logger.warning(f"Frame rate analysis failed: {str(e)}")
        return False

    def _analyze_dark_scenes(self, input_path: str) -> bool:
        """Analyze video for dark scenes"""
        try:
            with temp_path_context() as temp_dir:
                sample_cmd = [
                    str(self.ffmpeg_path),
                    "-i", input_path,
                    "-vf", "select='eq(pict_type,I)',signalstats",
                    "-show_entries", "frame_tags=lavfi.signalstats.YAVG",
                    "-f", "null",
                    "-"
                ]
                result = subprocess.run(
                    sample_cmd,
                    capture_output=True,
                    text=True
                )

                dark_frames = 0
                total_frames = 0
                for line in result.stderr.split("\n"):
                    if "YAVG" in line:
                        avg_brightness = float(line.split("=")[1])
                        if avg_brightness < 40:  # Dark scene threshold
                            dark_frames += 1
                        total_frames += 1

                return total_frames > 0 and (dark_frames / total_frames) > 0.2

        except Exception as e:
            logger.warning(f"Dark scene analysis failed: {str(e)}")
            return False

    def _get_audio_properties(self, audio_info: Dict) -> Dict[str, Any]:
        """Extract audio properties from stream info"""
        if not audio_info:
            return {
                "audio_bitrate": 0,
                "audio_channels": 2,
                "audio_sample_rate": 48000
            }

        return {
            "audio_bitrate": int(audio_info.get("bit_rate", 0)),
            "audio_channels": int(audio_info.get("channels", 2)),
            "audio_sample_rate": int(audio_info.get("sample_rate", 48000))
        }
