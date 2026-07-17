"""
IttyBittyPythonReturn - the lowering, completed: early return via call/cc.

Chapter 13 lowered everything but a return that is not the last thing a function
does.  An early return abandons the rest of the body and leaves the function then
and there, which is a non-local exit, and the machine has no form for it -- except
the one Book One's second interlude built, call/cc, which makes the continuation
a value you can hold and jump to.

A return IS a jump to the function's own continuation.  So wrap each function
body in call/cc, which hands the body the continuation that returns to the
caller, and lower every `return e` to an invocation of it:

    def f(params):            (lambda (params)
        BODY            ->      (let (<locals>)
                                  (call/cc (lambda (ret)
                                    <BODY, return e -> (ret e)>))))

Now `return e` anywhere -- inside an if, inside a loop, however deep -- restores
that continuation with e, and the function is left at once.  A body that runs off
its end never invokes `ret`, and call/cc returns the body's own last value.

The pipeline is unchanged: python text -> parse -> lower -> expand -> lEval.

Run with: python IttyBittyPythonReturn.py
"""

import sys
sys.path.insert( 0, '.' )
from IttyBittyPythonParser import Parser
from IttyBittyExpander import expand, gensym
from IttyBittyCore import lEval, global_env, lisp_str


# ---------------------------------------------------------------------------
# The assigned-names scan (Chapter 13): a def binds the names its body assigns.
# ---------------------------------------------------------------------------

def assigned_names( body ):
    found = set()
    for stmt in body:
        _assigned_stmt( stmt, found )
    return found

def _assigned_stmt( s, found ):
    tag = s[0]
    if tag == 'assign':
        found.add( s[1] )
    elif tag == 'if':
        for st in s[2]: _assigned_stmt( st, found )
        for _, blk in s[3]:
            for st in blk: _assigned_stmt( st, found )
        if s[4]:
            for st in s[4]: _assigned_stmt( st, found )
    elif tag == 'while':
        for st in s[2]: _assigned_stmt( st, found )
    elif tag == 'def':
        found.add( s[1] )


# ---------------------------------------------------------------------------
# Lowering.  Statements carry `ret`, the current function's return continuation,
# so a return anywhere in the body knows what to jump to.
# ---------------------------------------------------------------------------

_ARITH = { '+', '-', '*', '/', '%', '<', '>', '<=', '>=' }

def lower_module( node ):
    return [ 'begin' ] + [ lower_stmt( s, None ) for s in node[1] ]

def lower_body( stmts, ret ):
    return [ lower_stmt( s, ret ) for s in stmts ]

def lower_stmt( s, ret ):
    tag = s[0]
    if tag == 'assign':
        return [ 'set!', s[1], lower_expr( s[2] ) ]
    if tag == 'expr':
        return lower_expr( s[1] )
    if tag == 'return':
        value = lower_expr( s[1] ) if s[1] is not None else '#f'
        return [ ret, value ]                 # jump to the function's continuation
    if tag == 'pass':
        return '#f'
    if tag == 'if':
        return lower_if( s, ret )
    if tag == 'while':
        return lower_while( s, ret )
    if tag == 'def':
        return lower_def( s )                 # a nested def has its own continuation
    raise ValueError( f'unknown statement {s!r}' )

def lower_def( s ):
    _, name, params, body = s
    ret     = gensym()
    locals_ = sorted( assigned_names( body ) - set( params ) )
    cc = [ 'call/cc', [ 'lambda', [ ret ] ] + lower_body( body, ret ) ]
    if locals_:
        bindings = [ [ v, '#f' ] for v in locals_ ]
        lam_body = [ [ 'let', bindings, cc ] ]
    else:
        lam_body = [ cc ]
    return [ 'set!', name, [ 'lambda', list( params ) ] + lam_body ]

def lower_if( s, ret ):
    _, test, body, elifs, orelse = s
    clauses = [ [ lower_expr( test ), [ 'begin' ] + lower_body( body, ret ) ] ]
    for etest, ebody in elifs:
        clauses.append( [ lower_expr( etest ), [ 'begin' ] + lower_body( ebody, ret ) ] )
    if orelse is not None:
        clauses.append( [ 'else', [ 'begin' ] + lower_body( orelse, ret ) ] )
    return [ 'cond' ] + clauses

def lower_while( s, ret ):
    _, test, body = s
    loop = gensym()
    helper = [ 'lambda', [],
               [ 'if', lower_expr( test ),
                 [ 'begin' ] + lower_body( body, ret ) + [ [ loop ] ],
                 '#f' ] ]
    return [ 'let', [ [ loop, '#f' ] ],
             [ 'set!', loop, helper ],
             [ loop ] ]

def lower_expr( e ):
    tag = e[0]
    if tag == 'num':
        return e[1]
    if tag == 'name':
        return e[1]
    if tag == 'call':
        return [ lower_expr( e[1] ) ] + [ lower_expr( a ) for a in e[2] ]
    if tag == 'unary':
        op, x = e[1], lower_expr( e[2] )
        if op == '-':   return [ '-', 0, x ]
        if op == '+':   return x
        if op == 'not': return [ 'not', x ]
    if tag == 'binop':
        op, l, r = e[1], lower_expr( e[2] ), lower_expr( e[3] )
        if op in _ARITH:            return [ op, l, r ]
        if op == '==':              return [ '=', l, r ]
        if op == '!=':              return [ 'not', [ '=', l, r ] ]
        if op == 'and':             return [ 'and', l, r ]
        if op == 'or':              return [ 'or', l, r ]
    raise ValueError( f'unknown expression {e!r}' )


def run_python( source ):
    ast  = Parser().parse( source )
    core = expand( lower_module( ast ) )
    return lEval( core, global_env )


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def main():
    print( '--- factorial, the Chapter 13 cliffhanger, now runs ---\n' )
    fac = ( "def factorial(n):\n"
            "    if n == 0:\n"
            "        return 1\n"          # an EARLY return
            "    return n * factorial(n - 1)\n" )
    run_python( fac )
    print( 'factorial(5) =>', lisp_str( lEval( ['factorial', 5], global_env ) ) )   # 120

    print( '\n--- an early return in the middle of a body ---\n' )
    run_python( "def clamp0(x):\n"
                "    if x < 0:\n"
                "        return 0\n"
                "    return x\n" )
    print( 'clamp0(-5) =>', lisp_str( lEval(['clamp0',-5], global_env) ),
           '  clamp0(7) =>', lisp_str( lEval(['clamp0',7], global_env) ) )

    print( '\n--- return jumping straight out of a loop ---\n' )
    run_python( "def first_ge(n, threshold):\n"
                "    i = 0\n"
                "    while i < n:\n"
                "        if i >= threshold:\n"
                "            return i\n"     # leaves the loop AND the function
                "        i = i + 1\n"
                "    return -1\n" )
    print( 'first_ge(100, 7) =>', lisp_str( lEval(['first_ge',100,7], global_env) ) )  # 7

    print( '\n--- Chapter 13 still holds: tail return + while ---\n' )
    run_python( "def gcd(a, b):\n"
                "    while b != 0:\n"
                "        t = b\n"
                "        b = a % b\n"
                "        a = t\n"
                "    return a\n" )
    print( 'gcd(48, 36) =>', lisp_str( lEval(['gcd',48,36], global_env) ) )      # 12

    print( '\n--- a while still loops in constant space, call/cc and all ---\n' )
    run_python( "def count(n):\n"
                "    i = 0\n"
                "    while i < n:\n"
                "        i = i + 1\n"
                "    return i\n" )
    print( 'count(200000) =>', lisp_str( lEval(['count',200000], global_env) ) )


if __name__ == '__main__':
    main()
