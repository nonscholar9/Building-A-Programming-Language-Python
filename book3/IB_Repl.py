"""
IB_Repl - Chapter 18, second half.  The last black box.

Chapter 1 handed you a REPL and did not open it, and every machine in the
volume has been fed by it since.  Here is what is inside, and it is four
stages with a loop around them:

    read  ->  expand  ->  check  ->  run  ->  print

That line is the whole of Books One and Two in one function.  `evaluate`
below is it, and every tool in the rest of Book Three calls it rather than
calling the machine directly, because a debugger that skipped the checker
would be debugging a different language from the one you type at.

The one real problem a REPL has is telling an INCOMPLETE line from a WRONG
one.  Type `(+ 1 2` and it should wait for more.  Type `(+ 1 2))` and it
should complain.  Both are the same kind of thing to a parser that only
answers yes or no.

The obvious way to tell them apart is to count parentheses in the text, and
the obvious way is wrong, because a parenthesis is not always a parenthesis:

    (list #\\()          a parenthesis that is a character literal
    (+ 1 2) ; )         a parenthesis inside a comment

Counting characters gets both of those wrong.  What gets them right is the
scanner from Chapter 12, which already knows what a comment is and what `#\\`
does, and which will hand out tokens to anyone who asks.  So the REPL does
not do its own lexing.  It asks the language's own scanner, which is the
whole lesson: an instrument that reimplements a stage of the front end will
disagree with the front end.

Run with: python IB_Repl.py
"""

from IB_Core import (MachineError, lEval,
                     global_env)
from IB_Reader import Scanner, parse
from IB_Expander import expand
from IB_Analyzer import LispError, analyze
from IB_Printer import (flat, primitive_names,
                        show)


# ---------------------------------------------------------------------------
# The pipeline
# ---------------------------------------------------------------------------

def prepare(source):
  """read -> expand -> check.  Everything but the running."""
  form = parse(source) if isinstance(
      source, str) else source
  return analyze(expand(form))


def evaluate(source, env=None):
  """read -> expand -> check -> run.  One form."""
  return lEval(prepare(source),
               env or global_env)


# ---------------------------------------------------------------------------
# Complete, incomplete, or wrong
# ---------------------------------------------------------------------------
#
# Drive the reader's own scanner over the text and count the two structural
# tokens.  Anything the scanner swallowed on the way -- a comment, a
# character literal -- never reaches the count, which is the point.

def bracket_depth(source):
  """(depth, ok).  ok is False once a ) has closed one too many."""
  scanner = Scanner()
  scanner.reset(source, '<repl>')
  depth = 0
  while True:
    tok = scanner.peekToken()
    if tok == Scanner.EOF_TOK:
      return depth, True
    if tok == Scanner.LPAREN_TOK:
      depth = depth + 1
    elif tok == Scanner.RPAREN_TOK:
      depth = depth - 1
      if depth < 0:
        return depth, False
    scanner.consumeToken()


def naive_depth(source):
  """The way everybody writes it first, and it is wrong twice over."""
  return (source.count('(')
          - source.count(')'))


def state_of(source):
  depth, ok = bracket_depth(source)
  if not ok:
    return 'wrong'
  if depth > 0:
    return 'incomplete'
  if not source.strip():
    return 'empty'
  return 'complete'


# ---------------------------------------------------------------------------
# The loop
# ---------------------------------------------------------------------------

def repl(env=None, read=input):
  env = env or global_env
  names = primitive_names(env)
  pending = ''
  while True:
    prompt = 'lisp> ' if not pending else '...   '
    try:
      line = read(prompt)
    except (EOFError, KeyboardInterrupt):
      print()
      return
    if not pending and line.strip() in (
        'quit', 'exit'):
      return
    pending = (pending + '\n' + line
               if pending else line)
    state = state_of(pending)
    if state == 'empty':
      pending = ''
      continue
    if state == 'incomplete':
      continue
    source, pending = pending, ''
    try:
      print(flat(evaluate(source, env), names))
    except LispError as err:
      print('checker: ' + str(err))
    except MachineError as err:
      print('error: ' + str(err))
    except Exception as err:
      print('error: ' + str(err))


def scripted(lines):
  pending = list(lines)
  def read(prompt):
    if not pending:
      raise EOFError
    line = pending.pop(0)
    print(prompt + line)
    return line
  return read


# ---------------------------------------------------------------------------
# The chapter's demonstrations
# ---------------------------------------------------------------------------

TRICKY = [
    '(+ 1 2)',
    '(+ 1 2',
    '(+ 1 2))',
    '(list #\\()',
    '(+ 1 2) ; )',
    ')',
    '',
]


def depth_demo():
  print('--- counting characters against '
        'asking the scanner ---')
  print('  {:<16} {:>6} {:>6}  {}'.format(
      'input', 'naive', 'real', 'verdict'))
  for src in TRICKY:
    depth, ok = bracket_depth(src)
    print('  {:<16} {:>6} {:>6}  {}'.format(
        repr(src), naive_depth(src),
        depth if ok else 'closed',
        state_of(src)))
  print('  They disagree on two rows, '
        'and on both of them the')
  print('  scanner is right, because it '
        'is the one the reader uses.')


def session_demo():
  print()
  print('--- a session, including a form '
        'typed over three lines ---')
  repl(read=scripted([
      '(+ 1 2)',
      '(set! fact',
      '  (lambda (n)',
      '    (if (= n 0) 1 (* n (fact (- n 1))))))',
      '(fact 5)',
      '(+ 1 2) ; a comment with a )',
      '(lambda (a a) a)',
      '(+ 1 unbound)',
      'quit']))


def printer_demo():
  print()
  print('--- and the printer, on the '
        'function that was just defined ---')
  closure = global_env.lookup('fact')
  show(['lambda', 'n'] if closure is None
       else ['set!', 'fact',
             ['lambda', closure[1],
              closure[2][0]]])


def main():
  depth_demo()
  session_demo()
  printer_demo()


if __name__ == '__main__':
  main()
