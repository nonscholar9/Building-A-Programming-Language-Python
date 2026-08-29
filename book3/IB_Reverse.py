"""
IB_Reverse - Chapter 23.  Stepping backward.

Chapter 21 stopped the machine and looked at C, E and K.  This chapter keeps
them, and lets you walk back up the program you have just run.

The reason it is a chapter and not a paragraph is that two of the three
registers cooperate and one does not.

  C  is a form.  Keeping it is keeping a reference.  Free.

  K  is a Python list, and the machine mutates it in place, so a snapshot is
     a copy.  That is O(depth) per step, and it is the first honest cost.
     A challenge at the end of the chapter makes K a linked list, after which
     a snapshot is one pointer and every past K shares its whole tail.

  E  is MUTABLE, and no amount of copying fixes it.  Keeping a reference to
     an environment keeps a reference to whatever it holds NOW.  `set!` has
     been overwriting it ever since.  So restoring a saved state restores the
     shape of the past and not the values of the past, and a debugger that
     showed you that would be lying.

The repair is an undo log: every `set!` records what it overwrote, and
rewinding puts it back.  drift_demo() below measures the lie, and
rewind_demo() measures the repair.

There is a third thing the naive version cannot do, and it is worth naming
because it explains how real time-travel debuggers are built.  You can look at
a past state, but you cannot RESUME from one, because Book One's `lEval` takes
an expression and an environment and starts with K empty.  There is no way in
that takes a K.  Rather than open the machine a third time, this chapter does
what the real ones do: it replays the program from the beginning and stops at
the step you asked for.  Replay is cheap, and it is exact for as long as the
program is deterministic.

Run with: python IB_Reverse.py
"""

import IB_Core as Core
from IB_Core import (Environment, MachineError,
                     global_env, lisp_str)
from IB_Repl import evaluate


# ---------------------------------------------------------------------------
# The undo log
# ---------------------------------------------------------------------------
#
# Environment.set walks the scope chain and writes into whichever scope holds
# the name, or into the globals if none does.  To be able to put it back we
# have to know two things it does not return: which scope it wrote to, and
# what was there before.  So we walk the chain first, then let the machine's
# own method do the writing.

class UndoLog:
  def __init__(self):
    self.entries = []      # (step, env, name, had, old)
    self._original = None
    self.step = 0

  def install(self):
    if self._original is not None:
      return
    self._original = Environment.set
    log = self

    def logging_set(env, name, value):
      target = env
      while target is not None:
        if name in target._bindings:
          break
        target = target._outer
      if target is None:
        target = env._global
        log.entries.append(
            (log.step, target, name,
             False, None))
      else:
        log.entries.append(
            (log.step, target, name, True,
             target._bindings[name]))
      return log._original(env, name, value)

    Environment.set = logging_set

  def uninstall(self):
    if self._original is not None:
      Environment.set = self._original
      self._original = None

  def undo_after(self, step):
    """Put back everything written at or after `step`, newest first."""
    undone = 0
    while self.entries:
      recorded, env, name, had, old = \
          self.entries[-1]
      if recorded < step:
        break
      self.entries.pop()
      if had:
        env._bindings[name] = old
      else:
        env._bindings.pop(name, None)
      undone = undone + 1
    return undone


# ---------------------------------------------------------------------------
# The recorder
# ---------------------------------------------------------------------------

class Recorder:
  """The hook again, with `remember` where the debugger had `stop`."""

  def __init__(self, keep_undo=True):
    self.states = []       # (C, E, K-snapshot)
    self.frames_copied = 0
    self.undo = UndoLog() if keep_undo else None

  def on_expr(self, C, E, K):
    self.states.append((C, E, list(K)))
    self.frames_copied += len(K)
    if self.undo is not None:
      self.undo.step = len(self.states) - 1

  # ---- running -----------------------------------------------------------

  def record(self, source, env=None):
    env = env or global_env
    self.states = []
    self.frames_copied = 0
    if self.undo is not None:
      self.undo.entries = []
      self.undo.install()
    Core.step_hook = self.on_expr
    try:
      return evaluate(source, env)
    finally:
      Core.step_hook = None
      if self.undo is not None:
        self.undo.uninstall()

  # ---- looking backward --------------------------------------------------

  def state_at(self, index):
    return self.states[index]

  def show(self, index):
    C, E, K = self.states[index]
    print('  step ' + str(index) + ':  C = '
          + lisp_str(C) + '   depth of K = '
          + str(len(K)))

  def rewind_to(self, index):
    """Undo every mutation made at or after `index`, then hand back E."""
    if self.undo is None:
      return self.states[index]
    self.undo.undo_after(index)
    return self.states[index]

  def value_at(self, index, name):
    """What was `name` bound to when the machine was at step `index`?"""
    C, E, K = self.states[index]
    try:
      return lisp_str(E.lookup(name))
    except NameError:
      return '<unbound>'

  # ---- replay, which is how the real ones do it --------------------------

  def replay_to(self, source, index, env=None):
    """Re-run from the top and stop at step `index`.

      A saved state cannot be resumed, because the machine has no entry
      point that takes a K.  Replay needs none: it starts where the machine
      always starts.  The price is that the program runs again, so anything
      it printed the first time prints a second time.
    """
    env = env or global_env
    box = {}

    def stop_there(C, E, K):
      box['n'] = box.get('n', -1) + 1
      if box['n'] == index:
        raise _Arrived()

    Core.step_hook = stop_there
    try:
      evaluate(source, env)
    except MachineError as err:
      # The machine's other opening does the work here.  Anything raised
      # inside the hook comes back out as a MachineError with C, E and K
      # already attached, so the tool does not have to carry them itself.
      if isinstance(err.__cause__, _Arrived):
        return (err.C, err.E, list(err.K))
      return None
    finally:
      Core.step_hook = None
    return None


class _Arrived(Exception):
  """Raised inside the hook to stop the replay.  It never escapes: the
    machine catches it and re-raises it as a MachineError carrying C, E and K.
  """


# ---------------------------------------------------------------------------
# The chapter's measurements
# ---------------------------------------------------------------------------

COUNTING = """(begin
  (set! counter 0)
  (set! bump
    (lambda () (set! counter (+ counter 1))))
  (bump)
  (bump)
  (bump)
  counter)"""

NESTED = """(begin
  (set! addup
    (lambda (n)
      (if (= n 0) 0
          (+ 1 (addup (- n 1))))))
  (addup 8))"""


def cost_demo():
  print('--- what it costs to keep the '
        'past ---')
  for label, src in (('counting', COUNTING),
                     ('nested', NESTED)):
    rec = Recorder(keep_undo=False)
    answer = rec.record(src)
    print('  ' + label + ': '
          + str(len(rec.states))
          + ' states, '
          + str(rec.frames_copied)
          + ' frames copied, answer '
          + lisp_str(answer))
  print('  C costs a reference.  K costs a '
        'copy, once per step.')


def drift_demo():
  print()
  print('--- the lie: E is mutable, so a '
        'saved state drifts ---')
  rec = Recorder(keep_undo=False)
  rec.record(COUNTING)
  marks = [i for i, s in enumerate(rec.states)
           if s[0] == 'counter']
  print('  `counter` is evaluated at steps '
        + str(marks))
  print('  and at every one of those steps '
        'it really held a different value.')
  print('  Ask the saved states now:')
  for i in marks:
    print('    step ' + str(i)
          + ': counter = '
          + rec.value_at(i, 'counter'))
  print('  Every answer is the LAST one.  '
        'The states kept a reference')
  print('  to the environment, and set! '
        'has been writing to it since.')


def rewind_demo():
  print()
  print('--- the repair: an undo log ---')
  rec = Recorder(keep_undo=True)
  rec.record(COUNTING)
  marks = [i for i, s in enumerate(rec.states)
           if s[0] == 'counter']
  print('  rewinding to each step in turn, '
        'newest first:')
  for i in reversed(marks):
    rec.rewind_to(i)
    print('    step ' + str(i)
          + ': counter = '
          + rec.value_at(i, 'counter'))
  print('  Backwards only, and once: an '
        'undo log is a one-way street.')


def replay_demo():
  print()
  print('--- replay, because a state '
        'cannot be resumed ---')
  rec = Recorder(keep_undo=False)
  rec.record(NESTED)
  index = len(rec.states) // 2
  saved = rec.state_at(index)
  again = rec.replay_to(NESTED, index)
  print('  step ' + str(index) + ' recorded: '
        + lisp_str(saved[0]) + '  depth '
        + str(len(saved[2])))
  print('  step ' + str(index) + ' replayed: '
        + lisp_str(again[0]) + '  depth '
        + str(len(again[2])))
  print('  same form, same depth: '
        + str(saved[0] == again[0]
              and len(saved[2])
              == len(again[2])))


def main():
  cost_demo()
  drift_demo()
  rewind_demo()
  replay_demo()


if __name__ == '__main__':
  main()
