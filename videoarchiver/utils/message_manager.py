"""Message management utilities"""

import asyncio
import logging
from typing import Dict

logger = logging.getLogger("VideoArchiver")

class MessageManager:
    def __init__(self, message_duration: int, message_template: str):
        self.message_duration = message_duration
        self.message_template = message_template
        self.scheduled_deletions: Dict[int, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    def format_archive_message(
        self, author: str, url: str, original_message: str
    ) -> str:
        return self.message_template.format(
            author=author, url=url, original_message=original_message
        )

    async def schedule_message_deletion(self, message_id: int, delete_func) -> None:
        if self.message_duration <= 0:
            return

        async with self._lock:
            if message_id in self.scheduled_deletions:
                self.scheduled_deletions[message_id].cancel()

            async def delete_later():
                try:
                    await asyncio.sleep(self.message_duration * 3600)
                    await delete_func()
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    logger.error(f"Failed to delete message {message_id}: {str(e)}")
                finally:
                    async with self._lock:
                        self.scheduled_deletions.pop(message_id, None)

            self.scheduled_deletions[message_id] = asyncio.create_task(delete_later())

    async def cancel_all_deletions(self):
        """Cancel all scheduled message deletions"""
        async with self._lock:
            for task in self.scheduled_deletions.values():
                task.cancel()
            await asyncio.gather(*self.scheduled_deletions.values(), return_exceptions=True)
            self.scheduled_deletions.clear()
