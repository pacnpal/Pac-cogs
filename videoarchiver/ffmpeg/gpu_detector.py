"""GPU detection functionality for FFmpeg"""

import os
import subprocess
import logging
import platform
import re
from typing import Dict, List
from pathlib import Path

logger = logging.getLogger("VideoArchiver")

class GPUDetector:
    def __init__(self, ffmpeg_path: Path):
        """Initialize GPU detector
        
        Args:
            ffmpeg_path: Path to FFmpeg binary
        """
        self.ffmpeg_path = Path(ffmpeg_path)
        if not self.ffmpeg_path.exists():
            raise FileNotFoundError(f"FFmpeg not found at {self.ffmpeg_path}")

    def detect_gpu(self) -> Dict[str, bool]:
        """Detect available GPU acceleration support
        
        Returns:
            Dict containing boolean flags for each GPU type
        """
        gpu_info = {
            "nvidia": False,
            "amd": False,
            "intel": False
        }

        try:
            # Check system-specific GPU detection first
            system = platform.system().lower()
            if system == "windows":
                gpu_info.update(self._detect_windows_gpu())
            elif system == "linux":
                gpu_info.update(self._detect_linux_gpu())
            elif system == "darwin":
                gpu_info.update(self._detect_macos_gpu())

            # Verify GPU support in FFmpeg
            gpu_info.update(self._verify_ffmpeg_gpu_support())

            # Log detection results
            detected_gpus = [name for name, detected in gpu_info.items() if detected]
            if detected_gpus:
                logger.info(f"Detected GPUs: {', '.join(detected_gpus)}")
            else:
                logger.info("No GPU acceleration support detected")

            return gpu_info

        except Exception as e:
            logger.error(f"Error during GPU detection: {str(e)}")
            return {"nvidia": False, "amd": False, "intel": False}

    def _detect_windows_gpu(self) -> Dict[str, bool]:
        """Detect GPUs on Windows using PowerShell"""
        gpu_info = {"nvidia": False, "amd": False, "intel": False}
        
        try:
            # Use PowerShell to get GPU info
            cmd = ["powershell", "-Command", "Get-WmiObject Win32_VideoController | Select-Object Name"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                output = result.stdout.lower()
                gpu_info["nvidia"] = "nvidia" in output
                gpu_info["amd"] = any(x in output for x in ["amd", "radeon"])
                gpu_info["intel"] = "intel" in output
                
        except Exception as e:
            logger.error(f"Windows GPU detection failed: {str(e)}")
            
        return gpu_info

    def _detect_linux_gpu(self) -> Dict[str, bool]:
        """Detect GPUs on Linux using lspci and other tools"""
        gpu_info = {"nvidia": False, "amd": False, "intel": False}
        
        try:
            # Try lspci first
            try:
                result = subprocess.run(
                    ["lspci", "-v"],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if result.returncode == 0:
                    output = result.stdout.lower()
                    gpu_info["nvidia"] = "nvidia" in output
                    gpu_info["amd"] = any(x in output for x in ["amd", "radeon"])
                    gpu_info["intel"] = "intel" in output
            except FileNotFoundError:
                pass

            # Check for NVIDIA using nvidia-smi
            if not gpu_info["nvidia"]:
                try:
                    result = subprocess.run(
                        ["nvidia-smi"],
                        capture_output=True,
                        timeout=10
                    )
                    gpu_info["nvidia"] = result.returncode == 0
                except FileNotFoundError:
                    pass

            # Check for AMD using rocm-smi
            if not gpu_info["amd"]:
                try:
                    result = subprocess.run(
                        ["rocm-smi"],
                        capture_output=True,
                        timeout=10
                    )
                    gpu_info["amd"] = result.returncode == 0
                except FileNotFoundError:
                    pass

            # Check for Intel using intel_gpu_top
            if not gpu_info["intel"]:
                try:
                    result = subprocess.run(
                        ["intel_gpu_top", "-L"],
                        capture_output=True,
                        timeout=10
                    )
                    gpu_info["intel"] = result.returncode == 0
                except FileNotFoundError:
                    pass

        except Exception as e:
            logger.error(f"Linux GPU detection failed: {str(e)}")
            
        return gpu_info

    def _detect_macos_gpu(self) -> Dict[str, bool]:
        """Detect GPUs on macOS using system_profiler"""
        gpu_info = {"nvidia": False, "amd": False, "intel": False}
        
        try:
            cmd = ["system_profiler", "SPDisplaysDataType"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                output = result.stdout.lower()
                gpu_info["nvidia"] = "nvidia" in output
                gpu_info["amd"] = any(x in output for x in ["amd", "radeon"])
                gpu_info["intel"] = "intel" in output
                
        except Exception as e:
            logger.error(f"macOS GPU detection failed: {str(e)}")
            
        return gpu_info

    def _verify_ffmpeg_gpu_support(self) -> Dict[str, bool]:
        """Verify GPU support in FFmpeg installation"""
        gpu_support = {"nvidia": False, "amd": False, "intel": False}
        
        try:
            # Check FFmpeg encoders
            cmd = [str(self.ffmpeg_path), "-hide_banner", "-encoders"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            
            if result.returncode == 0:
                output = result.stdout.lower()
                
                # Check for specific GPU encoders
                gpu_support["nvidia"] = "h264_nvenc" in output
                gpu_support["amd"] = "h264_amf" in output
                gpu_support["intel"] = "h264_qsv" in output

                # Log available encoders
                encoders = []
                if gpu_support["nvidia"]:
                    encoders.append("NVENC")
                if gpu_support["amd"]:
                    encoders.append("AMF")
                if gpu_support["intel"]:
                    encoders.append("QSV")
                
                if encoders:
                    logger.info(f"FFmpeg supports GPU encoders: {', '.join(encoders)}")
                else:
                    logger.info("No GPU encoders available in FFmpeg")

        except Exception as e:
            logger.error(f"FFmpeg GPU support verification failed: {str(e)}")
            
        return gpu_support

    def get_gpu_info(self) -> Dict[str, List[str]]:
        """Get detailed GPU information
        
        Returns:
            Dict containing lists of GPU names by type
        """
        gpu_info = {
            "nvidia": [],
            "amd": [],
            "intel": []
        }

        try:
            system = platform.system().lower()
            
            if system == "windows":
                cmd = ["powershell", "-Command", "Get-WmiObject Win32_VideoController | Select-Object Name"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0:
                    for line in result.stdout.splitlines():
                        line = line.strip().lower()
                        if line:
                            if "nvidia" in line:
                                gpu_info["nvidia"].append(line)
                            elif any(x in line for x in ["amd", "radeon"]):
                                gpu_info["amd"].append(line)
                            elif "intel" in line:
                                gpu_info["intel"].append(line)
                                
            elif system == "linux":
                try:
                    result = subprocess.run(
                        ["lspci", "-v"],
                        capture_output=True,
                        text=True,
                        timeout=10
                    )
                    if result.returncode == 0:
                        for line in result.stdout.splitlines():
                            if "vga" in line.lower() or "3d" in line.lower():
                                if "nvidia" in line.lower():
                                    gpu_info["nvidia"].append(line.strip())
                                elif any(x in line.lower() for x in ["amd", "radeon"]):
                                    gpu_info["amd"].append(line.strip())
                                elif "intel" in line.lower():
                                    gpu_info["intel"].append(line.strip())
                except FileNotFoundError:
                    pass

            elif system == "darwin":
                cmd = ["system_profiler", "SPDisplaysDataType"]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                
                if result.returncode == 0:
                    current_gpu = None
                    for line in result.stdout.splitlines():
                        line = line.strip().lower()
                        if "chipset model" in line:
                            if "nvidia" in line:
                                current_gpu = "nvidia"
                                gpu_info["nvidia"].append(line.split(":")[1].strip())
                            elif any(x in line for x in ["amd", "radeon"]):
                                current_gpu = "amd"
                                gpu_info["amd"].append(line.split(":")[1].strip())
                            elif "intel" in line:
                                current_gpu = "intel"
                                gpu_info["intel"].append(line.split(":")[1].strip())

        except Exception as e:
            logger.error(f"Error getting detailed GPU info: {str(e)}")

        return gpu_info
