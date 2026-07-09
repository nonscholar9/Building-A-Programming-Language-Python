"""
IttyBittyParser -- An S-expression parser for the IttyBitty Lisp evaluator.

Parses a source string into a Python list structure -- the same AST that
lEval (from IttyBittyLisp1.py) operates on directly.

The complete pipeline:

    source string
        |
        v  tokenize()
    flat list of token strings
        |
        v  read_from()
    nested Python list (AST)
        |
        v  lEval()
    result value

Run with: python IttyBittyParser.py
"""


# ---------------------------------------------------------------------------
# Tokenizer
# ---------------------------------------------------------------------------

def tokenize( source ):
    """Split source into a flat list of token strings.

    S-expressions have only two special characters: ( and ).  Padding them
    with spaces means Python's str.split() separates them from adjacent atoms
    cleanly -- no character-by-character scanning required.

    Semicolon comments (to end of line) are stripped first.
    """
    lines = []
    for line in source.splitlines():
        comment = line.find( ';' )
        if comment >= 0:
            line = line[:comment]
        lines.append( line )
    source = ' '.join( lines )
    return source.replace( '(', ' ( ' ).replace( ')', ' ) ' ).split()


# ---------------------------------------------------------------------------
# Reader
# ---------------------------------------------------------------------------

def read_from( tokens ):
    """Consume one complete expression from the front of the token list.

    Called recursively for nested lists.  The token list is mutated in place
    so each recursive call sees only the remaining tokens.
    """
    if not tokens:
        raise SyntaxError( 'unexpected end of input' )
    token = tokens.pop( 0 )
    if token == '(':
        result = []
        while tokens[0] != ')':
            result.append( read_from( tokens ) )
        tokens.pop( 0 )          # discard closing ')'
        return result
    elif token == ')':
        raise SyntaxError( 'unexpected )' )
    elif token == "'":           # quote shorthand: 'expr -> (quote expr)
        return [ 'quote', read_from( tokens ) ]
    else:
        return atom( token )


def atom( token ):
    """Convert a token string to a Python int, float, or string (symbol)."""
    try:
        return int( token )
    except ValueError:
        try:
            return float( token )
        except ValueError:
            return token             # symbol -- a plain Python string


def parse( source ):
    """Parse a source string into an AST.

    Quote shorthand is handled by tokenizing ' as its own token before
    read_from sees it.
    """
    tokens = tokenize( source ).copy()
    # Tokenize does not split ' from adjacent tokens -- handle it here.
    expanded = []
    for tok in tokens:
        if tok.startswith( "'" ) and len( tok ) > 1:
            expanded.append( "'" )
            expanded.append( tok[1:] )
        else:
            expanded.append( tok )
    return read_from( expanded )


# ---------------------------------------------------------------------------
# The minimal evaluator (from IttyBittyLisp1) to complete the pipeline
# ---------------------------------------------------------------------------

def lEval( expr, env ):
    if isinstance( expr, str ):
        return env[expr]
    elif not isinstance( expr, list ):
        return expr
    elif len( expr ) == 0:
        return []

    head = expr[0]

    if head == 'if':
        cond = lEval( expr[1], env )
        return lEval( expr[2] if cond else expr[3], env )

    elif head == 'begin':
        for sub in expr[1:-1]:
            lEval( sub, env )
        return lEval( expr[-1], env )

    elif head == 'set!':
        var, valExpr = expr[1:]
        val = lEval( valExpr, env )
        env[var] = val
        return val

    elif head == 'quote':
        return expr[1]

    fn, *args = [ lEval( sub, env ) for sub in expr ]
    return fn( args )


global_env = {
    '+':  lambda args: args[0] + args[1],
    '-':  lambda args: args[0] - args[1],
    '*':  lambda args: args[0] * args[1],
    '=':  lambda args: 1 if args[0] == args[1] else 0,
    '<':  lambda args: 1 if args[0] <  args[1] else 0,
}


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def lisp_str( val ):
    # Render a value in Lisp surface syntax (the `ast` line below is left as a
    # Python list on purpose, to show the parser's output structure).
    if isinstance( val, list ):
        return '(' + ' '.join( lisp_str( x ) for x in val ) + ')'
    if callable( val ):
        return '#<primitive>'
    return str( val )


def run( source ):
    print( f'  source:  {source}' )
    ast = parse( source )
    print( f'  ast:     {ast}' )
    result = lEval( ast, global_env )
    print( f'  result:  {lisp_str( result )}' )
    print()


def main():
    # Show tokenization of a non-trivial expression
    src = "(if (= a 2) (+ a 1) (- a 1))"
    print( 'Tokenizer output:' )
    print( f'  source:  {src}' )
    print( f'  tokens:  {tokenize( src )}' )
    print()

    # Show that the AST is identical to what the IttyBitty examples wrote by hand
    print( 'Parser output (this is the AST lEval operates on):' )
    print( f'  source:  {src}' )
    print( f'  ast:     {parse( src )}' )
    print()

    # Full pipeline
    print( 'Full pipeline: source string -> parse -> lEval -> result' )
    global_env['a'] = 2
    run( "(+ 1 2)" )
    run( "(if (= a 2) (+ a 1) (- a 1))" )
    run( "(set! b (* 6 7))" )
    run( "b" )

    # quote shorthand
    print( "Quote shorthand: 'x is reader syntax for (quote x)" )
    run( "'(a b c)" )
    run( "(quote (a b c))" )


if __name__ == '__main__':
    main()
