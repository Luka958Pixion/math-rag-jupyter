import asyncio
import os
import time

from contextlib import asynccontextmanager

from decouple import config
from fastapi import FastAPI, Form, HTTPException
from scalar_fastapi import get_scalar_api_reference

from math_rag_jupyter.controllers import JupyterController
from math_rag_jupyter.sessions import SessionInfo, SessionManager


session_manager = SessionManager()


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(session_manager.cleanup_inactive_sessions())
    yield
    task.cancel()


app = FastAPI(lifespan=lifespan)

JUPYTER_SESSIONS_DIR = config('JUPYTER_SESSIONS_DIR', default='/mnt/jupyter_sessions')


@app.post('/start-session')
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


@app.post('/execute-code')
async def execute_code(user_id: str = Form(...), code: str = Form(...)):
    session_info = await session_manager.get_session(user_id)

    try:
        output = await session_info.controller.execute_code(code)

        return {'output': output}

    except HTTPException:
        raise

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/reset-session')
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


@app.post('/end-session')
async def end_session(user_id: str = Form(...)):
    if user_id not in session_manager._sessions:
        raise HTTPException(status_code=404, detail='Session not found')

    session_info = session_manager._sessions.pop(user_id)
    session_info.controller.cleanup()

    return {'message': 'Session ended successfully'}


@app.get('/health')
async def health_check():
    return {'status': 'ok'}


@app.get('/scalar', include_in_schema=False)
async def scalar_html():
    return get_scalar_api_reference(
        openapi_url=app.openapi_url,
        title=app.title,
    )
