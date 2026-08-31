"""
IB_VM - the machine the compiler emits for.

This is Chapter 6's CEK VM with two changes, and both of them are changes the
compiler asked for rather than improvements to the machine for its own sake.

  1. VARIABLES ARE SLOTS.  Chapter 6's OP_VAR carried a name and looked it up
     at run time, walking outward through scopes until it found one that had
     the name.  The addresser works that walk out ahead of time, so a local
     variable arrives here as a pair of integers: how many frames out, and
     which slot.  A frame is a list, not a dictionary, and reading a local is
     an index rather than a search.  Globals keep their names, because the
     global scope is a place anyone can add a name to while the program runs.

  2. call/cc.  Chapter 5's interlude reified K on the CEK machine; the same
     move works here, and is if anything simpler.  A continuation is a
     snapshot of the frame stack, and invoking one is a return: restore the
     stack, put the value in V, and do exactly what OP_RET does.

Registers: pc (program counter), V (value), E (frame), K (frame stack).

Run with: python IB_VM.py
"""

from IB_AST import lTrue, lFalse, lisp_str

# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
VAL_CLOSURE = 1        # (VAL_CLOSURE, params, body_pc, frame)

FRAME_IF   = 0         # waiting on a test value
FRAME_CALL = 1         # a call, accumulating operator + operands
FRAME_RET  = 2         # a saved return address (pc) and its frame

# Opcodes.  Chapter 6's list, with OP_VAR and OP_SET split in two: one for a
# variable the compiler could place, one for a variable it could not.
OP_INT       = 0       # V = a number or boolean literal
OP_QUOTE     = 1       # V = the datum, unevaluated
OP_LOCAL     = 2       # V = frame[depth].slots[index]
OP_GLOBAL    = 3       # V = GLOBALS[name]
OP_LAM       = 4       # V = (VAL_CLOSURE, params, body_pc, E)
OP_JUMP      = 5       # pc = target
OP_APP_START = 6       # K.push((FRAME_CALL, [], E))
OP_APPLY_ARG = 7       # stash V in the frame, restore E
OP_CALL      = 8       # non-tail call: push FRAME_RET, bind, jump
OP_TCALL     = 9       # tail call: bind, jump (no FRAME_RET -> TCO)
OP_IF_START  = 10      # K.push((FRAME_IF, then_pc, else_pc, E))
OP_APPLY_IF  = 11      # pop FRAME_IF, pc = then_pc or else_pc
OP_RET       = 12      # pop FRAME_RET and resume, or halt
OP_SET_LOCAL = 13      # frame[depth].slots[index] = V
OP_SET_GLOBAL= 14      # GLOBALS[name] = V
OP_VAR       = 15      # V = the value bound to this NAME, by searching
OP_SET_VAR   = 16      # bind this NAME, by searching

OP_NAMES = ['INT', 'QUOTE', 'LOCAL', 'GLOBAL', 'LAM', 'JUMP',
            'APP_START', 'APPLY_ARG', 'CALL', 'TCALL', 'IF_START',
            'APPLY_IF', 'RET', 'SET_LOCAL', 'SET_GLOBAL',
            'VAR', 'SET_VAR']

# Which pair of those the compiler emits, and therefore what a frame holds.
# It is one flag because it has to be: placing a variable is an agreement
# between the compiler and the machine, and neither can keep it alone.  Set it
# to False and the compiler stops addressing, the frames go back to holding
# names, and the machine goes back to searching.  That is the measurement in
# [SS]11.7, and it is the only reason the searching path is still here.
ADDRESSED = True


# ---------------------------------------------------------------------------
# A frame is a list of slots
# ---------------------------------------------------------------------------
#
# Chapter 6's Environment was a dictionary and a pointer outward.  This is the
# same shape with the dictionary gone: the names went into the compiler, and
# what is left at run time is the values, in the order the parameter list put
# them.  `outer` is still there, because a closure still has to reach the
# frames around the one it was made in.

class Frame:
  __slots__ = ('slots', 'outer')

  def __init__(self, slots, outer):
    self.slots = slots
    self.outer = outer


class _Unbound:
  """A slot a call never supplied a value for.  Reading one is the error that
    an unbound name used to be."""
  def __repr__(self):
    return '#<unbound>'

UNBOUND = _Unbound()


def unbound(name):
  raise NameError(f'Unbound variable: {name}')


def bind_slots(params, args):
  """The frame a call builds, in the order the addresser assumed.

    A dotted list (a . rest) fills the named slots and puts whatever is left
    over in the last one, so the frame is the same size for every call.
    """
  if '.' in params:
    dot   = params.index('.')
    named = list(args[:dot])
    named += [UNBOUND] * (dot - len(named))
    slots = named + [list(args[dot:])]
  else:
    slots = list(args[:len(params)])
    gaps  = len(params) - len(slots)
    slots += [UNBOUND] * gaps
  if ADDRESSED:
    return slots
  return dict(zip(frame_names(params), slots))


def frame_names(params):
  """The names a parameter list declares, in slot order."""
  if '.' in params:
    dot   = params.index('.')
    named = list(params[:dot])
    return named + [params[dot + 1]]
  return list(params)


# ---------------------------------------------------------------------------
# call/cc
# ---------------------------------------------------------------------------

class Continuation:
  """A snapshot of the frame stack.  Invoking it is a return that goes
    somewhere other than where this call came from."""

  __slots__ = ('stack',)

  def __init__(self, stack):
    self.stack = stack

  def __repr__(self):
    return '#<continuation>'


class _CallCC:
  def __repr__(self):
    return '#<primitive call/cc>'

CALLCC = _CallCC()


class _Apply:
  def __repr__(self):
    return '#<primitive apply>'

applyFn = _Apply()


# ---------------------------------------------------------------------------
# The VM
# ---------------------------------------------------------------------------
#
# STEPS counts instructions executed, and it is the only honest way to compare
# two versions of a program on this machine: it is the same number on every
# computer, and it does not move when the machine is busy.

STEPS = [0]


def run_vm(prog, pc=0, frame=None):
  V = None
  E = frame
  K = []
  steps = 0

  while True:
    instr = prog[pc]
    op    = instr[0]
    steps += 1

    if op == OP_INT or op == OP_QUOTE:
      V = instr[1]
      pc += 1

    elif op == OP_LOCAL:                # two integers, no search
      _, depth, index = instr
      f = E
      while depth:            # a countdown, not a range object:
        f = f.outer           # building one costs more than the walk
        depth -= 1
      V = f.slots[index]
      if V is UNBOUND:
        raise NameError('Unbound variable')
      pc += 1

    elif op == OP_GLOBAL:
      try:                     # one dictionary operation, not two:
        V = GLOBALS[instr[1]]  # asking then fetching is asking twice
      except KeyError:
        unbound(instr[1])
      pc += 1

    elif op == OP_LAM:                  # capture the frame in the closure
      _, params, body_pc = instr
      V = (VAL_CLOSURE, params, body_pc, E)
      pc += 1

    elif op == OP_JUMP:
      pc = instr[1]

    elif op == OP_SET_LOCAL:
      _, depth, index = instr
      f = E
      while depth:
        f = f.outer
        depth -= 1
      f.slots[index] = V
      pc += 1

    elif op == OP_SET_GLOBAL:
      GLOBALS[instr[1]] = V
      pc += 1

    elif op == OP_APP_START:
      K.append((FRAME_CALL, [], E))
      pc += 1

    elif op == OP_APPLY_ARG:
      _, doneList, frm = K.pop()
      K.append((FRAME_CALL,
                doneList + [V], frm))
      E  = frm
      pc += 1

    elif op == OP_CALL or op == OP_TCALL:
      _, doneList, callerFrame = K.pop()
      fn, *args = doneList

      # apply is a value spliced at the call site, exactly as on the CEK
      # machine.  Both sides read the OLD args; do not split this in two.
      while fn is applyFn:
        fn, args = (args[0],
                    list(args[1:-1])
                    + list(args[-1]))

      if fn is CALLCC:
        # (call/cc f) is a call of f on the stack as it stands.  A non-tail
        # call/cc pushes its return address FIRST, so the snapshot contains
        # it; after that the two cases are the same call.
        if op == OP_CALL:
          K.append((FRAME_RET, pc + 1,
                    callerFrame))
          op = OP_TCALL
        fn   = args[0]
        args = [Continuation(list(K))]

      if isinstance(fn, Continuation):
        # A return to somewhere else: restore the stack and land the value.
        K = list(fn.stack)
        V = args[0]
        if not K:
          STEPS[0] += steps
          return V
        _, pc, E = K.pop()

      elif callable(fn):                # a primitive
        V = fn(args)
        if op == OP_CALL:
          pc += 1
        elif not K:
          STEPS[0] += steps
          return V
        else:
          _, pc, E = K.pop()

      else:                             # a closure
        _, params, body_pc, cloFrame = fn
        if op == OP_CALL:
          K.append((FRAME_RET, pc + 1,
                    callerFrame))
        E  = Frame(bind_slots(params, args),
                   cloFrame)
        pc = body_pc

    elif op == OP_VAR:                  # the same variable, searched for
      name = instr[1]
      f = E
      while f is not None and name not in f.slots:
        f = f.outer
      if f is None:
        try:
          V = GLOBALS[name]
        except KeyError:
          unbound(name)
      else:
        V = f.slots[name]
      pc += 1

    elif op == OP_SET_VAR:
      name = instr[1]
      f = E
      while f is not None and name not in f.slots:
        f = f.outer
      if f is None:
        GLOBALS[name] = V
      else:
        f.slots[name] = V
      pc += 1

    elif op == OP_IF_START:
      _, then_pc, else_pc = instr
      K.append((FRAME_IF, then_pc,
                else_pc, E))
      pc += 1

    elif op == OP_APPLY_IF:             # #f is the only false value
      _, then_pc, else_pc, frm = K.pop()
      E  = frm
      pc = (then_pc if V is not lFalse
            else else_pc)

    elif op == OP_RET:
      if not K:
        STEPS[0] += steps
        return V
      _, pc, E = K.pop()


# ---------------------------------------------------------------------------
# Primitives.  The same set the CEK machine starts with, in a plain dict this
# time, because a global scope is exactly that: names, looked up by name.
# ---------------------------------------------------------------------------

def lisp_print(args):
  print(lisp_str(args[0]))
  return args[0]

def lisp_mul(args):
  result = 1
  for x in args:
    result *= x
  return result

def lisp_bool(b):
  return lTrue if b else lFalse

def lisp_set_nth(args):
  lst, n, newValue = args
  lst[n] = newValue
  return newValue


GLOBALS = {
    '+':     lambda args: sum(args),
    '-':     lambda args: args[0] - args[1],
    '*':     lisp_mul,
    '%':     lambda args: args[0] % args[1],
    '=':     lambda args: lisp_bool(args[0] == args[1]),
    '<':     lambda args: lisp_bool(args[0] <  args[1]),
    '>':     lambda args: lisp_bool(args[0] >  args[1]),
    '<=':    lambda args: lisp_bool(args[0] <= args[1]),
    '>=':    lambda args: lisp_bool(args[0] >= args[1]),
    'print': lisp_print,

    'car':   lambda args: args[0][0],
    'cdr':   lambda args: args[0][1:],
    'cons':  lambda args: [args[0]] + args[1],
    'list':  lambda args: list(args),
    'null?': lambda args: lisp_bool(args[0] == []),
    'nth':   lambda args: args[0][args[1]],
    'set-nth!': lisp_set_nth,

    'not':   lambda args: lisp_bool(args[0] is lFalse),

    'call/cc':                        CALLCC,
    'call-with-current-continuation': CALLCC,
    'apply':                          applyFn,
}


# ---------------------------------------------------------------------------
# Reading the code the compiler produced
# ---------------------------------------------------------------------------

def disassemble(prog, start=0, end=None):
  end = len(prog) if end is None else end
  for pc in range(start, end):
    instr = prog[pc]
    args  = ' '.join(lisp_str(a) if isinstance(a, list)
                     else str(a) for a in instr[1:])
    print(f'  {pc:4}  {OP_NAMES[instr[0]]:10} {args}')


def main():
  print('IB_VM is the machine; IB_Compiler is what feeds it.')
  print('Run python IB_Compiler.py to see both at work.')


if __name__ == '__main__':
  main()
