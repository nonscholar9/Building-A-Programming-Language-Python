"""
IBAddresser - the first pass that makes the program FASTER rather than
safer, and the first one that has to earn its keep with a number.

Every pass so far has either changed what the program says (the expander) or
refused to let it through (the checker).  This one leaves the meaning exactly
as it found it and changes only how the machine will go looking for things.

The machine finds a variable by name.  `lookup` starts at the innermost scope,
asks whether the name is there, and walks outward until it is.  That is a
SEARCH, and the work it does depends on how deeply nested the variable is and
how many names sit beside it.  But for a local variable, everything that search
is about to discover is already visible in the source:

    (lambda (x) (lambda (y) (+ x y)))
                                ^
                                x is one frame out, slot 0.  Always.

So we work it out once, here, instead of every time the machine runs that line.
A variable that resolves to a lambda's parameter becomes an `Addressed` symbol
carrying (depth, index).  A variable that does not becomes nothing at all: it
stays a plain string, because it is a global, and the global scope is a place
anyone can add a name to while the program runs.  You can address what you can
see the shape of, and a parameter list has a shape.

    (depth, index)      depth = frames to walk outward, 0 = innermost
                        index = slot within that frame

WHERE IT SITS.  After the expander, before the checker:

    read -> expand -> ADDRESS -> analyze -> machine

Before the checker on purpose.  This pass rewrites the tree, and a pass that
rewrites the tree should have something standing between it and the machine.
The checker validates what actually runs, which is this pass's output, not the
program as it was written.

An `Addressed` symbol is a `str` subclass, so every pass downstream keeps
working without knowing this one exists: it hashes, compares and prints as its
own name.  The address rides along as an attribute for the machine to find.

Run with: python IBAddresser.py
"""

from IBCore     import lisp_str
from IBExpander import expand
from IBAnalyzer import analyze, LispError


# ---------------------------------------------------------------------------
# The addressed symbol
# ---------------------------------------------------------------------------
#
# Subclassing str is what keeps this pass invisible to everything downstream.
# The checker asks `isinstance( head, str )`, uses names as dict keys, and
# compares them against 'quote' and 'lambda'.  All of that still works, because
# an Addressed IS a str with the same characters.  It just knows one more thing
# about itself.

class Addressed( str ):
    """A variable that knows where it lives."""

    def __new__( cls, name, depth, index ):
        sym = super().__new__( cls, name )
        sym.depth = depth
        sym.index = index
        return sym

    def __repr__( self ):
        return f'{str(self)}@{self.depth}.{self.index}'


# ---------------------------------------------------------------------------
# Frame layout
# ---------------------------------------------------------------------------

def frame_names( params ):
    """The slots a parameter list declares, in order.

    A dotted list (first . rest) declares the named parameters and then the
    rest parameter, which holds whatever is left over as a list.  The dot marks
    the split; it is not itself a slot.  So the frame is the same size for
    every call, however many arguments arrive.
    """
    if '.' in params:
        dot = params.index( '.' )
        return list( params[:dot] ) + [ params[dot + 1] ]
    return list( params )


def resolve( name, scopes ):
    """Search the COMPILE-TIME scope stack, innermost first.

    This is the same walk `lookup` does at run time, done once, here, with the
    parameter lists standing in for the frames that do not exist yet.  Innermost
    first is what makes shadowing come out right: the nearest binding wins, and
    the ones further out are never reached.
    """
    for depth, names in enumerate( reversed( scopes ) ):
        if name in names:
            return depth, names.index( name )
    return None                                  # not lexical, so global


# ---------------------------------------------------------------------------
# The pass
# ---------------------------------------------------------------------------

def address( form, scopes=None ):
    """Rewrite every lexically bound variable into an Addressed symbol.

    Globals are left exactly as they are.  The meaning of the program does not
    change; only the amount of work the machine has to do to find things.
    """
    if scopes is None:
        scopes = []

    if isinstance( form, str ):                  # a variable reference
        slot = resolve( form, scopes )
        if slot is None:
            return form                          # global: leave it a plain str
        depth, index = slot
        return Addressed( form, depth, index )

    if not isinstance( form, list ) or not form:
        return form                              # a number, or ()

    head = form[0]

    if head == 'quote':                          # datum is data, do not walk in
        return form

    if head == 'lambda':                         # ['lambda', params, *body]
        inner = scopes + [ frame_names( form[1] ) ]
        return [ 'lambda', form[1] ] + [ address( f, inner ) for f in form[2:] ]

    # if, set!, begin and application all just walk their parts.  set! is not a
    # special case here: its target is a variable reference like any other, and
    # addressing it is exactly what lets an assignment write straight to a slot.
    return [ address( f, scopes ) for f in form ]


# ---------------------------------------------------------------------------
# What it did
# ---------------------------------------------------------------------------

def slots( form, found=None ):
    """Collect every addressed variable, for showing the pass its own work."""
    if found is None:
        found = []
    if isinstance( form, Addressed ):
        found.append( form )
    elif isinstance( form, list ) and form and form[0] != 'quote':
        for sub in form:
            slots( sub, found )
    return found


def globals_in( form, found=None ):
    """Every variable the pass could NOT address."""
    if found is None:
        found = []
    if isinstance( form, Addressed ):
        pass
    elif isinstance( form, str ):
        found.append( form )
    elif isinstance( form, list ) and form and form[0] != 'quote':
        head = form[0]
        parts = form[2:] if head == 'lambda' else form
        for sub in parts:
            globals_in( sub, found )
    return found


def main():
    def show( label, source ):
        core = expand( source )
        out  = address( core )
        local = [ repr(s) for s in slots( out ) ]
        print( f'  {label}' )
        print( f'     addressed  {" ".join(local) if local else "(none)"}' )

    print( '--- what the pass works out, once, before the machine runs ---\n' )
    show( '(lambda (x) (lambda (y) (+ x y)))',
          ['lambda', ['x'], ['lambda', ['y'], ['+', 'x', 'y']]] )
    show( '(let ((a 1) (b 2)) (+ a b))',
          ['let', [['a', 1], ['b', 2]], ['+', 'a', 'b']] )
    show( '(lambda (first . rest) rest)',
          ['lambda', ['first', '.', 'rest'], 'rest'] )
    show( '(lambda (x) (lambda (x) x))            ; the inner x shadows',
          ['lambda', ['x'], ['lambda', ['x'], 'x']] )
    show( "(lambda (n) (set! n (+ n 1)))          ; set! writes to a slot too",
          ['lambda', ['n'], ['set!', 'n', ['+', 'n', 1]]] )

    print( '\n--- and what it leaves alone, because it cannot see their shape ---\n' )
    prog = expand( ['lambda', ['x'], ['+', 'x', 'y']] )
    out  = address( prog )
    print( f'  (lambda (x) (+ x y))' )
    print( f'     addressed  {" ".join(repr(s) for s in slots(out))}' )
    print( f'     left free  {" ".join(globals_in(out))}' )

    print( '\n--- the checker still checks, and now it checks THIS ---\n' )
    for label, source in [
        ( '(square 5 99), addressed first',
          ['begin', ['set!', 'square', ['lambda', ['n'], ['*', 'n', 'n']]],
                    ['square', 5, 99]] ),
        ( 'a good program, addressed first',
          ['begin', ['set!', 'square', ['lambda', ['n'], ['*', 'n', 'n']]],
                    ['square', 5]] ),
    ]:
        try:
            analyze( address( expand( source ) ) )
            print( f'  quiet   {label}' )
        except LispError as e:
            print( f'  error   {label}:  {e}' )

    print( '\n--- the meaning is untouched: printing it back gives the source ---\n' )
    src  = ['lambda', ['x'], ['lambda', ['y'], ['+', 'x', 'y']]]
    core = expand( src )
    print( f'  before  {lisp_str( core )}' )
    print( f'  after   {lisp_str( address( core ) )}' )


if __name__ == '__main__':
    main()
