"""
IB_Tracer - Chapter 20.  The tracer.

A tracer is a print inside the loop.  That really is the whole of it, and the
first section of this chapter is four lines long.

Then the chapter turns into the one that matters, which is that a print inside
the loop is unusable.  `(square 3)` is 7 steps and fits on the page.
`(fact 10)` is 149.  `(fact 100)` is 1409, and the programs you would actually
want to trace are far past that.  So the work is not producing the trace, it
is deciding what not to print.

Three filters, and between them they cover most of what anyone wants:

    only inside a named function     `only`
    only down to a given depth       `max_depth`
    only the first / last N steps    `limit`

There is a pleasant thing to notice on the way.  Since Chapter 4 this book has
shown every machine running in a column: a step number, the state, C, K and V.
That notation was drawn by hand for the page.  `Tracer(style='book')` prints
it, so from here on the book can show you a trace it did not have to typeset.

And one honest limit, which is worth a section of its own.  The hook is a
single call at the top of the EVAL loop, so a tracer sees every expression the
machine evaluates and none of the frames it pops.  Every step it prints says
EVAL.  The APPLY half of the book's traces needs a second hook, and whether
that is worth another call per frame is the chapter's last challenge.

Run with: python IB_Tracer.py
"""

import IB_Core as Core
from IB_Core import (FRAME_IF, FRAME_SET, FRAME_SEQ,
                     FRAME_CALL, MachineError,
                     global_env)
from IB_Printer import flat, primitive_names
from IB_Repl import evaluate


# ---------------------------------------------------------------------------
# Rendering a frame in section 4.4's notation
# ---------------------------------------------------------------------------

def frame_brief(frame, names=None):
  tag = frame[0]
  if tag == FRAME_IF:
    branches = (flat(frame[1], names) + ','
                + flat(frame[2], names))
    return '(F_IF,' + branches + ')'
  if tag == FRAME_SET:
    return '(F_SET,' + str(frame[1]) + ')'
  if tag == FRAME_SEQ:
    return '(F_SEQ,' + str(len(frame[1])) + ')'
  if tag == FRAME_CALL:
    done = '[' + ','.join(
        flat(d, names) for d in frame[1]) + ']'
    todo = '[' + ','.join(
        flat(t, names) for t in frame[2]) + ']'
    return '(F_CALL,' + done + ',' + todo + ')'
  return str(tag)


def k_brief(K, names=None):
  return ('[' + ', '.join(
      frame_brief(f, names) for f in K) + ']')


# ---------------------------------------------------------------------------
# The tracer
# ---------------------------------------------------------------------------

class Tracer:
  """The hook, with a print in it, and then three ways to print less."""

  def __init__(self, style='indent', limit=None,
               max_depth=None, only=None,
               width=48):
    self.style = style        # 'indent', 'book' or 'count'
    self.limit = limit        # stop printing after this many
    self.max_depth = max_depth
    self.only = set(only or ())
    self.width = width
    self.steps = 0
    self.printed = 0
    self.names = None
    self._inside = None       # depth we entered `only` at

  # ---- the whole tool ----------------------------------------------------

  def on_expr(self, C, E, K):
    self.steps = self.steps + 1
    if self.wanted(C, K):
      self.emit(C, K)

  # ---- deciding what not to print ----------------------------------------

  def wanted(self, C, K):
    if self.style == 'count':
      return False
    if (self.limit is not None
        and self.printed >= self.limit):
      return False
    if (self.max_depth is not None
        and len(K) > self.max_depth):
      return False
    if self.only:
      return self.in_scope(C, K)
    return True

  def in_scope(self, C, K):
    """Inside one of the named functions, and everything it calls.

      Entering is easy: C is a call to a name we were asked about.  Leaving
      is the same comparison the debugger's step out makes, on len(K).
    """
    if (isinstance(C, list) and C
        and isinstance(C[0], str)
        and C[0] in self.only):
      self._inside = len(K)
      return True
    if self._inside is None:
      return False
    if len(K) >= self._inside:
      return True          # still inside it
    self._inside = None    # the call returned
    return False

  # ---- printing ----------------------------------------------------------

  def emit(self, C, K):
    self.printed = self.printed + 1
    if self.style == 'book':
      self.emit_book(C, K)
    else:
      self.emit_indent(C, K)

  def emit_book(self, C, K):
    print('step ' + str(self.steps)
          + '   EVAL')
    print('   C  ' + flat(C, self.names))
    print('   K  ' + k_brief(K, self.names))
    print('   V  -')
    print()

  def emit_indent(self, C, K):
    pad = '  ' * min(len(K), 16)
    line = pad + flat(C, self.names)
    if len(line) > self.width:
      line = line[:self.width - 3] + '...'
    print('{:>5}  {}'.format(self.steps, line))

  # ---- running -----------------------------------------------------------

  def run(self, source, env=None):
    env = env or global_env
    self.names = primitive_names(env)
    self.steps = 0
    self.printed = 0
    self._inside = None
    Core.step_hook = self.on_expr
    try:
      return evaluate(source, env)
    except MachineError as err:
      print('*** ' + str(err))
      return None
    finally:
      Core.step_hook = None


def count_steps(source, env=None):
  """The tracer with the printing taken out, which is all a step count is."""
  tracer = Tracer(style='count')
  value = tracer.run(source, env)
  return tracer.steps, value


# ---------------------------------------------------------------------------
# The chapter's demonstrations
# ---------------------------------------------------------------------------

SETUP = """(begin
  (set! cd
    (lambda (n) (if (= n 0) 0 (cd (- n 1)))))
  (set! square (lambda (n) (* n n)))
  (set! hyp
    (lambda (a b)
      (+ (square a) (square b))))
  (set! fact
    (lambda (n)
      (if (= n 0) 1 (* n (fact (- n 1)))))))"""

SMALL = '(square 3)'
BIG = '(fact 10)'


def notation_demo():
  print('--- the notation this book has '
        'used since Chapter 4 ---')
  Tracer(style='book', limit=4).run(SMALL)


def indent_demo():
  print('--- the same run, one line a '
        'step, indented by depth ---')
  Tracer().run(SMALL)


def volume_demo():
  print()
  print('--- and the reason the rest of '
        'the chapter exists ---')
  for src in (SMALL, '(hyp 3 4)', BIG,
              '(fact 100)', '(cd 1000)'):
    steps, value = count_steps(src)
    shown = flat(value)
    if len(shown) > 12:
      shown = shown[:9] + '...'
    print('  {:<12} {:>6} steps   => {}'
          .format(src, steps, shown))


def filter_demo():
  print()
  print('--- only what happens inside '
        'square ---')
  t = Tracer(only=['square'])
  t.run('(hyp 3 4)')
  print('  printed ' + str(t.printed)
        + ' of ' + str(t.steps))

  print()
  print('--- or only the top level of '
        'the same run ---')
  t = Tracer(max_depth=1)
  t.run('(hyp 3 4)')
  print('  printed ' + str(t.printed)
        + ' of ' + str(t.steps))

  print()
  print('--- or the first 5 steps of a '
        'run far too long to read ---')
  t = Tracer(limit=5)
  t.run('(fact 10)')
  print('  printed ' + str(t.printed)
        + ' of ' + str(t.steps))


def main():
  evaluate(SETUP)
  notation_demo()
  indent_demo()
  volume_demo()
  filter_demo()


if __name__ == '__main__':
  main()
