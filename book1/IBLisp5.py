"""
IBLisp5 - The CEK Machine, Complete.

Continues from IBLisp4, which introduced the CEK machine on pure lambda
calculus + if -- the smallest setting that still has closures and control flow,
so the machine itself (the C/E/K registers, the two-state EVAL/APPLY loop, the
continuation frames) stands out with nothing else competing for attention.

This part puts the full IBLisp3 language back: #t/#f with Scheme
truthiness (#f is the only false value -- 0 is true), quote, set!, begin,
multi-argument lambdas and applications, let, and primitives.  The lesson is
that doing so does NOT change the machine's shape.  The two loops and the
explicit K stack are untouched; the language just contributes more kinds of
continuation frame:

  FRAME_IF   -- wait on a test value, then pick a branch
  FRAME_SET  -- wait on a value, then assign it
  FRAME_SEQ  -- a begin / lambda-body with forms still to run
  FRAME_ARG  -- an application accumulating operator + operands

let needs no frame of its own: it desugars to a lambda application right in the
EVAL loop.  A function call pushes no frame (FRAME_ARG installs the body
directly), so a tail call reuses the current K depth -- the same tail-call
optimization #3 and #4 have, now living on the explicit stack.  (countdown
100000) at the bottom runs in constant K depth to prove it.

Run with: python IBLisp5.py
"""

from IB_AST import LBoolean, lTrue, lFalse

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
# Environment: a linked chain of scopes (same class as IBLisp2/3/4)
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
#   K : continuation stack (a Python list)
#
# Value forms: a number; a boolean (#t / #f); a primitive (a Python callable);
#              a closure (VAL_CLOSURE, params, body, captured_env).

def lEval( expr, env ):
    C = expr
    V = None
    E = env
    K = []

    while True:

        # ----- state EVAL: descend into C (pushing frames) until a leaf -> V -----
        while True:
            if isinstance( C, str ):           # variable -> look it up
                V = E.lookup( C )
                break
            elif isinstance( C, (int, float, LBoolean) ):  # number or boolean -> itself
                V = C
                break
            elif C[0] == 'quote':              # ['quote', datum] -> the datum, unevaluated
                V = C[1]
                break
            elif C[0] == 'lambda':             # ['lambda', params, *body] -> a closure
                V = ( VAL_CLOSURE, C[1], list(C[2:]), E )
                break
            elif C[0] == 'if':                 # ['if', test, then, else]
                K.append( (FRAME_IF, C[2], C[3], E) )
                C = C[1]                       # evaluate the test first
            elif C[0] == 'set!':               # ['set!', name, valueExpr]
                K.append( (FRAME_SET, C[1], E) )
                C = C[2]                       # evaluate the value first
            elif C[0] == 'begin':              # ['begin', *forms]
                forms = list( C[1:] )
                if len(forms) > 1:
                    K.append( (FRAME_SEQ, forms[1:], E) )
                C = forms[0]
            elif C[0] == 'let':                # ['let', ((name init)...), *body]
                # Desugar to ((lambda (name...) body...) init...) and re-dispatch.
                names = [ pair[0] for pair in C[1] ]
                inits = [ pair[1] for pair in C[1] ]
                C = [ ['lambda', names] + list(C[2:]) ] + inits
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
                    C = [ 'if', test, result, ['cond'] + clauses[1:] ]
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
                K.append( (FRAME_ARG, [], list(C[1:]), E) )
                C = C[0]                       # evaluate the operator first

        # ----- state APPLY: feed V to the top frame -----
        while True:
            if not K:
                return V

            frame = K.pop()
            ftag  = frame[0]

            if ftag == FRAME_IF:               # (FRAME_IF, then, else, env)
                C = frame[1] if V is not lFalse else frame[2]   # #f is the only false
                E = frame[3]
                break

            elif ftag == FRAME_SET:            # (FRAME_SET, name, env)
                frame[2].set( frame[1], V )    # V is set!'s result; it flows on
                continue                       # stay in APPLY

            elif ftag == FRAME_SEQ:            # (FRAME_SEQ, remaining_forms, env)
                forms = frame[1]               # the previous form's value V is discarded
                E = frame[2]
                if len(forms) > 1:
                    K.append( (FRAME_SEQ, forms[1:], E) )
                C = forms[0]
                break

            elif ftag == FRAME_ARG:            # (FRAME_ARG, done, todo, env)
                done = frame[1] + [V]
                todo = frame[2]
                if todo:                       # more operands to evaluate
                    K.append( (FRAME_ARG, done, todo[1:], frame[3]) )
                    C = todo[0]
                    E = frame[3]
                    break
                # operator + all operands evaluated -> apply done[0] to done[1:]
                fn, args = done[0], done[1:]

                # apply is a value: splice its final list into the argument
                # positions and call the real function, here at the call site.
                # The loop lets (apply apply ...) resolve.
                while fn is APPLY:
                    fn, args = args[0], list( args[1:-1] ) + list( args[-1] )

                if callable( fn ):             # primitive: compute the value, flow it on
                    V = fn( args )
                    continue                   # stay in APPLY
                _, params, body, clo_env = fn  # closure: bind params, run the body
                initialBindings = bind_params( params, args )
                E = Environment( parent=clo_env, bindings=initialBindings )
                if len(body) > 1:
                    K.append( (FRAME_SEQ, body[1:], E) )
                C = body[0]
                break

            elif ftag == FRAME_AND:            # (FRAME_AND, remaining_forms, env)
                if V is lFalse:                # short-circuit: the #f flows on
                    continue
                forms = frame[1]
                if not forms:                  # V is the last operand's value
                    continue
                E = frame[2]
                K.append( (FRAME_AND, forms[1:], E) )
                C = forms[0]
                break

            elif ftag == FRAME_OR:             # (FRAME_OR, remaining_forms, env)
                if V is not lFalse:            # short-circuit: the true value flows on
                    continue
                forms = frame[1]
                if not forms:                  # V is #f
                    continue
                E = frame[2]
                K.append( (FRAME_OR, forms[1:], E) )
                C = forms[0]
                break

        # fall through to the outer loop -- re-enter EVAL with the new C/E


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

# apply is a value the evaluator recognizes at the call site, not a special form
# and not an ordinary primitive: it must open a scope and run a body, which a
# Python primitive cannot do.
class _Apply:
    pass

APPLY = _Apply()

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
    'apply': APPLY,
}
global_env = Environment( bindings=globalBindings )

# ---------------------------------------------------------------------------
# Helpers and demo
# ---------------------------------------------------------------------------

def lisp_str( val ):
    if isinstance( val, list ):
        return '(' + ' '.join( lisp_str(x) for x in val ) + ')'
    if isinstance( val, tuple ):             # a closure: (VAL_CLOSURE, params, body, env)
        return '#<procedure (' + ' '.join( val[1] ) + ')>'
    if val is APPLY:
        return '#<primitive apply>'
    if callable( val ):
        return '#<primitive>'
    return str( val )


def run( expr ):
    result = lEval( expr, global_env )
    print( '>>> ' + lisp_str( expr ) )
    print( '==> ' + lisp_str( result ) )
    print()


def main():
    run( ['+', ['-', 10, 7], 2] )                      # 5

    # A side-effecting primitive.  Unlike +, -, *, =, <, the print primitive
    # reaches outside the evaluator -- and it *returns* its argument, so it
    # composes inside a larger expression.  Because run() evaluates before it
    # echoes, the raw 10 (the effect) prints above the >>> line, and 15 (the
    # returned 10, flowed on into +) is the value.
    run( ['+', ['print', 10], 5] )                     # prints 10, ==> 15

    run( ['set!', 'x', ['*', 6, 7]] )                  # 42
    run( 'x' )                                          # 42

    run( ['set!', 'square', ['lambda', ['n'], ['*', 'n', 'n']]] )
    run( ['square', 5] )                                # 25

    run( ['let', [['a', 3], ['b', 4]],
          ['+', ['*', 'a', 'a'], ['*', 'b', 'b']]] )    # 25

    run( ['begin', ['set!', 'y', 1], ['set!', 'y', ['+', 'y', 9]], 'y'] )   # 10

    run( ['if', 0, 100, 200] )                          # 100  (0 is TRUE in Scheme)
    run( ['quote', ['a', 'b', 'c']] )                   # (a b c)

    # Tail-recursive countdown: TCO keeps K bounded, so 100,000 iterations run
    # without growing the continuation stack.
    run( ['set!', 'countdown',
          ['lambda', ['n'],
           ['if', ['=', 'n', 0], 0, ['countdown', ['-', 'n', 1]]]]] )
    run( ['countdown', 100000] )                        # 0

    # Chapter 1's forms, now on the machine.
    run( ['car', ['quote', ['a', 'b', 'c']]] )          # a
    run( ['cons', 1, ['quote', [2, 3]]] )               # (1 2 3)
    run( ['cond', [['<', 2, 1], ['quote', 'no']],
                  ['else', ['quote', 'yes']]] )         # yes
    run( ['and', lFalse, ['print', 'unreached']] )      # #f, and nothing prints
    run( ['or', lFalse, ['quote', 'fallback']] )        # fallback

    # Chapter 2's: a rest parameter, and apply spreading a list back out.
    run( ['set!', 'tally',
          ['lambda', ['label', '.', 'nums'],
           ['list', 'label', ['apply', '+', 'nums']]]] )
    run( ['tally', ['quote', 'total']] )                # (total 0)
    run( ['tally', ['quote', 'total'], 1, 2, 3] )       # (total 6)
    run( ['apply', '+', 10, 20, ['quote', [1, 2, 3]]] ) # 36

    # A tail apply is still a tail call: K stays bounded here too.
    run( ['set!', 'countdown2',
          ['lambda', ['n', '.', 'rest'],
           ['cond', [['=', 'n', 0], 0],
                    ['else', ['apply', 'countdown2', ['list', ['-', 'n', 1]]]]]]] )
    run( ['countdown2', 100000] )                       # 0


if __name__ == '__main__':
    main()
