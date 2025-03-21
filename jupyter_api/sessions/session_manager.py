import asyncio

from time import time

from fastapi import HTTPException

from .session_info import SessionInfo


class SessionManager:
    def __init__(self):
        self._sessions: dict[str, SessionInfo] = {}

    @property
    def sessions(self) -> dict[str, SessionInfo]:
        return self._sessions

    async def get_session(self, user_id: str) -> SessionInfo:
        if user_id not in self._sessions:
            raise HTTPException(
                status_code=404, detail='Session not found, please start a new session'
            )

        session_info = self._sessions[user_id]
        session_info.last_activity = time()

        if not session_info.controller._kernel_ready:
            try:
                await session_info.controller._wait_for_kernel_ready(timeout=10)

            except TimeoutError:
                await session_info.controller.reset_kernel()

        return session_info

    async def cleanup_inactive_sessions(self):
        while True:
            current_time = time()
            to_remove = []

            for user_id, session_info in self._sessions.items():
                if current_time - session_info.last_activity > 3600:
                    to_remove.append(user_id)

            for user_id in to_remove:
                session_info = self._sessions.pop(user_id)
                session_info.controller.cleanup()

            await asyncio.sleep(300)
