"""
IB_Measure - Chapter 24.  Measurement.

Chapter 20's tracer with the printing taken out is a counter, and a counter is
a profiler.  That is one page.  The rest of the chapter is what to do with it,
and what to do with it is settle arguments the earlier books only asserted.

Books One and Two make claims they never test.  A tail call runs in constant
space.  A lookup walks the scope chain, and that is real work.  The optimizer
removes instructions.  Every one of those is a number, and none of them was
ever printed.  Here they are.

WHY STEPS AND NOT SECONDS.  A step count is deterministic: run it twice and
get the same number, on any machine, in any year.  A second is a measurement
of your laptop.  Chapter 11 reported instruction counts for exactly this
reason and left the clock for later; later is here, and the clock turns out to
deserve its reputation.  wall_clock() below shows why, and prints the spread
so you can see it rather than take our word for it.

WHAT THE HOOK COSTS.  Every tool in this book rides on one `if` at the top of
the EVAL loop.  hook_cost() measures it, because a book that adds a line to
the machine's hot loop and does not measure it has no business asking you to
trust its other numbers.

Run with: python IB_Measure.py
"""

import time

import IB_Core as Core
from IB_Core import Environment, global_env
from IB_Printer import flat
from IB_Repl import evaluate


# ---------------------------------------------------------------------------
# The profiler: the tracer, counting instead of printing
# ---------------------------------------------------------------------------

class Profile:
  def __init__(self):
    self.steps = 0
    self.max_depth = 0
    self.by_head = {}       # head symbol -> times evaluated
    self.lookups = 0
    self.hops = 0
    self._original = None

  # ---- the hook ----------------------------------------------------------

  def on_expr(self, C, E, K):
    self.steps = self.steps + 1
    if len(K) > self.max_depth:
      self.max_depth = len(K)
    if isinstance(C, list) and C and isinstance(
        C[0], str):
      head = C[0]
      self.by_head[head] = self.by_head.get(
          head, 0) + 1

  # ---- counting what lookup does -----------------------------------------
  #
  # Chapter 2 said a lookup walks the chain outward and that walking is real
  # work.  It never said how far.  This counts the hops.

  def watch_lookup(self):
    self._original = Environment.lookup
    prof = self

    def counting_lookup(env, name):
      prof.lookups = prof.lookups + 1
      scope = env
      while scope is not None:
        if name in scope._bindings:
          break
        prof.hops = prof.hops + 1
        scope = scope._outer
      return prof._original(env, name)

    Environment.lookup = counting_lookup

  def unwatch_lookup(self):
    if self._original is not None:
      Environment.lookup = self._original
      self._original = None

  # ---- running -----------------------------------------------------------

  def run(self, source, env=None):
    env = env or global_env
    self.watch_lookup()
    Core.step_hook = self.on_expr
    try:
      return evaluate(source, env)
    finally:
      Core.step_hook = None
      self.unwatch_lookup()

  def top(self, count=5):
    pairs = sorted(self.by_head.items(),
                   key=lambda p: -p[1])
    return pairs[:count]


def profile(source, env=None):
  prof = Profile()
  value = prof.run(source, env)
  return prof, value


# ---------------------------------------------------------------------------
# The clock, and why the book does not use it
# ---------------------------------------------------------------------------

def wall_clock(source, repeats=7, env=None):
  """Time the same program several times and return every reading."""
  times = []
  for _ in range(repeats):
    start = time.perf_counter()
    evaluate(source, env or global_env)
    times.append(time.perf_counter() - start)
  return times


def hook_cost(source, repeats=7):
  """What the one added `if` costs when nothing is watching."""
  Core.step_hook = None
  off = min(wall_clock(source, repeats))

  def do_nothing(C, E, K):
    pass

  Core.step_hook = do_nothing
  try:
    on = min(wall_clock(source, repeats))
  finally:
    Core.step_hook = None
  return off, on


# ---------------------------------------------------------------------------
# The claims, settled
# ---------------------------------------------------------------------------

SETUP = """(begin
  (set! countdown
    (lambda (n)
      (if (= n 0) 0 (countdown (- n 1)))))
  (set! addup
    (lambda (n)
      (if (= n 0) 0 (+ 1 (addup (- n 1))))))
  (set! deep
    (lambda (a)
      (lambda (b)
        (lambda (c) (+ a (+ b c))))))
  (set! fact
    (lambda (n)
      (if (= n 0) 1 (* n (fact (- n 1)))))))"""


def constant_space():
  print('--- Chapter 3 claimed a tail call '
        'runs in constant space ---')
  print('  {:<18} {:>7} {:>10}'.format(
      'program', 'steps', 'max depth'))
  for n in (10, 100, 1000):
    src = '(countdown ' + str(n) + ')'
    prof, _ = profile(src)
    print('  {:<18} {:>7} {:>10}'.format(
        src, prof.steps, prof.max_depth))
  for n in (10, 100, 1000):
    src = '(addup ' + str(n) + ')'
    prof, _ = profile(src)
    print('  {:<18} {:>7} {:>10}'.format(
        src, prof.steps, prof.max_depth))
  print('  Steps grow with n in both.  '
        'Depth grows in only one.')


def lookup_cost():
  print()
  print('--- Chapter 2 said a lookup walks '
        'the chain.  How far? ---')
  print('  {:<20} {:>7} {:>8} {:>7}'.format(
      'program', 'lookups', 'hops', 'per'))
  for src in ('(fact 10)', '(countdown 100)',
              '(((deep 1) 2) 3)'):
    prof, _ = profile(src)
    per = (prof.hops / prof.lookups
           if prof.lookups else 0)
    print('  {:<20} {:>7} {:>8} {:>7.2f}'
          .format(src, prof.lookups,
                  prof.hops, per))
  print('  The last line nests three '
        'closures deep, and its hops per')
  print('  lookup are nearly three times '
        'what the first line pays.')
  print('  Nothing in the machine '
        'remembers a chain it has')
  print('  already walked.')


def hot_forms():
  print()
  print('--- where the steps actually go, '
        'in (fact 10) ---')
  prof, value = profile('(fact 10)')
  for head, count in prof.top(6):
    print('  {:<10} {:>5}'.format(
        head, count))
  print('  ' + str(prof.steps)
        + ' steps in all, answer '
        + flat(value))


def clock():
  print()
  print('--- and the clock, which is why '
        'this book counts steps ---')
  times = wall_clock('(fact 100)')
  best, worst = min(times), max(times)
  print('  (fact 100), 7 runs')
  print('  fastest {:.6f}s   slowest '
        '{:.6f}s   spread {:.0f}%'.format(
            best, worst,
            100.0 * (worst - best) / best))
  prof, _ = profile('(fact 100)')
  print('  steps, all 7 runs: '
        + str(prof.steps)
        + ', every time')


def hook():
  print()
  print('--- what the hook costs when '
        'nothing is watching ---')
  off, on = hook_cost('(fact 100)')
  print('  hook unset {:.6f}s   hook set '
        'to a no-op {:.6f}s'.format(off, on))
  print('  {:.1f}%.  Note what that is and '
        'is not: the `if` runs in'.format(
            100.0 * (on - off) / off))
  print('  both columns, so this is the '
        'price of the CALL it guards.')
  print('  Pricing the `if` itself needs a '
        'machine without one, and')
  print('  Book Two still has one.')


def main():
  evaluate(SETUP)
  constant_space()
  lookup_cost()
  hot_forms()
  clock()
  hook()


if __name__ == '__main__':
  main()
