"""
IttyBittyLisp2 - A recursive Lisp evaluator with closures.

Extends IttyBittyLisp1.py (Part 1) with:
  - Environment   : a linked chain of scopes for lexical binding
  - Function : a closure that captures its defining environment
  - let   : local variable binding
  - lambda: first-class functions (closures)

This is a *recursive* evaluator -- every call in tail position pushes a new
Python stack frame.  It will overflow Python's ~1000-frame limit for deeply
recursive Lisp programs.  See IttyBittyLisp3.py for the looping version that
avoids this with tail-call optimization (TCO).

Stack discipline: like Part 1, every call -- tail and non-tail alike --
recurses, so the Python call stack holds the entire evaluation and overflows
even for simple tail recursion.  Closures and scoping change *what* is
evaluated, not *how* the stack is used.

Run with: python IttyBittyLisp2.py
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
        self.params: list[str]   = params
        self.body:   list        = body    # last expression is in tail position
        self.env:    Environment = env     # captured at definition -- this is what makes it a closure

# ---------------------------------------------------------------------------
# The recursive evaluator
# ---------------------------------------------------------------------------

def lEval( expr, env ):

    # ---- State = EVAL (dispatch on expression syntax) ----
    if expr in ('#t', '#f'):           # boolean literals evaluate to themselves (they are
        return expr                    # data, not identifiers -- never looked up)
    elif isinstance(expr, str):        # a symbol
        return env.lookup(expr)
    elif not isinstance(expr, list):   # everything else evaluates to itself
        return expr
    elif expr[0] == 'set!':
        name, valExpr = expr[1:]
        val = lEval(valExpr, env)
        return env.set(name, val)

    elif expr[0] == 'if':
        condExpr, thenExpr, elseExpr = expr[1:]
        condVal = lEval(condExpr, env)
        return lEval(elseExpr if condVal == '#f' else thenExpr, env)

    elif expr[0] == 'begin':
        for subExpr in expr[1:-1]:     # non-tail forms: evaluated for effect
            lEval(subExpr, env)
        return lEval(expr[-1], env)    # tail form: its value is the result

    elif expr[0] == 'quote':
        return expr[1]

    elif expr[0] == 'lambda':
        params, *body = expr[1:]
        return Function(params, body, env)

    elif expr[0] == 'let':
        bindingPairs, *body = expr[1:]
        # Each init is evaluated in the OUTER env -- that is what makes this let, not let*.
        initialBindings = { name: lEval(initExpr, env) for name, initExpr in bindingPairs }
        new_env = Environment( parent=env, bindings=initialBindings )
        
        for subExpr in body[:-1]:             # non-tail body forms
            lEval(subExpr, new_env)
        return lEval(body[-1], new_env)       # tail body form

    else:
        fn, *args = [ lEval(elt, env) for elt in expr ]   # eval operator + operands

        # ---- State = APPLY (invoke a procedure on evaluated args) ----
        if callable(fn):                   # primitive implemented in Python
            return fn(args)
        else:
            # user-defined function: evaluate its body in a fresh local scope chained
            # off the *captured* (lexical) environment, not the caller's.
            initialBindings = dict(zip(fn.params, args))
            new_env = Environment(parent=fn.env, bindings=initialBindings)
            
            for subExpr in fn.body[:-1]:       # non-tail body forms
                lEval(subExpr, new_env)
            return lEval(fn.body[-1], new_env)   # tail body form

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
    print( f'>>> {lisp_str( expr )}' )
    print( f'==> {lisp_str( result )}' )
    print()


def main():
    # Basic arithmetic (same as Part 1)
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

    # Higher-order function: make-adder returns a closure
    run( ['set!', 'make-adder',
          ['lambda', ['n'],
           ['lambda', ['x'], ['+', 'n', 'x']]]] )
    run( ['set!', 'add5', ['make-adder', 5]] )
    run( ['add5', 3] )

    # let creates a local scope
    run( ['let', [['a', 3], ['b', 4]],
          ['+', ['*', 'a', 'a'], ['*', 'b', 'b']]] )

    # Recursive factorial.
    # NOTE: each call pushes a Python stack frame.  This works for moderate n
    # but will crash with RecursionError for very large n (no TCO).
    run( ['set!', 'factorial',
          ['lambda', ['n'],
           ['if', ['=', 'n', 0],
            1,
            ['*', 'n', ['factorial', ['-', 'n', 1]]]]]] )
    run( ['factorial', 10] )

    # quote
    run( ['quote', ['a', 'b', 'c']] )


if __name__ == '__main__':
    main()
