import asyncio
import os
import queue
import time

import nbformat

from fastapi import FastAPI, Form, HTTPException
from jupyter_client import KernelManager
from nbformat.v4 import new_notebook
from pydantic import BaseModel


app = FastAPI()

BASE_FOLDER = '/mnt/data'
SESSIONS_FOLDER = '/mnt/jupyter_sessions'


class JupyterController:
    def __init__(self, folder_path):
        self.folder_path = folder_path
        self.notebook_path = None
        self.kernel_manager = None
        self.kernel_client = None
        self._kernel_ready = False

    async def _wait_for_kernel_ready(self, timeout=30):
        start_time = time.time()
        while not self._kernel_ready:
            if time.time() - start_time > timeout:
                raise TimeoutError('Kernel failed to start within timeout period')
            try:
                if self.kernel_manager and self.kernel_manager.is_alive():
                    self.kernel_client.execute('1+1')
                    while True:
                        try:
                            msg = self.kernel_client.get_iopub_msg(timeout=0.1)
                            if (
                                msg['header']['msg_type'] == 'status'
                                and msg['content']['execution_state'] == 'idle'
                            ):
                                break
                        except queue.Empty:
                            break
                    self._kernel_ready = True
                    break
            except Exception as e:
                print(f'Kernel init error: {str(e)}')
            await asyncio.sleep(0.1)

    async def create_notebook(self, notebook_name):
        os.makedirs(self.folder_path, exist_ok=True)
        self.notebook_path = os.path.join(self.folder_path, f'{notebook_name}.ipynb')
        nb = new_notebook()
        with open(self.notebook_path, 'w') as f:
            nbformat.write(nb, f)
        self.kernel_manager = KernelManager()
        self.kernel_manager.start_kernel()
        self.kernel_client = self.kernel_manager.client()
        self.kernel_client.start_channels()
        await self._wait_for_kernel_ready()
        self._clear_output_queue()
        return self.notebook_path

    def _clear_output_queue(self):
        while True:
            try:
                self.kernel_client.get_iopub_msg(timeout=0.1)
            except queue.Empty:
                break

    async def execute_code(self, code):
        if not self._kernel_ready:
            raise RuntimeError(
                'Kernel not ready. Please wait for initialization or restart session.'
            )
        if not self.kernel_manager.is_alive():
            self._kernel_ready = False
            raise RuntimeError('Kernel died. Please restart session.')
        self._clear_output_queue()
        msg_id = self.kernel_client.execute(code)
        outputs = []
        error_encountered = False
        while True:
            try:
                msg = self.kernel_client.get_iopub_msg(timeout=10)
                msg_type = msg['header']['msg_type']
                content = msg['content']
                if msg_type == 'stream':
                    outputs.append(content['text'])
                elif msg_type == 'execute_result':
                    outputs.append(str(content['data'].get('text/plain', '')))
                elif msg_type == 'display_data':
                    text_data = content['data'].get('text/plain', '')
                    if text_data:
                        outputs.append(str(text_data))
                elif msg_type == 'error':
                    error_encountered = True
                    raise HTTPException(
                        status_code=400,
                        detail={
                            'error': 'Execution error',
                            'traceback': content['traceback'],
                        },
                    )
                elif msg_type == 'status' and content['execution_state'] == 'idle':
                    if not error_encountered:
                        break
            except queue.Empty:
                raise HTTPException(status_code=408, detail='Code execution timed out')
        return '\n'.join(outputs) if outputs else ''

    async def reset_kernel(self):
        if self.kernel_manager:
            self._kernel_ready = False
            self.kernel_manager.restart_kernel()
            await self._wait_for_kernel_ready()
            self._clear_output_queue()

    def cleanup(self):
        if self.kernel_client:
            self.kernel_client.stop_channels()
        if self.kernel_manager:
            self.kernel_manager.shutdown_kernel(now=True)
        if self.notebook_path and os.path.exists(self.notebook_path):
            os.remove(self.notebook_path)


class SessionInfo:
    def __init__(self, controller, created_at: float):
        self.controller = controller
        self.created_at = created_at
        self.last_activity = created_at


sessions: dict[str, SessionInfo] = {}


class ExecuteRequest(BaseModel):
    user_id: str
    code: str


class InstallPackageRequest(BaseModel):
    user_id: str
    package_name: str


async def cleanup_inactive_sessions():
    while True:
        current_time = time.time()
        to_remove = []
        for user_id, session_info in sessions.items():
            if current_time - session_info.last_activity > 3600:
                to_remove.append(user_id)
        for user_id in to_remove:
            session_info = sessions.pop(user_id)
            session_info.controller.cleanup()
        await asyncio.sleep(300)


@app.on_event('startup')
async def startup_event():
    asyncio.create_task(cleanup_inactive_sessions())


async def get_session(user_id: str) -> SessionInfo:
    if user_id not in sessions:
        raise HTTPException(
            status_code=404, detail='Session not found. Please start a new session.'
        )
    session_info = sessions[user_id]
    session_info.last_activity = time.time()
    if not session_info.controller._kernel_ready:
        try:
            await session_info.controller._wait_for_kernel_ready(timeout=10)
        except TimeoutError:
            await session_info.controller.reset_kernel()
    return session_info


@app.post('/start_session')
async def start_session(user_id: str = Form(...)):
    if user_id in sessions:
        sessions[user_id].controller.cleanup()
    session_folder = os.path.join(SESSIONS_FOLDER, user_id)
    controller = JupyterController(session_folder)
    try:
        notebook_path = await controller.create_notebook(f'notebook_{user_id}')
        sessions[user_id] = SessionInfo(controller, time.time())
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
    session_info = await get_session(request.user_id)
    try:
        output = await session_info.controller.execute_code(request.code)
        return {'output': output}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post('/reset')
async def reset_session(user_id: str = Form(...)):
    session_info = await get_session(user_id)
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
    if user_id not in sessions:
        raise HTTPException(status_code=404, detail='Session not found')
    session_info = sessions.pop(user_id)
    session_info.controller.cleanup()
    return {'message': 'Session ended successfully'}
