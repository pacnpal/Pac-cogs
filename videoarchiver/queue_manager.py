import asyncio
import logging
from typing import Dict, Optional, Set, Tuple, Callable, Any
from datetime import datetime
import traceback
from dataclasses import dataclass
import weakref

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('QueueManager')

@dataclass
class QueueItem:
    """Represents a video processing task in the queue"""
    url: str
    message_id: int
    channel_id: int
    guild_id: int
    author_id: int
    added_at: datetime
    callback: Callable[[str, bool, str], Any]
    status: str = "pending"  # pending, processing, completed, failed
    error: Optional[str] = None
    attempt: int = 0

class VideoQueueManager:
    """Manages a queue of videos to be processed, ensuring sequential processing"""
    
    def __init__(self, max_retries: int = 3, retry_delay: int = 5):
        self.max_retries = max_retries
        self.retry_delay = retry_delay
        
        # Queue storage
        self._queue: asyncio.Queue[QueueItem] = asyncio.Queue()
        self._processing: Dict[str, QueueItem] = {}
        self._failed: Dict[str, QueueItem] = {}
        self._completed: Dict[str, QueueItem] = {}
        
        # Track active tasks
        self._active_tasks: Set[asyncio.Task] = set()
        self._processing_lock = asyncio.Lock()
        
        # Status tracking
        self._guild_queues: Dict[int, Set[str]] = {}
        self._channel_queues: Dict[int, Set[str]] = {}
        
        # Cleanup references
        self._weak_refs: Set[weakref.ref] = set()
        
        # Start queue processor
        self._processor_task = asyncio.create_task(self._process_queue())
        self._active_tasks.add(self._processor_task)

    async def add_to_queue(
        self,
        url: str,
        message_id: int,
        channel_id: int,
        guild_id: int,
        author_id: int,
        callback: Callable[[str, bool, str], Any]
    ) -> bool:
        """Add a video to the processing queue"""
        try:
            # Create queue item
            item = QueueItem(
                url=url,
                message_id=message_id,
                channel_id=channel_id,
                guild_id=guild_id,
                author_id=author_id,
                added_at=datetime.utcnow(),
                callback=callback
            )
            
            # Add to tracking collections
            if guild_id not in self._guild_queues:
                self._guild_queues[guild_id] = set()
            self._guild_queues[guild_id].add(url)
            
            if channel_id not in self._channel_queues:
                self._channel_queues[channel_id] = set()
            self._channel_queues[channel_id].add(url)
            
            # Add to queue
            await self._queue.put(item)
            
            # Create weak reference for cleanup
            self._weak_refs.add(weakref.ref(item))
            
            logger.info(f"Added video to queue: {url}")
            return True
            
        except Exception as e:
            logger.error(f"Error adding video to queue: {str(e)}")
            return False

    async def _process_queue(self):
        """Process videos in the queue sequentially"""
        while True:
            try:
                # Get next item from queue
                item = await self._queue.get()
                
                async with self._processing_lock:
                    self._processing[item.url] = item
                    item.status = "processing"
                
                try:
                    # Execute callback with the URL
                    success = await item.callback(item.url, True, "")
                    
                    if success:
                        item.status = "completed"
                        self._completed[item.url] = item
                        logger.info(f"Successfully processed video: {item.url}")
                    else:
                        # Handle retry logic
                        item.attempt += 1
                        if item.attempt < self.max_retries:
                            # Re-queue with delay
                            await asyncio.sleep(self.retry_delay * item.attempt)
                            await self._queue.put(item)
                            logger.info(f"Retrying video processing: {item.url} (Attempt {item.attempt + 1})")
                        else:
                            item.status = "failed"
                            item.error = "Max retries exceeded"
                            self._failed[item.url] = item
                            logger.error(f"Failed to process video after {self.max_retries} attempts: {item.url}")
                            
                            # Notify callback of failure
                            await item.callback(item.url, False, item.error)
                    
                except Exception as e:
                    logger.error(f"Error processing video: {str(e)}\n{traceback.format_exc()}")
                    item.status = "failed"
                    item.error = str(e)
                    self._failed[item.url] = item
                    
                    # Notify callback of failure
                    await item.callback(item.url, False, str(e))
                
                finally:
                    # Clean up tracking
                    self._processing.pop(item.url, None)
                    if item.guild_id in self._guild_queues:
                        self._guild_queues[item.guild_id].discard(item.url)
                    if item.channel_id in self._channel_queues:
                        self._channel_queues[item.channel_id].discard(item.url)
                    
                    # Mark queue item as done
                    self._queue.task_done()
            
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Queue processor error: {str(e)}\n{traceback.format_exc()}")
                await asyncio.sleep(1)  # Prevent tight error loop

    def get_queue_status(self, guild_id: Optional[int] = None) -> Dict[str, int]:
        """Get current queue status, optionally filtered by guild"""
        if guild_id is not None:
            guild_urls = self._guild_queues.get(guild_id, set())
            return {
                "pending": sum(1 for _ in self._queue._queue if _.url in guild_urls),
                "processing": sum(1 for url in self._processing if url in guild_urls),
                "completed": sum(1 for url in self._completed if url in guild_urls),
                "failed": sum(1 for url in self._failed if url in guild_urls)
            }
        else:
            return {
                "pending": self._queue.qsize(),
                "processing": len(self._processing),
                "completed": len(self._completed),
                "failed": len(self._failed)
            }

    def get_channel_queue_size(self, channel_id: int) -> int:
        """Get number of items queued for a specific channel"""
        return len(self._channel_queues.get(channel_id, set()))

    async def clear_guild_queue(self, guild_id: int) -> int:
        """Clear all queued items for a specific guild"""
        if guild_id not in self._guild_queues:
            return 0
        
        cleared = 0
        guild_urls = self._guild_queues[guild_id].copy()
        
        # Remove from main queue
        new_queue = asyncio.Queue()
        while not self._queue.empty():
            item = await self._queue.get()
            if item.guild_id != guild_id:
                await new_queue.put(item)
            else:
                cleared += 1
        
        self._queue = new_queue
        
        # Clean up tracking
        for url in guild_urls:
            self._processing.pop(url, None)
            self._completed.pop(url, None)
            self._failed.pop(url, None)
        
        self._guild_queues.pop(guild_id, None)
        
        # Clean up channel queues
        for channel_id, urls in list(self._channel_queues.items()):
            urls.difference_update(guild_urls)
            if not urls:
                self._channel_queues.pop(channel_id, None)
        
        return cleared

    async def cleanup(self):
        """Clean up resources and stop queue processing"""
        # Cancel processor task
        if self._processor_task and not self._processor_task.done():
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass
        
        # Cancel all active tasks
        for task in self._active_tasks:
            if not task.done():
                task.cancel()
        
        await asyncio.gather(*self._active_tasks, return_exceptions=True)
        
        # Clear all collections
        self._queue = asyncio.Queue()
        self._processing.clear()
        self._completed.clear()
        self._failed.clear()
        self._guild_queues.clear()
        self._channel_queues.clear()
        
        # Clear weak references
        self._weak_refs.clear()
