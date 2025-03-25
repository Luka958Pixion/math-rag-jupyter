import asyncio
import os
import time

from contextlib import asynccontextmanager

from decouple import config
from fastapi import FastAPI, Form, HTTPException

from math_rag_jupyter.controllers import JupyterController
from math_rag_jupyter.requests import ExecuteRequest
from math_rag_jupyter.sessions import SessionInfo, SessionManager


session_manager = SessionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(session_manager.cleanup_inactive_sessions())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)

JUPYTER_SESSIONS_DIR = config('JUPYTER_SESSIONS_DIR', default='/mnt/jupyter_sessions')


@app.post('/start_session')
async def start_session(user_id: str = Form(...)):
    if user_id in session_manager._sessions:
        session_manager._sessions[user_id].controller.cleanup()

    session_dir = os.path.join(JUPYTER_SESSIONS_DIR, user_id)
    controller = JupyterController(session_dir)

    try:
        notebook_path = await controller.create_notebook(f'notebook_{user_id}')
        session_manager._sessions[user_id] = SessionInfo(controller, time.time())
        setup_code = """
        import pandas as pd
        import numpy as np
        import matplotlib.pyplot as plt
        """
        await controller.execute_code(setup_code)

        return {
            'message': 'Session started successfully',
            'notebook_path': notebook_path,
        }

    except Exception as e:
        controller.cleanup()
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/execute')
async def execute_code(request: ExecuteRequest):
    session_info = await session_manager.get_session(request.user_id)

    try:
        output = await session_info.controller.execute_code(request.code)

        return {'output': output}

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/reset')
async def reset_session(user_id: str = Form(...)):
    session_info = await session_manager.get_session(user_id)

    try:
        await session_info.controller.reset_kernel()
        setup_code = """
        import pandas as pd
        import numpy as np
        import matplotlib.pyplot as plt
        """
        await session_info.controller.execute_code(setup_code)

        return {'message': 'Kernel reset successful'}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/end_session')
async def end_session(user_id: str = Form(...)):
    if user_id not in session_manager._sessions:
        raise HTTPException(status_code=404, detail='Session not found')

    session_info = session_manager._sessions.pop(user_id)
    session_info.controller.cleanup()

    return {'message': 'Session ended successfully'}
