"""
IttyBittyAnalyzer - a checker that runs before the machine does, and finds out
by building it exactly how far such a checker can get.

The introduction admitted the machine checks nothing: hand it a broken program
and Python's own errors come up through the floor.  This is the pass a real
front end runs first, to catch the break and report it as an error in *our*
language instead.  It is a tree walk in three layers of rising ambition, and
the third layer walks straight into a wall that is worth seeing from the inside.

Unlike the expander, this is not a phase every later program runs through.  The
machine still runs unchecked; a linter is a tool you point at a program, not a
link in the chain that evaluates it.  So this file stands on its own.  It runs
AFTER the expander, though, so the only forms it ever meets are the core forms
the machine knows: quote, lambda, if, set!, begin, and application.  The sugar
is already gone.

Run with: python IttyBittyAnalyzer.py
"""

from IttyBittyExpander import expand


class LispError( Exception ):
    """A complaint phrased in our language, not a Python traceback."""


# ---------------------------------------------------------------------------
# Layer 1: shapes.  Entirely static, genuinely useful, and it never needs to
# know a single thing about a value.  A form either has a shape that can mean
# something or it does not.
# ---------------------------------------------------------------------------

def check_shapes( form ):
    if not isinstance( form, list ):
        return                                   # an atom is always well shaped
    if not form:
        raise LispError( 'empty application: ()' )

    head = form[0]

    if head == 'quote':                          # (quote datum): datum is data
        if len(form) != 2:
            raise LispError( f'quote: expected 1 datum, found {len(form) - 1}' )
        return                                   # do not walk into the datum

    if head == 'if':
        if len(form) != 4:
            n = len(form) - 1
            raise LispError( 'if: expected a test and two branches, '
                             f'found {n} part' + ('' if n == 1 else 's') )

    elif head == 'set!':
        if len(form) != 3:
            raise LispError( 'set!: expected a name and a value, '
                             f'found {len(form) - 1} parts' )
        if not isinstance( form[1], str ):
            raise LispError( f'set!: target is not a name: {form[1]}' )

    elif head == 'lambda':
        if len(form) < 3:
            raise LispError( 'lambda: expected a parameter list and a body' )
        params = form[1]
        if not isinstance( params, list ):
            raise LispError( f'lambda: parameter list is not a list: {params}' )
        names = [ p for p in params if p != '.' ]
        if len(names) != len(set(names)):
            raise LispError( f'lambda: a parameter is named twice in {params}' )

    for sub in form[1:]:
        check_shapes( sub )


# ---------------------------------------------------------------------------
# Layer 2: arity.  This one works, and then it stops working, and where it
# stops is the whole point.  We can check a call only when we can see the
# lambda it calls.  A closure hides the lambda, and the checker goes quiet.
# ---------------------------------------------------------------------------

def arity_of( params ):
    # (min, max); max is None when a rest parameter makes the call variadic.
    if '.' in params:
        return ( params.index('.'), None )
    return ( len(params), len(params) )


def check_arity( form, known ):
    """`known` maps a name to a parameter list, for the lambdas we can see.

    It is updated as we move down a body, so that a `set!` earlier in the body
    is visible to the calls that come after it.
    """
    if not isinstance( form, list ) or not form:
        return
    head = form[0]

    if head == 'quote':
        return
    if head == 'lambda':
        for sub in form[2:]:
            check_arity( sub, dict(known) )      # a body gets its own scope
        return
    if head == 'set!':
        name, value = form[1], form[2]
        check_arity( value, known )
        # We learn an arity only when the value is a lambda sitting right here.
        if isinstance( value, list ) and value and value[0] == 'lambda':
            known[name] = value[1]
        return

    if isinstance( head, str ) and head in known:
        lo, hi = arity_of( known[head] )
        n = len(form) - 1
        if n < lo or (hi is not None and n > hi):
            want = str(lo) if hi == lo else f'{lo} or more' if hi is None \
                   else f'{lo} to {hi}'
            noun = 'argument' if want == '1' else 'arguments'
            raise LispError( f'{head}: expected {want} {noun}, got {n}' )

    for sub in form[1:]:
        check_arity( sub, known )


# ---------------------------------------------------------------------------
# Layer 3: types.  We catch the error we can see whole, and go silent the
# instant either side of it is a name.  There is nothing to check against.
# ---------------------------------------------------------------------------

_NUMERIC = { '+', '-', '*', '/', '%', '<', '>', '<=', '>=', '=' }

def check_types( form ):
    if not isinstance( form, list ) or not form:
        return
    head = form[0]
    if head == 'quote':
        return
    if isinstance( head, str ) and head in _NUMERIC:
        for arg in form[1:]:
            # We can judge only what is written out in full.  A quoted symbol
            # is a non-number we can see; a variable or a call, we cannot.
            if isinstance( arg, list ) and arg and arg[0] == 'quote':
                raise LispError( f"{head}: argument is not a number: '{arg[1]}" )
    for sub in form[1:]:
        check_types( sub )


def analyze( form ):
    """Run all three layers.  Returns the form unchanged; an analyzer inspects,
    it does not rewrite.  Raises LispError on the first problem it can prove."""
    check_shapes( form )
    check_arity( form, {} )
    check_types( form )
    return form


# ---------------------------------------------------------------------------
# What it catches, and where it goes quiet
# ---------------------------------------------------------------------------

def main():
    def check( label, source ):
        try:
            analyze( expand( source ) )
            print( f'  quiet   {label}' )
        except LispError as e:
            print( f'  error   {label}:  {e}' )

    print( '--- shapes: caught, every one, with nothing but the tree ---\n' )
    check( '(if #t)',          ['if', '#t'] )
    check( '(set! 5 1)',       ['set!', 5, 1] )
    check( '(lambda x x)',     ['lambda', 'x', 'x'] )
    check( '(lambda (a a) a)', ['lambda', ['a', 'a'], 'a'] )

    print( '\n--- arity: caught while the lambda is in view... ---\n' )
    check( '(square 5 99)',
           ['begin', ['set!', 'square', ['lambda', ['x'], ['*', 'x', 'x']]],
                     ['square', 5, 99]] )

    print( '\n--- ...and quiet the moment a closure hides it ---\n' )
    check( '((make-adder 3) 10)',
           ['begin', ['set!', 'make-adder',
                      ['lambda', ['n'], ['lambda', ['x'], ['+', 'x', 'n']]]],
                     [['make-adder', 3], 10]] )

    print( '\n--- types: caught when written whole, mute when a name hides it ---\n' )
    check( "(+ 'foo 1)", ['+', ['quote', 'foo'], 1] )
    check( '(+ x 1)',    ['begin', ['set!', 'x', 5], ['+', 'x', 1]] )

    print( '\n--- and a program with nothing wrong draws no complaint ---\n' )
    check( 'factorial',
           ['begin',
            ['set!', 'fact', ['lambda', ['n'],
                              ['if', ['=', 'n', 0], 1,
                               ['*', 'n', ['fact', ['-', 'n', 1]]]]]],
            ['fact', 5]] )


if __name__ == '__main__':
    main()
