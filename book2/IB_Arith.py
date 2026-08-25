"""
IB_Arith - a parser for infix arithmetic, built on the ParserBase tool.

This is the worked example for the parsing chapter.  It parses ordinary infix
arithmetic, `1 + 2 * 3`, into the s-expressions the machine already runs:

    "1 + 2 * 3"   ->   ['+', 1, ['*', 2, 3]]   ->   lEval   ->   7

which is the whole front end, for a language that is not Lisp, feeding the same
back end.  The tree we drew in Book One, Chapter 1, and never had to build, we
build here, and then we run it.

Two parsers are shown, and they produce identical trees:

  * a STRATIFIED recursive-descent parser, where precedence lives in the shape
    of the grammar (expr calls term calls factor), one method per level; and

  * a PRATT parser, where precedence lives in a table of binding powers and one
    loop, which is the same idea folded up small once the levels multiply.

Neither one ever rewinds the scanner, and the base offers no way to: LL(1)
decides every step from the one token in front of it.

Run with: python IB_Arith.py
"""

from ParserBase  import LexerBase, ParserBase, ParseError
from IB_Core import lEval, global_env, lisp_str


# ---------------------------------------------------------------------------
# The scanner: characters into tokens.  A concrete LexerBase supplies token
# constants and one method, _scanNextToken; the buffer, the lookahead, and the
# source-position bookkeeping all come from the tool.
# ---------------------------------------------------------------------------

class Lexer(LexerBase):
  EOF_TOK    = 0
  INT_TOK    = 1
  PLUS_TOK   = 2
  MINUS_TOK  = 3
  STAR_TOK   = 4
  PERCENT_TOK= 5
  LPAREN_TOK = 6
  RPAREN_TOK = 7

  _SINGLE = {
      '+': PLUS_TOK, '-': MINUS_TOK, '*': STAR_TOK, '%': PERCENT_TOK,
      '(': LPAREN_TOK, ')': RPAREN_TOK,
}
  _DIGITS = '0123456789'

  def _scanNextToken(self):
    buf = self.buffer
    buf.consumePast(' \t\n\r')              # skip whitespace between tokens
    buf.markStartOfLexeme()

    ch = buf.peekChar()
    if ch == '':
      return Lexer.EOF_TOK
    if ch in Lexer._SINGLE:
      buf.consumeChar()
      return Lexer._SINGLE[ch]
    if ch in Lexer._DIGITS:
      buf.consumePast(Lexer._DIGITS)       # the whole run of digits
      return Lexer.INT_TOK
    raise ParseError(buf, f'unexpected character: {ch!r}')


# ---------------------------------------------------------------------------
# Parser 1: stratified recursive descent.  Precedence is the grammar's shape.
#
# The grammar, one rule per level of precedence, loosest first.  Written
# iteratively rather than left-recursively, so a rule consumes a token before
# it recurses:
#
#     expr   = term { ( "+" | "-" ) term }.
#     term   = factor { ( "*" | "%" ) factor }.
#     factor = INTEGER | "(" expr ")" | "-" factor.
#
#   expr   ->  term   (('+' | '-') term)*
#   term   ->  factor (('*' | '%') factor)*
#   factor ->  INT  |  '(' expr ')'  |  '-' factor
#
# Each rule is one method; a lower-precedence rule calls the next higher one,
# so multiplication, sitting deeper, binds tighter than addition without any
# precedence table at all.
# ---------------------------------------------------------------------------

_OP = {Lexer.PLUS_TOK: '+', Lexer.MINUS_TOK: '-',
        Lexer.STAR_TOK: '*', Lexer.PERCENT_TOK: '%'}

class Parser(ParserBase):
  def __init__(self):
    self._scanner = Lexer()

  def parse(self, source, filename=''):
    scn = self._scanner
    scn.reset(source, filename)
    tree = self._parseExpr()
    if scn.peekToken() != Lexer.EOF_TOK:
      raise ParseError(scn.buffer,
          'end of input expected')
    return tree

  def _parseExpr(self):
    scn  = self._scanner
    node = self._parseTerm()
    while scn.peekToken() in (
        Lexer.PLUS_TOK, Lexer.MINUS_TOK):
      op = _OP[scn.peekToken()]
      scn.consumeToken()
      node = [op, node, self._parseTerm()]
    return node

  def _parseTerm(self):
    scn  = self._scanner
    node = self._parseFactor()
    while scn.peekToken() in (
        Lexer.STAR_TOK, Lexer.PERCENT_TOK):
      op = _OP[scn.peekToken()]
      scn.consumeToken()
      node = [op, node, self._parseFactor()]
    return node

  def _parseFactor(self):
    scn = self._scanner
    tok = scn.peekToken()
    if tok == Lexer.INT_TOK:
      value = int(scn.getLexeme())
      scn.consumeToken()
      return value
    if tok == Lexer.LPAREN_TOK:
      scn.consumeToken()
      node = self._parseExpr()
      scn.expectToken(Lexer.RPAREN_TOK,
          "')' expected")
      return node
    # unary minus: -x is (- 0 x)
    if tok == Lexer.MINUS_TOK:
      scn.consumeToken()
      return ['-', 0, self._parseFactor()]
    raise ParseError(scn.buffer,
        'a number or ( expected')


# ---------------------------------------------------------------------------
# Parser 2: Pratt.  Precedence is a table of binding powers and one loop.
#
# The left binding power of each operator says how tightly it pulls on what is
# to its left.  To parse left-associatively, an operator recurses with a
# minimum one step ABOVE its own power, so the next operator of equal power
# stops and the left operand closes first.
# ---------------------------------------------------------------------------

class PrattParser(ParserBase):
  _LBP = {Lexer.PLUS_TOK: 1,
           Lexer.MINUS_TOK: 1,
           Lexer.STAR_TOK: 3,
           Lexer.PERCENT_TOK: 3}
  # unary minus binds tighter than *
  _PREFIX_BP = 5

  def __init__(self):
    self._scanner = Lexer()

  def parse(self, source, filename=''):
    scn = self._scanner
    scn.reset(source, filename)
    tree = self._parseExpr(0)
    if scn.peekToken() != Lexer.EOF_TOK:
      raise ParseError(scn.buffer,
          'end of input expected')
    return tree

  def _parseExpr(self, min_bp):
    lhs = self._parsePrefix()
    while True:
      tok = self._scanner.peekToken()
      lbp = PrattParser._LBP.get(tok)
      if lbp is None or lbp < min_bp:
        break
      self._scanner.consumeToken()
      # +1 -> left associative
      rhs = self._parseExpr(lbp + 1)
      lhs = [_OP[tok], lhs, rhs]
    return lhs

  def _parsePrefix(self):
    scn = self._scanner
    tok = scn.peekToken()
    if tok == Lexer.INT_TOK:
      value = int(scn.getLexeme())
      scn.consumeToken()
      return value
    if tok == Lexer.LPAREN_TOK:
      scn.consumeToken()
      node = self._parseExpr(0)
      scn.expectToken(Lexer.RPAREN_TOK,
          "')' expected")
      return node
    if tok == Lexer.MINUS_TOK:
      scn.consumeToken()
      bp = PrattParser._PREFIX_BP
      return ['-', 0, self._parseExpr(bp)]
    raise ParseError(scn.buffer,
        'a number or ( expected')


# ---------------------------------------------------------------------------
# The whole front end, feeding the same back end
# ---------------------------------------------------------------------------

def main():
  cases = [
      '1 + 2 * 3',
      '(1 + 2) * 3',
      '10 - 2 - 3',
      '2 * 3 + 4 * 5',
      '-2 * 3',
      '100 % 7 % 3',
      '2 * (3 + 4) - 1',
]
  strat = Parser()
  pratt = PrattParser()

  print(f'{"source":18} {"tree (s-expression)":28} value   both agree')
  print('-' * 72)
  for src in cases:
    t1 = strat.parse(src)
    t2 = pratt.parse(src)
    agree = 'yes' if t1 == t2 else 'NO'
    value = lisp_str(lEval(t1, global_env))
    print(f'{src:18} {lisp_str(t1):28} {value:5}   {agree}')
    assert t1 == t2, f'parsers disagree on {src!r}: {t1} vs {t2}'

  print('\n--- a syntax error points at the column ---\n')
  try:
    strat.parse('1 + * 3')
  except ParseError as e:
    print(e)


if __name__ == '__main__':
  main()
