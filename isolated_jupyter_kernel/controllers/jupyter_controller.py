import asyncio
import os

from queue import Empty
from time import time

import nbformat

from fastapi import HTTPException
from jupyter_client import KernelManager
from nbformat.v4 import new_notebook


class JupyterController:
    def __init__(self, folder_path):
        self.folder_path = folder_path
        self.notebook_path = None
        self.kernel_manager = None
        self.kernel_client = None
        self._kernel_ready = False

    async def _wait_for_kernel_ready(self, timeout=30):
        start_time = time()
        while not self._kernel_ready:
            if time() - start_time > timeout:
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
                        except Empty:
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
            except Empty:
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
            except Empty:
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
