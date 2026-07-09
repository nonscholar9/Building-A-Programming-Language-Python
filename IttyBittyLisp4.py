"""
IttyBittyLisp4 - A CEK machine Lisp evaluator.

The CEK machine is named for its three-part state:
  C - Control:      the expression currently being evaluated
  E - Environment:  the current lexical scope
  K - Kontinuation: an explicit stack of continuation frames

Unlike the looping evaluator (IttyBittyLisp3), the CEK machine never calls
lEval recursively -- not even for non-tail sub-expressions.  Instead it pushes
a continuation frame onto K that resumes when the sub-expression's value
arrives.  Non-tail depth is absorbed by K (a heap list), not the Python call
stack, so the Python stack stays flat no matter how deeply a program nests.

The machine runs as two states, written as two inner loops:

  EVAL  (top loop)    -- descend into C, pushing a frame for each sub-expression
                         that must be evaluated first, until a leaf produces a
                         value into the V register.
  APPLY (bottom loop) -- pop the top frame of K and feed it V, which either
                         finishes the program (K empty) or sets up the next C/E.

Because the value flows back in its own register V, C is *always* code -- there
is no need for the value/code discriminator the textbook one-register CEK uses.

A continuation frame is just a tagged tuple -- (FRAME_IF, ...), (FRAME_ARG, ...),
(FRAME_CALL, ...) -- dispatched on its tag in the APPLY loop.  There are no frame
classes and no `step` methods: a frame is plain data and all the behavior lives
here in the machine, the way the real interpreters (pyScheme / cppScheme2) do it.

This toy is a pure lambda calculus + if (a number is true unless it is 0) -- the
smallest setting that still has closures and control flow, so the machine itself
stands out with nothing else competing for attention.  The fuller language of
toys 1-3 (let, set!, begin, primitives, ...) would only add more frame kinds, not
change the machine's shape -- which is exactly what IttyBittyLisp5 does, putting
the full language back on this same machine.

Stack discipline: nothing recurses -- all depth, tail and non-tail alike, lives
in the explicit K stack on the heap.  A function call pushes no frame of its own
(FRAME_CALL just installs the body), so a tail call reuses the current K depth --
that is where the machine's tail-call optimization comes from.

Run with: python IttyBittyLisp4.py
"""

# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
# A number value is just a Python int; only a closure needs a tag, to carry
# its (param, body, captured-environment).
VAL_CLOSURE = 1

# Continuation frame kinds.
FRAME_IF   = 0   # waiting on a test value
FRAME_ARG  = 1   # waiting on a function value
FRAME_CALL = 2   # waiting on an argument value

# ---------------------------------------------------------------------------
# Environment: a linked chain of scopes (same class as IttyBittyLisp2/3)
# ---------------------------------------------------------------------------

class Environment:
    def __init__( self, parent=None, bindings=None ):
        self._bindings = dict(bindings or {})
        self._parent   = parent
        self._global   = parent._global if parent else self   # direct handle to the root

    def lookup( self, name ):
        scope = self
        while scope:
            if name in scope._bindings:
                return scope._bindings[name]
            scope = scope._parent
        raise NameError( f'Unbound variable: {name}' )

    def set( self, name, value ):
        # Walk to the innermost scope that already owns the name.
        scope = self
        while scope:
            if name in scope._bindings:
                scope._bindings[name] = value
                return value
            scope = scope._parent
        # Name not found anywhere -- create it in the global scope.  The _global
        # handle goes straight there, with no second walk down the chain.
        self._global._bindings[name] = value
        return value

# ---------------------------------------------------------------------------
# The CEK machine
# ---------------------------------------------------------------------------

def lEval( expr, env=None ):
    C = expr                                       # Control:      expression being evaluated
    V = None                                       # Value:        result flowing back in APPLY
    E = Environment() if env is None else env      # Environment:  lexical scope
    K = []                                         # Kontinuation: a stack of frames

    while True:

        # ----- state EVAL: descend into C, pushing frames, until a leaf -> V -----
        while True:
            if isinstance( C, int ):          # a number literal -> itself
                V = C
                break
            elif isinstance( C, str ):        # a variable -> look it up
                V = E.lookup( C )
                break
            elif C[0] == 'lambda':            # ['lambda', param, body] -> a closure
                V = ( VAL_CLOSURE, C[1], C[2], E )
                break
            elif C[0] == 'if':                # ['if', test, then, else]
                K.append( (FRAME_IF, C[2], C[3], E) )
                C = C[1]                      # evaluate the test first (keep descending)
            else:                             # [fn, arg] -- an application
                K.append( (FRAME_ARG, C[1], E) )
                C = C[0]                      # evaluate fn first (keep descending)

        # ----- state APPLY: feed V to the top frame -----
        while True:
            if not K:
                return V

            frame = K.pop()
            ftag  = frame[0]

            if ftag == FRAME_IF:              # (FRAME_IF, then, else, env)
                # V is the test value; 0 is false, everything else (incl. a closure) true.
                C = frame[2] if V == 0 else frame[1]
                E = frame[3]
                break

            elif ftag == FRAME_ARG:           # (FRAME_ARG, arg, env)
                # V is the function value; remember it, evaluate the argument next.
                K.append( (FRAME_CALL, V) )
                C = frame[1]                  # arg
                E = frame[2]                  # env
                break

            elif ftag == FRAME_CALL:          # (FRAME_CALL, closure)
                # V is the argument value; frame[1] is the closure.  Bind the
                # parameter in the closure's captured env and evaluate the body.
                # No frame is pushed here -- a tail call reuses this K depth (TCO).
                _, param, body, clo_env = frame[1]
                E = Environment( parent=clo_env, bindings={ param: V } )
                C = body
                break

        # fall through to the outer loop -- re-enter EVAL with the new C/E

# ---------------------------------------------------------------------------
# Helpers and demo
# ---------------------------------------------------------------------------

def lisp_str( val ):
    # Render an expression or a value in Lisp surface syntax.
    if isinstance( val, list ):              # an expression (code)
        return '(' + ' '.join( lisp_str(x) for x in val ) + ')'
    if isinstance( val, tuple ):             # a closure value: (VAL_CLOSURE, param, body, env)
        return '#<procedure (' + val[1] + ')>'
    return str( val )                        # a number or a symbol


def run( expr ):
    result = lEval( expr )
    print( f'>>> {lisp_str( expr )}' )
    print( f'==> {lisp_str( result )}' )
    print()


def main():
    # A literal evaluates to itself.
    run( 42 )

    # ((lambda (x) x) 7) -- identity applied to 7.
    run( [['lambda', 'x', 'x'], 7] )

    # (((lambda (x) (lambda (y) x)) 3) 9) -- a curried constant function.
    run( [[['lambda', 'x', ['lambda', 'y', 'x']], 3], 9] )

    # (if 1 100 200) -- a nonzero test takes the then branch.
    run( ['if', 1, 100, 200] )

    # (if 0 100 200) -- a zero test takes the else branch.
    run( ['if', 0, 100, 200] )

    # ((lambda (f) (f 3)) (lambda (x) x)) -- pass a function as an argument.
    run( [['lambda', 'f', ['f', 3]], ['lambda', 'x', 'x']] )


if __name__ == '__main__':
    main()
