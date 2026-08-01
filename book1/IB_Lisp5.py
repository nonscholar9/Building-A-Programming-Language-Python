"""
IB_Lisp5 - The CEK Machine, Complete.

Continues from IB_Lisp4, which introduced the CEK machine on pure lambda
calculus + if -- the smallest setting that still has closures and control flow,
so the machine itself (the C/E/K registers, the two-state EVAL/APPLY loop, the
continuation frames) stands out with nothing else competing for attention.

This part puts the full IB_Lisp3 language back: #t/#f with Scheme
truthiness (#f is the only false value -- 0 is true), quote, set!, begin,
multi-argument lambdas and applications, let, and primitives.  The lesson is
that doing so does NOT change the machine's shape.  The two loops and the
explicit K stack are untouched; the language just contributes more kinds of
continuation frame:

  FRAME_IF   -- wait on a test value, then pick a branch
  FRAME_SET  -- wait on a value, then assign it
  FRAME_SEQ  -- a begin / lambda-body with forms still to run
  FRAME_ARG  -- an application accumulating operator + operands

let needs no frame of its own: it desugars to a lambda application right in the
EVAL loop.  A function call pushes no frame (FRAME_ARG installs the body
directly), so a tail call reuses the current K depth -- the same tail-call
optimization #3 and #4 have, now living on the explicit stack.  (countdown
100000) at the bottom runs in constant K depth to prove it.

Run with: python IB_Lisp5.py
"""

from IB_AST import lTrue, lFalse
from IB_Reader import parse

# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
# A number or boolean value is itself; only a closure needs a tag, to carry its
# (params, body, captured-environment).
VAL_CLOSURE = 1

# Continuation frame kinds.
FRAME_IF  = 0   # waiting on a test value
FRAME_SET = 1   # waiting on a value to assign
FRAME_SEQ = 2   # a begin / body with forms still to run
FRAME_ARG = 3   # an application accumulating operator + operands
FRAME_AND = 4   # an and with operands still to run
FRAME_OR  = 5   # an or with operands still to run

# ---------------------------------------------------------------------------
# Environment: a scope at run time, linked into a stack (same class as IB_Lisp2/3/4)
# ---------------------------------------------------------------------------

class Environment:
  def __init__( self, outer=None, bindings=None ):
    self._bindings = dict(bindings or {})
    self._outer   = outer
    self._global   = outer._global if outer else self   # direct handle to the root

  def lookup( self, name ):
    env = self
    while env:
      if name in env._bindings:
        return env._bindings[name]
      env = env._outer
    raise NameError( f'Unbound variable: {name}' )

  def set( self, name, value ):
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
# Binding a call's arguments
# ---------------------------------------------------------------------------
#
# A dotted parameter list `(first . rest)` is written here as the plain list
# ['first', '.', 'rest'], so the dot is just an element to look for.  Bind the
# named parameters one to one, and gather whatever is left over into a list
# bound to the name after the dot.

def bind_params( params, args ):
  if '.' in params:
    dot   = params.index( '.' )
    named = params[:dot]
    rest  = params[dot + 1]
    bindings = dict( zip( named, args ) )
    bindings[rest] = list( args[len(named):] )
    return bindings
  return dict( zip( params, args ) )

# ---------------------------------------------------------------------------
# The CEK machine
# ---------------------------------------------------------------------------
#
# Registers:
#   C : current expression  (EVAL loop)
#   V : current value        (APPLY loop)
#   E : current environment
#   K : continuation stack (Python spells a stack as a list)
#
# Value forms: a number; a boolean (#t / #f); a primitive (a Python callable);
#              a closure (VAL_CLOSURE, params, body, captured_env).

def lEval( expr, env ):
  C = expr
  V = None
  E = env
  K = []

  while True:

    # ----- Begin state EVAL -----
    while True:
      if isinstance( C, str ):           # variable -> look it up
        V = E.lookup( C )
        break
      elif not isinstance( C, list ):    # number or boolean -> itself
        V = C
        break
      elif C[0] == 'quote':              # ['quote', datum] -> the datum, unevaluated
        V = C[1]
        break
      elif C[0] == 'lambda':             # ['lambda', params, *body] -> a closure
        _, params, *body = C
        V = ( VAL_CLOSURE, params, body, E )
        break
      elif C[0] == 'if':                 # ['if', test, then, else]
        _, condExpr, thenExpr, elseExpr = C
        K.append( (FRAME_IF, thenExpr, elseExpr, E) )
        C = condExpr                       # evaluate the test first
      elif C[0] == 'set!':               # ['set!', name, valueExpr]
        _, name, valExpr = C
        K.append( (FRAME_SET, name, E) )
        C = valExpr                       # evaluate the value first
      elif C[0] == 'begin':              # ['begin', *forms]
        forms = list( C[1:] )
        if len(forms) > 1:
          K.append( (FRAME_SEQ, forms[1:], E) )
        C = forms[0]
      elif C[0] == 'let':                # ['let', ((name init)...), *body]
        # Desugar to ((lambda (name...) body...) init...) and re-dispatch.
        _, bindingPairs, *body = C
        names = [ pair[0] for pair in bindingPairs ]
        inits = [ pair[1] for pair in bindingPairs ]
        C = [ ['lambda', names] + list(body) ] + inits
      elif C[0] == 'cond':               # ['cond', (test result)...]
        # Really a chain of ifs, so say so: peel one clause and re-dispatch.
        clauses = list( C[1:] )
        if not clauses:
          V = lFalse
          break
        test, result = clauses[0]
        if test == 'else':
          C = result
        else:
          C = [ 'if', test, result,
               ['cond'] + clauses[1:] ]
      elif C[0] == 'and':                # ['and', *forms] -- short-circuits
        forms = list( C[1:] )
        if not forms:
          V = lTrue                  # (and) with no forms is true
          break
        K.append( (FRAME_AND, forms[1:], E) )
        C = forms[0]
      elif C[0] == 'or':                 # ['or', *forms] -- short-circuits
        forms = list( C[1:] )
        if not forms:
          V = lFalse                 # (or) with no forms is false
          break
        K.append( (FRAME_OR, forms[1:], E) )
        C = forms[0]
      else:                              # [fn, *args] -- an application
        fnExpr, *argExprs = C
        K.append( (FRAME_ARG, [], argExprs, E) )
        C = fnExpr                       # evaluate the operator first

    # ----- Begin state APPLY -----
    while True:
      if not K:
        return V

      frame = K.pop()
      ftag  = frame[0]

      if ftag == FRAME_IF:               # (FRAME_IF, then, else, env)
        _, thenExpr, elseExpr, env = frame
        C = thenExpr if V is not lFalse else elseExpr   # #f is the only false
        E = env
        break

      elif ftag == FRAME_SET:            # (FRAME_SET, name, env)
        _, name, env = frame
        env.set( name, V )    # V is set!'s result; it flows on
        continue                       # stay in APPLY

      elif ftag == FRAME_SEQ:            # (FRAME_SEQ, remaining_forms, env)
        _, forms, env = frame               # the previous form's value V is discarded
        E = env
        if len(forms) > 1:
          K.append( (FRAME_SEQ, forms[1:], E) )
        C = forms[0]
        break

      elif ftag == FRAME_ARG:            # (FRAME_ARG, doneList, todoList, env)
        _, doneList, todoList, env = frame
        doneList = doneList + [V]
        if todoList:                       # more operands to evaluate
          K.append( (FRAME_ARG, doneList, todoList[1:],
                     env) )
          C = todoList[0]
          E = env
          break
        # operator + all operands evaluated -> apply doneList[0] to doneList[1:]
        fn, *args = doneList

        # apply is a value: splice its final list into the argument
        # positions and call the real function, here at the call site.
        # The loop lets (apply apply ...) resolve.
        while fn is applyFn:
          # Both sides read the OLD args; do not split this in two.
          fn, args = args[0], list( args[1:-1] ) + list( args[-1] )

        if callable( fn ):             # primitive: compute the value, flow it on
          V = fn( args )
          continue                   # stay in APPLY
        _, params, body, clo_env = fn  # closure: bind params, run the body
        initialBindings = bind_params( params, args )
        E = Environment( outer=clo_env,
                        bindings=initialBindings )
        if len(body) > 1:
          K.append( (FRAME_SEQ, body[1:], E) )
        C = body[0]
        break

      elif ftag == FRAME_AND:            # (FRAME_AND, remaining_forms, env)
        if V is lFalse:                # short-circuit: the #f flows on
          continue
        _, forms, env = frame
        if not forms:                  # V is the last operand's value
          continue
        E = env
        K.append( (FRAME_AND, forms[1:], E) )
        C = forms[0]
        break

      elif ftag == FRAME_OR:             # (FRAME_OR, remaining_forms, env)
        if V is not lFalse:            # short-circuit: the true value flows on
          continue
        _, forms, env = frame
        if not forms:                  # V is #f
          continue
        E = env
        K.append( (FRAME_OR, forms[1:], E) )
        C = forms[0]
        break

    # fall through to the outer loop -- re-enter EVAL with the new C/E


# ---------------------------------------------------------------------------
# Primitives and global environment
# ---------------------------------------------------------------------------

def lisp_print( args ):
  print( lisp_str( args[0] ) )   # our printer, not Python's: a list shows as (a b)
  return args[0]       # returned, so print composes inside a larger expression

def lisp_mul( args ):    # variadic product; (*) is 1, the multiplicative identity
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
    '+':     lambda args: sum( args ),                          # variadic; (+) is 0
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
    'list':  lambda args: list( args ),
    'null?': lambda args: lTrue if args[0] == [] else lFalse,

    # apply, above, is bound to the sentinel the evaluator watches for.
    'apply': applyFn,
}
global_env = Environment( bindings=globalBindings )

# ---------------------------------------------------------------------------
# Helpers and demo
# ---------------------------------------------------------------------------

def lisp_str( val ):
  if isinstance( val, list ):
    return '(' + ' '.join( lisp_str(x) for x in val ) + ')'
  if isinstance( val, tuple ):             # a closure: (VAL_CLOSURE, params, body, env)
    return '#<procedure (' + ' '.join( val[1] ) + ')>'
  if val is applyFn:
    return '#<primitive apply>'
  if callable( val ):
    return '#<primitive>'
  return str( val )


def run( source ):
  expr = parse( source ) if isinstance( source, str ) else source   # Chapter 8 built this
  print( '>>> ' + lisp_str( expr ) )
  result = lEval( expr, global_env )
  print( '==> ' + lisp_str( result ) )
  print()


def main():
  run( '(+ (- 10 7) 2)' )                      # 5

  # A side-effecting primitive.  Unlike +, -, *, =, <, the print primitive
  # reaches outside the evaluator -- and it *returns* its argument, so it
  # composes inside a larger expression.  run() echoes the form first, so the
  # raw 10 (the effect) prints between the >>> line and the value, and 15 (the
  # returned 10, flowed on into +) is the value.
  run( '(+ (print 10) 5)' )                     # prints 10, ==> 15

  run( '(set! x (* 6 7))' )                  # 42
  run( 'x' )                                          # 42

  run( '(set! square (lambda (n) (* n n)))' )
  run( '(square 5)' )                                # 25

  run( '(let ((a 3) (b 4)) (+ (* a a) (* b b)))' )    # 25

  run( '(begin (set! y 1) (set! y (+ y 9)) y)' )   # 10

  run( '(if 0 100 200)' )                          # 100  (0 is TRUE in Scheme)
  run( "'(a b c)" )                   # (a b c)

  # Tail-recursive countdown: TCO keeps K bounded, so 100,000 iterations run
  # without growing the continuation stack.
  run( '(set! countdown (lambda (n) (if (= n 0) 0 (countdown (- n 1)))))' )
  run( '(countdown 100000)' )                        # 0

  # Chapter 1's forms, now on the machine.
  run( "(car '(a b c))" )          # a
  run( "(cons 1 '(2 3))" )               # (1 2 3)
  run( "(cond ((< 2 1) 'no) (else 'yes))" )         # yes
  run( '(and #f (print unreached))' )      # #f, and nothing prints
  run( "(or #f 'fallback)" )        # fallback

  # Chapter 2's: a rest parameter, and apply spreading a list back out.
  run( '(set! tally (lambda (label . nums) (list label (apply + nums))))' )
  run( "(tally 'total)" )                # (total 0)
  run( "(tally 'total 1 2 3)" )       # (total 6)
  run( "(apply + 10 20 '(1 2 3))" ) # 36

  # A tail apply is still a tail call: K stays bounded here too.
  run( '(set! countdown2 (lambda (n . rest) (cond ((= n 0) 0) (else (apply countdown2 (list (- n 1)))))))' )
  run( '(countdown2 100000)' )                       # 0


if __name__ == '__main__':
  main()
