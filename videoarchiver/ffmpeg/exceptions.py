"""FFmpeg-related exceptions"""


class FFmpegError(Exception):
    """Base exception for FFmpeg-related errors"""

    pass


class DownloadError(FFmpegError):
    """Exception raised when FFmpeg download fails"""

    pass


class VerificationError(FFmpegError):
    """Exception raised when FFmpeg verification fails"""

    def __init__(self, message: str, binary_type: str = "FFmpeg"):
        self.binary_type = binary_type
        super().__init__(f"{binary_type} verification failed: {message}")


class EncodingError(FFmpegError):
    """Exception raised when video encoding fails"""

    pass


class AnalysisError(FFmpegError):
    """Exception raised when video analysis fails"""

    pass


class GPUError(FFmpegError):
    """Exception raised when GPU operations fail"""

    pass


class HardwareAccelerationError(FFmpegError):
    """Exception raised when hardware acceleration fails"""

    def __init__(self, message: str, fallback_used: bool = False):
        self.fallback_used = fallback_used
        super().__init__(message)


class FFmpegNotFoundError(FFmpegError):
    """Exception raised when FFmpeg binary is not found"""

    pass


class FFprobeError(FFmpegError):
    """Exception raised when FFprobe operations fail"""

    pass


class CompressionError(FFmpegError):
    """Exception raised when video compression fails"""

    def __init__(self, message: str, input_size: int, target_size: int):
        self.input_size = input_size
        self.target_size = target_size
        super().__init__(f"{message} (Input: {input_size}B, Target: {target_size}B)")


class FormatError(FFmpegError):
    """Exception raised when video format is invalid or unsupported"""

    pass


class PermissionError(FFmpegError):
    """Exception raised when file permissions prevent operations"""

    pass


class TimeoutError(FFmpegError):
    """Exception raised when FFmpeg operations timeout"""

    pass


class ResourceError(FFmpegError):
    """Exception raised when system resources are insufficient"""

    def __init__(self, message: str, resource_type: str):
        self.resource_type = resource_type
        super().__init__(f"{message} (Resource: {resource_type})")


class QualityError(FFmpegError):
    """Exception raised when video quality requirements cannot be met"""

    def __init__(self, message: str, target_quality: int, achieved_quality: int):
        self.target_quality = target_quality
        self.achieved_quality = achieved_quality
        super().__init__(
            f"{message} (Target: {target_quality}p, Achieved: {achieved_quality}p)"
        )


class AudioError(FFmpegError):
    """Exception raised when audio processing fails"""

    pass


class BitrateError(FFmpegError):
    """Exception raised when bitrate requirements cannot be met"""

    def __init__(self, message: str, target_bitrate: int, actual_bitrate: int):
        self.target_bitrate = target_bitrate
        self.actual_bitrate = actual_bitrate
        super().__init__(
            f"{message} (Target: {target_bitrate}bps, Actual: {actual_bitrate}bps)"
        )


def handle_ffmpeg_error(error_output: str) -> FFmpegError:
    """Convert FFmpeg error output to appropriate exception"""
    error_output = error_output.lower()

    if "no such file" in error_output:
        return FFmpegNotFoundError("FFmpeg binary not found")
    elif "permission denied" in error_output:
        return PermissionError("Insufficient permissions")
    elif "hardware acceleration" in error_output:
        return HardwareAccelerationError(
            "Hardware acceleration failed", fallback_used=True
        )
    elif "invalid data" in error_output:
        return FormatError("Invalid or corrupted video format")
    elif "insufficient memory" in error_output:
        return ResourceError("Insufficient memory", "memory")
    elif "audio" in error_output:
        return AudioError("Audio processing failed")
    elif "bitrate" in error_output:
        return BitrateError("Bitrate requirements not met", 0, 0)
    elif "timeout" in error_output:
        return TimeoutError("Operation timed out")
    elif "version" in error_output:
        return VerificationError("Version check failed")
    elif "verification" in error_output:
        return VerificationError(error_output)
    else:
        return FFmpegError(f"FFmpeg operation failed: {error_output}")
