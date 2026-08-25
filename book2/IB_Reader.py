"""
IB_Reader - source text in, AST out.  The one reader every machine shares.

Chapter 1 showed the thing this module exists to make cheap: a Lisp program
already *is* a tree, so writing `['+', 1, 2]` in Python is writing the program.
That is worth seeing once.  It is not worth typing for the rest of a book, and
it is certainly not worth typing when you want to try something of your own.

So from Chapter 2 on, every machine reads its examples from source:

    from IB_Reader import parse
    lEval( parse( '(+ 1 2)' ), global_env )

Nothing about the machines changes.  The reader hands them exactly the trees
they were handed before, which is the point: the AST is still the real input,
and now something else types it.

The scanner and the reader are the two subclasses ParserBase.py asks for: a
Lexer that supplies one method, _scanNextToken, and a Reader that supplies the
grammar.  The cursor, the one token of lookahead, and the line and column an
error points at all come from the base.  What is left is the part that is
Lisp's alone, and there is very little of it, because a parenthesised program
states its own tree.  The parsing chapter is where this file gets built, and
where every line of it is explained.  You can use it long before you read it;
that is what a module is for.
"""

from ParserBase import (LexerBase, ParserBase,
                        ParseError)
from IB_AST import lTrue, lFalse

# A delimiter ends the atom currently being scanned.  Everything that is not a
# delimiter continues it, so the scanner needs no table of "symbol characters".
DELIMITERS = set(" \t\n\r()';")
WHITESPACE = " \t\n\r"


# ---------------------------------------------------------------------------
# The scanner: characters into tokens.  The structural tokens ( ) ' each stand
# alone; every name and number arrives as one ATOM whose text the reader
# classifies later.
# ---------------------------------------------------------------------------

class Lexer(LexerBase):
  EOF_TOK    = 0
  LPAREN_TOK = 1
  RPAREN_TOK = 2
  QUOTE_TOK  = 3
  ATOM_TOK   = 4

  _SINGLE = {'(': LPAREN_TOK,
             ')': RPAREN_TOK,
             "'": QUOTE_TOK}

  def _scanNextToken(self):
    buf = self.buffer
    self._skipSpaceAndComments()
    buf.markStartOfLexeme()

    ch = buf.peekNextChar()
    if ch == '':
      return Lexer.EOF_TOK
    if ch in Lexer._SINGLE:
      buf.consume()
      return Lexer._SINGLE[ch]
    # anything else begins an atom
    buf.consumeUpTo(DELIMITERS)
    # '#\' takes one more character,
    # whatever it is: #\( #\; #\space
    if buf.getLexeme() == '#\\':
      buf.consume()
    return Lexer.ATOM_TOK

  def _skipSpaceAndComments(self):
    buf = self.buffer
    while True:
      buf.consumePast(WHITESPACE)
      if buf.peekNextChar() != ';':
        return          # a ';' comment runs to end of line
      buf.consumeUpTo('\n')


# ---------------------------------------------------------------------------
# The reader: recursive descent over the token stream
# ---------------------------------------------------------------------------

class Reader(ParserBase):
  def __init__(self):
    self._scanner = Lexer()

  def parse(self, source, filename=''):
    """The one expression in `source`."""
    scn = self._scanner
    scn.reset(source, filename)
    tree = self._readObject()
    if scn.peekToken() != Lexer.EOF_TOK:
      raise ParseError(scn.buffer,
          'unexpected trailing input')
    return tree

  def parseAll(self, source, filename=''):
    """Every expression in `source`, in
       order.  A file is a sequence of
       forms."""
    scn = self._scanner
    scn.reset(source, filename)
    forms = []
    while scn.peekToken() != Lexer.EOF_TOK:
      forms.append(self._readObject())
    return forms

  def _readObject(self):
    """Read one complete expression from
       the front of the token stream."""
    scn = self._scanner
    tok = scn.peekToken()
    if tok == Lexer.ATOM_TOK:
      text = scn.getLexeme()
      scn.consume()
      return atom(text)
    if tok == Lexer.LPAREN_TOK:
      return self._readList()
    if tok == Lexer.QUOTE_TOK:      # 'expr -> (quote expr)
      scn.consume()
      return ['quote', self._readObject()]
    if tok == Lexer.RPAREN_TOK:
      raise ParseError(scn.buffer,
          'unexpected )')
    raise ParseError(scn.buffer,
        'unexpected end of input')

  def _readList(self):
    scn = self._scanner
    scn.consume()          # discard the opening '('
    result = []
    while scn.peekToken() not in (
        Lexer.RPAREN_TOK, Lexer.EOF_TOK):
      result.append(self._readObject())
    # the closing ')' must be there
    scn.expect(Lexer.RPAREN_TOK,
        'unterminated list, expected )')
    return result


def atom(text):
  """Classify an atom's text as an int, a boolean, or else a symbol (a string)."""
  try:
    return int(text)
  except ValueError:
    # the two booleans, minted here at the parse boundary (a name stays a
    # string)
    if text == '#t':
      return lTrue
    if text == '#f':
      return lFalse
    return text                             # a symbol -- a plain string


def parse(source, filename=''):
  return Reader().parse(source, filename)


def parse_all(source, filename=''):
  return Reader().parseAll(source, filename)
