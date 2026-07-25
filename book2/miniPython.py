"""
miniPython - the finished interpreter, everything folded in.

The whole front end, assembled onto the whole Lisp interpreter.  A program in
mini-Python passes through every stage both books built and comes out a
value:

    mini-Python:  text --parse--> mini-Python AST --lower--> Lisp AST
    Lisp:         Lisp AST --expand--> core AST --analyze--> core AST --lEval--> value

Each arrow is a piece the book built:

    parse    book2/miniPythonParser.py  (Ch 11-12, on ParserBase)
    lower    book2/miniPythonGen.py      (Ch 13-15: the assigned-names scan,
                                               while->tail recursion, return->call/cc,
                                               yield->a call/cc coroutine)
    expand   book2/IB_Expander.py        (Ch 9: let/cond/and/or -> core)
    analyze  book2/IB_Analyzer.py         (Ch 10: the checker; quiet unless the
                                                lowered program is malformed)
    lEval    book2/IB_Core.py             (Book One's CEK machine, sealed at Ch 9)

Two languages, one tower.  The lower half is the complete Lisp interpreter
(reader, expander, analyzer, CEK evaluator).  mini-Python is perched on top,
and it is really a second front end: it lowers its own surface into the Lisp the
tower already runs.  Nothing below `lower` knows the program began as something
that looked like Python, and the machine has not changed a line since Chapter 9.

Run with: python miniPython.py
"""

import sys
sys.path.insert( 0, '.' )
from miniPythonParser import Parser
from miniPythonGen    import lower_module      # the full lowering, yield and all
from IB_Expander     import expand
from IB_Analyzer     import analyze
from IB_Core         import lEval, global_env, lisp_str


def run( source ):
    """Run a whole mini-Python program through every stage of the tower."""
    tree = Parser().parse( source )       # text  -> tree
    core = expand( lower_module( tree ) ) # tree  -> Lisp -> core
    core = analyze( core )                # core  -> core, or a refusal
    return lEval( core, global_env )      # core  -> behaviour


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
    print( '--- a mini-Python program, run end to end ---\n' )
    print( 'source:' )
    print( PROGRAM )
    print( 'output:' )
    run( PROGRAM )


if __name__ == '__main__':
    main()
