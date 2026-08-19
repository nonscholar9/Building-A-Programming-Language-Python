"""
miniPythonLower - lower the mini-Python AST onto the machine.

The last stage of the front end.  The parser produced a tree that speaks of def,
while, and return, which the machine has never heard of.  This turns that tree
into forms the machine does run.

The lowering emits SURFACE Lisp (let, cond, and, or, begin, set!, lambda), and
then hands it to Chapter 9's expander to finish into core forms.  So the pipeline
is:  python text -> parse -> lower -> expand -> lEval.  The lowering reuses the
expander rather than reimplementing let/cond/and/or.

Two things earn their keep here.  A def scans its body for the names it assigns
and binds them up front, because in Python an assignment makes a name local to
the whole body, while the machine's set! would otherwise reach out to the global.
And a while loop lowers to a helper function that calls itself in tail position,
which is a loop on this machine only because Chapter 3 made tail calls iterate.

Return is handled here only in tail position: a return becomes its value, which
is right when the return is the LAST thing the function does.  A return with code
after it (early return) is a non-local exit, and expressing one language's
non-local exit in another needs call/cc.  That is the next chapter; this file
runs every program whose returns are all in tail position, and no others.

Run with: python miniPythonLower.py
"""

import sys
sys.path.insert(0, '.')
from miniPythonParser import Parser
from IB_Expander import expand, gensym
from IB_Core import lEval, global_env, lisp_str
from IB_AST      import lFalse
from IB_Reader   import parse


# ---------------------------------------------------------------------------
# The assigned-names scan: every name a body assigns to is local to that whole
# body, so the def must bind them all up front.
# ---------------------------------------------------------------------------

def assigned_names(body):
  found = set()
  for stmt in body:
    _assigned_stmt(stmt, found)
  return found

def _assigned_stmt(s, found):
  tag = s[0]
  if tag == 'assign':
    found.add(s[1])
  elif tag == 'if':
    for st in s[2]:
      _assigned_stmt(st, found)
    for _, blk in s[3]:
      for st in blk:
        _assigned_stmt(st, found)
    if s[4]:
      for st in s[4]:
        _assigned_stmt(st, found)
  elif tag == 'while':
    for st in s[2]:
      _assigned_stmt(st, found)
  elif tag == 'def':
    # the def name is a local binding
    found.add(s[1])
    # do not descend: a nested def owns its own scope


# ---------------------------------------------------------------------------
# Lowering
# ---------------------------------------------------------------------------

_UNCHANGED = {'+', '-', '*', '%',
               '<', '>', '<=', '>='}

def lower_module(node):
  return ['begin'] + lower_body(node[1])

def lower_stmt(s):
  tag = s[0]
  if tag == 'assign':
    return ['set!', s[1], lower_expr(s[2])]
  if tag == 'expr':
    return lower_expr(s[1])
  if tag == 'return':
    if s[1] is None:
      return lFalse
    return lower_expr(s[1])
  if tag == 'pass':
    return lFalse
  if tag == 'if':
    return lower_if(s)
  if tag == 'while':
    return lower_while(s)
  if tag == 'def':
    return lower_def(s)
  raise ValueError(f'unknown statement {s!r}')

def lower_body(stmts):
  return [lower_stmt(s) for s in stmts]

def lower_def(s):
  _, name, params, body = s
  names   = assigned_names(body)
  locals_ = sorted(names - set(params))
  inner = lower_body(body)
  if locals_:
    bindings = [[v, lFalse] for v in locals_]
    lam_body = [['let', bindings] + inner]
  else:
    lam_body = inner
  fn = ['lambda', list(params)] + lam_body
  return ['set!', name, fn]

def _clause(test, block):
  return [lower_expr(test),
           ['begin'] + lower_body(block)]

def lower_if(s):
  _, test, body, elifs, orelse = s
  clauses = [_clause(test, body)]
  for etest, ebody in elifs:
    clauses.append(_clause(etest, ebody))
  if orelse is not None:
    tail = ['begin'] + lower_body(orelse)
    clauses.append(['else', tail])
  return ['cond'] + clauses

def lower_while(s):
  _, test, body = s
  loop  = gensym()
  again = (['begin'] + lower_body(body)
            + [[loop]])
  helper = ['lambda', [],
             ['if', lower_expr(test),
               again, lFalse]]
  return ['let', [[loop, lFalse]],
           ['set!', loop, helper],
           [loop]]

def lower_expr(e):
  tag = e[0]
  if tag == 'num':
    return e[1]
  if tag == 'name':
    return e[1]
  if tag == 'call':
    fn   = lower_expr(e[1])
    args = [lower_expr(a) for a in e[2]]
    return [fn] + args
  if tag == 'unary':
    op, x = e[1], lower_expr(e[2])
    if op == '-':
      return ['-', 0, x]
    if op == '+':
      return x
    if op == 'not':
      return ['not', x]
  if tag == 'binop':
    op = e[1]
    l  = lower_expr(e[2])
    r  = lower_expr(e[3])
    if op in _UNCHANGED:
      return [op, l, r]
    if op == '==':
      return ['=', l, r]
    if op == '!=':
      return ['not', ['=', l, r]]
    if op == 'and':
      return ['and', l, r]
    if op == 'or':
      return ['or', l, r]
  raise ValueError(f'unknown expression {e!r}')


def run_python(source):
  ast  = Parser().parse(source)
  core = expand(lower_module(ast))
  return lEval(core, global_env)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def show_lowering(source):
  """Print a def and the Lisp it
     lowers to."""
  tree = Parser().parse(source)
  print(source, end='')
  print('  =>',
        lisp_str(lower_def(tree[1][0])))
  print()


def main():
  print('--- what the lowering emits ---\n')
  show_lowering("def f(a):\n"
                 "    return a + 1\n")
  show_lowering("def f(a):\n"
                 "    if a < 0:\n"
                 "        return 0\n"
                 "    return a\n")
  show_lowering("def f():\n"
                 "    x = 5\n"
                 "    return x\n")

  print('--- a function with no early return: gcd (tail return + while) ---\n')
  gcd = ("def gcd(a, b):\n"
          "    while b != 0:\n"
          "        t = b\n"
          "        b = a % b\n"
          "        a = t\n"
          "    return a\n"
          "print(gcd(48, 36))\n")
  print('gcd(48, 36) =>', lisp_str(run_python(gcd)))     # expect 12

  print('\n--- while loops in constant space (TCO) ---\n')
  count = ("def count(n):\n"
            "    i = 0\n"
            "    while i < n:\n"
            "        i = i + 1\n"
            "    return i\n")
  run_python(count)
  print('count(200000) =>', lisp_str(lEval(parse('(count 200000)'), global_env)))

  print('\n--- the assigned-names scan keeps a local local ---\n')
  lEval(parse('(set! x 999)'), global_env)        # a global x
  run_python("def setx():\n    x = 5\n    return x\n")
  print('setx() =>', lisp_str(lEval(parse('(setx)'), global_env)),
         '   global x =>', lisp_str(lEval(parse('x'), global_env)), '(must be 999)')

  print('\n--- EARLY return: factorial cannot lower yet ---\n')
  fac = ("def factorial(n):\n"
          "    if n == 0:\n"
          "        return 1\n"
          "    return n * factorial(n - 1)\n")
  print('lowered =>', lisp_str(lower_def(Parser().parse(fac)[1][0])))
  print('The (cond ((= n 0) 1)) is not the last form, so its value is thrown')
  print('away: the early "return 1" does not return.  factorial(0) falls')
  print('through to (* 0 (factorial -1)) and recurses without end.')
  print('A return that is not in tail position needs call/cc -- Chapter 16.')


if __name__ == '__main__':
  main()
