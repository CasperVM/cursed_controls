from fastapi import Request
from cursed_controls.app_state import AppState


def get_state(request: Request) -> AppState:
    return request.app.state.app_state


def get_runtime_manager(request: Request):
    return request.app.state.runtime_manager
