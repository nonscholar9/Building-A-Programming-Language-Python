"""
IB_Addresser - the first pass that makes the program FASTER rather than
safer, and the first one that has to earn its keep with a number.

Every pass so far has either changed what the program says (the expander) or
refused to let it through (the checker).  This one leaves the meaning exactly
as it found it and changes only how the machine will go looking for things.

The machine finds a variable by name.  `lookup` starts at the innermost scope,
asks whether the name is there, and walks outward until it is.  That is a
SEARCH, and the work it does depends on how deeply nested the variable is and
how many names sit beside it.  But for a local variable, everything that search
is about to discover is already visible in the source:

    (lambda (x) (lambda (y) (+ x y)))
                                ^
                                x is one frame out, slot 0.  Always.

So we work it out once, here, instead of every time the machine runs that line.
A variable that resolves to a lambda's parameter becomes an `Addressed` symbol
carrying (depth, index).  A variable that does not becomes nothing at all: it
stays a plain string, because it is a global, and the global scope is a place
anyone can add a name to while the program runs.  You can address what you can
see the shape of, and a parameter list has a shape.

    (depth, index)      depth = frames to walk outward, 0 = innermost
                        index = slot within that frame

WHERE IT SITS.  After the expander, before the checker:

    read -> expand -> ADDRESS -> analyze -> machine

Before the checker on purpose.  This pass rewrites the tree, and a pass that
rewrites the tree should have something standing between it and the machine.
The checker validates what actually runs, which is this pass's output, not the
program as it was written.

An `Addressed` symbol is a `str` subclass, so every pass downstream keeps
working without knowing this one exists: it hashes, compares and prints as its
own name.  The address rides along as an attribute for the machine to find.

Run with: python IB_Addresser.py
"""

import IB_Core

from IB_Core     import lisp_str
from IB_Expander import expand
from IB_Analyzer import analyze, LispError
from IB_Reader   import parse


# ---------------------------------------------------------------------------
# The addressed symbol
# ---------------------------------------------------------------------------
#
# Subclassing str is what keeps this pass invisible to everything downstream.
# The checker asks `isinstance( head, str )`, uses names as dict keys, and
# compares them against 'quote' and 'lambda'.  All of that still works, because
# an Addressed IS a str with the same characters.  It just knows one more thing
# about itself.

class Addressed(str):
  """A local variable that knows where it lives."""

  def __new__(cls, name, depth, index):
    sym = super().__new__(cls, name)
    sym.depth = depth
    sym.index = index
    return sym

  def __repr__(self):
    return f'{str(self)}@{self.depth}.{self.index}'


class Global(str):
  """A variable the pass could not place, which is a positive result.

    The only way to bind a name in this language is a lambda parameter.  So a
    name with no enclosing parameter of that name is not merely unplaced, it is
    GLOBAL, and nothing later can shadow it.  Saying so is worth more than it
    looks: the machine's walk outward is longest for exactly these names, and
    this is what lets it skip the walk entirely.
    """
  depth = None                                 # never at a depth: it is global

  def __repr__(self):
    return f'{str(self)}@global'


# ---------------------------------------------------------------------------
# Frame layout
# ---------------------------------------------------------------------------

def frame_names(params):
  """The slots a parameter list declares, in order.

    A dotted list (first . rest) declares the named parameters and then the
    rest parameter, which holds whatever is left over as a list.  The dot marks
    the split; it is not itself a slot.  So the frame is the same size for
    every call, however many arguments arrive.
    """
  if '.' in params:
    dot = params.index('.')
    return list(params[:dot]) + [params[dot + 1]]
  return list(params)


def resolve(name, scopes):
  """Search the COMPILE-TIME scope stack, innermost first.

    This is the same walk `lookup` does at run time, done once, here, with the
    parameter lists standing in for the frames that do not exist yet.  Innermost
    first is what makes shadowing come out right: the nearest binding wins, and
    the ones further out are never reached.
    """
  for depth, names in enumerate(reversed(scopes)):
    if name in names:
      return depth, names.index(name)
  return None                                  # not lexical, so global


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

def address(form, scopes=None, mark_globals=True):
  """Label every variable with where it lives: a depth, or the global scope.

    The meaning of the program does not change; only the amount of work the
    machine has to do to find things.

    `mark_globals` is here so the two halves of the win can be measured apart.
    Turn it off and only locals are labelled, which is lexical addressing as it
    is usually described.  Leave it on and the globals are labelled too, which
    is where nearly all of the saving turns out to be.
    """
  if scopes is None:
    scopes = []

  if isinstance(form, str):                  # a variable reference
    slot = resolve(form, scopes)
    if slot is None:
      return Global(form) if mark_globals else form
    depth, index = slot
    return Addressed(form, depth, index)

  if not isinstance(form, list) or not form:
    return form                              # a number, or ()

  head = form[0]

  if head == 'quote':                          # datum is data, do not walk in
    return form

  if head == 'lambda':                         # ['lambda', params, *body]
    inner = scopes + [frame_names(form[1])]
    return ['lambda', form[1]] + [address(f, inner, mark_globals)
                                   for f in form[2:]]

  # if, set!, begin and application all just walk their parts.  set! is not a
  # special case here: its target is a variable reference like any other, and
  # addressing it is exactly what lets an assignment write straight to a slot.
  return [address(f, scopes, mark_globals) for f in form]


# ---------------------------------------------------------------------------
# What it did
# ---------------------------------------------------------------------------

def slots(form, found=None):
  """Collect every addressed variable, for showing the pass its own work."""
  if found is None:
    found = []
  if isinstance(form, Addressed):
    found.append(form)
  elif isinstance(form, list) and form and form[0] != 'quote':
    for sub in form:
      slots(sub, found)
  return found


def globals_in(form, found=None):
  """Every variable the pass could NOT address."""
  if found is None:
    found = []
  if isinstance(form, Addressed):
    pass
  elif isinstance(form, str):
    found.append(form)
  elif isinstance(form, list) and form and form[0] != 'quote':
    head = form[0]
    parts = form[2:] if head == 'lambda' else form
    for sub in parts:
      globals_in(sub, found)
  return found


# ---------------------------------------------------------------------------
# What it is worth, in scopes examined
# ---------------------------------------------------------------------------
#
# The unit is one dictionary looked in.  The searching version looks in every
# scope on the way out until it finds the name; the told versions look in one.
# It is the same count on every computer, and it is exactly what the pass
# removes, which is more than can be said for a stopwatch.

BENCH = """
(begin
  (set! fib (lambda (n)
    (if (< n 2) n (+ (fib (- n 1)) (fib (- n 2))))))
  (set! gcd (lambda (a b)
    (if (= b 0) a (gcd b (% a b)))))
  (set! adder (lambda (x) (lambda (y) (lambda (z) (+ x (+ y z))))))
  (set! total 0)
  (set! loop (lambda (i)
    (if (= i 0) 0
      (begin (set! total (+ total (((adder 1) 2) i)))
             (loop (- i 1))))))
  (list (fib 18) (gcd 1071 462) (loop 300) total))
"""


def count_scopes(form):
  """Run a program on a fresh machine, counting the dictionaries it looks in."""
  seen = {'scopes': 0}
  Env  = IB_Core.Environment
  saved = (Env.lookup, Env.lookupAtDepth, Env.lookupGlobal)

  def counted(method, scopes_per_call=None):
    def go(self, name, *rest):
      if scopes_per_call is None:            # the searching version
        env, n = self, 1
        while env and name not in env._bindings:
          env = env._outer
          n += 1
        seen['scopes'] += n
      else:
        seen['scopes'] += scopes_per_call
      return method(self, name, *rest)
    return go

  Env.lookup        = counted(saved[0])
  Env.lookupAtDepth = counted(saved[1], 1)
  Env.lookupGlobal  = counted(saved[2], 1)
  try:
    value = IB_Core.lEval(
        form, Env(bindings=IB_Core.globalBindings))
  finally:
    Env.lookup, Env.lookupAtDepth, Env.lookupGlobal = saved
  return lisp_str(value), seen['scopes']


def measure():
  core = expand(parse(BENCH))
  runs = [
      ('nothing placed',        core),
      ('locals placed',         address(core, mark_globals=False)),
      ('locals and globals',    address(core)),
]
  print('  what the machine was told   scopes examined      value')
  base = None
  for label, form in runs:
    value, scopes = count_scopes(form)
    base = scopes if base is None else base
    share = '' if scopes == base else f'  ({100.0*(base-scopes)/base:.0f}% fewer)'
    print(f'  {label:26} {scopes:>10,}{share:>14}   {value}')
  return runs


def main():
  def show(label, source):
    core = expand(source)
    out  = address(core)
    local = [repr(s) for s in slots(out)]
    print(f'  {label}')
    print(f'     addressed  {" ".join(local) if local else "(none)"}')

  print('--- what the pass works out, once, before the machine runs ---\n')
  show('(lambda (x) (lambda (y) (+ x y)))',
        ['lambda', ['x'], ['lambda', ['y'], ['+', 'x', 'y']]])
  show('(let ((a 1) (b 2)) (+ a b))',
        ['let', [['a', 1], ['b', 2]], ['+', 'a', 'b']])
  show('(lambda (first . rest) rest)',
        ['lambda', ['first', '.', 'rest'], 'rest'])
  show('(lambda (x) (lambda (x) x))            ; the inner x shadows',
        ['lambda', ['x'], ['lambda', ['x'], 'x']])
  show("(lambda (n) (set! n (+ n 1)))          ; set! writes to a slot too",
        ['lambda', ['n'], ['set!', 'n', ['+', 'n', 1]]])

  print('\n--- and what it leaves alone, because it cannot see their shape ---\n')
  prog = expand(['lambda', ['x'], ['+', 'x', 'y']])
  out  = address(prog)
  print(f'  (lambda (x) (+ x y))')
  print(f'     addressed  {" ".join(repr(s) for s in slots(out))}')
  print(f'     left free  {" ".join(globals_in(out))}')

  print('\n--- the checker still checks, and now it checks THIS ---\n')
  for label, source in [
      ('(square 5 99), addressed first',
        ['begin', ['set!', 'square', ['lambda', ['n'], ['*', 'n', 'n']]],
                  ['square', 5, 99]]),
      ('a good program, addressed first',
        ['begin', ['set!', 'square', ['lambda', ['n'], ['*', 'n', 'n']]],
                  ['square', 5]]),
]:
    try:
      analyze(address(expand(source)))
      print(f'  quiet   {label}')
    except LispError as e:
      print(f'  error   {label}:  {e}')

  print('\n--- what the placing is worth, in scopes examined ---\n')
  measure()

  print('\n--- the meaning is untouched: printing it back gives the source ---\n')
  src  = ['lambda', ['x'], ['lambda', ['y'], ['+', 'x', 'y']]]
  core = expand(src)
  print(f'  before  {lisp_str( core )}')
  print(f'  after   {lisp_str( address( core ) )}')


if __name__ == '__main__':
  main()
