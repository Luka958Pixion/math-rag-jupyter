from jupyter.controllers import JupyterController


class SessionInfo:
    def __init__(self, controller: JupyterController, created_at: float):
        self.controller = controller
        self.created_at = created_at
        self.last_activity = created_at
