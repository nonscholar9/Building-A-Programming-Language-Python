"""
IttyBittyLisp1 - The simplest possible Lisp evaluator.

The AST is hand-written as nested Python lists -- no parser.  The environment
is a plain Python dict -- no scoping, no closures.  Every recursive call pushes
a new Python stack frame, so deeply recursive Lisp programs will overflow
Python's ~1000-frame limit.

This file is the starting point for a series that progressively adds features:

  IttyBittyLisp1.py   -- bare evaluator, flat dict environment  (this file)
  IttyBittyLisp2.py   -- adds closures, let, lexical scoping
  IttyBittyLisp3.py   -- adds tail-call optimization (TCO) via looping
  IttyBittyLisp4.py   -- the CEK machine (explicit K), on pure lambda calculus
  IttyBittyLisp5.py   -- the CEK machine with the full language restored
  IttyBittyLisp6.py   -- compiles the machine to a flat bytecode VM
  IttyBittyParser.py  -- adds a source-string parser to complete the pipeline

Throughout the series, evaluation is driven by three quantities:

  C - the Control:      the expression currently being evaluated
  E - the Environment:  the bindings in scope
  K - the Kontinuation: what to do with the result once it is known

In this first version all three are *implicit*.  C and E are simply the
parameters `expr` and `env`, and K is the Python call stack itself -- each
recursive lEval call is one frame of "what to do next".  Later parts make
each one explicit: IttyBittyLisp3 turns tail calls into a loop, and
IttyBittyLisp4 (the CEK machine) promotes C, E, and K into real machine
registers that the loop updates in place -- and IttyBittyLisp5 scales that same
machine up to the full language.

Stack discipline: every call -- tail and non-tail alike -- recurses, so the
Python call stack holds the entire evaluation; it overflows even for simple
tail recursion.

Run with: python IttyBittyLisp1.py
"""

# ---------------------------------------------------------------------------
# The recursive evaluator
# ---------------------------------------------------------------------------

def lEval( expr, env ):
    # ---- State = EVAL (dispatch on expression syntax) ----
    if expr in ('#t', '#f'):           # boolean -> return unchanged
        return expr
    elif isinstance(expr, str):        # symbol -> look it up
        return env[expr]
    elif not isinstance(expr, list):   # other non-lists -> return unchanged
        return expr

    elif expr[0] == 'set!':
        # Real Scheme separates `define` (introduce a binding) from `set!`
        # (assign an existing one); this tiny Lisp uses one lenient `set!`.
        name, valExpr = expr[1:]
        val = lEval(valExpr, env)
        env[name] = val
        return val

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

    else:
        # Call a primitive
        fn, *args = [ lEval(elt, env) for elt in expr ]   # eval operator + operands

        # ---- State = APPLY (invoke a procedure on evaluated args) ----
        # This minimal Lisp has only primitives (no lambda yet), so every callable
        # is a plain Python function.
        return fn( args )

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

global_env = {
    '+':     lambda args: sum( args ),                          # variadic; (+) is 0
    '-':     lambda args: args[0] - args[1],
    '*':     lisp_mul,                                          # variadic; (*) is 1
    '=':     lambda args: '#t' if args[0] == args[1] else '#f',
    '<':     lambda args: '#t' if args[0] <  args[1] else '#f',
    'print': lisp_print,
}

# ---------------------------------------------------------------------------
# Helpers and demo
# ---------------------------------------------------------------------------

def lisp_str( val ):
    # Render a value (or AST node) in Lisp surface syntax, so the demo speaks
    # the language being interpreted instead of printing Python's repr.
    if isinstance( val, list ):
        return '(' + ' '.join( lisp_str( x ) for x in val ) + ')'
    if callable( val ):
        return '#<primitive>'
    return str( val )

def run( expr ):
    result = lEval( expr, global_env )
    print( f'>>> {lisp_str( expr )}' )    # the expression, in Lisp syntax
    print( f'==> {lisp_str( result )}' )  # its value, in Lisp syntax
    print()

def main() -> None:
    # Self-evaluating atom: a number evaluates to itself.
    run( 42 )

    # set!: assign a variable, return the value.
    run( ['set!', 'a', ['+', 1, 1]] )

    # Symbol lookup: a bare variable evaluates to its current value.
    run( 'a' )

    # Arithmetic primitives.
    run( ['+', ['-', 10, 7], 'a'] )
    run( ['*', 3, 4] )

    # A side-effecting primitive.  Unlike +, -, *, =, <, the print primitive
    # reaches outside the evaluator -- and it *returns* its argument, so it
    # composes inside a larger expression.  Because run() evaluates before it
    # echoes, the raw 10 (the effect) prints above the >>> line, and 15 (the
    # returned 10, flowed on into +) is the value.
    run( ['+', ['print', 10], 5] )

    # Comparison: = and < return #t (true) or #f (false).
    run( ['=', 'a', 2] )
    run( ['<', 2, 5] )
    run( ['<', 5, 2] )

    # if: evaluate condition, then pick the matching branch.
    run( ['if', ['=', 'a', 2], ['+', 'a', 1], ['-', 'a', 1]] )

    # begin: evaluate a sequence of forms; return the value of the last one.
    run( ['begin', ['set!', 'b', 10], ['+', 'b', 5]] )

    # quote: return a datum unevaluated -- suppresses evaluation entirely.
    run( ['quote', ['a', 'b', 'c']] )

if __name__ == '__main__':
    main()
