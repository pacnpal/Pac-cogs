"""GPU detection functionality for FFmpeg"""

import os
import json
import subprocess
import logging
from pathlib import Path
from typing import Dict

logger = logging.getLogger("VideoArchiver")

class GPUDetector:
    def __init__(self, ffmpeg_path: Path):
        self.ffmpeg_path = ffmpeg_path

    def detect_gpu(self) -> Dict[str, bool]:
        """Detect available GPU and its capabilities"""
        gpu_info = {"nvidia": False, "amd": False, "intel": False, "arm": False}

        try:
            if os.name == "posix":  # Linux/Unix
                gpu_info.update(self._detect_linux_gpu())
            elif os.name == "nt":  # Windows
                gpu_info.update(self._detect_windows_gpu())

        except Exception as e:
            logger.warning(f"GPU detection failed: {str(e)}")

        return gpu_info

    def _test_encoder(self, encoder: str) -> bool:
        """Test if a specific encoder works"""
        try:
            test_cmd = [
                str(self.ffmpeg_path),
                "-f", "lavfi",
                "-i", "testsrc=duration=1:size=1280x720:rate=30",
                "-c:v", encoder,
                "-f", "null",
                "-"
            ]
            result = subprocess.run(
                test_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5
            )
            return result.returncode == 0
        except Exception:
            return False

    def _detect_linux_gpu(self) -> Dict[str, bool]:
        """Detect GPUs on Linux systems"""
        gpu_info = {"nvidia": False, "amd": False, "intel": False, "arm": False}

        # Check for NVIDIA GPU
        try:
            nvidia_smi = subprocess.run(
                ["nvidia-smi", "-q", "-d", "ENCODER"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5
            )
            if nvidia_smi.returncode == 0 and b"Encoder" in nvidia_smi.stdout:
                gpu_info["nvidia"] = self._test_encoder("h264_nvenc")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Check for AMD GPU
        try:
            if os.path.exists("/dev/dri/renderD128"):
                with open("/sys/class/drm/renderD128/device/vendor", "r") as f:
                    vendor = f.read().strip()
                    if vendor == "0x1002":  # AMD vendor ID
                        gpu_info["amd"] = self._test_encoder("h264_amf")
        except (IOError, OSError):
            pass

        # Check for Intel GPU
        try:
            lspci = subprocess.run(
                ["lspci"],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5
            )
            output = lspci.stdout.decode().lower()
            if "intel" in output and ("vga" in output or "display" in output):
                gpu_info["intel"] = self._test_encoder("h264_qsv")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

        # Check for ARM GPU
        if os.uname().machine.startswith(("aarch64", "armv7")):
            gpu_info["arm"] = True

        return gpu_info

    def _detect_windows_gpu(self) -> Dict[str, bool]:
        """Detect GPUs on Windows systems"""
        gpu_info = {"nvidia": False, "amd": False, "intel": False, "arm": False}

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
                        gpu_info["nvidia"] = self._test_encoder("h264_nvenc")
                    if "amd" in name or "radeon" in name:
                        gpu_info["amd"] = self._test_encoder("h264_amf")
                    if "intel" in name:
                        gpu_info["intel"] = self._test_encoder("h264_qsv")

        except Exception as e:
            logger.error(f"Error during Windows GPU detection: {str(e)}")

        return gpu_info
