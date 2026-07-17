"""
IttyBittyCore - the machine, finished.

This is where Chapter 9 leaves the evaluator, and it is the last time the
evaluator changes.  From Chapter 10 on, every example in this book begins with

    from IttyBittyCore import lEval, global_env, lisp_str

and never opens this file again.  That import is the whole argument of Book Two
written as one line: everything we build from here runs *in front of* the
machine, and a backend is something you use without opening.

What is in here is Chapter 5's CEK machine, plus the Book One challenges the
introduction handed over, minus the four forms Chapter 9 took out.  `let`,
`cond`, `and`, and `or` are gone, along with two frame kinds, because they are
rewrite rules now and a rule needs no room in the machine.  A program that has
been through the expander contains none of them.

The core forms that remain are all the machine knows: quote, lambda, if, set!,
begin, and application.

Two halves, and they are not equally settled:

  * The machine itself (Environment, bind_params, lEval, the frames) is FINAL.
    Nothing later in this book touches it.

  * The primitives below it are NOT frozen.  Adding a primitive is not a change
    to the evaluator, it is a change to what happens to be bound in the global
    environment when it starts, and later chapters may well add one.

Run with: python IttyBittyCore.py   (a short check that the machine is alive)
"""

# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
VAL_CLOSURE = 1

# Continuation frame kinds.
FRAME_IF  = 0   # waiting on a test value
FRAME_SET = 1   # waiting on a value to assign
FRAME_SEQ = 2   # a begin / body with forms still to run
FRAME_ARG = 3   # an application accumulating operator + operands


# ---------------------------------------------------------------------------
# call/cc support (Book One's second interlude, unchanged)
# ---------------------------------------------------------------------------

class Continuation:
    """A reified continuation: a snapshot of the K stack."""
    def __init__( self, stack ):
        self.stack = stack

class _CallCC:
    """A sentinel, not a plain callable: capturing the continuation needs the
    machine's K register, which an ordinary primitive never sees."""

CALLCC = _CallCC()


# ---------------------------------------------------------------------------
# Environment: a linked chain of scopes
# ---------------------------------------------------------------------------

class Environment:
    def __init__( self, parent=None, bindings=None ):
        # Note: this COPIES the bindings it is given.  Handing more primitives
        # to an environment that already exists means calling .set() on it.
        self._bindings = dict(bindings or {})
        self._parent   = parent
        self._global   = parent._global if parent else self

    def lookup( self, name ):
        scope = self
        while scope:
            if name in scope._bindings:
                return scope._bindings[name]
            scope = scope._parent
        raise NameError( f'Unbound variable: {name}' )

    def set( self, name, value ):
        scope = self
        while scope:
            if name in scope._bindings:
                scope._bindings[name] = value
                return value
            scope = scope._parent
        self._global._bindings[name] = value
        return value

    def set2( self, name, value ):
        # Like set, but a miss creates the binding in the INNERMOST scope
        # rather than the global one: an assignment that makes a new local.
        scope = self
        while scope:
            if name in scope._bindings:
                scope._bindings[name] = value
                return value
            scope = scope._parent
        self._bindings[name] = value
        return value


# ---------------------------------------------------------------------------
# Binding a call's arguments  (Book One, Chapter 2 challenge: rest parameters)
# ---------------------------------------------------------------------------

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
# Registers:  C (expression), V (value), E (environment), K (frame stack).
#
# Value forms: a number; '#t' / '#f'; a list; a primitive (a Python callable);
#              a closure (VAL_CLOSURE, params, body, captured_env);
#              a Continuation; the CALLCC sentinel.
#
# Note what a plain Python string means here: a VARIABLE.  That is why this
# language has no string literals, and why adding them would be a change to the
# machine rather than an addition to it.

def lEval( expr, env ):
    C = expr
    V = None
    E = env
    K = []

    while True:

        # ----- state EVAL: descend into C (pushing frames) until a leaf -> V -----
        while True:
            if C in ('#t', '#f'):              # boolean literal -> itself
                V = C
                break
            elif isinstance( C, (int, float) ):  # number -> itself
                V = C
                break
            elif isinstance( C, str ):         # variable -> look it up
                V = E.lookup( C )
                break
            elif C[0] == 'quote':              # ['quote', datum] -> the datum
                V = C[1]
                break
            elif C[0] == 'lambda':             # ['lambda', params, *body] -> a closure
                V = ( VAL_CLOSURE, C[1], list(C[2:]), E )
                break
            elif C[0] == 'if':                 # ['if', test, then, else]
                K.append( (FRAME_IF, C[2], C[3], E) )
                C = C[1]
            elif C[0] == 'set!':               # ['set!', name, valueExpr]
                K.append( (FRAME_SET, C[1], E, False) )   # miss -> global
                C = C[2]
            elif C[0] == 'set2!':              # ['set2!', name, valueExpr]
                K.append( (FRAME_SET, C[1], E, True) )    # miss -> innermost scope
                C = C[2]
            elif C[0] == 'begin':              # ['begin', *forms]
                forms = list( C[1:] )
                if len(forms) > 1:
                    K.append( (FRAME_SEQ, forms[1:], E) )
                C = forms[0]
            else:                              # [fn, *args] -- an application
                K.append( (FRAME_ARG, [], list(C[1:]), E) )
                C = C[0]

        # ----- state APPLY: feed V to the top frame -----
        while True:
            if not K:
                return V

            frame = K.pop()
            ftag  = frame[0]

            if ftag == FRAME_IF:               # (FRAME_IF, then, else, env)
                C = frame[1] if V != '#f' else frame[2]
                E = frame[3]
                break

            elif ftag == FRAME_SET:            # (FRAME_SET, name, env, local?)
                if frame[3]:
                    frame[2].set2( frame[1], V )
                else:
                    frame[2].set( frame[1], V )
                continue

            elif ftag == FRAME_SEQ:            # (FRAME_SEQ, remaining_forms, env)
                forms = frame[1]
                E = frame[2]
                if len(forms) > 1:
                    K.append( (FRAME_SEQ, forms[1:], E) )
                C = forms[0]
                break

            elif ftag == FRAME_ARG:            # (FRAME_ARG, done, todo, env)
                done = frame[1] + [V]
                todo = frame[2]
                if todo:
                    K.append( (FRAME_ARG, done, todo[1:], frame[3]) )
                    C = todo[0]
                    E = frame[3]
                    break
                fn, args = done[0], done[1:]

                if fn is CALLCC:               # (call/cc f): reify K, then call f with it
                    cont = Continuation( list(K) )
                    fn, args = args[0], [cont]

                if isinstance( fn, Continuation ):   # invoking a captured continuation
                    K = list( fn.stack )
                    V = args[0]
                    continue

                if callable( fn ):             # primitive
                    V = fn( args )
                    continue
                _, params, body, clo_env = fn  # closure
                E = Environment( parent=clo_env, bindings=bind_params( params, args ) )
                if len(body) > 1:
                    K.append( (FRAME_SEQ, body[1:], E) )
                C = body[0]
                break


# ---------------------------------------------------------------------------
# Primitives and global environment
# ---------------------------------------------------------------------------
#
# Everything above this line is finished.  Everything below it is a list of
# names that happen to be bound when the machine starts, and a later chapter
# that needs one more is welcome to add it.

def lisp_print( args ):
    print( args[0] )
    return args[0]

def lisp_mul( args ):
    result = 1
    for x in args:
        result *= x
    return result

def lisp_bool( b ):
    return '#t' if b else '#f'

globalBindings = {
    '+':     lambda args: sum( args ),
    '-':     lambda args: args[0] - args[1],
    '*':     lisp_mul,
    '/':     lambda args: args[0] / args[1],
    '%':     lambda args: args[0] % args[1],
    '=':     lambda args: lisp_bool( args[0] == args[1] ),
    '<':     lambda args: lisp_bool( args[0] <  args[1] ),
    '>':     lambda args: lisp_bool( args[0] >  args[1] ),
    '<=':    lambda args: lisp_bool( args[0] <= args[1] ),
    '>=':    lambda args: lisp_bool( args[0] >= args[1] ),
    'print': lisp_print,

    'car':   lambda args: args[0][0],
    'cdr':   lambda args: args[0][1:],
    'cons':  lambda args: [args[0]] + args[1],
    'list':  lambda args: list( args ),
    'null?': lambda args: lisp_bool( args[0] == [] ),

    'not':   lambda args: lisp_bool( args[0] == '#f' ),

    'call/cc':                        CALLCC,
    'call-with-current-continuation': CALLCC,
}
global_env = Environment( bindings=globalBindings )


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def lisp_str( val ):
    if isinstance( val, list ):
        return '(' + ' '.join( lisp_str(x) for x in val ) + ')'
    if isinstance( val, tuple ):
        return '#<procedure (' + ' '.join( val[1] ) + ')>'
    if isinstance( val, Continuation ):
        return '#<continuation>'
    if val is CALLCC:
        return '#<primitive call/cc>'
    if callable( val ):
        return '#<primitive>'
    return str( val )


# ---------------------------------------------------------------------------
# A check that the machine is alive
# ---------------------------------------------------------------------------
#
# Core forms only.  Anything with a `let` or a `cond` in it belongs to the
# expander now, and will not run here.

def main():
    checks = [
        ( ['+', ['-', 10, 7], 2],                                  5 ),
        ( ['if', ['<', 1, 2], ['quote', 'yes'], ['quote', 'no']],  'yes' ),
        ( [['lambda', ['x'], ['*', 'x', 'x']], 7],                 49 ),
        ( ['quote', ['a', 'b']],                                   '(a b)' ),
    ]
    for expr, want in checks:
        got = lisp_str( lEval( expr, global_env ) )
        print( f'{"ok " if got == str(want) else "FAIL"} {lisp_str(expr)}  ==>  {got}' )

    # Tail calls still loop, and call/cc still escapes.
    lEval( ['set!', 'countdown',
            ['lambda', ['n'], ['if', ['=', 'n', 0], 0,
                               ['countdown', ['-', 'n', 1]]]]], global_env )
    got = lEval( ['countdown', 100000], global_env )
    print( f'{"ok " if got == 0 else "FAIL"} (countdown 100000)  ==>  {got}   [constant K]' )

    got = lEval( ['call/cc', ['lambda', ['k'],
                              ['+', 1, ['k', 42]]]], global_env )
    print( f'{"ok " if got == 42 else "FAIL"} (call/cc (lambda (k) (+ 1 (k 42))))  ==>  {got}' )


if __name__ == '__main__':
    main()
