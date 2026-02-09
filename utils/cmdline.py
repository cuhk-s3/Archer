import os
import shlex
import signal
import subprocess


def safe_killpg(pid, sig):
  try:
    os.killpg(pid, sig)
  except ProcessLookupError:
    pass  # Ignore if there is no such process


def spawn_process(
  cmd, stdout, stderr, timeout, **kwargs
) -> subprocess.CompletedProcess:
  # Fix: subprocess.run(cmd) series methods, when timed out, only send a SIGTERM
  # signal to cmd while does not kill cmd's subprocess. We let each command run
  # in a new process group by adding start_new_session flag, and kill the whole
  # process group such that all cmd's subprocesses are also killed when timed out.
  with subprocess.Popen(
    cmd, stdout=stdout, stderr=stderr, start_new_session=True, **kwargs
  ) as proc:
    try:
      output, err_msg = proc.communicate(timeout=timeout)
    except:  # Including TimeoutExpired, KeyboardInterrupt, communicate handled that.
      safe_killpg(os.getpgid(proc.pid), signal.SIGKILL)
      # We don't call proc.wait() as .__exit__ does that for us.
      raise
    ecode = proc.poll()
  return subprocess.CompletedProcess(proc.args, ecode, output, err_msg)


def check_call(cmd: str, timeout: int = 60, **kwargs):
  proc = spawn_process(
    shlex.split(cmd),
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    timeout=timeout,
    **kwargs,
  )
  proc.check_returncode()


def getoutput(cmd: str, timeout: int = 60, check=True, **kwargs):
  proc = spawn_process(
    shlex.split(cmd),
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,
    timeout=timeout,
    **kwargs,
  )
  if check:
    proc.check_returncode()
  return proc.stdout


def check_output(cmd: str, timeout: int = 60, **kwargs):
  return getoutput(cmd, timeout, check=True, **kwargs)
