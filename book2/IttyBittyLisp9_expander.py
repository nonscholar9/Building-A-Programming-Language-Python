"""
IttyBittyLisp9 - the expander: the sugar moves out of the machine.

This is IttyBittyBase with four branches deleted.

`let`, `cond`, `and`, and `or` are gone from lEval, and so are two frame kinds.
Nothing was lost.  Those four now live in a table of rewrite rules that runs
over the program before the machine ever sees it.  The machine got smaller and
the language stayed exactly the same size.

Two of the four were already rewrites and had been all along.  Look at the
`let` branch in IttyBittyBase, and the `cond` branch under it: each one builds a
new expression and re-dispatches.  That is a desugaring, performed at the last
possible moment, one node at a time, inside the evaluator's hot loop.  The other
two, `and` and `or`, were frames, so pulling them out deletes machinery too.

The table is a plain dict.  A dict is data, and data can be added to while the
program runs, which is `define-macro`:

    (define-macro (when test . body) (list 'if test (cons 'begin body) '#f))

A rule written in Lisp has to be *run* in order to expand a form, and running
Lisp is the one thing we already know how to do.  So the expander calls the
evaluator, and the compiler now contains the interpreter.

Run with: python IttyBittyLisp9_expander.py
"""

# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
VAL_CLOSURE = 1

# Continuation frame kinds.  FRAME_AND and FRAME_OR are gone: `and` and `or`
# are rewrite rules now, and a rule needs no room in the machine.
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
# The CEK machine, four branches lighter
# ---------------------------------------------------------------------------
#
# Registers:  C (expression), V (value), E (environment), K (frame stack).
#
# The core forms are all that is left: quote, lambda, if, set!, begin, and
# application.  Everything else the language offers arrives as a rewrite.

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
                K.append( (FRAME_SET, C[1], E) )
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

            elif ftag == FRAME_SET:            # (FRAME_SET, name, env)
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
# The expander
# ---------------------------------------------------------------------------
#
# A rewrite rule takes a form and returns another form.  The four below are the
# ones that used to be branches in lEval, written out as ordinary functions.
# Each rewrites its form into forms the machine still knows.

_gensym_counter = 0

def gensym():
    """Return a name that no source text can contain.

    A symbol in this Lisp is a plain Python string, and the reader splits the
    source on whitespace.  So a leading space is the whole trick: it makes a
    name the machine is perfectly happy with and the reader can never produce.
    """
    global _gensym_counter
    _gensym_counter += 1
    return ' t' + str( _gensym_counter )


def rule_let( form ):
    # (let ((name init)...) body...)  ->  ((lambda (name...) body...) init...)
    names = [ pair[0] for pair in form[1] ]
    inits = [ pair[1] for pair in form[1] ]
    return [ ['lambda', names] + list(form[2:]) ] + inits


def rule_cond( form ):
    # (cond (test result)...)  ->  (if test result (cond ...))
    # `else` is the clause whose test always holds.
    clauses = list( form[1:] )
    if not clauses:
        return '#f'
    test, result = clauses[0][0], clauses[0][1]
    if test == 'else':
        return result
    return [ 'if', test, result, ['cond'] + clauses[1:] ]


def rule_and( form ):
    # (and)            ->  #t
    # (and x)          ->  x
    # (and x rest...)  ->  (if x (and rest...) #f)
    forms = list( form[1:] )
    if not forms:
        return '#t'
    if len(forms) == 1:
        return forms[0]
    return [ 'if', forms[0], ['and'] + forms[1:], '#f' ]


def rule_or( form ):
    # (or)            ->  #f
    # (or x)          ->  x
    # (or x rest...)  ->  (let ((tmp x)) (if tmp tmp (or rest...)))
    #
    # The temporary is the entire difficulty.  Without it the rule reads
    # (if x x (or rest...)), which evaluates x twice, and `or` is not allowed
    # to do that: (or (print 7) 99) must print 7 exactly once.  So the rule
    # needs a name to hold the value in, and that name must be one the caller's
    # own code cannot collide with.  gensym is here for the rule writer's sake,
    # before any reader of this file has asked for a macro.
    forms = list( form[1:] )
    if not forms:
        return '#f'
    if len(forms) == 1:
        return forms[0]
    tmp = gensym()
    return [ 'let', [[tmp, forms[0]]],
             ['if', tmp, tmp, ['or'] + forms[1:]] ]


# The rule table.  It is an ordinary dict, which is the whole of the chapter:
# a table is data, and a program that can reach the data can add to it.
RULES = {
    'let':  rule_let,
    'cond': rule_cond,
    'and':  rule_and,
    'or':   rule_or,
}


def apply_macro( macro, form ):
    """Run a rule that is written in Lisp rather than in Python.

    The arguments handed over are the argument *trees*, unevaluated.  That is
    the only thing separating a macro from a procedure.  Binding parameters and
    running a body is what the machine does for every call it makes, so rather
    than reimplement it here, we ask the machine.
    """
    _, params, body, env = macro
    args  = list( form[1:] )
    local = Environment( parent=env, bindings=bind_params( params, args ) )
    return lEval( ['begin'] + body, local )


def apply_rule( rule, form ):
    if callable( rule ):                # a rule written in Python
        return rule( form )
    return apply_macro( rule, form )    # a rule written in Lisp


def define_macro( form ):
    # (define-macro (name . params) body...)
    #
    # The body is expanded before it is stored.  It has to be: a macro body is
    # ordinary Lisp, an author will reach for `let` inside one, and the machine
    # that will run it no longer knows what `let` is.
    spec   = form[1]
    name   = spec[0]
    params = list( spec[1:] )
    body   = [ expand(f) for f in form[2:] ]
    RULES[name] = ( VAL_CLOSURE, params, body, global_env )
    return '#f'


def is_rule_use( form ):
    return ( isinstance( form, list ) and form
             and isinstance( form[0], str ) and form[0] in RULES )


def expand( form ):
    """Rewrite a program until nothing but core forms is left.

    The core forms are the ones lEval still knows: quote, lambda, if, set!,
    begin, and application.  Everything else is a rule in RULES.
    """
    if not isinstance( form, list ) or not form:
        return form                          # an atom rewrites to itself

    if form[0] == 'define-macro':
        return define_macro( form )

    # Rewrite this node until its head is no longer a rule.  This is a loop and
    # not an `if`, because a rule may expand into another rule's form: `or`
    # expands into a `let`, and `let` expands into a lambda applied to its
    # inits.  Keep going until the head is something the machine can run.
    while is_rule_use( form ):
        form = apply_rule( RULES[ form[0] ], form )
        if not isinstance( form, list ) or not form:
            return form

    head = form[0]
    if head == 'quote':                      # (quote datum): the datum is data
        return form
    if head == 'lambda':                     # the parameters are names, not code
        return [ 'lambda', form[1] ] + [ expand(f) for f in form[2:] ]
    if head == 'set!':                       # the name is a name, not code
        return [ 'set!', form[1], expand( form[2] ) ]
    return [ expand(f) for f in form ]       # if / begin / application


# gensym is a rule writer's tool above, and a macro writer's tool here.  Same
# counter, same names, two different people reaching for it.
#
# It goes in through `set!` rather than into globalBindings, because the global
# environment copied that dict when it was built and has not looked at it since.
global_env.set( 'gensym', lambda args: gensym() )


# ---------------------------------------------------------------------------
# Helpers and demo
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


def run( expr ):
    """The pipeline, and it is two lines long.

    Every phase this book adds from here shows up in this function.
    """
    core   = expand( expr )
    result = lEval( core, global_env )

    print( '>>> ' + lisp_str( expr ) )
    if core != expr:
        print( '  = ' + lisp_str( core ) )
    print( '==> ' + lisp_str( result ) )
    print()


def main():
    print( '--- the language still has everything the machine gave up ---\n' )
    run( ['let', [['a', 3], ['b', 4]],
          ['+', ['*', 'a', 'a'], ['*', 'b', 'b']]] )           # 25
    run( ['cond', [['=', 1, 2], ['quote', 'no']],
                  [['<', 1, 2], ['quote', 'yes']],
                  ['else',      ['quote', 'fallback']]] )      # yes
    run( ['and', 1, 2] )                                       # 2
    run( ['and', '#f', 99] )                                   # #f
    run( ['or', '#f', 7] )                                     # 7

    print( "--- `and` short-circuits, and so the rewrite must too ---\n" )
    run( ['and', '#f', ['print', 99]] )                        # #f, 99 unprinted

    print( "--- why `or`'s rule needs a name you cannot type ---\n" )
    run( ['or', ['print', 7], 99] )                            # prints 7 ONCE

    print( '--- the table is data, so a program can add to it ---\n' )
    run( ['define-macro', ['when', 'test', '.', 'body'],
          ['list', ['quote', 'if'], 'test',
                   ['cons', ['quote', 'begin'], 'body'],
                   ['quote', '#f']]] )
    run( ['when', ['<', 1, 2], ['print', ['quote', 'yes']]] )  # yes
    run( ['when', ['>', 1, 2], ['print', ['quote', 'no']]] )   # #f, nothing printed

    print( '--- a macro that expands into a macro ---\n' )
    run( ['define-macro', ['my-if', 'test', 'a', 'b'],
          ['list', ['quote', 'cond'], ['list', 'test', 'a'],
                   ['list', ['quote', 'else'], 'b']]] )
    run( ['my-if', ['<', 1, 2], ['quote', 'first'], ['quote', 'second']] )

    print( '--- capture: the macro works until the caller picks the wrong name ---\n' )
    run( ['define-macro', ['swap!', 'a', 'b'],
          ['list', ['quote', 'let'],
                   ['list', ['list', ['quote', 'tmp'], 'a']],
                   ['list', ['quote', 'set!'], 'a', 'b'],
                   ['list', ['quote', 'set!'], 'b', ['quote', 'tmp']]]] )
    run( ['set!', 'x', 1] )
    run( ['set!', 'tmp', 2] )
    run( ['begin', ['swap!', 'x', 'tmp'], ['list', 'x', 'tmp']] )   # wanted (2 1)

    print( '--- gensym fixes it ---\n' )
    run( ['define-macro', ['swap2!', 'a', 'b'],
          ['let', [['g', ['gensym']]],
           ['list', ['quote', 'let'],
                    ['list', ['list', 'g', 'a']],
                    ['list', ['quote', 'set!'], 'a', 'b'],
                    ['list', ['quote', 'set!'], 'b', 'g']]]] )
    run( ['set!', 'x', 1] )
    run( ['set!', 'tmp', 2] )
    run( ['begin', ['swap2!', 'x', 'tmp'], ['list', 'x', 'tmp']] )  # (2 1)

    print( '--- the half gensym cannot fix ---\n' )
    run( ['define-macro', ['add1', 'n'],
          ['list', ['quote', '+'], 'n', 1]] )
    run( ['add1', 5] )                                         # 6
    run( ['let', [['+', '-']], ['add1', 5]] )                  # 4, every name fresh

    print( '--- and the machine is still the machine ---\n' )
    run( ['set!', 'countdown',
          ['lambda', ['n'], ['if', ['=', 'n', 0], 0,
                             ['countdown', ['-', 'n', 1]]]]] )
    run( ['countdown', 100000] )                               # 0, constant K


if __name__ == '__main__':
    main()
