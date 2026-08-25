"""
ParserBase - the small reusable base for LL(1) recursive-descent parsing.

Everything a hand-written scanner and parser share, and nothing else.  You
subclass it once per language: a Scanner supplies the tokens (one method,
_scanNextToken), and a Parser supplies the grammar (one recursive-descent
method per production).  This is the general-purpose one: it knows nothing
about any particular language, and it carries what a real front end wants
anyway, including errors that point at a file, line and column.  Three
languages subclass it.  IB_Reader.py reads Lisp, and is the measure of how
little a subclass can be: a parenthesised program states its own tree, so the
part that is Lisp's alone is a handful of lines.  IB_Arith.py parses infix
arithmetic, the parsing chapter's worked example.  miniPythonParser.py is the
mini-Python front end, where the source states nothing and the subclass has to
work all of it out.  All three hand their trees to the same Lisp back end.

  * ScannerBuffer - a cursor over the source text: peek a character, consume it,
    insist on one the grammar requires, scan a run, remember where a lexeme
    began, and track line and column so an error can point at the spot.
  * ScannerBase   - one token of lookahead on top of the buffer.  A subclass
    fills in _scanNextToken; everyone else calls peekToken / consumeToken /
    expectToken / getLexeme.  The two cursors are the same shape one size apart.
  * ParserBase  - the abstract parse(source) a concrete grammar implements.
  * ParseError  - a syntax error that renders as file (line, col) with a caret.

For a language that LL(1) can parse, nothing here is missing.  What is absent
is absent deliberately.  A fuller parser reaches for machinery we do not need,
and which you can add when you do: backtracking (save and restore the scanner
to try another alternative), more than one token of lookahead, and error
recovery (resynchronising after a mistake instead of stopping at the first).
Recursive descent needs none of it.  One token of lookahead decides every step,
and it never rewinds.
"""

from abc import ABC, abstractmethod


# ---------------------------------------------------------------------------
# ScannerBuffer: a cursor over the source string
# ---------------------------------------------------------------------------

class ScannerBuffer:
  def __init__(self):
    self._filename  = ''
    self._source    = ''
    self._sourceLen = 0
    self._nextChar  = ''      # the character at _point, cached
    self._point     = 0       # index of the next unread character
    self._mark      = 0       # index where the current lexeme began
    self._lineNum   = 1

  def reset(self, source, filename=''):
    self._filename  = filename
    self._source    = source
    self._sourceLen = len(source)
    self._nextChar  = source[:1]
    self._point     = 0
    self._mark      = 0
    self._lineNum   = 1

  def peekChar(self):
    return self._nextChar

  def consumeChar(self):
    if self._nextChar == '':
      return
    if self._nextChar == '\n':
      self._lineNum += 1
    self._point += 1
    self._nextChar = (
        self._source[self._point]
        if self._point < self._sourceLen
        else '')

  def expectChar(self, charSet, message=None):
    """Consume the next character, which
       the grammar says must be in
       charSet.  Refuse anything else."""
    if (not self._nextChar
        or self._nextChar not in charSet):
      raise ParseError(self, message or
          f'{charSet!r} expected')
    self.consumeChar()

  def consumePast(self, charSet):
    """Advance over a run of characters
       that ARE in charSet."""
    while (self._nextChar
            and self._nextChar in charSet):
      self.consumeChar()

  def consumeUpTo(self, charSet):
    """Advance over a run of characters
       that are NOT in charSet."""
    while (self._nextChar
            and self._nextChar not in charSet):
      self.consumeChar()

  def markStartOfLexeme(self):
    self._mark = self._point

  def getLexeme(self):
    return self._source[
        self._mark : self._point]

  # --- source position, for error messages ---

  def filename(self):
    return self._filename

  def scanLineNum(self):
    return self._lineNum

  def scanLinePos(self):
    """Index of the first character of
       the current line."""
    return self._source.rfind(
        '\n', 0, self._point) + 1

  def scanColNum(self):
    return self._point - self.scanLinePos() + 1

  def scanLineTxt(self):
    start = self.scanLinePos()
    end   = self._source.find('\n', start)
    if end == -1:
      return self._source[start:]
    return self._source[start:end]


# ---------------------------------------------------------------------------
# ScannerBase: one token of lookahead over the buffer
# ---------------------------------------------------------------------------

class ScannerBase(ABC):
  def __init__(self):
    self.buffer = ScannerBuffer()
    self._tok   = -1

  def reset(self, source, filename=''):
    self.buffer.reset(source, filename)
    self.consumeToken()                   # prime the one-token lookahead

  def peekToken(self):
    return self._tok

  def consumeToken(self):
    self._tok = self._scanNextToken()

  def expectToken(self, tok, message=None):
    """Consume the next token, which the
       grammar says must be tok, and
       return its lexeme.  Refuse
       anything else."""
    if self._tok != tok:
      raise ParseError(self.buffer, message
          or f'{self.tokenName(tok)} expected')
    lex = self.getLexeme()
    self.consumeToken()
    return lex

  def getLexeme(self):
    return self.buffer.getLexeme()

  def tokenName(self, tok):
    """What to call a token kind in an
       error message.  A subclass with
       names for its kinds overrides
       this."""
    return str(tok)

  @abstractmethod
  def _scanNextToken(self):
    """Scan past the next token, leaving
       the buffer with _mark at its first
       character and _point one past its
       last.  Return the token's kind."""
    ...


# ---------------------------------------------------------------------------
# ParseError: a syntax error that points at the source
# ---------------------------------------------------------------------------

class ParseError(Exception):
  def __init__(self, buf, message):
    super().__init__(self._format(
        buf.filename(), buf.scanLineNum(), buf.scanColNum(),
        buf.scanLineTxt(), message))

  @staticmethod
  def _format(filename, line, col, sourceLine,
              message):
    caret = ' ' * (col - 1) + '^'
    return (
        f'Syntax Error: "{filename}" '
        f'({line},{col})\n'
        f'{sourceLine}\n{caret}\n{message}')


# ---------------------------------------------------------------------------
# ParserBase: the grammar a concrete parser implements
# ---------------------------------------------------------------------------

class ParserBase(ABC):
  @abstractmethod
  def parse(self, source):
    """Parse source text and return an AST."""
    ...
