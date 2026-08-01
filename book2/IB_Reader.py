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

Chapter 8 is where this file gets built, a scanner and a recursive-descent
reader, and where every line of it is explained.  You can use it long before
you read it; that is what a module is for.
"""

from IB_AST import lTrue, lFalse

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
      self._pos += 1
      self._tok = LPAREN
    elif ch == ')':
      self._pos += 1
      self._tok = RPAREN
    elif ch == "'":
      self._pos += 1
      self._tok = QUOTE
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
  """Classify an atom's text as an int, a boolean, or else a symbol (a string)."""
  try:
    return int( text )
  except ValueError:
    # the two booleans, minted here at the parse boundary (a name stays a
    # string)
    if text == '#t':
      return lTrue
    if text == '#f':
      return lFalse
    return text                             # a symbol -- a plain string


def parse( source ):
  scanner = Scanner( source )
  tree = read_object( scanner )
  if scanner.peek() != EOF:
    raise SyntaxError( 'unexpected trailing input' )
  return tree


def parse_all( source ):
  """Every expression in `source`, in order.  A file is a sequence of forms."""
  scanner = Scanner( source )
  forms = []
  while scanner.peek() != EOF:
    forms.append( read_object( scanner ) )
  return forms
