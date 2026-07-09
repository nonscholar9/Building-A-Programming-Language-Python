"""
IttyBittyRepl -- a read-eval-print loop for the IttyBitty Lisp evaluators.

Wires the parser (IttyBittyParser.parse) to an evaluator so you can type Lisp
at a prompt instead of hand-writing nested Python lists:

    $ python IttyBittyRepl.py
    lisp> (+ 1 2)
    3
    lisp> (set! a (+ 1 1))
    2
    lisp> (if (= a 2) (+ a 1) (- a 1))
    3
    lisp> quit

By default it drives IttyBittyLisp1 (Chapter 1).  To use a later chapter's
evaluator, change the import below to IttyBittyLisp2, 3, or 5 -- they share the
same lEval(expr, env) / global_env / lisp_str interface, so nothing else changes.

Leave with 'quit', 'exit', or end-of-input (Ctrl-D on Unix, Ctrl-Z Enter on
Windows).

Run with: python IttyBittyRepl.py
"""

from IttyBittyParser import parse
from IttyBittyLisp1  import lEval, global_env, lisp_str   # <- swap for IttyBittyLisp2 / 3 / 5


def repl():
    while True:
        try:
            source = input( 'lisp> ' )
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if source.strip() in ( 'quit', 'exit' ):
            break
        if not source.strip():
            continue
        try:
            print( lisp_str( lEval( parse( source ), global_env ) ) )
        except Exception as err:
            # A bad expression prints an error and returns to the prompt,
            # rather than crashing the loop.
            print( f'error: {err}' )


if __name__ == '__main__':
    repl()
