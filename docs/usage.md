# Usage

[scope](scope.md) explains what the results mean and what the tool does not cover.

The exit code is 0 on success. It is 1 when `can-use` or `issues` match nothing.
`can-use` also exits 1 when the query matches more than one feature. The exit code is 2 for bad arguments, including
an unknown `--compiler`, and for missing data.

## offload can-use

```
offload can-use [--list] [--format text|json] [FEATURE]
```

`FEATURE` is a feature id or part of one, such as `clause.map.present`. If it matches several features, they are
listed and the exit code is 1. Each cell is `correct`, `unsupported` or `unknown`, or `-` where the compiler does not
run on that machine.

```
offload can-use --list map
offload can-use clause.map.present
```

## offload issues

```
offload issues [--compiler cce|afar|nvhpc|gcc|cce19|...] [--kind incorrect|unsupported]
               [--stage compile|link|run] [--status open|fixed|changed|not-reproduced]
               [--legality confirmed|supported|contested|unconfirmed] [--show ID] [--format text|json] [QUERY...]
```

Every query word must appear in the id, title, constructs or messages. Without `--show`, the command lists the
matches with the compilers affected and how each fails: refused at compile or link time, a compiler crash, a hang,
a crash or error at run time, or a wrong answer. `--stage` keeps the issues that fail at compile, link or run
time. `--legality` keeps the issues with that verdict of the independent legality review (the website's method
page, "Legality review"); the JSON output carries it as `legality`. `--show ID` prints one issue in full, with the
spec reference, the legality verdict and its reason, the state per compiler and the reproducer source.

```
offload issues dist_schedule
offload issues --compiler nvhpc --kind unsupported
offload issues --stage link
offload issues --legality contested
offload issues --show cce-c-dist-schedule-segv
```
