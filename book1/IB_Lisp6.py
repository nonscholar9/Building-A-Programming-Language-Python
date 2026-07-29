"""
IB_Lisp6 - A Bytecode VM.

The CEK machine of IB_Lisp5 re-walks the AST and re-decides "which
transition runs next" on every single step.  But for a fixed program that
decision never changes -- `(lambda (x) x)` is always a lambda.  So why make it
over and over at run time?

A bytecode VM makes it ONCE, at compile time.  Give every CEK transition a
number -- an *opcode* -- and walk the AST a single time, emitting a flat list of
these numbered instructions.  At run time there is no AST left to dispatch on and
no EVAL/APPLY state flag: the loop just reads the next opcode and does it.  That
is all a bytecode VM is -- the CEK machine with its dispatch precomputed.

It runs the whole language IB_Lisp5 runs: #t/#f with Scheme truthiness (#f is
the only false value -- 0 is true), quote, set!, begin, let, cond, and, or,
multi-argument lambdas and applications, rest parameters, apply, and the
primitives.  Precomputing the dispatch does not cost the language anything, and
that is the claim this toy is here to make good on.

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

Run with: python IB_Lisp6.py
"""

from IB_AST import LBoolean, lTrue, lFalse

# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------
VAL_CLOSURE = 1                 # a closure: (VAL_CLOSURE, params, body_pc, env)

# Continuation frame kinds.  FRAME_ARG accumulates the operator and every
# operand of one call, exactly as IB_Lisp5's did; IB_Lisp4's separate
# FRAME_CALL was only ever needed when a call had exactly one argument.
FRAME_IF  = 0                   # waiting on a test value
FRAME_ARG = 1                   # a call, accumulating operator + operands
FRAME_RET = 2                   # NEW: a saved return address (pc) and its env

# Opcodes -- one per CEK transition, plus OP_JUMP for layout.
OP_INT       = 0   # V = n (or a boolean literal; both are constants)
OP_VAR       = 1   # V = E.lookup(name)
OP_LAM       = 2   # V = (VAL_CLOSURE, params, body_pc, E)
OP_JUMP      = 3   # pc = target
OP_APP_START = 4   # K.push((FRAME_ARG, [], E))
OP_APPLY_ARG = 5   # stash V in the frame, restore E for the next operand
OP_CALL      = 6   # non-tail call: push FRAME_RET, bind params, jump to body
OP_TCALL     = 7   # tail call: bind params, jump to body (NO FRAME_RET -> TCO)
OP_IF_START  = 8   # K.push((FRAME_IF, then_pc, else_pc, E))
OP_APPLY_IF  = 9   # pop FRAME_IF, restore E, pc = then_pc or else_pc
OP_RET       = 10  # pop FRAME_RET and resume there, or halt if K is empty
OP_SET       = 11  # E.set(name, V)
OP_QUOTE     = 12  # V = the datum, unevaluated

_OP_NAMES = ['INT', 'VAR', 'LAM', 'JUMP', 'APP_START', 'APPLY_ARG',
             'CALL', 'TCALL', 'IF_START', 'APPLY_IF', 'RET', 'SET', 'QUOTE']


# ---------------------------------------------------------------------------
# Environment: a linked stack of scopes (same class as IB_Lisp2-5)
# ---------------------------------------------------------------------------

class Environment:
    def __init__( self, outer=None, bindings=None ):
        self._bindings = dict(bindings or {})
        self._outer   = outer
        self._global   = outer._global if outer else self

    def lookup( self, name ):
        env = self
        while env:
            if name in env._bindings:
                return env._bindings[name]
            env = env._outer
        raise NameError( f'Unbound variable: {name}' )

    def set( self, name, value ):
        # Walk to the innermost scope that already owns the name.
        env = self
        while env:
            if name in env._bindings:
                env._bindings[name] = value
                return value
            env = env._outer
        # Name not found anywhere -- create it in the global scope.
        self._global._bindings[name] = value
        return value


# ---------------------------------------------------------------------------
# Binding a call's arguments
# ---------------------------------------------------------------------------
#
# A dotted parameter list `(first . rest)` is written here as the plain list
# ['first', '.', 'rest'], so the dot is just an element to look for.

def bind_params( params, args ):
    if '.' in params:
        dot   = params.index( '.' )
        named = params[:dot]
        rest  = params[dot + 1]
        bindings = dict( zip( named, args ) )
        bindings[rest] = list( args[len(named):] )
        return bindings
    return dict( zip( params, args ) )


# ---------------------------------------------------------------------------
# The compiler: walk the AST once, emit a flat instruction list
# ---------------------------------------------------------------------------
#
# `tail` tracks tail position: a leaf or closure in tail position is followed by
# OP_RET, and a call in tail position becomes OP_TCALL rather than OP_CALL.  A
# function body is laid out inline right after the OP_LAM that builds its
# closure, with an OP_JUMP in front so the closure-building path skips over it.
#
# Four forms emit no opcodes of their own.  let, cond, and, or are rewrites: the
# compiler turns each into forms it already knows and compiles that instead,
# which is the same move IB_Lisp5 made in its EVAL loop, now made once rather
# than on every pass.

# A reserved parameter name `or` binds its first value to, so a true result is
# returned without evaluating it twice.  It is not a legal source name; making a
# trick like this hygienic in general is Chapter 9's expander.
_OR_TMP = '%or-tmp%'


def compile_body( forms, out, tail ):
    for f in forms[:-1]:
        compile_expr( f, out, tail=False )      # value computed, then overwritten
    compile_expr( forms[-1], out, tail=tail )


def compile_expr( expr, out, tail ):
    if isinstance( expr, (int, LBoolean) ):  # a number or boolean -> a constant
        out.append( (OP_INT, expr) )
        if tail: out.append( (OP_RET,) )

    elif isinstance( expr, str ):           # a variable
        out.append( (OP_VAR, expr) )
        if tail: out.append( (OP_RET,) )

    elif expr[0] == 'quote':                # ['quote', datum] -> the datum itself
        out.append( (OP_QUOTE, expr[1]) )
        if tail: out.append( (OP_RET,) )

    elif expr[0] == 'lambda':               # ['lambda', [params], *body]
        lam_idx  = len(out); out.append( None )   # reserve OP_LAM
        jump_idx = len(out); out.append( None )   # reserve OP_JUMP (skip the body)
        body_pc  = len(out)
        _, params, *body = expr
        compile_body( body, out, tail=True )      # a body is always in tail position
        out[lam_idx]  = (OP_LAM, params, body_pc)
        out[jump_idx] = (OP_JUMP, len(out))
        if tail: out.append( (OP_RET,) )

    elif expr[0] == 'if':                   # ['if', test, then, else]
        _, condExpr, thenExpr, elseExpr = expr
        if_idx = len(out); out.append( None )     # reserve OP_IF_START
        compile_expr( condExpr, out, tail=False ) # the test is never in tail position
        out.append( (OP_APPLY_IF,) )
        then_pc = len(out)
        compile_expr( thenExpr, out, tail=tail )  # then inherits our tail context
        if not tail:
            then_jump_idx = len(out); out.append( None )   # skip the else branch
        else_pc = len(out)
        compile_expr( elseExpr, out, tail=tail )  # else inherits our tail context
        if not tail:
            out[then_jump_idx] = (OP_JUMP, len(out))
        out[if_idx] = (OP_IF_START, then_pc, else_pc)

    elif expr[0] == 'set!':                 # ['set!', name, valueExpr]
        _, name, valExpr = expr
        compile_expr( valExpr, out, tail=False )
        out.append( (OP_SET, name) )
        if tail: out.append( (OP_RET,) )

    elif expr[0] == 'begin':                # ['begin', *forms]
        compile_body( expr[1:], out, tail )

    elif expr[0] == 'let':                  # ['let', ((name init)...), *body]
        _, bindingPairs, *body = expr
        names = [ pair[0] for pair in bindingPairs ]
        inits = [ pair[1] for pair in bindingPairs ]
        compile_expr( [['lambda', names] + list( body )] + inits, out, tail )

    elif expr[0] == 'cond':                 # ['cond', (test result)...]
        clauses = expr[1:]
        if not clauses:
            compile_expr( lFalse, out, tail )
        elif clauses[0][0] == 'else':
            compile_expr( clauses[0][1], out, tail )
        else:                               # a chain of ifs, peeled one clause
            compile_expr( ['if', clauses[0][0], clauses[0][1],
                           ['cond'] + list( clauses[1:] )], out, tail )

    elif expr[0] == 'and':                  # ['and', *forms] -- short-circuits
        forms = expr[1:]
        if not forms:
            compile_expr( lTrue, out, tail )     # (and) is true
        elif len( forms ) == 1:
            compile_expr( forms[0], out, tail )
        else:                               # (if a (and rest...) #f)
            compile_expr( ['if', forms[0], ['and'] + list( forms[1:] ), lFalse],
                          out, tail )

    elif expr[0] == 'or':                   # ['or', *forms] -- short-circuits
        forms = expr[1:]
        if not forms:
            compile_expr( lFalse, out, tail )    # (or) is false
        elif len( forms ) == 1:
            compile_expr( forms[0], out, tail )
        else:                               # bind a once, return it if true
            compile_expr( [['lambda', [_OR_TMP],
                            ['if', _OR_TMP, _OR_TMP, ['or'] + list( forms[1:] )]],
                           forms[0]], out, tail )

    else:                                   # [fn, *args] -- an application
        out.append( (OP_APP_START,) )
        for sub in expr:
            compile_expr( sub, out, tail=False )  # operator and operands alike
            out.append( (OP_APPLY_ARG,) )
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

PROG = []                       # the program, appended to as expressions arrive


def run_vm( prog, pc=0, env=None ):
    V  = None
    E  = global_env if env is None else env
    K  = []

    while True:
        instr = prog[pc]
        op    = instr[0]

        if op == OP_INT:
            V = instr[1]
            pc += 1

        elif op == OP_QUOTE:                # the datum, never evaluated
            V = instr[1]
            pc += 1

        elif op == OP_VAR:
            V = E.lookup( instr[1] )
            pc += 1

        elif op == OP_LAM:                  # capture E inside the closure
            _, params, body_pc = instr
            V = (VAL_CLOSURE, params, body_pc, E)
            pc += 1

        elif op == OP_JUMP:
            pc = instr[1]

        elif op == OP_SET:                  # V is set!'s result; it flows on
            E.set( instr[1], V )
            pc += 1

        elif op == OP_APP_START:            # start collecting operator + operands
            K.append( (FRAME_ARG, [], E) )
            pc += 1

        elif op == OP_APPLY_ARG:            # stash V, restore E for the next one
            _, doneList, env = K.pop()
            K.append( (FRAME_ARG, doneList + [V], env) )
            E  = env
            pc += 1

        elif op == OP_CALL or op == OP_TCALL:
            _, doneList, callerEnv = K.pop()
            fn, *args = doneList

            # apply is a value: (apply g x ... lst) is a call of g on x ... plus
            # the elements of lst.  Splice here, at the call site, the same way
            # IB_Lisp5 does; the loop lets (apply apply ...) resolve.
            while fn is APPLY:
                fn, args = args[0], list( args[1:-1] ) + list( args[-1] )

            if callable( fn ):              # primitive: compute it, flow it on
                V = fn( args )
                if op == OP_CALL:
                    pc += 1
                elif not K:                 # a primitive ended the program
                    return V
                else:                       # a tail call still returns
                    _, pc, E = K.pop()
            else:                           # closure: bind params, enter the body
                _, params, body_pc, clo_env = fn
                if op == OP_CALL:
                    K.append( (FRAME_RET, pc + 1, callerEnv) )
                E  = Environment( outer=clo_env,
                                  bindings=bind_params( params, args ) )
                pc = body_pc

        elif op == OP_IF_START:             # remember both branch pcs and E
            _, then_pc, else_pc = instr
            K.append( (FRAME_IF, then_pc, else_pc, E) )
            pc += 1

        elif op == OP_APPLY_IF:             # V is the test; #f is the only false value
            _, then_pc, else_pc, env = K.pop()
            E  = env
            pc = then_pc if V is not lFalse else else_pc

        elif op == OP_RET:                  # end of a body
            if not K:
                return V                    # top level: done
            _, pc, E = K.pop()              # resume the caller, in the caller's scope


def lEval( expr, env=None ):
    """Evaluate one expression on the running machine.

    The compiled code is appended to PROG rather than replacing it, because a
    closure remembers the address of its own body.  Throw the program away
    between expressions and every closure made by an earlier one points into
    code that is no longer there.
    """
    start = len( PROG )
    compile_expr( expr, PROG, tail=True )
    return run_vm( PROG, start, env )


# ---------------------------------------------------------------------------
# Primitives and global environment (the same set as IB_Lisp5)
# ---------------------------------------------------------------------------

def lisp_print( args ):
    print( args[0] )
    return args[0]       # returned, so print composes inside a larger expression

def lisp_mul( args ):    # variadic product; (*) is 1, the multiplicative identity
    result = 1
    for x in args:
        result *= x
    return result

# apply is a value the machine recognizes at the call site, not a special form
# and not an ordinary primitive: it must open a scope and run a body, which a
# Python primitive cannot do.
class _Apply:
    pass

APPLY = _Apply()

globalBindings = {
    '+':     lambda args: sum( args ),                          # variadic; (+) is 0
    '-':     lambda args: args[0] - args[1],
    '*':     lisp_mul,                                          # variadic; (*) is 1
    '%':     lambda args: args[0] % args[1],
    '=':     lambda args: lTrue if args[0] == args[1] else lFalse,
    '<':     lambda args: lTrue if args[0] <  args[1] else lFalse,
    '>':     lambda args: lTrue if args[0] >  args[1] else lFalse,
    '<=':    lambda args: lTrue if args[0] <= args[1] else lFalse,
    '>=':    lambda args: lTrue if args[0] >= args[1] else lFalse,
    'print': lisp_print,

    # `not` computes from an already-evaluated argument, so it is an ordinary
    # primitive.  `and` and `or` cannot be: they must skip evaluating an
    # operand, which only a special form can do.
    'not':   lambda args: lTrue if args[0] is lFalse else lFalse,

    # The list primitives.  A Lisp list is a Python list, so each is one line.
    'car':   lambda args: args[0][0],
    'cdr':   lambda args: args[0][1:],
    'cons':  lambda args: [args[0]] + args[1],
    'list':  lambda args: list( args ),
    'null?': lambda args: lTrue if args[0] == [] else lFalse,

    # apply, above, is bound to the sentinel the machine watches for.
    'apply': APPLY,
}
global_env = Environment( bindings=globalBindings )


# ---------------------------------------------------------------------------
# Helpers and demo
# ---------------------------------------------------------------------------

def lisp_str( val ):
    if isinstance( val, list ):
        return '(' + ' '.join( lisp_str(x) for x in val ) + ')'
    if isinstance( val, tuple ):            # (VAL_CLOSURE, params, body_pc, env)
        return '#<procedure (' + ' '.join( val[1] ) + ')>'
    if val is APPLY:
        return '#<primitive apply>'
    if callable( val ):
        return '#<primitive>'
    return str( val )


def disassemble( prog ):
    for pc, instr in enumerate( prog ):
        args = ' '.join( lisp_str(a) if isinstance(a, list) else str(a)
                         for a in instr[1:] )
        print( f'  {pc:3}  {_OP_NAMES[instr[0]]:10} {args}' )


def run( expr ):
    print( '>>> ' + lisp_str( expr ) )
    print( '==> ' + lisp_str( lEval( expr ) ) )
    print()


def main():
    # First, show what compilation produces for a small program.
    prog = compile_program( [['lambda', ['x'], 'x'], 7] )
    print( 'bytecode for ((lambda (x) x) 7):' )
    disassemble( prog )
    print()

    run( ['+', ['-', 10, 7], 2] )                       # 5
    run( ['+', ['print', 10], 5] )                      # prints 10, ==> 15

    run( ['set!', 'x', ['*', 6, 7]] )                   # 42
    run( 'x' )                                          # 42

    run( ['set!', 'square', ['lambda', ['n'], ['*', 'n', 'n']]] )
    run( ['square', 5] )                                # 25

    run( ['let', [['a', 3], ['b', 4]],
          ['+', ['*', 'a', 'a'], ['*', 'b', 'b']]] )    # 25

    run( ['begin', ['set!', 'y', 1], ['set!', 'y', ['+', 'y', 9]], 'y'] )   # 10

    run( ['if', 0, 100, 200] )                          # 100  (0 is TRUE in Scheme)
    run( ['quote', ['a', 'b', 'c']] )                   # (a b c)

    # Tail-recursive countdown: TCO keeps K bounded, so 100,000 iterations run
    # without growing the continuation stack.
    run( ['set!', 'countdown',
          ['lambda', ['n'],
           ['if', ['=', 'n', 0], 0, ['countdown', ['-', 'n', 1]]]]] )
    run( ['countdown', 100000] )                        # 0

    # Chapter 1's forms, on the compiled machine.
    run( ['car', ['quote', ['a', 'b', 'c']]] )          # a
    run( ['cons', 1, ['quote', [2, 3]]] )               # (1 2 3)
    run( ['cond', [['<', 2, 1], ['quote', 'no']],
                  ['else', ['quote', 'yes']]] )         # yes
    run( ['and', lFalse, ['print', 'unreached']] )      # #f, and nothing prints
    run( ['or', lFalse, ['quote', 'fallback']] )        # fallback

    # Chapter 2's: a rest parameter, and apply spreading a list back out.
    run( ['set!', 'tally',
          ['lambda', ['label', '.', 'nums'],
           ['list', 'label', ['apply', '+', 'nums']]]] )
    run( ['tally', ['quote', 'total']] )                # (total 0)
    run( ['tally', ['quote', 'total'], 1, 2, 3] )       # (total 6)
    run( ['apply', '+', 10, 20, ['quote', [1, 2, 3]]] ) # 36

    # A tail apply is still a tail call: K stays bounded here too.
    run( ['set!', 'countdown2',
          ['lambda', ['n', '.', 'rest'],
           ['cond', [['=', 'n', 0], 0],
                    ['else', ['apply', 'countdown2', ['list', ['-', 'n', 1]]]]]]] )
    run( ['countdown2', 100000] )                       # 0


if __name__ == '__main__':
    main()
