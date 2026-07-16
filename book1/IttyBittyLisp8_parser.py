"""
IttyBittyLisp8_parser -- An S-expression scanner and reader for the IttyBitty Lisp.

Turns a source string into the nested Python list AST that lEval (from
IttyBittyLisp1.py) evaluates directly.  Two stages, the same split real
compilers use:

    source string
        |
        v  Scanner        one character at a time -> a stream of tokens
    tokens: ( ) ' and atoms
        |
        v  read_object    recursive descent -> a nested Python list
    AST
        |
        v  lEval
    result value

Unlike a pad-the-parens-and-split tokenizer, the scanner reads the source one
character at a time.  For a Lisp that is a little more code than the trick
allows, but it is a real scanner: it is where you would add string literals,
line numbers for error messages, or any token whose pieces are not already
separated by spaces (see the challenges in Chapter 7).

Run with: python IttyBittyLisp8_parser.py
"""

# ---------------------------------------------------------------------------
# The scanner: a character cursor with a one-token lookahead
# ---------------------------------------------------------------------------

# Token kinds.  The structural tokens ( ) ' each stand alone; every name and
# number arrives as one ATOM whose text the reader classifies later.
EOF, LPAREN, RPAREN, QUOTE, ATOM = 'eof', '(', ')', "'", 'atom'

# A delimiter ends the atom currently being scanned.  Everything that is not a
# delimiter continues it, so the scanner needs no table of "symbol characters".
DELIMITERS = set( " \t\n\r()';" )


class Scanner:
    def __init__( self, source ):
        self._src  = source
        self._pos  = 0            # index of the next unread character
        self._mark = 0            # index where the current lexeme began
        self.consume()            # prime the one-token lookahead

    # ----- character level -----
    def _peekChar( self ):
        return self._src[self._pos] if self._pos < len( self._src ) else ''

    def _consumePast( self, charSet ):     # advance while IN charSet
        while self._peekChar() and self._peekChar() in charSet:
            self._pos += 1

    def _consumeUpTo( self, charSet ):     # advance while NOT in charSet
        while self._peekChar() and self._peekChar() not in charSet:
            self._pos += 1

    # ----- token level (this is what the reader talks to) -----
    def peek( self ):             # the current token's kind, not yet consumed
        return self._tok

    def lexeme( self ):           # the current token's source text
        return self._src[self._mark : self._pos]

    def consume( self ):          # advance to the next token
        self._skipSpaceAndComments()
        self._mark = self._pos
        ch = self._peekChar()
        if ch == '':
            self._tok = EOF
        elif ch == '(':
            self._pos += 1;  self._tok = LPAREN
        elif ch == ')':
            self._pos += 1;  self._tok = RPAREN
        elif ch == "'":
            self._pos += 1;  self._tok = QUOTE
        else:                                  # anything else begins an atom
            self._consumeUpTo( DELIMITERS )    # scan the run up to a delimiter
            self._tok = ATOM

    def _skipSpaceAndComments( self ):
        while True:
            self._consumePast( " \t\n\r" )
            if self._peekChar() != ';':        # a ';' comment runs to end of line
                return
            self._consumeUpTo( "\n" )


# ---------------------------------------------------------------------------
# The reader: recursive descent over the token stream
# ---------------------------------------------------------------------------

def read_object( scanner ):
    """Read one complete expression from the front of the token stream."""
    tok = scanner.peek()
    if tok == ATOM:
        text = scanner.lexeme()
        scanner.consume()
        return atom( text )
    elif tok == LPAREN:
        return read_list( scanner )
    elif tok == QUOTE:                         # 'expr  ->  (quote expr)
        scanner.consume()
        return [ 'quote', read_object( scanner ) ]
    elif tok == RPAREN:
        raise SyntaxError( 'unexpected )' )
    else:                                       # EOF
        raise SyntaxError( 'unexpected end of input' )


def read_list( scanner ):
    scanner.consume()                           # discard the opening '('
    result = []
    while scanner.peek() not in ( RPAREN, EOF ):
        result.append( read_object( scanner ) )
    if scanner.peek() == EOF:
        raise SyntaxError( 'unterminated list, expected )' )
    scanner.consume()                           # discard the closing ')'
    return result


def atom( text ):
    """Classify an atom's text as a Python int, or else a symbol (a string)."""
    try:
        return int( text )
    except ValueError:
        return text                             # a symbol -- a plain string


def parse( source ):
    scanner = Scanner( source )
    tree = read_object( scanner )
    if scanner.peek() != EOF:
        raise SyntaxError( 'unexpected trailing input' )
    return tree


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
    # Python list on purpose, to show the reader's output structure).
    if isinstance( val, list ):
        return '(' + ' '.join( lisp_str( x ) for x in val ) + ')'
    if callable( val ):
        return '#<primitive>'
    return str( val )


def scan_all( source ):
    # Drain a fresh scanner into a list of (kind, lexeme) pairs, so the chapter
    # can show the token stream the reader consumes.
    scanner = Scanner( source )
    tokens = []
    while scanner.peek() != EOF:
        tokens.append( ( scanner.peek(), scanner.lexeme() ) )
        scanner.consume()
    return tokens


def run( source ):
    print( f'  source:  {source}' )
    ast = parse( source )
    print( f'  ast:     {ast}' )
    print( f'  result:  {lisp_str( lEval( ast, global_env ) )}' )
    print()


def main():
    # Show the token stream for a non-trivial expression.
    src = "(if (= a 2) (+ a 1) (- a 1))"
    print( 'Scanner output (the token stream the reader consumes):' )
    print( f'  source:  {src}' )
    print( f'  tokens:  {scan_all( src )}' )
    print()

    # Show that the AST is identical to what the IttyBitty examples wrote by hand.
    print( 'Reader output (this is the AST lEval operates on):' )
    print( f'  source:  {src}' )
    print( f'  ast:     {parse( src )}' )
    print()

    # Full pipeline: source string -> parse -> lEval -> result.
    print( 'Full pipeline: source string -> parse -> lEval -> result' )
    global_env['a'] = 2
    run( "(+ 1 2)" )
    run( "(if (= a 2) (+ a 1) (- a 1))" )
    run( "(set! b (* 6 7))" )
    run( "b" )

    # Quote shorthand: 'x is reader syntax for (quote x).
    print( "Quote shorthand: 'x is reader syntax for (quote x)" )
    run( "'(a b c)" )
    run( "(quote (a b c))" )


if __name__ == '__main__':
    main()
