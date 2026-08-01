"""
IB_Repl -- a read-eval-print loop for the IttyBitty Lisp evaluators.

Wires the reader (IB_Reader.parse) to an evaluator so you can type Lisp
at a prompt instead of hand-writing nested Python lists:

    $ python IB_Repl.py
    lisp> (+ 1 2)
    3
    lisp> (set! a (+ 1 1))
    2
    lisp> (if (= a 2) (+ a 1) (- a 1))
    3
    lisp> quit

By default it drives IB_Lisp1 (Chapter 1).  To use a later chapter's
evaluator, change the import below to IB_Lisp2, 3, 5, or 7 -- every machine
in the book exports the same lEval(expr, env) / global_env / lisp_str interface,
so nothing else changes.  The parser is written once, in Chapter 8, and every
machine is fed by it.

Leave with 'quit', 'exit', or end-of-input (Ctrl-D on Unix, Ctrl-Z Enter on
Windows).

Run with: python IB_Repl.py
"""

from IB_Reader import parse
from IB_Lisp1  import lEval, global_env, lisp_str   # <- swap for IB_Lisp2 / 3 / 5 / 7


def repl():
  while True:
    try:
      source = input('lisp> ')
    except (EOFError, KeyboardInterrupt):
      print()
      break
    if source.strip() in ('quit', 'exit'):
      break
    if not source.strip():
      continue
    try:
      print(lisp_str(lEval(parse(source), global_env)))
    except Exception as err:
      # A bad expression prints an error and returns to the prompt,
      # rather than crashing the loop.
      print(f'error: {err}')


if __name__ == '__main__':
  repl()
