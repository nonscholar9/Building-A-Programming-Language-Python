"""
IB_Lisp2 - A recursive Lisp evaluator with closures.

Extends IB_Lisp1.py (Part 1) with:
  - Environment   : a scope at run time, linked into a stack
  - Function : a closure that captures its defining environment
  - let   : local variable binding
  - lambda: first-class functions (closures)

This is a *recursive* evaluator -- every call in tail position pushes a new
Python stack frame.  It will overflow Python's ~1000-frame limit for deeply
recursive Lisp programs.  See IB_Lisp3.py for the looping version that
avoids this with tail-call optimization (TCO).

Stack discipline: like Part 1, every call -- tail and non-tail alike --
recurses, so the Python call stack holds the entire evaluation and overflows
even for simple tail recursion.  Closures and scoping change *what* is
evaluated, not *how* the stack is used.

Run with: python IB_Lisp2.py
"""

from IB_AST import lTrue, lFalse
from IB_Reader import parse

# ---------------------------------------------------------------------------
# Environment: a scope at run time, linked into a stack
# ---------------------------------------------------------------------------

class Environment:
  def __init__(self, outer=None, bindings=None):
    self._bindings = dict(bindings or {})
    self._outer   = outer
    self._global   = outer._global if outer else self   # direct handle to the root

  def lookup(self, name):
    env = self
    while env:
      if name in env._bindings:
        return env._bindings[name]
      env = env._outer
    raise NameError(f'Unbound variable: {name}')

  def set(self, name, value):
    # Walk to the innermost environment that already owns the name.
    env = self
    while env:
      if name in env._bindings:
        env._bindings[name] = value
        return value
      env = env._outer
    # Name not found anywhere -- create it in the global environment.  The _global
    # handle goes straight there, with no second walk down the stack.
    self._global._bindings[name] = value
    return value

# ---------------------------------------------------------------------------
# Function: a closure capturing its lexical environment
# ---------------------------------------------------------------------------

class Function:
  def __init__(self, params, body, definingEnv):
    self.params = params   # list of parameter name strings
    self.body   = body     # last expression is in tail position
    self.definingEnv = definingEnv   # this is what makes it a closure

# ---------------------------------------------------------------------------
# Binding a call's arguments
# ---------------------------------------------------------------------------
#
# A dotted parameter list `(first . rest)` is written here as the plain list
# ['first', '.', 'rest'], so the dot is just an element to look for.  Bind the
# named parameters one to one, and gather whatever is left over into a list
# bound to the name after the dot.

def bind_params(params, args):
  if '.' in params:
    dot   = params.index('.')
    named = params[:dot]
    rest  = params[dot + 1]
    bindings = dict(zip(named, args))
    bindings[rest] = list(args[len(named):])
    return bindings
  return dict(zip(params, args))

# ---------------------------------------------------------------------------
# The recursive evaluator
# ---------------------------------------------------------------------------

def lEval(expr, env):

  # ----- Begin state EVAL -----
  if isinstance(expr, str):          # a symbol -> look it up
    return env.lookup(expr)
  elif not isinstance(expr, list):   # a number or boolean -> itself
    return expr
  elif expr[0] == 'set!':
    _, name, valExpr = expr
    val = lEval(valExpr, env)
    return env.set(name, val)

  elif expr[0] == 'if':
    _, condExpr, thenExpr, elseExpr = expr
    condVal = lEval(condExpr, env)
    return lEval(
        elseExpr if condVal is lFalse
        else thenExpr,
        env)

  elif expr[0] == 'cond':
    # Really a chain of ifs, so say so: peel one clause and re-evaluate the
    # rest.  `else` is the clause whose test always holds.
    clauses = expr[1:]
    if not clauses:
      return lFalse
    test, result = clauses[0]
    if test == 'else':
      return lEval(result, env)
    return lEval(
        ['if', test, result,
         ['cond'] + list(clauses[1:])],
        env)

  elif expr[0] == 'and':             # short-circuits: stops at the first #f
    val = lTrue                    # (and) with no forms is true
    for subExpr in expr[1:]:
      val = lEval(subExpr, env)
      if val is lFalse:
        return lFalse
    return val                     # the last operand's value, not #t

  elif expr[0] == 'or':              # short-circuits: stops at the first true
    for subExpr in expr[1:]:
      val = lEval(subExpr, env)
      if val is not lFalse:
        return val             # the true value itself, not #t
    return lFalse                  # (or) with no forms is false

  elif expr[0] == 'begin':
    _, *forms = expr
    for subExpr in forms[:-1]:     # non-tail forms: evaluated for effect
      lEval(subExpr, env)
    return lEval(forms[-1], env)   # tail form: its value is the result

  elif expr[0] == 'quote':
    return expr[1]

  elif expr[0] == 'lambda':
    _, params, *body = expr
    return Function(params, body, env)

  elif expr[0] == 'let':
    _, bindingPairs, *body = expr
    # Each init is evaluated in the OUTER env -- that is what makes this let, not let*.
    initialBindings = {
        name: lEval(initExpr, env)
        for name, initExpr in bindingPairs}
    local_env = Environment(
        outer=env, bindings=initialBindings)
        
    for subExpr in body[:-1]:             # non-tail body forms
      lEval(subExpr, local_env)
    return lEval(body[-1], local_env)       # tail body form

  else:
    # eval operator + operands
    fn, *args = [lEval(elt, env)
                 for elt in expr]

    # apply is a value, not a special form: (apply g x ... lst) is a call of
    # g on x ... plus the elements of lst.  Splice it here, at the call site;
    # a primitive could not, because it has to open a scope and run g's body.
    # The loop lets (apply apply ...) resolve.
    while fn is applyFn:
      # Both sides read the OLD args; do not split this in two.
      fn, args = (args[0],
          args[1:-1] + list(args[-1]))

    # ----- Begin state APPLY -----
    if callable(fn):                   # primitive implemented in Python
      return fn(args)
    else:
      # user-defined function: evaluate its body in a fresh local environment stacked
      # off the *captured* (lexical) environment, not the caller's.
      initialBindings = bind_params(
          fn.params, args)
      local_env = Environment(
          outer=fn.definingEnv,
          bindings=initialBindings)

      for subExpr in fn.body[:-1]:       # non-tail body forms
        lEval(subExpr, local_env)
      return lEval(fn.body[-1], local_env)   # tail body form

# ---------------------------------------------------------------------------
# Primitives and global environment
# ---------------------------------------------------------------------------

def lisp_print(args):
  print(lisp_str(args[0]))   # our printer, not Python's: a list shows as (a b)
  return args[0]       # returned, so print composes inside a larger expression

def lisp_mul(args):    # variadic product; (*) is 1, the multiplicative identity
  result = 1
  for x in args:
    result *= x
  return result

# apply is a value the evaluator recognizes at the call site, not a special form
# and not an ordinary primitive: it must open a scope and run a body, which a
# Python primitive cannot do.
class _Apply:
  pass

applyFn = _Apply()

globalBindings = {
    '+':     lambda args: sum(args),                          # variadic; (+) is 0
    '-':     lambda args: args[0] - args[1],
    '*':     lisp_mul,                                          # variadic; (*) is 1
    '%':     lambda args: args[0] % args[1],
    '=':     lambda args: lTrue if args[0] == args[1] else lFalse,
    '<':     lambda args: lTrue if args[0] <  args[1] else lFalse,
    '>':     lambda args: lTrue if args[0] >  args[1] else lFalse,
    '<=':    lambda args: lTrue if args[0] <= args[1] else lFalse,
    '>=':    lambda args: lTrue if args[0] >= args[1] else lFalse,
    'print': lisp_print,

    # `not` computes from an already-evaluated argument, so it is an ordinary
    # primitive.  `and` and `or` cannot be: they must skip evaluating an
    # operand, which only a special form can do.
    'not':   lambda args: lTrue if args[0] is lFalse else lFalse,

    # The list primitives.  A Lisp list is a Python list, so each is one line.
    'car':   lambda args: args[0][0],
    'cdr':   lambda args: args[0][1:],
    'cons':  lambda args: [args[0]] + args[1],
    'list':  lambda args: list(args),
    'null?': lambda args: lTrue if args[0] == [] else lFalse,

    # apply, above, is bound to the sentinel the evaluator watches for.
    'apply': applyFn,
}
global_env = Environment(
    bindings=globalBindings)


# ---------------------------------------------------------------------------
# Helpers and demo
# ---------------------------------------------------------------------------

def lisp_str(val):
  # Render a value (or AST node) in Lisp surface syntax, so the demo speaks
  # the language being interpreted instead of printing Python's repr.
  if isinstance(val, list):
    parts = ' '.join(lisp_str(x) for x in val)
    return '(' + parts + ')'
  if isinstance(val, Function):
    parts = ' '.join(val.params)
    return '#<procedure (' + parts + ')>'
  if val is applyFn:
    return '#<primitive apply>'
  if callable(val):
    return '#<primitive>'
  return str(val)


def run(source):
  expr = parse(source) if isinstance(source, str) else source   # Chapter 12 built this
  print(f'>>> {lisp_str( expr )}')
  result = lEval(expr, global_env)
  print(f'==> {lisp_str( result )}')
  print()


def main():
  # Basic arithmetic (same as Part 1)
  run('(+ (- 10 7) 2)')

  # A side-effecting primitive.  Unlike +, -, *, =, <, the print primitive
  # reaches outside the evaluator -- and it *returns* its argument, so it
  # composes inside a larger expression.  run() echoes the form first, so the
  # raw 10 (the effect) prints between the >>> line and the value, and 15 (the
  # returned 10, flowed on into +) is the value.
  run('(+ (print 10) 5)')

  # set! and variable lookup
  run('(set! x (* 6 7))')
  run('x')

  # lambda creates a closure
  run('(set! square (lambda (n) (* n n)))')
  run('(square 5)')

  # Higher-order function: make-adder returns a closure
  run('(set! make-adder (lambda (n) (lambda (x) (+ n x))))')
  run('(set! add5 (make-adder 5))')
  run('(add5 3)')

  # let creates a local scope
  run('(let ((a 3) (b 4)) (+ (* a a) (* b b)))')

  # Recursive factorial.
  # NOTE: each call pushes a Python stack frame.  This works for moderate n
  # but will crash with RecursionError for very large n (no TCO).
  run('(set! factorial (lambda (n) (if (= n 0) 1 (* n (factorial (- n 1))))))')
  run('(factorial 10)')

  # quote
  run("'(a b c)")

  # Rest parameters: a dotted parameter list gathers the leftover arguments
  # into a list, so one function serves callers of any arity.
  run('(set! tally (lambda (label . nums) (list label (apply + nums))))')
  run("(tally 'total)")
  run("(tally 'total 1 2 3)")

  # apply spreads a list into a call's argument positions.  Leading arguments
  # come first, then the elements of the final list.
  run("(apply + '(1 2 3))")
  run("(apply + 10 20 '(1 2 3))")

  # The pair together: a wrapper that forwards whatever it was handed, without
  # knowing how many arguments that is.
  run("(set! logged (lambda (f . args) (begin (print 'calling) (apply f args))))")
  run('(logged square 7)')
  run('(logged + 1 2 3)')


if __name__ == '__main__':
  main()
