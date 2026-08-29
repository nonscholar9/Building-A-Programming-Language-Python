"""
IB_Debugger2 - Chapter 22.  The debugger, part two.

Chapter 21's debugger works.  This one is the difference between a debugger
that works and one you would use, and almost none of that difference is in
the hook.  The hook is the same nine lines it was.  What changes is that a
breakpoint stops being a name in a set and becomes a thing with a number, a
condition, a count, and a place.

Four of the sections here are one idea each:

  * A breakpoint is an object in a numbered table, so you can list it,
    disable it, or take it away without retyping it.

  * A condition is a Lisp expression evaluated in the stopped environment.
    The hook has to be off while it runs, or the debugger steps on itself.

  * An ignore count is subtraction.  Break on the hundredth call, not the
    first.

  * A place is `id(form)`.  A function that calls `+` five times has five
    call sites and only one name, so the interesting breakpoint is on the
    third `+`, not on `+`.  A form in this machine is one Python list, and
    the machine puts that very object in C, so its identity is the address
    of a point in the program.

And then the bill for that last one, which is the section readers will
remember: redefine the function and the form you keyed on is garbage.  The
breakpoint still exists, still has a number, and can never fire again.  So the
table has to notice.  prune_stale() is that, and it is nine lines.

Run with: python IB_Debugger2.py
"""

from IB_Core import (VAL_CLOSURE, global_env,
                     lisp_str)
from IB_AST import lFalse
from IB_Repl import evaluate
from IB_Break import _evaluate
from IB_Debugger import Debugger


# ---------------------------------------------------------------------------
# Finding a call site
# ---------------------------------------------------------------------------
#
# Pre-order, so the numbering is reading order: the first call to `callee` you
# would meet reading the body aloud is number 1.

def collect_calls(form, callee, found=None):
  if found is None:
    found = []
  if not isinstance(form, list):
    return found
  if form and form[0] == callee:
    found.append(form)
  for part in form:
    collect_calls(part, callee, found)
  return found


def closure_body(closure):
  """(VAL_CLOSURE, params, body, env) -> the body, or None."""
  if (isinstance(closure, tuple) and closure
      and closure[0] == VAL_CLOSURE):
    return closure[2]
  return None


# ---------------------------------------------------------------------------
# A breakpoint, which used to be a string
# ---------------------------------------------------------------------------

class Breakpoint:
  def __init__(self, number, label, head=None,
               site=None, fn_name=None,
               fn_obj=None):
    self.number = number
    self.label = label
    self.head = head        # fires on any form headed by this name
    self.site = site        # fires on this one form, by identity
    self.fn_name = fn_name  # the function that form lives in
    self.fn_obj = fn_obj    # the closure it lived in when set
    self.cond = None
    self.ignore = 0
    self.hits = 0
    self.enabled = True

  def describe(self):
    mark = ' ' if self.enabled else '-'
    line = (mark + str(self.number) + '  '
            + self.label)
    if self.cond:
      line = line + '   if ' + self.cond
    if self.ignore:
      line = (line + '   ignore '
              + str(self.ignore))
    if self.hits:
      line = (line + '   hits '
              + str(self.hits))
    return line


# ---------------------------------------------------------------------------
# The debugger
# ---------------------------------------------------------------------------

class Debugger2(Debugger):

  def __init__(self):
    Debugger.__init__(self)
    self.breaks = {}      # number -> Breakpoint
    self.sites = {}       # id(form) -> Breakpoint
    self.heads = {}       # name -> Breakpoint
    self.watches = []     # (number, source)
    self._next_number = 1
    self._next_watch = 1

  # -----------------------------------------------------------------------
  # The hook, with the same shape and a different first question
  # -----------------------------------------------------------------------

  def on_expr(self, C, E, K):
    bp = self.fired(C, E)
    if bp is not None:
      self.stop(C, E, K,
                '*** Breakpoint '
                + str(bp.number) + ': '
                + bp.label)
      return
    self.step_check(C, E, K)

  def fired(self, C, E):
    """Identity first, then name.  Then the condition, then the count."""
    if not isinstance(C, list) or not C:
      return None
    bp = self.sites.get(id(C))
    if bp is None and isinstance(C[0], str):
      bp = self.heads.get(C[0])
    if bp is None or not bp.enabled:
      return None
    if not self.condition_holds(bp, E):
      return None
    bp.hits = bp.hits + 1
    if bp.ignore > 0:
      bp.ignore = bp.ignore - 1
      return None
    return bp

  def condition_holds(self, bp, E):
    """A Lisp expression, run in the stopped environment.

      _evaluate turns the hook off first.  Without that the machine would
      call this debugger while this debugger is asking the machine a
      question, and the recursion has no bottom.
    """
    if not bp.cond:
      return True
    try:
      return _evaluate(bp.cond, E) is not lFalse
    except Exception as err:
      print('  (condition on breakpoint '
            + str(bp.number) + ' failed: '
            + str(err) + ')')
      return False

  # -----------------------------------------------------------------------
  # Setting breakpoints
  # -----------------------------------------------------------------------

  def add(self, bp):
    self.breaks[bp.number] = bp
    self._next_number = self._next_number + 1
    return bp

  def break_on_name(self, name):
    bp = Breakpoint(self._next_number, name,
                    head=name)
    self.heads[name] = bp
    return self.add(bp)

  def break_on_site(self, spec, env=None):
    """spec is fn:callee:n, one-based, in reading order."""
    env = env or global_env
    fn_name, callee, index = spec.split(':')
    index = int(index)
    closure = env.lookup(fn_name)
    body = closure_body(closure)
    if body is None:
      raise ValueError(fn_name
                       + ' is not a function')
    calls = []
    for form in body:
      collect_calls(form, callee, calls)
    if not 1 <= index <= len(calls):
      raise ValueError(
          fn_name + ' has ' + str(len(calls))
          + ' call(s) to ' + callee)
    form = calls[index - 1]
    bp = Breakpoint(self._next_number, spec,
                    site=form,
                    fn_name=fn_name,
                    fn_obj=closure)
    self.sites[id(form)] = bp
    return self.add(bp)

  def remove(self, number):
    bp = self.breaks.pop(number, None)
    if bp is None:
      return None
    if bp.head is not None:
      self.heads.pop(bp.head, None)
    if bp.site is not None:
      self.sites.pop(id(bp.site), None)
    return bp

  # -----------------------------------------------------------------------
  # The bill for keying on identity
  # -----------------------------------------------------------------------

  def prune_stale(self, env=None):
    """Drop site breakpoints whose function has been redefined.

      The form is still a perfectly good Python list.  Nothing points at it
      any more, so the machine will never put it in C, so the breakpoint can
      never fire.  A breakpoint that cannot fire is worse than none: you set
      it, you saw it in the table, and you concluded the code never ran.
    """
    env = env or global_env
    dropped = []
    for number in sorted(self.breaks):
      bp = self.breaks[number]
      if bp.site is None:
        continue
      try:
        current = env.lookup(bp.fn_name)
      except NameError:
        current = None
      if current is not bp.fn_obj:
        dropped.append(bp)
    for bp in dropped:
      self.remove(bp.number)
      print('  (stale breakpoint '
            + str(bp.number) + ' '
            + bp.label + ' removed: '
            + str(bp.fn_name)
            + ' was redefined)')
    return dropped

  # -----------------------------------------------------------------------
  # Showing where the breakpoints are
  # -----------------------------------------------------------------------

  def marked(self, form):
    return id(form) in self.sites

  def contains_mark(self, form):
    if self.marked(form):
      return True
    if not isinstance(form, list):
      return False
    for part in form:
      if self.contains_mark(part):
        return True
    return False

  def print_annotated(self, form, indent=0):
    """Print a body, opening out only the branches that hold a breakpoint."""
    pad = '  ' * indent
    if self.marked(form):
      print('>>' + pad + lisp_str(form))
      return
    if (not isinstance(form, list)
        or not self.contains_mark(form)):
      print('  ' + pad + lisp_str(form))
      return
    print('  ' + pad + '(' + lisp_str(form[0]))
    for part in form[1:]:
      self.print_annotated(part, indent + 1)
    print('  ' + pad + ')')

  def show_body(self, name, env=None):
    env = env or global_env
    body = closure_body(env.lookup(name))
    if body is None:
      print('  ' + name + ' is not a function')
      return
    for form in body:
      self.print_annotated(form)

  # -----------------------------------------------------------------------
  # Locals, scope by scope
  # -----------------------------------------------------------------------
  #
  # Chapter 2 said an environment is a stack of scopes.  This prints the
  # stack, and it is the first time in the volume the reader sees one.

  def show_locals(self, E, max_scopes=None):
    env = E
    top = E._global
    number = 0
    while env is not None and env is not top:
      if (max_scopes is not None
          and number >= max_scopes):
        return
      names = [n
               for n in sorted(env._bindings)
               if not callable(
                   env._bindings[n])]
      if names:
        print('  --- scope ' + str(number)
              + ' ---')
        for name in names:
          print('  ' + name + ': '
                + lisp_str(env._bindings[name]))
        number = number + 1
      env = env._outer
    if number == 0:
      print('  (nothing bound outside the '
            'globals)')

  # -----------------------------------------------------------------------
  # Watches you can manage
  # -----------------------------------------------------------------------

  def show_watches(self, E):
    for number, source in self.watches:
      try:
        value = lisp_str(_evaluate(source, E))
      except Exception:
        value = '<unbound here>'
      print('    watch ' + str(number) + ' '
            + source + ' = ' + value)

  # -----------------------------------------------------------------------
  # The prompt
  # -----------------------------------------------------------------------

  def commands(self, depth):
    handlers = Debugger.commands(self, depth)

    def set_break(rest):
      if not rest:
        return list_breaks(rest)
      try:
        if ':' in rest:
          bp = self.break_on_site(rest,
                                  self._env)
        else:
          bp = self.break_on_name(rest)
      except Exception as err:
        print('  ' + str(err))
        return None
      print('  breakpoint ' + str(bp.number)
            + ': ' + bp.label)
      return None

    def list_breaks(rest):
      if not self.breaks:
        print('  (no breakpoints)')
      for number in sorted(self.breaks):
        print('  '
              + self.breaks[number].describe())
      return None

    def drop_break(rest):
      bp = self.remove(int(rest))
      print('  breakpoint ' + rest
            + (' removed' if bp
               else ' not found'))
      return None

    def toggle_break(rest):
      bp = self.breaks.get(int(rest))
      if bp:
        bp.enabled = not bp.enabled
        print('  breakpoint ' + rest + ' '
              + ('on' if bp.enabled
                 else 'off'))
      return None

    def set_condition(rest):
      number, _, source = rest.partition(' ')
      bp = self.breaks.get(int(number))
      if bp:
        bp.cond = source.strip() or None
        print('  breakpoint ' + number
              + ' if ' + str(bp.cond))
      return None

    def set_ignore(rest):
      number, _, count = rest.partition(' ')
      bp = self.breaks.get(int(number))
      if bp:
        bp.ignore = int(count)
        print('  breakpoint ' + number
              + ' ignores the next ' + count)
      return None

    def show_body(rest):
      self.show_body_of(rest)
      return None

    def add_watch(rest):
      if not rest:
        for number, source in self.watches:
          print('  watch ' + str(number)
                + ' ' + source)
        return None
      self.watches.append(
          (self._next_watch, rest))
      self._next_watch = self._next_watch + 1
      return None

    def drop_watch(rest):
      number = int(rest)
      self.watches = [w for w in self.watches
                      if w[0] != number]
      print('  watch ' + rest + ' removed')
      return None

    handlers.update({
        'b': set_break, 'bl': list_breaks,
        'b-': drop_break, 'b!': toggle_break,
        'bc': set_condition, 'bi': set_ignore,
        'body': show_body, 'w': add_watch,
        'w-': drop_watch})
    return handlers

  def show_body_of(self, name):
    self.show_body(name, self._env)

  # -----------------------------------------------------------------------
  # Running
  # -----------------------------------------------------------------------

  def run(self, source, env=None, step=False,
          commands=None):
    env = env or global_env
    self.prune_stale(env)
    return Debugger.run(self, source, env=env,
                        step=step,
                        commands=commands)


# ---------------------------------------------------------------------------
# The chapter's demonstrations
# ---------------------------------------------------------------------------

PROGRAM = """(begin
  (set! area
    (lambda (w h) (+ (* w h) (+ w h))))
  (set! total
    (lambda (a b)
      (+ (area a b) (area b a))))
  (total 2 3))"""

NESTED = """(begin
  (set! outer
    (lambda (a b)
      ((lambda (c) (+ a (+ b c))) 10)))
  (outer 1 2))"""

REDEFINE = """(begin
  (set! area
    (lambda (w h) (* w h)))
  (total 2 3))"""


def table_demo():
  print('--- a breakpoint is an object in '
        'a table ---')
  dbg = Debugger2()
  dbg.break_on_name('area')
  answer = dbg.run(PROGRAM, commands=[
      'bl', 'w b', 'v', 'c',
      'v', 'bl', 'c'])
  print('==> ' + lisp_str(answer))


def ignore_demo():
  print()
  print('--- an ignore count is '
        'subtraction ---')
  dbg = Debugger2()
  bp = dbg.break_on_name('area')
  bp.ignore = 1
  answer = dbg.run(PROGRAM,
                   commands=['bl', 'c'])
  print('==> ' + lisp_str(answer))
  print('  two calls, one stop')


def condition_demo():
  print()
  print('--- a condition is a Lisp '
        'expression in the stopped E ---')
  print()
  print('  First, the trap.  A breakpoint '
        'on a NAME fires at the call,')
  print('  in the environment of the '
        'CALLER, before the callee has '
        'parameters:')
  dbg = Debugger2()
  bp = dbg.break_on_name('area')
  bp.cond = '(= w 3)'
  dbg.run(PROGRAM, commands=['c'])
  print('  fired ' + str(bp.hits)
        + ' time(s) out of 2 calls')

  print()
  print('  The same condition on a form '
        'INSIDE area, where w is bound:')
  dbg = Debugger2()
  bp = dbg.break_on_name('*')
  bp.cond = '(= w 3)'
  answer = dbg.run(PROGRAM,
                   commands=['v', 'c'])
  print('==> ' + lisp_str(answer))
  print('  fired ' + str(bp.hits)
        + ' time(s) out of 2 calls')


def site_demo():
  print()
  print('--- a place, not a name: area '
        'calls + twice ---')
  dbg = Debugger2()
  evaluate(PROGRAM)
  dbg.break_on_site('area:+:2')
  print('  the body, with the breakpoint '
        'marked:')
  dbg.show_body('area')
  answer = dbg.run('(area 2 3)', commands=[
      'v', 'bt', 'c'])
  print('==> ' + lisp_str(answer))


def stale_demo():
  print()
  print('--- and the bill for keying on '
        'identity ---')
  dbg = Debugger2()
  evaluate(PROGRAM)
  dbg.break_on_site('area:+:1')
  print('  before redefining area:')
  for number in sorted(dbg.breaks):
    print('  '
          + dbg.breaks[number].describe())
  evaluate(REDEFINE)
  print('  after (set! area ...) runs '
        'again:')
  dbg.prune_stale()
  if not dbg.breaks:
    print('  (the table is empty; the form '
          'it pointed at is unreachable)')


def scopes_demo():
  print()
  print('--- an environment is a stack of '
        'scopes, and here it is ---')
  dbg = Debugger2()
  bp = dbg.break_on_name('+')
  bp.cond = '(= c 10)'
  answer = dbg.run(NESTED,
                   commands=['v', 'c', 'v', 'c'])
  print('==> ' + lisp_str(answer))


def watches_demo():
  print()
  print('--- watches you can manage ---')
  dbg = Debugger2()
  dbg.break_on_name('square')
  answer = dbg.run(PROGRAM_SQ, commands=[
      'w a', 'w (* a 100)', 'w', 'c',
      'w- 1', 'c'])
  print('==> ' + lisp_str(answer))


def session_demo():
  print()
  print('--- the finished debugger ---')
  dbg = Debugger2()
  lEval_program()
  dbg.break_on_site('area:+:2')
  bp = dbg.breaks[1]
  bp.cond = '(= w 3)'
  answer = dbg.run('(total 2 3)', commands=[
      'bl', 'body area', 'v', 'bi 1 1',
      'c'])
  print('==> ' + lisp_str(answer))


def lEval_program():
  evaluate(PROGRAM)


PROGRAM_SQ = """(begin
  (set! square (lambda (x) (* x x)))
  (set! sum-squares
    (lambda (a b)
      (+ (square a) (square b))))
  (sum-squares 3 4))"""


def main():
  table_demo()
  ignore_demo()
  condition_demo()
  site_demo()
  stale_demo()
  scopes_demo()
  watches_demo()
  session_demo()


if __name__ == '__main__':
  main()
