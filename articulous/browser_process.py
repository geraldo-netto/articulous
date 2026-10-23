"""BUILD-009/013: owned browser sessions with explicit deadlines or suite checkpoints."""
from collections.abc import Sequence
import subprocess
import sys

from .backends.processes import open_session
from .process_contracts import SessionOptions, deadline_seconds


def command_arguments(command: object) -> list[str]:
    if isinstance(command, (str, bytes)) or not isinstance(command, Sequence):
        raise ValueError('Browser command must be a sequence of string arguments')
    if not command:
        raise ValueError('Browser command is empty')
    for argument in command:
        if not isinstance(argument, str) or '\x00' in argument:
            raise ValueError('Browser arguments must be strings without NUL')
    if not command[0]:
        raise ValueError('Browser executable is empty')
    return list(command)



def run_browser(command: object, *, timeout: object) -> subprocess.CompletedProcess[str]:
    arguments = command_arguments(command)
    seconds = deadline_seconds(timeout)
    with open_session(arguments) as session:
        try:
            stdout, stderr = session.communicate(seconds)
        except subprocess.TimeoutExpired as error:
            stdout, stderr = session.stop()
            raise subprocess.TimeoutExpired(arguments, seconds, output=stdout, stderr=stderr) from error
        return completed_session(arguments, session, stdout, stderr)


def completed_session(arguments, session, stdout, stderr):
    code = session.returncode
    if code is None:
        raise RuntimeError('Native session completed without exit evidence')
    return subprocess.CompletedProcess(arguments, code, stdout, stderr)


def report_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def settled_checkpoint(stderr: str | bytes | None, previous: str, report) -> str:
    output = stderr.decode(errors='replace') if isinstance(stderr, bytes) else (stderr or '')
    stages = [line for line in output.split('\n')[:-1] if line.startswith('[BUILD-013] settled ')]
    latest = stages[-1] if stages else previous
    if latest != previous:
        report(latest)
    else:
        report('[BUILD-013] no newly settled stage; native operation progress uncertain; protocol bounds remain active')
    return latest


def run_browser_suite(command: object, *, checkpoint: object = 30, report=report_progress, tooling=True) -> subprocess.CompletedProcess[str]:
    """Observe a protocol-bounded finite suite; checkpoint expiry is not failure.

    The caller owns case admission; native CDP commands retain their 10-second
    deadlines. Cancellation and errors leave through the same owned-tree fence
    as fixed-deadline sessions. Missing stage progress is reported as uncertainty,
    never invented progress or a passing result.
    """
    arguments = command_arguments(command)
    seconds = deadline_seconds(checkpoint)
    previous = ''
    with open_session(arguments, options=SessionOptions(tooling=tooling, checkpoint_output=True)) as session:
        while True:
            try:
                stdout, stderr = session.communicate(seconds)
                return completed_session(arguments, session, stdout, stderr)
            except subprocess.TimeoutExpired as error:
                previous = settled_checkpoint(error.stderr, previous, report)


def run_owned(command, *, tooling=True):
    result = run_browser_suite(command, tooling=tooling)
    result.check_returncode()
    return result


def main(argv=None):
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    result = run_browser_suite(args.command)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
