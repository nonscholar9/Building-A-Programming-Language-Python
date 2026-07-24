"""
IB_Lisp1 - The simplest possible Lisp evaluator.

The AST is hand-written as nested Python lists -- no parser.  The environment
is a plain Python dict -- no scoping, no closures.  Every recursive call pushes
a new Python stack frame, so deeply recursive Lisp programs will overflow
Python's ~1000-frame limit.

This file is the starting point for a series that progressively adds features:

  IB_Lisp1.py   -- bare evaluator, flat dict environment  (this file)
  IB_Lisp2.py   -- adds closures, let, lexical scoping
  IB_Lisp3.py   -- adds tail-call optimization (TCO) via looping
  IB_Lisp4.py   -- the CEK machine (explicit K), on pure lambda calculus
  IB_Lisp5.py   -- the CEK machine with the full language restored
  IB_Lisp6.py   -- compiles the machine to a flat bytecode VM
  IB_Lisp8_parser.py  -- adds a source-string parser to complete the pipeline

Throughout the series, evaluation is driven by three quantities:

  C - the Control:      the expression currently being evaluated
  E - the Environment:  the bindings in scope
  K - the Kontinuation: what to do with the result once it is known

In this first version all three are *implicit*.  C and E are simply the
parameters `expr` and `env`, and K is the Python call stack itself -- each
recursive lEval call is one frame of "what to do next".  Later parts make
each one explicit: IB_Lisp3 turns tail calls into a loop, and
IB_Lisp4 (the CEK machine) promotes C, E, and K into real machine
registers that the loop updates in place -- and IB_Lisp5 scales that same
machine up to the full language.

Stack discipline: every call -- tail and non-tail alike -- recurses, so the
Python call stack holds the entire evaluation; it overflows even for simple
tail recursion.

Run with: python IB_Lisp1.py
"""

from IB_AST import lTrue, lFalse

# ---------------------------------------------------------------------------
# The recursive evaluator
# ---------------------------------------------------------------------------

def lEval( expr, env ):
    # ---- State = EVAL (dispatch on expression syntax) ----
    if isinstance(expr, str):          # symbol -> look it up
        return env[expr]
    elif not isinstance(expr, list):   # number or boolean -> return unchanged
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
        return lEval(elseExpr if condVal is lFalse else thenExpr, env)

    elif expr[0] == 'cond':
        # Really a chain of ifs, so say so: peel one clause and re-evaluate the
        # rest.  `else` is the clause whose test always holds.
        clauses = expr[1:]
        if not clauses:
            return lFalse
        test, result = clauses[0]
        if test == 'else':
            return lEval(result, env)
        return lEval( ['if', test, result, ['cond'] + list(clauses[1:])], env )

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

    # The list primitives are what make quote pay off: with them a quoted list
    # can be taken apart and rebuilt, all without touching lEval.
    run( ['car', ['quote', ['a', 'b', 'c']]] )
    run( ['cdr', ['quote', ['a', 'b', 'c']]] )
    run( ['cons', 1, ['quote', [2, 3]]] )
    run( ['list', 1, ['+', 1, 1], 3] )
    run( ['null?', ['quote', []]] )

    # cond: a chain of ifs written flat, with else as the last clause.
    run( ['cond', [['<', 'a', 0], ['quote', 'negative']],
                  [['=', 'a', 0], ['quote', 'zero']],
                  ['else',        ['quote', 'positive']]] )

    # not is a primitive; and/or are special forms, because they must be able
    # to leave an operand unevaluated.  Both return a value, not just #t/#f.
    run( ['not', ['=', 'a', 2]] )
    run( ['and', ['<', 1, 2], ['quote', 'both']] )
    run( ['or', ['<', 2, 1], ['quote', 'fallback']] )

    # The short circuit is observable: print never runs on the skipped operand.
    run( ['and', lFalse, ['print', 'unreached']] )

if __name__ == '__main__':
    main()
