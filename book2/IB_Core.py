"""
IB_Core - the machine, finished.

This is where Chapter 9 leaves the evaluator, and it is the last time the
evaluator changes.  From Chapter 10 on, every example in this book begins with

    from IB_Core import lEval, global_env, lisp_str

and never opens this file again.  That import is the whole argument of Book Two
written as one line: everything we build from here runs *in front of* the
machine, and a backend is something you use without opening.

What is in here is Chapter 5's CEK machine, plus the Book One challenges the
introduction handed over, minus the four forms Chapter 9 took out.  `let`,
`cond`, `and`, and `or` are gone, along with two frame kinds, because they are
rewrite rules now and a rule needs no room in the machine.  A program that has
been through the expander contains none of them.

The core forms that remain are all the machine knows: quote, lambda, if, set!,
begin, and application.

Two halves, and they are not equally settled:

  * The machine itself (Environment, bind_params, lEval, the frames) is FINAL.
    Nothing later in this book touches it.

  * The primitives below it are NOT frozen.  Adding a primitive is not a change
    to the evaluator, it is a change to what happens to be bound in the global
    environment when it starts, and later chapters may well add one.

Run with: python IB_Core.py   (a short check that the machine is alive)
"""

from IB_AST import lTrue, lFalse, lisp_str
from IB_Reader import parse

# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
VAL_CLOSURE = 1

# Continuation frame kinds.
FRAME_IF  = 0   # waiting on a test value
FRAME_SET = 1   # waiting on a value to assign
FRAME_SEQ = 2   # a begin / body with forms still to run
FRAME_ARG = 3   # an application accumulating operator + operands


# ---------------------------------------------------------------------------
# call/cc support (Book One's second interlude, unchanged)
# ---------------------------------------------------------------------------

class Continuation:
  """A reified continuation: a snapshot of the K stack."""
  def __init__( self, stack ):
    self.stack = stack
  def __repr__( self ):
    return '#<continuation>'

class _CallCC:
  """A sentinel, not a plain callable: capturing the continuation needs the
    machine's K register, which an ordinary primitive never sees."""
  def __repr__( self ):
    return '#<primitive call/cc>'

CALLCC = _CallCC()

class _Apply:
  """Also a sentinel: apply must open a scope and run a body, which no ordinary
    primitive can do, so the evaluator recognizes it at the call site."""
  def __repr__( self ):
    return '#<primitive apply>'

applyFn = _Apply()


# ---------------------------------------------------------------------------
# Environment: a scope at run time, linked into a stack
# ---------------------------------------------------------------------------

class Environment:
  def __init__( self, outer=None, bindings=None ):
    # Note: this COPIES the bindings it is given.  Handing more primitives
    # to an environment that already exists means calling .set() on it.
    self._bindings = dict(bindings or {})
    self._outer   = outer
    self._global   = outer._global if outer else self

  def lookup( self, name ):
    env = self
    while env:
      if name in env._bindings:
        return env._bindings[name]
      env = env._outer
    raise NameError( f'Unbound variable: {name}' )

  def set( self, name, value ):
    env = self
    while env:
      if name in env._bindings:
        env._bindings[name] = value
        return value
      env = env._outer
    self._global._bindings[name] = value
    return value


# ---------------------------------------------------------------------------
# Binding a call's arguments  (Book One, Chapter 2 challenge: rest parameters)
# ---------------------------------------------------------------------------

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
# Registers:  C (expression), V (value), E (environment), K (frame stack).
#
# Value forms: a number; a boolean (#t / #f); a list; a primitive (a Python callable);
#              a closure (VAL_CLOSURE, params, body, captured_env);
#              a Continuation; the CALLCC sentinel.
#
# Note what a plain Python string means here: a VARIABLE.  That is why this
# language has no string literals, and why adding them would be a change to the
# machine rather than an addition to it.

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
      elif C[0] == 'quote':              # ['quote', datum] -> the datum
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
        C = condExpr
      elif C[0] == 'set!':               # ['set!', name, valueExpr]
        _, name, valExpr = C
        K.append( (FRAME_SET, name, E) )
        C = valExpr
      elif C[0] == 'begin':              # ['begin', *forms]
        forms = list( C[1:] )
        if len(forms) > 1:
          K.append( (FRAME_SEQ, forms[1:], E) )
        C = forms[0]
      else:                              # [fn, *args] -- an application
        fnExpr, *argExprs = C
        K.append( (FRAME_ARG, [], argExprs, E) )
        C = fnExpr

    # ----- Begin state APPLY -----
    while True:
      if not K:
        return V

      frame = K.pop()
      ftag  = frame[0]

      if ftag == FRAME_IF:               # (FRAME_IF, then, else, env)
        _, thenExpr, elseExpr, env = frame
        C = (thenExpr if V is not lFalse
             else elseExpr)
        E = env
        break

      elif ftag == FRAME_SET:            # (FRAME_SET, name, env)
        _, name, env = frame
        env.set( name, V )
        continue

      elif ftag == FRAME_SEQ:            # (FRAME_SEQ, remaining_forms, env)
        _, forms, env = frame
        E = env
        if len(forms) > 1:
          K.append( (FRAME_SEQ, forms[1:], E) )
        C = forms[0]
        break

      elif ftag == FRAME_ARG:            # (FRAME_ARG, doneList, todoList, env)
        _, doneList, todoList, env = frame
        doneList = doneList + [V]
        if todoList:
          K.append( (FRAME_ARG, doneList, todoList[1:],
                     env) )
          C = todoList[0]
          E = env
          break
        fn, *args = doneList

        while fn is applyFn:             # apply is a value: splice its final
          # list into the argument positions and call the real function,
          # here at the call site, just as call/cc reaches in below.
          # Both sides read the OLD args; do not split this in two.
          fn, args = ( args[0],
                       list( args[1:-1] )
                       + list( args[-1] ) )

        if fn is CALLCC:               # (call/cc f): reify K, then call f with it
          cont = Continuation( list(K) )
          fn   = args[0]
          args = [cont]

        if isinstance( fn, Continuation ):   # invoking a captured continuation
          K = list( fn.stack )
          V = args[0]
          continue

        if callable( fn ):             # primitive
          V = fn( args )
          continue
        _, params, body, clo_env = fn  # closure
        E = Environment( outer=clo_env, bindings=bind_params( params, args ) )
        if len(body) > 1:
          K.append( (FRAME_SEQ, body[1:], E) )
        C = body[0]
        break


# ---------------------------------------------------------------------------
# Primitives and global environment
# ---------------------------------------------------------------------------
#
# Everything above this line is finished.  Everything below it is a list of
# names that happen to be bound when the machine starts, and a later chapter
# that needs one more is welcome to add it.

def lisp_print( args ):
  print( lisp_str( args[0] ) )   # our printer, not Python's: a list shows as (a b)
  return args[0]

def lisp_mul( args ):
  result = 1
  for x in args:
    result *= x
  return result

def lisp_bool( b ):
  return lTrue if b else lFalse

globalBindings = {
    '+':     lambda args: sum( args ),
    '-':     lambda args: args[0] - args[1],
    '*':     lisp_mul,
    '%':     lambda args: args[0] % args[1],
    '=':     lambda args: lisp_bool( args[0] == args[1] ),
    '<':     lambda args: lisp_bool( args[0] <  args[1] ),
    '>':     lambda args: lisp_bool( args[0] >  args[1] ),
    '<=':    lambda args: lisp_bool( args[0] <= args[1] ),
    '>=':    lambda args: lisp_bool( args[0] >= args[1] ),
    'print': lisp_print,

    'car':   lambda args: args[0][0],
    'cdr':   lambda args: args[0][1:],
    'cons':  lambda args: [args[0]] + args[1],
    'list':  lambda args: list( args ),
    'null?': lambda args: lisp_bool( args[0] == [] ),

    'not':   lambda args: lisp_bool( args[0] is lFalse ),

    'call/cc':                        CALLCC,
    'call-with-current-continuation': CALLCC,
    'apply':                          applyFn,   # a value, spliced at the call site
}
global_env = Environment( bindings=globalBindings )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------
# The value printer lisp_str is imported from IB_AST.py (top of file):
# one renderer shared by every stage of the pipeline, and Core is just one of
# its callers.  Continuation and the two sentinels above describe themselves
# through __repr__, so the shared printer needs no special case for them.


# ---------------------------------------------------------------------------
# A check that the machine is alive
# ---------------------------------------------------------------------------
#
# Core forms only.  Anything with a `let` or a `cond` in it belongs to the
# expander now, and will not run here.

def main():
  checks = [
      ( '(+ (- 10 7) 2)',              5 ),
      ( "(if (< 1 2) 'yes 'no)",       'yes' ),
      ( '((lambda (x) (* x x)) 7)',    49 ),
      ( "'(a b)",                      '(a b)' ),
  ]
  for source, want in checks:
    expr = parse( source )
    got = lisp_str( lEval( expr, global_env ) )
    print( f'{"ok " if got == str(want) else "FAIL"} {lisp_str(expr)}  ==>  {got}' )

  # Tail calls still loop, and call/cc still escapes.
  lEval( parse( '(set! countdown (lambda (n) (if (= n 0) 0 (countdown (- n 1)))))' ),
         global_env )
  got = lEval( parse( '(countdown 100000)' ), global_env )
  print( f'{"ok " if got == 0 else "FAIL"} (countdown 100000)  ==>  {got}   [constant K]' )

  got = lEval( parse( '(call/cc (lambda (k) (+ 1 (k 42))))' ), global_env )
  print( f'{"ok " if got == 42 else "FAIL"} (call/cc (lambda (k) (+ 1 (k 42))))  ==>  {got}' )


if __name__ == '__main__':
  main()
