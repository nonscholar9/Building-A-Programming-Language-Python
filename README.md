# Building a Programming Language from Scratch (Python Edition)

Companion source code for the book
**_Building a Programming Language from Scratch (Python Edition)_**, in two books:

- **Book One, _From Parentheses to Bytecode_** — the machine, built six times over.
- **Book Two, _The Interpreter Front End_** — a second language, compiled onto it.

Everything here is plain Python, short enough to read start to finish.

## Requirements

Just **Python 3** (3.8 or newer). No third-party packages, no installation, no
build step. The files depend only on each other.

## Running the examples

Run any command from the repository root.

Each of Book One's files is a **complete interpreter on its own**, and prints a
short demo session when you run it:

```
python book1/IttyBittyLisp1.py
```

To type Lisp at an interactive prompt, run the REPL:

```
python book1/IttyBittyRepl.py
```

By default the REPL loads Chapter 1's evaluator. To point it at a later machine,
edit the one import line near the top of `book1/IttyBittyRepl.py` (swap
`IttyBittyLisp1` for `IttyBittyLisp2`, `IttyBittyLisp3`, and so on).

```
lisp> (+ 1 2)
3
```

Book Two's files are **not** a ladder like Book One's. They are parts of one
pipeline, and they import each other rather than replacing each other: the
machine is finished after Chapter 9 and never changes again, and each later
chapter adds a pass in front of it. The last file runs the whole thing:

```
python book2/IttyBittyPython.py
```

## The files

### Book One — the machine, one rung at a time

Each file is a snapshot: where you stand after that chapter.

| File | Chapter |
|------|---------|
| `book1/IttyBittyLisp1.py` | Chapter 1, the naive tree-walker |
| `book1/IttyBittyLisp2.py` | Chapter 2, closures |
| `book1/IttyBittyLisp2b_objects.py` | Interlude, closures as objects |
| `book1/IttyBittyLisp3.py` | Chapter 3, the looping evaluator |
| `book1/IttyBittyLisp4.py` | Chapter 4, the CEK machine |
| `book1/IttyBittyLisp5.py` | Chapter 5, the CEK machine, complete |
| `book1/IttyBittyLisp5b_callcc.py` | Interlude, continuations as values |
| `book1/IttyBittyLisp6.py` | Chapter 6, the bytecode VM |
| `book1/IttyBittyLisp7.py` | Chapter 7, memory and garbage collection |
| `book1/IttyBittyLisp8_parser.py` | Chapter 8, the parser |
| `book1/IttyBittyRepl.py` | the shared REPL introduced in Chapter 1 |

### Book Two — the pipeline, one pass at a time

Each file is a part, not a snapshot. They are named rather than numbered for
exactly that reason.

| File | Chapter |
|------|---------|
| `book2/IttyBittyBase.py` | the introduction: Book One's machine, with the challenges done |
| `book2/IttyBittyCore.py` | Chapter 9, the machine finished, and sealed |
| `book2/IttyBittyExpander.py` | Chapter 9, the expander |
| `book2/IttyBittyAnalyzer.py` | Chapter 10, the checker, and its ceiling |
| `book2/ParserBase.py` | Chapter 11, the reusable base for scanning and parsing |
| `book2/IttyBittyArith.py` | Chapter 12, infix arithmetic, the worked example |
| `book2/IttyBittyPython.ebnf` | Chapter 12, the IttyBittyPython grammar |
| `book2/IttyBittyPythonParser.py` | Chapters 11–12, the IttyBittyPython front end |
| `book2/IttyBittyPythonLower.py` | Chapter 13, lowering onto the machine |
| `book2/IttyBittyPythonReturn.py` | Chapter 14, early return via `call/cc` |
| `book2/IttyBittyPythonGen.py` | Chapter 15, generators |
| `book2/IttyBittyPython.py` | Chapter 15, the finished interpreter |

## License

The code in this repository is released under the **MIT License** (see
[`LICENSE`](LICENSE)). You are free to read it, run it, adapt it, and build on
it; please keep the copyright notice.

The text of the book itself is **not** part of this repository and is not covered
by that license.
