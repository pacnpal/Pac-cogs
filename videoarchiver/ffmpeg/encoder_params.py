"""FFmpeg encoding parameters generator"""

import os
import logging
from typing import Dict, Any
from .exceptions import CompressionError, QualityError, BitrateError

logger = logging.getLogger("VideoArchiver")

class EncoderParams:
    """Manages FFmpeg encoding parameters based on hardware and content"""

    # Quality presets based on content type
    QUALITY_PRESETS = {
        "gaming": {
            "crf": "20",
            "preset": "fast",
            "tune": "zerolatency",
            "x264opts": "rc-lookahead=20:me=hex:subme=6:ref=3:b-adapt=1:direct=spatial"
        },
        "animation": {
            "crf": "18",
            "preset": "slow",
            "tune": "animation",
            "x264opts": "rc-lookahead=60:me=umh:subme=9:ref=6:b-adapt=2:direct=auto:deblock=-1,-1"
        },
        "film": {
            "crf": "22",
            "preset": "medium",
            "tune": "film",
            "x264opts": "rc-lookahead=50:me=umh:subme=8:ref=4:b-adapt=2:direct=auto"
        }
    }

    # Minimum bitrates to ensure quality
    MIN_VIDEO_BITRATE = 500_000  # 500 Kbps
    MIN_AUDIO_BITRATE = 64_000   # 64 Kbps per channel
    MAX_AUDIO_BITRATE = 192_000  # 192 Kbps per channel

    def __init__(self, cpu_cores: int, gpu_info: Dict[str, bool]):
        """Initialize encoder parameters manager
        
        Args:
            cpu_cores: Number of available CPU cores
            gpu_info: Dict containing GPU availability information
        """
        self.cpu_cores = cpu_cores
        self.gpu_info = gpu_info
        logger.info(f"Initialized encoder with {cpu_cores} CPU cores and GPU info: {gpu_info}")

    def get_params(self, video_info: Dict[str, Any], target_size_bytes: int) -> Dict[str, str]:
        """Get optimal FFmpeg parameters based on hardware and video analysis"""
        try:
            # Get base parameters
            params = self._get_base_params()
            logger.debug(f"Base parameters: {params}")

            # Update with content-specific parameters
            content_params = self._get_content_specific_params(video_info)
            params.update(content_params)
            logger.debug(f"Content-specific parameters: {content_params}")

            # Update with GPU-specific parameters if available
            gpu_params = self._get_gpu_specific_params()
            if gpu_params:
                params.update(gpu_params)
                logger.debug(f"GPU-specific parameters: {gpu_params}")

            # Calculate and update bitrate parameters
            bitrate_params = self._get_bitrate_params(video_info, target_size_bytes)
            params.update(bitrate_params)
            logger.debug(f"Bitrate parameters: {bitrate_params}")

            # Validate final parameters
            self._validate_params(params, video_info)
            
            logger.info(f"Final encoding parameters: {params}")
            return params

        except Exception as e:
            logger.error(f"Error generating encoding parameters: {str(e)}")
            # Return safe default parameters
            return self._get_safe_defaults()

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
        
        # Detect content type
        content_type = self._detect_content_type(video_info)
        if content_type in self.QUALITY_PRESETS:
            params.update(self.QUALITY_PRESETS[content_type])

        # Additional optimizations based on content analysis
        if video_info.get("has_high_motion", False):
            params.update({
                "tune": "grain",
                "x264opts": "rc-lookahead=60:me=umh:subme=7:ref=4:b-adapt=2:direct=auto:deblock=-1,-1:psy-rd=1.0:aq-strength=0.8"
            })

        if video_info.get("has_dark_scenes", False):
            x264opts = params.get("x264opts", "rc-lookahead=60:me=umh:subme=7:ref=4:b-adapt=2:direct=auto")
            params.update({
                "x264opts": x264opts + ":aq-mode=3:aq-strength=1.0:deblock=1:1",
                "tune": "film" if not video_info.get("has_high_motion") else "grain"
            })

        return params

    def _get_gpu_specific_params(self) -> Dict[str, str]:
        """Get GPU-specific encoding parameters"""
        if self.gpu_info.get("nvidia", False):
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
        elif self.gpu_info.get("amd", False):
            return {
                "c:v": "h264_amf",
                "quality": "quality",
                "rc": "vbr_peak",
                "enforce_hrd": "1",
                "vbaq": "1",
                "preanalysis": "1",
                "max_muxing_queue_size": "1024"
            }
        elif self.gpu_info.get("intel", False):
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
            duration = float(video_info.get("duration", 0))
            if duration <= 0:
                raise ValueError("Invalid video duration")

            # Calculate target bitrate based on file size
            total_bitrate = int((target_size_bytes * 8) / duration)

            # Handle audio bitrate
            audio_channels = int(video_info.get("audio_channels", 2))
            audio_bitrate = min(
                self.MAX_AUDIO_BITRATE * audio_channels,
                max(self.MIN_AUDIO_BITRATE * audio_channels, int(total_bitrate * 0.1))
            )

            # Calculate video bitrate, ensuring it doesn't go below minimum
            video_bitrate = max(self.MIN_VIDEO_BITRATE, total_bitrate - audio_bitrate)

            # Set video bitrate constraints
            params.update({
                "b:v": f"{int(video_bitrate)}",
                "maxrate": f"{int(video_bitrate * 1.5)}",
                "bufsize": f"{int(video_bitrate * 2)}"
            })

            # Set audio parameters
            params.update({
                "c:a": "aac",
                "b:a": f"{int(audio_bitrate/1000)}k",
                "ar": "48000",  # Standard audio sample rate
                "ac": str(audio_channels)
            })

            # Adjust CRF based on target size
            input_bitrate = int(video_info.get("bitrate", 0))
            if input_bitrate > 0:
                compression_ratio = input_bitrate / video_bitrate
                if compression_ratio > 4:
                    params["crf"] = "26"
                    params["preset"] = "faster"
                elif compression_ratio > 2:
                    params["crf"] = "23"
                    params["preset"] = "medium"
                else:
                    params["crf"] = "20"
                    params["preset"] = "slow"

            logger.info(f"Calculated bitrates - Video: {video_bitrate}bps, Audio: {audio_bitrate}bps")
            return params

        except Exception as e:
            logger.error(f"Error calculating bitrates: {str(e)}")
            # Use safe default parameters
            return {
                "c:a": "aac",
                "b:a": "128k",
                "ar": "48000",
                "ac": "2",
                "crf": "23"  # Use CRF mode instead of bitrate when calculation fails
            }

    def _detect_content_type(self, video_info: Dict[str, Any]) -> str:
        """Detect content type based on video analysis"""
        try:
            # Check for gaming content
            if video_info.get("has_high_motion", False) and video_info.get("fps", 0) >= 60:
                return "gaming"
                
            # Check for animation
            if video_info.get("has_sharp_edges", False) and not video_info.get("has_film_grain", False):
                return "animation"
                
            # Default to film
            return "film"
            
        except Exception as e:
            logger.error(f"Error detecting content type: {str(e)}")
            return "film"

    def _validate_params(self, params: Dict[str, str], video_info: Dict[str, Any]) -> None:
        """Validate encoding parameters"""
        try:
            # Check for required parameters
            required_params = ["c:v", "preset", "pix_fmt"]
            missing_params = [p for p in required_params if p not in params]
            if missing_params:
                raise ValueError(f"Missing required parameters: {missing_params}")

            # Validate video codec
            if params["c:v"] not in ["libx264", "h264_nvenc", "h264_amf", "h264_qsv"]:
                raise ValueError(f"Invalid video codec: {params['c:v']}")

            # Validate preset
            valid_presets = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow", "p1", "p2", "p3", "p4", "p5", "p6", "p7"]
            if params["preset"] not in valid_presets:
                raise ValueError(f"Invalid preset: {params['preset']}")

            # Validate pixel format
            if params["pix_fmt"] not in ["yuv420p", "nv12", "yuv444p"]:
                raise ValueError(f"Invalid pixel format: {params['pix_fmt']}")

            # Validate audio parameters
            if "c:a" in params and params["c:a"] == "aac":
                if "b:a" not in params:
                    raise ValueError("Missing audio bitrate parameter")
                if "ar" not in params:
                    raise ValueError("Missing audio sample rate parameter")
                if "ac" not in params:
                    raise ValueError("Missing audio channels parameter")

        except Exception as e:
            logger.error(f"Parameter validation failed: {str(e)}")
            raise

    def _get_safe_defaults(self) -> Dict[str, str]:
        """Get safe default encoding parameters"""
        return {
            "c:v": "libx264",
            "preset": "medium",
            "crf": "23",
            "pix_fmt": "yuv420p",
            "profile:v": "high",
            "level": "4.1",
            "c:a": "aac",
            "b:a": "128k",
            "ar": "48000",
            "ac": "2"
        }
