"""
IttyBittyLisp2b_objects - Object-oriented programs running on the Part 2 evaluator.

This is NOT a new evaluator.  It imports lEval and the global environment from
IttyBittyLisp2.py *unchanged* and feeds them ordinary object-oriented programs.
The point: the recursive evaluator of Part 2 -- the first one with closures --
already runs OO with no OO feature anywhere in it.

An object here is a closure:
  - its private fields  = the variables it closes over (`balance`, `limit`)
  - its methods         = the clauses of the body
  - message dispatch    = a `cond` on a quoted symbol tag
  - encapsulation       = lexical scope (the fields are unreachable except
                          through the body)
  - polymorphism        = two closures answering the same messages
  - inheritance         = one object closing over another and delegating

The dispatcher takes `(msg . args)`, so each message carries exactly the
arguments it needs: `(acct 'deposit 50)` and `(acct 'balance)` are both fine.
Delegation forwards with `apply`, so a wrapper never has to know how many
arguments the message it is passing on actually takes.

Run with: python IttyBittyLisp2b_objects.py
"""

from IttyBittyLisp2 import lEval, global_env, lisp_str


def run( expr ):
    result = lEval( expr, global_env )
    print( f'>>> {lisp_str( expr )}' )
    print( f'==> {lisp_str( result )}' )
    print()


def Q( sym ):
    # (quote sym) -- a literal symbol, used here as a message name.
    return ['quote', sym]


def main():

    # -----------------------------------------------------------------------
    # 1. An object is a closure: a message-passing bank account.
    #    make-account closes over `balance`; the returned closure dispatches
    #    on a message symbol and mutates the captured `balance` via set!.
    # -----------------------------------------------------------------------
    run( ['set!', 'make-account',
          ['lambda', ['balance'],
           ['lambda', ['msg', '.', 'args'],
            ['cond',
             [['=', 'msg', Q('deposit')],
              ['begin', ['set!', 'balance', ['+', 'balance', ['car', 'args']]], 'balance']],
             [['=', 'msg', Q('withdraw')],
              ['begin', ['set!', 'balance', ['-', 'balance', ['car', 'args']]], 'balance']],
             [['=', 'msg', Q('balance')],
              'balance'],
             ['else',
              ['print', Q('unknown-message')]]]]]] )

    run( ['set!', 'acct', ['make-account', 100]] )   # -> #<procedure (msg . args)>
    run( ['acct', Q('deposit'),  50] )    # -> 150
    run( ['acct', Q('withdraw'), 30] )    # -> 120
    run( ['acct', Q('balance')] )         # -> 120   no argument needed

    # A second account keeps its own books, independent of the first.
    run( ['set!', 'acct2', ['make-account', 500]] )
    run( ['acct2', Q('withdraw'), 200] )  # -> 300
    run( ['acct',  Q('balance')] )        # -> 120   (acct is unaffected)

    # -----------------------------------------------------------------------
    # 2. Polymorphism: a different object answering the SAME messages.
    #    An overdraft account permits balance to fall to -limit.  A client
    #    that only sends messages works on either kind, blind to the type.
    # -----------------------------------------------------------------------
    run( ['set!', 'make-overdraft-account',
          ['lambda', ['balance', 'limit'],
           ['lambda', ['msg', '.', 'args'],
            ['cond',
             [['=', 'msg', Q('deposit')],
              ['begin', ['set!', 'balance', ['+', 'balance', ['car', 'args']]], 'balance']],
             [['=', 'msg', Q('withdraw')],
              ['if', ['<', ['-', 'balance', ['car', 'args']], ['-', 0, 'limit']],
               ['print', Q('overdraft-refused')],
               ['begin', ['set!', 'balance', ['-', 'balance', ['car', 'args']]], 'balance']]],
             [['=', 'msg', Q('balance')],
              'balance'],
             ['else',
              ['print', Q('unknown-message')]]]]]] )

    run( ['set!', 'net-after-fee',
          ['lambda', ['account'],
           ['begin',
            ['account', Q('withdraw'), 5],    # a $5 fee, via the shared interface
            ['account', Q('balance')]]]] )

    run( ['set!', 'a1', ['make-account', 100]] )
    run( ['set!', 'a2', ['make-overdraft-account', 100, 50]] )
    run( ['net-after-fee', 'a1'] )    # -> 95
    run( ['net-after-fee', 'a2'] )    # -> 95   (same client, different object)

    # -----------------------------------------------------------------------
    # 3. Inheritance by delegation: a logging account closes over a plain
    #    account (its "parent"), adds behavior to `deposit`, and forwards
    #    every other message unchanged.  The captured `parent` IS the chain.
    #    apply does the forwarding, so the wrapper never counts the arguments.
    # -----------------------------------------------------------------------
    run( ['set!', 'make-logging-account',
          ['lambda', ['balance'],
           ['let', [['parent', ['make-account', 'balance']]],
            ['lambda', ['msg', '.', 'args'],
             ['cond',
              [['=', 'msg', Q('deposit')],
               ['begin', ['print', Q('logging-deposit')],
                         ['apply', 'parent', 'msg', 'args']]],
              ['else',
               ['apply', 'parent', 'msg', 'args']]]]]]] )   # delegate everything else

    run( ['set!', 'log-acct', ['make-logging-account', 200]] )
    run( ['log-acct', Q('deposit'),  25] )   # prints logging-deposit, -> 225
    run( ['log-acct', Q('withdraw'), 25] )   # delegated,             -> 200
    run( ['log-acct', Q('balance')] )        # delegated,             -> 200


if __name__ == '__main__':
    main()
