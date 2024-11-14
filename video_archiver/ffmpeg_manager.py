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

logger = logging.getLogger('VideoArchiver')

class FFmpegManager:
    FFMPEG_URLS = {
        'Windows': {
            'x86_64': {
                'url': 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip',
                'bin_name': 'ffmpeg.exe'
            }
        },
        'Linux': {
            'x86_64': {
                'url': 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-gpl.tar.xz',
                'bin_name': 'ffmpeg'
            },
            'aarch64': {  # ARM64
                'url': 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linuxarm64-gpl.tar.xz',
                'bin_name': 'ffmpeg'
            },
            'armv7l': {  # ARM32
                'url': 'https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linuxarm32-gpl.tar.xz',
                'bin_name': 'ffmpeg'
            }
        },
        'Darwin': {  # macOS
            'x86_64': {
                'url': 'https://evermeet.cx/ffmpeg/getrelease/zip',
                'bin_name': 'ffmpeg'
            },
            'arm64': {  # Apple Silicon
                'url': 'https://evermeet.cx/ffmpeg/getrelease/zip',
                'bin_name': 'ffmpeg'
            }
        }
    }

    def __init__(self):
        self.base_path = Path(__file__).parent / 'bin'
        self.base_path.mkdir(exist_ok=True)
        
        # Get system architecture
        self.system = platform.system()
        self.machine = platform.machine().lower()
        if self.machine == 'arm64':
            self.machine = 'aarch64'  # Normalize ARM64 naming
        
        # Try to use system FFmpeg first
        system_ffmpeg = shutil.which('ffmpeg')
        if system_ffmpeg:
            self.ffmpeg_path = Path(system_ffmpeg)
            logger.info(f"Using system FFmpeg: {self.ffmpeg_path}")
        else:
            # Fall back to downloaded FFmpeg
            try:
                arch_config = self.FFMPEG_URLS[self.system][self.machine]
                self.ffmpeg_path = self.base_path / arch_config['bin_name']
            except KeyError:
                raise Exception(f"Unsupported system/architecture: {self.system}/{self.machine}")
        
        self._gpu_info = self._detect_gpu()
        self._cpu_cores = multiprocessing.cpu_count()
        
        if not system_ffmpeg:
            self._ensure_ffmpeg()

    def _detect_gpu(self) -> dict:
        """Detect available GPU and its capabilities"""
        gpu_info = {
            'nvidia': False,
            'amd': False,
            'intel': False,
            'arm': False
        }
        
        try:
            if self.system == 'Linux':
                # Check for NVIDIA GPU
                nvidia_smi = subprocess.run(['nvidia-smi'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if nvidia_smi.returncode == 0:
                    gpu_info['nvidia'] = True
                
                # Check for AMD GPU
                if os.path.exists('/dev/dri/renderD128'):
                    gpu_info['amd'] = True
                
                # Check for Intel GPU
                lspci = subprocess.run(['lspci'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if b'VGA' in lspci.stdout and b'Intel' in lspci.stdout:
                    gpu_info['intel'] = True
                
                # Check for ARM GPU
                if self.machine in ['aarch64', 'armv7l']:
                    gpu_info['arm'] = True
                    
            elif self.system == 'Windows':
                # Check for any GPU using dxdiag
                dxdiag = subprocess.run(['dxdiag', '/t', 'temp_dxdiag.txt'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                if os.path.exists('temp_dxdiag.txt'):
                    with open('temp_dxdiag.txt', 'r') as f:
                        content = f.read().lower()
                        if 'nvidia' in content:
                            gpu_info['nvidia'] = True
                        if 'amd' in content or 'radeon' in content:
                            gpu_info['amd'] = True
                        if 'intel' in content:
                            gpu_info['intel'] = True
                    os.remove('temp_dxdiag.txt')
                    
        except Exception as e:
            logger.warning(f"GPU detection failed: {str(e)}")
            
        return gpu_info

    def _get_optimal_ffmpeg_params(self, input_path: str, target_size_bytes: int) -> dict:
        """Get optimal FFmpeg parameters based on hardware and video size"""
        params = {
            'c:v': 'libx264',  # Default to CPU encoding
            'threads': str(self._cpu_cores),  # Use all CPU cores
            'preset': 'medium',
            'crf': '23',  # Default quality
            'maxrate': None,
            'bufsize': None,
            'movflags': '+faststart',  # Optimize for web playback
            'profile:v': 'high',  # High profile for better quality
            'level': '4.1',  # Compatibility level
            'pix_fmt': 'yuv420p'  # Standard pixel format
        }
        
        # Check if GPU encoding is possible
        if self._gpu_info['nvidia']:
            params.update({
                'c:v': 'h264_nvenc',
                'preset': 'p4',  # High quality NVENC preset
                'rc:v': 'vbr',  # Variable bitrate for better quality
                'cq:v': '19',  # Quality level for NVENC
                'spatial-aq': '1',  # Enable spatial adaptive quantization
                'temporal-aq': '1',  # Enable temporal adaptive quantization
                'b_ref_mode': 'middle'  # Better quality for B-frames
            })
        elif self._gpu_info['amd']:
            params.update({
                'c:v': 'h264_amf',
                'quality': 'quality',
                'rc': 'vbr_peak',
                'enforce_hrd': '1',
                'vbaq': '1',  # Enable adaptive quantization
                'preanalysis': '1'
            })
        elif self._gpu_info['intel']:
            params.update({
                'c:v': 'h264_qsv',
                'preset': 'veryslow',  # Best quality for QSV
                'look_ahead': '1',
                'global_quality': '23'
            })
        elif self._gpu_info['arm']:
            # Use OpenMAX (OMX) on supported ARM devices
            if os.path.exists('/dev/video-codec'):
                params.update({
                    'c:v': 'h264_v4l2m2m',  # V4L2 M2M encoder
                    'extra_hw_frames': '10'
                })
            else:
                # Fall back to optimized CPU encoding for ARM
                params.update({
                    'c:v': 'libx264',
                    'preset': 'medium',
                    'tune': 'fastdecode'
                })
        
        # Get input file size and probe info
        input_size = os.path.getsize(input_path)
        probe = ffmpeg.probe(input_path)
        duration = float(probe['format']['duration'])
        
        # Only add bitrate constraints if compression is needed
        if input_size > target_size_bytes:
            # Calculate target bitrate (bits/second)
            target_bitrate = int((target_size_bytes * 8) / duration * 0.95)  # 95% of target size
            
            params['maxrate'] = f"{target_bitrate}"
            params['bufsize'] = f"{target_bitrate * 2}"
            
            # Adjust quality settings based on compression ratio
            ratio = input_size / target_size_bytes
            if ratio > 4:
                params['crf'] = '28' if params['c:v'] == 'libx264' else '23'
                params['preset'] = 'faster'
            elif ratio > 2:
                params['crf'] = '26' if params['c:v'] == 'libx264' else '21'
                params['preset'] = 'medium'
            else:
                params['crf'] = '23' if params['c:v'] == 'libx264' else '19'
                params['preset'] = 'slow'
        
        # Audio settings
        params.update({
            'c:a': 'aac',
            'b:a': '192k',  # High quality audio
            'ar': '48000'  # Standard sample rate
        })
        
        return params

    def _ensure_ffmpeg(self):
        """Ensure FFmpeg is available, downloading if necessary"""
        if not self.ffmpeg_path.exists():
            self._download_ffmpeg()
        
        # Make binary executable on Unix systems
        if self.system != 'Windows':
            self.ffmpeg_path.chmod(self.ffmpeg_path.stat().st_mode | stat.S_IEXEC)

    def _download_ffmpeg(self):
        """Download and extract FFmpeg binary"""
        try:
            arch_config = self.FFMPEG_URLS[self.system][self.machine]
        except KeyError:
            raise Exception(f"Unsupported system/architecture: {self.system}/{self.machine}")

        url = arch_config['url']
        archive_path = self.base_path / f"ffmpeg_archive{'.zip' if self.system == 'Windows' else '.tar.xz'}"

        # Download archive
        response = requests.get(url, stream=True)
        response.raise_for_status()
        with open(archive_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        # Extract archive
        if self.system == 'Windows':
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                ffmpeg_files = [f for f in zip_ref.namelist() if arch_config['bin_name'] in f]
                if ffmpeg_files:
                    zip_ref.extract(ffmpeg_files[0], self.base_path)
                    os.rename(self.base_path / ffmpeg_files[0], self.ffmpeg_path)
        else:
            with tarfile.open(archive_path, 'r:xz') as tar_ref:
                ffmpeg_files = [f for f in tar_ref.getnames() if arch_config['bin_name'] in f]
                if ffmpeg_files:
                    tar_ref.extract(ffmpeg_files[0], self.base_path)
                    os.rename(self.base_path / ffmpeg_files[0], self.ffmpeg_path)

        # Cleanup
        archive_path.unlink()

    def get_ffmpeg_path(self) -> str:
        """Get path to FFmpeg binary"""
        if not self.ffmpeg_path.exists():
            raise Exception("FFmpeg is not available")
        return str(self.ffmpeg_path)

    def get_compression_params(self, input_path: str, target_size_mb: int) -> dict:
        """Get optimal compression parameters for the given input file"""
        return self._get_optimal_ffmpeg_params(input_path, target_size_mb * 1024 * 1024)
