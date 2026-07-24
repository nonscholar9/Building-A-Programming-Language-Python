"""
IBBase - Book One's machine, with the challenges done.

This is the machine Book Two builds on, and it is not a new one.  It is
IBLisp5, the CEK machine from Book One, plus exactly the things Book One
asked you to add and then left to you:

  * `cond`                       Book One, Chapter 1 challenge
  * `not`, `and`, `or`           Book One, Chapter 1 challenge
  * `car cdr cons list null?`    Book One, Chapter 1 challenge
  * rest parameters              Book One, Chapter 2 challenge
  * `call/cc`                    Book One, the second interlude

Nothing here is new.  If you worked those challenges, this file is what you
already have, and you can keep using yours.  If you skipped them, take this one:
every addition is a few lines you can read in place, and none of them touches
the evaluator's shape.  The two loops, the registers, and the frames are exactly
as Chapter 5 left them.

That is the point, and it is worth being plain about it.  Book Two never changes
this machine.  It sits underneath, and everything we build from here runs in
front of it -- which is what it means to call it a *backend*.

Run with: python IBBase.py
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
# call/cc support
# ---------------------------------------------------------------------------
# A captured continuation is nothing but a saved copy of the K stack.  Because
# K is an ordinary list, "reify the continuation" = "copy the list", and
# "resume the continuation" = "make that list be K again".

class Continuation:
    """A reified continuation: a snapshot of the K stack, taken at the moment
    call/cc ran.  Invoking it like a one-argument function discards whatever K
    is current and reinstates this saved one, so control jumps back to wherever
    the continuation was captured, carrying the supplied value."""
    def __init__( self, stack ):
        self.stack = stack

class _CallCC:
    """The call/cc primitive is a sentinel, not an ordinary Python callable,
    because capturing the continuation needs the machine's K register -- which
    a plain primitive never sees.  The APPLY loop recognizes this object and
    does the capture itself."""

CALLCC = _CallCC()

class _Apply:
    """apply is also a value, not a special form: it must open a scope and run a
    body, which no primitive can do, so the evaluator recognizes it at the call
    site (see the splice in FRAME_ARG), the same way it recognizes call/cc."""

APPLY = _Apply()

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
#              a closure (VAL_CLOSURE, params, body, captured_env);
#              a Continuation (a saved K stack); the CALLCC sentinel.

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

                while fn is APPLY:             # apply is a value: splice its final
                    # list into the argument positions and call the real function,
                    # here at the call site, just as call/cc reaches in below.
                    fn, args = args[0], list( args[1:-1] ) + list( args[-1] )

                if fn is CALLCC:               # (call/cc f): reify K, then call f with it
                    # This application's own frame was already popped above, so K
                    # right now *is* the continuation of the whole (call/cc f)
                    # expression.  Snapshot it, and redirect to "call f on it".
                    cont = Continuation( list(K) )
                    fn, args = args[0], [cont]

                if isinstance( fn, Continuation ):   # invoking a captured continuation
                    K = list( fn.stack )       # discard current K, reinstate the saved one
                    V = args[0]                # the value handed to the continuation...
                    continue                   # ...flows straight into the restored K

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
    'call/cc':                       CALLCC,                    # the star of this file
    'call-with-current-continuation': CALLCC,                  # its full Scheme name
    'apply':                         APPLY,                     # a value, spliced at the call site
}
global_env = Environment( bindings=globalBindings )

# ---------------------------------------------------------------------------
# Helpers and demo
# ---------------------------------------------------------------------------

def lisp_str( val ):
    if isinstance( val, list ):
        return '(' + ' '.join( lisp_str(x) for x in val ) + ')'
    if isinstance( val, Continuation ):      # a reified continuation
        return '#<continuation>'
    if val is CALLCC:
        return '#<primitive call/cc>'
    if val is APPLY:
        return '#<primitive apply>'
    if isinstance( val, tuple ):             # a closure: (VAL_CLOSURE, params, body, env)
        return '#<procedure (' + ' '.join( val[1] ) + ')>'
    if callable( val ):
        return '#<primitive>'
    return str( val )


def run( expr ):
    result = lEval( expr, global_env )
    print( '>>> ' + lisp_str( expr ) )
    print( '==> ' + lisp_str( result ) )
    print()


def main():
    print( '--- everything Chapter 5 had, unchanged ---\n' )
    run( ['+', ['-', 10, 7], 2] )                          # 5
    run( ['let', [['a', 3], ['b', 4]],
          ['+', ['*', 'a', 'a'], ['*', 'b', 'b']]] )       # 25
    run( ['quote', ['a', 'b', 'c']] )                      # (a b c)

    print( "--- Chapter 1's list primitives ---\n" )
    run( ['car', ['quote', ['a', 'b', 'c']]] )             # a
    run( ['cdr', ['quote', ['a', 'b', 'c']]] )             # (b c)
    run( ['cons', 1, ['quote', [2, 3]]] )                  # (1 2 3)
    run( ['list', 1, 2, 3] )                               # (1 2 3)
    run( ['null?', ['quote', []]] )                        # #t

    print( "--- Chapter 1's cond, and, or, not ---\n" )
    run( ['set!', 'sign',
          ['lambda', ['n'],
           ['cond', [['=', 'n', 0], ['quote', 'zero']],
                    [['<', 'n', 0], ['quote', 'negative']],
                    ['else',        ['quote', 'positive']]]]] )
    run( ['sign', 0] )                                     # zero
    run( ['sign', -5] )                                    # negative
    run( ['sign', 5] )                                     # positive

    run( ['and', 1, 2, 3] )                                # 3   (last value)
    run( ['and', 1, lFalse, 3] )                           # #f
    run( ['or', lFalse, 2, 3] )                            # 2   (first true value)
    run( ['or', lFalse, lFalse] )                          # #f
    run( ['not', lFalse] )                                 # #t

    # Short-circuiting is the reason these cannot be primitives: if `and` ran
    # like `+`, this would print 99 before deciding anything.
    run( ['and', lFalse, ['print', 99]] )                  # #f, and 99 never prints

    print( "--- Chapter 2's rest parameters ---\n" )
    run( ['set!', 'tally', ['lambda', ['first', '.', 'rest'],
                            ['list', 'first', 'rest']]] )
    run( ['tally', 1] )                                    # (1 ())
    run( ['tally', 1, 2, 3] )                              # (1 (2 3))

    print( '--- the second interlude: call/cc ---\n' )
    run( ['+', 1, ['call/cc', ['lambda', ['k'], ['+', 10, ['k', 5]]]]] )   # 6

    # An escape, which is what mini-Python's `return` will need.
    run( ['set!', 'first-negative',
          ['lambda', ['xs'],
           ['call/cc', ['lambda', ['return'],
             ['begin',
              ['set!', 'walk', ['lambda', ['ys'],
                ['cond', [['null?', 'ys'], lFalse],
                         [['<', ['car', 'ys'], 0], ['return', ['car', 'ys']]],
                         ['else', ['walk', ['cdr', 'ys']]]]]],
              ['walk', 'xs']]]]]] )
    run( ['first-negative', ['quote', [3, 7, -2, 9]]] )    # -2
    run( ['first-negative', ['quote', [3, 7, 9]]] )        # #f

    print( '--- and the machine is still the machine ---\n' )
    run( ['set!', 'countdown',
          ['lambda', ['n'],
           ['if', ['=', 'n', 0], 0, ['countdown', ['-', 'n', 1]]]]] )
    run( ['countdown', 100000] )                           # 0, in constant K


if __name__ == '__main__':
    main()
