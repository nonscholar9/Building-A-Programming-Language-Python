# Building a Programming Language from Scratch in Python

Companion source code for the book
**_Building a Programming Language from Scratch in Python_**, in three books:

- **Book One, _The Runtime_.**  The machine, built four times over.
- **Book Two, _The Compiler_.**  Everything that stands in front of one.
- **Book Three, _The Tools_.**  The instruments that watch it run.

Everything here is plain Python, short enough to read start to finish.

## Requirements

Just **Python 3** (3.8 or newer).  No third-party packages, no installation, no
build step.  The files depend only on each other.

## Running the examples

Run any command from the repository root.  Every file prints a short demo
session when you run it:

```
python book1/IB_Lisp1.py
python book2/IB_Expander.py
python book3/IB_Tracer.py
```

To type Lisp at an interactive prompt, run Book One's REPL:

```
python book1/IB_Repl.py
```

```
lisp> (+ 1 2)
3
```

It drives Chapter 1's evaluator.  To point it at a later machine, change the
one import line near the top of `book1/IB_Repl.py`.  Every machine in Book One
exports the same `lEval`, `global_env` and `lisp_str`, so nothing else changes.
The one exception is `IB_Lisp4.py`: Chapter 4 shrinks the language to a handful
of forms while the CEK machine is built, and Chapter 5 hands the rest back.
Leave the prompt with `quit`, `exit`, or end-of-input.

## Book One: the machine, one rung at a time

Each file is a snapshot, where you stand at the end of that chapter, and each
one is a complete interpreter on its own.

| File | Chapter |
|------|---------|
| `book1/IB_Lisp1.py` | Chapter 1, the naive tree-walker |
| `book1/IB_Lisp2.py` | Chapter 2, the tree-walker complete |
| `book1/IB_Lisp2b_objects.py` | Interlude, closures as objects |
| `book1/IB_Lisp3.py` | Chapter 3, the tail-call looper |
| `book1/IB_Lisp4.py` | Chapter 4, the CEK machine, first half |
| `book1/IB_Lisp5.py` | Chapter 5, the CEK machine complete |
| `book1/IB_Lisp5b_callcc.py` | Interlude, continuations as values |
| `book1/IB_Lisp6.py` | Chapter 6, the CEK VM |
| `book1/IB_Lisp7.py` | Chapter 7, memory and garbage collection |
| `book1/IB_Reader.py` | the reader, which every machine from Chapter 2 imports |
| `book1/IB_AST.py` | the two booleans, which every machine imports |
| `book1/ParserBase.py` | the base the reader is built on, and Book Two with it |
| `book1/IB_Repl.py` | the shared REPL introduced in Chapter 1 |

## Book Two: the pipeline, one pass at a time

Book Two's files are not a ladder.  They are parts of one pipeline, and they
import each other rather than replacing each other.  The machine is
`book2/IB_Core.py`, and it does not change; each chapter adds a pass in front
of it.  The last file runs the whole thing, a small Python compiled onto that
machine:

```
python book2/miniPython.py
python book2/miniPython.py --vm
```

The second line runs the same program on the CEK VM instead of the CEK machine.

| File | Chapter |
|------|---------|
| `book2/IB_Core.py` | the machine you start from |
| `book2/IB_Expander.py` | Chapter 8, the expander |
| `book2/IB_Analyzer.py` | Chapter 9, the checker |
| `book2/IB_Addresser.py` | Chapter 10, where a variable lives |
| `book2/IB_Compiler.py` | Chapter 10, core forms to bytecode |
| `book2/IB_VM.py` | Chapter 10, the machine that runs the bytecode |
| `book2/IB_Optimizer.py` | Chapter 11, bytecode in, shorter bytecode out |
| `book2/IB_LispParser.py` | Chapter 12, the scanner and the reader, end to end |
| `book2/miniPython.atg` | Chapters 13 and 14, the grammar the front end is written from |
| `book2/miniPythonParser.py` | Chapters 13 and 14, the scanner and the parser |
| `book2/IB_Arith.py` | Chapter 14, infix arithmetic, the worked example |
| `book2/miniPythonLower.py` | Chapter 15, the lowering |
| `book2/miniPythonReturn.py` | Chapter 16, the lowering, with `return` |
| `book2/miniPythonGen.py` | Chapter 16, the lowering, with `yield` |
| `book2/miniPython.py` | Chapter 17, the finished interpreter |
| `book2/IB_Reader.py` | the reader, opened in Chapter 12 |
| `book2/ParserBase.py` | the base under every scanner and parser in the book |
| `book2/IB_AST.py` | the two booleans, which every part imports |

## Book Three: one tool per file

Every tool here reads the three registers of Chapter 5's CEK machine, with Book
Two's passes in front of it.  The last six files in the table are that machine,
carried over.

| File | Chapter |
|------|---------|
| `book3/IB_Printer.py` | Chapter 18, the printer |
| `book3/IB_Repl.py` | Chapter 18, the REPL |
| `book3/IB_Break.py` | Chapter 19, the backtrace and the break loop |
| `book3/IB_Tracer.py` | Chapter 20, the tracer |
| `book3/IB_Debugger.py` | Chapter 21, the debugger |
| `book3/IB_Debugger2.py` | Chapter 22, the debugger, part two |
| `book3/IB_Reverse.py` | Chapter 23, stepping backward |
| `book3/IB_Measure.py` | Chapter 24, the profiler |
| `book3/IB_Difftest.py` | Chapter 25, the differential tester |
| `book3/IB_Core.py` | the machine you start from, with its two openings |
| `book3/IB_Expander.py` | the expander, from Chapter 8 |
| `book3/IB_Analyzer.py` | the checker, from Chapter 9 |
| `book3/IB_Reader.py` | the reader, from Chapter 12 |
| `book3/ParserBase.py` | the base under the reader |
| `book3/IB_AST.py` | the two booleans, which every tool imports |

Running `book3/IB_Repl.py` prints Chapter 18's demonstrations rather than
opening a prompt.  For the prompt itself, from inside `book3/`:

```
python -c "import IB_Repl; IB_Repl.repl()"
```

## License

The code in this repository is released under the **MIT License** (see
[`LICENSE`](LICENSE)).  You are free to read it, run it, adapt it, and build on
it; please keep the copyright notice.

The text of the book itself is **not** part of this repository and is not
covered by that license.
