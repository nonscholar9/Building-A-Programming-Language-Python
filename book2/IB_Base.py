"""
IB_Base - Book One's machine, ready to be built on.

This is the machine Book Two builds on, and it is not a new one.  It is
IB_Lisp5, the CEK machine from Chapter 5, plus one thing: `call/cc`, from the
second interlude.  Line for line it is IB_Lisp5b_callcc.py under a name that
says what it is used for rather than which chapter made it.

Nothing here is new, and nothing here is yours to add.  Everything else the
machine does it could already do by the end of Chapter 5: `cond`, `and`, `or`
and `not`, the list primitives, rest parameters, and `apply`.  If you read the
second interlude you already have this file; keep using yours.  The two loops,
the registers, and the frames are exactly as Chapter 5 left them.

That is the point, and it is worth being plain about it.  Book Two never changes
this machine.  It sits underneath, and everything we build from here runs in
front of it -- which is what it means to call it a *backend*.

Run with: python IB_Base.py
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
# call/cc support
# ---------------------------------------------------------------------------
# A captured continuation is nothing but a saved copy of the K stack.  Because
# K is a stack we own, "reify the continuation" = "copy the stack", and
# "resume the continuation" = "make that stack be K again".

class Continuation:
  """A reified continuation: a snapshot of the K stack, taken at the moment
    call/cc ran.  Invoking it like a one-argument function discards whatever K
    is current and reinstates this saved one, so control jumps back to wherever
    the continuation was captured, carrying the supplied value."""
  def __init__( self, stack ):
    self.stack = stack

class _CallCC:
  """The call/cc primitive is a sentinel, not an ordinary Python callable,
    because capturing the continuation needs the machine's K register -- which
    a plain primitive never sees.  The APPLY loop recognizes this object and
    does the capture itself."""

CALLCC = _CallCC()

class _Apply:
  """apply is also a value, not a special form: it must open a scope and run a
    body, which no primitive can do, so the evaluator recognizes it at the call
    site (see the splice in FRAME_ARG), the same way it recognizes call/cc."""

applyFn = _Apply()

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
#              a closure (VAL_CLOSURE, params, body, captured_env);
#              a Continuation (a saved K stack); the CALLCC sentinel.

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
        K.append( (FRAME_IF, thenExpr,
                       elseExpr, E) )
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
        names = [ pair[0]
                  for pair in bindingPairs ]
        inits = [ pair[1]
                  for pair in bindingPairs ]
        C = ( [ ['lambda', names] + list(body) ]
              + inits )
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
          K.append( (FRAME_ARG, doneList,
                         todoList[1:], env) )
          C = todoList[0]
          E = env
          break
        # operator + all operands evaluated -> apply doneList[0] to doneList[1:]
        fn, *args = doneList

        while fn is applyFn:             # apply is a value: splice its final
          # list into the argument positions and call the real function,
          # here at the call site, just as call/cc reaches in below.
          # Both sides read the OLD args; do not split this in two.
          fn, args = ( args[0],
                       list( args[1:-1] )
                       + list( args[-1] ) )

        if fn is CALLCC:               # (call/cc f): reify K, then call f with it
          # This application's own frame was already popped above, so K
          # right now *is* the continuation of the whole (call/cc f)
          # expression.  Snapshot it, and redirect to "call f on it".
          cont = Continuation( list(K) )
          fn   = args[0]
          args = [cont]

        if isinstance( fn, Continuation ):   # invoking a captured continuation
          K = list( fn.stack )       # discard current K, reinstate the saved one
          V = args[0]                # the value handed to the continuation...
          continue                   # ...flows straight into the restored K

        if callable( fn ):             # primitive: compute the value, flow it on
          V = fn( args )
          continue                   # stay in APPLY
        _, params, body, clo_env = fn  # closure: bind params, run the body
        initialBindings = bind_params(
            params, args )
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
    'call/cc':                       CALLCC,                    # the star of this file
    'call-with-current-continuation': CALLCC,                  # its full Scheme name
    'apply':                         applyFn,                     # a value, spliced at the call site
}
global_env = Environment( bindings=globalBindings )

# ---------------------------------------------------------------------------
# Helpers and demo
# ---------------------------------------------------------------------------

def lisp_str( val ):
  if isinstance( val, list ):
    return '(' + ' '.join( lisp_str(x) for x in val ) + ')'
  if isinstance( val, Continuation ):      # a reified continuation
    return '#<continuation>'
  if val is CALLCC:
    return '#<primitive call/cc>'
  if val is applyFn:
    return '#<primitive apply>'
  if isinstance( val, tuple ):             # a closure: (VAL_CLOSURE, params, body, env)
    return '#<procedure (' + ' '.join( val[1] ) + ')>'
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
  print( '--- everything Chapter 5 had, unchanged ---\n' )
  run( '(+ (- 10 7) 2)' )                          # 5
  run( '(let ((a 3) (b 4)) (+ (* a a) (* b b)))' )       # 25
  run( "'(a b c)" )                      # (a b c)

  print( "--- Chapter 1's list primitives ---\n" )
  run( "(car '(a b c))" )             # a
  run( "(cdr '(a b c))" )             # (b c)
  run( "(cons 1 '(2 3))" )                  # (1 2 3)
  run( '(list 1 2 3)' )                               # (1 2 3)
  run( "(null? '())" )                        # #t

  print( "--- Chapter 1's cond, and, or, not ---\n" )
  run( "(set! sign (lambda (n) (cond ((= n 0) 'zero) ((< n 0) 'negative) (else 'positive))))" )
  run( '(sign 0)' )                                     # zero
  run( '(sign -5)' )                                    # negative
  run( '(sign 5)' )                                     # positive

  run( '(and 1 2 3)' )                                # 3   (last value)
  run( '(and 1 #f 3)' )                           # #f
  run( '(or #f 2 3)' )                            # 2   (first true value)
  run( '(or #f #f)' )                          # #f
  run( '(not #f)' )                                 # #t

  # Short-circuiting is the reason these cannot be primitives: if `and` ran
  # like `+`, this would print 99 before deciding anything.
  run( '(and #f (print 99))' )                  # #f, and 99 never prints

  print( "--- Chapter 2's rest parameters ---\n" )
  run( '(set! tally (lambda (first . rest) (list first rest)))' )
  run( '(tally 1)' )                                    # (1 ())
  run( '(tally 1 2 3)' )                              # (1 (2 3))

  print( '--- the second interlude: call/cc ---\n' )
  run( '(+ 1 (call/cc (lambda (k) (+ 10 (k 5)))))' )   # 6

  # An escape, which is what mini-Python's `return` will need.
  run( '(set! first-negative (lambda (xs) (call/cc (lambda (return) (begin (set! walk (lambda (ys) (cond ((null? ys) #f) ((< (car ys) 0) (return (car ys))) (else (walk (cdr ys)))))) (walk xs))))))' )
  run( "(first-negative '(3 7 -2 9))" )    # -2
  run( "(first-negative '(3 7 9))" )        # #f

  print( '--- and the machine is still the machine ---\n' )
  run( '(set! countdown (lambda (n) (if (= n 0) 0 (countdown (- n 1)))))' )
  run( '(countdown 100000)' )                           # 0, in constant K


if __name__ == '__main__':
  main()
