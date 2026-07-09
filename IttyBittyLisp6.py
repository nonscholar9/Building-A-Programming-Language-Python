"""
IttyBittyLisp6 - A Bytecode VM.

The CEK machine of IttyBittyLisp4 re-walks the AST and re-decides "which
transition runs next" on every single step.  But for a fixed program that
decision never changes -- `(lambda (x) x)` is always a lambda.  So why make it
over and over at run time?

A bytecode VM makes it ONCE, at compile time.  Give every CEK transition a
number -- an *opcode* -- and walk the AST a single time, emitting a flat list of
these numbered instructions.  At run time there is no AST left to dispatch on and
no EVAL/APPLY state flag: the loop just reads the next opcode and does it.  That
is all a bytecode VM is -- the CEK machine with its dispatch precomputed.

This toy compiles the same pure lambda calculus + if as IttyBittyLisp4 (a number
is true unless it is 0), so the new idea -- compilation -- stands alone, exactly
as #4 isolated the machine.  Compiling the full language of #5 works the same
way, with more opcodes.

Two registers carry over from the CEK machine -- E (environment) and K
(continuation stack) -- and one is new:

  pc - the program counter: the index of the next instruction to run.  It
       replaces C; where the CEK machine held an expression, the VM holds a
       position in the instruction stream.

K gains one new frame kind, FRAME_RET, that the CEK machine did not need.  The
CEK machine could always find "what to do after this call returns" by looking at
the surrounding AST.  A flat instruction stream has no surrounding tree, so the
return address must be stored explicitly -- on K.  A tail call (OP_TCALL) stores
no return address, so K stays flat across tail calls and TCO is still structural.

Run with: python IttyBittyLisp6.py
"""

# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
VAL_CLOSURE = 1                 # a closure value: (VAL_CLOSURE, param, body_pc, env)

# Continuation frame kinds.
FRAME_IF   = 0
FRAME_ARG  = 1
FRAME_CALL = 2
FRAME_RET  = 3                  # NEW: a saved return address (pc)

# Opcodes -- one per CEK transition, plus OP_JUMP for layout.
OP_INT       = 0   # V = n
OP_VAR       = 1   # V = E.lookup(name)
OP_LAM       = 2   # V = (VAL_CLOSURE, param, body_pc, E)
OP_JUMP      = 3   # pc = target
OP_APP_START = 4   # K.push((FRAME_ARG, E))
OP_APPLY_ARG = 5   # pop FRAME_ARG, restore E, K.push((FRAME_CALL, V))
OP_CALL      = 6   # non-tail call: push FRAME_RET, bind param, jump to body
OP_TCALL     = 7   # tail call: bind param, jump to body (NO FRAME_RET -> TCO)
OP_IF_START  = 8   # K.push((FRAME_IF, then_pc, else_pc, E))
OP_APPLY_IF  = 9   # pop FRAME_IF, restore E, pc = then_pc or else_pc
OP_RET       = 10  # pop FRAME_RET and resume there, or halt if K is empty

_OP_NAMES = ['INT', 'VAR', 'LAM', 'JUMP', 'APP_START', 'APPLY_ARG',
             'CALL', 'TCALL', 'IF_START', 'APPLY_IF', 'RET']


# ---------------------------------------------------------------------------
# Environment: a linked chain of scopes (same class as IttyBittyLisp2-5)
# ---------------------------------------------------------------------------

class Environment:
    def __init__( self, parent=None, bindings=None ):
        self._bindings = dict(bindings or {})
        self._parent   = parent
        self._global   = parent._global if parent else self

    def lookup( self, name ):
        scope = self
        while scope:
            if name in scope._bindings:
                return scope._bindings[name]
            scope = scope._parent
        raise NameError( f'Unbound variable: {name}' )


# ---------------------------------------------------------------------------
# The compiler: walk the AST once, emit a flat instruction list
# ---------------------------------------------------------------------------
#
# `tail` tracks tail position: a leaf or closure in tail position is followed by
# OP_RET, and a call in tail position becomes OP_TCALL rather than OP_CALL.  A
# function body is laid out inline right after the OP_LAM that builds its
# closure, with an OP_JUMP in front so the closure-building path skips over it.

def compile_expr( expr, out, tail ):
    if isinstance( expr, int ):             # a number literal
        out.append( (OP_INT, expr) )
        if tail: out.append( (OP_RET,) )

    elif isinstance( expr, str ):           # a variable
        out.append( (OP_VAR, expr) )
        if tail: out.append( (OP_RET,) )

    elif expr[0] == 'lambda':               # ['lambda', param, body]
        lam_idx  = len(out); out.append( None )   # reserve OP_LAM
        jump_idx = len(out); out.append( None )   # reserve OP_JUMP (skip the body)
        body_pc  = len(out)
        compile_expr( expr[2], out, tail=True )   # a body is always in tail position
        past_body = len(out)
        out[lam_idx]  = (OP_LAM, expr[1], body_pc)
        out[jump_idx] = (OP_JUMP, past_body)
        if tail: out.append( (OP_RET,) )

    elif expr[0] == 'if':                   # ['if', test, then, else]
        if_idx = len(out); out.append( None )     # reserve OP_IF_START
        compile_expr( expr[1], out, tail=False )  # the test is never in tail position
        out.append( (OP_APPLY_IF,) )
        then_pc = len(out)
        compile_expr( expr[2], out, tail=tail )   # then inherits our tail context
        if not tail:
            then_jump_idx = len(out); out.append( None )   # skip the else branch
        else_pc = len(out)
        compile_expr( expr[3], out, tail=tail )   # else inherits our tail context
        if not tail:
            out[then_jump_idx] = (OP_JUMP, len(out))
        out[if_idx] = (OP_IF_START, then_pc, else_pc)

    else:                                   # [fn, arg] -- an application
        out.append( (OP_APP_START,) )
        compile_expr( expr[0], out, tail=False )  # fn  -- not in tail position
        out.append( (OP_APPLY_ARG,) )
        compile_expr( expr[1], out, tail=False )  # arg -- not in tail position
        out.append( (OP_TCALL,) if tail else (OP_CALL,) )


def compile_program( expr ):
    out = []
    compile_expr( expr, out, tail=True )
    return out


# ---------------------------------------------------------------------------
# The VM: a flat instruction loop, dispatching only on the integer opcode
# ---------------------------------------------------------------------------
#
# Registers:  pc (program counter), V (value), E (environment), K (frame stack).

def run_vm( prog ):
    pc = 0
    V  = None
    E  = Environment()
    K  = []

    while True:
        instr = prog[pc]
        op    = instr[0]

        if op == OP_INT:
            V = instr[1]
            pc += 1

        elif op == OP_VAR:
            V = E.lookup( instr[1] )
            pc += 1

        elif op == OP_LAM:                  # capture E inside the closure
            V = (VAL_CLOSURE, instr[1], instr[2], E)
            pc += 1

        elif op == OP_JUMP:
            pc = instr[1]

        elif op == OP_APP_START:            # remember E for the argument
            K.append( (FRAME_ARG, E) )
            pc += 1

        elif op == OP_APPLY_ARG:            # fn value is in V; remember it
            E = K.pop()[1]
            K.append( (FRAME_CALL, V) )
            pc += 1

        elif op == OP_CALL:                 # non-tail: save return pc, enter body
            closure = K.pop()[1]
            K.append( (FRAME_RET, pc + 1) )
            E  = Environment( parent=closure[3], bindings={ closure[1]: V } )
            pc = closure[2]                 # body_pc

        elif op == OP_TCALL:                # tail: enter body, push NO return frame
            closure = K.pop()[1]
            E  = Environment( parent=closure[3], bindings={ closure[1]: V } )
            pc = closure[2]

        elif op == OP_IF_START:             # remember both branch pcs and E
            K.append( (FRAME_IF, instr[1], instr[2], E) )
            pc += 1

        elif op == OP_APPLY_IF:             # V is the test; 0 is false, else true
            frame = K.pop()
            E  = frame[3]
            pc = frame[2] if V == 0 else frame[1]

        elif op == OP_RET:                  # end of a body
            if not K:
                return V                    # top level: done
            pc = K.pop()[1]                 # resume the caller


def lEval( expr ):
    return run_vm( compile_program( expr ) )


# ---------------------------------------------------------------------------
# Helpers and demo
# ---------------------------------------------------------------------------

def lisp_str( val ):
    if isinstance( val, list ):
        return '(' + ' '.join( lisp_str(x) for x in val ) + ')'
    if isinstance( val, tuple ):            # a closure: (VAL_CLOSURE, param, body_pc, env)
        return '#<procedure (' + val[1] + ')>'
    return str( val )


def disassemble( prog ):
    for pc, instr in enumerate( prog ):
        args = ' '.join( str(a) for a in instr[1:] )
        print( f'  {pc:3}  {_OP_NAMES[instr[0]]:10} {args}' )


def run( expr ):
    print( '>>> ' + lisp_str( expr ) )
    print( '==> ' + lisp_str( lEval( expr ) ) )
    print()


def main():
    # First, show what compilation produces for a small program.
    prog = compile_program( [['lambda', 'x', 'x'], 7] )
    print( 'bytecode for ((lambda (x) x) 7):' )
    disassemble( prog )
    print()

    run( 42 )                                              # 42
    run( [['lambda', 'x', 'x'], 7] )                       # 7
    run( [[['lambda', 'x', ['lambda', 'y', 'x']], 3], 9] ) # 3
    run( ['if', 1, 100, 200] )                             # 100
    run( ['if', 0, 100, 200] )                             # 200
    run( [['lambda', 'f', ['f', 3]], ['lambda', 'x', 'x']] )  # 3


if __name__ == '__main__':
    main()
