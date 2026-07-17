"""
ParserBase - the small reusable base for LL(1) recursive-descent parsing.

Everything a hand-written scanner and parser share, and nothing else.  You
subclass it once per language: a Lexer supplies the tokens (one method,
_scanNextToken), and a Parser supplies the grammar (one recursive-descent
method per production).  Book One's Lisp reader and Book Two's IttyBittyPython
front end are two subclasses of the same three classes here.

  * LexerBuffer - a cursor over the source text: peek a character, consume it,
    scan a run, remember where a lexeme began, and track line and column so an
    error can point at the spot.
  * LexerBase   - one token of lookahead on top of the buffer.  A subclass
    fills in _scanNextToken; everyone else calls peekToken / consume / getLexeme.
  * ParserBase  - the abstract parse(source) a concrete grammar implements.
  * ParseError  - a syntax error that renders as file (line, col) with a caret.

This is deliberately the minimal version.  A production parser reaches for
machinery we do not need, and which you can add when you do: backtracking (save
and restore the scanner to try another alternative), more than one token of
lookahead, and error recovery (resynchronising after a mistake instead of
stopping at the first).  LL(1) recursive descent needs none of it.  One token of
lookahead decides every step, and it never rewinds.
"""

from abc import ABC, abstractmethod


# ---------------------------------------------------------------------------
# LexerBuffer: a cursor over the source string
# ---------------------------------------------------------------------------

class LexerBuffer:
    def __init__( self ):
        self._filename  = ''
        self._source    = ''
        self._sourceLen = 0
        self._nextChar  = ''      # the character at _point, cached
        self._point     = 0       # index of the next unread character
        self._mark      = 0       # index where the current lexeme began
        self._lineNum   = 1

    def reset( self, source, filename='' ):
        self._filename  = filename
        self._source    = source
        self._sourceLen = len( source )
        self._nextChar  = source[0] if source else ''
        self._point     = 0
        self._mark      = 0
        self._lineNum   = 1

    def peekNextChar( self ):
        return self._nextChar

    def consume( self ):
        if self._nextChar == '':
            return
        if self._nextChar == '\n':
            self._lineNum += 1
        self._point += 1
        self._nextChar = ( self._source[self._point]
                           if self._point < self._sourceLen else '' )

    def consumePast( self, charSet ):
        """Advance over a run of characters that ARE in charSet."""
        while self._nextChar and self._nextChar in charSet:
            self.consume()

    def consumeUpTo( self, charSet ):
        """Advance over a run of characters that are NOT in charSet."""
        while self._nextChar and self._nextChar not in charSet:
            self.consume()

    def markStartOfLexeme( self ):
        self._mark = self._point

    def getLexeme( self ):
        return self._source[ self._mark : self._point ]

    # --- source position, for error messages ---

    def filename( self ):
        return self._filename

    def scanLineNum( self ):
        return self._lineNum

    def scanLinePos( self ):
        """Index of the first character of the current line."""
        return self._source.rfind( '\n', 0, self._point ) + 1

    def scanColNum( self ):
        return self._point - self.scanLinePos() + 1

    def scanLineTxt( self ):
        start = self.scanLinePos()
        end   = self._source.find( '\n', start )
        return self._source[start:] if end == -1 else self._source[start:end]


# ---------------------------------------------------------------------------
# LexerBase: one token of lookahead over the buffer
# ---------------------------------------------------------------------------

class LexerBase( ABC ):
    def __init__( self ):
        self.buffer = LexerBuffer()
        self._tok   = -1

    def reset( self, source, filename='' ):
        self.buffer.reset( source, filename )
        self.consume()                        # prime the one-token lookahead

    def peekToken( self ):
        return self._tok

    def consume( self ):
        self._tok = self._scanNextToken()

    def getLexeme( self ):
        return self.buffer.getLexeme()

    @abstractmethod
    def _scanNextToken( self ):
        """Scan past the next token, leaving the buffer with _mark at its first
        character and _point one past its last, and return the token's kind."""
        ...


# ---------------------------------------------------------------------------
# ParseError: a syntax error that points at the source
# ---------------------------------------------------------------------------

class ParseError( Exception ):
    def __init__( self, scanner, message ):
        buf = scanner.buffer
        super().__init__( self._format(
            buf.filename(), buf.scanLineNum(), buf.scanColNum(),
            buf.scanLineTxt(), message ) )

    @staticmethod
    def _format( filename, line, col, sourceLine, message ):
        caret = ' ' * ( col - 1 ) + '^'
        return ( f'Syntax Error: "{filename}" ({line},{col})\n'
                 f'{sourceLine}\n{caret}\n{message}' )


# ---------------------------------------------------------------------------
# ParserBase: the grammar a concrete parser implements
# ---------------------------------------------------------------------------

class ParserBase( ABC ):
    @abstractmethod
    def parse( self, source ):
        """Parse source text and return an AST."""
        ...
