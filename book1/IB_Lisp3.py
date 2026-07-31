"""
IB_Lisp3 - A looping Lisp evaluator with tail-call optimization (TCO).

The key idea: instead of recursing into tail positions, overwrite the
current expression and environment and loop.

This is the first part where C and E become real machine registers.  Where
IB_Lisp1 recursed for *every* sub-expression, here a tail position
just reassigns the registers and loops back:

  C - the Control:      the expression currently being evaluated  (was `expr`)
  E - the Environment:  the bindings in scope                     (was `env`)

K -- the continuation -- is still implicit here.  Non-tail sub-expressions
(an `if` condition, a call's arguments, non-tail body forms) are still
evaluated by a recursive lEval call, so they still ride the Python call
stack -- the stack *is* K for now.  That is why deeply *non-tail* recursion
can still overflow.  IB_Lisp4 promotes K to an explicit stack as well,
removing the last use of Python's call stack.

Compare with IB_Lisp1.py, which uses a naive recursive evaluator
and overflows Python's call stack even for tail-recursive programs.

Stack discipline: tail positions loop (the Python stack stays flat), but
non-tail sub-expressions still recurse -- so only *non-tail* depth uses the
Python call stack.  Tail recursion runs forever; deep non-tail nesting can
still overflow.

Run with: python IB_Lisp3.py
"""

from IB_AST import lTrue, lFalse
from IB_Reader import parse

# ---------------------------------------------------------------------------
# Environment: a scope at run time, linked into a stack
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
# Function: a closure capturing its lexical environment
# ---------------------------------------------------------------------------

class Function:
    def __init__( self, params, body, definingEnv ):
        self.params = params   # list of parameter name strings
        self.body   = body     # list of body expressions; last is the tail
        self.definingEnv = definingEnv   # captured when the lambda is evaluated

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
        if isinstance(C, str):        # a symbol -- look it up in the environment
            return E.lookup(C)
        elif not isinstance(C, list): # a number or boolean -- evaluates to itself
            return C
        elif C[0] == 'set!':
            _, name, valExpr = C
            val = lEval(valExpr, E)             # rvalue: not tail, recurse
            return E.set(name, val)

        elif C[0] == 'if':
            _, condExpr, thenExpr, elseExpr = C
            condVal = lEval(condExpr, E)   # condition: not tail, recurse
            C = elseExpr if condVal is lFalse else thenExpr
            continue                            # tail branch: loop

        elif C[0] == 'cond':
            # Really a chain of ifs, so say so: peel one clause and loop.  The
            # chosen result stays in tail position, so cond keeps TCO.
            clauses = C[1:]
            if not clauses:
                return lFalse
            test, result = clauses[0]
            if test == 'else':
                C = result
            else:
                C = [ 'if', test, result, ['cond'] + list(clauses[1:]) ]
            continue

        elif C[0] == 'and':                     # short-circuits at the first #f
            forms = C[1:]
            if not forms:
                return lTrue                    # (and) with no forms is true
            for subExpr in forms[:-1]:          # non-tail forms: recurse
                if lEval(subExpr, E) is lFalse:
                    return lFalse
            C = forms[-1]
            continue                            # tail: the last form's value wins

        elif C[0] == 'or':                      # short-circuits at the first true
            forms = C[1:]
            if not forms:
                return lFalse                   # (or) with no forms is false
            for subExpr in forms[:-1]:          # non-tail forms: recurse
                val = lEval(subExpr, E)
                if val is not lFalse:
                    return val                  # the true value itself, not #t
            C = forms[-1]
            continue                            # tail: the last form's value wins

        elif C[0] == 'begin':
            _, *forms = C
            for subExpr in forms[:-1]:          # non-tail forms: recurse
                lEval(subExpr, E)
            C = forms[-1]
            continue                            # tail: last form

        elif C[0] == 'quote':
            return C[1]

        elif C[0] == 'lambda':
            _, params, *body = C
            return Function(params, body, E)

        elif C[0] == 'let':
            _, bindingPairs, *body = C
            
            # Eval every init expr in the OUTER env E (parallel `let`, not `let*`),
            # then open a new environment that holds them all.
            initialBindings = { name: lEval(initExpr, E) for name, initExpr in bindingPairs }
            E = Environment( outer=E, bindings=initialBindings )
        
            # Execute body in the new E
            for subExpr in body[:-1]:            # non-tail body forms: recurse
                lEval(subExpr, E)
            C = body[-1]
            continue                            # tail: last body form

        else:
            fn, *args = [ lEval(elt, E) for elt in C ]   # eval operator + operands

            # apply is a value, not a special form: (apply g x ... lst) is a call
            # of g on x ... plus the elements of lst.  Splice it here, at the call
            # site.  A tail apply stays a tail call because nothing is pushed; the
            # loop lets (apply apply ...) resolve.
            while fn is applyFn:
                fn, args = args[0], args[1:-1] + list( args[-1] )

            # ---- State = APPLY (invoke a procedure on evaluated args) ----
            if callable(fn):                        # primitive implemented in Python
                return fn(args)
            else:
                # user-defined function: TCO -- reassign the registers and loop.  The
                # new environment is opened on the *captured* (lexical) env, not the caller's.
                initialBindings = bind_params(fn.params, args)
                E = Environment( outer=fn.definingEnv, bindings=initialBindings )

                # Execute the body in the new E
                for subExpr in fn.body[:-1]:            # non-tail body forms: recurse
                    lEval(subExpr, E)
                C = fn.body[-1]
                continue                                # tail call: loop, no stack growth

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
    # Render a value (or AST node) in Lisp surface syntax, so the demo speaks
    # the language being interpreted instead of printing Python's repr.
    if isinstance( val, list ):
        return '(' + ' '.join( lisp_str( x ) for x in val ) + ')'
    if isinstance( val, Function ):
        return '#<procedure (' + ' '.join( val.params ) + ')>'
    if val is applyFn:
        return '#<primitive apply>'
    if callable( val ):
        return '#<primitive>'
    return str( val )

def run( source ):
    expr = parse( source ) if isinstance( source, str ) else source   # Chapter 8 built this
    print( f'>>> {lisp_str( expr )}' )    # the expression, in Lisp syntax
    result = lEval( expr, global_env )
    print( f'==> {lisp_str( result )}' )  # its value, in Lisp syntax
    print()


def main():
    # Basic arithmetic
    run( '(+ (- 10 7) 2)' )

    # A side-effecting primitive.  Unlike +, -, *, =, <, the print primitive
    # reaches outside the evaluator -- and it *returns* its argument, so it
    # composes inside a larger expression.  run() echoes the form first, so the
    # raw 10 (the effect) prints between the >>> line and the value, and 15 (the
    # returned 10, flowed on into +) is the value.
    run( '(+ (print 10) 5)' )

    # set! and variable lookup
    run( '(set! x (* 6 7))' )
    run( 'x' )

    # lambda creates a closure
    run( '(set! square (lambda (n) (* n n)))' )
    run( '(square 5)' )

    # let creates a local scope
    run( '(let ((a 3) (b 4)) (+ (* a a) (* b b)))' )

    # Tail-recursive countdown.
    # The naive recursive evaluator in IB_Lisp1.py would hit Python's
    # ~1000-frame stack limit and crash.  With TCO each tail call reuses
    # the same Python frame, so 100,000 iterations need only a handful of
    # stack frames.
    run( '(set! countdown (lambda (n) (if (= n 0) 0 (countdown (- n 1)))))' )

    run( '(countdown 100000)' )

    # Rest parameters and apply, and the tail call survives both: a tail apply
    # loops rather than recursing, so this runs in constant stack.
    run( '(set! countdown2 (lambda (n . ignored) (cond ((= n 0) 0) (else (apply countdown2 (list (- n 1)))))))' )
    run( '(countdown2 100000)' )

    # and/or keep their last form in tail position too.
    run( "(and (< 1 2) (or #f 'reached))" )


if __name__ == '__main__':
    main()
