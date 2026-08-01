"""
IB_Lisp8_parser -- An S-expression scanner and reader for the IttyBitty Lisp.

Turns a source string into the nested Python list AST that lEval (from
IB_Lisp1.py) evaluates directly.  Two stages, the same split real
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
separated by spaces (see the challenges in Chapter 8).

What is here is the smallest version of a general tool.  The cursor, the one
token of lookahead, and the recursive descent over the token stream are what
every hand-written front end is made of; Book Two packages exactly those, plus
line and column tracking for error messages, as a ParserBase.py that a language
subclasses.  This file is that design cut down to what one Lisp needs and
written out by hand, which is why it fits in a chapter.

Run with: python IB_Lisp8_parser.py
"""

from IB_AST import lTrue, lFalse

# The scanner and the reader themselves now live in IB_Reader.py, because every
# machine from Chapter 2 on imports them.  This file is the rest of Chapter 8:
# the reader wired to an evaluator, which is the whole pipeline end to end.
from IB_Reader import Scanner, read_object, read_list, atom, parse
from IB_Reader import EOF, LPAREN, RPAREN, QUOTE, ATOM, DELIMITERS


# ---------------------------------------------------------------------------
# The minimal evaluator (from IB_Lisp1) to complete the pipeline
# ---------------------------------------------------------------------------

def lEval(expr, env):
  if isinstance(expr, str):        # symbol -> look it up
    return env[expr]
  elif not isinstance(expr, list):  # number or boolean -> return unchanged
    return expr
  elif len(expr) == 0:
    return []

  head = expr[0]

  if head == 'if':
    _, condExpr, thenExpr, elseExpr = expr
    condVal = lEval(condExpr, env)
    return lEval(elseExpr if condVal is lFalse else thenExpr, env)

  elif head == 'begin':
    _, *forms = expr
    for sub in forms[:-1]:
      lEval(sub, env)
    return lEval(forms[-1], env)

  elif head == 'set!':
    _, name, valExpr = expr
    val = lEval(valExpr, env)
    env[name] = val
    return val

  elif head == 'quote':
    return expr[1]

  fn, *args = [lEval(sub, env) for sub in expr]
  return fn(args)


global_env = {
    '+':  lambda args: args[0] + args[1],
    '-':  lambda args: args[0] - args[1],
    '*':  lambda args: args[0] * args[1],
    '=':  lambda args: lTrue if args[0] == args[1] else lFalse,
    '<':  lambda args: lTrue if args[0] <  args[1] else lFalse,
}


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

def lisp_str(val):
  # Render a value in Lisp surface syntax (the `ast` line below is left as a
  # Python list on purpose, to show the reader's output structure).
  if isinstance(val, list):
    parts = ' '.join(lisp_str(x) for x in val)
    return '(' + parts + ')'
  if callable(val):
    return '#<primitive>'
  return str(val)


def scan_all(source):
  # Drain a fresh scanner into a list of (kind, lexeme) pairs, so the chapter
  # can show the token stream the reader consumes.
  scanner = Scanner(source)
  tokens = []
  while scanner.peek() != EOF:
    tokens.append((scanner.peek(), scanner.lexeme()))
    scanner.consume()
  return tokens


def run(source):
  print(f'  source:  {source}')
  ast = parse(source)
  print(f'  ast:     {ast}')
  print(f'  result:  {lisp_str( lEval( ast, global_env ) )}')
  print()


def main():
  # Show the token stream for a non-trivial expression.
  src = "(if (= a 2) (+ a 1) (- a 1))"
  print('Scanner output (the token stream the reader consumes):')
  print(f'  source:  {src}')
  print(f'  tokens:  {scan_all( src )}')
  print()

  # Show that the AST is identical to what the IttyBitty examples wrote by hand.
  print('Reader output (this is the AST lEval operates on):')
  print(f'  source:  {src}')
  print(f'  ast:     {parse( src )}')
  print()

  # Full pipeline: source string -> parse -> lEval -> result.
  print('Full pipeline: source string -> parse -> lEval -> result')
  global_env['a'] = 2
  run("(+ 1 2)")
  run("(if (= a 2) (+ a 1) (- a 1))")
  run("(set! b (* 6 7))")
  run("b")

  # Quote shorthand: 'x is reader syntax for (quote x).
  print("Quote shorthand: 'x is reader syntax for (quote x)")
  run("'(a b c)")
  run("(quote (a b c))")


if __name__ == '__main__':
  main()
