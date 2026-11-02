"""Constants for VideoProcessor"""

from typing import Dict, List, Union
from dataclasses import field, dataclass
from enum import Enum

class ReactionType(Enum):
    """Types of reactions used in the processor"""
    QUEUED = 'queued'
    PROCESSING = 'processing'
    SUCCESS = 'success'
    ERROR = 'error'
    ARCHIVED = 'archived'
    NUMBERS = 'numbers'
    PROGRESS = 'progress'
    DOWNLOAD = 'download'

@dataclass(frozen=True)
class ReactionEmojis:
    """Emoji constants for different reaction types"""
    QUEUED: str = '📹'
    PROCESSING: str = '⚙️'
    SUCCESS: str = '✅'
    ERROR: str = '❌'
    ARCHIVED: str = '🔄'

@dataclass(frozen=True)
class ProgressEmojis:
    """Emoji sequences for progress indicators"""
    NUMBERS: List[str] = ('1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣')
    PROGRESS: List[str] = ('⬛', '🟨', '🟩')
    DOWNLOAD: List[str] = ('0️⃣', '2️⃣', '4️⃣', '6️⃣', '8️⃣', '🔟')

# Main reactions dictionary with type hints
REACTIONS: Dict[str, Union[str, List[str]]] = {
    ReactionType.QUEUED.value: ReactionEmojis.QUEUED,
    ReactionType.PROCESSING.value: ReactionEmojis.PROCESSING,
    ReactionType.SUCCESS.value: ReactionEmojis.SUCCESS,
    ReactionType.ERROR.value: ReactionEmojis.ERROR,
    ReactionType.ARCHIVED.value: ReactionEmojis.ARCHIVED,
    ReactionType.NUMBERS.value: list(ProgressEmojis.NUMBERS),
    ReactionType.PROGRESS.value: list(ProgressEmojis.PROGRESS),
    ReactionType.DOWNLOAD.value: list(ProgressEmojis.DOWNLOAD)
}

def get_reaction(reaction_type: Union[ReactionType, str]) -> Union[str, List[str]]:
    """
    Get reaction emoji(s) for a given reaction type.
    
    Args:
        reaction_type: The type of reaction to get, either as ReactionType enum or string
        
    Returns:
        Either a single emoji string or a list of emoji strings
        
    Raises:
        KeyError: If the reaction type doesn't exist
    """
    key = reaction_type.value if isinstance(reaction_type, ReactionType) else reaction_type
    return REACTIONS[key]

def get_progress_emoji(progress: float, emoji_list: List[str]) -> str:
    """
    Get the appropriate progress emoji based on a progress value.
    
    Args:
        progress: Progress value between 0 and 1
        emoji_list: List of emojis to choose from
        
    Returns:
        The emoji representing the current progress
    """
    if not 0 <= progress <= 1:
        raise ValueError("Progress must be between 0 and 1")
        
    index = int(progress * (len(emoji_list) - 1))
    return emoji_list[index]
