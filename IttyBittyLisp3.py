"""
IttyBittyLisp3 - A looping Lisp evaluator with tail-call optimization (TCO).

The key idea: instead of recursing into tail positions, overwrite the
current expression and environment and loop.

This is the first part where C and E become real machine registers.  Where
IttyBittyLisp1 recursed for *every* sub-expression, here a tail position
just reassigns the registers and loops back:

  C - the Control:      the expression currently being evaluated  (was `expr`)
  E - the Environment:  the bindings in scope                     (was `env`)

K -- the continuation -- is still implicit here.  Non-tail sub-expressions
(an `if` condition, a call's arguments, non-tail body forms) are still
evaluated by a recursive lEval call, so they still ride the Python call
stack -- the stack *is* K for now.  That is why deeply *non-tail* recursion
can still overflow.  IttyBittyLisp4 promotes K to an explicit stack as well,
removing the last use of Python's call stack.

Compare with IttyBittyLisp1.py, which uses a naive recursive evaluator
and overflows Python's call stack even for tail-recursive programs.

Stack discipline: tail positions loop (the Python stack stays flat), but
non-tail sub-expressions still recurse -- so only *non-tail* depth uses the
Python call stack.  Tail recursion runs forever; deep non-tail nesting can
still overflow.

Run with: python IttyBittyLisp3.py
"""

# ---------------------------------------------------------------------------
# Environment: a linked chain of scopes
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
# Function: a closure capturing its lexical environment
# ---------------------------------------------------------------------------

class Function:
    def __init__( self, params, body, env ):
        self.params = params   # list of parameter name strings
        self.body   = body     # list of body expressions; last is the tail
        self.env    = env      # lexical environment at definition time

# ---------------------------------------------------------------------------
# The looping evaluator with TCO
# ---------------------------------------------------------------------------

def lEval( expr, env ):
    # C and E are machine registers.  A tail position overwrites them and loops
    # (TCO) instead of recursing -- no new Python frame is pushed; a non-tail
    # position recurses, riding the Python stack as the continuation K.
    C = expr   # Control:     the expression currently being evaluated
    E = env    # Environment: the bindings in scope
    
    while True:
        # ---- State = EVAL (dispatch on expression syntax) ----
        if C in ('#t', '#f'):         # boolean literals self-evaluate (they are
            return C                   # data, not identifiers -- never looked up)
        elif isinstance(C, str):      # a symbol -- look it up in the environment
            return E.lookup(C)
        elif not isinstance(C, list): # everything else evaluates to itself
            return C
        elif C[0] == 'set!':
            name, valExpr = C[1:]
            val = lEval(valExpr, E)             # rvalue: not tail, recurse
            return E.set(name, val)

        elif C[0] == 'if':
            condExpr, thenExpr, elseExpr = C[1:]
            condVal = lEval(condExpr, E)   # condition: not tail, recurse
            C = elseExpr if condVal == '#f' else thenExpr
            continue                            # tail branch: loop

        elif C[0] == 'begin':
            for subExpr in C[1:-1]:             # non-tail forms: recurse
                lEval(subExpr, E)
            C = C[-1]
            continue                            # tail: last form

        elif C[0] == 'quote':
            return C[1]

        elif C[0] == 'lambda':
            params, *body = C[1:]
            return Function(params, body, E)

        elif C[0] == 'let':
            bindingPairs, *body = C[1:]
            
            # Eval every init expr in the OUTER env E (parallel `let`, not `let*`),
            # then open a new scope that holds them all.
            initialBindings = { name: lEval(initExpr, E) for name, initExpr in bindingPairs }
            E = Environment( parent=E, bindings=initialBindings )
        
            # Execute body in the new E
            for subExpr in body[:-1]:            # non-tail body forms: recurse
                lEval(subExpr, E)
            C = body[-1]
            continue                            # tail: last body form

        else:
            fn, *args = [ lEval(elt, E) for elt in C ]   # eval operator + operands
    
            # ---- State = APPLY (invoke a procedure on evaluated args) ----
            if callable(fn):                        # primitive implemented in Python
                return fn(args)
            else:
                # user-defined function: TCO -- reassign the registers and loop.  The new
                # scope is opened on the *captured* (lexical) env, not the caller's.
                initialBindings = dict(zip(fn.params, args))
                E = Environment( parent=fn.env, bindings=initialBindings )
                
                # Execute the body in the new E
                for subExpr in fn.body[:-1]:            # non-tail body forms: recurse
                    lEval(subExpr, E)
                C = fn.body[-1]
                continue                                # tail call: loop, no stack growth

# ---------------------------------------------------------------------------
# Primitives and global environment
# ---------------------------------------------------------------------------

def lisp_print( args ):
    print( args[0] )
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
    '=':     lambda args: '#t' if args[0] == args[1] else '#f',
    '<':     lambda args: '#t' if args[0] <  args[1] else '#f',
    'print': lisp_print,
}
global_env = Environment( bindings=globalBindings )

# ---------------------------------------------------------------------------
# Helpers and demo
# ---------------------------------------------------------------------------

def lisp_str( val ):
    # Render a value (or AST node) in Lisp surface syntax, so the demo speaks
    # the language being interpreted instead of printing Python's repr.
    if isinstance( val, list ):
        return '(' + ' '.join( lisp_str( x ) for x in val ) + ')'
    if isinstance( val, Function ):
        return '#<procedure (' + ' '.join( val.params ) + ')>'
    if callable( val ):
        return '#<primitive>'
    return str( val )

def run( expr ):
    result = lEval( expr, global_env )
    print( f'>>> {lisp_str( expr )}' )    # the expression, in Lisp syntax
    print( f'==> {lisp_str( result )}' )  # its value, in Lisp syntax
    print()


def main():
    # Basic arithmetic
    run( ['+', ['-', 10, 7], 2] )

    # A side-effecting primitive.  Unlike +, -, *, =, <, the print primitive
    # reaches outside the evaluator -- and it *returns* its argument, so it
    # composes inside a larger expression.  Because run() evaluates before it
    # echoes, the raw 10 (the effect) prints above the >>> line, and 15 (the
    # returned 10, flowed on into +) is the value.
    run( ['+', ['print', 10], 5] )

    # set! and variable lookup
    run( ['set!', 'x', ['*', 6, 7]] )
    run( 'x' )

    # lambda creates a closure
    run( ['set!', 'square', ['lambda', ['n'], ['*', 'n', 'n']]] )
    run( ['square', 5] )

    # let creates a local scope
    run( ['let', [['a', 3], ['b', 4]],
          ['+', ['*', 'a', 'a'], ['*', 'b', 'b']]] )

    # Tail-recursive countdown.
    # The naive recursive evaluator in IttyBittyLisp1.py would hit Python's
    # ~1000-frame stack limit and crash.  With TCO each tail call reuses
    # the same Python frame, so 100,000 iterations need only a handful of
    # stack frames.
    run( ['set!', 'countdown',
          ['lambda', ['n'],
           ['if', ['=', 'n', 0],
            0,
            ['countdown', ['-', 'n', 1]]]]] )

    run( ['countdown', 100000] )


if __name__ == '__main__':
    main()
