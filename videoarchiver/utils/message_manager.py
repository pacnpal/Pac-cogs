"""Message management utilities"""

import asyncio
from collections import defaultdict
import logging
from typing import Dict, List

logger = logging.getLogger("VideoArchiver")

class MessageManager:
    def __init__(self, message_duration: int, message_template: str):
        self.message_duration = message_duration
        self.message_template = message_template
        self.scheduled_deletions: Dict[int, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    def format_archive_message(
        self, author: str, url: str, original_message: str, **fields: str
    ) -> str:
        # Templates use {username}/{channel} too; anything not passed renders as "Unknown"
        values = defaultdict(lambda: "Unknown", fields)
        values.update(author=author, url=url, original_message=original_message)
        return self.message_template.format_map(values)

    async def get_message_reactions(self, message) -> List[Dict]:
        """Get all reactions from a message"""
        reactions = []
        for reaction in message.reactions:
            reactions.append({
                'emoji': str(reaction.emoji),
                'count': reaction.count,
                'users': [user.id async for user in reaction.users()]
            })
        return reactions

    async def restore_reactions(self, message, reactions: List[Dict]) -> None:
        """Restore reactions to a message"""
        for reaction_data in reactions:
            try:
                await message.add_reaction(reaction_data['emoji'])
            except Exception as e:
                logger.error(f"Failed to restore reaction {reaction_data['emoji']}: {str(e)}")

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
            tasks = list(self.scheduled_deletions.values())
            self.scheduled_deletions.clear()
        for task in tasks:
            task.cancel()
        # Outside the lock: each task's finally takes it to unregister itself
        await asyncio.gather(*tasks, return_exceptions=True)
