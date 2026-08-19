"""
miniPython - the finished interpreter, everything folded in.

The whole front end, assembled onto the whole Lisp interpreter.  A program in
mini-Python passes through every stage both books built and comes out a
value:

    mini-Python:  text --parse--> mini-Python AST --lower--> Lisp AST
    Lisp:         Lisp AST --expand--> core AST --analyze--> core AST --lEval--> value

Each arrow is a piece the book built:

    parse    book2/miniPythonParser.py  (Ch 13-14, on ParserBase)
    lower    book2/miniPythonGen.py      (Ch 15-17: the assigned-names scan,
                                               while->tail recursion, return->call/cc,
                                               yield->a call/cc coroutine)
    expand   book2/IB_Expander.py        (Ch 9: let/cond/and/or -> core)
    analyze  book2/IB_Analyzer.py         (Ch 10: the checker; quiet unless the
                                                lowered program is malformed)
    lEval    book2/IB_Core.py             (Book One's CEK machine, Ch 4-5)

Two languages, one tower.  The lower half is the complete Lisp interpreter
(expander, analyzer, CEK evaluator).  mini-Python is perched on top,
and it is really a second front end: it lowers its own surface into the Lisp the
tower already runs.  Nothing below `lower` knows the program began as something
that looked like Python, and the machine has not changed a line since Chapter 9.

EITHER MACHINE.  Nothing above the last line cares which of Book One's last two
machines runs the core forms, so the last line is a choice.  `lEval` is the CEK
machine of Chapters 4 and 5.  `run_core` addresses the same forms, compiles them
to bytecode, and runs that on the CEK VM of Chapter 6, which is the machine
Chapters 11 and 12 build.  The program, and every stage above it, is identical
either way.

Run with: python miniPython.py          (the CEK machine)
          python miniPython.py --vm     (the CEK VM)
"""

import sys
sys.path.insert(0, '.')
from miniPythonParser import Parser
from miniPythonGen    import lower_module      # the full lowering, yield and all
from IB_Expander     import expand
from IB_Analyzer     import analyze
from IB_Core         import lEval, global_env, lisp_str
from IB_Compiler     import run_core


def run(source, backend='cek'):
  """Run a whole mini-Python program through every stage of the tower."""
  tree = Parser().parse(source)     # text -> tree
  core = expand(lower_module(tree)) # tree -> Lisp -> core
  core = analyze(core)              # core -> core, or a refusal
  if backend == 'vm':
    return run_core(core)           # core -> bytecode -> the VM
  return lEval(core, global_env)    # core -> behaviour


# ---------------------------------------------------------------------------
# A program using every feature of the language at once
# ---------------------------------------------------------------------------

PROGRAM = """
def is_prime(n):
    if n < 2:
        return 0
    i = 2
    while i * i <= n:
        if n % i == 0:
            return 0
        i = i + 1
    return 1

def primes():
    n = 2
    while 1:
        if is_prime(n) == 1:
            yield n
        n = n + 1

def fib(n):
    if n < 2:
        return n
    return fib(n - 1) + fib(n - 2)

def gcd(a, b):
    while b != 0:
        t = a % b
        a = b
        b = t
    return a

print(is_prime(97))
print(fib(20))
print(gcd(1071, 462))

g = primes()
print(next(g))
print(next(g))
print(next(g))
print(next(g))
print(next(g))
"""


def main():
  if '--vm' in sys.argv:
    backend, name = 'vm', 'the CEK VM'
  else:
    backend, name = 'cek', 'the CEK machine'
  print(f'--- mini-Python, on {name} ---')
  print()
  print('source:')
  print(PROGRAM)
  print('output:')
  run(PROGRAM, backend)


if __name__ == '__main__':
  main()
