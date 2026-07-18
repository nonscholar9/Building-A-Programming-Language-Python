"""
IttyBittyPythonParser - the front end for IttyBittyPython, on the ParserBase.

A Lexer (tokens) and a Parser (grammar), each a subclass of the pared-down
ParserBase.  Together they turn IttyBittyPython source text into an AST; a later
pass lowers that AST onto the machine.  ("IttyBittyPython", never bare "Python":
the host we write it in is Python too.)

The grammar is examples/book2/IttyBittyPython.ebnf, and every parse method below
is that grammar's matching production run through one mechanical rule:

    "t"        -> self._expect(T)
    B          -> self._parseB()
    a b ...    -> statements in sequence
    a | b      -> if self._peek() in FIRST(a): ... elif ...
    [ a ]      -> if self._peek() in FIRST(a): ...
    a*         -> while self._peek() in FIRST(a): ...
    a+         -> once, then the while

The one idea the Lisp reader never needed is in the Lexer: IttyBittyPython's
blocks are significant whitespace, so the scanner keeps an indent stack and
emits INDENT and DEDENT tokens the source never contained.

Run with: python IttyBittyPythonParser.py
"""

import string
from ParserBase import LexerBase, ParserBase, ParseError

_NAME_START = string.ascii_letters + '_'
_NAME_REST  = string.ascii_letters + string.digits + '_'
_DIGITS     = string.digits


# ---------------------------------------------------------------------------
# The scanner: characters into tokens, with an indent stack for the layout
# ---------------------------------------------------------------------------

class Lexer( LexerBase ):
    ( EOF_TOK, NEWLINE_TOK, INDENT_TOK, DEDENT_TOK,
      NAME_TOK, INTEGER_TOK,
      DEF_TOK, IF_TOK, ELIF_TOK, ELSE_TOK, WHILE_TOK, RETURN_TOK, PASS_TOK,
      AND_TOK, OR_TOK, NOT_TOK,
      PLUS_TOK, MINUS_TOK, STAR_TOK, SLASH_TOK, PERCENT_TOK,
      EQEQ_TOK, NOTEQ_TOK, LT_TOK, GT_TOK, LE_TOK, GE_TOK,
      ASSIGN_TOK, LPAREN_TOK, RPAREN_TOK, COLON_TOK, COMMA_TOK,
      YIELD_TOK ) = range( 33 )

    KEYWORDS = {
        'def': DEF_TOK, 'if': IF_TOK, 'elif': ELIF_TOK, 'else': ELSE_TOK,
        'while': WHILE_TOK, 'return': RETURN_TOK, 'pass': PASS_TOK,
        'and': AND_TOK, 'or': OR_TOK, 'not': NOT_TOK, 'yield': YIELD_TOK,
    }
    _SINGLE = {
        '+': PLUS_TOK, '-': MINUS_TOK, '*': STAR_TOK, '/': SLASH_TOK,
        '%': PERCENT_TOK, '(': LPAREN_TOK, ')': RPAREN_TOK,
        ':': COLON_TOK, ',': COMMA_TOK,
    }

    def __init__( self ):
        super().__init__()
        self._indents     = [0]      # a stack of indentation widths
        self._pending     = []       # tokens ready to emit (queued DEDENTs, EOF)
        self._at_line_start = True

    def _scanNextToken( self ):
        if self._pending:
            return self._pending.pop( 0 )

        if self._at_line_start:
            self._at_line_start = False
            tok = self._begin_line()
            if tok is not None:
                return tok               # NEWLINE-free INDENT/DEDENT/EOF handling

        return self._scan_inline_token()

    # -- resolve indentation at the first non-blank line, emitting layout tokens
    def _begin_line( self ):
        col = self._skip_blank_lines_and_measure()
        if col is None:                  # end of input: unwind to column 0
            while len( self._indents ) > 1:
                self._indents.pop()
                self._pending.append( Lexer.DEDENT_TOK )
            self._pending.append( Lexer.EOF_TOK )
            return self._pending.pop( 0 )

        top = self._indents[-1]
        if col > top:
            self._indents.append( col )
            return Lexer.INDENT_TOK
        if col < top:
            while len( self._indents ) > 1 and col < self._indents[-1]:
                self._indents.pop()
                self._pending.append( Lexer.DEDENT_TOK )
            if self._indents[-1] != col:
                raise ParseError( self, 'unindent does not match any outer level' )
            return self._pending.pop( 0 )
        return None                      # col == top: no layout token, scan on

    def _skip_blank_lines_and_measure( self ):
        buf = self.buffer
        while True:
            n = 0
            while buf.peekNextChar() == ' ':
                buf.consume(); n += 1
            ch = buf.peekNextChar()
            if ch == '#':
                buf.consumeUpTo( '\n' )
                ch = buf.peekNextChar()
            if ch == '':
                return None              # end of input
            if ch == '\n':
                buf.consume()            # a blank / comment-only line: skip it
                continue
            return n

    # -- one ordinary token, or the NEWLINE that ends the logical line
    def _scan_inline_token( self ):
        buf = self.buffer
        buf.consumePast( ' \t' )
        if buf.peekNextChar() == '#':
            buf.consumeUpTo( '\n' )

        ch = buf.peekNextChar()
        if ch == '' or ch == '\n':
            if ch == '\n':
                buf.consume()
            self._at_line_start = True
            return Lexer.NEWLINE_TOK

        buf.markStartOfLexeme()

        if ch in _NAME_START:
            buf.consumePast( _NAME_REST )
            return Lexer.KEYWORDS.get( self.getLexeme(), Lexer.NAME_TOK )
        if ch in _DIGITS:
            buf.consumePast( _DIGITS )
            return Lexer.INTEGER_TOK
        if ch == '=':
            buf.consume()
            if buf.peekNextChar() == '=':
                buf.consume(); return Lexer.EQEQ_TOK
            return Lexer.ASSIGN_TOK
        if ch == '!':
            buf.consume()
            if buf.peekNextChar() == '=':
                buf.consume(); return Lexer.NOTEQ_TOK
            raise ParseError( self, "'=' expected after '!'" )
        if ch == '<':
            buf.consume()
            if buf.peekNextChar() == '=':
                buf.consume(); return Lexer.LE_TOK
            return Lexer.LT_TOK
        if ch == '>':
            buf.consume()
            if buf.peekNextChar() == '=':
                buf.consume(); return Lexer.GE_TOK
            return Lexer.GT_TOK
        if ch in Lexer._SINGLE:
            buf.consume()
            return Lexer._SINGLE[ch]
        raise ParseError( self, f'unexpected character: {ch!r}' )


# ---------------------------------------------------------------------------
# Names for the tokens, for error messages
# ---------------------------------------------------------------------------

_TOKEN_NAME = {
    Lexer.EOF_TOK: 'end of input', Lexer.NEWLINE_TOK: 'a newline',
    Lexer.INDENT_TOK: 'an indent', Lexer.DEDENT_TOK: 'a dedent',
    Lexer.NAME_TOK: 'a name', Lexer.INTEGER_TOK: 'an integer',
    Lexer.DEF_TOK: "'def'", Lexer.IF_TOK: "'if'", Lexer.ELIF_TOK: "'elif'",
    Lexer.ELSE_TOK: "'else'", Lexer.WHILE_TOK: "'while'",
    Lexer.RETURN_TOK: "'return'", Lexer.PASS_TOK: "'pass'",
    Lexer.LPAREN_TOK: "'('", Lexer.RPAREN_TOK: "')'",
    Lexer.COLON_TOK: "':'", Lexer.COMMA_TOK: "','", Lexer.ASSIGN_TOK: "'='",
}

_BINOP_NAME = { Lexer.PLUS_TOK: '+', Lexer.MINUS_TOK: '-', Lexer.STAR_TOK: '*',
                Lexer.SLASH_TOK: '/', Lexer.PERCENT_TOK: '%' }
_COMP_NAME  = { Lexer.EQEQ_TOK: '==', Lexer.NOTEQ_TOK: '!=', Lexer.LT_TOK: '<',
                Lexer.GT_TOK: '>', Lexer.LE_TOK: '<=', Lexer.GE_TOK: '>=' }

_FIRST_EXPR = ( Lexer.NAME_TOK, Lexer.INTEGER_TOK, Lexer.LPAREN_TOK,
                Lexer.PLUS_TOK, Lexer.MINUS_TOK, Lexer.NOT_TOK )

# FIRST(statement) = FIRST(simple_stmt) | FIRST(compound_stmt).  Every "*" and
# "+" over statements tests this, exactly as the mapping table prescribes.
_FIRST_STMT = _FIRST_EXPR + ( Lexer.RETURN_TOK, Lexer.PASS_TOK, Lexer.YIELD_TOK,
                              Lexer.IF_TOK, Lexer.WHILE_TOK, Lexer.DEF_TOK )


# ---------------------------------------------------------------------------
# The parser: one method per production, translated by the mechanical rule
# ---------------------------------------------------------------------------

class Parser( ParserBase ):
    def __init__( self ):
        self._scanner = Lexer()

    # -- helpers over the scanner
    def _peek( self ):
        return self._scanner.peekToken()

    def _next( self ):
        self._scanner.consume()

    def _expect( self, tok ):
        if self._scanner.peekToken() != tok:
            raise ParseError( self._scanner, f'{_TOKEN_NAME.get(tok, tok)} expected' )
        lex = self._scanner.getLexeme()
        self._scanner.consume()
        return lex

    # file_input ::= statement* ENDMARKER
    def parse( self, source, filename='' ):
        self._scanner.reset( source, filename )
        body = []
        while self._peek() in _FIRST_STMT:               # statement*
            body.append( self._parse_statement() )
        if self._peek() != Lexer.EOF_TOK:                # ENDMARKER
            raise ParseError( self._scanner, 'a statement or end of input expected' )
        return ( 'module', body )

    # statement ::= simple_stmt | compound_stmt
    def _parse_statement( self ):
        if self._peek() in ( Lexer.IF_TOK, Lexer.WHILE_TOK, Lexer.DEF_TOK ):
            return self._parse_compound()
        return self._parse_simple()

    # simple_stmt ::= (assign_or_expr | return_stmt | pass_stmt | yield_stmt) NEWLINE
    def _parse_simple( self ):
        tok = self._peek()
        if tok == Lexer.RETURN_TOK:
            node = self._parse_return()
        elif tok == Lexer.YIELD_TOK:
            node = self._parse_yield()
        elif tok == Lexer.PASS_TOK:
            self._next()
            node = ( 'pass', )
        else:
            node = self._parse_assign_or_expr()
        self._expect( Lexer.NEWLINE_TOK )
        return node

    # return_stmt ::= "return" [expression]
    def _parse_return( self ):
        self._expect( Lexer.RETURN_TOK )
        value = self._parse_expression() if self._peek() in _FIRST_EXPR else None
        return ( 'return', value )

    # yield_stmt ::= "yield" expression
    def _parse_yield( self ):
        self._expect( Lexer.YIELD_TOK )
        return ( 'yield', self._parse_expression() )

    # assign_or_expr ::= expression ["=" expression]
    def _parse_assign_or_expr( self ):
        left = self._parse_expression()
        if self._peek() == Lexer.ASSIGN_TOK:
            self._next()
            right = self._parse_expression()
            if left[0] != 'name':
                raise ParseError( self._scanner, 'cannot assign to this expression' )
            return ( 'assign', left[1], right )
        return ( 'expr', left )

    # compound_stmt ::= if_stmt | while_stmt | funcdef
    def _parse_compound( self ):
        if self._peek() == Lexer.IF_TOK:
            return self._parse_if()
        if self._peek() == Lexer.WHILE_TOK:
            return self._parse_while()
        return self._parse_def()

    # if_stmt ::= "if" expression ":" suite ("elif" expression ":" suite)*
    #             ["else" ":" suite]
    def _parse_if( self ):
        self._expect( Lexer.IF_TOK )
        test = self._parse_expression()
        self._expect( Lexer.COLON_TOK )
        body = self._parse_suite()
        elifs = []
        while self._peek() == Lexer.ELIF_TOK:
            self._next()
            t = self._parse_expression()
            self._expect( Lexer.COLON_TOK )
            elifs.append( ( t, self._parse_suite() ) )
        orelse = None
        if self._peek() == Lexer.ELSE_TOK:
            self._next()
            self._expect( Lexer.COLON_TOK )
            orelse = self._parse_suite()
        return ( 'if', test, body, elifs, orelse )

    # while_stmt ::= "while" expression ":" suite
    def _parse_while( self ):
        self._expect( Lexer.WHILE_TOK )
        test = self._parse_expression()
        self._expect( Lexer.COLON_TOK )
        return ( 'while', test, self._parse_suite() )

    # funcdef ::= "def" NAME "(" [parameter_list] ")" ":" suite
    # parameter_list ::= NAME ("," NAME)*
    def _parse_def( self ):
        self._expect( Lexer.DEF_TOK )
        name = self._expect( Lexer.NAME_TOK )
        self._expect( Lexer.LPAREN_TOK )
        params = []
        if self._peek() == Lexer.NAME_TOK:
            params.append( self._expect( Lexer.NAME_TOK ) )
            while self._peek() == Lexer.COMMA_TOK:
                self._next()
                params.append( self._expect( Lexer.NAME_TOK ) )
        self._expect( Lexer.RPAREN_TOK )
        self._expect( Lexer.COLON_TOK )
        return ( 'def', name, params, self._parse_suite() )

    # suite ::= NEWLINE INDENT statement+ DEDENT
    def _parse_suite( self ):
        self._expect( Lexer.NEWLINE_TOK )
        self._expect( Lexer.INDENT_TOK )
        body = [ self._parse_statement() ]               # "+": once...
        while self._peek() in _FIRST_STMT:               # ...then the while
            body.append( self._parse_statement() )
        self._expect( Lexer.DEDENT_TOK )
        return body

    # -- expressions, low precedence to high --

    def _parse_expression( self ):                       # expression ::= or_test
        return self._parse_or()

    def _parse_or( self ):        # or_test ::= and_test ("or" and_test)*
        node = self._parse_and()
        while self._peek() == Lexer.OR_TOK:
            self._next()
            node = ( 'binop', 'or', node, self._parse_and() )
        return node

    def _parse_and( self ):       # and_test ::= not_test ("and" not_test)*
        node = self._parse_not()
        while self._peek() == Lexer.AND_TOK:
            self._next()
            node = ( 'binop', 'and', node, self._parse_not() )
        return node

    def _parse_not( self ):       # not_test ::= "not" not_test | comparison
        if self._peek() == Lexer.NOT_TOK:
            self._next()
            return ( 'unary', 'not', self._parse_not() )
        return self._parse_comparison()

    def _parse_comparison( self ):   # comparison ::= sum [comp_op sum]
        node = self._parse_sum()
        if self._peek() in _COMP_NAME:
            op = _COMP_NAME[ self._peek() ]
            self._next()
            node = ( 'binop', op, node, self._parse_sum() )
        return node

    def _parse_sum( self ):       # sum ::= term (("+" | "-") term)*
        node = self._parse_term()
        while self._peek() in ( Lexer.PLUS_TOK, Lexer.MINUS_TOK ):
            op = _BINOP_NAME[ self._peek() ]
            self._next()
            node = ( 'binop', op, node, self._parse_term() )
        return node

    def _parse_term( self ):      # term ::= factor (("*" | "/" | "%") factor)*
        node = self._parse_factor()
        while self._peek() in ( Lexer.STAR_TOK, Lexer.SLASH_TOK, Lexer.PERCENT_TOK ):
            op = _BINOP_NAME[ self._peek() ]
            self._next()
            node = ( 'binop', op, node, self._parse_factor() )
        return node

    def _parse_factor( self ):    # factor ::= ("+" | "-") factor | call
        if self._peek() in ( Lexer.PLUS_TOK, Lexer.MINUS_TOK ):
            op = _BINOP_NAME[ self._peek() ]
            self._next()
            return ( 'unary', op, self._parse_factor() )
        return self._parse_call()

    def _parse_call( self ):      # call ::= atom ("(" [argument_list] ")")*
        node = self._parse_atom()
        while self._peek() == Lexer.LPAREN_TOK:
            self._next()
            args = self._parse_arguments()
            self._expect( Lexer.RPAREN_TOK )
            node = ( 'call', node, args )
        return node

    # argument_list ::= expression ("," expression)*   (optional inside the call)
    def _parse_arguments( self ):
        args = []
        if self._peek() in _FIRST_EXPR:
            args.append( self._parse_expression() )
            while self._peek() == Lexer.COMMA_TOK:
                self._next()
                args.append( self._parse_expression() )
        return args

    def _parse_atom( self ):      # atom ::= NAME | INTEGER | "(" expression ")"
        tok = self._peek()
        if tok == Lexer.NAME_TOK:
            return ( 'name', self._expect( Lexer.NAME_TOK ) )
        if tok == Lexer.INTEGER_TOK:
            return ( 'num', int( self._expect( Lexer.INTEGER_TOK ) ) )
        if tok == Lexer.LPAREN_TOK:
            self._next()
            node = self._parse_expression()
            self._expect( Lexer.RPAREN_TOK )
            return node
        raise ParseError( self._scanner, 'a name, an integer, or ( expected' )


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def pp( node, indent=0 ):
    pad = '  ' * indent
    if isinstance( node, tuple ) and node and isinstance( node[0], str ):
        head = node[0]
        if head in ( 'name', 'num', 'pass' ):
            return pad + repr( node )
        lines = [ pad + '(' + head ]
        for part in node[1:]:
            lines.append( pp( part, indent + 1 ) )
        return '\n'.join( lines ) + ' )'
    if isinstance( node, tuple ):                    # an (elif-test, body) pair
        lines = [ pad + '(clause' ]
        for part in node:
            lines.append( pp( part, indent + 1 ) )
        return '\n'.join( lines ) + ' )'
    if isinstance( node, list ):
        if not node:
            return pad + '[]'
        return '\n'.join( pp( x, indent ) for x in node )
    return pad + repr( node )


def main():
    factorial = (
        "def factorial(n):\n"
        "    if n == 0:\n"
        "        return 1\n"
        "    return n * factorial(n - 1)\n"
        "\n"
        "print(factorial(5))\n"
    )
    gcd = (
        "def gcd(a, b):\n"
        "    while b != 0:\n"
        "        t = b\n"
        "        b = a % b\n"
        "        a = t\n"
        "    return a\n"
        "print(gcd(48, 36))\n"
    )
    grades = (
        "def grade(score):\n"
        "    if score >= 90:\n"
        "        return 1\n"
        "    elif score >= 80:\n"
        "        return 2\n"
        "    else:\n"
        "        return 3\n"
    )

    parser = Parser()
    for label, src in [ ('factorial', factorial), ('gcd', gcd), ('grade', grades) ]:
        print( f'=== {label} ===' )
        print( pp( parser.parse( src ) ) )
        print()

    # Structure checks (parsing is right, not just non-crashing).
    fac = parser.parse( factorial )
    assert fac[0] == 'module'
    d = fac[1][0]
    assert d[0] == 'def' and d[1] == 'factorial' and d[2] == ['n'], d
    assert len( d[3] ) == 2, 'def body should be: the if, and the return'

    # Precedence: 1 + 2 * 3 nests the * under the +.
    e = parser.parse( "x = 1 + 2 * 3\n" )[1][0]
    assert e == ( 'assign', 'x',
                  ( 'binop', '+', ('num', 1),
                    ('binop', '*', ('num', 2), ('num', 3)) ) ), e

    # Deep nesting exercises multi-level INDENT/DEDENT.
    nested = ( "def f(n):\n"
               "    while n > 0:\n"
               "        if n == 1:\n"
               "            return n\n"
               "        n = n - 1\n"
               "    return 0\n" )
    parser.parse( nested )
    print( 'structure checks passed.\n' )

    print( '--- a syntax error points at line and column ---\n' )
    try:
        parser.parse( "x = 2 * * 3\n" )               # a stray operator
    except ParseError as e:
        print( e )


if __name__ == '__main__':
    main()
