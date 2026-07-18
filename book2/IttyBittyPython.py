"""
IttyBittyPython - the finished interpreter.

The whole front end, assembled onto the machine.  A program in IttyBittyPython
goes through every stage this book built and comes out a value:

    text  --parse-->  tree  --lower-->  Lisp  --expand-->  core  --lEval-->  value

Each arrow is one of the pieces:

    parse   book2/IttyBittyPythonParser.py   (Chapters 11-12, on ParserBase)
    lower   book2/IttyBittyPythonReturn.py   (Chapters 13-14, the scan, while->TCO,
                                              return->call/cc)
    expand  book2/IttyBittyExpander.py        (Chapter 9)
    lEval   book2/IttyBittyCore.py            (Book One, sealed since Chapter 9)

Nothing below `lower` knows the program began as something that looked like
Python.  The machine is the one from Book One, unchanged, and the same expander
that finishes our Lisp finishes this.

Run with: python IttyBittyPython.py
"""

import sys
sys.path.insert( 0, '.' )
from IttyBittyPythonParser import Parser
from IttyBittyPythonReturn import lower_module
from IttyBittyExpander        import expand
from IttyBittyCore            import lEval, global_env, lisp_str


def run( source ):
    """Run a whole IttyBittyPython program.  Its `print`s happen as it runs; the
    value returned is the value of the program's last top-level statement."""
    tree = Parser().parse( source )
    core = expand( lower_module( tree ) )
    return lEval( core, global_env )


# ---------------------------------------------------------------------------
# A real program, using the whole language at once
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

def count_primes(limit):
    total = 0
    n = 2
    while n <= limit:
        if is_prime(n) == 1:
            total = total + 1
        n = n + 1
    return total

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

print(count_primes(50))
print(fib(20))
print(gcd(1071, 462))
print(is_prime(97))
"""


def main():
    print( '--- an IttyBittyPython program, run end to end ---\n' )
    print( 'source:' )
    print( PROGRAM )
    print( 'output:' )
    run( PROGRAM )


if __name__ == '__main__':
    main()
