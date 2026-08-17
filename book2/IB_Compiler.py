"""
IB_Compiler - core forms in, bytecode out.

Every pass so far has handed the machine a tree.  This one hands it a list of
instructions, and that is the whole difference: the machine no longer has to
work out what kind of form it is looking at, because the answer was worked out
once, here, and written down as a number.

The pipeline this chapter completes:

    text -> parse -> expand -> ADDRESS -> COMPILE -> the VM

The two new stages are one chapter's work because they are one idea seen twice.
The addresser removes the search for a variable; the compiler removes the
search for a form.  Both replace something the machine was re-deciding on every
pass with something decided once, before it ran.

WHAT THE COMPILER KNOWS.  Only the core forms: quote, lambda, if, set!, begin,
and application.  The expander already turned everything else into these, so
there is nothing here for `let` or `cond`, and there does not need to be.

TAIL POSITION.  `tail` is threaded through exactly as it was in Chapter 6: a
value in tail position is followed by OP_RET, and a call in tail position
becomes OP_TCALL, which pushes no return address.  Tail-call optimization is a
property of the code we emit, not of the machine that runs it.

Run with: python IB_Compiler.py
"""

import sys

from IB_AST       import LBoolean, lisp_str
from IB_Reader    import parse
from IB_Expander  import expand
from IB_Addresser import address, Addressed
from IB_VM        import (OP_INT, OP_QUOTE, OP_LOCAL, OP_GLOBAL, OP_LAM,
                          OP_JUMP, OP_APP_START, OP_APPLY_ARG, OP_CALL,
                          OP_TCALL, OP_IF_START, OP_APPLY_IF, OP_RET,
                          OP_SET_LOCAL, OP_SET_GLOBAL,
                          run_vm, disassemble, GLOBALS, STEPS)


# ---------------------------------------------------------------------------
# The compiler
# ---------------------------------------------------------------------------

def compile_body(forms, out, tail):
  """A body: every form but the last is computed and discarded."""
  for f in forms[:-1]:
    compile_expr(f, out, tail=False)
  compile_expr(forms[-1], out, tail=tail)


def compile_expr(expr, out, tail):
  if isinstance(expr, Addressed):        # a local: the addresser placed it
    out.append((OP_LOCAL, expr.depth,
                expr.index))
    if tail:
      out.append((OP_RET,))

  elif isinstance(expr, str):            # a global: still looked up by name
    out.append((OP_GLOBAL, expr))
    if tail:
      out.append((OP_RET,))

  elif isinstance(expr, (int, LBoolean)):
    out.append((OP_INT, expr))
    if tail:
      out.append((OP_RET,))

  elif expr[0] == 'quote':
    out.append((OP_QUOTE, expr[1]))
    if tail:
      out.append((OP_RET,))

  elif expr[0] == 'lambda':              # ['lambda', params, *body]
    lam_idx  = len(out)                # reserve OP_LAM
    out.append(None)
    jump_idx = len(out)                # reserve the jump over the body
    out.append(None)
    body_pc  = len(out)
    _, params, *body = expr
    compile_body(body, out, tail=True)   # a body is always in tail position
    out[lam_idx]  = (OP_LAM, params,
                     body_pc)
    out[jump_idx] = (OP_JUMP, len(out))
    if tail:
      out.append((OP_RET,))

  elif expr[0] == 'if':                  # ['if', test, then, else]
    _, condExpr, thenExpr, elseExpr = expr
    if_idx = len(out)
    out.append(None)
    compile_expr(condExpr, out, tail=False)
    out.append((OP_APPLY_IF,))
    then_pc = len(out)
    compile_expr(thenExpr, out, tail=tail)
    if not tail:
      then_jump_idx = len(out)
      out.append(None)
    else_pc = len(out)
    compile_expr(elseExpr, out, tail=tail)
    if not tail:
      out[then_jump_idx] = (OP_JUMP,
                            len(out))
    out[if_idx] = (OP_IF_START, then_pc,
                   else_pc)

  elif expr[0] == 'set!':                # ['set!', name, valueExpr]
    _, name, valExpr = expr
    compile_expr(valExpr, out, tail=False)
    if isinstance(name, Addressed):
      out.append((OP_SET_LOCAL,
                  name.depth, name.index))
    else:
      out.append((OP_SET_GLOBAL, name))
    if tail:
      out.append((OP_RET,))

  elif expr[0] == 'begin':
    compile_body(expr[1:], out, tail)

  else:                                  # [fn, *args] -- an application
    out.append((OP_APP_START,))
    for sub in expr:
      compile_expr(sub, out, tail=False)
      out.append((OP_APPLY_ARG,))
    out.append((OP_TCALL,) if tail
               else (OP_CALL,))


def compile_program(core):
  """Address, then compile, one whole expression."""
  out = []
  compile_expr(address(core), out, tail=True)
  return out


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------
#
# The compiled code is appended to PROG rather than replacing it, for the
# reason Chapter 6 gave: a closure remembers the address of its own body, and
# throwing the program away between expressions would leave every closure made
# by an earlier one pointing into code that is no longer there.

PROG = []


def lEval(expr, env=None):
  """Compile one expression onto the end of the program and run it."""
  start = len(PROG)
  compile_expr(address(expr), PROG, tail=True)
  return run_vm(PROG, start, env)


def run_core(core):
  """Everything after the expander: address, compile, run."""
  return lEval(core)


def run(source):
  """The whole pipeline, for one line of source text."""
  core = expand(parse(source) if isinstance(source, str)
                else source)
  return lEval(core)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def show(source, want=None):
  before = STEPS[0]
  got    = lisp_str(run(source))
  steps  = STEPS[0] - before
  mark   = '' if want is None else ('ok   ' if got == str(want)
                                    else 'FAIL ')
  print(f'  {mark}{source}')
  print(f'       ==> {got}   [{steps} instructions]')


def main():
  print('--- what the compiler emits, and where the addresser shows ---\n')
  core = expand(parse('(let ((x 7)) (lambda (y) (+ x y)))'))
  print(f'  core   {lisp_str(core)}')
  print(f'  addressed  {lisp_str(address(core))}\n')
  disassemble(compile_program(core))

  print('\n--- the language, on the compiled machine ---\n')
  show('(+ (- 10 7) 2)', 5)
  show("(if (< 1 2) 'yes 'no)", 'yes')
  show('((lambda (x) (* x x)) 7)', 49)
  show("'(a b)", '(a b)')
  show('(let ((a 3) (b 4)) (+ (* a a) (* b b)))', 25)
  show("(cond ((< 2 1) 'no) (else 'yes))", 'yes')
  show('(and #f (print unreached))', '#f')
  show("(or #f 'fallback)", 'fallback')
  show('(begin (set! y 1) (set! y (+ y 9)) y)', 10)

  print('\n--- rest parameters and apply ---\n')
  run('(set! tally (lambda (label . nums)'
      '  (list label (apply + nums))))')
  show("(tally 'total 1 2 3)", '(total 6)')
  show("(apply + 10 20 '(1 2 3))", 36)

  print('\n--- tail calls stay flat ---\n')
  run('(set! countdown (lambda (n)'
      '  (if (= n 0) 0 (countdown (- n 1)))))')
  show('(countdown 100000)', 0)

  print('\n--- call/cc, on the VM ---\n')
  show('(call/cc (lambda (k) (+ 1 (k 42))))', 42)
  show('(+ 1 (call/cc (lambda (k) (+ 10 (k 5)))))', 6)
  show('(+ 1 (call/cc (lambda (k) 5)))', 6)
  run('(set! find (lambda (xs)'
      '  (call/cc (lambda (out)'
      '    (begin'
      '      (set! walk (lambda (ys)'
      '        (if (null? ys) 0'
      '          (if (= (car ys) 3) (out (quote found))'
      '            (walk (cdr ys))))))'
      '      (walk xs))))))')
  show("(find '(1 2 3 4))", 'found')

  print('\n--- a macro, all the way down to bytecode ---\n')
  run('(define-macro (unless test . body)'
      "  (list 'if test '#f (cons 'begin body)))")
  show('(unless (< 2 1) (+ 20 22))', 42)


if __name__ == '__main__':
  main()
