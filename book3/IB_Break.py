"""
IB_Break - Chapter 19.  When it goes wrong.

Two tools, and the second one needs the first.

  backtrace(K)   turns the machine's continuation stack into something a
                 person can read.  It is the whole of a backtrace, because
                 K already IS the stack of unfinished work.

  break_loop(E)  stops and hands you a prompt bound to the environment the
                 error happened in.  It is a REPL with a different E.

Two facts about the backtrace are the point of the chapter, and both of them
are consequences of decisions Book One made for unrelated reasons:

  * A frame records what is WAITING, not who is RUNNING.  A closure is
    (VAL_CLOSURE, params, body, env) with no name in it, so nothing in K can
    tell you which function you are inside.

  * Chapter 3's tail-call optimization works by not keeping frames.  The same
    bug, at the same depth, leaves 21 frames when written with a pending `+`
    and 1 frame when written tail-recursively.  See main() at the foot.

Run with: python IB_Break.py
"""

import IB_Core as Core
from IB_Core import (FRAME_IF, FRAME_SET, FRAME_SEQ,
                     FRAME_CALL, MachineError,
                     global_env, lisp_str)
from IB_Printer import flat, primitive_names
from IB_Repl import evaluate


# ---------------------------------------------------------------------------
# The backtrace
# ---------------------------------------------------------------------------
#
# One line per frame, innermost first.  Each line says what that frame is
# waiting for, because that is the only thing a frame knows.

_NAMES = None

def frame_str(frame):
  global _NAMES
  if _NAMES is None:
    _NAMES = primitive_names()
  tag = frame[0]
  if tag == FRAME_IF:
    return ('if: waiting on the test of '
            + lisp_str(frame[1]))
  if tag == FRAME_SET:
    return ('set!: waiting on the value for '
            + str(frame[1]))
  if tag == FRAME_SEQ:
    n = len(frame[1])
    return ('begin: ' + str(n)
            + ' form(s) still to run')
  if tag == FRAME_CALL:
    done, todo = frame[1], frame[2]
    if not done:
      return 'call: waiting on the operator'
    fn = flat(done[0], _NAMES)
    return ('call: applying ' + fn + ', '
            + str(len(done) - 1) + ' of '
            + str(len(done) - 1 + len(todo))
            + ' argument(s) evaluated')
  return 'frame: ' + str(tag)


def backtrace(K, limit=None):
  """Innermost frame first.  A list of strings, one per frame."""
  frames = list(reversed(K))
  if limit is not None:
    frames = frames[:limit]
  out = []
  for i, frame in enumerate(frames):
    out.append('  ' + str(i) + ': '
               + frame_str(frame))
  return out


def print_backtrace(K, limit=None):
  if not K:
    print('  (no frames: the machine was at '
          'the top of the program)')
    return
  for line in backtrace(K, limit):
    print(line)


# ---------------------------------------------------------------------------
# The break loop
# ---------------------------------------------------------------------------
#
# A REPL is a read-eval-print loop over the global environment.  A break loop
# is the same loop over the environment a program stopped in.  That is the
# entire difference, and it is why this chapter can reuse Chapter 18's REPL.
#
# `extra` lets a later chapter add commands without reopening this function.
# Chapter 21's debugger passes its stepping commands in that way.  A handler
# is called with the rest of the line and returns either None (stay at the
# prompt) or a string, which becomes break_loop's return value.

def _evaluate(source, env):
  """Run one form in the stopped environment.

    The hook is suppressed while this runs.  Without that, a debugger's own
    prompt would step on itself: evaluating an expression here would call
    back into the tool that is asking for it.
  """
  saved = Core.step_hook
  Core.step_hook = None
  try:
    return evaluate(source, env)
  finally:
    Core.step_hook = saved


def break_loop(E, K, extra=None, prompt='break> ',
               banner=None, read=input):
  if banner:
    print(banner)
  handlers = dict(extra or {})
  while True:
    try:
      line = read(prompt).strip()
    except (EOFError, KeyboardInterrupt):
      print()
      return 'abort'
    if not line:
      continue
    word, _, rest = line.partition(' ')
    rest = rest.strip()

    if word in handlers:
      answer = handlers[word](rest)
      if answer is not None:
        return answer
      continue

    if word in ('c', 'continue'):
      return 'continue'
    if word in ('q', 'abort'):
      return 'abort'
    if word == 'bt':
      print_backtrace(K)
      continue
    if word == 'h':
      print('  c continue   q abort   bt '
            'backtrace')
      print('  anything else is evaluated '
            'in the stopped environment')
      for name in sorted(handlers):
        print('  ' + name)
      continue

    try:
      print(lisp_str(_evaluate(line, E)))
    except MachineError as err:
      print('error: ' + str(err))
    except Exception as err:
      print('error: ' + str(err))


# ---------------------------------------------------------------------------
# Running a program with the break loop attached
# ---------------------------------------------------------------------------

def scripted(commands):
  """A stand-in for input() that plays a fixed list of commands.

    Every session printed in this chapter is real output, produced by handing
    break_loop one of these instead of the keyboard.
  """
  pending = list(commands)
  def read(prompt):
    if not pending:
      raise EOFError
    line = pending.pop(0)
    print(prompt + line)
    return line
  return read


def run(source, env=None, interactive=True,
        read=input):
  """Evaluate one form.  On failure, report and stop where it happened."""
  env = env or global_env
  try:
    return evaluate(source, env)
  except MachineError as err:
    print()
    print('*** ' + str(err))
    print('    while evaluating: '
          + lisp_str(err.C))
    print('    backtrace:')
    print_backtrace(err.K)
    if interactive:
      break_loop(err.E, err.K, read=read,
                 banner='    (c or q to leave)')
    return None


# ---------------------------------------------------------------------------
# The chapter's measurement
# ---------------------------------------------------------------------------

TAIL = """(begin
  (set! countdown
    (lambda (n)
      (if (= n 0) (oops 1)
          (countdown (- n 1)))))
  (countdown 20))"""

NON_TAIL = """(begin
  (set! addup
    (lambda (n)
      (if (= n 0) (oops 1)
          (+ 1 (addup (- n 1))))))
  (addup 20))"""


def depth_of(source):
  try:
    evaluate(source)
  except MachineError as err:
    return len(err.K), err
  return None, None


SESSION = """(begin
  (set! area
    (lambda (w d) (* w (oops d))))
  (set! total
    (lambda (a b) (+ (area a b) 1)))
  (total 2 3))"""


def session_demo():
  print('--- stopped where it happened ---')
  run(SESSION, read=scripted(
      ['w', 'd', '(* w d)', 'bt', 'q']))


def main():
  for label, src in (('tail-recursive', TAIL),
                     ('non-tail', NON_TAIL)):
    depth, err = depth_of(src)
    print(label + ': ' + str(err)
          + '   K depth = ' + str(depth))
    print_backtrace(err.K, limit=3)
    print()

  print('Same bug, same depth of call, two '
        'different backtraces.')
  print('The difference is the tail-call '
        'optimization of Chapter 3.')
  print()
  session_demo()


if __name__ == '__main__':
  main()
