import os
import sys
import platform
import subprocess
import logging
import shutil
import requests
import zipfile
import tarfile
from pathlib import Path
import stat
import multiprocessing
import ffmpeg
import tempfile
import json

logger = logging.getLogger("VideoArchiver")


class FFmpegManager:
    FFMPEG_URLS = {
        "Windows": {
            "x86_64": {
                "url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip",
                "bin_name": "ffmpeg.exe",
            }
        },
        "Linux": {
            "x86_64": {
                "url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz",
                "bin_name": "ffmpeg",
            },
            "aarch64": {  # ARM64
                "url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linuxarm64-gpl.tar.xz",
                "bin_name": "ffmpeg",
            },
            "armv7l": {  # ARM32
                "url": "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linuxarm32-gpl.tar.xz",
                "bin_name": "ffmpeg",
            },
        },
        "Darwin": {  # macOS
            "x86_64": {
                "url": "https://evermeet.cx/ffmpeg/getrelease/zip",
                "bin_name": "ffmpeg",
            },
            "arm64": {  # Apple Silicon
                "url": "https://evermeet.cx/ffmpeg/getrelease/zip",
                "bin_name": "ffmpeg",
            },
        },
    }

    def __init__(self):
        self.base_path = Path(__file__).parent / "bin"
        self.base_path.mkdir(exist_ok=True)

        # Get system architecture
        self.system = platform.system()
        self.machine = platform.machine().lower()
        if self.machine == "arm64":
            self.machine = "aarch64"  # Normalize ARM64 naming

        # Try to use system FFmpeg first
        system_ffmpeg = shutil.which("ffmpeg")
        if system_ffmpeg:
            self.ffmpeg_path = Path(system_ffmpeg)
            logger.info(f"Using system FFmpeg: {self.ffmpeg_path}")
        else:
            # Check for existing FFmpeg in our bin directory
            try:
                arch_config = self.FFMPEG_URLS[self.system][self.machine]
                self.ffmpeg_path = self.base_path / arch_config["bin_name"]
                if not self.ffmpeg_path.exists():
                    # Only download if FFmpeg doesn't exist
                    self._download_ffmpeg()
                    if not self._verify_ffmpeg():
                        raise Exception("Downloaded FFmpeg binary is not functional")
                elif not self._verify_ffmpeg():
                    logger.warning(
                        "Existing FFmpeg binary not functional, downloading new copy"
                    )
                    self._download_ffmpeg()
                    if not self._verify_ffmpeg():
                        raise Exception("Downloaded FFmpeg binary is not functional")
            except KeyError:
                raise Exception(
                    f"Unsupported system/architecture: {self.system}/{self.machine}"
                )

        self._gpu_info = self._detect_gpu()
        self._cpu_cores = multiprocessing.cpu_count()

    def _verify_ffmpeg(self) -> bool:
        """Verify FFmpeg binary works"""
        try:
            if not self.ffmpeg_path.exists():
                return False

            # Make binary executable on Unix systems
            if self.system != "Windows":
                try:
                    self.ffmpeg_path.chmod(
                        self.ffmpeg_path.stat().st_mode | stat.S_IEXEC
                    )
                except Exception as e:
                    logger.error(
                        f"Failed to set FFmpeg executable permissions: {str(e)}"
                    )
                    return False

            # Test FFmpeg and check for required encoders
            result = subprocess.run(
                [str(self.ffmpeg_path), "-encoders"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
            )
            
            if result.returncode != 0:
                return False

            # Verify encoders are available
            encoders = result.stdout.decode()
            required_encoders = ["libx264"]  # Base requirement
            if self._gpu_info["nvidia"]:
                required_encoders.append("h264_nvenc")
            if self._gpu_info["amd"]:
                required_encoders.append("h264_amf")
            if self._gpu_info["intel"]:
                required_encoders.append("h264_qsv")

            for encoder in required_encoders:
                if encoder not in encoders:
                    logger.warning(f"Required encoder {encoder} not available")
                    if encoder != "libx264":  # Only warn for GPU encoders
                        self._gpu_info[encoder.split('_')[1].replace('h264', '')] = False

            return True
        except Exception as e:
            logger.error(f"FFmpeg verification failed: {str(e)}")
            return False

    def _detect_gpu(self) -> dict:
        """Detect available GPU and its capabilities"""
        gpu_info = {"nvidia": False, "amd": False, "intel": False, "arm": False}

        try:
            if self.system == "Linux":
                # Check for NVIDIA GPU
                try:
                    nvidia_smi = subprocess.run(
                        ["nvidia-smi", "-q", "-d", "ENCODER"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=5,
                    )
                    if nvidia_smi.returncode == 0 and b"Encoder" in nvidia_smi.stdout:
                        gpu_info["nvidia"] = True
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass

                # Check for AMD GPU
                try:
                    if os.path.exists("/dev/dri/renderD128"):
                        with open("/sys/class/drm/renderD128/device/vendor", "r") as f:
                            vendor = f.read().strip()
                            if vendor == "0x1002":  # AMD vendor ID
                                gpu_info["amd"] = True
                except (IOError, OSError):
                    pass

                # Check for Intel GPU
                try:
                    lspci = subprocess.run(
                        ["lspci"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        timeout=5,
                    )
                    output = lspci.stdout.decode().lower()
                    if "intel" in output and ("vga" in output or "display" in output):
                        gpu_info["intel"] = True
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    pass

                # Check for ARM GPU
                if self.machine in ["aarch64", "armv7l"]:
                    gpu_info["arm"] = True

            elif self.system == "Windows":
                try:
                    # Use PowerShell to get GPU info
                    ps_command = "Get-WmiObject Win32_VideoController | ConvertTo-Json"
                    result = subprocess.run(
                        ["powershell", "-Command", ps_command],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        gpu_data = json.loads(result.stdout)
                        if not isinstance(gpu_data, list):
                            gpu_data = [gpu_data]
                        
                        for gpu in gpu_data:
                            name = gpu.get("Name", "").lower()
                            if "nvidia" in name:
                                gpu_info["nvidia"] = True
                            if "amd" in name or "radeon" in name:
                                gpu_info["amd"] = True
                            if "intel" in name:
                                gpu_info["intel"] = True
                except Exception:
                    # Fallback to dxdiag if PowerShell method fails
                    with tempfile.NamedTemporaryFile(
                        suffix=".txt", delete=False
                    ) as temp_file:
                        temp_path = temp_file.name

                    try:
                        subprocess.run(
                            ["dxdiag", "/t", temp_path],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            timeout=10,
                        )
                        if os.path.exists(temp_path):
                            with open(temp_path, "r", errors="ignore") as f:
                                content = f.read().lower()
                                if "nvidia" in content:
                                    gpu_info["nvidia"] = True
                                if "amd" in content or "radeon" in content:
                                    gpu_info["amd"] = True
                                if "intel" in content:
                                    gpu_info["intel"] = True
                    finally:
                        try:
                            os.unlink(temp_path)
                        except OSError:
                            pass

        except Exception as e:
            logger.warning(f"GPU detection failed: {str(e)}")

        return gpu_info

    def _analyze_video(self, input_path: str) -> dict:
        """Analyze video content for optimal encoding settings"""
        try:
            probe = ffmpeg.probe(input_path)
            video_info = next(s for s in probe['streams'] if s['codec_type'] == 'video')
            
            # Get video properties
            width = int(video_info.get('width', 0))
            height = int(video_info.get('height', 0))
            fps = eval(video_info.get('r_frame_rate', '30/1'))
            duration = float(probe['format'].get('duration', 0))
            bitrate = float(probe['format'].get('bit_rate', 0))
            
            # Detect high motion content
            has_high_motion = False
            if video_info.get('avg_frame_rate'):
                avg_fps = eval(video_info['avg_frame_rate'])
                if abs(avg_fps - fps) > 5:  # Significant frame rate variation
                    has_high_motion = True
            
            # Get audio properties
            audio_info = next((s for s in probe['streams'] if s['codec_type'] == 'audio'), None)
            audio_bitrate = 0
            if audio_info:
                audio_bitrate = int(audio_info.get('bit_rate', 0))
            
            return {
                'width': width,
                'height': height,
                'fps': fps,
                'duration': duration,
                'bitrate': bitrate,
                'has_high_motion': has_high_motion,
                'audio_bitrate': audio_bitrate
            }
        except Exception as e:
            logger.error(f"Error analyzing video: {str(e)}")
            return {}

    def _get_optimal_ffmpeg_params(
        self, input_path: str, target_size_bytes: int
    ) -> dict:
        """Get optimal FFmpeg parameters based on hardware and video size"""
        # Analyze video content
        video_info = self._analyze_video(input_path)
        
        # Base parameters
        params = {
            "c:v": "libx264",  # Default to CPU encoding
            "threads": str(self._cpu_cores),  # Use all CPU cores
            "preset": "medium",
            "crf": "23",  # Default quality
            "maxrate": None,
            "bufsize": None,
            "movflags": "+faststart",  # Optimize for web playback
            "profile:v": "high",  # High profile for better quality
            "level": "4.1",  # Compatibility level
            "pix_fmt": "yuv420p",  # Standard pixel format
        }

        # Add advanced encoding parameters
        params.update({
            "x264opts": "rc-lookahead=60:me=umh:subme=7:ref=4:b-adapt=2:direct=auto",
            "tune": "film",  # General-purpose tuning
            "fastfirstpass": "1",  # Fast first pass for two-pass encoding
        })

        # Adjust for high motion content
        if video_info.get('has_high_motion'):
            params.update({
                "tune": "grain",  # Better for high motion
                "x264opts": params["x264opts"] + ":deblock=-1,-1:psy-rd=1.0:aq-strength=0.8"
            })

        # GPU-specific optimizations
        if self._gpu_info["nvidia"]:
            try:
                params.update({
                    "c:v": "h264_nvenc",
                    "preset": "p7",  # Highest quality NVENC preset
                    "rc:v": "vbr",  # Variable bitrate
                    "cq:v": "19",  # Quality level
                    "b_ref_mode": "middle",
                    "spatial-aq": "1",
                    "temporal-aq": "1",
                    "rc-lookahead": "32",
                    "surfaces": "64",
                    "max_muxing_queue_size": "1024",
                })
            except Exception as e:
                logger.error(f"NVENC initialization failed: {str(e)}")
                self._gpu_info["nvidia"] = False  # Disable NVENC
        
        elif self._gpu_info["amd"]:
            try:
                params.update({
                    "c:v": "h264_amf",
                    "quality": "quality",
                    "rc": "vbr_peak",
                    "enforce_hrd": "1",
                    "vbaq": "1",
                    "preanalysis": "1",
                    "max_muxing_queue_size": "1024",
                })
            except Exception as e:
                logger.error(f"AMF initialization failed: {str(e)}")
                self._gpu_info["amd"] = False
        
        elif self._gpu_info["intel"]:
            try:
                params.update({
                    "c:v": "h264_qsv",
                    "preset": "veryslow",
                    "look_ahead": "1",
                    "global_quality": "23",
                    "max_muxing_queue_size": "1024",
                })
            except Exception as e:
                logger.error(f"QSV initialization failed: {str(e)}")
                self._gpu_info["intel"] = False

        try:
            # Calculate target bitrate
            input_size = os.path.getsize(input_path)
            duration = video_info.get('duration', 0)
            
            if duration > 0 and input_size > target_size_bytes:
                # Reserve 5% for container overhead
                video_size_target = int(target_size_bytes * 0.95)
                
                # Calculate audio bitrate (10-20% of total, based on content)
                total_bitrate = (video_size_target * 8) / duration
                audio_bitrate = min(
                    192000,  # Max 192kbps
                    max(
                        64000,  # Min 64kbps
                        int(total_bitrate * 0.15)  # 15% of total
                    )
                )
                
                # Remaining bitrate for video
                video_bitrate = int((video_size_target * 8) / duration - audio_bitrate)
                
                # Set bitrate constraints
                params["maxrate"] = str(int(video_bitrate * 1.5))  # Allow 50% overflow
                params["bufsize"] = str(int(video_bitrate * 2))    # Double buffer size
                
                # Adjust quality based on compression ratio
                ratio = input_size / target_size_bytes
                if ratio > 4:
                    params["crf"] = "26" if params["c:v"] == "libx264" else "23"
                    params["preset"] = "faster"
                elif ratio > 2:
                    params["crf"] = "23" if params["c:v"] == "libx264" else "21"
                    params["preset"] = "medium"
                else:
                    params["crf"] = "20" if params["c:v"] == "libx264" else "19"
                    params["preset"] = "slow"
                
                # Audio settings
                params.update({
                    "c:a": "aac",
                    "b:a": f"{int(audio_bitrate/1000)}k",
                    "ar": "48000",
                    "ac": "2",  # Stereo
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
                "ac": "2",
            })

        return params

    def _download_ffmpeg(self):
        """Download and extract FFmpeg binary"""
        try:
            arch_config = self.FFMPEG_URLS[self.system][self.machine]
        except KeyError:
            raise Exception(
                f"Unsupported system/architecture: {self.system}/{self.machine}"
            )

        url = arch_config["url"]
        archive_path = (
            self.base_path
            / f"ffmpeg_archive{'.zip' if self.system == 'Windows' else '.tar.xz'}"
        )

        try:
            # Download archive
            response = requests.get(url, stream=True, timeout=30)
            response.raise_for_status()
            with open(archive_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Extract archive
            if self.system == "Windows":
                with zipfile.ZipFile(archive_path, "r") as zip_ref:
                    ffmpeg_files = [
                        f for f in zip_ref.namelist() if arch_config["bin_name"] in f
                    ]
                    if not ffmpeg_files:
                        raise Exception("FFmpeg binary not found in archive")
                    zip_ref.extract(ffmpeg_files[0], self.base_path)
                    if self.ffmpeg_path.exists():
                        self.ffmpeg_path.unlink()
                    os.rename(self.base_path / ffmpeg_files[0], self.ffmpeg_path)
            else:
                with tarfile.open(archive_path, "r:xz") as tar_ref:
                    ffmpeg_files = [
                        f for f in tar_ref.getnames() if arch_config["bin_name"] in f
                    ]
                    if not ffmpeg_files:
                        raise Exception("FFmpeg binary not found in archive")
                    tar_ref.extract(ffmpeg_files[0], self.base_path)
                    if self.ffmpeg_path.exists():
                        self.ffmpeg_path.unlink()
                    os.rename(self.base_path / ffmpeg_files[0], self.ffmpeg_path)

        except Exception as e:
            logger.error(f"FFmpeg download/extraction failed: {str(e)}")
            raise
        finally:
            # Cleanup
            try:
                if archive_path.exists():
                    archive_path.unlink()
            except Exception as e:
                logger.warning(f"Failed to cleanup FFmpeg archive: {str(e)}")

    def force_download(self) -> bool:
        """Force re-download of FFmpeg binary"""
        try:
            # Remove existing binary if it exists
            if self.ffmpeg_path.exists():
                try:
                    self.ffmpeg_path.unlink()
                except Exception as e:
                    logger.error(f"Failed to remove existing FFmpeg: {str(e)}")
                    return False

            # Download new binary
            self._download_ffmpeg()

            # Verify new binary
            return self._verify_ffmpeg()
        except Exception as e:
            logger.error(f"Failed to force download FFmpeg: {str(e)}")
            return False

    def get_ffmpeg_path(self) -> str:
        """Get path to FFmpeg binary"""
        if not self.ffmpeg_path.exists():
            raise Exception("FFmpeg is not available")
        return str(self.ffmpeg_path)

    def get_compression_params(self, input_path: str, target_size_mb: int) -> dict:
        """Get optimal compression parameters for the given input file"""
        return self._get_optimal_ffmpeg_params(input_path, target_size_mb * 1024 * 1024)
