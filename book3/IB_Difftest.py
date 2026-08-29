"""
IB_Difftest - Chapter 25.  Testing an interpreter, and what is left.

Every other tool in this book answers "what is my program doing".  This one
answers a question about the machine itself: how do you know it is right?

There is no oracle.  Nobody can hand you the correct answer for an arbitrary
program in a language you invented last week.  What you can do is find a
SECOND implementation and make the two disagree.  A disagreement is a bug in
one of them, and you will usually know which.

This volume is unusually well supplied with second opinions.  Book One built
the machine four times over and insisted, chapter after chapter, that every
version ran the same language and returned the same answers.  That claim has
been made in prose about a dozen times and never once checked in front of you.
Here it is checked.

There is a sharper target too.  Book Two took `let`, `cond`, `and` and `or`
OUT of the machine and made them rewrite rules, on the argument that a
rewrite before the machine does exactly what a branch inside it did.  That is
a testable claim, and this is the test: run `let` on Chapter 5's machine,
which has a branch for it, and on Book Three's core, which does not and must
expand it first, and compare.

And one warning that is the real lesson of the chapter.  **A differential
test can pass vacuously.**  If both machines fail on every program, they
agree perfectly and you have learned nothing.  So the tester counts how many
programs produced an actual VALUE, and a run where that number is low is a
broken tester, not a clean bill of health.  self_check() at the foot goes
further: it breaks a machine on purpose and insists the tester notices.  A
test that has never failed has not been tested.

Run with: python IB_Difftest.py
"""

import importlib
import os
import sys

HERE = os.path.dirname(
    os.path.abspath(__file__))
BOOK1 = os.path.join(HERE, '..', 'book1')


# ---------------------------------------------------------------------------
# Loading several machines into one process
# ---------------------------------------------------------------------------
#
# Each machine imports its own copy of the reader and the AST module, and
# Python caches a module by NAME.  So the shared names have to be evicted
# between loads, or the second machine quietly gets the first one's reader.
# This is the whole trick, and it is the reason a differ is usually a script
# that runs each machine in its own process instead.

SHARED = ('IB_AST', 'IB_Reader', 'ParserBase',
          'IB_Core', 'IB_Expander',
          'IB_Analyzer')


def load_machine(directory, names):
  """Import a machine and its companions, isolated from the ones already in.

    Returns a dict of the modules asked for.
  """
  saved = {}
  for module in list(sys.modules):
    if (module.startswith(SHARED)
        or module in names):
      saved[module] = sys.modules.pop(module)
  sys.path.insert(0, directory)
  loaded = {}
  try:
    for name in names:
      loaded[name] = importlib.import_module(
          name)
  finally:
    sys.path.pop(0)
    for module_name in list(sys.modules):
      if (module_name.startswith(SHARED)
          or module_name in names):
        del sys.modules[module_name]
    sys.modules.update(saved)
  return loaded


class Machine:
  """One implementation, and how to feed it.

    ONE THING HERE IS NOT DECORATION.  Each machine gets ITS OWN reader,
    taken from its own module, and not the reader this file imported.  `#f`
    is a single object that the machine compares by identity, so a `#f` made
    by one machine's IB_AST is not the `#f` another machine tests against.
    Share a reader between two machines and the shared one wins every
    comparison of a boolean, silently, and the differ reports disagreements
    that are entirely its own fault.  It cost an afternoon to find.
  """

  def __init__(self, label, directory, name,
               expands=False):
    names = ([name, 'IB_Expander'] if expands
             else [name])
    loaded = load_machine(directory, names)
    self.label = label
    self.module = loaded[name]
    self.parse = loaded[name].parse
    self.expands = expands
    self.expand = (loaded['IB_Expander'].expand
                   if expands else None)

  def answer(self, source):
    """A string: the value, or the error.  Never an exception."""
    module = self.module
    try:
      form = self.parse(source)
      if self.expand is not None:
        form = self.expand(form)
      value = module.lEval(
          form, module.global_env)
      return 'value ' + module.lisp_str(value)
    except Exception as err:
      return 'error ' + type(err).__name__


def machines():
  return [
      Machine('Ch3 tail-call looper', BOOK1,
              'IB_Lisp3'),
      Machine('Ch5 CEK machine', BOOK1,
              'IB_Lisp5'),
      Machine('Ch6 CEK VM', BOOK1, 'IB_Lisp6'),
      Machine('Ch7 memory', BOOK1, 'IB_Lisp7'),
      Machine('Book Three core', HERE,
              'IB_Core', expands=True),
  ]


# ---------------------------------------------------------------------------
# The suite
# ---------------------------------------------------------------------------
#
# Two halves.  The first uses only the forms every machine has.  The second
# uses the four forms Book Two took out, which is where the interesting
# comparison is.

CORE = [
    '(+ (- 10 7) 2)',
    '(if (< 1 2) (quote yes) (quote no))',
    '((lambda (x) (* x x)) 7)',
    '(quote (a (b c)))',
    '(begin (set! x 1) (set! x (+ x 1)) x)',
    '((lambda (f) (f (f 3)))'
    ' (lambda (n) (* n n)))',
    '(begin (set! fact (lambda (n)'
    ' (if (= n 0) 1 (* n (fact (- n 1))))))'
    ' (fact 10))',
    '(begin (set! cd (lambda (n)'
    ' (if (= n 0) 0 (cd (- n 1)))))'
    ' (cd 2000))',
]

SUGAR = [
    '(let ((a 2) (b 3)) (+ a b))',
    '(let ((a 2)) (let ((b 3)) (* a b)))',
    '(cond ((= 1 2) 10) ((= 1 1) 20)'
    ' (else 30))',
    '(cond (else 7))',
    '(and 1 2 3)',
    '(and)',
    '(and 1 #f 3)',
    '(or #f #f 7)',
    '(or)',
]


# ---------------------------------------------------------------------------
# Comparing
# ---------------------------------------------------------------------------

def compare(suite, machines_, title):
  print('--- ' + title + ' ---')
  disagreements = 0
  with_a_value = 0
  for source in suite:
    answers = [m.answer(source)
               for m in machines_]
    agreed = len(set(answers)) == 1
    if answers[0].startswith('value'):
      with_a_value = with_a_value + 1
    if not agreed:
      disagreements = disagreements + 1
      print('  DISAGREEMENT on ' + source)
      for m, a in zip(machines_, answers):
        print('    {:<22} {}'.format(
            m.label, a))
  print('  {} programs x {} machines: {} '
        'disagreement(s)'.format(
            len(suite), len(machines_),
            disagreements))
  print('  {} of {} produced a VALUE, not '
        'an error'.format(
            with_a_value, len(suite)))
  return disagreements, with_a_value


# ---------------------------------------------------------------------------
# Proving the tester can fail
# ---------------------------------------------------------------------------

def self_check(machines_):
  print()
  print('--- and now break one on purpose '
        '---')
  victim = machines_[1]
  original = victim.module.global_env.lookup('*')
  victim.module.global_env.set(
      '*', lambda args: 0)
  found, _ = compare(
      ['((lambda (x) (* x x)) 7)'],
      machines_,
      'one machine with a sabotaged *')
  victim.module.global_env.set('*', original)
  if found:
    print('  The tester noticed.  Its clean '
          'runs above mean something.')
  else:
    print('  THE TESTER DID NOT NOTICE, '
          'which makes it worthless.')
  return found


# ---------------------------------------------------------------------------
# What this volume names and does not build
# ---------------------------------------------------------------------------

LEFT_TO_DO = """
  Source locations that survive to runtime.  A field on every node holding
  the line and column of the token that began it, threaded through the
  phases.  Section 14.7 names it.  With it, every tool in this book could
  point at a line of YOUR file instead of at a Lisp form.

  A debugger for mini-Python.  The same instruments, stopped in the language
  the reader actually wrote, which is the item above and nothing else.

  A language server.  Everything here reports on a program that ran.  An
  editor wants answers about a program that does not compile yet, which
  means a front end that recovers from an error instead of stopping at it,
  and that reverses a ruling Book Two made on purpose.

  A disassembler for the VM, which Chapter 6 already sets as a challenge.
"""


def main():
  loaded = machines()
  print('Machines under test:')
  for m in loaded:
    print('  ' + m.label
          + ('   (expands first)'
             if m.expands else ''))
  print()
  compare(CORE, loaded,
          'the forms every machine has')
  print()
  compare(SUGAR, loaded,
          'the four forms Book Two took out '
          'of the machine')
  self_check(loaded)
  print()
  print('--- what this volume names and '
        'does not build ---')
  print(LEFT_TO_DO.rstrip())


if __name__ == '__main__':
  main()
