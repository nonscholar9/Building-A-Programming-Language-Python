"""
IB_Printer - Chapter 18, first half.  Printing a value.

`lisp_str` has been in the volume since Chapter 1, and it does one thing: it
puts a value on one line.  That was enough while the values were small.  It
stops being enough the moment a tool has to show you a program, because a
function body on one line is a wall of parentheses.

So this chapter's printer answers a different question.  Not "what does this
value look like" but "what does it look like in the space I have".  Two rules
and it is finished:

  * If the whole form fits in the width, print it flat.  Nothing is gained by
    breaking up something you can already read.

  * Otherwise print the head, then every remaining part on its own line,
    indented one step.  A few heads keep their first part on the head line,
    because `(lambda` on a line of its own tells you nothing and
    `(lambda (x y)` tells you everything.

The width defaults to 48 columns, which is the width this book's listings are
set to, so anything the printer produces will fit on the page you are reading.

There is a second thing worth fixing here while we are in the printer.
`lisp_str` renders every primitive as `#<primitive>`, because a Python
function does not know what it was bound to.  A backtrace full of
`#<primitive>` is not much use.  The environment knows the names, so the
printer can ask it once and remember.

Run with: python IB_Printer.py
"""

from IB_AST import lisp_str
from IB_Core import global_env


WIDTH = 48

# Heads that keep their first part on the head line.
KEEP_ONE = {'lambda', 'let', 'set!', 'if',
            'define'}


# ---------------------------------------------------------------------------
# Giving the primitives their names back
# ---------------------------------------------------------------------------

def primitive_names(env=None):
  """id(value) -> the name it is bound to in the globals."""
  env = env or global_env
  out = {}
  for name in env._global._bindings:
    value = env._global._bindings[name]
    if callable(value) or isinstance(value,
                                     tuple):
      out.setdefault(id(value), name)
  return out


def flat(value, names=None):
  """lisp_str, with a primitive shown by name when we know one."""
  if names is None:
    return lisp_str(value)
  if isinstance(value, list):
    parts = ' '.join(flat(v, names)
                     for v in value)
    return '(' + parts + ')'
  known = names.get(id(value))
  if known is not None:
    if callable(value):
      return '#<primitive ' + known + '>'
    return '#<procedure ' + known + '>'
  return lisp_str(value)


# ---------------------------------------------------------------------------
# The layout
# ---------------------------------------------------------------------------

def lay_out(form, width=WIDTH, indent=0,
            names=None):
  """A list of lines, each already indented."""
  pad = ' ' * indent
  one = flat(form, names)
  if (not isinstance(form, list) or not form
      or indent + len(one) <= width):
    return [pad + one]

  rest = list(form[1:])
  head = pad + '(' + flat(form[0], names)
  if (isinstance(form[0], str)
      and form[0] in KEEP_ONE and rest):
    head = head + ' ' + flat(rest[0], names)
    rest = rest[1:]
  lines = [head]
  for part in rest:
    lines.extend(lay_out(part, width,
                         indent + 2, names))
  lines[-1] = lines[-1] + ')'
  return lines


def pp(form, width=WIDTH, indent=0,
       names=None):
  return '\n'.join(lay_out(form, width,
                           indent, names))


def show(form, width=WIDTH, indent=0,
         names=None):
  print(pp(form, width, indent, names))


# ---------------------------------------------------------------------------
# The chapter's demonstration
# ---------------------------------------------------------------------------

FORM = ['begin',
        ['set!', 'fact',
         ['lambda', ['n'],
          ['if', ['=', 'n', 0], 1,
           ['*', 'n',
            ['fact', ['-', 'n', 1]]]]]],
        ['fact', 5]]


def main():
  print('--- one line, which is all '
        'lisp_str can do ---')
  print(lisp_str(FORM))
  print()
  print('--- the same form, laid out to '
        'fit 48 columns ---')
  show(FORM)
  print()
  print('--- and to fit 28, which is what '
        'a phone gives you ---')
  show(FORM, width=28)
  print()
  print('--- a primitive, before and '
        'after asking the environment ---')
  plus = global_env.lookup('+')
  print('  ' + lisp_str(plus))
  print('  ' + flat(plus, primitive_names()))


if __name__ == '__main__':
  main()
