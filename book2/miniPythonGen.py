"""
miniPythonGen - the lowering, with generators.

The capstone feature.  Chapter 14 made a function's `return` a jump to the
function's continuation.  A generator goes one step past that: it does not just
leave, it *pauses*, hands a value back, and is later resumed from where it
stopped.  That is a coroutine, and it needs two continuations passing control
between them: the generator's suspend point, and the consumer's resume point.

  yield v   ->   (call/cc (lambda (k) (set! resume k) (consumer v)))
  next(g)   ->   (g)                    the generator IS its own advance-thunk
  gen def   ->   a next-thunk closing over the two cells (resume, consumer)

A function whose body contains `yield` is lowered as a generator; every other
function is lowered exactly as Chapter 14 lowered it.  This is the one genuinely
hard thing in the book, and it is the strongest single trick call/cc can do for
a Python-shaped language: a function that produces an endless sequence, one value
at a time, which a return-based function cannot express.

Run with: python miniPythonGen.py
"""

import sys
sys.path.insert(0, '.')
from miniPythonParser import Parser
from IB_Expander        import expand, gensym
from IB_Core            import (lEval,
    global_env, lisp_str)
from IB_AST            import lFalse

# a value mini-Python source cannot make
_STOP = ['quote', 'stop-iteration']


# ---------------------------------------------------------------------------
# Scans over a function body
# ---------------------------------------------------------------------------

def assigned_names(body):
  found = set()
  for s in body:
    _assigned(s, found)
  return found

def _assigned(s, found):
  tag = s[0]
  if tag == 'assign':
    found.add(s[1])
  elif tag == 'if':
    for st in s[2]:
      _assigned(st, found)
    for _, blk in s[3]:
      for st in blk:
        _assigned(st, found)
    if s[4]:
      for st in s[4]:
        _assigned(st, found)
  elif tag == 'while':
    for st in s[2]:
      _assigned(st, found)
  elif tag == 'def':
    found.add(s[1])

def contains_yield(body):
  return any(_has_yield(s) for s in body)

def _has_yield(s):
  tag = s[0]
  if tag == 'yield':
    return True
  if tag == 'if':
    if any(_has_yield(x) for x in s[2]):
      return True
    for _, blk in s[3]:
      if any(_has_yield(x) for x in blk):
        return True
    if s[4] is None:
      return False
    return any(_has_yield(x) for x in s[4])
  if tag == 'while':
    return any(_has_yield(x) for x in s[2])
  # a nested def is its own generator
  return False


# ---------------------------------------------------------------------------
# Lowering.  `ctx` tells a statement how to leave the current function:
#   ('func', ret)              a return jumps to the continuation `ret`
#   ('gen', resume, consumer)  a yield suspends; a return stops the generator
# ---------------------------------------------------------------------------

_UNCHANGED = {'+', '-', '*', '%',
               '<', '>', '<=', '>='}

def lower_module(node):
  return ['begin'] + lower_body(node[1], None)

def lower_body(stmts, ctx):
  return [lower_stmt(s, ctx) for s in stmts]

def lower_stmt(s, ctx):
  tag = s[0]
  if tag == 'assign':
    return ['set!', s[1], lower_expr(s[2])]
  if tag == 'expr':
    return lower_expr(s[1])
  if tag == 'pass':
    return lFalse
  if tag == 'return':
    if ctx[0] == 'func':
      value = lFalse
      if s[1] is not None:
        value = lower_expr(s[1])
      return [ctx[1], value]
    # a return ends a generator
    return [ctx[2], _STOP]
  if tag == 'yield':
    _, resume, consumer = ctx
    k = gensym()
    return ['call/cc',
             ['lambda', [k],
               ['set!', resume, k],
               [consumer, lower_expr(s[1])]]]
  if tag == 'if':
    return lower_if(s, ctx)
  if tag == 'while':
    return lower_while(s, ctx)
  if tag == 'def':
    return lower_def(s)
  raise ValueError(f'unknown statement {s!r}')

def lower_def(s):
  _, name, params, body = s
  names   = assigned_names(body)
  locals_ = sorted(names - set(params))
  if contains_yield(body):
    return lower_generator(name, params,
                            body, locals_)

  ret = gensym()
  ctx = ('func', ret)
  cc  = ['call/cc',
          ['lambda', [ret]]
            + lower_body(body, ctx)]
  inner = [cc]
  if locals_:
    cells = [[v, lFalse] for v in locals_]
    inner = [['let', cells, cc]]
  fn = ['lambda', list(params)] + inner
  return ['set!', name, fn]

def lower_generator(name, params, body,
                     locals_):
  resume   = gensym()
  consumer = gensym()
  ig       = gensym()
  kn       = gensym()
  ctx   = ('gen', resume, consumer)
  cells = [[resume, lFalse],
            [consumer, lFalse]]
  cells += [[v, lFalse] for v in locals_]

  # and the value that says it ran off the end
  resume_body = (lower_body(body, ctx)
                  + [[consumer, _STOP]])
  resume_fn   = ['lambda', [ig]] + resume_body
  next_thunk  = ['lambda', [],
                  ['call/cc',
                    ['lambda', [kn],
                      ['set!', consumer, kn],
                      [resume, lFalse]]]]
  gen_fn = ['lambda', list(params),
             ['let', cells,
               ['set!', resume, resume_fn],
               next_thunk]]
  return ['set!', name, gen_fn]

def _clause(test, block, ctx):
  return [lower_expr(test),
           ['begin'] + lower_body(block, ctx)]

def lower_if(s, ctx):
  _, test, body, elifs, orelse = s
  clauses = [_clause(test, body, ctx)]
  for etest, ebody in elifs:
    clauses.append(_clause(etest, ebody, ctx))
  if orelse is not None:
    tail = ['begin'] + lower_body(orelse, ctx)
    clauses.append(['else', tail])
  return ['cond'] + clauses

def lower_while(s, ctx):
  _, test, body = s
  loop  = gensym()
  again = (['begin'] + lower_body(body, ctx)
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
    # next(g) advances the generator, which
    # IS its own advance-thunk
    if (e[1][0] == 'name' and e[1][1] == 'next'
         and len(e[2]) == 1):
      return [lower_expr(e[2][0])]
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


def run(source):
  tree = Parser().parse(source)
  core = expand(lower_module(tree))
  return lEval(core, global_env)


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main():
  print('--- an INFINITE generator: a return-based function cannot do this ---\n')
  run("def fibs():\n"
       "    a = 0\n"
       "    b = 1\n"
       "    while 1:\n"
       "        yield a\n"
       "        t = a + b\n"
       "        a = b\n"
       "        b = t\n"
       "g = fibs()\n"
       "print(next(g))\n"
       "print(next(g))\n"
       "print(next(g))\n"
       "print(next(g))\n"
       "print(next(g))\n"
       "print(next(g))\n"
       "print(next(g))\n")

  print('\n--- an infinite prime stream, filtered by is_prime ---\n')
  run("def is_prime(n):\n"
       "    if n < 2:\n"
       "        return 0\n"
       "    i = 2\n"
       "    while i * i <= n:\n"
       "        if n % i == 0:\n"
       "            return 0\n"
       "        i = i + 1\n"
       "    return 1\n"
       "def primes():\n"
       "    n = 2\n"
       "    while 1:\n"
       "        if is_prime(n) == 1:\n"
       "            yield n\n"
       "        n = n + 1\n"
       "p = primes()\n"
       "print(next(p))\n"
       "print(next(p))\n"
       "print(next(p))\n"
       "print(next(p))\n"
       "print(next(p))\n"
       "print(next(p))\n")

  print('\n--- a while loop pulling a stream until a condition ---\n')
  run("def fibs():\n"
       "    a = 0\n"
       "    b = 1\n"
       "    while 1:\n"
       "        yield a\n"
       "        t = a + b\n"
       "        a = b\n"
       "        b = t\n"
       "g = fibs()\n"
       "x = next(g)\n"
       "while x < 100:\n"
       "    print(x)\n"
       "    x = next(g)\n")


if __name__ == '__main__':
  main()
