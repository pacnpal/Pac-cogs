"""FFmpeg encoding parameters generator"""

import os
import logging
from typing import Dict, Any

logger = logging.getLogger("VideoArchiver")

class EncoderParams:
    def __init__(self, cpu_cores: int, gpu_info: Dict[str, bool]):
        self.cpu_cores = cpu_cores
        self.gpu_info = gpu_info

    def get_params(self, video_info: Dict[str, Any], target_size_bytes: int) -> Dict[str, str]:
        """Get optimal FFmpeg parameters based on hardware and video analysis"""
        params = self._get_base_params()
        params.update(self._get_content_specific_params(video_info))
        params.update(self._get_gpu_specific_params())
        params.update(self._get_bitrate_params(video_info, target_size_bytes))
        return params

    def _get_base_params(self) -> Dict[str, str]:
        """Get base encoding parameters"""
        return {
            "c:v": "libx264",  # Default to CPU encoding
            "threads": str(self.cpu_cores),
            "preset": "medium",
            "crf": "23",
            "movflags": "+faststart",
            "profile:v": "high",
            "level": "4.1",
            "pix_fmt": "yuv420p",
            "x264opts": "rc-lookahead=60:me=umh:subme=7:ref=4:b-adapt=2:direct=auto",
            "tune": "film",
            "fastfirstpass": "1"
        }

    def _get_content_specific_params(self, video_info: Dict[str, Any]) -> Dict[str, str]:
        """Get parameters optimized for specific content types"""
        params = {}
        
        if video_info.get("has_high_motion"):
            params.update({
                "tune": "grain",
                "x264opts": "rc-lookahead=60:me=umh:subme=7:ref=4:b-adapt=2:direct=auto:deblock=-1,-1:psy-rd=1.0:aq-strength=0.8"
            })

        if video_info.get("has_dark_scenes"):
            x264opts = params.get("x264opts", "rc-lookahead=60:me=umh:subme=7:ref=4:b-adapt=2:direct=auto")
            params.update({
                "x264opts": x264opts + ":aq-mode=3:aq-strength=1.0:deblock=1:1",
                "tune": "film" if not video_info.get("has_high_motion") else "grain"
            })

        return params

    def _get_gpu_specific_params(self) -> Dict[str, str]:
        """Get GPU-specific encoding parameters"""
        if self.gpu_info["nvidia"]:
            return {
                "c:v": "h264_nvenc",
                "preset": "p7",
                "rc:v": "vbr",
                "cq:v": "19",
                "b_ref_mode": "middle",
                "spatial-aq": "1",
                "temporal-aq": "1",
                "rc-lookahead": "32",
                "surfaces": "64",
                "max_muxing_queue_size": "1024",
                "gpu": "any"
            }
        elif self.gpu_info["amd"]:
            return {
                "c:v": "h264_amf",
                "quality": "quality",
                "rc": "vbr_peak",
                "enforce_hrd": "1",
                "vbaq": "1",
                "preanalysis": "1",
                "max_muxing_queue_size": "1024"
            }
        elif self.gpu_info["intel"]:
            return {
                "c:v": "h264_qsv",
                "preset": "veryslow",
                "look_ahead": "1",
                "global_quality": "23",
                "max_muxing_queue_size": "1024"
            }
        return {}

    def _get_bitrate_params(self, video_info: Dict[str, Any], target_size_bytes: int) -> Dict[str, str]:
        """Calculate and get bitrate-related parameters"""
        params = {}
        try:
            duration = video_info.get("duration", 0)
            input_size = video_info.get("bitrate", 0) * duration / 8  # Estimate from bitrate

            if duration > 0 and input_size > target_size_bytes:
                video_size_target = int(target_size_bytes * 0.95)
                total_bitrate = (video_size_target * 8) / duration

                # Audio bitrate calculation
                audio_channels = video_info.get("audio_channels", 2)
                min_audio_bitrate = 64000 * audio_channels
                max_audio_bitrate = 192000 * audio_channels
                audio_bitrate = min(
                    max_audio_bitrate,
                    max(min_audio_bitrate, int(total_bitrate * 0.15))
                )

                # Video bitrate calculation
                video_bitrate = int((video_size_target * 8) / duration - audio_bitrate)

                # Set bitrate constraints
                params["maxrate"] = str(int(video_bitrate * 1.5))
                params["bufsize"] = str(int(video_bitrate * 2))

                # Quality adjustments based on compression ratio
                ratio = input_size / target_size_bytes
                if ratio > 4:
                    params["crf"] = "26" if params.get("c:v", "libx264") == "libx264" else "23"
                    params["preset"] = "faster"
                elif ratio > 2:
                    params["crf"] = "23" if params.get("c:v", "libx264") == "libx264" else "21"
                    params["preset"] = "medium"
                else:
                    params["crf"] = "20" if params.get("c:v", "libx264") == "libx264" else "19"
                    params["preset"] = "slow"

                # Dark scene adjustments
                if video_info.get("has_dark_scenes"):
                    if params.get("c:v", "libx264") == "libx264":
                        params["crf"] = str(max(18, int(params["crf"]) - 2))
                    elif params.get("c:v") == "h264_nvenc":
                        params["cq:v"] = str(max(15, int(params.get("cq:v", "19")) - 2))

                # Audio settings
                params.update({
                    "c:a": "aac",
                    "b:a": f"{int(audio_bitrate/1000)}k",
                    "ar": str(video_info.get("audio_sample_rate", 48000)),
                    "ac": str(video_info.get("audio_channels", 2))
                })

        except Exception as e:
            logger.error(f"Error calculating bitrates: {str(e)}")
            # Use safe default parameters
            params.update({
                "crf": "23",
                "preset": "medium",
                "maxrate": f"{2 * 1024 * 1024}",  # 2 Mbps
                "bufsize": f"{4 * 1024 * 1024}",  # 4 Mbps buffer
                "c:a": "aac",
                "b:a": "128k",
                "ar": "48000",
                "ac": "2"
            })

        return params
