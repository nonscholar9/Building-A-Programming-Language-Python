"""
IB_Lisp4 - A CEK machine Lisp evaluator.

The CEK machine is named for its three-part state:
  C - Control:      the expression currently being evaluated
  E - Environment:  the current lexical environment
  K - Kontinuation: an explicit stack of continuation frames

Unlike the tail-call looper (IB_Lisp3), the CEK machine never calls
lEval recursively -- not even for non-tail sub-expressions.  Instead it pushes
a continuation frame onto K that resumes when the sub-expression's value
arrives.  Non-tail depth is absorbed by K (a stack on the heap), not the Python call
stack, so the Python stack stays flat no matter how deeply a program nests.

The machine runs as two states, written as two inner loops:

  EVAL  (top loop)    -- descend into C, pushing a frame for each sub-expression
                         that must be evaluated first, until a leaf produces a
                         value into the V register.
  APPLY (bottom loop) -- pop the top frame of K and feed it V, which either
                         finishes the program (K empty) or sets up the next C/E.

Because the value flows back in its own register V, C is *always* code -- there
is no need for the value/code discriminator the textbook one-register CEK uses.

A continuation frame is just a tagged tuple -- (FRAME_IF, ...), (FRAME_CALL, ...)
-- dispatched on its tag in the APPLY loop.  There are no frame classes and no
`step` methods: a frame is plain data and all the behavior lives here in the
machine, the way a real interpreter would.

A call needs only ONE kind of frame, however many arguments it has.  FRAME_CALL
accumulates: it carries the values already in hand and the expressions still to
evaluate, and each time a value arrives the frame is popped, extended, and pushed
back with one less expression to go.  The operator is just the first of them, so
the function and its arguments are gathered by the same frame.

This toy is a pure lambda calculus + if (#f is the only false value) -- the
smallest setting that still has closures and control flow, so the machine itself
stands out with nothing else competing for attention.  The fuller language of
toys 1-3 (let, set!, begin, primitives, ...) would only add more frame kinds, not
change the machine's shape -- which is exactly what IB_Lisp5 does, putting
the full language back on this same machine.

Stack discipline: nothing recurses -- all depth, tail and non-tail alike, lives
in the explicit K stack on the heap.  A function call pushes no frame of its own
(FRAME_CALL just installs the body), so a tail call reuses the current K depth --
that is where the machine's tail-call optimization comes from.

Run with: python IB_Lisp4.py
"""

from IB_AST import lTrue, lFalse
from IB_Reader import parse

# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
# A number value is just a Python int; only a closure needs a tag, to carry
# its (params, body, captured-environment).
VAL_CLOSURE = 1

# Continuation frame kinds.
FRAME_IF   = 0   # waiting on a test value
FRAME_CALL = 1   # an application accumulating operator + operands

# ---------------------------------------------------------------------------
# Environment: a scope at run time, linked into a stack (same class as IB_Lisp2/3)
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
# The CEK machine
# ---------------------------------------------------------------------------

def lEval(expr, env):
  C = expr                                       # Control:      expression being evaluated
  V = None                                       # Value:        result flowing back in APPLY
  E = env                                        # Environment:  the lexical environment (caller supplies it)
  K = []                                         # Kontinuation: a stack of frames

  while True:

    # ----- Begin state EVAL -----
    while True:
      if isinstance(C, str):          # a variable -> look it up
        V = E.lookup(C)
        break
      elif not isinstance(C, list):   # a number or boolean literal -> itself
        V = C
        break
      elif C[0] == 'lambda':            # ['lambda', params, body] -> a closure
        _, params, body = C
        V = (VAL_CLOSURE, params, body, E)
        break
      elif C[0] == 'if':                # ['if', test, then, else]
        _, condExpr, thenExpr, elseExpr = C
        K.append((FRAME_IF, thenExpr,
                       elseExpr, E))
        C = condExpr                  # evaluate the test first (keep descending)
      else:                             # [fn, *args] -- an application
        fnExpr, *argExprs = C
        K.append((FRAME_CALL, [], argExprs, E))
        C = fnExpr                    # evaluate the operator first (keep descending)

    # ----- Begin state APPLY -----
    while True:
      if not K:
        return V

      frame = K.pop()
      ftag  = frame[0]

      if ftag == FRAME_IF:              # (FRAME_IF, then, else, env)
        # V is the test value; #f is the only false value, as everywhere else.
        _, thenExpr, elseExpr, env = frame
        E = env
        C = (thenExpr if V is not lFalse
             else elseExpr)
        break

      elif ftag == FRAME_CALL:          # (FRAME_CALL, doneList, todoList, env)
        # V is the newest value: the operator the first time through, then one
        # operand per visit.  Move it into doneList and look at what is left.
        _, doneList, todoList, env = frame
        doneList = doneList + [V]
        if todoList:                       # more operands to evaluate
          K.append((FRAME_CALL, doneList,
                         todoList[1:], env))
          E = env
          C = todoList[0]
          break
        # Operator and operands all in -> apply doneList[0] to doneList[1:].
        # Bind the parameters in the closure's captured env and evaluate the
        # body.  No frame is pushed here -- a tail call reuses this K depth (TCO).
        fn, *args = doneList
        _, params, body, clo_env = fn
        E = Environment(outer=clo_env,
            bindings=dict(zip(params, args)))
        C = body
        break

    # fall through to the outer loop -- re-enter EVAL with the new C/E

# ---------------------------------------------------------------------------
# Helpers and demo
# ---------------------------------------------------------------------------

def lisp_str(val):
  # Render an expression or a value in Lisp surface syntax.
  if isinstance(val, list):              # an expression (code)
    parts = ' '.join(lisp_str(x) for x in val)
    return '(' + parts + ')'
  if isinstance(val, tuple):             # a closure value: (VAL_CLOSURE, params, body, env)
    return '#<procedure (' + ' '.join(val[1]) + ')>'
  return str(val)                        # a number or a symbol


def run(source):
  expr = parse(source) if isinstance(source, str) else source   # Chapter 12 built this
  print(f'>>> {lisp_str( expr )}')
  result = lEval(expr, Environment())
  print(f'==> {lisp_str( result )}')
  print()


def main():
  # A literal evaluates to itself.
  run('42')

  # Identity applied to 7.
  run('((lambda (x) x) 7)')

  # Two parameters, two arguments: one frame gathers the function and both.
  run('((lambda (x y) (if x x y)) #f 9)')

  # A lambda that returns a lambda -- two nested calls, and the inner
  # function hands back the x it captured.
  run('(((lambda (x) (lambda (y) x)) 3) 9)')

  # A true test takes the then branch.
  run('(if #t 100 200)')

  # #f is the only false value, so this takes the else branch.
  run('(if #f 100 200)')

  # Pass a function as an argument.
  run('((lambda (f) (f 3)) (lambda (x) x))')


if __name__ == '__main__':
  main()
