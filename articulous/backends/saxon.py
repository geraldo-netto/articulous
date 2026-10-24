"""Native Saxon command adapter; descriptor borrows stay inside this boundary."""
from ..browser_process import observe_session
from ..process_contracts import SessionOptions
from .processes import open_session


def run_transform_command(command, *, pass_fds):
    options = SessionOptions(tooling=False, checkpoint_output=True, seal_on_exit=True)
    with open_session(command, options=options, pass_fds=pass_fds) as session:
        result = observe_session(command, session, 30)
    result.check_returncode()
    return result
