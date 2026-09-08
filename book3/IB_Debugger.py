"""
IB_Debugger - Chapter 21.  The debugger.

Chapter 19 stopped the machine when it broke.  This chapter stops it on
purpose, and that is the whole difference.

Everything here hangs off `IB_Core.step_hook`, the one call Book Three added
at the top of the EVAL loop.  The hook is handed C, E and K, and every feature
below is a question asked of one of them:

    a breakpoint   is a predicate on C
    a watch        is a predicate on E
    step into      stop at the next expression, whatever its depth
    step over      stop at the next expression with len(K) <= here
    step out       stop at the next expression with len(K) <  here

Those last three are the chapter.  On a machine that keeps its unfinished work
in the host language's call stack there is nothing to compare.  Here the depth
of the continuation is an integer you own, so the three commands every
debugger has are three comparisons on it.

And one of them is a lie, for a reason Chapter 3 is responsible for.  Step out
means "run until this call returns", and a tail call has no frame to return
to.  tail_call_demo() at the foot of this file measures it.

Run with: python IB_Debugger.py
"""

import IB_Core as Core
from IB_Core import (MachineError, global_env,
                     lisp_str)
from IB_Repl import evaluate
from IB_Break import (break_loop, print_backtrace,
                      scripted, _evaluate)


class Debugger:
  """A set of names, a list of expressions, and one integer."""

  def __init__(self):
    self.breakpoints = set()
    self.watches = []
    self._stepping = False
    self._skip_until = None
    self._env = global_env
    self._read = input

  # -----------------------------------------------------------------------
  # The hook
  # -----------------------------------------------------------------------
  #
  # Called once per expression, before the machine looks at it.  Two
  # questions, in this order: is there a breakpoint on this form, and if not,
  # are we stepping and is this shallow enough to be interesting?

  def on_expr(self, C, E, K):
    name = self.breakpoint_on(C)
    if name is not None:
      self.stop(C, E, K,
                '*** Breakpoint: ' + name)
      return
    self.step_check(C, E, K)

  def step_check(self, C, E, K):
    """The three step commands, all of them one comparison on len(K)."""
    if not self._stepping:
      return
    depth = len(K)
    if self._skip_until is not None:
      if depth > self._skip_until:
        return           # still inside what we stepped over
      self._skip_until = None
    self.stop(C, E, K, None)

  def breakpoint_on(self, C):
    """The predicate on C: a form headed by a name we were asked about."""
    if not self.breakpoints:
      return None
    if not isinstance(C, list) or not C:
      return None
    head = C[0]
    if (isinstance(head, str)
        and head in self.breakpoints):
      return head
    return None

  # -----------------------------------------------------------------------
  # Stopping
  # -----------------------------------------------------------------------

  def stop(self, C, E, K, banner):
    depth = len(K)
    self._env = E
    if banner:
      print()
      print(banner)
    print(('  ' * min(depth, 12))
          + lisp_str(C))
    self.show_watches(E)
    action = break_loop(
        E, K, extra=self.commands(depth),
        prompt='debug> ', read=self._read)
    if action == 'continue':
      self._stepping = False
      self._skip_until = None
    elif action == 'abort':
      self._stepping = False
      self._skip_until = None
      raise MachineError('Aborted from the '
                         'debugger.',
                         C, E, K)

  def show_watches(self, E):
    for source in self.watches:
      try:
        value = lisp_str(_evaluate(source, E))
      except Exception:
        value = '<unbound here>'
      print('    watch ' + source + ' = '
            + value)

  def show_locals(self, E):
    """The nearest scope only.  Chapter 22 walks the whole chain."""
    if E is E._global:
      print('  (the global scope: nothing '
            'is local here)')
      return
    shown = 0
    for name in sorted(E._bindings):
      value = E._bindings[name]
      if callable(value):
        continue          # the primitives are not news
      print('  ' + name + ': '
            + lisp_str(value))
      shown = shown + 1
    if not shown:
      print('  (nothing bound in this scope)')

  # -----------------------------------------------------------------------
  # The commands this chapter adds to Chapter 19's prompt
  # -----------------------------------------------------------------------
  #
  # A handler returns None to stay at the prompt, or a string to leave it.
  # The three stepping commands all leave, and all they do on the way out is
  # set the threshold the hook will compare len(K) against.

  def commands(self, depth):
    def step_into(rest):
      self._stepping = True
      self._skip_until = None
      return 'step'

    def step_over(rest):
      self._stepping = True
      self._skip_until = depth
      return 'step'

    def step_out(rest):
      self._stepping = True
      self._skip_until = (depth - 1 if depth
                          else None)
      return 'step'

    def add_break(rest):
      if rest:
        self.breakpoints.add(rest)
        print('  breakpoint on ' + rest)
      else:
        print('  ' + (', '.join(
            sorted(self.breakpoints))
            or '(no breakpoints)'))
      return None

    def drop_break(rest):
      self.breakpoints.discard(rest)
      print('  breakpoint off ' + rest)
      return None

    def add_watch(rest):
      if rest:
        self.watches.append(rest)
      else:
        print('  ' + (', '.join(self.watches)
                      or '(no watches)'))
      return None

    def locals_here(rest):
      self.show_locals(self._env)
      return None

    return {'s': step_into, 'n': step_over,
            'o': step_out, 'b': add_break,
            'b-': drop_break, 'w': add_watch,
            'v': locals_here}

  # -----------------------------------------------------------------------
  # Running a program under the debugger
  # -----------------------------------------------------------------------

  def run(self, source, env=None, step=False,
          commands=None):
    """Evaluate one form with the hook installed.

      `step` starts stopped at the very first expression.  `commands` plays a
      fixed session instead of reading the keyboard, which is how every
      transcript in this chapter was produced.
    """
    env = env or global_env
    self._stepping = step
    self._skip_until = None
    self._env = env
    self._read = (scripted(commands) if commands
                  else input)
    Core.step_hook = self.on_expr
    try:
      return evaluate(source, env)
    except MachineError as err:
      print()
      print('*** ' + str(err))
      print_backtrace(err.K, limit=5)
      return None
    finally:
      Core.step_hook = None


# ---------------------------------------------------------------------------
# Watching the depth without a keyboard
# ---------------------------------------------------------------------------
#
# The same hook, with the prompt taken out: instead of stopping, record how
# deep K was.  It is the measurement the chapter's last section rests on, and
# it is also, exactly, Chapter 24's profiler in embryo.

def depths_at(source, names):
  dbg = Debugger()
  dbg.breakpoints.update(names)
  seen = []
  dbg.stop = (lambda C, E, K, banner:
              seen.append(len(K)))
  Core.step_hook = dbg.on_expr
  try:
    evaluate(source)
  finally:
    Core.step_hook = None
  return seen


# ---------------------------------------------------------------------------
# The chapter's demonstrations
# ---------------------------------------------------------------------------

PROGRAM = """(begin
  (set! square (lambda (x) (* x x)))
  (set! sum-squares
    (lambda (a b)
      (+ (square a) (square b))))
  (sum-squares 3 4))"""


def opening_demo():
  print('--- the smallest run that uses '
        'any of it ---')
  dbg = Debugger()
  dbg.breakpoints.add('square')
  answer = dbg.run(PROGRAM, commands=[
      'a', 'c', 'c'])
  print('==> ' + lisp_str(answer))


def breakpoint_demo():
  print()
  print('--- a breakpoint is a predicate '
        'on C ---')
  dbg = Debugger()
  dbg.breakpoints.add('square')
  answer = dbg.run(PROGRAM, commands=[
      'v', 'bt', 'c', 'c'])
  print('==> ' + lisp_str(answer))


def stepping_demo():
  print()
  print('--- s, n and o are three '
        'comparisons on len(K) ---')
  dbg = Debugger()
  dbg.breakpoints.add('sum-squares')
  dbg.watches.append('a')
  answer = dbg.run(PROGRAM, commands=[
      's', 's', 'n', 'o', 'c'])
  print('==> ' + lisp_str(answer))


TAIL = """(begin
  (set! countdown
    (lambda (n)
      (if (= n 0) (quote done)
          (countdown (- n 1)))))
  (countdown 5))"""

NON_TAIL = """(begin
  (set! addup
    (lambda (n)
      (if (= n 0) 0
          (+ 1 (addup (- n 1))))))
  (addup 5))"""


def session_demo():
  print()
  print('--- the whole thing, in one '
        'sitting ---')
  dbg = Debugger()
  dbg.breakpoints.add('sum-squares')
  answer = dbg.run(PROGRAM, commands=[
      'w a', 'v', 'b square', 'c', 'v',
      'bt', 's', 's', 's', 'v', 'c', 'c'])
  print('==> ' + lisp_str(answer))


def tail_call_demo():
  """The same algorithm, written twice, stopped at every recursive call.

    In the non-tail version the calls stack up, so stepping out of one of
    them lands in the one that called it.  In the tail version there is
    nothing to land in: Chapter 3 reused the frame instead of keeping it.
  """
  print()
  print('--- what step out means when there '
        'is no frame to go out to ---')
  non_tail = depths_at(NON_TAIL, ['addup'])
  tail = depths_at(TAIL, ['countdown'])
  print('  non-tail       K depth at each '
        'call: ' + str(non_tail))
  print('  tail-recursive K depth at each '
        'call: ' + str(tail))
  print('  Step out compares against those '
        'numbers.  One of the two')
  print('  columns has nowhere for it to go.')


def main():
  opening_demo()
  breakpoint_demo()
  stepping_demo()
  tail_call_demo()
  session_demo()


if __name__ == '__main__':
  main()
